"""Executor for Spatial Test 003 (the frozen SPATIAL_PLAN_003.json ONLY). Sequential single requests, no retries, STOP at the first non-normal / unparseable / schema-invalid outcome.
The live-call hold is suspended only around each single request and restored on success, failure, exception, SIGINT/SIGTERM and interpreter exit.
Usage (live):  run_live_003.py --authorized-plan-sha256 <full hash>          Usage (offline mechanics test): --loopback-port N --hold-dir DIR --evidence-dir DIR
No secret is ever printed or stored. Evidence is write-once."""
import argparse, atexit, hashlib, json, pathlib, shutil, signal, sys, time
HERE = pathlib.Path(__file__).resolve().parent; WS = HERE.parent; EXP = pathlib.Path.home() / "ifi-amd-inference-experiment"
sys.path.insert(0, str(EXP)); sys.path.insert(0, str(HERE)); sys.path.insert(0, str(WS))
from ext import amd_client, pipeline, streaming           # noqa: E402  (client used ONLY here, never by the bridge)
import build_plan as BP, score as S                       # noqa: E402
from oracle3 import Oracle3                               # noqa: E402
H = lambda b: hashlib.sha256(b).hexdigest()
EXPECTED = {"model": "DeepSeek-V4.1-Flash", "stream": True, "max_tokens": 400, "temperature": 0.0, "response_format": {"type": "json_object"}, "extra_parameters": None, "no_progress_abort_s": 90, "wall_abort_s": 150, "retries": 0, "parallel_requests": 0}
CFG = {"source_doc_id": "dp001_ansi_b_v2_drawings", "source_sha256": BP.PDF_SHA, "page_number": 2, "sheet": "C101", "crop_rect_norm_page": [0.03, 0.095, 0.645, 0.69], "enclosure_stroke_min_pt": 1.9, "edge_to_interior_threshold_in": 1.5}


def preflight(plan_path, authorized):
    raw = json.loads(plan_path.read_text()); stored = raw.pop("plan_sha256_excluding_this_field"); re = H(json.dumps(raw, sort_keys=True).encode())
    assert stored == re, "plan content does not match its stored hash"
    assert authorized is None or authorized == stored, "authorized hash differs from the stored plan hash"
    raw["plan_sha256_excluding_this_field"] = stored
    for k, v in EXPECTED.items(): assert raw["request_settings"][k] == v, f"request setting {k} changed"
    assert raw["source"]["sha256"] == BP.PDF_SHA == H(BP.PDF.read_bytes()), "source PDF identity"
    for f, h in raw["frozen_files_sha256"].items():
        if f != "spatial_plan/build_plan.py": assert H((WS / f).read_bytes()) == h, f"{f} changed since the plan was frozen"
    assert H(BP.SYSTEM.encode()) == raw["prompt"]["system_sha256"]
    for c in raw["crops"]:
        assert H((WS / c["image_file"]).read_bytes()) == c["image_sha256"], c["crop_id"]
        spec = next(x for x in BP.CROPS if x["crop_id"] == c["crop_id"]); assert H(BP.USER.replace("__ORDER__", BP.ORDERS[spec["ask"]]).encode()) == c["user_prompt_sha256"], "prompt changed"
        assert [spec["region_norm_page"], spec["ask"]] == [c["region_norm_page"], c["ask"]]
    u = BP.USER
    for leak in ("G1", "G2", "G3", "COURT", "Court", "interior divider B"): assert leak not in u.replace("a rounded label containing the letter G and a number", ""), f"prompt leaks {leak}"
    o = Oracle3(BP.PDF, CFG); vis = {}
    try:
        for c in raw["crops"]:
            r = c["region_norm_page"]; inside = lambda p: r[0] <= p[0] <= r[2] and r[1] <= p[1] <= r[3]
            for t in c["oracle_preflight_not_shown_to_model"]["type_tags"]:
                lt = o.leader_target(t); assert lt["verdict"] == "LEADER_TARGET_DERIVED" and lt["element"] == c["oracle_preflight_not_shown_to_model"]["type_tag_leader_targets"][t]["element"], "oracle pre-flight changed"
                assert inside(lt["leader_far_end_norm"]) and inside(lt["diamond_norm"][:2]) and inside(lt["diamond_norm"][2:]), f"leader of {t} not fully inside crop {c['crop_id']}"
                vis[f"{c['crop_id']}:{t}"] = {"leader_far_end_inside_crop": True, "diamond_inside_crop": True, "target": lt["element"], "side": lt.get("enclosure_side"), "distance_in": lt["distance_in"]}
    finally: o.close()
    return raw, vis


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--authorized-plan-sha256"); ap.add_argument("--loopback-port", type=int); ap.add_argument("--hold-dir"); ap.add_argument("--evidence-dir"); ap.add_argument("--preflight-only", action="store_true")
    a = ap.parse_args(); test = a.loopback_port is not None
    plan, vis = preflight(HERE / "SPATIAL_PLAN_003.json", a.authorized_plan_sha256 if not test else None)
    ev = pathlib.Path(a.evidence_dir) if a.evidence_dir else HERE / "runs_v3"; hold_dir = pathlib.Path(a.hold_dir) if a.hold_dir else EXP
    HOLD, SUSP = hold_dir / "LIVE_CALLS_DISABLED", hold_dir / "LIVE_CALLS_DISABLED.suspended_for_one_request"
    assert HOLD.exists() and not SUSP.exists(), "the live-call hold must be in force before starting"
    hold_text = HOLD.read_text(); ev.mkdir(parents=True, exist_ok=True)
    pre = {"plan_sha256": plan["plan_sha256_excluding_this_field"], "plan_file_sha256": H((HERE / "SPATIAL_PLAN_003.json").read_bytes()), "executor_sha256": H(pathlib.Path(__file__).read_bytes()), "harness_version": pipeline.harness_version(),
           "frozen_files_sha256": plan["frozen_files_sha256"], "crop_hashes": {c["crop_id"]: c["image_sha256"] for c in plan["crops"]}, "leader_visibility_in_crops": vis, "hold_in_force": True, "loopback_test": test,
           "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "oracle_expectations_frozen": {c["crop_id"]: c["oracle_preflight_not_shown_to_model"] for c in plan["crops"]}}
    if not test: (ev / "PREFLIGHT.json").write_text(json.dumps(pre, indent=1)) if not (ev / "PREFLIGHT.json").exists() else None
    print(json.dumps({"preflight": "PASS", "plan_sha256": pre["plan_sha256"], "leader_visibility": vis}, indent=1), flush=True)
    if a.preflight_only: return
    def restore():
        if SUSP.exists(): shutil.move(str(SUSP), str(HOLD))
        assert HOLD.exists() and HOLD.read_text() == hold_text, "HOLD NOT RESTORED"
    atexit.register(lambda: SUSP.exists() and shutil.move(str(SUSP), str(HOLD)))
    def on_sig(sig, frm): restore(); print("signal received: hold restored; stopping", flush=True); sys.exit(130)
    for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP): signal.signal(s, on_sig)
    key, base = ("test-key-not-secret", f"http://127.0.0.1:{a.loopback_port}") if test else amd_client.load_config()
    o = Oracle3(BP.PDF, CFG); results = []; stop = None
    try:
        for c in plan["crops"]:
            cid = c["crop_id"]; spec = next(x for x in BP.CROPS if x["crop_id"] == cid); rd = ev / cid
            assert not rd.exists(), f"{cid} was already run; this authorization allows one attempt per crop"
            png = (WS / c["image_file"]).read_bytes(); user = BP.USER.replace("__ORDER__", BP.ORDERS[spec["ask"]])
            body = pipeline.build_request(EXPECTED["model"], amd_client.image_message(user, png, system=BP.SYSTEM), EXPECTED["max_tokens"], EXPECTED["temperature"], json_mode=True, extra=None)
            shutil.move(str(HOLD), str(SUSP)); t0 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            try:
                pipeline.assert_live_allowed(base, True)
                res = streaming.stream_chat(base, key, body, no_progress_s=EXPECTED["no_progress_abort_s"], wall_s=EXPECTED["wall_abort_s"])
            finally:
                restore()
            t1 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()); tel = res["telemetry"]; rd.mkdir(parents=True)
            (rd / "stage1_raw_response.json").write_text(json.dumps({"sanitized": "provider key-hash metadata scrubbed; no credential present", "request_started_utc": t0, "request_ended_utc": t1, "telemetry": tel, "content": res["content"],
                                                                       "reasoning_chars": len(res["reasoning"]), "usage": res["usage"], "events": res["events"][:60]}, indent=1))
            (rd / "request_meta.json").write_text(json.dumps({"crop_id": cid, "image_sha256": c["image_sha256"], "user_prompt_sha256": c["user_prompt_sha256"], "system_sha256": plan["prompt"]["system_sha256"], "plan_sha256": pre["plan_sha256"],
                                                              "request": {k: v for k, v in body.items() if k != "messages"} | {"stream": True}, "source_sha256": BP.PDF_SHA}, indent=1))
            obj, cat, detail = pipeline.strict_parse(res["content"]); normal = tel["outcome"] == "normal"
            sc = S.score(obj, cid, o, normal) if obj is not None else {"crop_id": cid, "1_valid_completed_json": False, "shape_problems": [f"strict parse failed: {cat}: {detail}"]}
            (rd / "scoring.json").write_text(json.dumps({"strict_parse": {"category": cat, "detail": detail}, "score": sc, "parsed": obj}, indent=1, ensure_ascii=False))
            results.append({"crop_id": cid, "outcome": tel["outcome"], "http": tel["http_status"], "first_byte_s": tel.get("t_first_byte_s"), "end_s": tel["t_end_s"], "finish": tel.get("finish_reason"), "usage": res["usage"], "valid": sc["1_valid_completed_json"], "pass": sc.get("pass_for_this_crop")})
            print(json.dumps(results[-1]), flush=True)
            if not normal or obj is None or sc.get("shape_problems") or not sc["1_valid_completed_json"]:
                stop = f"STOP after {cid}: non-normal / unparseable / schema-invalid outcome (no retry, no further request)"; break
    except BaseException as e:
        stop = f"STOP: {type(e).__name__}: {str(e)[:120]}"
    finally:
        o.close(); restore()
    print(json.dumps({"stopped": stop, "requests_made": len(results), "hold_restored": HOLD.exists() and HOLD.read_text() == hold_text}))
    if not test: (ev / "RUN_SUMMARY.json").write_text(json.dumps({"plan_sha256": pre["plan_sha256"], "results": results, "stopped": stop, "hold_restored": HOLD.exists() and HOLD.read_text() == hold_text}, indent=1))


if __name__ == "__main__":
    main()

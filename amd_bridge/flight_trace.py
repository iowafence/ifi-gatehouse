"""Builds dp001/flight_recorder.json (schema gatehouse-flight-trace.v1, see docs/FLIGHT_RECORDER_CONTRACT.md) OFFLINE from the stored inference records
that the evidence ledger already indexes. No network, no AMD client, no clock: the output is deterministic.
Every event is derived from a stored record that is hashed here; a measurement a record does not contain is written as reported=false / value=null
(never estimated). Two values are DERIVED from measured fields of the same record and say so with their formula.
Usage:  python3 -m amd_bridge.flight_trace            write dp001/flight_recorder.json
        python3 -m amd_bridge.flight_trace --check    exit 1 unless the file on disk equals a fresh rebuild"""
import hashlib, json, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent.parent
LEDGER = HERE / "dp001/ai_findings.json"
OUT = HERE / "dp001/flight_recorder.json"
EXP = HERE / "amd_experiment"
PROVIDER = "AMD Token Factory (developer.amd.com.cn)"
PROVIDER_NOTE = "Provider is the harness's configured AMD endpoint; the individual record does not store the host."
H = lambda b: hashlib.sha256(b).hexdigest()


def f(value, unit=None, derived=None):
    """A field. value None => not reported."""
    return {"value": value, "unit": unit, "reported": value is not None, "derived": derived}


def locate(path):
    for base in (HERE, EXP, HERE / "spatial_plan"):
        p = base / path
        if p.is_file():
            return p
    raise FileNotFoundError(path)


def read(path):
    p = locate(path)
    raw = p.read_bytes()
    rel = p.relative_to(HERE).as_posix()
    return (json.loads(raw) if p.suffix == ".json" else None), rel, H(raw)


# attempt -> (file that carries the telemetry, how to read it)
RECORD = {
    "exp1-gemma-fullpage": ("runs/exp1/Gemma-4-31B-IT/summary.json", "summary"),
    "exp2-qwen-crop": ("runs/exp2/Qwen3.8-27B/summary.json", "summary"),
    "exp2-deepseek-crop": ("runs/exp2/DeepSeek-V4.1-Flash/summary.json", "summary"),
    "exp2-deepseek-stream-diagnostic": ("runs/exp2/DeepSeek-V4.1-Flash_stream_diagnostic/diagnostic_record.json", "diagnostic"),
    "spatial_c101_live_001": ("runs_v2/dp001_ansi_b_v2_drawings/62ab61d7f255/spatial_c101_live_001/run_record.json", "run_record"),
    "spatial_c101_live_002": ("runs_v2/dp001_ansi_b_v2_drawings/62ab61d7f255/spatial_c101_live_002/run_record.json", "run_record"),
}
for r in ("r1_north_band_gates_and_tag", "r2_east_edge_type_tag_and_gate", "r3_west_edge_gate"):
    RECORD[f"spatial_003_{r}"] = (f"spatial_plan/runs_v3/{r}/stage1_raw_response.json", "stream")


def measured(kind, rec):
    """Pull the measured values out of ONE stored record. Returns (telemetry dict, usage dict, utc)."""
    if kind in ("run_record",):
        return rec.get("telemetry", {}), {}, None
    if kind == "stream":
        return rec.get("telemetry", {}), rec.get("usage") or {}, rec.get("request_started_utc")
    if kind == "summary":
        t = {"http_status": rec.get("http_status"), "finish_reason": rec.get("finish_reason"), "total_s": rec.get("latency_s")}
        return t, rec.get("usage") or {}, None
    if kind == "diagnostic":
        keys = ("http_status", "finish_reason", "chunks", "t_connected_s", "t_request_sent_s", "t_first_byte_s", "t_first_content_token_s", "t_end_s")
        return {k: rec.get(k) for k in keys if k in rec} | {k: rec.get("telemetry", {}).get(k) for k in keys if k in rec.get("telemetry", {})}, rec.get("usage") or {}, None
    return {}, {}, None


def amd_fields(model, kind, rec, ledger_attempt):
    t, u, _ = measured(kind, rec)
    num = lambda x: x if isinstance(x, (int, float)) and not isinstance(x, bool) else None
    flds = {
        "provider": f(PROVIDER), "model": f(model),
        "model_returned": f(rec.get("model_returned") if isinstance(rec, dict) else None),
        "http_status": f(num(t.get("http_status"))), "finish_reason": f(t.get("finish_reason")),
        "t_connected_s": f(num(t.get("t_connected_s")), "s"), "t_request_sent_s": f(num(t.get("t_request_sent_s")), "s"),
        "t_first_content_token_s": f(num(t.get("t_first_content_token_s") if t.get("t_first_content_token_s") is not None else t.get("t_first_byte_s")), "s"),
        "t_end_s": f(num(t.get("t_end_s") if t.get("t_end_s") is not None else t.get("total_s")), "s"),
        "chunks": f(num(t.get("chunks"))),
        "prompt_tokens": f(num(u.get("prompt_tokens"))), "completion_tokens": f(num(u.get("completion_tokens"))), "total_tokens": f(num(u.get("total_tokens"))),
        "cost_usd": f(num(u.get("cost")) if u.get("cost") is not None else num((ledger_attempt.get("usage") or {}).get("cost_usd")), "USD"),
    }
    # DERIVED values, only from measured fields of this same record
    a, b = flds["t_first_content_token_s"]["value"], flds["t_request_sent_s"]["value"]
    flds["ttft_s"] = f(round(a - b, 3), "s", {"formula": "t_first_content_token_s - t_request_sent_s", "inputs": ["t_first_content_token_s", "t_request_sent_s"]}) if a is not None and b is not None and a >= b else f(None, "s")
    ct, end = flds["completion_tokens"]["value"], flds["t_end_s"]["value"]
    flds["tokens_per_s"] = (f(round(ct / (end - a), 1), "tokens/s", {"formula": "completion_tokens / (t_end_s - t_first_content_token_s)", "inputs": ["completion_tokens", "t_end_s", "t_first_content_token_s"]})
                            if kind == "stream" and ct and a is not None and end is not None and end > a else f(None, "tokens/s"))
    return flds


def build():
    led = json.loads(LEDGER.read_bytes())
    ledger_sha = H(LEDGER.read_bytes())
    amd_events, gemma_events = [], []
    for a in led["attempts"]:
        aid = a["attempt_id"]
        failed = a["state"] != "CANDIDATES_AVAILABLE"
        src = {"kind": "none", "record_path": None, "record_sha256": None}
        flds, utc, rec_kind = {}, None, None
        if aid in RECORD:
            path, rec_kind = RECORD[aid]
            rec, rel, sha = read(path)
            src = {"kind": "stored_inference_record", "record_path": rel, "record_sha256": sha}
            flds = amd_fields(a["model"], rec_kind, rec, a)
            utc = measured(rec_kind, rec)[2]
        elif aid == "exp1-qwen-fullpage":   # only a request log exists: statuses and client-side latencies
            p = locate("runs/exp1/request_attempts.jsonl"); raw = p.read_bytes()
            rows = [json.loads(x) for x in raw.decode().splitlines() if x.strip()]
            src = {"kind": "stored_inference_record", "record_path": p.relative_to(HERE).as_posix(), "record_sha256": H(raw)}
            flds = {"provider": f(PROVIDER), "model": f(a["model"]), "attempts_logged": f(len(rows)), "http_status": f(rows[-1].get("status")), "t_end_s": f(rows[-1].get("latency_s"), "s")}
        else:
            raise SystemExit(f"no record mapping for attempt {aid}")
        ev = {"event_id": f"amd:{aid}", "kind": "inference_request", "label": f"{a['model']} · {a.get('scope_of_input') or a['page']}", "state": "FAILED" if failed else "RECORDED",
              "utc": utc, "fields": flds, "source": src,
              "note": (a["outcome"] + " " if failed else "") + PROVIDER_NOTE if failed else PROVIDER_NOTE}
        ev["note"] = ((a["outcome"] + " ") if failed else "") + PROVIDER_NOTE
        amd_events.append(ev)
        if "gemma" in a["model"].lower():
            rec, rel, sha = read(RECORD[aid][0])
            meta, mrel, msha = read("runs/exp1/Gemma-4-31B-IT/request_meta.json")
            u = rec.get("usage") or {}
            gemma_events.append({"event_id": f"gemma:{aid}", "kind": "model_response", "label": f"{meta['model']} · {a.get('scope_of_input') or a['page']}", "state": "FAILED", "utc": None,
                "fields": {"model": f(meta["model"]), "model_returned": f(rec.get("model_returned")), "prompt_tokens": f(u.get("prompt_tokens")), "completion_tokens": f(u.get("completion_tokens")),
                           "finish_reason": f(rec.get("finish_reason")), "parse_result": f(rec.get("json")), "citations": f(None), "findings_returned": f(None)},
                "source": {"kind": "stored_inference_record", "record_path": rel, "record_sha256": sha},
                "note": "The model used its whole 8000-token budget and returned no parseable JSON; no findings, no citations, nothing validated. " + a["outcome"]})
    layers = [
        {"layer": "amd", "state": "RECORDED", "summary": f"{len(amd_events)} real requests to the AMD-hosted endpoint, shown from stored telemetry. No request was made by this page or this session. GPU utilization is not reported by any record.", "events": amd_events},
        {"layer": "gemma", "state": "FAILED", "summary": "One stored Gemma-4-31B-IT attempt, which failed. Spatial Test 003 and the accepted findings came from DeepSeek-V4.1-Flash, not Gemma, and are listed under AMD only.", "events": gemma_events},
        {"layer": "evolus", "state": "NOT_REPORTED", "summary": "No Evolus workflow execution has been recorded. The repository has only an Evolus REST client with a mock mode and agent instructions; nothing was ever run against a live Evolus workspace.", "events": []},
    ]
    return {"schema": "gatehouse-flight-trace.v1", "trace_id": "gatehouse-recorded-amd-evidence", "generated_utc": None,
            "producer": {"name": "amd_bridge.flight_trace", "version": "ledger_sha256=" + ledger_sha}, "layers": layers}


def main():
    doc = json.dumps(build(), indent=1, ensure_ascii=False) + "\n"
    if "--check" in sys.argv:
        sys.exit(0 if OUT.exists() and OUT.read_text() == doc else 1)
    OUT.write_text(doc)
    print(f"wrote {OUT.relative_to(HERE)} ({len(doc)} bytes)")


if __name__ == "__main__":
    main()

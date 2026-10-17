"""AMD -> Gatehouse inference bridge, OFFLINE activity table builder.

Reads the stored attempt records (read-only) and writes dp001/ai_activity.json: for each attempt in the ledger (dp001/ai_findings.json) the token counts and call time
exactly as the stored records state them, each with the file and SHA-256 it came from. Nothing is estimated or summed; a value no record states is null (printed NOT_REPORTED).
Only numbers, states and file hashes are copied. No organization, project or key identifier is ever read into the output.
No network call is made. Usage: python3 -m amd_bridge.ai_activity   (writes the file; --check exits non-zero if the committed file differs)"""
import hashlib, json, os, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent.parent
EXP = pathlib.Path(os.environ.get("GATEHOUSE_AMD_EXPERIMENT") or (HERE / "amd_experiment"))
OUT = HERE / "dp001" / "ai_activity.json"
LEDGER = HERE / "dp001" / "ai_findings.json"
V2 = "runs_v2/dp001_ansi_b_v2_drawings/62ab61d7f255"
SPATIAL3 = HERE / "evidence" / "spatial_test_003_runs"
# attempt_id -> (token source file, call-time source file, how the time is stated)
SOURCES = {
    "exp1-gemma-fullpage":                  (EXP / "runs/exp1/Gemma-4-31B-IT/summary.json", EXP / "runs/exp1/Gemma-4-31B-IT/summary.json", "latency_s"),
    "exp1-qwen-fullpage":                   (None, EXP / "runs/exp1/request_attempts.jsonl", "attempts"),
    "exp2-qwen-crop":                       (EXP / "runs/exp2/Qwen3.8-27B/summary.v1.json", EXP / "runs/exp2/Qwen3.8-27B/summary.v1.json", "latency_s"),
    "exp2-deepseek-crop":                   (EXP / "runs/exp2/DeepSeek-V4.1-Flash/summary.json", EXP / "runs/exp2/DeepSeek-V4.1-Flash/summary.json", "latency_s"),
    "exp2-deepseek-stream-diagnostic":      (EXP / "runs/exp2/DeepSeek-V4.1-Flash_stream_diagnostic/diagnostic_record.json", EXP / "runs/exp2/DeepSeek-V4.1-Flash_stream_diagnostic/diagnostic_record.json", "t_end_s"),
    "spatial_c101_live_001":                (EXP / f"{V2}/spatial_c101_live_001/stage1_raw_response.json", EXP / f"{V2}/spatial_c101_live_001/stage1_raw_response.json", "request_window"),
    "spatial_c101_live_002":                (EXP / f"{V2}/spatial_c101_live_002/stage1_raw_response.json", EXP / f"{V2}/spatial_c101_live_002/stage1_raw_response.json", "t_end_s"),
    "spatial_003_r1_north_band_gates_and_tag": (SPATIAL3 / "r1_north_band_gates_and_tag/stage1_raw_response.json",) * 2 + ("t_end_s",),
    "spatial_003_r2_east_edge_type_tag_and_gate": (SPATIAL3 / "r2_east_edge_type_tag_and_gate/stage1_raw_response.json",) * 2 + ("t_end_s",),
    "spatial_003_r3_west_edge_gate":        (SPATIAL3 / "r3_west_edge_gate/stage1_raw_response.json",) * 2 + ("t_end_s",),
}
sha = lambda p: hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
rel = lambda p: str(pathlib.Path(p).resolve().relative_to(HERE)) if str(pathlib.Path(p).resolve()).startswith(str(HERE)) else str(pathlib.Path(p).relative_to(EXP.parent))
num = lambda v: v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _usage(doc):
    u = doc.get("usage") if isinstance(doc, dict) else None
    if not isinstance(u, dict): return None
    pin, pout = num(u.get("prompt_tokens")), num(u.get("completion_tokens"))
    if pin is None and pout is None: return None
    cached = num((u.get("prompt_tokens_details") or {}).get("cached_tokens"))
    return {"tokens_in": pin, "tokens_out": pout, "tokens_cached": cached, "cost_usd": num(u.get("cost"))}


def build():
    led = json.loads(LEDGER.read_text())
    rows, files = [], {}
    for a in led["attempts"]:
        tok_f, time_f, how = SOURCES[a["attempt_id"]]
        row = {"attempt_id": a["attempt_id"], "model": a["model"], "state": a["state"], "outcome": a.get("outcome"),
               "tokens_in": None, "tokens_out": None, "tokens_cached": None, "cost_usd": None, "call_time_s": None, "call_time_basis": None, "when_utc": None, "sources": []}
        if tok_f is not None:
            u = _usage(json.loads(pathlib.Path(tok_f).read_text()))
            if u: row.update(u); row["sources"].append({"what": "tokens", "file": rel(tok_f), "sha256": sha(tok_f)})
        if how == "attempts":      # exp1 Qwen: the request log lists each call; report the recorded client-timeout calls, never a sum
            calls = [json.loads(l) for l in pathlib.Path(time_f).read_text().splitlines() if l.strip()]
            timed = [c["latency_s"] for c in calls if c.get("status") == 0 and num(c.get("latency_s"))]
            if timed: row["call_time_s"] = timed[0]; row["call_time_basis"] = f"time until client timeout; {len(timed)} timed-out calls recorded ({', '.join(str(x) + ' s' for x in timed)}); the first is shown"
        else:
            d = json.loads(pathlib.Path(time_f).read_text())
            t = d.get("telemetry") if isinstance(d.get("telemetry"), dict) else {}
            if how == "request_window":
                v = num(t.get("t_end_s")) if num(t.get("t_end_s")) is not None else (num((t.get("limits") or {}).get("wall_s")) if t.get("outcome") == "client_abort_wall_time" else None)
                row["call_time_s"] = v
                row["call_time_basis"] = "time until the client aborted at its wall-time limit" if v is not None else None
            else:
                v = num(d.get(how)) if num(d.get(how)) is not None else num(t.get(how))
                row["call_time_s"] = v
                row["call_time_basis"] = ("time until client timeout" if a["state"] == "TIMED_OUT" else "call time") if v is not None else None
            row["when_utc"] = d.get("request_started_utc") if isinstance(d.get("request_started_utc"), str) else None
        if row["call_time_s"] is not None: row["sources"].append({"what": "call time", "file": rel(time_f), "sha256": sha(time_f)})
        rows.append(row)
    by_model, by_state = {}, {}
    for r in rows:
        by_model[r["model"]] = by_model.get(r["model"], 0) + 1; by_state[r["state"]] = by_state.get(r["state"], 0) + 1
    return {"schema": "gatehouse-ai-activity.v1", "ledger_sha256": sha(LEDGER),
            "note": "Per-attempt values copied from the stored attempt records. Null means no record states it. Nothing here is estimated, summed or rounded.",
            "by_model": by_model, "by_state": by_state,
            "tokens_reported_on": sum(1 for r in rows if r["tokens_in"] is not None or r["tokens_out"] is not None),
            "call_time_reported_on": sum(1 for r in rows if r["call_time_s"] is not None), "attempts": rows}


if __name__ == "__main__":
    doc = json.dumps(build(), indent=1) + "\n"
    if "--check" in sys.argv: sys.exit(0 if OUT.read_text() == doc else "dp001/ai_activity.json differs from the stored records")
    OUT.write_text(doc); print(f"wrote {OUT} ({len(doc)} bytes)")

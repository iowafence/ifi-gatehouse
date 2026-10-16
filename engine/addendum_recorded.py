"""RECORDED replay of a logged live parse, for UI verification. It is labeled RECORDED, never LIVE: no network, no credential, no ledger
call is used or consumed. It answers only for the exact document (SHA-256) the recording was made from."""
import copy
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
RECORDING = ROOT / "amd_experiment" / "recorded" / "addendum_02_call2.json"


def recorded_parser(pages, context):
    from .addendum_intake import ParseUnavailable
    try:
        rec = json.loads(RECORDING.read_text())
    except (OSError, ValueError):
        raise ParseUnavailable("no recording is available", {"mode": "RECORDED"})
    if context.get("sha256") != rec["source_sha256"]:
        raise ParseUnavailable("RECORDED mode answers only for the document the recording was made from; this document has no recording", {"mode": "RECORDED"})
    meta = {"mode": "RECORDED", "model": rec["model_returned"], "elapsed_ms": rec["elapsed_ms"], "usage": rec["usage"],
            "recorded_from": f"live call {rec['ledger_call_no']} at {rec['live_call_utc']}"}
    return copy.deepcopy(rec["facts"]), meta


recorded_parser.enforce_slots = True

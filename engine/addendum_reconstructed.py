"""RECONSTRUCTED replay of live call 2, for UI verification. Call 2's raw reply was not retained, so this is NOT a recording: it rebuilds the
facts the engine accepted from the logged intake record. It is labeled RECONSTRUCTED, never RECORDED or LIVE: no network, no credential, no
ledger call is used or consumed. It answers only for the exact document (SHA-256) the log was made from."""
import copy
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
RECORDING = ROOT / "amd_experiment" / "reconstructed" / "addendum_02_call2_reconstructed.json"


def reconstructed_parser(pages, context):
    from .addendum_intake import ParseUnavailable
    try:
        rec = json.loads(RECORDING.read_text())
    except (OSError, ValueError):
        raise ParseUnavailable("no reconstruction is available", {"mode": "RECONSTRUCTED"})
    if context.get("sha256") != rec["source_sha256"]:
        raise ParseUnavailable("RECONSTRUCTED mode answers only for the document the log was made from; this document has none", {"mode": "RECONSTRUCTED"})
    meta = {"mode": "RECONSTRUCTED", "model": rec["model_returned"], "elapsed_ms": rec["elapsed_ms"], "usage": rec["usage"],
            "recorded_from": f"logged intake record of live call {rec['ledger_call_no']} at {rec['live_call_utc']}"}
    return copy.deepcopy(rec["facts"]), meta


reconstructed_parser.enforce_slots = True

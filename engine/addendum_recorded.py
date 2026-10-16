"""RECORDED replay of a CAPTURED live reply, for UI verification. A capture is the verbatim raw response (and the request, without
credentials) stored at the time of a live call. This replay runs that raw reply through the same reply-to-facts code as the live call, so it
returns exactly what the live call returned. It uses no network, no credential and no ledger call, and answers only for the exact document
(SHA-256) the capture was made from. If no capture exists it says so (it never substitutes a reconstruction)."""
import base64
import glob
import hashlib
import json
import os

from . import addendum_live as live


def _load(path, sha):
    cap = json.load(open(path))
    if cap.get("source_sha256") != sha or cap.get("http_status") != 200:
        return None
    raw = base64.b64decode(cap["response_raw_b64"]) if cap.get("response_raw_b64") else None
    if raw is not None and hashlib.sha256(raw).hexdigest() != cap.get("response_raw_sha256"):
        raise ValueError("response digest mismatch")
    if hashlib.sha256(json.dumps(cap["request_body"], separators=(",", ":")).encode()).hexdigest() != cap.get("request_body_sha256"):
        raise ValueError("request digest mismatch")
    return cap


def recorded_parser(pages, context):
    from .addendum_intake import ParseUnavailable
    sha = context.get("sha256") or ""
    caps = sorted(glob.glob(str(live.capture_dir() / f"{sha[:12]}_call*.json")), key=lambda p: int(os.path.basename(p).rsplit("call", 1)[1].split(".")[0]), reverse=True)
    for path in caps:
        try:
            cap = _load(path, sha)
            if cap is None:
                continue
            facts, model, usage, finish = live.reply_to_facts(cap["response_raw_text"], context.get("slots") or [])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        return facts, {"mode": "RECORDED", "model": model, "requested_model": cap["request_body"].get("model", live.NR), "elapsed_ms": cap["elapsed_ms"], "usage": usage,
                       "finish_reason": finish, "recorded_from": f"captured live call {cap['call_no']} at {cap['utc']}", "capture_file": os.path.basename(path)}
    raise ParseUnavailable("no verified capture exists for this document, so there is nothing to replay (RECORDED mode never substitutes a reconstruction)", {"mode": "RECORDED"})


recorded_parser.enforce_slots = True

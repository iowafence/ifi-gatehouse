"""The live AMD parse for an addendum: ONE bounded text-only request to Qwen3.8-27B on AMD Token Factory, only for documents the owner
has authorized by SHA-256, at most `max_calls` calls in total, one attempt per call (no retry loop), hard timeout.

Authorization lives in amd_experiment/LIVE_AUTH_ADDENDUM_02.json (owner-edited). It narrows, and does not replace, the harness-wide
hold: amd_experiment/LIVE_CALLS_DISABLED stays in force for the experiment pipeline and every other caller. The call is reserved in
the file BEFORE it is sent, so a crash cannot exceed the budget. Unknown telemetry is recorded as NOT_REPORTED, never guessed.
The model only proposes {path, value, page, excerpt}; the engine verifies the excerpt is on the cited page and a named human accepts."""
import base64
import fcntl
import hashlib
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
AUTH_FILE = ROOT / "amd_experiment" / "LIVE_AUTH_ADDENDUM_02.json"
MODEL = "Qwen3.8-27B"
MAX_TOKENS = 1500
MAX_PROMPT_CHARS = 40_000
NR = "NOT_REPORTED"

SYSTEM = ("You read the text of one construction bid addendum and report only facts it states about the listed fact slots. "
          "Reply with ONE JSON object and nothing else: {\"facts\":[{\"path\":<slot path>,\"value\":<number>,\"page\":<integer page number>,"
          "\"excerpt\":<exact words copied from that page>}]}. Rules: use only the listed slot paths; one entry per slot at most; "
          "copy the excerpt exactly as written on the page; the value must be the number the excerpt states, in the slot's unit; "
          "if the addendum says a gate's post or footing is the same as another gate's, return {\"path\":<slot path>,\"same_as\":<that gate's class name, e.g. GATE_G1>,\"page\":<page>,\"excerpt\":<exact words>} with NO value and no numbers; "
          "if the addendum does not state a slot, omit it; never estimate, infer, convert from other facts, or invent. "
          "If nothing is stated reply {\"facts\":[]}.")


def _unavailable(msg, meta=None):
    from .addendum_intake import ParseUnavailable
    return ParseUnavailable(msg, meta)


class _Locked:
    def __enter__(self):
        self.fh = open(AUTH_FILE, "r+")
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        self.data = json.load(self.fh)
        return self

    def save(self):
        self.fh.seek(0)
        self.fh.truncate()
        json.dump(self.data, self.fh, indent=1)
        self.fh.write("\n")
        self.fh.flush()
        os.fsync(self.fh.fileno())

    def __exit__(self, *a):
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


def _reserve(sha):
    """Check the authorization and reserve one call in the file. Raises ParseUnavailable (nothing sent) if any check fails."""
    if not AUTH_FILE.exists():
        raise _unavailable("live parse is not authorized: no authorization file (amd_experiment/LIVE_AUTH_ADDENDUM_02.json)")
    try:
        with _Locked() as lk:
            d = lk.data
            if d.get("model") != MODEL or d.get("purpose") != "ADDENDUM_02_PARSE_ONLY" or not d.get("authorized_by"):
                raise _unavailable("the authorization file is malformed or names another model or purpose")
            if sha not in (d.get("allowed_sha256") or []):
                raise _unavailable("live parse is authorized for Addendum 02 only: this document's SHA-256 is not on the authorized list")
            calls = d.setdefault("calls", [])
            if len(calls) >= int(d.get("max_calls", 0)):
                raise _unavailable(f"the live-call budget ({d.get('max_calls')}) is used up; no further live call is authorized")
            call = {"call_no": len(calls) + 1, "sha256": sha, "reserved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "result": "RESERVED"}
            calls.append(call)
            lk.save()
            return call["call_no"], float(d.get("timeout_s", 120))
    except (OSError, ValueError) as e:
        raise _unavailable(f"the authorization file cannot be read: {type(e).__name__}")


def _record(call_no, **fields):
    with _Locked() as lk:
        lk.data["calls"][call_no - 1].update(fields)
        lk.save()


def build_messages(pages, slots):
    lines = ["FACT SLOTS (path | what it is | unit):"] + [f"{s['path']} | {s['label']} | {s['unit']}" for s in slots]
    body = "\n\n".join(f"=== PAGE {p['page']} ===\n{p['text']}" for p in pages)
    if len(body) > MAX_PROMPT_CHARS:
        raise _unavailable("the addendum text is too long to send in one bounded request")
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n".join(lines) + "\n\nADDENDUM TEXT:\n" + body}]


def capture_dir():
    """Where verbatim captures of live calls are kept: outside the repository (they are evidence, not source). Override with GATEHOUSE_CAPTURE_DIR."""
    return pathlib.Path(os.environ.get("GATEHOUSE_CAPTURE_DIR") or (pathlib.Path.home() / "ifi-gatehouse-live-captures"))


def capture_path(sha, call_no):
    return capture_dir() / f"{sha[:12]}_call{call_no}.json"


def _write_capture(sha, call_no, key, body, status, raw, elapsed_ms, client_error):
    """Store the exact request body (credentials are never in it: the key travels only in a header) and the verbatim response bytes."""
    req = json.dumps(body, separators=(",", ":")).encode()
    text = raw.decode("utf-8", "replace")
    redacted = bool(key) and key in text
    if redacted:
        text = text.replace(key, "<redacted>")
    rec = {"capture_version": 1, "call_no": call_no, "source_sha256": sha, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "endpoint_path": "/chat/completions",
           "request_body": body, "request_body_sha256": hashlib.sha256(req).hexdigest(), "http_status": status, "elapsed_ms": elapsed_ms, "client_error": client_error,
           "response_raw_text": text, "response_raw_b64": base64.b64encode(raw).decode() if not redacted else None, "response_raw_sha256": hashlib.sha256(raw).hexdigest(),
           "redacted": redacted}
    d = capture_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = capture_path(sha, call_no)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)       # never overwrite a capture
    with os.fdopen(fd, "w") as fh:
        json.dump(rec, fh, indent=1)
        fh.write("\n")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def reply_to_facts(raw_text, slots):
    """The ONE place a model reply becomes proposed facts (used by the live call and by the RECORDED replay of a capture).
    -> (facts, model, usage, finish_reason). Raises ValueError for anything that is not the required JSON."""
    body = json.loads(raw_text)
    if not isinstance(body, dict):
        raise ValueError("reply is not an object")
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else None
    out = json.loads(body["choices"][0]["message"]["content"])
    facts = out["facts"]
    if not isinstance(facts, list) or set(out) != {"facts"}:
        raise ValueError("reply is not {facts: [...]}")
    unit = {s["path"]: s["unit"] for s in slots}
    for f in facts:
        if isinstance(f, dict) and f.get("path") in unit:
            f["unit"] = unit[f["path"]]
        if isinstance(f, dict) and "value" in f and (isinstance(f.get("value"), bool) or not isinstance(f.get("value"), (int, float))):
            f["value"] = "INVALID"          # a non-number is later refused by the engine's own value checks, never coerced here
    return (facts, body.get("model") or MODEL,
            {k: usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens") if k in usage} if usage else NR,
            (((body.get("choices") or [{}])[0]) or {}).get("finish_reason") or NR)


def _post(base, key, body, timeout):
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body, separators=(",", ":")).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Accept": "application/json", "Content-Type": "application/json"})
    t0 = time.monotonic()
    err = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raw, status, err = b"", 0, type(e).__name__
    return status, raw, int((time.monotonic() - t0) * 1000), err


def live_parser(pages, context):
    slots = context.get("slots") or []
    if not slots:
        raise _unavailable("no open fact slots to ask about")
    sha = context["sha256"]
    call_no, timeout = _reserve(sha)
    sys.path.insert(0, str(ROOT / "amd_experiment"))
    try:
        from ext import amd_client
        messages = build_messages(pages, slots)
        key, base = amd_client.load_config()
    except Exception as e:  # noqa: BLE001 - includes NoCredential; nothing is sent
        _record(call_no, result="NOT_SENT", detail=type(e).__name__)
        raise _unavailable(f"live parse not sent: {type(e).__name__}", {"model": MODEL})
    body = {"model": MODEL, "messages": messages, "max_tokens": MAX_TOKENS, "temperature": 0.0,
            "response_format": {"type": "json_object"}, "chat_template_kwargs": {"enable_thinking": False}}
    status, raw, elapsed, err = _post(base, key, body, timeout)
    try:
        path, csha = _write_capture(sha, call_no, key, body, status, raw, elapsed, err)
        cap = {"capture_file": path.name, "capture_sha256": csha}
    except OSError as e:
        cap = {"capture_file": None, "capture_error": type(e).__name__}
    try:
        facts, model, usage, finish = reply_to_facts(raw.decode("utf-8", "replace"), slots) if status == 200 else (None, MODEL, NR, NR)
    except Exception:  # noqa: BLE001
        facts, model, usage, finish = None, MODEL, NR, NR
        parsed_ok = False
    else:
        parsed_ok = facts is not None
    meta = {"mode": "LIVE", "model": model, "requested_model": MODEL, "elapsed_ms": elapsed, "http_status": status, "usage": usage, "finish_reason": finish}
    if status != 200:
        _record(call_no, result="HTTP_ERROR", http_status=status, elapsed_ms=elapsed, **cap)
        raise _unavailable(f"the model call failed (HTTP {status}); no retry was made", meta)
    if not parsed_ok:
        _record(call_no, result="UNPARSEABLE", http_status=200, elapsed_ms=elapsed, usage=usage, **cap)
        raise _unavailable("the model's reply was not the required JSON; nothing was accepted and no retry was made", meta)
    _record(call_no, result="RETURNED", http_status=200, elapsed_ms=elapsed, model_returned=model, usage=usage, facts_returned=len(facts), facts=facts, **cap)
    return facts, meta


def verify_identity():
    """ONE read-only GET /models (no inference, one attempt) to compare the configured model id with what the endpoint reports. Logged apart from
    parse calls in the authorization file. Returns a dict; never raises."""
    sys.path.insert(0, str(ROOT / "amd_experiment"))
    out = {"requested_model": MODEL, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        from ext import amd_client
        cli = amd_client.Client()
        t0 = time.monotonic()
        r = cli._call("GET", "/models", timeout=60, retries=0, retry_on=())
        out.update(http_status=r.get("status"), elapsed_ms=int((time.monotonic() - t0) * 1000))
        body = r.get("body") if isinstance(r.get("body"), dict) else {}
        data = body.get("data") if isinstance(body.get("data"), list) else []
        ids = sorted(str(m.get("id")) for m in data if isinstance(m, dict) and m.get("id"))
        out["endpoint_models_matching"] = [i for i in ids if "qwen" in i.lower()]
        out["endpoint_model_count"] = len(ids)
        out["exact_match"] = MODEL in ids
        out["suffix_match"] = [i for i in ids if i.split("/")[-1] == MODEL]
    except Exception as e:  # noqa: BLE001
        out.update(error=type(e).__name__)
    try:
        with _Locked() as lk:
            lk.data.setdefault("identity_checks", []).append(out)
            lk.save()
    except (OSError, ValueError):
        out["logged"] = False
    return out

"""Minimal OpenAI-compatible client for AMD Token Factory (standard library only).

The API key is read from the environment (AMD_TOKEN_FACTORY_API_KEY) or from ~/.config/ifi-amd/token_factory.env (must be mode 0600).
It is never printed, logged, written to a run directory, or sent anywhere except the Authorization header of the configured base URL.
Every saved artifact is passed through `redact()`.
"""
import base64
import json
import os
import pathlib
import stat
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "https://developer.amd.com.cn/radeon/api/v1"
SECRET_FILE = pathlib.Path.home() / ".config/ifi-amd/token_factory.env"
KEY_VAR, BASE_VAR = "AMD_TOKEN_FACTORY_API_KEY", "AMD_TOKEN_FACTORY_BASE_URL"


class NoCredential(RuntimeError):
    pass


def _read_secret_file():
    if not SECRET_FILE.exists():
        return {}
    mode = stat.S_IMODE(SECRET_FILE.stat().st_mode)
    if mode & 0o077:
        raise NoCredential(f"{SECRET_FILE} must not be readable by group/others (chmod 600)")
    out = {}
    for line in SECRET_FILE.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_config():
    f = _read_secret_file()
    key = os.environ.get(KEY_VAR) or f.get(KEY_VAR) or ""
    base = (os.environ.get(BASE_VAR) or f.get(BASE_VAR) or DEFAULT_BASE).rstrip("/")
    if not key:
        raise NoCredential(f"no {KEY_VAR}: set it in the environment or in {SECRET_FILE} (mode 600). Nothing was sent.")
    return key, base


def redact(text, key):
    return text.replace(key, "<redacted>") if key else text


class Client:
    def __init__(self, key=None, base=None, log_path=None):
        self.key, self.base = (key, base) if key else load_config()
        self.attempts = []          # status/latency per attempt only; never headers or bodies
        self.log_path = log_path    # appended after EVERY attempt, so an interrupted run still leaves a record

    def _call(self, method, path, body=None, timeout=300, retries=3, retry_on=(429, 500, 502, 503, 504, 0)):
        url = self.base + path
        data = None if body is None else json.dumps(body).encode()
        last = None
        for attempt in range(1, retries + 2):
            req = urllib.request.Request(url, data=data, method=method, headers={
                "Authorization": f"Bearer {self.key}", "Accept": "application/json", **({"Content-Type": "application/json"} if data else {})})
            t0 = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    raw, status, hdr = r.read(), r.status, r.headers
            except urllib.error.HTTPError as e:
                raw, status, hdr = e.read(), e.code, e.headers
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                raw, status, hdr = redact(str(e), self.key).encode(), 0, {}
                exc_class = type(e).__name__ + (":" + type(getattr(e, "reason", None)).__name__ if getattr(e, "reason", None) is not None else "")
            latency = time.monotonic() - t0
            exc_class = locals().get('exc_class') if status == 0 else None
            rl = {k.lower(): v for k, v in dict(hdr).items() if k.lower().startswith(("x-ratelimit", "ratelimit", "retry-after"))} if hdr else {}
            self.attempts.append({"method": method, "path": path, "attempt": attempt, "status": status, "latency_s": round(latency, 3), "utc": time.strftime("%H:%M:%S", time.gmtime()),
                                  "client_exception": exc_class, "rate_limit_headers": rl, "timeout_s": timeout})
            if self.log_path:
                with open(self.log_path, "a") as fh:
                    fh.write(json.dumps(self.attempts[-1]) + "\n")
            try:
                parsed = json.loads(raw)
            except ValueError:
                parsed = {"_non_json_body": redact(raw[:500].decode("utf-8", "replace"), self.key)}
            last = {"status": status, "latency_s": latency, "body": parsed, "retry_after": (hdr.get("Retry-After") if hdr else None)}
            if status >= 400 and isinstance(parsed, dict):
                err = parsed.get("error") if isinstance(parsed.get("error"), dict) else {}
                self.attempts[-1]["error_category"] = {"type": err.get("type"), "code": err.get("code"), "param": err.get("param"), "detail_present": "detail" in parsed, "message": redact(str(err.get("message") or parsed.get("detail") or "")[:200], self.key)}
            if status in retry_on and attempt <= retries:
                wait = float(last["retry_after"]) if last["retry_after"] and str(last["retry_after"]).replace(".", "").isdigit() else 2 ** attempt
                self.attempts[-1]["backoff_s"] = wait
                time.sleep(min(wait, 60))
                continue
            return last
        return last

    def models(self):
        return self._call("GET", "/models", timeout=60)

    def chat(self, model, messages, max_tokens=4096, temperature=0.0, timeout=600, extra=None, retry_on=(429, 500, 502, 503, 504, 0)):
        body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature, **(extra or {})}
        return self._call("POST", "/chat/completions", body, timeout=timeout, retry_on=retry_on)


def image_message(prompt, png_bytes, system=None):
    url = "data:image/png;base64," + base64.b64encode(png_bytes).decode()
    msgs = [{"role": "system", "content": system}] if system else []
    msgs.append({"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": url}}]})
    return msgs

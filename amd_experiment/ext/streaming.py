"""One streaming chat request with watchdogs and full telemetry. No retries, ever: a cancelled request may still be running at the provider.

stream_chat(base_url, key, body, no_progress_s, wall_s) -> {"telemetry": {...}, "content": str, "reasoning": str, "usage": dict|None, "events": [...]}

Telemetry fields: t_connected_s, t_request_sent_s, t_first_byte_s, t_first_content_token_s, t_first_reasoning_token_s, t_done_s, t_end_s,
chunks, inter_chunk_gap_s{n,max,median,over_5s}, http_status, finish_reason, outcome (error category), partial (bool).
Outcome categories: normal | http_error | client_abort_no_progress | client_abort_wall_time | stream_closed_without_done | connect_error | stream_error.
`client_abort_*` means THIS client cancelled; `http_error` means the provider answered with an error status. The key only ever goes into the
Authorization header; it is never placed in telemetry, content or exceptions.
"""
import http.client
import json
import socket
import ssl
import statistics
import time
import urllib.parse


def _scrub(o):
    if isinstance(o, dict):
        return {k: ("<redacted-hash>" if k == "apiKeyHash" else _scrub(v)) for k, v in o.items()}
    return [_scrub(x) for x in o] if isinstance(o, list) else o


def stream_chat(base_url, key, body, no_progress_s=90.0, wall_s=150.0, path_suffix="/chat/completions"):
    u = urllib.parse.urlparse(base_url)
    payload = json.dumps({**body, "stream": True}).encode()
    t0 = time.monotonic()
    now = lambda: round(time.monotonic() - t0, 3)
    tel = {"http_status": None, "outcome": None, "partial": True, "limits": {"no_progress_s": no_progress_s, "wall_s": wall_s}, "chunks": 0}
    content, reasoning, gaps, usage, events = [], [], [], None, []
    conn = None
    last = t0
    try:
        if u.scheme == "https":
            conn = http.client.HTTPSConnection(u.netloc, timeout=no_progress_s, context=ssl.create_default_context())
        else:
            conn = http.client.HTTPConnection(u.netloc, timeout=no_progress_s)
        try:
            conn.connect()
        except (OSError, socket.timeout) as e:
            tel.update(outcome="connect_error", exception_class=type(e).__name__)
            raise _Done()
        tel["t_connected_s"] = now()
        sock = conn.sock                                 # http.client detaches conn.sock once a streaming response starts; keep our own reference
        conn.putrequest("POST", u.path.rstrip("/") + path_suffix)
        for h, v in (("Authorization", f"Bearer {key}"), ("Content-Type", "application/json"), ("Accept", "text/event-stream"), ("Content-Length", str(len(payload)))):
            conn.putheader(h, v)
        conn.endheaders(payload)
        tel["t_request_sent_s"] = now()
        sock.settimeout(min(no_progress_s, wall_s))
        try:
            resp = conn.getresponse()
        except (socket.timeout, TimeoutError):
            tel["outcome"] = "client_abort_no_progress" if now() < wall_s else "client_abort_wall_time"
            tel["http_status"] = None
            raise _Done()
        tel["t_first_byte_s"] = now()
        tel["http_status"] = resp.status
        tel["rate_limit_headers"] = {k.lower(): v for k, v in resp.getheaders() if k.lower().startswith(("x-ratelimit", "retry-after"))}
        last = time.monotonic()
        if resp.status != 200:
            try:
                tel["error_body"] = resp.read(2000).decode("utf-8", "replace")[:500]
            except OSError:
                tel["error_body"] = None
            tel["outcome"] = "http_error"
            raise _Done()
        while True:
            el = time.monotonic() - t0
            if el > wall_s:
                tel["outcome"] = "client_abort_wall_time"
                break
            sock.settimeout(max(0.05, min(no_progress_s - (time.monotonic() - last), wall_s - el)))
            try:
                line = resp.fp.readline()
            except (socket.timeout, TimeoutError):
                tel["outcome"] = "client_abort_no_progress" if time.monotonic() - last >= no_progress_s - 0.05 else "client_abort_wall_time"
                break
            except (OSError, http.client.HTTPException) as e:
                tel.update(outcome="stream_error", exception_class=type(e).__name__)
                break
            if not line:
                tel["outcome"] = "stream_closed_without_done"
                break
            tn = time.monotonic()
            gaps.append(round(tn - last, 3))
            last = tn
            s = line.decode("utf-8", "replace").strip()
            if not s.startswith("data:"):
                continue
            d = s[5:].strip()
            if d == "[DONE]":
                tel["outcome"], tel["t_done_s"], tel["partial"] = "normal", now(), False
                break
            try:
                ev = _scrub(json.loads(d))
            except ValueError:
                events.append({"t": now(), "non_json_event": d[:60]})
                continue
            tel["chunks"] += 1
            if ev.get("usage"):
                usage = ev["usage"]
            for ch in ev.get("choices") or []:
                dl = ch.get("delta") or {}
                if dl.get("content"):
                    tel.setdefault("t_first_content_token_s", now())
                    content.append(dl["content"])
                if dl.get("reasoning_content"):
                    tel.setdefault("t_first_reasoning_token_s", now())
                    reasoning.append(dl["reasoning_content"])
                if ch.get("finish_reason"):
                    tel["finish_reason"] = ch["finish_reason"]
    except _Done:
        pass
    except (OSError, http.client.HTTPException) as e:
        tel["outcome"] = tel["outcome"] or ("connect_error" if tel["http_status"] is None and "t_connected_s" not in tel else "stream_error")
        tel["exception_class"] = type(e).__name__
    finally:
        tel["t_end_s"] = now()
        if conn is not None:
            conn.close()                       # client-side cancellation; never followed by an automatic retry
    tel["inter_chunk_gap_s"] = {"n": len(gaps), "max": max(gaps) if gaps else None, "median": round(statistics.median(gaps), 3) if gaps else None, "over_5s": sum(1 for g in gaps if g > 5)}
    tel["cancelled_by_client"] = str(tel["outcome"]).startswith("client_abort")
    if tel["outcome"] is None:
        tel["outcome"] = "stream_error"
    tel["usage_supplied"] = usage is not None
    return {"telemetry": tel, "content": "".join(content), "reasoning": "".join(reasoning), "usage": usage, "events": events}


class _Done(Exception):
    pass

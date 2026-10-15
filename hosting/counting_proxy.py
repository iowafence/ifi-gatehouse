#!/usr/bin/env python3
"""Transparent local forwarding proxy that COUNTS new demo sessions created through it (a new session is the only response that sets the session cookie). It adds no headers and forges nothing:
the target service sees this machine's real network address. Used to know exactly how many new-session admissions a test run consumed before a rate-limit threshold test.
Usage: counting_proxy.py TARGET_HOST [PORT=18500]   (HTTPS to TARGET_HOST; GET /__count returns the JSON counters; refuses the frozen demo's ports)"""
import http.client, json, ssl, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
host = sys.argv[1]; port = int(sys.argv[2]) if len(sys.argv) > 2 else 18500
if port in (5071, 5051, 8099, 8098): sys.exit("refusing the frozen demo's ports")
LOCK = threading.Lock(); C = {"requests": 0, "new_sessions": 0, "status": {}}
HOP = {"transfer-encoding", "connection", "keep-alive", "content-length", "content-encoding"}
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def handle_any(self):
        if self.path == "/__count":
            b = json.dumps(C).encode(); self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        n = int(self.headers.get("Content-Length") or 0); body = self.rfile.read(n) if n else None
        hd = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "connection", "accept-encoding", "content-length")}; hd["Host"] = host; hd["Accept-Encoding"] = "identity"
        for k in list(hd):   # the browser talks to this local origin; present the same-origin the target expects (the app refuses cross-origin POSTs), nothing else is changed
            if k.lower() in ("origin", "referer") and hd[k].startswith("http://127.0.0.1"): hd[k] = hd[k].replace("http://127.0.0.1:%d" % port, "https://" + host)
        if body is not None: hd["Content-Length"] = str(len(body))
        c = http.client.HTTPSConnection(host, timeout=60, context=ssl.create_default_context())
        try: c.request(self.command, self.path, body=body, headers=hd); r = c.getresponse(); data = r.read(); code = r.status; heads = r.getheaders()
        except Exception as e: data = str(e).encode(); code = 502; heads = []
        finally: c.close()
        cookies = [v for k, v in heads if k.lower() == "set-cookie"]
        with LOCK:
            C["requests"] += 1; C["status"][str(code)] = C["status"].get(str(code), 0) + 1
            if cookies: C["new_sessions"] += 1
        self.send_response(code)
        for k, v in heads:
            if k.lower() not in HOP and k.lower() != "set-cookie": self.send_header(k, v)
        for v in cookies: self.send_header("Set-Cookie", v)
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = handle_any
    def log_message(self, *a): pass
ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()

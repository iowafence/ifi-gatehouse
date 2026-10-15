#!/usr/bin/env python3
"""LOCAL adversarial matrix for the session controls (no production, no external call). For each scenario a fresh container of IMAGE runs with the production environment and a
local proxy in front that plays the platform: it APPENDS to X-Forwarded-For (never clears it) like Render. Scenarios vary what the proxy appends and what the client forges.
Usage: hosting/limiter_matrix.py IMAGE    Exit 0 only if every scenario behaves as expected. Containers are removed afterwards; frozen-demo ports are never used."""
import json, random, subprocess, sys, threading, time, urllib.error, urllib.request, http.cookiejar as hc
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
IMAGE = sys.argv[1]; PORT0 = 18400; results = []; BASE_ENV = {"CLIENT_IP_HEADER": "x-forwarded-for", "NEW_DEMOS_PER_HOUR": "120", "IP_REQUESTS_PER_MIN": "900", "IP_MUTATIONS_PER_10MIN": "400", "DEMO_MAX_PROJECTS": "500"}
def sh(*a): return subprocess.run(a, capture_output=True, text=True)
def start(name, port, env):
    sh("docker", "rm", "-f", name); args = ["docker", "run", "-d", "--name", name, "--read-only", "--tmpfs", "/tmp", "--tmpfs", "/app/web/.next/cache:uid=10001", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "-p", f"127.0.0.1:{port}:8080"]
    for k, v in {**BASE_ENV, **env}.items(): args += ["-e", f"{k}={v}"]
    r = sh(*args, IMAGE); assert r.returncode == 0, r.stderr
    for _ in range(60):
        try: urllib.request.urlopen(f"http://127.0.0.1:{port}/api/demo/health", timeout=2); return
        except Exception: time.sleep(1)
    raise SystemExit("container did not start")
def proxy(upstream, port, mode):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            hop = "198.51.100.7" if mode == "const" else f"198.51.100.{random.randint(1, 250)}"; prior = self.headers.get("X-Forwarded-For")
            xff = ((prior + ", ") if prior else "") + "203.0.113.9" + ((", " + hop) if mode != "none" else "")
            hd = {"X-Forwarded-For": xff} if mode != "none" else ({"X-Forwarded-For": prior} if prior else {})
            for k in ("Cookie",):
                if self.headers.get(k): hd[k] = self.headers[k]
            try: r = urllib.request.urlopen(urllib.request.Request(upstream + self.path, headers=hd), timeout=30); code, body, sc = r.status, r.read(), r.headers.get_all("Set-Cookie")
            except urllib.error.HTTPError as e: code, body, sc = e.code, e.read(), None
            self.send_response(code); self.send_header("Content-Length", str(len(body)))
            for c in sc or []: self.send_header("Set-Cookie", c)
            self.end_headers(); self.wfile.write(body)
        def log_message(self, *a): pass
    srv = ThreadingHTTPServer(("127.0.0.1", port), H); threading.Thread(target=srv.serve_forever, daemon=True).start(); return srv
def sessions(port, n, forge=False, path="/api/demo/state"):
    hit = {}; first = None
    for i in range(n):
        h = {"X-Forwarded-For": f"6.6.{random.randint(1, 250)}.{random.randint(1, 250)}"} if forge else {}
        try: c = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=h), timeout=30).status
        except urllib.error.HTTPError as e: c = e.code
        hit[c] = hit.get(c, 0) + 1
        if c != 200 and first is None: first = i + 1
    return hit, first
def scenario(name, env, mode, n, expect_first, forge=False, expect_codes=None, fn=None):
    port = PORT0 + len(results) * 2; cname = f"gh-matrix-{len(results)}"; start(cname, port, env); srv = proxy(f"http://127.0.0.1:{port}", port + 1, mode)
    try:
        if fn: ok, detail = fn(port, port + 1)
        else:
            hit, first = sessions(port + 1, n, forge); ok = first == expect_first; detail = f"{hit} first refusal at {first} (expected {expect_first})"
        results.append((name, ok, detail)); print(("PASS  " if ok else "FAIL  ") + name + " -> " + detail, flush=True)
    finally: srv.shutdown(); sh("docker", "rm", "-f", cname)
scenario("S1 stable proxy entry, FROM_RIGHT=1: per-network limit enforced", {"CLIENT_IP_FROM_RIGHT": "1"}, "const", 150, 121)
scenario("S2 rotating proxy entry, FROM_RIGHT=1: OLD BYPASS reproduced (no per-network refusal; the global guard is still below 300)", {"CLIENT_IP_FROM_RIGHT": "1"}, "rotate", 150, None)
scenario("S3 rotating proxy entry, FROM_RIGHT=2: visitor entry keyed, limit enforced", {"CLIENT_IP_FROM_RIGHT": "2"}, "rotate", 150, 121)
scenario("S4 FROM_RIGHT=2 + client forges a different X-Forwarded-For prefix on every request: cannot create buckets", {"CLIENT_IP_FROM_RIGHT": "2"}, "rotate", 150, 121, forge=True)
scenario("S5 header missing entirely (no proxy), FROM_RIGHT=2: fails closed into one shared bucket", {"CLIENT_IP_FROM_RIGHT": "2"}, "none", 150, 121)
scenario("S6 malformed FROM_RIGHT=abc + forged first entries: fails closed, never trusts the client-controlled first entry", {"CLIENT_IP_FROM_RIGHT": "abc"}, "rotate", 150, 121, forge=True)
scenario("S7 too few entries (FROM_RIGHT=3, two entries): fails closed", {"CLIENT_IP_FROM_RIGHT": "3"}, "rotate", 150, 121)
scenario("S8 global guard with rotating identifiers and broken attribution (FROM_RIGHT=1): stops at 300 by default", {"CLIENT_IP_FROM_RIGHT": "1"}, "rotate", 330, 301)
scenario("S9 global guard env honored (NEW_DEMOS_GLOBAL_PER_HOUR=10)", {"CLIENT_IP_FROM_RIGHT": "1", "NEW_DEMOS_GLOBAL_PER_HOUR": "10"}, "rotate", 40, 11)
def capacity(port, pport):
    jars = []
    for i in range(30):
        cj = hc.CookieJar(hc.DefaultCookiePolicy(secure_protocols=("https", "http"))); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj)); op.open(f"http://127.0.0.1:{pport}/api/demo/state", timeout=30).read(); op.open(f"http://127.0.0.1:{pport}/api/demo/state", timeout=30).read(); jars.append(op)   # second call = real use
    codes = [sessions(pport, 1)[0] for _ in range(6)]; refused = all(set(c) == {503} for c in codes)
    alive = sum(1 for op in jars if op.open(f"http://127.0.0.1:{pport}/api/demo/state", timeout=30).status == 200 and json.loads(op.open(f"http://127.0.0.1:{pport}/api/demo/state", timeout=30).read())["fresh"] is False)
    mem = sh("docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", f"gh-matrix-{len(results)}").stdout.split("/")[0].strip()
    return refused and alive == 30, f"at 30/30 active: new requests refused with 503 {refused}; existing sessions still usable {alive}/30 (none replaced: fresh=false); memory {mem}"
scenario("S10 capacity (DEMO_MAX_PROJECTS=30, active sessions): controlled 503, nobody evicted, memory bounded", {"CLIENT_IP_FROM_RIGHT": "2", "DEMO_MAX_PROJECTS": "30", "NEW_DEMOS_PER_HOUR": "500", "NEW_DEMOS_GLOBAL_PER_HOUR": "1000", "IP_REQUESTS_PER_MIN": "6000"}, "rotate", 0, None, fn=capacity)
def flood(port, pport):
    hit, first = sessions(pport, 30); full = sessions(pport, 1)[0]; time.sleep(22); after = sessions(pport, 1)[0]
    return full == {503: 1} and after == {200: 1}, f"30 never-used sessions fill the cap; next request {full}; after the 20 s untouched window a new session {after}"
scenario("S11 flood of never-used sessions frees its slots (DEMO_UNTOUCHED_TTL_SECONDS=20), capacity recovers", {"CLIENT_IP_FROM_RIGHT": "2", "DEMO_MAX_PROJECTS": "30", "DEMO_UNTOUCHED_TTL_SECONDS": "20", "NEW_DEMOS_PER_HOUR": "500", "NEW_DEMOS_GLOBAL_PER_HOUR": "1000", "IP_REQUESTS_PER_MIN": "6000"}, "rotate", 0, None, fn=flood)
bad = [r for r in results if not r[1]]; print(f"\n{len(results) - len(bad)} of {len(results)} scenarios as expected"); sys.exit(1 if bad else 0)

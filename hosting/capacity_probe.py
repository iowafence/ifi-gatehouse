#!/usr/bin/env python3
"""BOUNDED capacity, isolation and client-IP probe for a running Gatehouse judge demo (local container or a deployed URL). Read-mostly: it only calls the public demo
routes a judge uses (GETs, plus POST /api/demo/reset on its OWN session). No Evolus or AMD call is possible. Refuses the frozen demo's ports.
Usage: hosting/capacity_probe.py BASE_URL [--judges 20] [--walks 3] [--spoof]   (--spoof also tests that a forged X-Forwarded-For prefix does not open a new rate-limit bucket)"""
import http.cookiejar as _hc
import json, sys, threading, time, urllib.request, urllib.error, http.cookiejar, re, statistics, argparse
ap = argparse.ArgumentParser(); ap.add_argument("base"); ap.add_argument("--judges", type=int, default=20); ap.add_argument("--walks", type=int, default=3); ap.add_argument("--spoof", action="store_true"); ap.add_argument("--xff", choices=["none", "shared", "distinct"], default="none", help="emulate a proxy that writes the client address as the LAST X-Forwarded-For entry"); a = ap.parse_args()
base = a.base.rstrip("/")
if re.search(r":(5071|5051|8099|8098)\b", base): sys.exit("refusing the frozen demo's ports")
if a.judges > 60 or a.walks > 10: sys.exit("bounded: at most 60 judges and 10 walks")
def judge(extra=None):
    cj = http.cookiejar.CookieJar(_hc.DefaultCookiePolicy(secure_protocols=('https', 'http'))); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj)); op.addheaders = list((extra or {}).items())
    def call(path, body=None):
        t = time.perf_counter(); req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"} if body is not None else {})
        try:
            with op.open(req, timeout=30) as r: data = r.read(); code = r.status
        except urllib.error.HTTPError as e: data = e.read(); code = e.code
        except Exception as e: data = b""; code = 0
        return code, data, (time.perf_counter() - t) * 1000
    return call
WALK = ["/", "/api/demo/state", "/api/demo/scope-draft", "/api/demo/ai-findings", "/api/demo/documents", "/api/demo/takeoff", "/api/demo/flight-recorder", "/api/demo/portfolio", "/api/demo/health"]
lat, codes, lock = [], {}, threading.Lock()
def rec(code, ms):
    with lock: lat.append(ms); codes[code] = codes.get(code, 0) + 1
def run_judge(i):
    c = judge({} if a.xff == "none" else {"X-Forwarded-For": "203.0.113.9" if a.xff == "shared" else f"198.51.100.{i + 1}"})
    for _ in range(a.walks):
        for p in WALK: rec(*(lambda r: (r[0], r[2]))(c(p)))
        code, data, ms = c("/api/demo/documents"); rec(code, ms)
        try: docs = json.loads(data); ids = [d["doc_id"] if isinstance(d, dict) else d for d in (docs.get("documents", docs) if isinstance(docs, dict) else docs)]
        except Exception: ids = []
        for d in ids[:2]: rec(*(lambda r: (r[0], r[2]))(c(f"/api/demo/documents/{d}")))
        rec(*(lambda r: (r[0], r[2]))(c("/api/demo/reset", {})))
t0 = time.time(); ts = [threading.Thread(target=run_judge, args=(i,)) for i in range(a.judges)]
[t.start() for t in ts]; [t.join() for t in ts]; el = time.time() - t0
n = len(lat); s = sorted(lat)
print(json.dumps({"judges": a.judges, "walks": a.walks, "requests": n, "seconds": round(el, 1), "req_per_s": round(n / el, 1), "status_codes": codes, "p50_ms": round(statistics.median(s)), "p95_ms": round(s[int(n * .95) - 1]), "max_ms": round(s[-1])}))
# isolation: A's reset/changes never alter B
A, B = judge(), judge(); ca, da, _ = A("/api/demo/state"); cb, db, _ = B("/api/demo/state")
if ca == 200 and cb == 200:
    pa, pb = json.loads(da)["project"], json.loads(db)["project"]; A("/api/demo/reset", {}); _, db2, _ = B("/api/demo/state"); pb2 = json.loads(db2)["project"]
    print("isolation:", "PASS" if pa.get("project_id", pa.get("id")) != pb.get("project_id", pb.get("id")) and pb == pb2 else "FAIL", "(separate project ids; B unchanged after A reset)")
else: print("isolation: SKIPPED (state returned", ca, cb, ")")
# tampered cookie never yields someone else's project
cj = http.cookiejar.CookieJar(_hc.DefaultCookiePolicy(secure_protocols=('https', 'http'))); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj)); op.open(base + "/api/demo/state", timeout=20).read()
for c in cj: c.value = c.value[:-4] + ("AAAA" if not c.value.endswith("AAAA") else "BBBB")
try: code = op.open(base + "/api/demo/state", timeout=20).status
except urllib.error.HTTPError as e: code = e.code
print("tampered cookie: HTTP", code, "(must not return an existing project; a fresh one or a refusal is fine)")
if a.spoof:  # forged client-supplied prefix must not create fresh buckets: send many requests, each with a different forged leading XFF
    hit = {}; 
    for i in range(400):
        c = judge({"X-Forwarded-For": f"203.0.113.{i % 250}, 198.51.100.{i // 250}"}); code, _, _ = c("/api/demo/state"); hit[code] = hit.get(code, 0) + 1
    print("spoof (400 sessions, forged XFF prefixes):", hit, "-> 429s mean the forged prefix did NOT bypass the per-network new-session limit")

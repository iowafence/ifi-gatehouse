#!/usr/bin/env python3
"""Phase-4 verification of a RUNNING Gatehouse judge demo (local container or the deployed HTTPS URL). Read-only toward the service except its own session; no Evolus or AMD call.
Checks: health, HTTP->HTTPS redirect, headers (HSTS recorded, not required), public-path probes, every DP-001 PDF served with the registry hash, Flight Recorder content
(successful Evolus run RECORDED, HTTP 400 run separate and FAILED, AMD/Gemma NOT_REPORTED, D1 SUPPORTED-pending, D2 FLAGGED non-actionable, G3 clarification unapproved, audit pinned and
authenticated, no invented telemetry, historical evidence separate, original evidence sha256 unchanged), no write route to evidence, session isolation.
Usage: hosting/verify_live.py BASE_URL      (refuses the frozen demo's ports)      Exit 0 = every mandatory check passed."""
import hashlib, http.cookiejar as hc, json, re, ssl, sys, urllib.error, urllib.request
base = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else sys.exit(__doc__)
if re.search(r":(5071|5051|8099|8098)\b", base): sys.exit("refusing the frozen demo's ports")
fails, notes = [], []
def ok(c, m): print(("PASS  " if c else "FAIL  ") + m); (None if c else fails.append(m))
def info(m): print("INFO  " + m); notes.append(m)
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
def session():
    cj = hc.CookieJar(hc.DefaultCookiePolicy(secure_protocols=("https", "http"))); return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
def get(op, path, method="GET", data=None):
    req = urllib.request.Request(base + path, method=method, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        with op.open(req, timeout=30) as r: return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e: return e.code, e.read(), dict(e.headers)
op = session()
c, b, h = get(op, "/api/demo/health"); ok(c == 200 and b"responsive" in b, f"health endpoint 200 {b[:40]!r}")
c, b, h = get(op, "/"); ok(c == 200 and b"Gatehouse" in b, "main demo page loads")
hl = {k.lower(): v for k, v in h.items()}
for k in ("x-content-type-options", "x-frame-options", "referrer-policy", "permissions-policy", "content-security-policy"): ok(k in hl, f"header {k}")
info("HSTS: " + (hl.get("strict-transport-security") or "NOT PRESENT (record; platform layer should add it)")); info("server header: " + hl.get("server", "none"))
if base.startswith("https://"):
    try:
        no = urllib.request.build_opener(NoRedirect); r = no.open(urllib.request.Request("http://" + base[8:] + "/api/demo/health"), timeout=15); code, loc = r.status, ""
    except urllib.error.HTTPError as e: code, loc = e.code, e.headers.get("Location", "")
    except Exception as e: code, loc = 0, str(e)
    ok(code in (301, 302, 307, 308) and loc.startswith("https://"), f"http redirects to https ({code} {loc})")
for p in ("/.env", "/api/demo/documents/..%2f..%2fetc%2fpasswd", "/api/demo/documents/nope", "/traces", "/cases", "/dp001/independent_audits/AUDIT-GH-RUN-e5bbcecef551-2.json", "/release/x", "/RELEASE_SHA256SUMS", "/loom_reports/"):
    c, _, _ = get(op, p); ok(c == 404, f"probe {p} -> {c}")
c, b, _ = get(op, "/api/demo/state"); ok(c == 200 and b'"project"' in b, "session created; project present")
# documents: every registry PDF served, valid PDF, hash equals the registry hash
c, b, _ = get(op, "/api/demo/documents"); docs = json.loads(b)["documents"]; ok(len(docs) >= 4, f"{len(docs)} DP-001 documents listed")
for d in docs:
    c, body, hh = get(op, f"/api/demo/documents/{d['doc_id']}"); ok(c == 200 and body[:5] == b"%PDF-" and hashlib.sha256(body).hexdigest() == d["sha256"], f"document {d['doc_id']} renders (PDF, sha256 equals registry)")
# flight recorder
c, b, _ = get(op, "/api/demo/flight-recorder"); fr = json.loads(b); ok(c == 200 and fr["schema"].startswith("gatehouse-flight-recorder-view"), "flight recorder view served")
EXP = {"GH-TRACE-06b4b6d525133f8a": "5aa339ec1bf7022ba98b505ba4ae6776c47aa9605870df24286ed21c0fe9bef8", "GH-TRACE-2b2a7a1397a9599b": "8cd25c9761ed13528a067e42c69feaa49e6b4f2d0889ac0b23ddd7dd2020d6bd"}
ex = {x["trace_id"]: x for x in fr["executions"]}; ok(set(ex) == set(EXP), f"exactly the two authentic executions: {sorted(ex)}")
for t, s in EXP.items(): ok(ex[t]["sha256"] == s, f"{t} trace sha256 equals the original")
ok_, bad_ = ex["GH-TRACE-06b4b6d525133f8a"], ex["GH-TRACE-2b2a7a1397a9599b"]
L = lambda x: {l["layer"]: l["state"] for l in x["layers"]}
ok(ok_["outcome"] == "RECORDED" and L(ok_) == {"amd": "NOT_REPORTED", "gemma": "NOT_REPORTED", "evolus": "RECORDED"}, "successful Evolus execution RECORDED; AMD and Gemma NOT_REPORTED (no invented telemetry)")
ok(bad_["outcome"] == "FAILED" and not bad_.get("review") and L(bad_)["evolus"] == "FAILED", "earlier HTTP 400 execution is separate: FAILED, no review, no cases")
rv = ok_["review"]; cs = {c["draft_id"]: c for c in rv["cases"]}
ok(cs["D1"]["assessment"]["state"] == "SUPPORTED" and cs["D1"]["status"] == "PENDING_HUMAN_REVIEW" and cs["D1"]["approval_status"] == "NOT_APPROVED" and cs["D1"]["sent_externally"] is False, "D1 pending, unapproved, unsent (SUPPORTED = eligible for human review only)")
ok(cs["D2"]["assessment"]["state"] == "FLAGGED" and cs["D2"]["assessment"]["actionable"] is False and cs["D2"]["approval_status"] == "NOT_APPROVED", "D2 FLAGGED and not actionable")
au = rv["audit"]; ok(au["is_human_decision"] is False and au["human_authorization_status"] == "NONE_RECORDED", "audit is not a human decision; human authorization NONE_RECORDED")
ok(au["audit_id"].endswith("-2") and au["sha256"] == "b68748fecf9e9986ecceead9b428c5330471c59857ab88a7cedbd8b6f9f734b8" and au["pinned"]["report_verified"] is True and au["pinned"]["report_sha256"] == "d6040e169d374b03f3b8336f4d255d31fd892ee08bcb7b201d3273b26aeabf05", "pinned audit authenticates (bytes equal the release manifest; bundled LOOM report verified)")
ok(any(s["sha256"] == "1e4f1c196cdaa91659d76eb8529e2a7bda489f5d8161247d8361d7f76387371b" for s in au["pinned"]["superseded"]), "superseded audit -1 retained unchanged")
pc = au["proposed_clarifications"]; ok(len(pc) == 1 and pc[0]["approved"] is False and pc[0]["sent"] is False and pc[0]["evolus_generated"] is False, "G3 post-OD clarification proposed, unapproved, unsent, not an Evolus case")
ok({f["item"]: f["status"] for f in au["scope_findings"]} == {"G3_CLEAR_OPENING_WIDTH": "UNRESOLVED", "G3_POST_OD": "UNRESOLVED", "G3_FOOTING": "SPECIFIED"}, "G3 scope findings as audited")
ok(all(s["accepted"] for s in fr["sources"]), "every trace, case and audit source accepted (no REJECTED)")
dump = json.dumps(fr)
ok(not re.search(r"/home/|/app/|/tmp/|\b(10|192\.168)\.\d+\.\d+\.\d+\b|api[_-]?key|Bearer ", dump), "recorder output exposes no server paths, internal addresses or credentials")
ok(not re.search(r"gpu_util|tokens_per_s|ttft", json.dumps([ok_["layers"], bad_["layers"]]), re.I), "no inference telemetry in the Evolus executions")
hist = fr["historical"]; ok(hist and any(l["layer"] in ("amd", "gemma") for l in hist["layers"]), "historical AMD/Gemma evidence present and separate from the executions")
# no write path to evidence
for m in ("POST", "PUT", "PATCH", "DELETE"):
    for p in ("/api/demo/flight-recorder", "/api/demo/documents/dp001_ansi_b_v2_drawings", "/traces/GH-TRACE-06b4b6d525133f8a.json"):
        c, _, _ = get(op, p, m, b"{}"); ok(c in (404, 405, 401), f"{m} {p} -> {c} (evidence not writable)")
c, b2, _ = get(op, "/api/demo/flight-recorder"); fr2 = json.loads(b2); ok({x["trace_id"]: x["sha256"] for x in fr2["executions"]} == EXP, "evidence hashes unchanged after the write attempts")
# isolation
A, B = session(), session(); pa = json.loads(get(A, "/api/demo/state")[1])["project"]; pb = json.loads(get(B, "/api/demo/state")[1])["project"]; get(A, "/api/demo/reset", "POST", b"{}")
ok(pa["project_id"] != pb["project_id"] and json.loads(get(B, "/api/demo/state")[1])["project"] == pb, "judge sessions are isolated (A's reset leaves B unchanged)")
print(f"\n{'ALL MANDATORY CHECKS PASSED' if not fails else str(len(fails)) + ' CHECK(S) FAILED'}")
for n in notes: print("  note:", n)
sys.exit(1 if fails else 0)

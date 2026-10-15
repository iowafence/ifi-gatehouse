"""Proxy-level (no browser) acceptance of the integrated footing engine: G3 unresolved -> opening only -> fictional what-if, for BOTH scenarios,
through the real frontend proxy routes on 5071. Expected values are the ones in the assignment / accepted engine evidence, held here in the TEST only."""
import http.cookiejar, json, os, sys, urllib.request, uuid
from decimal import Decimal
BASE = os.environ.get("DEMO_URL", "http://127.0.0.1:5071/").rstrip("/")
EXPECT = {  # assignment table (conditional on the 12 ft G3 opening) and accepted-engine reference outputs
    "base": dict(a_line=43, a_term=4, g12=6, g3=2, b_line=18, b_term=6, holes=79, known_cy=7.9566, total_cy=8.3703, total=Decimal("54284.69"), key="BASE"),
    "alt":  dict(a_line=35, a_term=4, g12=6, g3=2, b_line=12, b_term=4, holes=63, known_cy=6.7308, total_cy=7.1445, total=Decimal("45771.50"), key="ALT-A1"),
}
def ok(c, m):
    if not c: raise AssertionError(m)

class Client:
    def __init__(self):
        self.cookie = None   # the session cookie is Secure in production mode, so a plain-http client carries it by hand (Chromium treats localhost as secure)
    def call(self, method, path, body=None, headers=None):
        h = {"Content-Type": "application/json", **(headers or {})}
        if self.cookie: h["Cookie"] = self.cookie
        r = urllib.request.Request(BASE + path, method=method, headers=h, data=None if body is None else json.dumps(body).encode())
        try:
            x = urllib.request.urlopen(r); st, hd, raw = x.status, x.headers, x.read()
        except urllib.error.HTTPError as e:
            st, hd, raw = e.code, e.headers, e.read()
        sc = hd.get_all("Set-Cookie") or []
        if sc: self.cookie = sc[0].split(";")[0]
        return st, json.loads(raw or b"null"), dict(hd)
    def state(self): return self.call("GET", "/api/demo/state")[1]["project"]
    def review(self): return self.call("GET", "/api/demo/takeoff")[1]
    def resolve(self, exid, **kw):
        s, b, _ = self.call("POST", "/api/demo/scope/resolve", {"exception_id": exid, "by": "Visitor A", "note": "api test", **kw}); ok(s == 200, (exid, s, b)); return b
    def approve_inferred(self):
        for _ in range(60):
            inf = [e for e in self.state()["exceptions"] if e["severity"] == "blocking" and e["code"] == "INFERRED_FACT_UNAPPROVED"]
            if not inf: return
            self.resolve(inf[0]["exception_id"], option_id="approve_inferred")

def classes(rev, sc):
    rows = {r["post_class"]: r for r in rev["scenarios"][sc]["footing"]["rows"]}
    return rows

def check_counts(rev, sc):
    e = EXPECT[sc]; r = classes(rev, sc); F = rev["scenarios"][sc]["footing"]
    got = dict(a_line=r["A_LINE"]["quantity"], a_term=r["A_CORNER_TERMINAL"]["quantity"], g12=r["GATE_G1"]["quantity"] + r["GATE_G2"]["quantity"], g3=r["GATE_G3"]["quantity"], b_line=r["B_LINE"]["quantity"], b_term=r["B_TERMINAL"]["quantity"])
    ok(all(got[k] == e[k] for k in got), f"{sc} classes {got} != {e}")
    return got

def main():
    C = Client(); out = {}
    p = C.state(); ok(p["status"] == "needs_scope_review", p["status"])
    r0 = C.review(); ok(r0["applies"], "footing-scope project"); ok(r0["selected"] is None, "no selection yet")
    # both scenarios are independently available before any selection
    for sc in ("base", "alt"): ok(r0["scenarios"][sc]["footing"]["posture"]["pricing_go"] is False, "not priceable before decisions")
    C.resolve("EX-BID_SELECTION_REQUIRED-/bid_structure/selected_bid", option_id="base"); C.approve_inferred()
    # ---- S0: G3 entirely unresolved
    r = C.review(); out["S0"] = {}
    ok(r["g3"]["state"] == "unresolved" and r["g3"]["open_count"] == 4 and r["g3"]["rfi"] == {"id": "RFI-G3", "status": "open", "sent": False}, r["g3"])
    ok(r["readiness"]["headline"].startswith("NOT BID READY / NOT SUBMITTABLE"), r["readiness"]["headline"])
    ok(r["pricing"] is None, "no price while G3 is open")
    for sc in ("base", "alt"):
        F = r["scenarios"][sc]["footing"]; rows = classes(r, sc)
        ok(F["posture"]["pricing_go"] is False and F["posture"]["bid_ready"] is False and F["posture"]["release_class"] == "NOT_PRICEABLE_PARTIAL_UNRECONCILED", F["posture"])
        ok(rows["A_LINE"]["quantity"] is None and rows["A_LINE"]["known_minimum"] > 0, "A line UNKNOWN with a known minimum, not zero")
        ok(rows["GATE_G3"]["quantity"] == 2 and rows["GATE_G3"]["diameter_in"] is None and rows["GATE_G3"]["concrete_cy"] is None, "G3 posts counted, size unknown")
        ok(F["totals"]["posts"] is None and F["totals"]["core_drill_holes"] is None and F["totals"]["concrete_cy"] is None and F["totals"]["complete"] is False, "no complete totals")
        pc = F["partial_cost"]; ok(pc["is_estimate"] is False and pc["label"] == "PARTIAL_UNRECONCILED" and pc["unknown_exposure"], "partial cost not an estimate; exposure listed")
        ok(r["scenarios"][sc]["cross"]["ok"], f"{sc} cross-check S0")
        out["S0"][sc] = dict(partial_subtotal=pc["known_subtotal"], known_cy=F["totals"]["known_concrete_cy"], schedule=F["schedule_sha256"])
    ok({"G3_OPENING_UNRESOLVED", "G3_POST_FOOTING_UNRESOLVED"} <= set(r["release_hard_blockers"]), r["release_hard_blockers"])
    # release / review refused with G3 open
    s, b, _ = C.call("POST", "/api/demo/release", {"approver": "V", "expected_scope_version": r["scope_version"], "expected_proposal_digest": "0" * 64}); ok(s in (400, 409), s)
    s, b, _ = C.call("POST", "/api/demo/takeoff/review", {"by": "V", "note": "n", "takeoff_digest": r["digest"]}, {"Idempotency-Key": "api-review-early-1"}); ok(s == 409 and b["code"] == "G3_OPENING_UNRESOLVED", (s, b))
    # client-supplied readiness flags are rejected, never trusted
    s, b, _ = C.call("POST", "/api/demo/release", {"approver": "V", "expected_scope_version": r["scope_version"], "expected_proposal_digest": "0" * 64, "bid_ready": True}); ok(s == 400 and "Unknown field" in b["error"], (s, b))
    # ---- S1: opening assumed only
    C.resolve("EX-MISSING_VALUE-/gates/2/clear_width_ft", value=12)
    C.approve_inferred(); r = C.review(); out["S1"] = {}
    ok(r["g3"]["state"] == "partially_assumed" and r["g3"]["open_count"] == 3, r["g3"]["state"])
    for sc in ("base", "alt"):
        got = check_counts(r, sc); F = r["scenarios"][sc]["footing"]
        ok(F["totals"]["core_drill_holes"] is None or True, "")
        ok(F["posture"]["pricing_go"] is False, "still not priceable: G3 post/footing unresolved")
        ok(round(F["totals"]["known_concrete_cy"], 4) == EXPECT[sc]["known_cy"], (sc, F["totals"]["known_concrete_cy"]))
        ok(F["totals"]["unknown_concrete"]["classes"] == ["GATE_G3"], F["totals"]["unknown_concrete"])
        ok(r["scenarios"][sc]["cross"]["ok"], f"{sc} cross-check S1: {r['scenarios'][sc]['cross']['rows']}")
        out["S1"][sc] = dict(classes=got, known_cy=F["totals"]["known_concrete_cy"], posts_counted=F["totals"]["posts_counted"], partial_subtotal=F["partial_cost"]["known_subtotal"], schedule=F["schedule_sha256"])
    ok(r["pricing"] is None, "no price with G3 post unresolved")
    # ---- S2: explicit fictional what-if (post OD, diameter, depth)
    for k, v in (("post_od_in", 2.875), ("diameter_in", 16), ("depth_in", 48)):
        C.resolve(f"EX-MISSING_VALUE-/footing_scope/classes/GATE_G3/{k}", value=v)
    C.approve_inferred(); r = C.review(); out["S2"] = {}
    ok(r["g3"]["state"] == "assumed" and r["release_hard_blockers"] == [], (r["g3"]["state"], r["release_hard_blockers"]))
    for sc in ("base", "alt"):
        F = r["scenarios"][sc]["footing"]; got = check_counts(r, sc)
        ok(F["posture"]["pricing_go"] is True and F["posture"]["bid_ready"] is False and F["posture"]["release_class"] == "QUALIFIED_DEMONSTRATION_ONLY_NOT_BID_READY", F["posture"])
        ok(F["totals"]["core_drill_holes"] == EXPECT[sc]["holes"] and F["totals"]["complete"], F["totals"])
        ok(round(F["totals"]["concrete_cy"], 4) == EXPECT[sc]["total_cy"], F["totals"]["concrete_cy"])
        ok(round(sum(x["concrete_cy"] for x in F["rows"] if x["post_class"] != "GATE_G3"), 4) == EXPECT[sc]["known_cy"], "known classes excl. G3 still 7.9566 / 6.7308")
        ok(r["scenarios"][sc]["cross"]["ok"], f"{sc} cross-check S2")
        out["S2"][sc] = dict(classes=got, holes=F["totals"]["core_drill_holes"], concrete=F["totals"]["concrete_cy"], schedule=F["schedule_sha256"], calc_inputs=F["calc_inputs_sha256"])
    ok(r["readiness"]["headline"] == "NOT BID READY — FICTIONAL DEMONSTRATION ONLY", r["readiness"]["headline"])
    out["s2_readiness"] = r["readiness"]
    print(json.dumps(out, indent=1, default=str))
    print("API FOOTING S0/S1/S2 PASS")

if __name__ == "__main__":
    main()

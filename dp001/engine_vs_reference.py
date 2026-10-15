"""Engine footing schedule (accepted footing-repair engine, port 8099, direct HTTP) versus the independent reference for a sweep of G3 openings.
For each opening one fresh project is created (Base selected -> the engine returns BASE and ALT-A1 schedules) and per-class counts / holes / net are compared.
Where the reference refuses a geometry (assumed gates overlap), the engine must refuse as well (no quantity). Prints JSON; exit 1 on any mismatch."""
import json, os, pathlib, sys, uuid, urllib.request
from decimal import Decimal as D
HOME = pathlib.Path.home(); WS = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WS / "dp001/reference")); from dp001_takeoff_review import reconcile as REF
env = dict(l.strip().split("=", 1) for l in (WS / "run/engine.env").read_text().splitlines() if "=" in l and not l.startswith("#"))
KEY, B, OWN = env["ENGINE_API_KEY"], "http://127.0.0.1:8099/", "c" * 64
def call(m, p, body=None, idem=None):
    h = {"X-Engine-Key": KEY, "X-Demo-Owner": OWN, "Content-Type": "application/json"}
    if idem: h["Idempotency-Key"] = idem
    r = urllib.request.Request(B + p, method=m, headers=h, data=None if body is None else json.dumps(body).encode())
    try:
        x = urllib.request.urlopen(r); return x.status, json.load(x)
    except urllib.error.HTTPError as e: return e.code, json.load(e)
def run(g3):
    pid = call("POST", "demo/projects", {})[1]["project_id"]
    def res(exid, **kw): return call("POST", f"projects/{pid}/scope/resolve", {"exception_id": exid, "by": "sweep (self-declared)", "note": "G3 sweep, fictional", **kw}, str(uuid.uuid4()))
    res("EX-BID_SELECTION_REQUIRED-/bid_structure/selected_bid", option_id="base")
    def inferred():
        for _ in range(60):
            p = call("GET", f"projects/{pid}")[1]; inf = [e for e in p["exceptions"] if e["severity"] == "blocking" and e["code"] == "INFERRED_FACT_UNAPPROVED"]
            if not inf: return p
            res(inf[0]["exception_id"], option_id="approve_inferred")
    inferred(); s, b = res("EX-MISSING_VALUE-/gates/2/clear_width_ft", value=float(g3)); p = inferred()
    return s, b, p
def ref_counts(scn, g3):
    r = REF(scn, D(str(g3))); ta, tb = r["type_a_post_count"], r["type_b_post_count"]
    return {"A_LINE": ta["line"], "A_CORNER_TERMINAL": ta["corners"], "GATE_G12": ta["gate_posts_total"] - ta["gate_posts_unknown_size_g3"], "GATE_G3": ta["gate_posts_unknown_size_g3"], "B_LINE": tb["line"], "B_TERMINAL": tb["terminals"], "holes": r["total_core_drill_holes"], "net_a": float(r["net_type_a_lf"])}
out, bad = [], []
for g3 in (4, 6, 8, 10, 12, 14, 16, 20, 25, 30, 40, 50, 60):
    refusals = {}
    for scn in ("base", "alternate_a1"):
        try: ref_counts(scn, g3); refusals[scn] = None
        except Exception as e: refusals[scn] = str(e)[:60]
    s, b, p = run(g3); fp = (p.get("pricing") or {}).get("footing") or {}
    row = {"g3_ft": g3, "engine_resolve_http": s}
    for scn, key in (("base", "BASE"), ("alternate_a1", "ALT-A1")):
        f = fp.get(key)
        if refusals[scn]:
            ok = (s != 200) or f is None or any(e["code"] == "GEOMETRY_INVALID" for e in p["exceptions"]) or f["totals"]["posts"] is None
            row[scn] = {"reference": "REFUSED", "engine": "refused/no quantity" if ok else "QUANTITIES PRODUCED", "ok": ok}
        else:
            rc = ref_counts(scn, g3); q = {c["post_class"]: c["quantity"] for c in f["classes"]} if f else {}
            got = {"A_LINE": q.get("A_LINE"), "A_CORNER_TERMINAL": q.get("A_CORNER_TERMINAL"), "GATE_G12": (q.get("GATE_G1") or 0) + (q.get("GATE_G2") or 0), "GATE_G3": q.get("GATE_G3"), "B_LINE": q.get("B_LINE"), "B_TERMINAL": q.get("B_TERMINAL")}
            holes = sum(v for v in got.values() if v is not None)
            ok = f is not None and all(got[k] == rc[k] for k in got) and holes == rc["holes"]
            row[scn] = {"engine": {**got, "holes": holes}, "reference": {k: rc[k] for k in got} | {"holes": rc["holes"]}, "ok": ok}
        if not row[scn]["ok"]: bad.append((g3, scn))
    out.append(row)
print(json.dumps({"cases": len(out) * 2, "mismatches": bad, "rows": out}, indent=1))
sys.exit(1 if bad else 0)

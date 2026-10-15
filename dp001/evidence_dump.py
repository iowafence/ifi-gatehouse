"""Evidence dump straight from the accepted footing engine (direct HTTP, port 8099; fictional data): per-scenario footing schedules in the three G3 states
(S0 unresolved / S1 opening only / S2 explicit fictional what-if), the engine-calculated pricing breakdown for the what-if under the accepted-engine reference
inputs (FDB-DP001 wage record, crew plan CR13 preferred + CR13 drilling), the same under the UI's earlier CR12 plan (to identify the crew-plan difference), and
the HTTP release response. Writes evidence/footing_engine_dump.json and evidence/FOOTING_SCHEDULES.md. The UI never computes any of this."""
import json, os, pathlib, sys, uuid
WS = pathlib.Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True; sys.path.insert(0, str(WS))
import urllib.request
from tests.test_ratebook_workflow import wage_args            # the accepted reference wage record (FDB-DP001 mod 0)
env = dict(l.strip().split("=", 1) for l in (WS / "run/engine.env").read_text().splitlines() if "=" in l and not l.startswith("#"))
KEY, B, OWN = env["ENGINE_API_KEY"], "http://127.0.0.1:8099/", "d" * 64
def call(m, p, body=None, idem=None):
    h = {"X-Engine-Key": KEY, "X-Demo-Owner": OWN, "Content-Type": "application/json"}
    if idem: h["Idempotency-Key"] = idem
    r = urllib.request.Request(B + p, method=m, headers=h, data=None if body is None else json.dumps(body).encode())
    try:
        x = urllib.request.urlopen(r); return x.status, json.load(x)
    except urllib.error.HTTPError as e: return e.code, json.load(e)
WHO = {"by": "Evidence script (self-declared, fictional)", "note": "evidence dump; fictional what-if values"}
def project(bid):
    pid = call("POST", "demo/projects", {})[1]["project_id"]
    def res(exid, **kw):
        s, b = call("POST", f"projects/{pid}/scope/resolve", {"exception_id": exid, **WHO, **kw}, str(uuid.uuid4())); assert s == 200, (exid, s, b)
    def inferred():
        for _ in range(60):
            p = call("GET", f"projects/{pid}")[1]; inf = [e for e in p["exceptions"] if e["severity"] == "blocking" and e["code"] == "INFERRED_FACT_UNAPPROVED"]
            if not inf: return
            res(inf[0]["exception_id"], option_id="approve_inferred")
    res("EX-BID_SELECTION_REQUIRED-/bid_structure/selected_bid", option_id=bid); inferred()
    return pid, res, inferred
def slim(fp):
    return {"schedule_sha256": fp["schedule_sha256"], "calc_inputs_sha256": fp["calc_inputs_sha256"], "posture": fp["posture"], "totals": fp["totals"],
            "records": [{k: r[k] for k in ("run_id", "post_class", "role", "owner", "quantity", "quantity_known_minimum", "diameter_in", "depth_in", "post_od_in", "concrete_cy", "core_drill_holes", "value_basis", "unknown_reason")} | {"review_state": r["review"]["state"]} for r in fp["records"]],
            "partial_cost": {k: fp["partial_cost"][k] for k in ("label", "is_estimate", "known_subtotal", "by_class", "unknown_exposure") if k in fp["partial_cost"]}}
out = {}
pid, res, inferred = project("base")
def snap(tag):
    p = call("GET", f"projects/{pid}")[1]; out[tag] = {k: slim(v) for k, v in p["pricing"]["footing"].items()}; out[tag + "_blocking"] = [e["exception_id"] for e in p["exceptions"] if e["severity"] == "blocking"]; return p
snap("S0_g3_unresolved")
res("EX-MISSING_VALUE-/gates/2/clear_width_ft", value=12); inferred(); snap("S1_opening_12_only")
for k, v in (("post_od_in", 2.875), ("diameter_in", 16), ("depth_in", 48)): res(f"EX-MISSING_VALUE-/footing_scope/classes/GATE_G3/{k}", value=v)
inferred(); snap("S2_fictional_whatif")
def price(bid, pref):
    pid2, res2, inf2 = project(bid)
    res2("EX-MISSING_VALUE-/gates/2/clear_width_ft", value=12); inf2()
    for k, v in (("post_od_in", 2.875), ("diameter_in", 16), ("depth_in", 48)): res2(f"EX-MISSING_VALUE-/footing_scope/classes/GATE_G3/{k}", value=v)
    inf2(); p = call("GET", f"projects/{pid2}")[1]
    sha = next(e["required_decision"]["sha256"] for e in p["exceptions"] if e["code"] == "QUANTITY_RULESET_UNAPPROVED")
    for path, body in (("decisions/ruleset-approval", {**WHO, "ruleset_sha256": sha}), ("decisions/wage-determination", wage_args()),
                       ("decisions/crew-plan", {**WHO, "preferred_crew": pref, "assignments": {"L02": "CR13"}, "use_default_for_unassigned": False, "difficulty": {"default": "standard", "overrides": {}}})):
        s, b = call("POST", f"projects/{pid2}/{path}", body, str(uuid.uuid4())); assert s == 200, (path, s, b)
    p = call("GET", f"projects/{pid2}")[1]; ev = p["pricing"]["estimate_view"]
    return pid2, p, {"scope_ref": ev["scope_ref"], "price_total": ev["price_total"], "fence_lf": ev["fence_lf"], "breakdown": ev["breakdown"], "labor_lines": [{k: l[k] for k in ("task_id", "task", "uom", "quantity", "crew_id", "extended")} for l in ev["labor_lines"]],
                     "economics": {k: p["pricing"]["economics"][k] for k in p["pricing"]["economics"] if isinstance(p["pricing"]["economics"][k], (int, float))},
                     "ratebook": p["pricing"]["ratebook_ref"], "wage": {k: p["pricing"]["wage"].get(k) for k in ("decision_id", "cleared", "required")}, "crew_plan_preferred": pref,
                     "posture": p["pricing"]["footing"][ev["scope_ref"]]["posture"], "proposal_digest": p["proposal_digest"], "scope_version": p["scope_version"], "qualifications_footing": [q for q in ev["qualifications"] if "footing scope is" in q]}
out["pricing"] = {}
for bid in ("base", "ALT-A1"):
    pid2, p, d = price(bid, "CR13"); out["pricing"][bid + "_reference_inputs_CR13"] = d
    if bid == "base":
        r = call("POST", f"projects/{pid2}/release", {"approver": "Evidence script", "expected_scope_version": p["scope_version"], "expected_proposal_digest": p["proposal_digest"], "note": "evidence: client bid_ready is ignored", "bid_ready": True})
        out["release_http"] = {"status": r[0], "response": {k: v for k, v in r[1].items() if k != "qualifications"}, "footing_qualification_text": [q for q in r[1].get("qualifications", []) if isinstance(q, str)]}
    pid3, p3, d3 = price(bid, "CR12"); out["pricing"][bid + "_ui_crew_plan_CR12"] = {"price_total": d3["price_total"], "note": "identical engine, rate book, wage record and quantities; only the preferred crew differs (CR12 instead of CR13)"}
(WS / "evidence/footing_engine_dump.json").write_text(json.dumps(out, indent=1, default=str))
# ---- markdown schedules
L = ["# DP-001 footing schedules (engine footing-calc.v1 output; PROVISIONAL geometry)", "", "Source: accepted footing engine, direct HTTP, fictional data. G3 values in S1/S2 are SELF-DECLARED, NOT document facts. Counts are provisional; concrete in CY; cost basis is engine unit rates (S01 flat per hole; M40 one rate).", ""]
for tag, label in (("S0_g3_unresolved", "S0 — G3 entirely unresolved"), ("S1_opening_12_only", "S1 — G3 opening 12 ft assumed; G3 post/footing unresolved"), ("S2_fictional_whatif", "S2 — explicit fictional what-if (12 ft · 2.875 in OD · 16 × 48 in)")):
    L += [f"## {label}", ""]
    for sc in ("BASE", "ALT-A1"):
        f = out[tag][sc]; t = f["totals"]; po = f["posture"]
        L += [f"### {sc}", "", f"schedule_sha256 `{f['schedule_sha256']}` · calc_inputs_sha256 `{f['calc_inputs_sha256']}`", f"posture: pricing_go={po['pricing_go']} bid_ready={po['bid_ready']} release_class={po['release_class']}", "",
              "| Class | Run | Owner | Count | Ø × depth (in) | Concrete (CY) | Core holes | Basis | Review |", "|---|---|---|---:|---|---:|---:|---|---|"]
        for r in f["records"]:
            q = r["quantity"] if r["quantity"] is not None else f"UNKNOWN (≥ {r['quantity_known_minimum']})"
            dd = f"{r['diameter_in']:g} × {r['depth_in']:g}" if r["diameter_in"] is not None else "UNKNOWN"
            L.append(f"| {r['post_class']} | {r['run_id']} | {r['owner']} | {q} | {dd} | {r['concrete_cy'] if r['concrete_cy'] is not None else 'UNKNOWN'} | {r['core_drill_holes'] if r['core_drill_holes'] is not None else 'UNKNOWN'} | {r['value_basis']} | {r['review_state']} |")
        L += ["", f"Totals: posts {t['posts']}, holes {t['core_drill_holes']}, concrete {t['concrete_cy']}, known-class concrete {t['known_concrete_cy']} CY, complete={t['complete']}; unknown classes: {t['unknown_concrete']['classes']}", "",
              f"Partial known cost ({f['partial_cost']['label']}, is_estimate={f['partial_cost']['is_estimate']}): ${f['partial_cost']['known_subtotal']:,.2f}", ""]
L += ["## Engine-calculated pricing (fictional what-if, accepted-engine reference inputs)", ""]
for k, d in out["pricing"].items():
    if k.endswith("CR13"):
        L += [f"### {d['scope_ref']} — total ${d['price_total']:,.2f} (fence LF {d['fence_lf']})", "", "| Line | Amount |", "|---|---:|"] + [f"| {b['label']} | ${b['amount']:,.2f} |" for b in d["breakdown"]] + ["", f"posture: {d['posture']['release_class']} · bid_ready={d['posture']['bid_ready']}", ""]
L += ["Crew-plan sensitivity (same engine/inputs, only the preferred crew differs): " + ", ".join(f"{k} ${v['price_total']:,.2f}" for k, v in out["pricing"].items() if k.endswith("CR12")), ""]
(WS / "evidence/FOOTING_SCHEDULES.md").write_text("\n".join(L))
print("wrote footing_engine_dump.json and FOOTING_SCHEDULES.md;", {k: v.get("price_total") for k, v in out["pricing"].items()})

"""TEST HARNESS ONLY. The G3 values below are throwaway test inputs on a disposable project; they are not G3 answers and no total from this script is a bid figure.
Proxy-level (no browser) walk of the DP-001 operator path to a RECORDED release, through the real frontend routes.
Mirrors the UI steps of e2e_dp001.py: Base Bid -> approve derivations -> G3 what-if -> ruleset -> wage -> crew plan -> takeoff review -> release.
Prints the final project summary as JSON on stdout (step log on stderr). All identities are self-declared demo names; the G3 values are the fictional what-if."""
import json, os, sys, uuid
sys.path.insert(0, os.path.dirname(__file__))
import api_footing as A

BY = "Walk Script"
FICT_SCHED = [("Laborer, common or general", 24.50, 9.10), ("Power equipment operator, skid steer", 29.80, 11.25), ("Cement mason, concrete finisher", 28.40, 10.70)]
ROLE_CLASS = {"R1": 0, "R2": 0, "R3": 0, "R4": 1}

def log(m): print(m, file=sys.stderr)

def decide(C, route, body):
    s, b, _ = C.call("POST", f"/api/demo/decision/{route}", body, {"Idempotency-Key": f"walk-{route}-{uuid.uuid4()}"})
    A.ok(s == 200, (route, s, b)); return b

def walk(select="base", plan_note="walk"):
    C = A.Client(); C.state()
    sel = {"base": "base", "alt": "ALT-A1"}[select]
    C.resolve("EX-BID_SELECTION_REQUIRED-/bid_structure/selected_bid", option_id=sel); C.approve_inferred()
    for path, v in (("/gates/2/clear_width_ft", 12), ("/footing_scope/classes/GATE_G3/post_od_in", 2.875), ("/footing_scope/classes/GATE_G3/diameter_in", 16), ("/footing_scope/classes/GATE_G3/depth_in", 48)):
        ex = [e for e in C.state()["exceptions"] if e["severity"] == "blocking" and path in e["affects"]]
        if ex: C.resolve(ex[0]["exception_id"], value=v, source_note="TEST HARNESS ONLY: automated-test placeholder, not a document fact and not a G3 answer", note="test harness")
    C.approve_inferred(); log("scope cleared")
    p = C.state()
    decide(C, "ruleset", {"by": BY, "note": "Reviewed the rule table (demo)", "ruleset_sha256": p["pricing"]["ruleset"]["sha256"]}); log("ruleset approved (draft, self-declared)")
    roles = C.state()["pricing"]["wage"]["roles"]
    decide(C, "wage", {"by": BY, "note": "Transcribed from the fictional wage decision",
        "determination": {"decision_id": "FDB-DP001", "modification": "0", "date": "2026-10-05", "valid_through": "2026-12-31", "source_ref": "Fictional wage decision, Attachment A"},
        "schedule": [{"classification": c, "base_rate": b, "fringe_rate": f} for c, b, f in FICT_SCHED],
        "rows": [{"role_key": k, "classification": FICT_SCHED[ROLE_CLASS.get(k, 0)][0], "classification_status": "listed", "base_rate": FICT_SCHED[ROLE_CLASS.get(k, 0)][1], "fringe_rate": FICT_SCHED[ROLE_CLASS.get(k, 0)][2], "source_ref": "Fictional wage decision, Attachment A"} for k in roles],
        "employer_burden": {"pct": 0.20, "source_ref": "Fictional payroll cost sheet"}, "production_rates_approved": True,
        "certified_payroll_admin": {"basis": "per_week", "unit_cost": 85, "weeks": 4, "source_ref": "Fictional payroll administrator quote"}}); log("wage recorded")
    decide(C, "crew-plan", {"by": BY, "note": plan_note, "preferred_crew": "CR12", "assignments": {"L02": "CR13"}, "use_default_for_unassigned": False, "difficulty": {"default": "standard", "overrides": {}}}); log("crew plan approved")
    p = C.state(); A.ok(p["status"] == "ready_for_final_review" and p["proposal_digest"], p["status"])
    rv = C.review()
    s, b, _ = C.call("POST", "/api/demo/takeoff/review", {"by": BY, "note": "Checked deductions against C101 and F502", "takeoff_digest": rv["digest"]}, {"Idempotency-Key": f"walk-review-{uuid.uuid4()}"})
    A.ok(s == 200, (s, b)); rv = C.review(); log("takeoff reviewed")
    return C, rv

def release(C, rv):
    p = C.state()
    ack = rv.get("release_ack_required") or []
    s, b, _ = C.call("POST", "/api/demo/release", {"approver": BY, "expected_scope_version": p["scope_version"], "expected_proposal_digest": p["proposal_digest"], "note": "walk",
                     "takeoff_digest": rv["digest"], "acknowledged_blockers": ack})
    return s, b

if __name__ == "__main__":
    C, rv = walk(sys.argv[1] if len(sys.argv) > 1 else "base")
    s, b = release(C, rv); log(f"release -> {s}")
    if s != 200: log(json.dumps(b)[:800]); sys.exit(1)
    print(json.dumps({"release": b, "project": C.state()}))

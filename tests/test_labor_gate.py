"""Labor Gate (Gate 2) and cross-gate invalidation."""
import copy, json, pathlib, unittest
from engine import workflow as wf

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCOPE = json.load(open(ROOT / "samples/scope_synthetic.json"))
RATES = json.load(open(ROOT / "config/rates.example.json"))
BID = "EX-BID_SELECTION_REQUIRED-/bid_structure/selected_bid"
H42 = "EX-PLAN_SPEC_CONFLICT-/fence_runs/1/height_ft"
GUARD = "EX-PLAN_SPEC_CONFLICT-/accessories/1/applies_to_gates"
WHO = dict(by="Test Reviewer", note="test decision")


def scope_done(policy=None):
    s = wf.start(SCOPE, RATES, policy=policy)
    s = wf.resolve(s, BID, option_id="base", **WHO)
    s = wf.resolve(s, H42, option_id="v:3.5", **WHO)
    return wf.resolve(s, GUARD, option_id="v:no", **WHO)


STANDARD = dict(by="Test Reviewer", decision="verified_standard", certified_payroll=False,
                applicability_review="Checked the fictional contract for wage clauses; none found; owner confirmed",
                source_refs=["fictional-owner-email-1"], note="test")
ASSUMED = dict(by="Test Reviewer", decision="human_assumption_with_qualification", certified_payroll="unknown",
               applicability_review="No wage schedule in documents; external applicability not verified",
               qualification="Pricing uses company rates subject to confirmation of wage obligations",
               note="Estimating assumption only, not a legal determination")
FEDERAL = dict(by="Test Reviewer", decision="verified_federal", certified_payroll=True,
               applicability_review="Wage determination attached to fictional bid", wage_basis="federal_prevailing",
               source_refs=["WD-FICTIONAL-1"], classifications=["Fence erector"], loaded_hourly_rate=61.5, note="test")


class LaborGate(unittest.TestCase):
    def test_scope_resolved_without_labor_decision_has_no_price(self):
        s = scope_done()
        self.assertEqual(s["status"], "needs_labor_review")
        self.assertIsNotNone(s["takeoff"])  # provisional quantities may show...
        self.assertIsNone(s["estimate"])    # ...but money does not exist yet
        self.assertIsNone(s["proposal_digest"])

    def test_no_clause_does_not_silently_become_verified(self):
        s = scope_done()
        with self.assertRaises(wf.GateError):
            wf.approve_labor(s, **{**STANDARD, "source_refs": []})
        with self.assertRaises(wf.GateError):
            wf.approve_labor(s, **{**STANDARD, "applicability_review": "  "})
        self.assertEqual(s["status"], "needs_labor_review")

    def test_labor_cannot_be_decided_before_scope_is_resolved(self):
        with self.assertRaises(wf.GateError):
            wf.approve_labor(wf.start(SCOPE, RATES), **STANDARD)

    def test_named_actor_and_note_required(self):
        for kw in ({"by": ""}, {"by": "  "}, {"note": ""}, {"note": "\t"}):
            with self.subTest(kw=kw), self.assertRaises(wf.GateError):
                wf.approve_labor(scope_done(), **{**STANDARD, **kw})

    def test_invalid_decisions_rejected(self):
        for kw in ({"decision": "unresolved"}, {"decision": "verified"}, {"certified_payroll": "unknown"},
                   {"certified_payroll": None}, {"certified_payroll": "yes"}):
            with self.subTest(kw=kw), self.assertRaises(wf.GateError):
                wf.approve_labor(scope_done(), **{**STANDARD, **kw})

    def test_prevailing_wage_needs_class_source_and_positive_rate(self):
        for kw in ({"classifications": []}, {"source_refs": []}, {"loaded_hourly_rate": 0},
                   {"loaded_hourly_rate": -5}, {"loaded_hourly_rate": float("nan")}, {"loaded_hourly_rate": True},
                   {"loaded_hourly_rate": None}, {"wage_basis": "union_cba"}):
            with self.subTest(kw=kw), self.assertRaises(wf.GateError):
                wf.approve_labor(scope_done(), **{**FEDERAL, **kw})

    def test_company_rate_basis_cannot_override_company_rate(self):
        with self.assertRaises(wf.GateError):
            wf.approve_labor(scope_done(), **{**STANDARD, "loaded_hourly_rate": 1.0})

    def test_labor_rate_changes_labor_cost_not_materials(self):
        std, fed = wf.approve_labor(scope_done(), **STANDARD), wf.approve_labor(scope_done(), **FEDERAL)
        self.assertGreater(fed["estimate"]["cogs"]["labor"], std["estimate"]["cogs"]["labor"])
        self.assertEqual(fed["estimate"]["cogs"]["materials"], std["estimate"]["cogs"]["materials"])

    def test_assumption_requires_qualification_and_is_marked_provisional(self):
        with self.assertRaises(wf.GateError):
            wf.approve_labor(scope_done(), **{**ASSUMED, "qualification": " "})
        s = wf.approve_labor(scope_done(), **ASSUMED)
        self.assertTrue(s["estimate"]["labor_review"]["provisional"])
        self.assertNotIn("verified", s["labor_review"]["decision"].replace("human_assumption_with_qualification", ""))
        pkg = wf.release(s, "Test Approver", s["scope"]["scope_version"], s["proposal_digest"])
        kinds = [q["type"] for q in pkg["qualifications"]]
        self.assertIn("labor_assumption", kinds)  # the qualification survives into the released package

    def test_policy_can_forbid_assumptions(self):
        s = scope_done(policy={"allow_qualified_labor_assumption": False})
        with self.assertRaises(wf.GateError):
            wf.approve_labor(s, **ASSUMED)

    def test_missing_rate_source_holds(self):
        rates = copy.deepcopy(RATES)
        rates["profile"] = ""
        s = wf.start(SCOPE, rates)
        s = wf.resolve(s, BID, option_id="base", **WHO)
        s = wf.resolve(s, H42, option_id="v:3.5", **WHO)
        s = wf.resolve(s, GUARD, option_id="v:no", **WHO)
        with self.assertRaises(wf.GateError):
            wf.approve_labor(s, **STANDARD)
        self.assertIsNone(s["estimate"])


class Invalidation(unittest.TestCase):
    def test_scope_change_invalidates_labor_and_release_eligibility(self):
        s = wf.approve_labor(scope_done(), **STANDARD)
        digest, version = s["proposal_digest"], s["scope"]["scope_version"]
        self.assertEqual(s["status"], "ready_for_final_review")
        # a later correction reopens a human-resolved fact through a new exception path
        s["scope"]["fence_runs"][0]["length_lf"]["value"] = 380.0
        s = wf._advance(s)  # simulate new evidence arriving that changes a fact
        self.assertEqual(s["status"], "needs_scope_review")
        self.assertIsNone(s["estimate"])
        with self.assertRaises(wf.GateError):
            wf.release(s, "Test Approver", version, digest)

    def test_labor_decision_is_wiped_when_scope_version_changes(self):
        s = wf.approve_labor(scope_done(), **STANDARD)
        self.assertEqual(s["labor_review"]["status"], "decided")
        # reopen scope via a held RFI plus a fresh resolution on a new exception
        s["scope"]["gates"][0]["clear_width_ft"] = {"value": None, "status": "unresolved", "unit": "ft", "evidence": []}
        s = wf._advance(s)
        ex = next(e for e in wf.open_blockers(s) if e["code"] == "MISSING_VALUE")
        s = wf.resolve(s, ex["exception_id"], value=4.0, by="Test Reviewer", note="assumed 4 ft pending design")
        self.assertEqual(s["labor_review"]["status"], "unresolved")
        self.assertEqual(s["status"], "needs_labor_review")
        self.assertIn("labor_invalidated", [a["event"] for a in s["audit"]])
        self.assertIsNone(s["estimate"])

    def test_hold_blocks_pricing_and_release_until_new_input(self):
        s = wf.start(SCOPE, RATES)
        s = wf.hold(s, by="Test Reviewer", reason="RFI sent for G3 width")
        self.assertEqual(s["status"], "held")
        s = wf.resolve(s, BID, option_id="base", **WHO)
        self.assertNotEqual(s["status"], "held")  # new input clears the hold
        s = wf.hold(wf.resolve(wf.resolve(s, H42, option_id="v:3.5", **WHO), GUARD, option_id="v:no", **WHO),
                    by="Test Reviewer", reason="wage question open")
        self.assertEqual(s["status"], "held")
        self.assertIsNone(s["estimate"])
        with self.assertRaises(wf.GateError):
            wf.release(s, "Test Approver", s["scope"]["scope_version"], "0" * 64)
        s = wf.approve_labor(s, **STANDARD)  # the answer to the labor question is the new input
        self.assertEqual(s["status"], "ready_for_final_review")

    def test_rejected_decisions_do_not_mutate_state_or_audit(self):
        s = scope_done()
        snap = copy.deepcopy(s)
        for call in (lambda: wf.approve_labor(s, **{**STANDARD, "by": ""}),
                     lambda: wf.resolve(s, "EX-NOPE", option_id="x", **WHO),
                     lambda: wf.resolve(s, BID, option_id="base", by="", note="x")):
            with self.assertRaises(wf.GateError):
                call()
        self.assertEqual(s, snap)


if __name__ == "__main__":
    unittest.main()

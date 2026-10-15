"""Regression tests: unsafe gate widths and empty scopes must never reach pricing or release."""
import copy, json, math, pathlib, unittest
from engine import workflow as wf

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCOPE = json.load(open(ROOT / "samples/scope_synthetic.json"))
RATES = json.load(open(ROOT / "config/rates.example.json"))
EV = [{"doc_id": "PLANS", "page": 1, "source_type": "plan_sheet", "excerpt": "fictional fixture"}]

BID = "EX-BID_SELECTION_REQUIRED-/bid_structure/selected_bid"
H42 = "EX-PLAN_SPEC_CONFLICT-/fence_runs/1/height_ft"
GUARD = "EX-PLAN_SPEC_CONFLICT-/accessories/1/applies_to_gates"
WIDTH = "/gates/0/clear_width_ft"


def clean_scope():
    """The fixture with its three unrelated conflicts already settled by a named human."""
    s = wf.start(SCOPE, RATES)
    s = wf.resolve(s, BID, option_id="base", by="Test Reviewer", note="base bid")
    s = wf.resolve(s, H42, option_id="v:3.5", by="Test Reviewer", note="plan detail governs")
    s = wf.resolve(s, GUARD, option_id="v:no", by="Test Reviewer", note="spec text")
    return copy.deepcopy(s["scope"])


def with_width(value, status="confirmed", evidence=EV):
    sc = clean_scope()
    sc["gates"][0]["clear_width_ft"] = {"value": value, "status": status, "unit": "ft", "evidence": evidence}
    return sc


def blocker_codes(s):
    return {e["code"] for e in wf.open_blockers(s)}


class ZeroWidthGate(unittest.TestCase):
    def test_baseline_fixture_reaches_labor_gate(self):
        self.assertEqual(wf.start(clean_scope(), RATES)["status"], "needs_labor_review")

    def test_unusable_widths_block_instead_of_pricing(self):
        for bad in (0, 0.0, -4, -0.0, float("nan"), float("inf"), True, False, "4", [4], {"v": 4}):
            for status in ("confirmed", "inferred", "human_resolved"):
                with self.subTest(width=bad, status=status):
                    sc = with_width(bad, status)
                    sc["gates"][0]["clear_width_ft"]["inference_note"] = "n"
                    s = wf.start(sc, RATES)
                    self.assertEqual(s["status"], "needs_scope_review")
                    self.assertIsNone(s["estimate"])
                    self.assertIsNone(s["takeoff"])
                    self.assertTrue(blocker_codes(s) & {"INVALID_VALUE", "SCOPE_INVALID"})

    def test_missing_or_unwrapped_width_blocks(self):
        sc = clean_scope()
        del sc["gates"][0]["clear_width_ft"]
        self.assertEqual(wf.start(sc, RATES)["status"], "needs_scope_review")
        for raw in (0, 4.0):
            sc = clean_scope()
            sc["gates"][0]["clear_width_ft"] = raw  # not a fact object, so it carries no evidence/status
            s = wf.start(sc, RATES)
            self.assertEqual(s["status"], "needs_scope_review")
            self.assertIn("SCOPE_INVALID", blocker_codes(s))

    def test_unresolved_g3_stays_null_and_blocks(self):
        sc = with_width(None, "unresolved", [])
        s = wf.start(sc, RATES)
        self.assertEqual(blocker_codes(s), {"MISSING_VALUE"})
        self.assertIsNone(s["scope"]["gates"][0]["clear_width_ft"]["value"])
        self.assertIsNone(s["estimate"])

    def test_human_cannot_resolve_g3_with_unusable_value(self):
        eid = "EX-MISSING_VALUE-" + WIDTH
        for bad in (0, -1, float("nan"), float("inf"), True, "4", "four"):
            with self.subTest(value=bad):
                s = wf.start(with_width(None, "unresolved", []), RATES)
                before = copy.deepcopy(s["scope"])
                with self.assertRaises(wf.GateError):
                    wf.resolve(s, eid, value=bad, by="Test Reviewer", note="assumed")
                self.assertEqual(s["scope"], before, "a rejected resolution must not mutate state")
                self.assertEqual(s["audit"][-1]["event"], "start")

    def test_human_assumption_is_recorded_as_human_resolved_not_engineered(self):
        s = wf.start(with_width(None, "unresolved", []), RATES)
        s = wf.resolve(s, "EX-MISSING_VALUE-" + WIDTH, value=4.0, by="Test Reviewer",
                       note="Bid qualification: assumed 4 ft pending design confirmation")
        fact = s["scope"]["gates"][0]["clear_width_ft"]
        self.assertEqual((fact["value"], fact["status"]), (4.0, "human_resolved"))
        self.assertEqual(fact["evidence"][-1]["source_type"], "human_resolution")
        self.assertEqual(fact["evidence"][-1]["by"], "Test Reviewer")

    def test_unusable_widths_never_produce_a_price_through_any_run(self):
        for bad in (0, -4, float("nan"), 1e9):
            s = wf.start(with_width(bad), RATES)
            self.assertIsNone(s["estimate"])
            self.assertNotEqual(s["status"], "released")

    def test_gate_wider_than_its_run_blocks(self):
        sc = with_width(500.0)
        s = wf.start(sc, RATES)
        self.assertEqual(s["status"], "needs_scope_review")
        self.assertIn("GEOMETRY_INVALID", blocker_codes(s))

    def test_gate_with_unknown_run_blocks(self):
        sc = clean_scope()
        sc["gates"][0]["run_id"] = "FR-404"
        s = wf.start(sc, RATES)
        self.assertEqual(s["status"], "needs_scope_review")
        self.assertIn("SCOPE_INVALID", blocker_codes(s))


class EmptyScope(unittest.TestCase):
    EMPTIES = {
        "empty object": {},
        "not an object": [],
        "empty lists": {"fence_runs": [], "gates": [], "accessories": [], "bid_structure": {"pay_items": []}},
        "no runs, gates only": None,
        "zero-length run": None,
        "all runs zero repeat": None,
    }

    def scope(self, name):
        sc = self.EMPTIES[name]
        if sc is not None:
            return copy.deepcopy(sc)
        sc = clean_scope()
        if name == "no runs, gates only":
            sc["fence_runs"] = []
        elif name == "zero-length run":
            sc["fence_runs"][0]["length_lf"]["value"] = 0
            sc["fence_runs"][1]["length_lf"]["value"] = 0
            sc["gates"], sc["accessories"], sc["bid_structure"]["pay_items"] = [], [], []
        elif name == "all runs zero repeat":
            for r in sc["fence_runs"]:
                r["repeat"] = 0
        return sc

    def test_empty_scopes_never_price_or_release(self):
        for name in self.EMPTIES:
            with self.subTest(scope=name):
                s = wf.start(self.scope(name), RATES)
                self.assertEqual(s["status"], "needs_scope_review")
                self.assertIsNone(s["estimate"])
                self.assertIsNone(s["proposal_digest"])
                self.assertTrue(wf.open_blockers(s))
                with self.assertRaises(wf.GateError):
                    wf.release(s, approver="Test Approver", expected_scope_version=1,
                               expected_proposal_digest="0" * 64)

    def test_empty_scope_exceptions_cannot_be_resolved_away(self):
        s = wf.start({}, RATES)
        for e in wf.open_blockers(s):
            with self.assertRaises(wf.GateError):
                wf.resolve(s, e["exception_id"], value=1.0, by="Test Reviewer", note="try to force")
        self.assertEqual(s["status"], "needs_scope_review")

    def test_empty_scope_has_scope_version_and_audit(self):
        s = wf.start({}, RATES)
        self.assertEqual(s["scope"]["scope_version"], 1)
        self.assertEqual(s["audit"][0]["event"], "start")


class RateTableSanity(unittest.TestCase):
    def test_unusable_rate_tables_are_refused_at_start(self):
        for key, bad in (("target_margin_pct", 1.0), ("target_margin_pct", float("nan")), ("overhead_pct", -0.1),
                         ("mobilization", "900")):
            with self.subTest(key=key, bad=bad):
                rates = copy.deepcopy(RATES)
                rates[key] = bad
                with self.assertRaises(wf.GateError):
                    wf.start(clean_scope(), rates)
        rates = copy.deepcopy(RATES)
        rates["labor"]["hourly_rate_per_man"] = 0
        with self.assertRaises(wf.GateError):
            wf.start(clean_scope(), rates)

    def test_missing_rate_for_an_od_is_a_blocking_exception_not_a_crash(self):
        rates = copy.deepcopy(RATES)
        rates["materials"]["post_each_by_od"] = {"9.99": 1.0}
        s = wf.start(clean_scope(), rates)
        s = wf.approve_labor(s, by="Test Reviewer", decision="verified_standard", certified_payroll=False,
                             applicability_review="test", source_refs=["x"], note="n")
        self.assertEqual(s["status"], "needs_scope_review")
        self.assertIn("UNPRICEABLE", blocker_codes(s))
        self.assertIsNone(s["estimate"])


if __name__ == "__main__":
    unittest.main()

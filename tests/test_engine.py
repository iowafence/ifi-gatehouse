import copy, json, pathlib, unittest
from engine import workflow as wf
from engine.estimate import compute_estimate
from engine.takeoff import compute_takeoff
from engine.util import apply_patch, get_ptr

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCOPE = json.load(open(ROOT / "samples/scope_synthetic.json"))
RATES = json.load(open(ROOT / "config/rates.example.json"))

BID = "EX-BID_SELECTION_REQUIRED-/bid_structure/selected_bid"
H42 = "EX-PLAN_SPEC_CONFLICT-/fence_runs/1/height_ft"
GUARD = "EX-PLAN_SPEC_CONFLICT-/accessories/1/applies_to_gates"


def res(s, exception_id, **kw):
    kw.setdefault("by", "Test Reviewer")
    kw.setdefault("note", "test decision")
    return wf.resolve(s, exception_id, **kw)


def labor(s, **kw):
    args = dict(by="Test Reviewer", decision="verified_standard", certified_payroll=False,
                applicability_review="No wage schedule in fictional test documents; applicability checked in test",
                source_refs=["fictional-test-source"], note="test labor decision")
    return wf.approve_labor(s, **{**args, **kw})


def priced(bid="base"):
    return labor(resolved(bid))


def resolved(bid="base"):
    s = wf.start(SCOPE, RATES)
    s = res(s, BID, option_id=bid)
    s = res(s, H42, option_id="v:3.5")
    return res(s, GUARD, option_id="v:no")


class GateOne(unittest.TestCase):
    def test_blocks_and_does_not_guess(self):
        s = wf.start(SCOPE, RATES)
        self.assertEqual(s["status"], "needs_scope_review")
        codes = {e["code"] for e in wf.open_blockers(s)}
        self.assertEqual(codes, {"BID_SELECTION_REQUIRED", "PLAN_SPEC_CONFLICT"})
        self.assertIsNone(s["estimate"])
        self.assertIsNone(s["takeoff"])
        self.assertIsNone(get_ptr(s["scope"], "/fence_runs/1/height_ft")["value"])  # never filled in

    def test_advisories_do_not_block(self):
        s = wf.start(SCOPE, RATES)
        adv = {e["code"] for e in s["exceptions"] if e["severity"] == "advisory"}
        self.assertEqual(adv, {"OWNER_SELECTION_PENDING", "FIELD_VERIFY_REQUIRED", "PAYITEM_NOT_IN_SCOPE"})
        # fully resolved blockers + remaining advisories => proceeds
        self.assertEqual(resolved()["status"], "needs_labor_review")

    def test_resume_bumps_version_and_keeps_audit(self):
        s = resolved()
        self.assertEqual(s["scope"]["scope_version"], SCOPE["scope_version"] + 3)
        self.assertEqual([a["event"] for a in s["audit"]], ["start", "resolved", "resolved", "resolved"])
        fact = get_ptr(s["scope"], "/fence_runs/1/height_ft")
        self.assertEqual(fact["status"], "human_resolved")
        self.assertEqual(fact["evidence"][-1]["source_type"], "human_resolution")

    def test_free_value_resolution(self):
        s = wf.start(SCOPE, RATES)
        s = res(s, BID, option_id="base")
        s = res(s, H42, value=4.0, by="jordan", note="48 in per body text")
        self.assertEqual(get_ptr(s["scope"], "/fence_runs/1/height_ft")["value"], 4.0)


class Determinism(unittest.TestCase):
    def test_identical_inputs_identical_economics(self):
        a, b = priced(), priced()
        self.assertEqual(json.dumps(a["estimate"], sort_keys=True), json.dumps(b["estimate"], sort_keys=True))

    def test_pay_items_sum_to_price(self):
        e = priced()["estimate"]
        self.assertAlmostEqual(sum(i["price"] for i in e["pay_items"]), e["price_total"], places=2)

    def test_resolution_changes_money(self):
        s35 = priced()
        s = wf.start(SCOPE, RATES)
        s = res(s, BID, option_id="base")
        s = res(s, H42, option_id="v:4.0")
        s = labor(res(s, GUARD, option_id="v:no"))
        self.assertGreater(s["estimate"]["cogs"]["total"], s35["estimate"]["cogs"]["total"])


class Takeoff(unittest.TestCase):
    def test_base_quantities(self):
        t = resolved()["takeoff"]
        self.assertEqual(t["totals"]["gates"], 4)
        self.assertEqual(t["runs"]["FR-001"]["terminals"], 12)   # 4 corners + 8 gate posts
        self.assertEqual(t["runs"]["FR-001"]["line_posts"], 29)
        self.assertEqual(t["runs"]["FR-002"]["line_posts"], 12)
        self.assertEqual(t["gates"]["GT-001"]["transom_sf"], 48.0)  # 4 x 3 ft x 4 gates
        self.assertGreater(t["runs"]["FR-001"]["braces"], 0)
        self.assertEqual(t["runs"]["FR-002"]["braces"], 0)       # under 6 ft
        self.assertEqual(t["totals"]["core_drill_footings"], t["totals"]["footings"])

    def test_guard_on_gates_contradicts_stated_quantity(self):
        # Choosing "yes" adds 16 LF of guard across the 4 gates. The stated table (155 LF) does not
        # include it, so reconciliation must block rather than silently price it.
        s = wf.start(SCOPE, RATES)
        s = res(s, BID, option_id="base")
        s = res(s, H42, option_id="v:3.5")
        s = res(s, GUARD, option_id="v:yes")
        self.assertEqual(s["status"], "needs_scope_review")
        blockers = wf.open_blockers(s)
        self.assertEqual([e["code"] for e in blockers], ["QUANTITY_UNSUPPORTED"])
        self.assertIn("#10", blockers[0]["question"])
        self.assertIn("160.0", blockers[0]["question"])


class Reconciliation(unittest.TestCase):
    def test_base_reproduces_stated_quantities(self):
        r = {x["item_no"]: x for x in resolved()["reconciliation"]}
        self.assertEqual(r[13]["status"], "match")
        for n in (9, 10, 11, 12):
            self.assertIn(r[n]["status"], ("match", "within_tolerance"))

    def test_alternate_applies_patch_and_reconciles(self):
        s = resolved("ALT-3COURT")
        self.assertEqual(s["status"], "needs_labor_review")
        self.assertEqual(s["takeoff"]["totals"]["gates"], 3)
        r = {x["item_no"]: x for x in s["reconciliation"]}
        self.assertEqual(r[13]["status"], "match")
        self.assertEqual(r[11]["status"], "match")
        self.assertIn(r[12]["status"], ("match", "within_tolerance"))

    def test_mismatch_blocks_gate_one(self):
        bad = copy.deepcopy(SCOPE)
        bad["fence_runs"][0]["length_lf"]["value"] = 380.0
        s = wf.start(bad, RATES)
        s = res(s, BID, option_id="base")
        s = res(s, H42, option_id="v:3.5")
        s = res(s, GUARD, option_id="v:no")
        self.assertEqual(s["status"], "needs_scope_review")
        self.assertIn("QUANTITY_UNSUPPORTED", {e["code"] for e in wf.open_blockers(s)})


class ReleaseGate(unittest.TestCase):
    def rel(self, s, **kw):
        args = dict(approver="Test Approver", expected_scope_version=s["scope"]["scope_version"],
                    expected_proposal_digest=s["proposal_digest"])
        return wf.release(s, **{**args, **kw})

    def test_cannot_release_with_open_blockers(self):
        s = wf.start(SCOPE, RATES)
        with self.assertRaises(wf.GateError):
            wf.release(s, approver="x", expected_scope_version=1, expected_proposal_digest="0" * 64)

    def test_cannot_release_before_labor_gate(self):
        s = resolved()
        self.assertEqual(s["status"], "needs_labor_review")
        self.assertIsNone(s["estimate"])
        with self.assertRaises(wf.GateError):
            wf.release(s, approver="Test Approver", expected_scope_version=s["scope"]["scope_version"],
                       expected_proposal_digest="0" * 64)

    def test_release_needs_named_approver(self):
        for who in ("", "   ", None):
            s = priced()
            with self.assertRaises(wf.GateError):
                self.rel(s, approver=who)
            self.assertEqual(s["status"], "ready_for_final_review")

    def test_release_calls_hook_only_after_approval(self):
        sent = []
        s = priced()
        self.assertEqual(sent, [])
        pkg = self.rel(s, on_release=sent.append)
        self.assertEqual(len(sent), 1)
        self.assertEqual(s["status"], "released")
        self.assertEqual(pkg["audit"][-1]["event"], "released")
        self.assertEqual(pkg["proposal_digest"], s["proposal_digest"])

    def test_wrong_version_or_digest_rejected(self):
        s = priced()
        for kw in ({"expected_scope_version": s["scope"]["scope_version"] - 1},
                   {"expected_proposal_digest": "0" * 64}, {"expected_proposal_digest": None}):
            with self.subTest(kw=kw), self.assertRaises(wf.GateError):
                self.rel(s, **kw)
            self.assertEqual(s["status"], "ready_for_final_review")

    def test_rate_change_after_review_invalidates_digest(self):
        s = priced()
        digest = s["proposal_digest"]
        s["rates"]["materials"]["fabric_per_sf"] *= 2
        with self.assertRaises(wf.GateError):
            self.rel(s, expected_proposal_digest=digest)

    def test_double_release_and_post_release_edits_rejected(self):
        s = priced()
        self.rel(s)
        with self.assertRaises(wf.GateError):
            self.rel(s)
        with self.assertRaises(wf.GateError):
            res(s, BID, option_id="base")
        with self.assertRaises(wf.GateError):
            labor(s)


if __name__ == "__main__":
    unittest.main()

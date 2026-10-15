"""Day-2 integration scenarios through the frozen typed interface `engine.pricing_service`. All data is fictional (Crew 1/2/3 = 104% / 94% / 88%);
every expected figure is recomputed here from first principles, never read back from the code under test."""
import copy
import json
import pathlib
import unittest
from decimal import ROUND_HALF_UP, Decimal

from engine import pricing_service as svc
from engine import workflow as wf
from pricing import ratebook as pr
from tests import pricing_helpers as H
from tests import test_crew_plans as CP
from tests import test_ratebook_workflow as W
from tests import xlsx_builder as xb

ROOT = pathlib.Path(__file__).resolve().parent.parent
E = lambda x: Decimal(repr(x))
CENT = Decimal("0.01")
HOURLY = {"CR11": E(97.2), "CR12": E(140.4), "CR13": E(108.0), "CR14": E(151.2)}   # wage x 1.35 burden, recomputed from the Roles sheet in test_hourly_basis
EFF = {"CR11": 104, "CR12": 94, "CR13": 88, "CR14": 97}


def rate(book, task, crew):
    return E(next(o["production_rate"] for o in book["crew_options"] if o["task_id"] == task and o["crew_id"] == crew))


def qty(s, driver):
    return E(next(i["quantity"] for i in s["quantities"]["BASE"]["items"] if i.get("driver_key") == driver))


def task_cost(s, book, task, crew, driver, level_mult=1, efficiency=True):
    hours = qty(s, driver) / (rate(book, task, crew) * (E(EFF[crew]) / 100 if efficiency else 1) * E(level_mult))
    return hours, (hours * HOURLY[crew]).quantize(CENT, rounding=ROUND_HALF_UP)


def labor_line(res, task):
    return next(l for l in res["scenarios"]["BASE"]["lines"] if l["task_id"] == task)


class Base(unittest.TestCase):
    def setUp(self):
        self.book = H.book(profiles=True)
        self.s = CP.ready_to_plan(self.book)


class FleetAndEligibility(Base):
    def test_hourly_basis(self):
        loaded = {r["role_key"]: E(r["base_wage_per_hr"]) * (1 + E(r["burden_pct"])) for r in self.book["roles"]}
        for c in self.book["crews"]:
            if c["crew_id"] in HOURLY:
                self.assertEqual(sum(loaded[k] * n for k, n in c["members"].items()), HOURLY[c["crew_id"]])

    def test_sidebar_fleet_overview_keeps_every_crew_and_averages_to_95_75(self):
        f = svc.fleet_overview(self.book)
        self.assertEqual([(c["crew_id"], c["efficiency_pct"]) for c in f["crews"]], [("CR11", 104), ("CR12", 94), ("CR13", 88), ("CR14", 97)])
        self.assertEqual(f["fleet_average_display"], "95.8")
        self.assertEqual(f["fleet_average_efficiency_pct"], 95.75)
        self.assertEqual(f["crew_count"], 4)

    def test_a_crew_lacking_a_qualification_stays_in_the_fleet_average(self):
        b = H.book(lambda sp: xb.row(sp, "Labor", "task_id", "L02").update(required_qualifications="CDL-A"), profiles=True)
        self.assertEqual(svc.fleet_overview(b)["fleet_average_display"], "95.8")
        self.assertEqual(svc.fleet_overview(b)["crew_count"], 4)
        self.assertTrue(all(not c["eligible"] for c in svc.task_eligibility(b, "L02")["crews"]))      # nobody holds it, yet the fleet is unchanged

    def test_core_drilling_returns_crew_1_ineligible_with_the_missing_operator_reason(self):
        el = svc.task_eligibility(self.book, "L02")
        by = {c["crew_id"]: c for c in el["crews"]}
        self.assertFalse(by["CR11"]["eligible"])
        self.assertEqual(by["CR11"]["reasons"][0]["code"], "MISSING_REQUIRED_ROLE")
        self.assertEqual((by["CR11"]["reasons"][0]["role_key"], by["CR11"]["reasons"][0]["role"]), ("R4", "Operator"))
        self.assertEqual(by["CR11"]["reasons"][0]["message"], "CR11 has no Operator (R4), which this task requires")
        self.assertFalse(by["CR12"]["eligible"])
        self.assertEqual(by["CR12"]["reasons"][0]["role_key"], "R4")
        for ok in ("CR13", "CR14"):
            self.assertTrue(by[ok]["eligible"])
            self.assertEqual(by[ok]["reasons"], [])
        self.assertEqual([c["crew_id"] for c in el["crews"] if c["in_fleet"]], ["CR11", "CR12", "CR13", "CR14"])

    def test_crew_4_is_its_own_profile_not_a_copy_of_crew_3(self):
        c3, c4 = (next(c for c in self.book["crews"] if c["crew_id"] == k) for k in ("CR13", "CR14"))
        self.assertEqual(c4["members"], {"R1": 1, "R2": 2, "R4": 1})          # foreman, 2 installers, existing operator role; no new roles
        self.assertNotEqual((c3["difficulty"], c3["members"], c3["profile_version"]), (c4["difficulty"], c4["members"], c4["profile_version"]))
        rates3 = {o["task_id"]: o["production_rate"] for o in self.book["crew_options"] if o["crew_id"] == "CR13"}
        rates4 = {o["task_id"]: o["production_rate"] for o in self.book["crew_options"] if o["crew_id"] == "CR14"}
        self.assertEqual(set(rates3), set(rates4))
        self.assertTrue(all(rates3[t] != rates4[t] for t in rates3))
        cmp_ = svc.compare_crews(self.s)["BASE"]
        by = {x["crew_id"]: x for x in next(t for t in cmp_["tasks"] if t["task_id"] == "L02")["candidates"]}
        hours, cost = task_cost(self.s, self.book, "L02", "CR14", "D04")
        self.assertEqual(E(by["CR14"]["labor_cost"]), cost)
        self.assertAlmostEqual(by["CR14"]["crew_hours"], float(hours), places=5)
        self.assertNotEqual(by["CR14"]["labor_cost"], by["CR13"]["labor_cost"])

    def test_labor_gate_shows_all_four_crews_and_greys_out_the_two_without_an_operator_for_drilling(self):
        cmp_ = svc.compare_crews(self.s)["BASE"]
        self.assertEqual({c["crew_id"] for c in cmp_["crews"] if c["in_fleet"]}, {"CR11", "CR12", "CR13", "CR14"})
        drill = {c["crew_id"]: c for c in next(t for t in cmp_["tasks"] if t["task_id"] == "L02")["candidates"] if c["in_fleet"]}
        self.assertEqual(sorted(drill), ["CR11", "CR12", "CR13", "CR14"])
        for g in ("CR11", "CR12"):
            self.assertFalse(drill[g]["eligible"])
            self.assertEqual(drill[g]["reason_details"][0]["code"], "MISSING_REQUIRED_ROLE")
            self.assertEqual(drill[g]["reason_details"][0]["message"], f"{g} has no Operator (R4), which this task requires")
            self.assertNotIn("labor_cost", drill[g])
        self.assertTrue(drill["CR13"]["eligible"] and drill["CR14"]["eligible"])

    def test_unknown_task_has_no_eligibility_answer(self):
        self.assertIsNone(svc.task_eligibility(self.book, "L99"))
        self.assertEqual(len(svc.all_eligibility(self.book)), len(self.book["labor_tasks"]))


class Scenarios(Base):
    def test_1_crew_2_and_crew_3_produce_different_independently_reproducible_costs(self):
        c = svc.compare_crews(self.s)["BASE"]
        by = {x["crew_id"]: x for x in next(t for t in c["tasks"] if t["task_id"] == "L03")["candidates"]}
        for crew in ("CR12", "CR13"):
            hours, cost = task_cost(self.s, self.book, "L03", crew, "D03")
            self.assertEqual(E(by[crew]["labor_cost"]), cost)
            self.assertAlmostEqual(by[crew]["crew_hours"], float(hours), places=5)
        self.assertNotEqual(by["CR12"]["labor_cost"], by["CR13"]["labor_cost"])

    def test_2_crew_1_is_rejected_for_drilling_by_the_plan_and_state_is_untouched(self):
        before = copy.deepcopy(self.s)
        with self.assertRaises(svc.GateError) as cm:
            svc.adopt_crew_plan(self.s, by="Pat Estimator", note="try crew 1", assignments={"L02": "CR11"}, preferred_crew="CR13", difficulty={"default": "standard"})
        self.assertIn("CREW_UNSUITABLE", str(cm.exception))
        self.assertEqual(self.s, before)
        self.assertIsNone(self.s["estimate"])

    def test_3_mixed_crew_assignment_prices_to_the_sum_of_independent_task_costs_and_recomputes_immediately(self):
        r1 = svc.adopt_crew_plan(self.s, by="Pat Estimator", note="mixed", preferred_crew="CR12", assignments={"L02": "CR13", "L06": "CR11"},
                                 difficulty={"default": "standard"})
        self.assertTrue(r1["priced"])
        want = {"L02": ("CR13", "D04", "L02"), "L06": ("CR11", "D07", "L06")}
        for t, (crew, drv, tid) in want.items():
            _, cost = task_cost(self.s, self.book, tid, crew, drv)
            self.assertEqual((labor_line(r1, t)["crew_id"], E(labor_line(r1, t)["extended"])), (crew, cost))
        _, c3 = task_cost(self.s, self.book, "L03", "CR12", "D03")
        self.assertEqual(E(labor_line(r1, "L03")["extended"]), c3)                                 # unassigned task follows the stated preferred crew
        self.assertEqual(E(r1["scenarios"]["BASE"]["labor_subtotal"]), sum(E(l["extended"]) for l in r1["scenarios"]["BASE"]["lines"]))
        r2 = svc.adopt_crew_plan(self.s, by="Pat Estimator", note="swap drilling to nobody else", preferred_crew="CR12", assignments={"L02": "CR13", "L06": "CR12"},
                                 difficulty={"default": "standard"})
        self.assertNotEqual(r2["scenarios"]["BASE"]["labor_subtotal"], r1["scenarios"]["BASE"]["labor_subtotal"])   # recomputed by the real engine at once
        self.assertEqual(r2["crew_plan_version"], 2)

    def test_3b_crew_hours_and_worker_hours_stay_distinct_and_calendar_duration_is_not_modeled(self):
        r = svc.adopt_crew_plan(self.s, by="Pat Estimator", note="n", preferred_crew="CR13", difficulty={"default": "standard"})
        sc = r["scenarios"]["BASE"]
        self.assertGreater(sc["worker_hours"], sc["crew_hours"])
        self.assertAlmostEqual(sc["worker_hours"], sum(l["worker_hours"] for l in sc["lines"]), places=4)
        self.assertAlmostEqual(sc["crew_days"], sc["crew_hours"] / 8, places=4)
        self.assertIsNone(sc["calendar_duration"])
        self.assertNotIn("duration_days", self.s["estimate"]["scenarios"]["BASE"]["labor"])

    def test_4_unapproved_wage_classification_blocks_compliant_pricing(self):
        s = W.wage_ready()
        bad = W.good_rows()
        bad[3] = W.row("R4", W.OPR, status="proposed_for_conformance")
        r = svc.record_wage_decision(s, **W.wage_args(rows=bad))
        self.assertFalse(r["priced"])
        self.assertIsNone(r["proposal_digest"])
        self.assertIn("WAGE_CONFORMANCE_PENDING", {b["code"] for b in r["blockers"]})
        good = svc.record_wage_decision(s, **W.wage_args())
        self.assertTrue(good["priced"])
        self.assertEqual(good["scenarios"]["BASE"]["basis"], "prevailing_wage")

    def test_5_historical_calibrated_production_never_gets_efficiency_twice(self):
        def calibrate(sp):
            for r in sp["Crew_Production"]["rows"]:
                if r["task_id"] == "L06" and r["crew_id"] == "CR11":
                    r["rate_basis"] = "historical_calibrated"
        book = H.book(calibrate, profiles=True)
        s = CP.ready_to_plan(book)
        r = svc.adopt_crew_plan(s, by="Pat Estimator", note="n", assignments={"L02": "CR13", "L06": "CR11"}, preferred_crew="CR12", difficulty={"default": "standard"})
        l = labor_line(r, "L06")
        hours, _ = task_cost(s, book, "L06", "CR11", "D07", efficiency=False)
        self.assertFalse(l["efficiency_applied"])
        self.assertAlmostEqual(l["crew_hours"], float(hours), places=5)
        std = labor_line(r, "L03")
        self.assertTrue(std["efficiency_applied"])

    def test_6_difficulty_changes_hours_not_hourly_wage(self):
        std = svc.adopt_crew_plan(self.s, by="Pat Estimator", note="n", preferred_crew="CR13", difficulty={"default": "standard"})
        hard = svc.adopt_crew_plan(self.s, by="Pat Estimator", note="n", preferred_crew="CR13", difficulty={"default": "hard"})
        mult = E(next(c for c in self.book["crews"] if c["crew_id"] == "CR13")["difficulty"]["hard"])
        for t in ("L03", "L06"):
            a, b = labor_line(std, t), labor_line(hard, t)
            self.assertNotEqual(a["crew_hours"], b["crew_hours"])
            self.assertAlmostEqual(b["crew_hours"], a["crew_hours"] / float(mult), places=4)
            self.assertEqual(a["crew_rate_per_hr"], b["crew_rate_per_hr"])

    def test_7_changed_plan_or_profile_version_invalidates_the_previous_digest(self):
        r1 = svc.adopt_crew_plan(self.s, by="Pat Estimator", note="n", preferred_crew="CR13", difficulty={"default": "standard"})
        d1 = r1["proposal_digest"]
        self.assertTrue(svc.digest_is_current(self.s, d1)["current"])
        r2 = svc.adopt_crew_plan(self.s, by="Pat Estimator", note="n", preferred_crew="CR12", assignments={"L02": "CR13"}, difficulty={"default": "standard"})
        self.assertFalse(svc.digest_is_current(self.s, d1)["current"])
        with self.assertRaises(wf.GateError):
            wf.release(self.s, "Test Approver", self.s["scope"]["scope_version"], d1)
        newer = H.book(lambda sp: (xb.row(sp, "Meta", "key", "version").update(value="1.1.0"),
                                   xb.row(sp, "Crews", "crew_id", "CR12").update(profile_version="B2")), profiles=True)
        wf.attach_ratebook(self.s, newer, by="Test Approver", note="Crew 2 profile revised")
        self.assertIsNone(svc.labor_result(self.s)["crew_plan"])
        self.assertFalse(svc.digest_is_current(self.s, r2["proposal_digest"])["current"])
        self.assertFalse(svc.labor_result(self.s)["priced"])

    def test_7b_plan_versions_only_increase_and_are_never_reused_after_a_void(self):
        svc.adopt_crew_plan(self.s, by="Pat Estimator", note="n", preferred_crew="CR13", difficulty={"default": "standard"})
        svc.adopt_crew_plan(self.s, by="Pat Estimator", note="n", preferred_crew="CR12", assignments={"L02": "CR13"}, difficulty={"default": "standard"})
        newer = H.book(lambda sp: (xb.row(sp, "Meta", "key", "version").update(value="1.1.0"),
                                   xb.row(sp, "Crews", "crew_id", "CR13").update(profile_version="C2")), profiles=True)
        wf.attach_ratebook(self.s, newer, by="Test Approver", note="Crew 3 revised")
        if self.s["labor_review"]["status"] != "decided":
            W.labor(self.s)
        r = svc.adopt_crew_plan(self.s, by="Pat Estimator", note="n", preferred_crew="CR13", difficulty={"default": "standard"})
        self.assertEqual(r["crew_plan_version"], 3)
        hist = svc.crew_plan_history(self.s)
        self.assertEqual([p["plan_version"] for p in hist], [1, 2, 3])
        self.assertEqual(hist[0]["retired_reason"], "superseded by plan version 2")
        self.assertIn("crew profiles", hist[1]["retired_reason"])
        self.assertNotIn("retired_reason", hist[2])

    def test_8_unknown_or_unassigned_tasks_cannot_be_silently_priced(self):
        before = copy.deepcopy(self.s)
        for kw, code in (({}, "CREW_NOT_SELECTED"),                                            # nothing selected, defaults not authorized
                         ({"assignments": {"L02": "CR13"}}, "CREW_NOT_SELECTED"),             # only one task assigned
                         ):
            with self.assertRaises(wf.GateError) as cm:
                svc.adopt_crew_plan(self.s, by="Pat Estimator", note="n", difficulty={"default": "standard"}, **kw)
            self.assertIn(code, str(cm.exception))
        for bad in ({"L99": "CR13"}, {"L02": "CR99"}):
            with self.assertRaises(wf.GateError):
                svc.adopt_crew_plan(self.s, by="Pat Estimator", note="n", preferred_crew="CR13", assignments=bad, difficulty={"default": "standard"})
        with self.assertRaises(wf.GateError):
            svc.adopt_crew_plan(self.s, by="", note="n", preferred_crew="CR13", difficulty={"default": "standard"})
        self.assertEqual(self.s, before)
        self.assertFalse(svc.labor_result(self.s)["priced"])

    def test_9_rate_book_import_fails_closed(self):
        for data in (b"", b"not a zip", b"PK\x03\x04" + b"0" * 40):
            with self.assertRaises(svc.RateBookRejected) as cm:
                svc.import_ratebook(data)
            self.assertTrue(cm.exception.problems)
        bad = xb.valid_spec()
        xb.row(bad, "Crews", "crew_id", "CR1").update(efficiency_pct=0)
        with self.assertRaises(svc.RateBookRejected):
            svc.import_ratebook(xb.build(bad))
        ok = svc.import_ratebook(xb.build(xb.valid_spec(crew_profiles=True)))
        self.assertIn("content_sha256", ok["ratebook_ref"])

    def test_10_reference_book_is_explicitly_fictional(self):
        path = ROOT / "samples" / "public-demo" / "reference_pricing_workbook_v2_3_0.fictional.xlsx"
        res = svc.import_ratebook(path.read_bytes())
        self.assertEqual(res["data_classification"], "FICTIONAL_DEMO")
        self.assertIn("FICTIONAL", res["ratebook"]["meta"]["ratebook_id"])
        self.assertEqual(svc.fleet_overview(res["ratebook"])["fleet_average_display"], "95.8")
        el = {c["crew_id"]: c["eligible"] for c in svc.task_eligibility(res["ratebook"], "L02")["crews"]}
        self.assertEqual((el["CR11"], el["CR12"], el["CR13"], el["CR14"]), (False, False, True, True))
        self.assertEqual(res["ratebook_ref"]["version"], "2.3.0")
        with self.assertRaises(wf.GateError):                                                       # a demo-only session refuses a private book
            private = copy.deepcopy(res["ratebook"])
            private["meta"]["data_classification"] = "COMPANY_PRIVATE"
            wf.start(CP.sf.base_scope(), None, ratebook=private, policy={**W.POLICY, "allowed_ratebook_classes": ["FICTIONAL_DEMO"]})


class ProvisionalAverage(Base):
    def test_provisional_average_uses_task_eligible_crew_costs_not_the_mean_of_efficiencies(self):
        p = svc.provisional_labor(self.s)["BASE"]
        self.assertTrue(p["provisional"] and not p["releasable"])
        cmp_ = svc.compare_crews(self.s)["BASE"]
        drill = next(l for l in p["lines"] if l["task_id"] == "L02")
        self.assertEqual(drill["eligible_crews"], ["CR13", "CR14"])                                  # legacy default crew CR1 can drill but is not fleet
        self.assertEqual(sorted(x["crew_id"] for x in drill["excluded"] if x["reasons"]), ["CR11", "CR12"])
        c3, c4 = (task_cost(self.s, self.book, "L02", k, "D04")[1] for k in ("CR13", "CR14"))
        self.assertEqual(E(drill["provisional_cost"]), ((c3 + c4) / 2).quantize(CENT, rounding=ROUND_HALF_UP))
        # a task all four fleet crews can do averages all four costs
        t3 = next(l for l in p["lines"] if l["task_id"] == "L03")
        costs = [task_cost(self.s, self.book, "L03", k, "D03")[1] for k in ("CR11", "CR12", "CR13", "CR14")]
        self.assertEqual(t3["eligible_crews"], ["CR11", "CR12", "CR13", "CR14"])
        self.assertEqual(E(t3["provisional_cost"]), (sum(costs) / 4).quantize(CENT, rounding=ROUND_HALF_UP))
        self.assertTrue(p["complete"])
        self.assertFalse(svc.labor_result(self.s)["priced"])                                          # a provisional view never prices or releases

    def test_provisional_drilling_needs_cleared_wages_for_both_operator_crews(self):
        s = W.start(W.davis_bacon_scope(), self.book)
        W.approve_rules(s)
        self.assertEqual(s["status"], wf.LABOR_REVIEW)
        none_cleared = svc.provisional_labor(s)["BASE"]
        self.assertFalse(none_cleared["complete"])                                                    # no wage decision: nothing is costed at a guess
        bad = W.good_rows()
        bad[3] = W.row("R4", W.OPR, status="proposed_for_conformance")                               # the operator classification is not cleared
        svc.record_wage_decision(s, **W.wage_args(rows=bad))
        p = svc.provisional_labor(s)["BASE"]
        drill = next(l for l in p["lines"] if l["task_id"] == "L02")
        self.assertIsNone(drill["provisional_cost"])
        self.assertEqual(drill["eligible_crews"], [])
        svc.record_wage_decision(s, **W.wage_args())
        cmp_ = svc.compare_crews(s)["BASE"]
        by = {c["crew_id"]: c for c in next(t for t in cmp_["tasks"] if t["task_id"] == "L02")["candidates"]}
        # statutory CR14 hourly: R1 + 2 x R2 + R4 at wage + fringe + 20% employer cost on wages, recomputed here
        wages, fringe = E(24.50) * 3 + E(29.80), E(9.10) * 3 + E(11.25)
        self.assertEqual(E(by["CR14"]["crew_hourly_cost"]), wages + fringe + wages * E(0.20))
        p2 = svc.provisional_labor(s)["BASE"]
        self.assertEqual(next(l for l in p2["lines"] if l["task_id"] == "L02")["eligible_crews"], ["CR13", "CR14"])

    def test_changing_the_profile_set_voids_the_plan_and_digest_and_versions_keep_rising(self):
        def without_cr14(sp):
            sp["Crews"]["rows"] = [r for r in sp["Crews"]["rows"] if r["crew_id"] != "CR14"]
            sp["Crew_Production"]["rows"] = [r for r in sp["Crew_Production"]["rows"] if r["crew_id"] != "CR14"]
        old = H.book(without_cr14, profiles=True)
        self.assertEqual(svc.fleet_overview(old)["fleet_average_display"], "95.3")
        s = CP.ready_to_plan(old)
        r1 = svc.adopt_crew_plan(s, by="Pat Estimator", note="n", preferred_crew="CR12", assignments={"L02": "CR13"}, difficulty={"default": "standard"})
        newer = H.book(lambda sp: xb.row(sp, "Meta", "key", "version").update(value="1.1.0"), profiles=True)      # profile set now includes CR14
        wf.attach_ratebook(s, newer, by="Test Approver", note="Crew 4 added")
        self.assertIsNone(s["crew_plan"])
        self.assertFalse(svc.digest_is_current(s, r1["proposal_digest"])["current"])
        self.assertFalse(svc.labor_result(s)["priced"])
        if s["labor_review"]["status"] != "decided":
            W.labor(s)
        r2 = svc.adopt_crew_plan(s, by="Pat Estimator", note="n", preferred_crew="CR12", assignments={"L02": "CR14"}, difficulty={"default": "standard"})
        self.assertEqual(r2["crew_plan_version"], 2)
        self.assertEqual(labor_line(r2, "L02")["crew_id"], "CR14")

    def test_a_task_nobody_can_do_has_no_provisional_cost_and_the_total_is_incomplete(self):
        b = H.book(lambda sp: xb.row(sp, "Labor", "task_id", "L02").update(required_qualifications="CDL-A"), profiles=True)
        s = CP.ready_to_plan(b)
        p = svc.provisional_labor(s)["BASE"]
        self.assertFalse(p["complete"])
        self.assertIsNone(p["provisional_labor_cost"])
        self.assertIsNone(next(l for l in p["lines"] if l["task_id"] == "L02")["provisional_cost"])


class FrozenSurface(unittest.TestCase):
    def test_surface_matches_the_published_contract(self):
        published = json.loads((ROOT / "docs" / "pricing" / "engine_interface.v1.json").read_text())
        self.assertEqual(svc.SURFACE, published)
        for group in ("reads_ratebook", "reads_state", "decisions"):
            for name in svc.SURFACE[group]:
                self.assertTrue(callable(getattr(svc, name)), name)

    def test_labor_result_has_exactly_the_published_keys(self):
        s = CP.ready_to_plan(H.book(profiles=True))
        r = svc.adopt_crew_plan(s, by="Pat Estimator", note="n", preferred_crew="CR13", difficulty={"default": "standard"})
        self.assertEqual(sorted(r), sorted(svc.SURFACE["labor_result_keys"]))
        self.assertEqual(sorted(r["scenarios"]["BASE"]), sorted(svc.SURFACE["scenario_keys"]))
        self.assertEqual(sorted(svc.fleet_overview(s["ratebook"])), sorted(svc.SURFACE["fleet_overview_keys"]))
        self.assertEqual(r["contract_version"], "pricing-service.v1")


if __name__ == "__main__":
    unittest.main()

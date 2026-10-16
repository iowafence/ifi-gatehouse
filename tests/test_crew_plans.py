"""Crew efficiency, difficulty response, suitability, comparison and crew-plan approval. Every dollar and hour is recomputed here from first
principles; all crew data is fictional (Crew 1/2/3 = 104% / 94% / 88%)."""
import copy
import unittest
from decimal import Decimal

from engine import workflow as wf
from pricing import crews as pcrews
from pricing import engine
from pricing import ratebook as rb
from tests import pricing_helpers as H
from tests import scope_fixtures as sf
from tests import test_ratebook_workflow as W
from tests import xlsx_builder as xb

E = lambda x: Decimal(repr(x))
CENT = Decimal("0.01")
# loaded hourly cost per crew in the fictional test book (wage x 1.35 burden): R1 43.20, R2 35.10, R3 27.00, R4 37.80
HOURLY = {"CR1": E(108.0), "CR2": E(140.4), "CR11": E(97.2), "CR12": E(140.4), "CR13": E(108.0)}


def run(book, payload, plan, **kw):
    return engine.price(payload, book, labor_basis=H.labor_ok(book), as_of=H.AS_OF, crew_plan=plan, **kw)


def codes(book, payload, plan):
    return {p["code"] for p in engine.check(payload, book, labor_basis=H.labor_ok(book), as_of=H.AS_OF, crew_plan=plan)}


def line(est, task):
    return next(l for l in est["labor"]["lines"] if l["task_id"] == task)


class Formulas(unittest.TestCase):
    def setUp(self):
        self.book = H.book(profiles=True)
        self.q = {"D12": 1000, "D04": 240, "D03": 130}

    def plan(self, **kw):
        kw.setdefault("assignments", {"L02": "CR13"})        # CR11/CR12 have no operator, so the drilling task goes to Crew 3
        return H.eng_plan(self.book, **kw)

    def test_effective_production_hours_cost_and_unit_cost_follow_the_stated_formulas(self):
        est = run(self.book, H.payload(self.q), self.plan(preferred="CR11"))
        l = line(est, "L01")                                     # baseline for CR11 on L01 = 11 x 0.95 = 10.45, efficiency 104%, Standard response 1.00
        adj = E(10.45) * E(104) / 100 * E(1.0)
        hours = E(1000) / adj
        cost = (hours * HOURLY["CR11"]).quantize(CENT, rounding="ROUND_HALF_UP")
        self.assertEqual((l["crew_id"], l["baseline_production"], l["efficiency_pct"], l["difficulty_level"]), ("CR11", 10.45, 104, "standard"))
        self.assertEqual(E(l["effective_production"]), adj.quantize(Decimal("1e-6")))
        self.assertEqual(E(l["crew_hours"]), hours.quantize(Decimal("1e-6")))
        self.assertEqual(E(l["worker_hours"]), (hours * 3).quantize(Decimal("1e-6")))       # foreman + 2 laborers
        self.assertEqual(E(l["duration_days"]), (hours / 8).quantize(Decimal("1e-6")))
        self.assertEqual(E(l["extended"]), cost)
        self.assertEqual(E(l["cost_per_unit"]), (cost / 1000).quantize(Decimal("1e-4")))

    def test_efficiency_above_100_is_supported_and_below_100_costs_more_hours_not_lower_wages(self):
        est = run(self.book, H.payload(self.q), self.plan(preferred="CR13"))
        l = line(est, "L01")                                     # Crew 3 at 88%: baseline 11 x 1.10 = 12.1
        self.assertEqual(E(l["effective_production"]), (E(12.1) * E(88) / 100).quantize(Decimal("1e-6")))
        self.assertLess(l["effective_factor"], 1)
        self.assertEqual(l["crew_rate_per_hr"], 108.0)           # the hourly COST of the crew is untouched by efficiency
        hi = run(self.book, H.payload(self.q), self.plan(preferred="CR11"))
        self.assertGreater(line(hi, "L01")["effective_factor"], 1)

    def test_difficulty_response_is_per_crew_and_changes_hours_only(self):
        std = run(self.book, H.payload(self.q), self.plan(preferred="CR11"))
        hard = run(self.book, H.payload(self.q), self.plan(preferred="CR11", default="hard"))
        a, b = line(std, "L01"), line(hard, "L01")
        self.assertEqual(b["difficulty_multiplier"], 0.80)
        self.assertAlmostEqual(b["crew_hours"] / a["crew_hours"], 1 / 0.8, places=5)
        self.assertEqual((a["crew_rate_per_hr"], b["crew_rate_per_hr"]), (97.2, 97.2))          # same hourly cost on easy/standard/hard
        c = run(self.book, H.payload(self.q), self.plan(preferred="CR13", default="hard"))
        self.assertAlmostEqual(line(c, "L01")["crew_hours"] / line(run(self.book, H.payload(self.q), self.plan(preferred="CR13")), "L01")["crew_hours"], 1 / 0.97, places=5)
        # a foreman + two laborers is the best on easy work and the worst on hard work; the specialist is flatter
        def hours(crew, level):
            return line(run(self.book, H.payload(self.q), self.plan(preferred=crew, default=level)), "L01")["crew_hours"]
        self.assertLess(hours("CR11", "easy") / hours("CR13", "easy"), hours("CR11", "standard") / hours("CR13", "standard"))
        self.assertGreater(hours("CR11", "hard") / hours("CR13", "hard"), hours("CR11", "standard") / hours("CR13", "standard"))

    def test_per_task_difficulty_overrides_use_the_driver_key(self):
        est = run(self.book, H.payload(self.q), self.plan(preferred="CR11", overrides={"D03": "hard"}))
        self.assertEqual((line(est, "L01")["difficulty_level"], line(est, "L03")["difficulty_level"]), ("standard", "hard"))   # L03 = D03 post setting

    def test_difficulty_never_changes_quantities_or_materials(self):
        std = run(self.book, H.payload({**self.q, "M05": 100}), self.plan(preferred="CR11"))
        hard = run(self.book, H.payload({**self.q, "M05": 100}), self.plan(preferred="CR11", default="hard"))
        self.assertEqual(std["materials"], hard["materials"])
        self.assertEqual((std["equipment"], std["mobilization"], std["services"]), (hard["equipment"], hard["mobilization"], hard["services"]))
        self.assertNotEqual(std["labor"]["subtotal"], hard["labor"]["subtotal"])

    def test_historical_calibrated_rates_are_not_given_efficiency_twice(self):
        def calibrate(sp):
            for r in sp["Crew_Production"]["rows"]:
                if r["task_id"] == "L01" and r["crew_id"] == "CR11":
                    r["rate_basis"] = "historical_calibrated"
        book = H.book(calibrate, profiles=True)
        est = run(book, H.payload(self.q), H.eng_plan(book, preferred="CR11", assignments={"L02": "CR13"}))
        l = line(est, "L01")
        self.assertFalse(l["efficiency_applied"])
        self.assertEqual(l["effective_factor"], 1.0)                                       # 104% NOT applied on top of a calibrated rate
        self.assertEqual(l["effective_production"], 10.45)
        other = line(est, "L03")
        self.assertTrue(other["efficiency_applied"])
        hard = run(book, H.payload(self.q), H.eng_plan(book, preferred="CR11", assignments={"L02": "CR13"}, default="hard"))
        self.assertEqual(line(hard, "L01")["effective_factor"], 0.8)                       # the job's difficulty still applies to a calibrated rate

    def test_without_a_plan_the_engine_never_substitutes_an_efficiency(self):
        self.assertEqual(codes(self.book, H.payload(self.q), None), {"CREW_PLAN_NOT_APPROVED"})
        neutral = H.book()
        self.assertEqual(codes(neutral, H.payload(self.q), None), set())                  # a neutral book needs none, and applies factor 1
        l = line(run(neutral, H.payload(self.q), None), "L01")
        self.assertEqual((l["efficiency_pct"], l["effective_factor"], l["difficulty_level"]), (100, 1.0, "standard"))


class Suitability(unittest.TestCase):
    def setUp(self):
        self.book = H.book(profiles=True)
        self.q = {"D12": 1000, "D04": 240, "D03": 130}

    def test_efficiency_cannot_make_a_crew_without_the_required_role_eligible(self):
        plan = H.eng_plan(self.book, preferred="CR11", assignments={"L02": "CR11"})
        self.assertEqual(codes(self.book, H.payload(self.q), plan), {"CREW_UNSUITABLE"})        # Crew 1 is 104% but has no operator (R4)
        plan = H.eng_plan(self.book, preferred="CR12", assignments={"L02": "CR12"})
        self.assertEqual(codes(self.book, H.payload(self.q), plan), {"CREW_UNSUITABLE"})
        self.assertEqual(codes(self.book, H.payload(self.q), H.eng_plan(self.book, preferred="CR11", assignments={"L02": "CR13"})), set())

    def test_required_qualifications_are_enforced_too(self):
        def need(sp):
            for r in sp["Labor"]["rows"]:
                if r["driver_key"] == "D12":
                    r["required_qualifications"] = "surveyor_cert"
            xb.row(sp, "Crews", "crew_id", "CR13")["qualifications"] = "surveyor_cert"
        book = H.book(need, profiles=True)
        plan = H.eng_plan(book, preferred="CR11", assignments={"L02": "CR13"})
        self.assertEqual({p["code"] for p in engine.check(H.payload(self.q), book, labor_basis=H.labor_ok(book), as_of=H.AS_OF, crew_plan=plan)}, {"CREW_UNSUITABLE"})
        plan = H.eng_plan(book, preferred="CR13")
        self.assertEqual({p["code"] for p in engine.check(H.payload(self.q), book, labor_basis=H.labor_ok(book), as_of=H.AS_OF, crew_plan=plan)}, set())

    def test_nothing_is_assumed_when_a_task_has_no_crew_or_no_rate(self):
        plan = H.eng_plan(self.book, preferred="CR1", use_default=False)               # CR1 is priced for L01/L02 only; nothing else is stated
        self.assertIn("CREW_NOT_SELECTED", codes(self.book, H.payload(self.q), plan))
        self.assertIn("CREW_UNSUITABLE", codes(self.book, H.payload(self.q), H.eng_plan(self.book, preferred="CR11", use_default=False)))
        plan = H.eng_plan(self.book, assignments={"L01": "CR2"}, use_default=True)       # CR2 has no production rate for L01
        self.assertIn("CREW_NO_PRODUCTION_RATE", codes(self.book, H.payload(self.q), plan))

    def test_plan_must_be_approved_current_and_for_these_profiles(self):
        good = H.eng_plan(self.book, preferred="CR13")
        self.assertEqual(codes(self.book, H.payload(self.q), good), set())
        self.assertIn("CREW_PLAN_NOT_APPROVED", codes(self.book, H.payload(self.q), dict(good, approved_by="")))
        self.assertIn("CREW_PLAN_STALE", codes(self.book, H.payload(self.q), dict(good, ratebook_labor_sha256="0" * 64)))
        newer = H.eng_plan(self.book, preferred="CR13")
        newer["crew_profiles"]["CR13"] = "C0"
        self.assertIn("CREW_PROFILE_CHANGED", codes(self.book, H.payload(self.q), newer))
        for bad in (dict(default="extreme"), dict(overrides={"D03": "tough"})):
            self.assertIn("DIFFICULTY_INVALID", codes(self.book, H.payload(self.q), H.eng_plan(self.book, preferred="CR13", **bad)))

    def test_ai_difficulty_needs_cited_evidence_at_the_engine_too(self):
        plan = H.eng_plan(self.book, preferred="CR13", source="ai_recommended_human_approved")
        self.assertIn("DIFFICULTY_EVIDENCE_MISSING", codes(self.book, H.payload(self.q), plan))
        plan = H.eng_plan(self.book, preferred="CR13", source="ai_recommended_human_approved", evidence=[{"doc_id": "PM", "page": 12}])
        self.assertEqual(codes(self.book, H.payload(self.q), plan), set())


class ProfileInputs(unittest.TestCase):
    def codes(self, mutate):
        try:
            rb.import_workbook(xb.build(copy.deepcopy(self._spec(mutate))), as_of=H.AS_OF)
        except rb.RateBookRejected as e:
            return {p["code"] for p in e.problems}
        return set()

    def _spec(self, mutate):
        s = xb.valid_spec(crew_profiles=True)
        mutate(s)
        return s

    def test_efficiency_must_be_positive_and_finite_but_may_exceed_100(self):
        for bad in (0, -5, "104%", None, 301):
            self.assertTrue(self.codes(lambda s: xb.row(s, "Crews", "crew_id", "CR11").update(efficiency_pct=bad)), bad)
        self.assertEqual(self.codes(lambda s: xb.row(s, "Crews", "crew_id", "CR11").update(efficiency_pct=125)), set())

    def test_difficulty_responses_are_required_and_positive(self):
        self.assertIn("MISSING_DIFFICULTY_RESPONSE", self.codes(lambda s: xb.row(s, "Crews", "crew_id", "CR11").update(difficulty_hard=None)))
        self.assertTrue(self.codes(lambda s: xb.row(s, "Crews", "crew_id", "CR11").update(difficulty_hard=0)))
        self.assertTrue(self.codes(lambda s: xb.row(s, "Crews", "crew_id", "CR11").update(difficulty_easy=-1)))

    def test_rate_basis_workday_and_profile_version_are_explicit(self):
        self.assertTrue(self.codes(lambda s: s["Labor"]["rows"][0].update(rate_basis=None)))
        self.assertTrue(self.codes(lambda s: s["Labor"]["rows"][0].update(rate_basis="measured")))
        self.assertTrue(self.codes(lambda s: s["Crew_Production"]["rows"][0].update(rate_basis=None)))
        self.assertTrue(self.codes(lambda s: xb.row(s, "Meta", "key", "workday_hours").update(value=0)))
        self.assertTrue(self.codes(lambda s: s["Meta"].update(rows=[r for r in s["Meta"]["rows"] if r["key"] != "workday_hours"])))
        self.assertTrue(self.codes(lambda s: xb.row(s, "Crews", "crew_id", "CR11").update(profile_version=None)))

    def test_crew_options_are_validated(self):
        self.assertIn("UNKNOWN_CREW", self.codes(lambda s: s["Crew_Production"]["rows"][0].update(crew_id="CR99")))
        self.assertIn("UNKNOWN_TASK", self.codes(lambda s: s["Crew_Production"]["rows"][0].update(task_id="L77")))
        self.assertIn("DUPLICATE_CREW_OPTION", self.codes(lambda s: s["Crew_Production"]["rows"].append(dict(s["Crew_Production"]["rows"][0]))))
        self.assertIn("MISSING_PRODUCTION_RATE", self.codes(lambda s: s["Crew_Production"]["rows"][0].update(production_rate=None)))

    def test_profile_changes_change_the_labor_hash_and_version_the_book(self):
        a = H.book(profiles=True)
        b = H.book(lambda s: xb.row(s, "Crews", "crew_id", "CR11").update(efficiency_pct=110, profile_version="A2"), profiles=True)
        self.assertNotEqual(a["hashes"]["labor_sha256"], b["hashes"]["labor_sha256"])
        c = H.book(lambda s: xb.row(s, "Materials", "item_id", "M05").update(unit_price=9), profiles=True)
        self.assertEqual(a["hashes"]["labor_sha256"], c["hashes"]["labor_sha256"])


class Comparison(unittest.TestCase):
    def test_three_crews_are_compared_independently_for_every_task(self):
        book = H.book(profiles=True)
        q = {"D12": 1000, "D04": 240, "D03": 130, "D06": 700, "D08": 16, "D07": 600, "D11": 600, "D09": 4, "D10": 120}
        est = run(book, H.payload(q), H.eng_plan(book, preferred="CR13"))
        cmp_ = est["labor"]["crew_comparison"]
        crews = {c["crew_id"]: c for c in cmp_["crews"]}
        self.assertEqual({k: crews[k]["baseline_efficiency_pct"] for k in ("CR11", "CR12", "CR13")}, {"CR11": 104, "CR12": 94, "CR13": 88})
        self.assertEqual((crews["CR13"]["complete"], crews["CR11"]["complete"], crews["CR12"]["complete"]), (True, False, False))   # only Crew 3 has an operator
        # independent recomputation of Crew 3's job totals
        tasks = {t["task_id"]: t for t in book["labor_tasks"]}
        scale, hours, cost = Decimal("1.10"), Decimal(0), Decimal(0)
        base_hours = Decimal(0)
        for t in tasks.values():
            qty = E(q[t["driver_key"]])
            base = (E(t["production_rate"]) * scale).quantize(Decimal("0.01"), rounding="ROUND_HALF_EVEN")
            h = qty / (base * E(88) / 100)
            hours += h
            base_hours += qty / base
            cost += (h * HOURLY["CR13"]).quantize(CENT, rounding="ROUND_HALF_UP")
        self.assertEqual(E(crews["CR13"]["labor_cost"]), cost)
        self.assertAlmostEqual(crews["CR13"]["crew_hours"], float(hours), places=4)
        self.assertAlmostEqual(crews["CR13"]["worker_hours"], float(hours * 3), places=4)
        self.assertAlmostEqual(crews["CR13"]["crew_days"], float(hours / 8), places=4)
        self.assertAlmostEqual(crews["CR13"]["effective_efficiency_pct"], float(base_hours / hours * 100), places=3)      # = 88 at standard difficulty
        self.assertAlmostEqual(crews["CR13"]["effective_efficiency_pct"], 88.0, places=3)
        # per task: all eligible candidates are shown, ineligible ones with their reason
        drill = next(t for t in cmp_["tasks"] if t["task_id"] == "L02")
        by = {c["crew_id"]: c for c in drill["candidates"]}
        self.assertTrue(by["CR13"]["eligible"] and by["CR13"]["calculable"])
        self.assertFalse(by["CR11"]["eligible"])
        self.assertIn("lacks required role", by["CR11"]["reasons"][0])
        self.assertNotIn("labor_cost", by["CR11"])
        self.assertTrue(by["CR13"]["selected"])
        # the plan's selected crews are exactly what was priced
        self.assertEqual({l["task_id"]: l["crew_id"] for l in est["labor"]["lines"]}, {t["task_id"]: "CR13" for t in book["labor_tasks"]})

    def test_difficulty_changes_each_crews_row_differently(self):
        book = H.book(profiles=True)
        q = {"D12": 1000, "D04": 240, "D03": 130, "D06": 700, "D08": 16, "D07": 600, "D11": 600, "D09": 4, "D10": 120}
        def totals(level):
            est = run(book, H.payload(q), H.eng_plan(book, preferred="CR13", default=level))
            return {c["crew_id"]: c for c in est["labor"]["crew_comparison"]["crews"]}
        easy, hard = totals("easy"), totals("hard")
        self.assertLess(easy["CR11"]["crew_hours"], hard["CR11"]["crew_hours"])
        r11 = hard["CR11"]["crew_hours"] / easy["CR11"]["crew_hours"]
        r13 = hard["CR13"]["crew_hours"] / easy["CR13"]["crew_hours"]
        self.assertGreater(r11, r13)                    # Crew 1 loses more on hard work than Crew 3

    def test_unquantified_or_uncleared_crews_are_shown_as_not_calculable_never_costed(self):
        book = H.book(profiles=True)
        cmp_ = pcrews.compare(book, {"D12": None, "D04": 100}, {"default": "standard", "overrides": {}}, {"CR1": E(108.0)})
        l01 = next(t for t in cmp_["tasks"] if t["task_id"] == "L01")
        self.assertTrue(all(not c["calculable"] and "unresolved" in " ".join(c["reasons"]) for c in l01["candidates"]))
        l02 = next(t for t in cmp_["tasks"] if t["task_id"] == "L02")
        self.assertEqual([c["crew_id"] for c in l02["candidates"] if c["calculable"]], ["CR1"])


# ---------------------------------------------------------------------------------------------------------------- workflow

POLICY = {**W.POLICY, "allow_mixed_crew_plan": True}      # engine-mechanics baseline: these tests exercise mixed-crew math. The default policy REJECTS mixed plans (tests/test_single_crew_plan.py)


def start(scope=None, book=None, policy=None):
    return wf.start(scope or sf.base_scope(), None, ratebook=book or H.book(profiles=True), policy=policy or POLICY)


def ready_to_plan(book=None):
    s = start(book=book)
    W.to_scope_cleared(s)
    W.labor(s)
    return s


def plan_kw(**over):
    kw = dict(by="Pat Estimator", note="crew selection and job difficulty reviewed", preferred_crew="CR13", difficulty={"default": "standard"})
    kw.update(over)
    return kw


class CrewPlanWorkflow(unittest.TestCase):
    def test_a_book_with_crew_choices_needs_a_named_crew_plan_before_anything_prices(self):
        s = ready_to_plan()
        self.assertEqual(s["status"], wf.LABOR_REVIEW)
        self.assertIn("CREW_PLAN_REQUIRED", W.blocking(s))
        self.assertIsNone(s["estimate"])
        ex = next(e for e in s["exceptions"] if e["code"] == "CREW_PLAN_REQUIRED")
        self.assertEqual(ex["required_decision"], {"type": "crew_plan"})
        cmp_ = ex["evidence"][0]["BASE"]                       # the comparison the workspace shows
        self.assertEqual({c["crew_id"] for c in cmp_["crews"]}, {"CR1", "CR2", "CR11", "CR12", "CR13", "CR14"})
        self.assertFalse(cmp_["difficulty_approved"])
        self.assertIn("provisional", cmp_["difficulty_note"])
        self.assertEqual(s["crew_comparison"]["BASE"]["workday_hours"], 8)
        with self.assertRaises(wf.GateError):
            wf.release(s, "Test Approver", s["scope"]["scope_version"], "0" * 64)

    def test_approving_the_plan_prices_with_the_selected_crew_and_binds_it_to_the_digest(self):
        s = ready_to_plan()
        wf.approve_crew_plan(s, **plan_kw())
        self.assertEqual(s["status"], wf.READY)
        est = s["estimate"]["scenarios"]["BASE"]["labor"]
        self.assertEqual({l["crew_id"] for l in est["lines"]}, {"CR13"})
        self.assertEqual((est["crew_plan"]["plan_version"], est["crew_plan"]["approved_by"], est["crew_plan"]["difficulty"]["source"]), (1, "Pat Estimator", "human"))
        self.assertEqual(est["crew_plan"]["crew_profiles"]["CR13"], "C1")
        d1 = s["proposal_digest"]
        wf.approve_crew_plan(s, **plan_kw(preferred_crew="CR12", assignments={"L02": "CR13"}))      # a different crew choice
        self.assertEqual(s["crew_plan"]["plan_version"], 2)
        self.assertNotEqual(s["proposal_digest"], d1)
        with self.assertRaises(wf.GateError):
            wf.release(s, "Test Approver", s["scope"]["scope_version"], d1)
        d2 = s["proposal_digest"]
        wf.approve_crew_plan(s, **plan_kw(preferred_crew="CR12", assignments={"L02": "CR13"}, difficulty={"default": "hard"}))   # same crews, harder job
        self.assertNotEqual(s["proposal_digest"], d2)
        pkg = wf.release(s, "Test Approver", s["scope"]["scope_version"], s["proposal_digest"])
        self.assertEqual(pkg["estimate"]["scenarios"]["BASE"]["labor"]["crew_plan"]["difficulty"]["default"], "hard")
        self.assertIn("crew_plan_approved", {q["type"] for q in wf.qualifications(s)})

    def test_crews_can_be_assigned_by_task(self):
        s = ready_to_plan()
        wf.approve_crew_plan(s, **plan_kw(preferred_crew=None, assignments={"L02": "CR13", "L03": "CR12", "L04": "CR12"}, use_default_for_unassigned=True))
        crew_of = {l["task_id"]: l["crew_id"] for l in s["estimate"]["scenarios"]["BASE"]["labor"]["lines"]}
        self.assertEqual((crew_of["L02"], crew_of["L03"], crew_of["L01"]), ("CR13", "CR12", "CR1"))     # unassigned tasks only by explicit statement

    def test_refusals_leave_state_untouched(self):
        s = ready_to_plan()
        before = copy.deepcopy(s)
        cases = [plan_kw(preferred_crew="CR11"),                                                          # CR11 cannot drill; nothing else is stated
                 plan_kw(preferred_crew="CR13", assignments={"L02": "CR11"}),                           # unsuitable by assignment
                 plan_kw(preferred_crew="CR99"), plan_kw(assignments={"L99": "CR13"}), plan_kw(assignments={"L01": "CR99"}),
                 plan_kw(difficulty={"default": "extreme"}), plan_kw(difficulty={}), plan_kw(difficulty={"default": "hard", "overrides": {"D99": "easy"}}),
                 plan_kw(difficulty={"default": "hard", "overrides": {"D03": "brutal"}}), plan_kw(by=" "), plan_kw(use_default_for_unassigned="yes"),
                 plan_kw(preferred_crew=None, assignments={})]
        for kw in cases:
            with self.assertRaises(wf.GateError, msg=repr(kw)[:90]):
                wf.approve_crew_plan(s, **kw)
        self.assertEqual(s, before)

    def test_crew_with_efficiency_cannot_slip_past_the_required_role_via_the_workflow(self):
        s = ready_to_plan()
        with self.assertRaises(wf.GateError) as cm:
            wf.approve_crew_plan(s, **plan_kw(preferred_crew="CR11", assignments={"L02": "CR11"}))
        self.assertIn("CREW_UNSUITABLE", str(cm.exception))

    # ---- AI recommendation: cited evidence, human approval
    def test_ai_difficulty_needs_citations_and_never_prices_until_a_human_approves_it(self):
        s = ready_to_plan()
        for bad in (dict(evidence_refs=[]), dict(evidence_refs=None), dict(evidence_refs=[{"doc_id": "PM"}]), dict(evidence_refs=[{"doc_id": "", "page": 3}]),
                    dict(default="extreme", evidence_refs=[{"doc_id": "PM", "page": 3}]), dict(overrides={"D99": "hard"}, evidence_refs=[{"doc_id": "PM", "page": 3}])):
            kw = dict(by="ai:difficulty-model", default="hard"); kw.update(bad)
            with self.assertRaises(wf.GateError):
                wf.record_difficulty_recommendation(s, **kw)
        self.assertIsNone(s["difficulty_recommendation"])
        wf.record_difficulty_recommendation(s, by="ai:difficulty-model", default="standard", overrides={"D04": "hard"},
                                            evidence_refs=[{"doc_id": "PROJECT_MANUAL", "page": 17, "excerpt": "core drill every footing hole through pavement"}],
                                            rationale="pavement coring is slow")
        self.assertIn("DIFFICULTY_RECOMMENDATION_PENDING", {e["code"] for e in s["exceptions"]})
        self.assertEqual(s["status"], wf.LABOR_REVIEW)
        self.assertIsNone(s["estimate"])                                      # a recommendation prices nothing
        with self.assertRaises(wf.GateError):
            wf.approve_crew_plan(s, **plan_kw(difficulty=None, use_recommendation=False))
        wf.approve_crew_plan(s, **plan_kw(difficulty=None, use_recommendation=True))
        self.assertEqual(s["status"], wf.READY)
        d = s["crew_plan"]["difficulty"]
        self.assertEqual((d["source"], d["overrides"], d["recommended_by"]), ("ai_recommended_human_approved", {"D04": "hard"}, "ai:difficulty-model"))
        self.assertEqual(d["evidence_refs"][0]["doc_id"], "PROJECT_MANUAL")
        self.assertEqual(line_of(s, "L02")["difficulty_level"], "hard")
        self.assertEqual(line_of(s, "L01")["difficulty_level"], "standard")

    def test_approving_with_no_recommendation_on_file_is_refused(self):
        s = ready_to_plan()
        with self.assertRaises(wf.GateError):
            wf.approve_crew_plan(s, **plan_kw(difficulty=None, use_recommendation=True))

    # ---- versioning and invalidation
    def test_changed_crew_profiles_void_the_plan_and_the_old_digest(self):
        s = ready_to_plan()
        wf.approve_crew_plan(s, **plan_kw())
        d1 = s["proposal_digest"]
        newer = H.book(lambda sp: (xb.row(sp, "Meta", "key", "version").update(value="1.1.0"),
                                   xb.row(sp, "Crews", "crew_id", "CR13").update(efficiency_pct=95, profile_version="C2")), profiles=True)
        wf.attach_ratebook(s, newer, by="Test Approver", note="Crew 3 recalibrated")
        self.assertIsNone(s["crew_plan"])
        self.assertIn("crew_plan_invalidated", [a["event"] for a in s["audit"]])
        self.assertEqual(s["status"], wf.LABOR_REVIEW)
        self.assertIn("CREW_PLAN_REQUIRED", W.blocking(s))
        if s["labor_review"]["status"] != "decided":
            W.labor(s)
        wf.approve_crew_plan(s, **plan_kw())
        self.assertEqual(s["estimate"]["scenarios"]["BASE"]["labor"]["crew_plan"]["crew_profiles"]["CR13"], "C2")
        self.assertNotEqual(s["proposal_digest"], d1)

    def test_scope_revision_voids_plan_and_recommendation(self):
        s = start()
        W.to_scope_cleared(s)
        W.labor(s)
        wf.record_difficulty_recommendation(s, by="ai:m", default="hard", evidence_refs=[{"doc_id": "PM", "page": 1}])
        wf.approve_crew_plan(s, **plan_kw())
        g = sf.fact(12.0, doc="ADD03", page=1, sheet="ADD-03", rev=3)
        wf.revise_scope(s, [{"path": "/gates/2/clear_width_ft", "fact": g}], source={"doc_id": "ADD03", "doc_revision": 3, "sha256": W.SHA3}, by="intake", note="x")
        self.assertIsNone(s["crew_plan"])
        self.assertIsNone(s["difficulty_recommendation"])

    def test_difficulty_and_efficiency_never_change_takeoff_quantities_or_materials(self):
        s = ready_to_plan()
        wf.approve_crew_plan(s, **plan_kw(difficulty={"default": "easy"}))
        q_easy, mats_easy, take_easy = copy.deepcopy(s["quantities"]), copy.deepcopy(s["estimate"]["scenarios"]["BASE"]["materials"]), copy.deepcopy(s["takeoff"])
        wf.approve_crew_plan(s, **plan_kw(preferred_crew="CR12", assignments={"L02": "CR13"}, difficulty={"default": "hard", "overrides": {"D03": "easy"}}))
        self.assertEqual(s["quantities"], q_easy)
        self.assertEqual(s["takeoff"], take_easy)
        self.assertEqual(s["estimate"]["scenarios"]["BASE"]["materials"], mats_easy)

    def test_neutral_books_need_no_crew_plan(self):
        s = start(book=H.book())
        W.to_scope_cleared(s)
        W.labor(s)
        self.assertEqual(s["status"], wf.READY)
        self.assertEqual(s["estimate"]["scenarios"]["BASE"]["labor"]["crew_plan"], None)

    def test_summary_exposes_the_comparison_for_the_estimating_workspace(self):
        s = ready_to_plan()
        wf.approve_crew_plan(s, **plan_kw())
        cmp_ = s["estimate"]["scenarios"]["BASE"]["labor"]["crew_comparison"]
        row = next(c for c in cmp_["crews"] if c["crew_id"] == "CR11")
        for key in ("baseline_efficiency_pct", "difficulty_response", "effective_efficiency_pct", "crew_hours", "worker_hours", "crew_days", "labor_cost", "complete"):
            self.assertIn(key, row)
        self.assertTrue(s["crew_comparison"]["BASE"]["difficulty_approved"])


def line_of(s, task, scope="BASE"):
    return next(l for l in s["estimate"]["scenarios"][scope]["labor"]["lines"] if l["task_id"] == task)


class DavisBaconCrews(unittest.TestCase):
    """Every compared crew uses the approved classifications, wages, fringes and employer costs; efficiency never reduces them."""

    def ready(self, book=None):
        s = wf.start(W.davis_bacon_scope(), None, ratebook=book or H.book(profiles=True), policy=POLICY)
        W.approve_rules(s)
        return s

    def test_every_candidate_crew_needs_cleared_roles_and_is_costed_at_statutory_rates(self):
        s = self.ready()
        self.assertEqual(W.blocking(s), {"WAGE_DETERMINATION_REQUIRED", "CREW_PLAN_REQUIRED"})
        self.assertEqual(next(e for e in s["exceptions"] if e["code"] == "WAGE_DETERMINATION_REQUIRED")["required_decision"]["roles"], ["R1", "R2", "R3", "R4"])
        rows = W.good_rows()
        rows[3] = W.row("R4", W.OPR, fringe_rate=None)                                 # operator (R4) uncleared
        wf.record_wage_determination(s, **W.wage_args(rows=rows))
        cmp_ = s["crew_comparison"]["BASE"]
        crews = {c["crew_id"]: c for c in cmp_["crews"]}
        by_task = {t["task_id"]: {c["crew_id"]: c for c in t["candidates"]} for t in cmp_["tasks"]}
        self.assertTrue(by_task["L01"]["CR11"]["calculable"])                          # roles R1,R3 cleared => Crew 1 is costed
        self.assertFalse(by_task["L01"]["CR13"]["calculable"])                         # Crew 3 contains R4 => not costed, never guessed
        self.assertIn("not cleared", by_task["L01"]["CR13"]["reasons"][0])
        self.assertIsNone(s["estimate"])                                               # and the labor basis as a whole stays blocked
        self.assertIn("WAGE_FRINGE_MISSING", W.blocking(s))

    def test_efficiency_changes_hours_not_wages_or_fringes(self):
        def priced(eff):
            book = H.book(lambda sp: xb.row(sp, "Crews", "crew_id", "CR13").update(efficiency_pct=eff), profiles=True)
            s = self.ready(book)
            wf.record_wage_determination(s, **W.wage_args())
            wf.approve_crew_plan(s, **plan_kw())
            return s["estimate"]["scenarios"]["BASE"]["labor"]
        a, b = priced(88), priced(60)
        la, lb = a["lines"][0], b["lines"][0]
        self.assertEqual(la["crew_id"], "CR13")
        # per crew-hour the three statutory components are IDENTICAL; only the hours differ
        per_hour = lambda l, k: E(l[k]) / E(l["crew_hours"])
        for k in ("wages", "fringe", "employer_costs"):
            self.assertAlmostEqual(float(per_hour(la, k)), float(per_hour(lb, k)), places=1)
        self.assertGreater(lb["crew_hours"], la["crew_hours"])
        # Crew 3 = 2 installers + operator: wages 2 x 24.50 + 29.80, fringe 2 x 9.10 + 11.25, employer 20% of wages
        self.assertAlmostEqual(float(per_hour(la, "wages")), 78.8, places=1)
        self.assertAlmostEqual(float(per_hour(la, "fringe")), 29.45, places=1)
        self.assertAlmostEqual(float(per_hour(la, "employer_costs")), 15.76, places=1)
        self.assertEqual(E(la["wages"]) + E(la["fringe"]) + E(la["employer_costs"]), E(la["extended"]))
        self.assertGreater(b["subtotal"], a["subtotal"])                               # slower crew costs more at the same statutory rates

    def test_difficulty_never_lowers_a_statutory_hourly_rate(self):
        def lab(level):
            s = self.ready()
            wf.record_wage_determination(s, **W.wage_args())
            wf.approve_crew_plan(s, **plan_kw(difficulty={"default": level}))
            return s["estimate"]["scenarios"]["BASE"]["labor"]
        easy, hard = lab("easy"), lab("hard")
        for le, lh in zip(easy["lines"], hard["lines"]):
            self.assertEqual((le["crew_rate_per_hr"], le["crew_id"]), (lh["crew_rate_per_hr"], lh["crew_id"]))      # same hourly cost on every difficulty
            per = lambda l, k: round(E(l[k]) / E(l["crew_hours"]), 0)
            for k in ("wages", "fringe", "employer_costs"):
                self.assertEqual(per(le, k), per(lh, k))
        self.assertLess(easy["subtotal"], hard["subtotal"])          # harder work takes more hours at the same statutory rates

    def test_prevailing_wage_job_with_a_crew_plan_releases_and_the_digest_binds_wages_and_plan(self):
        s = self.ready()
        wf.record_wage_determination(s, **W.wage_args())
        self.assertIn("CREW_PLAN_REQUIRED", W.blocking(s))
        self.assertEqual(s["status"], wf.LABOR_REVIEW)
        self.assertEqual(s["crew_comparison"]["BASE"]["crews"][0]["crew_id"], "CR1")
        wf.approve_crew_plan(s, **plan_kw(difficulty={"default": "hard"}))
        self.assertEqual(s["status"], wf.READY)
        d1 = s["proposal_digest"]
        lab = s["estimate"]["scenarios"]["BASE"]["labor"]
        self.assertEqual(lab["basis"], "prevailing_wage")
        self.assertEqual(lab["components"]["fringe"] > 0, True)
        wf.record_wage_determination(s, **W.wage_args(employer_burden=dict(pct=0.25, source_ref="revised")))
        self.assertEqual((s["status"], s["crew_plan"]["plan_version"]), (wf.READY, 1))     # the crew choice stands; the repriced wages change the digest
        self.assertNotEqual(s["proposal_digest"], d1)
        with self.assertRaises(wf.GateError):
            wf.release(s, "Test Approver", s["scope"]["scope_version"], d1)


if __name__ == "__main__":
    unittest.main()

"""HTTP-level tests of the integrated pricing path on ANVIL 2's reference rate book v2.3.0 (fictional): four fleet crews CR11-CR14, crew plans,
read-only previews, Davis-Bacon blockers, release-digest invalidation. Every hour and dollar is recomputed here from the rate book's inputs and the
stated formulas; no value is copied from the engine's answer. All data is fictional."""
import copy, json, uuid, os, threading, unittest, urllib.error, urllib.request
from decimal import Decimal, ROUND_HALF_UP
from http.server import ThreadingHTTPServer
from unittest import mock

from api import server
from engine import integration, pricing_service as svc
from engine import workflow as wf
from tests.test_ratebook_workflow import wage_args

KEY = "demo-test-key-not-real"
OWNER = "a" * 64
G3 = "EX-MISSING_VALUE-/gates/2/clear_width_ft"
WHO = {"by": "Pat Estimator", "note": "reviewed"}
CENT = Decimal("0.01")
E = lambda x: Decimal(repr(x)) if isinstance(x, float) else Decimal(x)
FLEET = ["CR11", "CR12", "CR13", "CR14"]


def plan(pref="CR13", assign=None, diff="standard", over=None, **extra):
    """Draft/approved plan body. Legacy default crews are never selected implicitly (use_default_for_unassigned stays false)."""
    return {**({"preferred_crew": pref} if pref else {}), "assignments": {"L02": "CR13", **(assign or {})}, "use_default_for_unassigned": False,
            "difficulty": {"default": diff, "overrides": over or {}}, **extra}


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.book = integration.load_book()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"ENGINE_API_KEY": KEY, "ENGINE_DEMO_ROUTES": "1"})
        self.env.start()
        server.PROJECTS.clear()
        server.META.clear()
        code, out = self.call("POST", "/demo/projects", {})
        self.assertEqual(code, 201, out)
        self.pid = out["project_id"]

    def tearDown(self):
        self.env.stop()

    def call(self, method, path, body=None, owner=OWNER, idem=None):
        req = urllib.request.Request(self.base + path, method=method, data=None if body is None else json.dumps(body).encode())
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Engine-Key", KEY)
        if "/decisions/" in path and idem is not False:
            req.add_header("Idempotency-Key", idem or ("t-" + uuid.uuid4().hex))      # one fresh key per intentional decision
        if owner:
            req.add_header("X-Demo-Owner", owner)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def post(self, suffix, body, expect=200):
        code, out = self.call("POST", f"/projects/{self.pid}/{suffix}", body)
        self.assertEqual(code, expect, out)
        return out

    def get(self):
        return self.call("GET", f"/projects/{self.pid}")[1]

    def to_labor_gate(self):
        self.post("scope/resolve", {"exception_id": G3, "value": 10.0, **WHO})
        sha = next(e["required_decision"]["sha256"] for e in self.get()["exceptions"] if e["code"] == "QUANTITY_RULESET_UNAPPROVED")
        return self.post("decisions/ruleset-approval", {**WHO, "ruleset_sha256": sha})

    def to_wage_cleared(self):
        self.to_labor_gate()
        return self.post("decisions/wage-determination", wage_args())

    def hourly(self, crew_id):
        rows = {r["role_key"]: r for r in wage_args()["rows"]}
        members = next(c for c in self.book["crews"] if c["crew_id"] == crew_id)["members"]
        parts = {"wages": Decimal(0), "fringe": Decimal(0), "employer": Decimal(0)}
        for rk, n in members.items():
            parts["wages"] += n * E(rows[rk]["base_rate"])
            parts["fringe"] += n * E(rows[rk]["fringe_rate"])
            parts["employer"] += n * E(rows[rk]["base_rate"]) * E(0.20)
        return parts

    def qty(self, task_id):
        return E(next(i["quantity"] for i in self.get()["pricing"]["crew_comparison"]["BASE"]["tasks"] if i["task_id"] == task_id))

    def task(self, crew_id, task_id, level="standard"):
        """First-principles (crew_hours, worker_hours, labor_cost) for one task and crew from the book's own inputs."""
        rb = self.book
        t = next(t for t in rb["labor_tasks"] if t["task_id"] == task_id)
        crew = next(c for c in rb["crews"] if c["crew_id"] == crew_id)
        opt = t if t["crew_id"] == crew_id else next(o for o in rb["crew_options"] if o["task_id"] == task_id and o["crew_id"] == crew_id)
        self.assertEqual(opt["rate_basis"], "standard")
        hours = self.qty(task_id) / (E(opt["production_rate"]) * (E(crew["efficiency_pct"]) / 100) * E(crew["difficulty"][level]))
        cost = (hours * sum(self.hourly(crew_id).values())).quantize(CENT, rounding=ROUND_HALF_UP)       # owner decision 2026-10-16: ONE rounding per task (hours x loaded rate)
        return hours, hours * sum(crew["members"].values()), cost

    def labor_total(self, assignment):
        h = w = c = Decimal(0)
        for t in self.book["labor_tasks"]:
            a, b, d = self.task(assignment[t["task_id"]], t["task_id"])
            h, w, c = h + a, w + b, c + d
        return h, w, c


class FleetAndContract(Base):
    def test_four_fleet_crews_load_from_rate_book_2_3_0_and_the_workbook_is_pinned(self):
        out = self.get()["pricing"]
        self.assertEqual((out["ratebook_ref"]["ratebook_id"], out["ratebook_ref"]["version"], out["ratebook_ref"]["classification"]),
                         ("IFI-REF-FICTIONAL", "2.3.0", "FICTIONAL_DEMO"))
        crews = out["crews"]["crews"]
        self.assertEqual([c["crew_id"] for c in crews], FLEET)
        self.assertEqual([c["efficiency_pct"] for c in crews], [104, 94, 88, 97])
        self.assertEqual([c["name"] for c in crews], ["Crew 1", "Crew 2", "Crew 3", "Crew 4"])
        crew4 = next(c for c in self.book["crews"] if c["crew_id"] == "CR14")
        self.assertEqual(crew4["members"], {"R1": 1, "R2": 2, "R4": 1})
        self.assertEqual(crew4["difficulty"], {"easy": 1.05, "standard": 1.0, "hard": 0.92})
        import hashlib
        self.assertEqual(hashlib.sha256(integration.BOOK_PATH.read_bytes()).hexdigest(), integration.BOOK_SHA256)

    def test_a_different_workbook_is_refused(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".xlsx") as f:
            f.write(integration.BOOK_PATH.read_bytes() + b"x")
            f.flush()
            with self.assertRaises(ValueError):
                integration.load_book(f.name)

    def test_fleet_average_is_unweighted_over_all_four_crews_and_displays_95_8(self):
        out = self.get()
        self.assertEqual(out["crews"]["fleet_average_pct"], 95.8)
        self.assertEqual(out["crews"]["fleet_average_exact_pct"], 95.75)
        self.assertEqual(out["crews"]["crew_count"], 4)
        self.assertEqual(sum(c["efficiency_pct"] for c in out["crews"]["crews"]) / 4, 95.75)

    def test_the_frozen_pricing_interface_matches_its_pinned_description(self):
        pinned = json.loads((integration.ROOT / "docs/pricing/engine_interface.v1.json").read_text())
        self.assertEqual(svc.SURFACE, pinned)
        self.assertEqual(svc.CONTRACT_VERSION, "pricing-service.v1")
        self.assertEqual(self.get()["pricing"]["contract_version"], "pricing-service.v1")
        for name in sum((pinned[k] for k in ("reads_ratebook", "reads_state", "decisions")), []):
            self.assertTrue(callable(getattr(svc, name)), name)

    def test_summary_exposes_no_raw_book_and_no_workbook_file_hash(self):
        text = json.dumps(self.get())
        self.assertNotIn("file_sha256", text)
        self.assertNotIn("base_wage_per_hr", text)
        for m in self.book["materials"][:5]:
            self.assertNotIn(m["item"], text)

    def test_typed_decisions_are_not_accepted_through_generic_resolution(self):
        self.post("scope/resolve", {"exception_id": G3, "value": 10.0, **WHO})
        ex = next(e for e in self.get()["exceptions"] if e["code"] == "QUANTITY_RULESET_UNAPPROVED")
        self.post("scope/resolve", {"exception_id": ex["exception_id"], "value": ex["required_decision"]["sha256"], **WHO}, expect=409)

    def test_a_visitor_ruleset_approval_never_marks_the_ruleset_contractor_approved(self):
        before = self.get()["pricing"]["ruleset"]
        self.assertEqual((before["contractor_approved"], before["approved"], before["status"]), (False, False, "draft_pending_estimator_review"))
        after = self.to_labor_gate()["pricing"]["ruleset"]
        self.assertTrue(after["approved"] and after["approved_by"] == "Pat Estimator")
        self.assertFalse(after["contractor_approved"])
        self.assertIn("outstanding", after["contractor_note"])
        self.assertEqual(after["status"], "draft_pending_estimator_review")

    def test_malformed_and_unknown_decision_bodies_fail_closed_without_changing_state(self):
        self.to_labor_gate()
        before = self.get()
        for suffix, body in (("decisions/crew-plan", {**plan(), **WHO, "assignments": "L02"}), ("decisions/crew-plan", {**plan(), **WHO, "surprise": 1}),
                             ("decisions/crew-plan", {**plan(), **WHO, "difficulty": "hard"}), ("decisions/crew-plan", {**plan(), **WHO, "assignments": {"L02": 5}}),
                             ("decisions/wage-determination", {**WHO, "rows": "x", "schedule": 3}), ("decisions/nonsense", {**WHO}), ("crew-plan/preview", {"difficulty": 4})):
            code, _ = self.call("POST", f"/projects/{self.pid}/{suffix}", body)
            self.assertIn(code, (400, 404, 409), (suffix, body))
        after = self.get()
        self.assertEqual((before["audit"], before["status"], before["pricing"]["crew_plan"]), (after["audit"], after["status"], after["pricing"]["crew_plan"]))

    def test_portfolio_fixture_is_static_and_historical_crews_agree_with_the_book(self):
        before = self.call("GET", "/demo/portfolio")[1]
        self.to_wage_cleared()
        self.post("decisions/crew-plan", {**WHO, **plan("CR14")})
        self.assertEqual(self.call("GET", "/demo/portfolio")[1], before)
        booked = {c["crew_id"]: (c["name"], c["efficiency_pct"]) for c in integration.crew_roster(self.book)["crews"]}
        seen = {c["crew_id"] for p in before["projects"] for c in p["crew_plan"]}
        self.assertTrue(seen and seen <= set(booked))                  # portfolio crews are fleet crews of the rate book, same name and efficiency
        for p in before["projects"]:
            for c in p["crew_plan"]:
                self.assertEqual((c["name"], c["efficiency_pct"]), booked[c["crew_id"]])


class Compliance(Base):
    def test_unresolved_wages_show_hours_only_no_money_and_no_provisional_dollars(self):
        out = self.to_labor_gate()
        self.assertEqual(out["status"], "needs_labor_review")
        self.assertIsNone(out["estimate"])
        self.assertIsNone(out["proposal_digest"])
        self.assertIn("WAGE_DETERMINATION_REQUIRED", out["pricing"]["pricing_blocked_by"])
        for t in out["pricing"]["crew_comparison"]["BASE"]["tasks"]:
            for c in t["candidates"]:
                self.assertNotIn("labor_cost", c)
                if c["eligible"]:
                    self.assertTrue(c["hours_only"] and c["crew_hours"] > 0)
        prov = out["pricing"]["provisional"]
        self.assertIsNone(prov["provisional_labor_cost"])
        self.assertFalse(prov["complete"])
        self.assertTrue(prov["provisional"] and not prov["releasable"])
        self.assertIsNone(out["pricing"]["economics"])

    def test_company_rate_decisions_are_refused_on_a_prevailing_wage_project(self):
        self.to_labor_gate()
        self.post("labor/resolve", {"by": "Lee", "decision": "verified_standard", "certified_payroll": False, "applicability_review": "assumed",
                                    "source_refs": ["x"], "note": "company rates"}, expect=409)
        self.assertIsNone(self.get()["estimate"])

    def test_unapproved_wage_classifications_never_produce_compliant_pricing(self):
        self.to_labor_gate()
        cases = {}
        short = wage_args(); short["rows"] = short["rows"][:3]                                # operator role unclassified
        cases["unclassified"] = short
        mism = wage_args(); mism["rows"][0]["base_rate"] = 19.0                               # rate differs from the decision schedule
        cases["mismatch"] = mism
        pend = wage_args(); pend["rows"][3]["classification_status"] = "proposed_for_conformance"   # operator class not listed, conformance only proposed
        pend["rows"][3]["classification"] = "Fence erector (not in decision)"
        cases["conformance_pending"] = pend
        cases["production_unapproved"] = wage_args(production_rates_approved=False)
        for name, body in cases.items():
            out = self.post("decisions/wage-determination", body)
            self.assertIsNone(out["estimate"], name)
            self.assertIsNone(out["proposal_digest"], name)
            self.assertFalse(out["pricing"]["wage"]["cleared"], name)
            self.assertTrue(out["pricing"]["wage"]["blockers"], name)
            self.assertIsNone(out["pricing"]["economics"], name)
            if name == "unclassified":                    # the operator role is uncleared, so the crews that contain it (CR13, CR14) get no cost at all
                self.assertTrue(all("labor_cost" not in c for t in out["pricing"]["crew_comparison"]["BASE"]["tasks"] for c in t["candidates"] if c["crew_id"] in ("CR13", "CR14")), name)
        self.assertEqual(self.get()["status"], "needs_labor_review")

    def test_an_operator_on_the_crew_does_not_establish_wage_compliance(self):
        out = self.to_labor_gate()
        t = next(t for t in out["pricing"]["crew_comparison"]["BASE"]["tasks"] if t["task_id"] == "L02")
        for c in t["candidates"]:
            if c["crew_id"] in ("CR13", "CR14"):
                self.assertTrue(c["eligible"] and c.get("hours_only") and "labor_cost" not in c)
                self.assertTrue(any("not cleared" in n for n in c["cost_note"]))

    def test_cleared_wages_alone_do_not_price_without_an_approved_crew_plan(self):
        out = self.to_wage_cleared()
        self.assertIsNone(out["estimate"])
        self.assertIn("CREW_PLAN_REQUIRED", out["pricing"]["pricing_blocked_by"])
        self.assertTrue(out["pricing"]["wage"]["cleared"])


class ProvisionalAverage(Base):
    def test_provisional_drilling_is_the_mean_of_cr13_and_cr14_only_with_independent_costs(self):
        out = self.to_wage_cleared()
        prov = out["pricing"]["provisional"]
        line = next(l for l in prov["lines"] if l["task_id"] == "L02")
        self.assertEqual({c["crew_id"] for c in line["eligible_crews"]}, {"CR13", "CR14"})
        c13, c14 = self.task("CR13", "L02")[2], self.task("CR14", "L02")[2]
        self.assertAlmostEqual(line["provisional_cost"], float(((c13 + c14) / 2).quantize(CENT, rounding=ROUND_HALF_UP)), places=2)
        self.assertNotEqual(c13, c14)
        l01 = next(l for l in prov["lines"] if l["task_id"] == "L01")           # a non-drilling task averages the four fleet crews, never legacy defaults
        self.assertEqual({c["crew_id"] for c in l01["eligible_crews"]}, set(FLEET))
        mean = sum((self.task(c, "L01")[2] for c in FLEET), Decimal(0)) / 4
        self.assertAlmostEqual(l01["provisional_cost"], float(mean), delta=0.011)
        self.assertTrue(prov["provisional"] and not prov["releasable"] and prov["complete"])
        self.assertIsNone(out["proposal_digest"])
        self.assertIsNone(out["estimate"])                    # informational only: nothing was priced, nothing can be released

    def test_with_no_qualifying_fleet_crew_the_task_has_no_cost_and_the_estimate_is_incomplete(self):
        from engine import ratebook_mode as rm
        self.to_wage_cleared()
        s = copy.deepcopy(server.PROJECTS[self.pid])
        next(t for t in s["ratebook"]["labor_tasks"] if t["task_id"] == "L02")["required_roles"] = ["R9"]      # a role no crew has
        s["crew_comparison"] = rm.crew_comparison(s)
        pl = svc.provisional_labor(s)["BASE"]
        l02 = next(l for l in pl["lines"] if l["task_id"] == "L02")
        self.assertEqual((l02["provisional_cost"], l02["eligible_crews"]), (None, []))
        self.assertIsNone(pl["provisional_labor_cost"])
        self.assertFalse(pl["complete"])
        self.assertFalse(pl["releasable"])
        v = integration.provisional_view(s)
        self.assertFalse(v["complete"])
        self.assertIsNone(v["provisional_labor_cost"])


class CrewSelection(Base):
    def test_crews_11_and_12_are_ineligible_for_core_drilling_with_the_backend_reason_and_crews_13_14_are_eligible(self):
        out = self.to_wage_cleared()
        t = next(t for t in out["pricing"]["crew_comparison"]["BASE"]["tasks"] if t["task_id"] == "L02")
        self.assertEqual([c["crew_id"] for c in t["candidates"]], FLEET)                 # all four fleet crews shown, legacy defaults hidden
        by = {c["crew_id"]: c for c in t["candidates"]}
        for cid in ("CR11", "CR12"):
            self.assertFalse(by[cid]["eligible"])
            self.assertEqual(by[cid]["reason_details"][0]["code"], "MISSING_REQUIRED_ROLE")
            self.assertEqual(by[cid]["reasons_display"], [f"{cid} has no Equipment operator (R4), which this task requires"])
        for cid in ("CR13", "CR14"):
            self.assertTrue(by[cid]["eligible"] and by[cid]["calculable"])
        other = next(t for t in out["pricing"]["crew_comparison"]["BASE"]["tasks"] if t["task_id"] == "L01")
        self.assertTrue(all(c["eligible"] for c in other["candidates"]))

    def test_forged_assignments_of_crew_11_or_12_to_drilling_are_rejected_by_the_backend(self):
        self.to_wage_cleared()
        before = self.get()
        for bad in ("CR11", "CR12"):
            forged = self.post("decisions/crew-plan", {**WHO, **plan("CR13", {"L02": bad})}, expect=409)
            self.assertIn("lacks required role", forged["error"])
            pv = self.post("crew-plan/preview", plan("CR13", {"L02": bad}))
            self.assertFalse(pv["valid"])
            self.assertIsNone(pv["estimate"])
            self.assertTrue(any(p["code"] == "CREW_UNSUITABLE" for p in pv["problems"]))
            # a preferred crew that cannot drill is refused too when drilling is left to the preference
            self.post("decisions/crew-plan", {**WHO, "preferred_crew": bad, "assignments": {}, "use_default_for_unassigned": False,
                                              "difficulty": {"default": "standard"}}, expect=409)
        after = self.get()
        self.assertEqual((after["audit"], after["pricing"]["crew_plan"]), (before["audit"], None))

    def test_preview_is_read_only_and_matches_the_real_repricing(self):
        self.to_wage_cleared()
        before = copy.deepcopy(server.PROJECTS[self.pid])
        pv = self.post("crew-plan/preview", plan("CR14"))
        self.assertTrue(pv["valid"] and pv["draft"])
        self.assertEqual(server.PROJECTS[self.pid], before)                              # identical engine state: no decision, audit or approval
        real = self.post("decisions/crew-plan", {**WHO, **plan("CR14")})
        est = real["estimate"]["scenarios"]["BASE"]
        self.assertEqual(pv["estimate"]["price_total"], real["estimate"]["price_total"])
        self.assertEqual(pv["estimate"]["labor_subtotal"], est["labor"]["subtotal"])
        self.assertEqual(pv["estimate"]["crew_days"], est["labor"]["crew_days"])
        self.assertEqual(pv["economics"], real["pricing"]["economics"])

    def test_cr13_versus_cr14_for_drilling_differs_in_hours_and_labor_economics_and_is_recomputed(self):
        self.to_wage_cleared()
        res = {}
        for crew in ("CR13", "CR14"):
            pv = self.post("crew-plan/preview", plan("CR12", {"L02": crew}))              # same plan except who drills
            self.assertTrue(pv["valid"], pv["problems"])
            line = next(t for t in pv["comparison"]["BASE"]["tasks"] if t["task_id"] == "L02")
            sel = [c for c in line["candidates"] if c["selected"]]
            self.assertEqual([c["crew_id"] for c in sel], [crew])
            h, w, cost = self.task(crew, "L02")
            self.assertAlmostEqual(sel[0]["crew_hours"], float(h), places=4)
            self.assertAlmostEqual(sel[0]["worker_hours"], float(w), places=4)
            self.assertEqual(E(sel[0]["labor_cost"]), cost)
            res[crew] = (pv, sel[0], h, w, cost)
        a, b = res["CR13"], res["CR14"]
        self.assertNotEqual(a[2], b[2])                                                   # crew-hours differ (efficiency, production rate)
        self.assertNotEqual(a[3], b[3])                                                   # worker-hours differ (3 vs 4 workers, different hours)
        self.assertNotEqual(a[4], b[4])                                                   # drilling labor cost differs
        for key in ("labor_subtotal", "price_total", "direct_cost", "crew_hours", "worker_hours"):
            self.assertNotEqual(a[0]["estimate"][key], b[0]["estimate"][key], key)
        for key in ("gross_profit", "net_profit"):
            self.assertNotEqual(a[0]["economics"][key], b[0]["economics"][key], key)
        for crew, (pv, *_rest) in res.items():                                            # total hours/cost recomputed over all ten tasks
            asg = {t["task_id"]: ("CR12" if t["task_id"] != "L02" else crew) for t in self.book["labor_tasks"]}
            h, w, c = self.labor_total(asg)
            self.assertAlmostEqual(pv["estimate"]["crew_hours"], float(h), places=3)
            self.assertAlmostEqual(pv["estimate"]["worker_hours"], float(w), places=3)
            self.assertAlmostEqual(pv["estimate"]["crew_days"], float(h / 8), places=3)
            self.assertEqual(E(pv["estimate"]["labor_subtotal"]), c)
        again = self.post("crew-plan/preview", plan("CR12", {"L02": "CR13"}))
        self.assertEqual(again["estimate"], res["CR13"][0]["estimate"])

    def test_mixed_crews_by_task_reprice_correctly_and_difficulty_changes_hours_only(self):
        self.to_wage_cleared()
        crews = ["CR11", "CR12", "CR13", "CR14"]
        asg = {t["task_id"]: crews[i % 4] for i, t in enumerate(self.book["labor_tasks"])}
        asg["L02"] = "CR14"
        pv = self.post("crew-plan/preview", plan(None, asg))
        self.assertTrue(pv["valid"], pv["problems"])
        h, w, c = self.labor_total(asg)
        self.assertEqual(E(pv["estimate"]["labor_subtotal"]), c)
        self.assertAlmostEqual(pv["estimate"]["crew_hours"], float(h), places=3)
        self.assertAlmostEqual(pv["estimate"]["worker_hours"], float(w), places=3)
        hard = self.post("crew-plan/preview", plan(None, asg, over={"D12": "hard"}))
        self.assertGreater(hard["estimate"]["crew_hours"], pv["estimate"]["crew_hours"])
        l01 = next(t for t in hard["comparison"]["BASE"]["tasks"] if t["task_id"] == "L01")
        self.assertEqual(l01["difficulty_level"], "hard")

    def test_changing_an_approved_plan_invalidates_the_prior_digest_and_versions_never_repeat(self):
        self.to_wage_cleared()
        cur = self.post("decisions/crew-plan", {**WHO, **plan("CR13")})
        digests, versions = [cur["proposal_digest"]], [cur["pricing"]["crew_plan"]["plan_version"]]
        self.assertEqual(cur["status"], "ready_for_final_review")
        for label, body in (("selected crew", plan("CR13", {"L01": "CR14"})), ("task difficulty", plan("CR13", over={"D12": "hard"})),
                            ("job difficulty", plan("CR13", diff="easy")), ("preferred crew", plan("CR14"))):
            changed = self.post("decisions/crew-plan", {**WHO, **body})
            d = changed["proposal_digest"]
            self.assertNotIn(d, digests, label)
            for old in digests:                                                          # EVERY earlier digest is dead
                code, _ = self.call("POST", f"/projects/{self.pid}/release", {"approver": "Test Approver", "expected_scope_version": changed["scope_version"], "expected_proposal_digest": old})
                self.assertEqual(code, 409, label)
            self.assertEqual(self.get()["status"], "ready_for_final_review")
            digests.append(d)
            versions.append(changed["pricing"]["crew_plan"]["plan_version"])
        self.assertEqual(versions, sorted(set(versions)))                                # strictly increasing, never repeated
        hist = self.get()["pricing"]["plan_history"]
        self.assertEqual([h["plan_version"] for h in hist], versions)
        self.assertTrue(all(h.get("retired_reason") for h in hist[:-1]) and not hist[-1].get("retired_reason"))
        code, out = self.call("POST", f"/projects/{self.pid}/release", {"approver": "Test Approver", "expected_scope_version": changed["scope_version"], "expected_proposal_digest": digests[-1]})
        self.assertEqual((code, out["status"]), (200, "released"))
        self.post("decisions/crew-plan", {**WHO, **plan("CR13")}, expect=409)             # no change after release

    def test_a_new_wage_modification_re_derives_and_re_digests(self):
        self.to_wage_cleared()
        ready = self.post("decisions/crew-plan", {**WHO, **plan("CR13")})
        higher = wage_args()
        higher["determination"]["modification"] = "1"
        higher["rows"][3]["base_rate"] = 30.5
        higher["schedule"][1]["base_rate"] = 30.5
        out = self.post("decisions/wage-determination", higher)
        self.assertNotEqual(out["proposal_digest"], ready["proposal_digest"])
        self.post("scope/resolve", {"exception_id": G3, "value": 11.0, **WHO}, expect=409)


class EngineLevelInvalidation(unittest.TestCase):
    """Rate-book, production-rate and crew-profile changes (not exposed over HTTP) void the plan, the digest and never reuse a plan version.
    Uses the test-only workbook builder with its own crew ids; this checks the engine rule, not the reference book's content."""
    @staticmethod
    def spec_module():
        import importlib.util, pathlib
        p = pathlib.Path(__file__).resolve().parent.parent / "legacy_fixtures/build_legacy_testbook.py"
        m = importlib.util.spec_from_file_location("build_demo_ratebook", p)
        mod = importlib.util.module_from_spec(m)
        m.loader.exec_module(mod)
        return mod

    def book(self, version="1.0.0", mutate=None):
        import datetime
        from pricing import ratebook as pr
        from tests import xlsx_builder as xb
        spec = self.spec_module().spec()
        for r in spec["Meta"]["rows"]:
            if r["key"] == "version":
                r["value"] = version
        if mutate:
            mutate(spec)
        return pr.import_workbook(xb.build(spec), as_of=datetime.date.today())["ratebook"]

    def priced(self):
        from tests.test_ratebook_workflow import approve_rules
        s = wf.start(json.load(open(integration.SCOPE_PATH)), None, ratebook=self.book(), policy=integration.POLICY)
        wf.resolve(s, G3, value=10.0, by="Lee", note="assumed")
        approve_rules(s)
        svc.record_wage_decision(s, **wage_args())
        svc.adopt_crew_plan(s, by="Lee", note="plan", preferred_crew="CR2", assignments={"L02": "CR3"}, use_default_for_unassigned=True, difficulty={"default": "standard"})
        return s

    def test_changed_production_rate_voids_the_plan_and_the_old_digest_and_the_next_version_is_higher(self):
        s = self.priced()
        d1, v1 = s["proposal_digest"], s["crew_plan"]["plan_version"]
        def faster(spec):
            next(o for o in spec["Crew_Production"]["rows"] if o["task_id"] == "L01" and o["crew_id"] == "CR3")["production_rate"] = 20.0
        wf.attach_ratebook(s, self.book("1.1.0", faster), by="Lee", note="updated production rate")
        self.assertIsNone(s["crew_plan"])
        self.assertIsNone(s["estimate"])
        self.assertIsNone(s["proposal_digest"])
        self.assertFalse(svc.digest_is_current(s, d1)["current"])
        self.assertEqual([p["plan_version"] for p in svc.crew_plan_history(s)], [v1])
        self.assertTrue(svc.crew_plan_history(s)[0]["retired_reason"])
        with self.assertRaises(wf.GateError):
            wf.release(s, "Test Approver", s["scope"]["scope_version"], d1)
        svc.adopt_crew_plan(s, by="Lee", note="re-plan", preferred_crew="CR2", assignments={"L02": "CR3"}, use_default_for_unassigned=True, difficulty={"default": "standard"})
        self.assertGreater(s["crew_plan"]["plan_version"], v1)
        self.assertEqual([p["plan_version"] for p in svc.crew_plan_history(s)], sorted({v1, s["crew_plan"]["plan_version"]}))

    def test_changed_crew_profile_voids_the_plan(self):
        s = self.priced()
        def slower(spec):
            next(c for c in spec["Crews"]["rows"] if c["crew_id"] == "CR3")["efficiency_pct"] = 80
        wf.attach_ratebook(s, self.book("1.1.0", slower), by="Lee", note="profile update")
        self.assertIsNone(s["crew_plan"])
        self.assertIsNone(s["proposal_digest"])

    def test_estimate_view_and_economics_foot_to_the_engine_estimate(self):
        s = self.priced()
        v = integration.view(s)
        ev, econ = v["estimate_view"], v["economics"]
        amounts = {b["key"]: E(b["amount"]) for b in ev["breakdown"]}
        self.assertEqual(amounts["price_total"], E(s["estimate"]["price_total"]))
        self.assertEqual(amounts["direct_cost"], sum((amounts[k] for k in ("materials", "services", "labor", "certified_payroll", "equipment", "mobilization", "sales_tax")), Decimal(0)))
        self.assertEqual(E(econ["gross_profit"]), amounts["price_total"] - amounts["direct_cost"])
        self.assertEqual(E(econ["net_profit"]), amounts["profit"])
        self.assertEqual(ev["labor_totals"]["crew_days"], s["estimate"]["scenarios"]["BASE"]["labor"]["crew_days"])


if __name__ == "__main__":
    unittest.main()

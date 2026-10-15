"""Backend fleet enforcement at the HTTP decision boundary. Fleet membership (engine fleet metadata) and task qualification (engine rule) are
validated separately; no crew id is hard-coded where the engine's fleet_overview can answer."""
import json
import unittest

from engine import integration, pricing_service as svc
from pricing import crews as pcrews
from tests.http_harness import HttpBase, WHO, plan
from tests.test_ratebook_workflow import wage_args


class Fleet(HttpBase):
    def setUp(self):
        super().setUp()
        self.fleet = svc.fleet_overview(self.book)["crews"]
        self.fleet_ids = {c["crew_id"] for c in self.fleet}
        self.non_fleet = sorted(set(pcrews.used_crews(self.book)) - self.fleet_ids)     # derived from engine metadata, not typed in

    def refused(self, body, code, status=409, route="decisions/crew-plan"):
        before, muts = self.frozen(), self.mutations()
        c, out = self.call("POST", f"/projects/{self.pid}/{route}", body)
        self.assertEqual((c, out.get("code")), (status, code), out)
        after = json.loads(self.frozen()), json.loads(before)
        self.assertEqual(after[0]["audit"], after[1]["audit"])                      # no audit record
        self.assertEqual(after[0]["adapter"]["decisions"], after[1]["adapter"]["decisions"])
        self.assertIsNone(self.get()["pricing"]["crew_plan"])
        self.assertIsNone(self.get()["estimate"])
        return out

    def test_the_book_has_non_fleet_legacy_crews_to_attack_with(self):
        self.assertTrue(self.non_fleet, "test premise: legacy default crews exist")
        self.assertEqual(len(self.fleet_ids), 4)

    def test_every_non_fleet_crew_is_rejected_as_preferred_and_as_an_assignment(self):
        self.to_wage_cleared()
        for crew in self.non_fleet:
            out = self.refused({**WHO, **plan(pref=crew)}, "CREW_NOT_IN_FLEET")
            self.assertIn(crew, json.dumps(out["details"]))
            self.refused({**WHO, **plan(assign={"L02": crew})}, "CREW_NOT_IN_FLEET")

    def test_legacy_default_crew_that_has_an_operator_is_still_rejected_for_drilling(self):
        self.to_wage_cleared()
        drill = svc.task_eligibility(self.book, "L02")["crews"]
        legacy_operator_crews = [c["crew_id"] for c in drill if c["eligible"] and c["crew_id"] not in self.fleet_ids]
        self.assertTrue(legacy_operator_crews, "premise: a legacy crew (CR1) is task-eligible but not in the fleet")
        for crew in legacy_operator_crews:
            self.refused({**WHO, **plan(assign={"L02": crew})}, "CREW_NOT_IN_FLEET")     # fleet and qualification are independent checks

    def test_fleet_crews_without_the_operator_are_rejected_for_the_missing_role(self):
        self.to_wage_cleared()
        elig = {c["crew_id"]: c for c in svc.task_eligibility(self.book, "L02")["crews"]}
        ineligible = [c for c in self.fleet_ids if not elig[c]["eligible"]]
        self.assertEqual(len(ineligible), 2)
        for crew in sorted(ineligible):
            out = self.refused({**WHO, **plan(assign={"L02": crew})}, "ENGINE_REFUSED")
            self.assertIn("CREW_UNSUITABLE", out["engine_codes"])
            self.assertIn("R4", out["error"])                                                 # the missing operator role
        for crew in sorted(ineligible):                                                       # preferred crew cannot dodge the drilling rule either
            self.refused({**WHO, **plan(pref=crew, assign={"L02": crew})}, "ENGINE_REFUSED")

    def test_eligible_fleet_crews_are_accepted_once_wage_and_approvals_are_in_place(self):
        self.to_wage_cleared()
        elig = {c["crew_id"] for c in svc.task_eligibility(self.book, "L02")["crews"] if c["eligible"]} & self.fleet_ids
        self.assertEqual(len(elig), 2)
        for i, crew in enumerate(sorted(elig)):
            out = self.post("decisions/crew-plan", {**WHO, **plan(pref=crew, assign={"L02": crew}, diff=("standard", "hard")[i])})
            self.assertEqual(out["pricing"]["crew_plan"]["assignments"]["L02"], crew)
            lines = out["pricing"]["estimate_view"]["labor_lines"]
            self.assertTrue({l["crew_id"] for l in lines} <= self.fleet_ids)                  # no leakage of a legacy crew into the priced lines
            self.assertEqual(next(l for l in lines if l["task_id"] == "L02")["crew_id"], crew)

    def test_nothing_is_priced_for_any_crew_before_the_wage_determination_is_recorded(self):
        self.to_labor_gate()                                                                   # ruleset approved, wage determination NOT yet recorded
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan(assign={"L02": "CR13"})})
        # the engine may accept the plan but must not price: no estimate without the wage determination
        self.assertIsNone(self.get()["estimate"])

    def test_default_fallback_cannot_smuggle_legacy_crews_in(self):
        self.to_wage_cleared()
        body = {**WHO, **plan(pref=None, assign={"L02": "CR13"}, use_default=True)}            # tasks without a selection would fall back to default crews
        out = self.refused(body, "CREW_NOT_IN_FLEET")
        self.assertTrue(any(d["crew_id"] in self.non_fleet for d in out["details"]), out)

    def test_preview_applies_the_same_fleet_rule_and_stays_non_mutating(self):
        self.to_wage_cleared()
        before, muts = self.frozen(), self.mutations()
        crew = self.non_fleet[0]
        c, out = self.call("POST", f"/projects/{self.pid}/crew-plan/preview", plan(assign={"L02": crew}))
        self.assertEqual(c, 200)
        self.assertFalse(out["valid"])
        self.assertIn("CREW_NOT_IN_FLEET", {p["code"] for p in out["problems"]})
        self.assertIsNone(out["estimate"])
        c, out = self.call("POST", f"/projects/{self.pid}/crew-plan/preview", plan(pref=None, assign={"L02": "CR13"}, use_default=True))
        self.assertIn("CREW_NOT_IN_FLEET", {p["code"] for p in out["problems"]})
        self.assertEqual((self.frozen(), self.mutations()), (before, muts))

    def test_malformed_assignments_do_not_get_past_the_fleet_check_or_mutate(self):
        self.to_wage_cleared()
        before = self.frozen()
        for asg in ({"L02": ["CR13"]}, {"L02": {"x": 1}}, {f"L{i:02d}": "CR13" for i in range(1, 30)}):
            c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan(assign=asg)})
            self.assertIn(c, (400, 409), (asg, out))
        after = json.loads(self.frozen()); b = json.loads(before)
        self.assertEqual((after["audit"], after["pricing"]["crew_plan"]), (b["audit"], b["pricing"]["crew_plan"]))

    def test_summary_roster_is_exactly_the_engine_fleet(self):
        s = self.get()
        self.assertEqual({c["crew_id"] for c in s["crews"]["crews"]}, self.fleet_ids)
        self.assertEqual(s["crews"]["fleet_average_pct"], 95.8)


if __name__ == "__main__":
    unittest.main()

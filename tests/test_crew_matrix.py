"""Crew matrix read API: fleet and eligibility as the engine defines them today (no rule changed), with hourly components, hours and task cost."""
import json
import unittest

from engine import crew_matrix
from pricing import crews
from tests import footing_helpers as H
from tests.http_harness import HttpBase


class Matrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = H.priced()
        cls.m = crew_matrix.build(cls.st)

    def test_fleet_is_the_crew_production_alternatives_and_cr1_to_cr4_are_legacy_defaults(self):
        fleet = {c["crew_id"] for c in self.m["crews"] if c["in_fleet"]}
        self.assertEqual(fleet, set(crews.fleet_crew_ids(self.st["ratebook"])))
        self.assertEqual(fleet, {"CR11", "CR12", "CR13", "CR14"})
        legacy = {c["crew_id"]: c["fleet_reason"] for c in self.m["crews"] if not c["in_fleet"]}
        self.assertEqual(set(legacy), {"CR1", "CR2", "CR3", "CR4"})
        self.assertTrue(all("legacy per-task default crew" in r for r in legacy.values()))
        self.assertTrue(all("Crew_Production" in c["fleet_reason"] for c in self.m["crews"] if c["in_fleet"]))
        self.assertIn("CREW_NOT_IN_FLEET", self.m["definitions"]["fleet"])

    def test_eligibility_is_per_task_by_required_role_and_has_a_reason(self):
        l02 = next(t for t in self.m["scenarios"]["BASE"]["tasks"] if t["task_id"] == "L02")
        self.assertEqual(l02["required_roles"], ["R4"])
        by = {c["crew_id"]: c for c in l02["crews"]}
        for cid in ("CR11", "CR12"):                                              # no equipment operator (R4)
            self.assertFalse(by[cid]["eligible"])
            self.assertEqual([r["code"] for r in by[cid]["eligibility_reasons"]], ["MISSING_REQUIRED_ROLE"])
            self.assertFalse(by[cid]["calculable"])
        for cid in ("CR1", "CR13", "CR14"):
            self.assertTrue(by[cid]["eligible"] and by[cid]["calculable"], cid)
        self.assertEqual(by["CR1"]["in_fleet"], False)                           # eligible for the task, but not a fleet crew
        l01 = next(t for t in self.m["scenarios"]["BASE"]["tasks"] if t["task_id"] == "L01")
        self.assertTrue(all(c["eligible"] for c in l01["crews"]))                # L01 requires no role

    def test_every_task_and_crew_carries_rate_hours_cost_and_components(self):
        for sref, s in self.m["scenarios"].items():
            self.assertEqual([t["task_id"] for t in s["tasks"]], [f"L{i:02d}" for i in range(1, 11)])
            for t in s["tasks"]:
                for c in t["crews"]:
                    self.assertIn("production_rate", c)
                    if c["calculable"]:
                        self.assertGreater(c["crew_hours"], 0)
                        tc = c["task_cost"]
                        self.assertAlmostEqual(tc["total"], round(c["crew_hours"] * c["hourly"]["loaded_per_hr"], 2), delta=0.02)
                        self.assertLessEqual(abs(tc["wages"] + tc["fringe"] + tc["employer_cost"] - tc["total"]), 0.02)       # components are supporting detail
        h = next(c for c in self.m["crews"] if c["crew_id"] == "CR13")["hourly"]
        self.assertAlmostEqual(h["wages_per_hr"] + h["fringe_per_hr"] + h["employer_cost_per_hr"], h["loaded_per_hr"], places=2)
        self.assertEqual([m["role_key"] for m in next(c for c in self.m["crews"] if c["crew_id"] == "CR13")["members"]], ["R2", "R4"])

    def test_the_matrix_matches_the_priced_labor_lines_for_the_selected_crews(self):
        for sref, e in self.st["estimate"]["scenarios"].items():
            tasks = {t["task_id"]: t for t in self.m["scenarios"][sref]["tasks"]}
            for l in e["labor"]["lines"]:
                sel = next(c for c in tasks[l["task_id"]]["crews"] if c["selected"])
                self.assertEqual((sel["crew_id"], sel["task_cost"]["total"], sel["crew_hours"]), (l["crew_id"], l["extended"], l["crew_hours"]), (sref, l["task_id"]))

    def test_no_forbidden_keys(self):
        keys = set()
        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    keys.add(k); walk(v)
            elif isinstance(o, list):
                for v in o: walk(v)
        walk(self.m)
        self.assertFalse(keys & {"base_wage_per_hr", "burden_pct", "loaded_rate_per_hr", "role_wages", "labor_tasks", "crew_options"})
        json.dumps(self.m)

    def test_company_rate_path_shows_only_the_loaded_hourly_figure(self):
        from unittest import mock
        with mock.patch("engine.ratebook_mode.wage_required", return_value=False):
            m = crew_matrix.build(self.st)
        self.assertFalse(m["components_disclosed"])
        for c in m["crews"]:
            self.assertEqual(c["members"], [])
            self.assertTrue(all(c["hourly"][k] is None for k in ("wages_per_hr", "fringe_per_hr", "employer_cost_per_hr")))
            self.assertIsNotNone(c["hourly"]["loaded_per_hr"])
        task = m["scenarios"]["BASE"]["tasks"][0]
        self.assertTrue(all("wages" not in c["task_cost"] for c in task["crews"] if c["calculable"]))

    def test_not_priced_gives_none(self):
        self.assertIsNone(crew_matrix.build(H.start(H.fixture())))


class MatrixRoute(HttpBase):
    def test_route_answers_for_a_project_without_quantities(self):
        c, out = self.call("GET", f"/projects/{self.pid}/crew-matrix")
        self.assertEqual(c, 200)
        self.assertIn("definitions", out) if out.get("scenarios") is not None and out.get("definitions") else self.assertFalse(out.get("available", True))


if __name__ == "__main__":
    unittest.main()

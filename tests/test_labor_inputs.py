"""The labor/payroll inputs dump: data only, no totals, and it proves the engine's labor lines follow from the inputs it lists."""
import json
import unittest

from engine import labor_inputs
from tests import footing_helpers as H


def keys(o, acc):
    if isinstance(o, dict):
        for k, v in o.items():
            acc.add(k)
            keys(v, acc)
    elif isinstance(o, list):
        for v in o:
            keys(v, acc)
    return acc


class LaborInputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = H.priced()
        cls.d = labor_inputs.dump(cls.st)

    def test_no_totals_or_line_amounts(self):
        k = keys(self.d, set())
        for forbidden in ("extended", "price_total", "subtotal", "direct_cost", "labor_cost", "total", "cost_per_unit"):
            self.assertNotIn(forbidden, k)

    def test_every_role_has_classification_rates_and_loaded_rate_and_the_workbook_values_are_marked_unused(self):
        self.assertEqual([r["role_key"] for r in self.d["roles"]], ["R1", "R2", "R3", "R4"])
        for r in self.d["roles"]:
            self.assertTrue(r["classification"] and r["source_ref"])
            self.assertAlmostEqual(r["loaded_rate_per_hr"], r["base_rate_per_hr"] + r["fringe_rate_per_hr"] + r["employer_cost_per_hr"], places=2)
            self.assertAlmostEqual(r["employer_cost_per_hr"], r["base_rate_per_hr"] * self.d["employer_burden"]["pct"], places=2)     # burden on wages only
            self.assertIn("NOT_USED_workbook_company_burden_pct", r)

    def test_engine_labor_lines_follow_from_the_published_inputs(self):
        for sref, s in self.d["scenarios"].items():
            self.assertEqual(len(s["tasks"]), 10)
            for t in s["tasks"]:
                self.assertTrue(all(t["reproduces"].values()), (sref, t["task_id"], t["reproduces"]))
                self.assertEqual(t["crew_size"], sum(t["crew_members"].values()))
                self.assertIn("task_default_crew_id", t)

    def test_payroll_admin_burden_and_crew_plan_are_listed_with_their_source(self):
        self.assertEqual(set(self.d["certified_payroll_admin"]) , {"basis", "unit_cost", "weeks", "reason", "source_ref"})
        self.assertTrue(self.d["employer_burden"]["source_ref"] and self.d["certified_payroll_admin"]["source_ref"])
        self.assertTrue(self.d["crew_plan"]["preferred_crew"])
        json.dumps(self.d)                                              # plain data

    def test_refuses_a_project_that_is_not_priced(self):
        with self.assertRaises(ValueError):
            labor_inputs.dump(H.start(H.fixture()))


if __name__ == "__main__":
    unittest.main()

"""The additive read-only per-role wage classification field on the pricing view."""
import unittest

from engine import integration
from tests import footing_helpers as H


class RoleClassifications(unittest.TestCase):
    def test_before_any_wage_record_every_role_shows_nulls_never_a_default(self):
        w = integration.view(H.start(H.fixture()))["wage"]
        rc = w["role_classifications"]
        self.assertEqual([r["role_key"] for r in rc], ["R1", "R2", "R3", "R4"])
        for r in rc:
            self.assertEqual((r["classification"], r["base_rate"], r["fringe_rate"], r["priced"], r["cleared"]), (None, None, None, None, False))
        self.assertIsNone(w["employer_burden"])

    def test_recorded_rows_and_priced_figures_are_exposed_and_loaded_is_at_least_base_plus_fringe(self):
        w = integration.view(H.priced())["wage"]
        for r in w["role_classifications"]:
            if not r["cleared"]:
                continue
            p = r["priced"]
            self.assertGreaterEqual(p["wages"], r["base_rate"])
            self.assertGreaterEqual(p["fringe"], r["fringe_rate"])
            self.assertGreaterEqual(p["loaded"], round(r["base_rate"] + r["fringe_rate"], 2))
            self.assertTrue(r["classification"] and r["source_ref"])
        self.assertEqual(w["employer_burden"]["pct"], 0.2)

    def test_a_role_with_a_problem_is_not_cleared_and_names_its_codes(self):
        st = H.priced()
        wd = st["wage_determination"]
        from engine import workflow as wf
        rows = [dict(r) for r in wd["rows"]]
        rows[0]["classification"] = None
        wf.record_wage_determination(st, by=H.WHO, note="drop a classification", determination=wd["determination"], schedule=wd["schedule"], rows=rows,
                                     employer_burden=wd["employer_burden"], production_rates_approved=True, certified_payroll_admin=wd["certified_payroll_admin"])
        r0 = integration.view(st)["wage"]["role_classifications"][0]
        self.assertEqual((r0["cleared"], r0["priced"], "WAGE_ROLE_UNCLASSIFIED" in r0["problems"]), (False, None, True))


if __name__ == "__main__":
    unittest.main()

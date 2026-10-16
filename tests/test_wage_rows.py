"""Owner rule 2026-10-16: wage = workbook role rate if >= the Attachment A floor, else the floor, flagged; 35% burden from the workbook."""
import copy
import unittest

from engine import assumptions, integration, wage_rows, workflow as wf
from tests import footing_helpers as H
from tests.test_ratebook_workflow import SCHEDULE

MAP = {"R1": "Laborer, common or general", "R2": "Laborer, common or general", "R3": "Laborer, common or general", "R4": "Power equipment operator, skid steer"}


class WageRows(unittest.TestCase):
    def test_workbook_rate_when_at_or_above_the_floor_else_the_floor_flagged(self):
        rows = {r["role_key"]: r for r in wage_rows.rows_from_workbook(H.book(), SCHEDULE, MAP, "FDB-DP001 mod 0 Att. A")}
        self.assertEqual((rows["R1"]["base_rate"], rows["R1"]["floor_adjustment"]), (32, None))            # workbook 32.00 >= 24.50
        self.assertEqual((rows["R2"]["base_rate"], rows["R2"]["floor_adjustment"]), (26, None))            # workbook 26.00 >= 24.50
        self.assertEqual(rows["R3"]["base_rate"], 24.5)                                                     # workbook 20.00 < 24.50: the floor
        self.assertIn("workbook rate 20 is below the Attachment A floor 24.5", rows["R3"]["floor_adjustment"])
        self.assertEqual(rows["R4"]["base_rate"], 29.8)                                                     # workbook 28.00 < 29.80: the floor
        self.assertEqual([rows[k]["fringe_rate"] for k in ("R1", "R2", "R3", "R4")], [9.1, 9.1, 9.1, 11.25])  # the schedule's fringe
        self.assertEqual([rows[k]["workbook_rate_per_hr"] for k in ("R1", "R2", "R3", "R4")], [32, 26, 20, 28])

    def test_a_rate_exactly_at_the_floor_is_not_flagged(self):
        b = H.book()
        b["roles"][2]["base_wage_per_hr"] = 24.5
        self.assertIsNone({r["role_key"]: r for r in wage_rows.rows_from_workbook(b, SCHEDULE, MAP, "x")}["R3"]["floor_adjustment"])

    def test_burden_comes_from_the_workbook_and_mixed_burdens_are_refused_not_averaged(self):
        self.assertEqual(wage_rows.burden_pct(H.book()), 0.35)
        b = H.book()
        b["roles"][0]["burden_pct"] = 0.30
        with self.assertRaises(ValueError):
            wage_rows.burden_pct(b)

    def test_an_unlisted_classification_is_refused(self):
        with self.assertRaises(ValueError):
            wage_rows.rows_from_workbook(H.book(), SCHEDULE, {"R1": "Fence erector"}, "x")

    def test_recorded_flags_reach_the_view_and_the_export_lines_and_pricing_uses_the_priced_rate(self):
        st = H.priced()
        wd = st["wage_determination"]
        rows = wage_rows.rows_from_workbook(st["ratebook"], wd["schedule"], MAP, "FDB-DP001 mod 0 Att. A")
        wf.record_wage_determination(st, by=H.WHO, note="test", determination=wd["determination"], schedule=wd["schedule"], rows=rows,
                                     employer_burden={"pct": wage_rows.burden_pct(st["ratebook"]), "source_ref": "pinned workbook Roles burden_pct"},
                                     production_rates_approved=True, certified_payroll_admin={"basis": "not_charged", "reason": "no such line in the workbook", "source_ref": "workbook"})
        self.assertEqual(st["status"], wf.READY)
        rc = {r["role_key"]: r for r in integration.view(st)["wage"]["role_classifications"]}
        self.assertEqual([(rc[k]["raised_to_floor"], rc[k]["above_decision"]) for k in ("R1", "R2", "R3", "R4")], [(False, True), (False, True), (True, False), (True, False)])
        self.assertEqual((rc["R3"]["priced"]["wages"], rc["R4"]["priced"]["wages"], rc["R1"]["priced"]["wages"]), (24.5, 29.8, 32.0))
        quals = integration.view(st)["estimate_view"]["qualifications"]
        self.assertTrue(any(q.startswith("Wage flag (R3)") for q in quals))
        self.assertTrue(any(q.startswith("Wage flag (R4)") for q in quals))
        self.assertFalse(any(q.startswith("Wage flag (R1)") for q in quals))


if __name__ == "__main__":
    unittest.main()


class ExportStatements(unittest.TestCase):
    def setUp(self):
        st = H.priced()
        wd = st["wage_determination"]
        rows = wage_rows.rows_from_workbook(st["ratebook"], wd["schedule"], MAP, "FDB-DP001 mod 0 Att. A")
        wf.record_wage_determination(st, by=H.WHO, note="test", determination=wd["determination"], schedule=wd["schedule"], rows=rows,
                                     employer_burden={"pct": 0.35, "source_ref": "pinned workbook Roles burden_pct"}, production_rates_approved=True,
                                     certified_payroll_admin={"basis": "not_charged", "reason": "the pinned workbook carries no such line", "source_ref": "workbook"})
        self.st = st

    def test_export_states_certified_payroll_is_zero_because_the_workbook_has_no_such_line(self):
        quals = integration.view(self.st)["estimate_view"]["qualifications"]
        self.assertIn("Certified-payroll administration: $0.00; the pinned workbook carries no such line.", quals)
        self.assertEqual(self.st["estimate"]["scenarios"]["BASE"]["labor"]["certified_payroll_admin"]["extended"], 0)

    def test_export_prints_the_confirmed_classification_mapping_and_flags_a_mismatch(self):
        quals = integration.view(self.st)["estimate_view"]["qualifications"]
        self.assertTrue(any(q.startswith("Wage classifications (confirmed by Jordan)") and "Power equipment operator, skid steer" in q and "WARNING" not in q for q in quals))
        st = copy.deepcopy(self.st)
        st["wage_determination"]["rows"][0]["classification"] = "Cement mason, concrete finisher"
        a = {i["id"]: i for i in assumptions.build(st)["items"]}
        self.assertEqual(a["ASM-WAGE-CLASSIFICATION-MAPPING"]["status"], "OWNER_DECISION_NOT_MATCHED")
        self.assertIn("WARNING", a["ASM-WAGE-CLASSIFICATION-MAPPING"]["export_line"])

    def test_a_charged_payroll_basis_does_not_print_the_zero_statement(self):
        a = {i["id"]: i for i in assumptions.build(H.priced())["items"]}          # the shared test project charges per week
        self.assertNotIn("ASM-CERTIFIED-PAYROLL-ZERO", a)

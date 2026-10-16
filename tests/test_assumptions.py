"""Named assumptions on the export: nothing the engine assumes stays silent, and each claim about prior behavior is checked against the engine."""
import copy
import math
import unittest

from engine import assumptions, integration
from tests import footing_helpers as H


class Assumptions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = H.priced()
        cls.v = integration.view(cls.st)
        cls.a = {i["id"]: i for i in cls.v["assumptions"]["items"]}

    def test_the_three_owner_items_are_present_with_status_and_owner(self):
        self.assertEqual(self.a["ASM-M07-COUPLINGS"]["status"], "OWNER_DECIDED")
        self.assertEqual(self.a["ASM-O15-INSURANCE"]["status"], "OWNER_DECIDED")
        self.assertEqual(self.a["ASM-GATE-ASSEMBLY-250"]["status"], "OWNER_DECIDED")
        self.assertEqual(self.a["ASM-GATE-ASSEMBLY-250"]["value"]["rate_per_clear_opening_lf"], 250.0)
        self.assertEqual(self.a["ASM-SHARED-POST-BRACING-WHOLE"]["export_line"],
                         "Shared post and bracing lines carried whole; no gate-post share split out.")
        for i in self.a.values():
            self.assertEqual(i["owner"], "Jordan")
            self.assertTrue(i["export_line"] and i["prior_engine_behavior"])

    def test_m07_prior_behavior_claim_is_true_21ft_stick_and_a_coupling_at_each_joint(self):
        q = {i.get("item_id") or i["driver_key"]: i["quantity"] for i in self.st["quantities"]["BASE"]["items"]}
        top_a, top_b = q["M05"] - q["D02"], q["D02"]
        expected = math.ceil(top_a / 21) - 1 + math.ceil(top_b / 21) - 1 + math.ceil(q["M06"] / 21) - 1      # top A, top B, mid A: joints per rail line
        self.assertEqual(q["M07"], expected)
        self.assertEqual(self.a["ASM-M07-COUPLINGS"]["value"]["rail_stick_ft"], 21)

    def test_gate_material_override_replaces_the_old_fitted_corner_assumption(self):
        self.assertNotIn("ASM-GATE-FRAME-CORNERS", self.a)
        self.assertIn("M29", self.a["ASM-GATE-ASSEMBLY-250"]["applies_to"])
        self.assertIn("M30", self.a["ASM-GATE-ASSEMBLY-250"]["applies_to"])

    def test_o15_was_an_unused_template_row_so_it_was_ignored(self):
        b = self.st["ratebook"]
        self.assertNotIn("O15", [m["line_id"] for m in b["mobilization"]])
        self.assertIn({"sheet": "Mobilization_Other", "id": "O15"}, b["unused_template_lines"])
        self.assertEqual(self.a["ASM-O15-INSURANCE"]["line"], {"line_id": "O15", "item": "Project-specific insurance", "basis": "LS", "amount": 0.0, "note": "carried within overhead"})

    def test_export_qualifications_print_every_assumption_including_the_insurance_text(self):
        quals = self.v["estimate_view"]["qualifications"]
        self.assertIn("Project insurance per SC-11.1 carried within overhead", quals)
        for i in self.a.values():
            self.assertIn(i["export_line"], quals)
        self.assertTrue(any("$250.00 per LF" in q and "Replaces M21" in q for q in quals))

    def test_a_ruleset_that_differs_from_the_owner_decision_is_flagged_not_hidden(self):
        st = copy.deepcopy(self.st)
        st["ruleset"]["rules"]["params"]["rail_stick_ft"] = 20
        a = {i["id"]: i for i in assumptions.build(st)["items"]}
        self.assertEqual(a["ASM-M07-COUPLINGS"]["status"], "OWNER_DECISION_NOT_MATCHED")
        self.assertIn("WARNING", a["ASM-M07-COUPLINGS"]["export_line"])

    def test_the_ruleset_parameters_are_listed_with_their_draft_status(self):
        rp = self.v["assumptions"]["ruleset_parameters"]
        self.assertTrue(rp["status"].startswith("approved by "))                                           # the test project approved it
        self.assertIn("DRAFT", assumptions.build(H.start(H.fixture()))["ruleset_parameters"]["status"])   # until an estimator approves it, it says DRAFT
        self.assertEqual({p["param"]: p["value"] for p in rp["params"]}["rail_stick_ft"], 21)
        self.assertGreater(len(rp["params"]), 20)
        self.assertEqual(self.v["assumptions"]["allowances"], {"amount": 0.0, "locked": True, "note": "no allowances are carried"})

    def test_assumptions_never_change_a_price(self):
        before = copy.deepcopy(self.st["estimate"]["scenarios"]["BASE"]["price_total"])
        integration.view(self.st)
        self.assertEqual(self.st["estimate"]["scenarios"]["BASE"]["price_total"], before)

    def test_other_projects_do_not_get_the_dp001_insurance_item(self):
        st = copy.deepcopy(self.st)
        st["scope"]["project_ref"] = "OTHER"
        self.assertNotIn("ASM-O15-INSURANCE", [i["id"] for i in assumptions.build(st)["items"]])


if __name__ == "__main__":
    unittest.main()

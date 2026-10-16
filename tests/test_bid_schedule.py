"""ALLOC-V1 per-item schedule: reconciles to the engine to the cent, refuses rather than guesses, never combines scenarios."""
import copy
import unittest

from engine import bid_schedule as bs, integration
from tests import footing_helpers as H


class Arithmetic(unittest.TestCase):
    def test_remainder_rule_largest_remainder_ties_to_lowest_item(self):
        self.assertEqual(bs.spread(35000, {10: 300000, 11: 120000, 16: 30000}), {10: 23334, 11: 9333, 16: 2333})     # the contract's shared-pool example
        self.assertEqual(bs.spread(10, {1: 1, 2: 1, 3: 1}), {1: 4, 2: 3, 3: 3})
        self.assertEqual(bs.spread(0, {1: 1}), {1: 0})
        with self.assertRaises(bs.Refused):
            bs.spread(5, {1: 0, 2: 0})

    def test_contract_worked_example_to_the_cent(self):
        m = bs.split_markup({10: 300000, 11: 120000, 16: 30000}, 35000, 48500, 24250, 55775)
        self.assertEqual({i: r["shared"] for i, r in m.items()}, {10: 23334, 11: 9333, 16: 2333})
        self.assertEqual({i: r["direct"] for i, r in m.items()}, {10: 323334, 11: 129333, 16: 32333})
        self.assertEqual({i: r["overhead"] for i, r in m.items()}, {10: 32334, 11: 12933, 16: 3233})
        self.assertEqual({i: r["contingency"] for i, r in m.items()}, {10: 16167, 11: 6467, 16: 1616})
        self.assertEqual({i: r["subtotal"] for i, r in m.items()}, {10: 371835, 11: 148733, 16: 37182})
        self.assertEqual({i: r["profit"] for i, r in m.items()}, {10: 37184, 11: 14873, 16: 3718})
        self.assertEqual({i: r["amount"] for i, r in m.items()}, {10: 409019, 11: 163606, 16: 40900})
        self.assertEqual(sum(r["amount"] for r in m.values()), 613525)                                             # = the engine total
        ext = {}
        for i, qty in ((10, 100), (11, 50), (16, 20)):
            up, e = bs.printed_prices(m[i]["amount"], qty)
            ext[i] = (float(up), float(e))
        self.assertEqual(ext, {10: (40.90, 4090.0), 11: (32.72, 1636.0), 16: (20.45, 409.0)})
        self.assertEqual(round(sum(e for _, e in ext.values()) - 6135.25, 2), -0.25)                               # the printed rounding delta

    def test_half_up_unit_price(self):
        self.assertEqual(float(bs.printed_prices(1005, 1)[0]), 10.05)
        self.assertEqual(float(bs.printed_prices(100, 8)[0]), 0.13)         # 0.125 rounds up


class Schedule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = H.priced()
        cls.v = bs.view(cls.st)

    def test_each_scenario_adds_up_to_its_engine_total_within_the_disclosed_rounding(self):
        for sref in ("BASE", "ALT-A1"):
            s = self.v["scenarios"][sref]
            self.assertTrue(s["available"], s.get("reason"))
            self.assertEqual(s["engine_total"], self.st["estimate"]["scenarios"][sref]["price_total"])
            self.assertEqual(round(sum(r["allocated_amount"] for r in s["items"]), 2), s["engine_total"])          # exact before printed-price rounding
            self.assertEqual(round(sum(r["extended"] for r in s["items"]), 2), s["schedule_total"])
            self.assertEqual(s["rounding_delta"], round(s["schedule_total"] - s["engine_total"], 2))
            self.assertLessEqual(abs(s["rounding_delta"]), sum(r["quantity"] for r in s["items"]) * 0.005 + 1e-9)
            for r in s["items"]:
                self.assertEqual(r["extended"], round(r["quantity"] * r["unit_price"], 2))                        # the printed unit price governs
                self.assertEqual(r["label"], "allocated")
            self.assertIn("ALLOC-V1", s["reconciliation"])
            self.assertIsNone(s["combined_total"])

    def test_base_and_alternate_are_separate_and_never_combined(self):
        self.assertIsNone(self.v["combined_total"])
        self.assertNotEqual(self.v["scenarios"]["BASE"]["engine_total"], self.v["scenarios"]["ALT-A1"]["engine_total"])
        self.assertIn("replacement", self.v["note"])

    def test_item_16_has_material_only_and_the_top_rail_note(self):
        s = self.v["scenarios"]["BASE"]
        r16 = next(r for r in s["items"] if r["item_no"] == 16)
        self.assertEqual(r16["note"], "included in top-rail task")
        sc = self.st["estimate"]["scenarios"]["BASE"]
        m42 = next(l["extended"] for l in sc["materials"]["lines"] if l["item_id"] == "M42")
        self.assertEqual(r16["direct_attributed"], m42)                                                             # M42 only: no labor line of its own
        self.assertEqual(bs.LABOR["L04"][0], "GROSS_RUN_AB")
        self.assertNotIn(16, bs._Ctx(self.st, "BASE").basis("GROSS_RUN_AB"))

    def test_every_engine_line_has_an_attribution_rule(self):
        for sref, sc in self.st["estimate"]["scenarios"].items():
            self.assertTrue({l["item_id"] for l in sc["materials"]["lines"]} <= set(bs.MATERIALS))
            self.assertTrue({l["task_id"] for l in sc["labor"]["lines"]} <= set(bs.LABOR))

    def test_a_typed_g3_makes_the_prices_qualified(self):
        self.assertTrue(all(r["status"] == "PRICED_QUALIFIED" and r["qualifier"] == "assumed, RFI pending" for r in self.v["scenarios"]["BASE"]["items"]))

    def test_allowances_are_locked_at_zero(self):
        self.assertEqual(self.v["scenarios"]["BASE"]["allowances"], {"amount": 0.0, "locked": True, "note": "no allowances are carried"})

    def test_deterministic_and_revision_hash_changes_with_the_scope(self):
        again = bs.view(copy.deepcopy(self.st))
        self.assertEqual(again["scenarios"]["BASE"]["bid_revision"], self.v["scenarios"]["BASE"]["bid_revision"])
        other = copy.deepcopy(self.st)
        other["scope"]["scope_version"] += 1
        self.assertNotEqual(bs.view(other)["scenarios"]["BASE"]["bid_revision"], self.v["scenarios"]["BASE"]["bid_revision"])

    def test_the_schedule_is_in_the_pricing_view(self):
        self.assertEqual(integration.view(self.st)["bid_schedule"]["scenarios"]["BASE"]["engine_total"], self.v["scenarios"]["BASE"]["engine_total"])

    def test_attribution_table_is_hashed_and_printable(self):
        self.assertEqual(self.v["scenarios"]["BASE"]["attribution_table_sha256"], bs.table_sha256())
        self.assertIn("| M42 | ITEM_16 |", bs.table_markdown())
        self.assertIn("| L04 | GROSS_RUN_AB |", bs.table_markdown())


class FailClosed(unittest.TestCase):
    def test_unresolved_g3_shows_item_14_unpriced_with_the_missing_fields_and_no_total(self):
        st = H.start(H.fixture())
        v = integration.view(st)["bid_schedule"]
        self.assertFalse(v["available"])
        self.assertIsNone(v["combined_total"])
        r14 = next(r for r in v["items"] if r["item_no"] == 14)
        self.assertEqual(r14["status"], "UNPRICED_MISSING_INPUT")
        self.assertTrue(any("clear_width_ft" in m for m in r14["missing"]))
        self.assertTrue(all("unit_price" not in r for r in v["items"]))                                            # no price is shown anywhere
        self.assertEqual(next(r for r in v["items"] if r["item_no"] == 16)["note"], "included in top-rail task")

    def test_a_line_without_a_rule_refuses_the_whole_schedule(self):
        st = H.priced()
        st = copy.deepcopy(st)
        st["estimate"]["scenarios"]["BASE"]["materials"]["lines"][0]["item_id"] = "M99"
        s = bs.view(st)["scenarios"]["BASE"]
        self.assertEqual((s["available"], s["refused"], s["items"]), (False, "ATTRIBUTION_MISSING_KEY", []))
        self.assertTrue(bs.view(st)["scenarios"]["ALT-A1"]["available"])                                           # the other scenario is unaffected

    def test_a_direct_cost_mismatch_refuses(self):
        st = copy.deepcopy(H.priced())
        st["estimate"]["scenarios"]["BASE"]["direct_cost"] += 0.01
        self.assertEqual(bs.view(st)["scenarios"]["BASE"]["refused"], "ATTRIBUTION_MISMATCH")

    def test_unknown_gate_and_missing_inputs_refuse_without_crashing(self):
        st = copy.deepcopy(H.priced())
        st["scope"]["gates"][0]["gate_id"] = "G9"
        self.assertEqual(bs.view(st)["scenarios"]["BASE"]["refused"], "UNKNOWN_GATE")
        st2 = copy.deepcopy(H.priced())
        st2["footing_schedule"] = None
        self.assertFalse(bs.view(st2)["scenarios"]["BASE"]["available"])


if __name__ == "__main__":
    unittest.main()

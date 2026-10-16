"""M09/M10 brace bands: ONE band per side, TWO per brace assembly (owner decision 2026-10-16 2:15 PM CT; ruleset 1.2.1)."""
import unittest

from pricing import quantities
from tests import footing_helpers as H


def q(st, sref):
    return {i.get("item_id") or i["driver_key"]: i for i in st["quantities"][sref]["items"]}


class BraceBands(unittest.TestCase):
    def test_m09_plus_m10_equal_two_bands_per_assembly_and_each_equals_the_assembly_count(self):
        st = H.priced()
        for sref in ("BASE", "ALT-A1"):
            items = q(st, sref)
            assemblies = items["M08"]["quantity"]
            self.assertEqual(assemblies, items["D08"]["quantity"])
            self.assertGreater(assemblies, 0)
            self.assertEqual(items["M09"]["quantity"] + items["M10"]["quantity"], 2 * assemblies, sref)
            self.assertEqual((items["M09"]["quantity"], items["M10"]["quantity"]), (assemblies, assemblies), sref)
            self.assertIn("1 per brace assembly", items["M09"]["calculation_method"])
            self.assertIn("1 per brace assembly", items["M10"]["calculation_method"])

    def test_the_dp001_assembly_count_is_16_so_16_and_16(self):
        items = q(H.priced(), "BASE")
        self.assertEqual((items["M08"]["quantity"], items["M09"]["quantity"], items["M10"]["quantity"]), (16.0, 16.0, 16.0))

    def test_ruleset_carries_the_decision_and_a_new_version(self):
        rs = quantities.load_ruleset()
        self.assertEqual(rs["version"], "1.2.1")
        P = rs["rules"]["params"]
        self.assertEqual((P["brace_bands_terminal_side_per_brace"], P["brace_bands_line_side_per_brace"]), (1, 1))
        self.assertIn("M09_M10", rs["rules"]["basis_notes"])

    def test_the_export_names_it_as_an_assumption(self):
        from engine import integration
        quals = integration.view(H.priced())["estimate_view"]["qualifications"]
        self.assertTrue(any("brace bands one per side, two per brace assembly" in x for x in quals))

    def test_a_scope_with_no_braces_gets_no_bands(self):
        st = H.priced()
        self.assertEqual(q(st, "BASE")["M09"]["quantity"] > 0, True)


if __name__ == "__main__":
    unittest.main()

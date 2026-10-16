"""Jordan decision #4: gate package is sourced from opening widths and replaces the old gate material costs."""
import unittest

from pricing import quantities
from pricing.engine import GATE_OVERRIDE_IDS, REPLACED_GATE_MATERIALS
from engine import bid_schedule
from tests import footing_helpers as H


class GateAssemblyOverride(unittest.TestCase):
    def test_shared_post_and_bracing_lines_stay_whole_on_the_fence_item(self):
        for key in ("M06", "M08", "M09", "M10", "M12", "M14", "M16"):
            self.assertEqual(bid_schedule.MATERIALS[key][0], "ITEM_10")

    def test_base_and_alternate_charge_each_gate_once_and_keep_posts_footings_labor(self):
        state = H.priced()
        for sref, scope in quantities.scenario_scopes(state["scope"]).items():
            scenario = state["estimate"]["scenarios"][sref]
            lines = scenario["materials"]["lines"]
            ids = {line["item_id"] for line in lines}
            self.assertFalse(ids & REPLACED_GATE_MATERIALS)
            self.assertTrue(set(GATE_OVERRIDE_IDS.values()) <= ids)
            self.assertTrue({"M01", "M40"} <= ids)
            for gate in scope["gates"]:
                gid = gate["gate_id"]
                width = gate["clear_width_ft"]["value"]
                count = gate["quantity"]["value"] if isinstance(gate["quantity"], dict) else gate["quantity"]
                matches = [line for line in lines if line["item_id"] == GATE_OVERRIDE_IDS[gid]]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]["quantity"], width * count)
                self.assertEqual(matches[0]["extended"], width * count * 250)
                self.assertTrue(matches[0]["tax_exempt"])
            self.assertIn("L08", {line["task_id"] for line in scenario["labor"]["lines"]})


if __name__ == "__main__":
    unittest.main()

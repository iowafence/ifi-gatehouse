"""Owner answers on ruleset 1.2.1 (2026-10-16 4:35 PM CT): rounding up, mid rail stops at gates, and the qualified assumptions the counts rest on."""
import copy
import unittest

from engine import assumptions, integration
from tests import footing_helpers as H


def items(st):
    return {i["id"]: i for i in assumptions.build(st)["items"]}


class Geometry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = H.priced()
        cls.a = items(cls.st)

    def test_the_two_behaviour_decisions_are_named_and_checked_against_the_live_ruleset(self):
        self.assertEqual(self.a["ASM-LINE-POST-ROUNDING"]["status"], "OWNER_DECIDED")
        self.assertEqual(self.a["ASM-MID-RAIL-STOPS-AT-GATES"]["status"], "OWNER_DECIDED")
        st = copy.deepcopy(self.st)
        st["ruleset"]["rules"]["params"]["mid_rail_elevation_ft"] = 8.0                        # a mid rail above the 7 ft leaf would NOT stop at gates
        a = items(st)["ASM-MID-RAIL-STOPS-AT-GATES"]
        self.assertEqual(a["status"], "OWNER_DECISION_NOT_MATCHED")
        self.assertIn("WARNING", a["export_line"])

    def test_qualified_assumptions_list_the_actual_values_and_say_until_a_document_states_them(self):
        quals = integration.view(self.st)["estimate_view"]["qualifications"]
        self.assertIn("Qualified assumption (owner: Jordan, until a document states it): top rail continuous across gate openings = yes.", quals)
        gs = self.a["ASM-GATE-STATIONS"]
        self.assertEqual(sorted((s["gate"], s["station_ft"]) for s in gs["value"]["stations_ft"]), [("G1", 69.0), ("G2", 43.0), ("G2", 43.0), ("G3", 31.0)])
        self.assertTrue(all(s["fact_path"].startswith("/footing_scope/runs/") and s["fact_path"].endswith("/station_ft") for s in gs["value"]["stations_ft"]))
        self.assertTrue(any(q.startswith("Qualified assumption") and "gate stations" in q and "G3 31 ft" in q for q in quals))
        sides = self.a["ASM-SIDE-LENGTHS-QUALIFIED"]["value"]["sides_ft"]
        self.assertEqual([(s["length_ft"]) for s in sides], [64.0])
        for i in ("ASM-TOP-RAIL-CONTINUOUS", "ASM-GATE-STATIONS", "ASM-SIDE-LENGTHS-QUALIFIED"):
            self.assertEqual(self.a[i]["status"], "OWNER_DECIDED")
            self.assertIn("until a document states it", self.a[i]["export_line"])

    def test_a_fact_a_document_now_states_drops_out_of_the_assumption_list(self):
        st = copy.deepcopy(self.st)
        for run in st["scope"]["footing_scope"]["runs"]:
            for side in run["layout"]["sides"]:
                for g in side.get("gates") or []:
                    g["station_ft"]["status"] = "confirmed"
                if isinstance(side.get("length_lf"), dict):
                    side["length_lf"]["status"] = "confirmed"
        st["scope"]["global_requirements"]["top_rail_continuous_across_gate_openings"]["status"] = "confirmed"
        a = items(st)
        for i in ("ASM-TOP-RAIL-CONTINUOUS", "ASM-GATE-STATIONS", "ASM-SIDE-LENGTHS-QUALIFIED"):
            self.assertNotIn(i, a)
        self.assertIn("ASM-LINE-POST-ROUNDING", a)

    def test_nothing_here_records_the_ruleset_approval_or_claims_it(self):
        text = " ".join(i["export_line"] + str(i["value"]) for i in self.a.values())
        self.assertNotIn("ruleset approved", text.lower())
        self.assertNotIn("approved the ruleset", text.lower())
        self.assertTrue(all("ruleset" not in i["id"].lower() for i in self.a.values()))


if __name__ == "__main__":
    unittest.main()

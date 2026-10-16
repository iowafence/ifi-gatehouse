"""Owner crew decision record (2026-10-16 3:58 PM CT): the fleet, its efficiencies and difficulty modifiers, drilling eligibility, the display-only fleet
average, the provisional drilling rule (mean of ACTUAL COSTS of the eligible crews) and the 35% burden. The crews are defined in the pinned workbook."""
import copy
import hashlib
import pathlib
import unittest
from decimal import Decimal as D, ROUND_HALF_UP

from engine import pricing_service as svc, ratebook_mode as rm
from pricing import crews
from tests import footing_helpers as H

CENT = D("0.01")


class DecisionRecord(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = H.priced()
        cls.rb = cls.st["ratebook"]
        cls.cs = {c["crew_id"]: c for c in cls.rb["crews"]}

    def test_the_four_fleet_crews_and_their_profiles_match_the_record(self):
        self.assertEqual(crews.fleet_crew_ids(self.rb), ["CR11", "CR12", "CR13", "CR14"])
        self.assertEqual([self.cs[c]["efficiency_pct"] for c in ("CR11", "CR12", "CR13", "CR14")], [104, 94, 88, 97])
        self.assertEqual(self.cs["CR14"]["members"], {"R1": 1, "R2": 2, "R4": 1})
        self.assertEqual((self.cs["CR14"]["difficulty"]["easy"], self.cs["CR14"]["difficulty"]["standard"], self.cs["CR14"]["difficulty"]["hard"]), (1.05, 1, 0.92))

    def test_drilling_eligibility_and_visible_reasons(self):
        e = {c["crew_id"]: c for c in crews.eligibility(self.rb, "L02")["crews"]}
        self.assertEqual({k: e[k]["eligible"] for k in ("CR11", "CR12", "CR13", "CR14")}, {"CR11": False, "CR12": False, "CR13": True, "CR14": True})
        for k in ("CR11", "CR12"):
            self.assertEqual([r["code"] for r in e[k]["reasons"]], ["MISSING_REQUIRED_ROLE"])
            self.assertEqual(e[k]["reasons"][0]["role_key"], "R4")

    def test_fleet_average_is_95_75_display_only_and_prices_nothing(self):
        ov = svc.fleet_overview(self.rb)
        self.assertEqual(ov["fleet_average_efficiency_pct"], 95.75)
        self.assertEqual(ov["fleet_average_display"], "95.8")                       # display rounding to one decimal; the stored mean is 95.75
        self.assertIn("display only", ov["basis"])
        # nothing priced depends on it: change CR11's efficiency (moving the average) and the provisional drilling price is unchanged
        base = self._provisional(self.rb)
        rb2 = copy.deepcopy(self.rb)
        next(c for c in rb2["crews"] if c["crew_id"] == "CR11")["efficiency_pct"] = 50
        self.assertNotEqual(svc.fleet_overview(rb2)["fleet_average_efficiency_pct"], 95.75)
        self.assertEqual(self._provisional(rb2)["L02"], base["L02"])

    def _provisional(self, rb):
        drivers = {i["driver_key"]: i["quantity"] for i in self.st["quantities"]["BASE"]["items"] if "driver_key" in i}
        st = copy.deepcopy(self.st)
        st["ratebook"] = rb
        comp = crews.compare(rb, drivers, {"default": "standard", "overrides": {}}, rm.crew_rates(st), None)
        prov = crews.provisional_labor(comp, set(crews.fleet_crew_ids(rb)))
        self._comp = comp
        return {l["task_id"]: l["provisional_cost"] for l in prov["lines"]}

    def test_provisional_drilling_is_the_mean_of_the_actual_costs_of_cr13_and_cr14(self):
        prov = self._provisional(self.rb)
        cost = {c["crew_id"]: D(repr(c["labor_cost"])) for t in self._comp["tasks"] if t["task_id"] == "L02" for c in t["candidates"] if c["calculable"]}
        self.assertIn("CR13", cost); self.assertIn("CR14", cost)
        self.assertNotIn("CR11", cost); self.assertNotIn("CR12", cost)               # ineligible: not averaged
        self.assertEqual(D(repr(prov["L02"])), ((cost["CR13"] + cost["CR14"]) / 2).quantize(CENT, rounding=ROUND_HALF_UP))
        self.assertNotEqual(cost["CR13"], cost["CR14"])
        eff_mean = (D(88) + D(97)) / 2                                               # averaging efficiencies instead would give a different, wrong number
        self.assertNotEqual(D(repr(prov["L02"])), (D(repr(self._comp["tasks"][1]["quantity"])) / (D(8) * eff_mean / 100) * D("139.88")).quantize(CENT))

    def test_burden_is_35_percent_on_every_role_every_fleet_crew_uses(self):
        self.assertEqual({r["role_key"]: r["burden_pct"] for r in self.rb["roles"]}, {"R1": 0.35, "R2": 0.35, "R3": 0.35, "R4": 0.35})
        for cid in ("CR11", "CR12", "CR13", "CR14"):
            self.assertTrue(set(self.cs[cid]["members"]) <= {"R1", "R2", "R3", "R4"})

    def test_the_crews_come_from_the_pinned_workbook_file(self):
        f = pathlib.Path("samples/public-demo/reference_pricing_workbook_v2_3_0.fictional.xlsx")
        self.assertEqual(hashlib.sha256(f.read_bytes()).hexdigest(), "3d43120473c8db3840557d62397e5f4fc5669b7f2b3cf5a0c86005fc88dde8f1")


if __name__ == "__main__":
    unittest.main()

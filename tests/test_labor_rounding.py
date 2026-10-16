"""Owner decision 2026-10-16 3:28 PM CT: labor rounds ONCE per task extension (hours x loaded rate); components are supporting detail."""
import unittest
from decimal import Decimal as D, ROUND_HALF_UP

from engine import assumptions, integration, ratebook_mode as rm
from pricing import crews
from tests import footing_helpers as H

CENT = D("0.01")


class Rounding(unittest.TestCase):
    def test_a_constructed_case_where_separate_rounding_would_differ_by_a_cent(self):
        crew = {"crew_id": "X", "members": {"R1": 1}, "efficiency_pct": 100, "difficulty": {"easy": 1, "standard": 1, "hard": 1}, "profile_version": "1"}
        opt = {"crew_id": "X", "production_rate": 100, "rate_basis": "standard", "is_default": True}
        hourly = {"wages": D("1"), "fringe": D("1"), "employer_costs": D("1"), "loaded": D("3")}
        m = crews.metrics({}, opt, crew, D("33.5"), "standard", hourly, 8)         # hours = 0.335
        self.assertEqual(m["_cost"], (D("0.335") * D("3")).quantize(CENT, rounding=ROUND_HALF_UP))      # 1.005 -> 1.01, rounded once
        self.assertEqual(sum(m["_parts"].values()), D("1.02"))                     # the components, each rounded alone, foot to 1.02: supporting detail only
        self.assertEqual(m["labor_cost"], 1.01)

    def test_every_engine_labor_line_is_hours_times_loaded_rate_rounded_once(self):
        st = H.priced()
        rates = rm.crew_rates(st)
        for sref, e in st["estimate"]["scenarios"].items():
            for l in e["labor"]["lines"]:
                crew = next(c for c in st["ratebook"]["crews"] if c["crew_id"] == l["crew_id"])
                opt = next(o for o in crews.options(st["ratebook"], next(t for t in st["ratebook"]["labor_tasks"] if t["task_id"] == l["task_id"])) if o["crew_id"] == l["crew_id"])
                hours = D(repr(l["quantity"])) / (D(repr(opt["production_rate"])) * (D(crew["efficiency_pct"]) / 100) * D(repr(crew["difficulty"][l["difficulty_level"]])))
                self.assertEqual(D(repr(l["extended"])), (hours * rates[l["crew_id"]]["loaded"]).quantize(CENT, rounding=ROUND_HALF_UP), (sref, l["task_id"]))
            self.assertEqual(D(repr(e["labor"]["subtotal"])), sum((D(repr(l["extended"])) for l in e["labor"]["lines"]), D(0)))
            self.assertIn("rounded ONCE", e["labor"]["components_note"])

    def test_the_export_labels_the_convention(self):
        quals = integration.view(H.priced())["estimate_view"]["qualifications"]
        self.assertTrue(any(q.startswith("Labor rounding: each task extension is rounded once") and "may differ from the extension by a cent" in q for q in quals))


if __name__ == "__main__":
    unittest.main()

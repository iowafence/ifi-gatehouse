"""Every exposed demo crew view must agree with the pinned rate book v2.3.0 (names, efficiency, fleet, drilling eligibility) and none may use the
quarantined legacy roster (crew_1/2/3, 'drilling_operator', 'Crew 2 can drill')."""
import json
import unittest

from engine import integration, pricing_service as svc
from tests.http_harness import HttpBase, WHO, plan

LEGACY_TOKENS = ("crew_1", "crew_2", "crew_3", "drilling_operator", "crews.example", "demo_ratebook")


class CrewViews(HttpBase):
    def setUp(self):
        super().setUp()
        self.fleet = svc.fleet_overview(self.book)
        self.ids = [c["crew_id"] for c in self.fleet["crews"]]
        self.truth = {c["crew_id"]: (integration.short_name(next(b for b in self.book["crews"] if b["crew_id"] == c["crew_id"])), c["efficiency_pct"]) for c in self.fleet["crews"]}
        self.drill = {c["crew_id"]: c["eligible"] for c in svc.task_eligibility(self.book, "L02")["crews"]}

    def views(self):
        """Every place a crew view is exposed over HTTP, collected from live responses."""
        self.to_wage_cleared()
        before = self.get()
        prev = self.call("POST", f"/projects/{self.pid}/crew-plan/preview", plan())[1]
        after = self.post("decisions/crew-plan", {**WHO, **plan()})
        port = self.call("GET", "/demo/portfolio")[1]
        return {"summary.crews": before["crews"], "pricing.crews": before["pricing"]["crews"], "after.crews": after["crews"], "portfolio": port,
                "comparison": before["pricing"]["crew_comparison"], "preview.comparison": prev["comparison"], "provisional": before["pricing"]["provisional"],
                "after.comparison": after["pricing"]["crew_comparison"]}

    def test_roster_views_equal_the_engine_fleet(self):
        v = self.views()
        for name in ("summary.crews", "pricing.crews", "after.crews"):
            r = v[name]
            self.assertEqual([c["crew_id"] for c in r["crews"]], self.ids, name)
            self.assertEqual({c["crew_id"]: (c["name"], c["efficiency_pct"]) for c in r["crews"]}, self.truth, name)
            self.assertEqual((r["fleet_average_pct"], r["crew_count"]), (95.8, 4), name)
            self.assertEqual(r["fleet_average_exact_pct"], 95.75)

    def test_portfolio_crews_are_fleet_crews_with_book_names_and_efficiency(self):
        seen = [c for p in self.views()["portfolio"]["projects"] for c in p["crew_plan"]]
        self.assertTrue(seen)
        for c in seen:
            self.assertEqual((c["name"], c["efficiency_pct"]), self.truth[c["crew_id"]])

    def test_comparison_and_preview_show_only_fleet_crews_with_the_engines_drilling_eligibility(self):
        v = self.views()
        for name in ("comparison", "preview.comparison", "after.comparison"):
            for cmp_ in v[name].values():
                drill = next(t for t in cmp_["tasks"] if t["task_id"] == "L02")
                self.assertEqual(sorted(c["crew_id"] for c in drill["candidates"]), sorted(self.ids), name)
                for c in drill["candidates"]:
                    self.assertEqual(c["eligible"], self.drill[c["crew_id"]], (name, c["crew_id"]))
                    if not c["eligible"]:
                        self.assertEqual(c["reasons_display"], [f"{c['crew_id']} has no Equipment operator (R4), which this task requires"])
                for t in cmp_["tasks"]:
                    self.assertTrue({c["crew_id"] for c in t["candidates"]} <= set(self.ids))
                self.assertEqual({c["crew_id"] for c in cmp_["crews"]}, set(self.ids))

    def test_provisional_drilling_average_uses_only_eligible_fleet_crews(self):
        prov = self.views()["provisional"]
        drill = next(l for l in prov["lines"] if l["task_id"] == "L02")
        eligible = sorted(c for c, ok in self.drill.items() if ok and c in self.ids)
        self.assertEqual(sorted(c["crew_id"] for c in drill["eligible_crews"]), eligible)
        self.assertFalse(prov["releasable"])

    def test_no_response_anywhere_uses_the_legacy_roster(self):
        v = self.views()
        text = json.dumps(v).lower() + json.dumps(self.call("GET", "/health")[1])
        for tok in LEGACY_TOKENS:
            self.assertNotIn(tok.lower(), text, tok)

    def test_dev_route_summaries_also_use_the_rate_book_roster(self):
        from api import server
        self.assertEqual([c["crew_id"] for c in server.CREWS["crews"]], self.ids)
        self.assertEqual(server.CREWS["fleet_average_pct"], 95.8)
        self.assertTrue({c["crew_id"] for p in server.PORTFOLIO["projects"] for c in p["crew_plan"]} <= set(self.ids))

class LegacyFixturesAreQuarantined(unittest.TestCase):
    def test_legacy_modules_are_not_importable_from_the_served_packages(self):
        import importlib
        with self.assertRaises(ImportError):
            importlib.import_module("engine.crews")

    def test_legacy_roster_is_labelled_and_still_contradicts_the_book_which_is_why_it_is_quarantined(self):
        from legacy_fixtures import legacy_crews
        cfg = legacy_crews.load()
        self.assertIn("LEGACY", json.dumps(cfg))
        elig = {a["crew_id"]: a["eligible"] for a in legacy_crews.task_view(cfg, "footing_drilling")["assignments"]}
        self.assertTrue(elig["crew_2"])                                                    # the misleading claim, preserved only for this named test


if __name__ == "__main__":
    unittest.main()

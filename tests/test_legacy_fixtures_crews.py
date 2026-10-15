import copy, unittest
from legacy_fixtures import legacy_crews as crews


class Crews(unittest.TestCase):
    def setUp(self):
        self.cfg = crews.load()

    def test_fleet_average_covers_all_crews(self):
        self.assertEqual(crews.fleet_average_pct(self.cfg), 95.3)  # (104 + 94 + 88) / 3

    def test_fleet_average_ignores_eligibility(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["tasks"][0]["requires"][0]["min"] = 5
        self.assertEqual(crews.fleet_average_pct(cfg), 95.3)
        self.assertEqual(crews.overview(cfg)["fleet_average_pct"], 95.3)

    def test_task_view_lists_all_crews_with_exact_reason(self):
        t = crews.task_view(self.cfg, "footing_drilling")
        self.assertEqual([a["crew_id"] for a in t["assignments"]], ["crew_1", "crew_2", "crew_3"])
        c1, c2, c3 = t["assignments"]
        self.assertFalse(c1["eligible"])
        self.assertEqual(c1["reasons"], ["Crew 1 has no qualified drilling operator"])
        self.assertTrue(c2["eligible"] and c3["eligible"])
        self.assertEqual(t["eligible_average_pct"], 91.0)
        self.assertEqual(t["pricing_basis"], "provisional_fleet_average")
        self.assertFalse(t["approved"])

    def test_no_eligible_crew_gives_no_average(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["tasks"][0]["requires"][0]["qualification"] = "nobody_has_this"
        self.assertIsNone(crews.task_view(cfg, "footing_drilling")["eligible_average_pct"])

    def test_bad_config_fails_closed(self):
        for mutate in (lambda c: c.update(crews=[]),
                       lambda c: c["crews"][0].update(efficiency_pct=float("nan")),
                       lambda c: c["crews"][0].update(efficiency_pct=0),
                       lambda c: c["crews"][0].update(efficiency_pct=True),
                       lambda c: c["crews"][1].update(crew_id="crew_1"),
                       lambda c: c["crews"][0].update(composition=[])):
            cfg = copy.deepcopy(self.cfg)
            mutate(cfg)
            with self.assertRaises(crews.CrewConfigError):
                crews.validate(cfg)


if __name__ == "__main__":
    unittest.main()

"""Portfolio KPI tests. Expected values are recalculated here by hand/independent arithmetic, not read from the module."""
import copy, json, pathlib, re, unittest
from fractions import Fraction
from engine import integration, portfolio

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = json.load(open(ROOT / "config/portfolio.example.json"))
ROSTER = integration.crew_roster(integration.load_book())      # the rate book v2.3.0 fleet is the only crew source


def rows(cfg):
    return [portfolio.derive(p, ROSTER) for p in cfg["projects"]]


class Seed(unittest.TestCase):
    def test_eight_distinct_synthetic_projects(self):
        ps = RAW["projects"]
        self.assertEqual(len(ps), 8)
        self.assertEqual(len({p["project_id"] for p in ps}), 8)
        self.assertEqual(len({p["name"] for p in ps}), 8)
        self.assertEqual(sorted(p["status"] for p in ps), ["bidding"] * 3 + ["lost"] * 2 + ["won"] * 3)
        self.assertEqual(sum(1 for p in ps if p["kind"] == "active_estimating"), 1)
        for r in portfolio.overview()["projects"]:
            self.assertTrue(r["synthetic"])
            self.assertTrue(r["owner"].startswith("Example "), r["owner"])
            self.assertEqual(r["figures_basis"], "estimated_at_bid")
        self.assertIn("SYNTHETIC", RAW["_note"])

    def test_seed_stores_only_source_inputs(self):
        for p in RAW["projects"]:
            for derived in ("gross_profit", "net_profit", "gross_margin_pct", "net_margin_pct", "direct_cost"):
                self.assertNotIn(derived, p)

    def test_no_credentials_or_documents_in_fixture(self):
        text = (ROOT / "config/portfolio.example.json").read_text()
        self.assertIsNone(re.search(r"(api[_-]?key|secret|token|password)\s*[:=]|\.pdf|\.zip|\.xlsx|@", text, re.I))

    def test_crew_plans_resolve_to_configured_crews(self):
        cfg = ROSTER
        names = {c["crew_id"]: (c["name"], c["efficiency_pct"]) for c in cfg["crews"]}
        seen = [c for r in portfolio.overview(None, ROSTER)["projects"] for c in r["crew_plan"]]
        self.assertTrue(seen, "fixture crews must resolve against the rate-book fleet (previously vacuous)")
        for r in portfolio.overview(None, ROSTER)["projects"]:
            for c in r["crew_plan"]:
                self.assertEqual((c["name"], c["efficiency_pct"]), names[c["crew_id"]])
        for p in RAW["projects"]:
            for c in p["crew_plan"]:
                self.assertIn(c, names)


class Derivation(unittest.TestCase):
    def test_every_figure_agrees_with_components(self):
        for r in portfolio.overview()["projects"]:
            direct = r["materials_cost"] + r["labor_cost"] + r["other_direct_cost"]
            self.assertEqual(r["direct_cost"], direct)
            self.assertEqual(r["gross_profit"], r["bid_amount"] - direct)
            self.assertEqual(r["net_profit"], r["gross_profit"] - r["allocated_overhead"])
            self.assertAlmostEqual(r["gross_margin_pct"], 100 * r["gross_profit"] / r["bid_amount"], delta=0.051)
            self.assertAlmostEqual(r["net_margin_pct"], 100 * r["net_profit"] / r["bid_amount"], delta=0.051)

    def test_hand_checked_project(self):  # Des Moines: 186400 - (79200+41800+9600) = 55800; - 25100 = 30700
        r = portfolio.overview()["projects"][0]
        self.assertEqual((r["gross_profit"], r["net_profit"], r["gross_margin_pct"], r["net_margin_pct"]), (55800, 30700, 29.9, 16.5))


class Kpis(unittest.TestCase):
    def setUp(self):
        self.k = portfolio.overview()["kpis"]

    def test_values_match_independent_recalculation(self):
        ps = RAW["projects"]
        bid = [p for p in ps if p["status"] == "bidding"]
        self.assertEqual(self.k["active_bids"], 3)
        self.assertEqual(self.k["win_rate_pct"], 60.0)          # 3 won / (3 won + 2 lost); bidding excluded
        self.assertEqual(self.k["open_bid_pipeline"], 186400 + 312000 + 127300)
        np_ = {p["project_id"]: p["bid_amount"] - p["materials_cost"] - p["labor_cost"] - p["other_direct_cost"] - p["allocated_overhead"] for p in ps}
        exp = sum(Fraction(np_[p["project_id"]]) * Fraction(str(p["win_probability"])) for p in bid)
        self.assertEqual(exp, Fraction(35280))
        self.assertEqual(self.k["expected_pipeline_net_profit"], 35280)
        gp = [Fraction(p["bid_amount"] - p["materials_cost"] - p["labor_cost"] - p["other_direct_cost"], p["bid_amount"]) for p in ps]
        self.assertEqual(self.k["avg_estimated_gp_pct"], round(float(100 * sum(gp) / 8), 1))
        npp = [Fraction(np_[p["project_id"]], p["bid_amount"]) for p in ps]
        self.assertEqual(self.k["avg_expected_np_pct"], round(float(100 * sum(npp) / 8), 1))
        self.assertEqual(self.k["margin_projects_counted"], 8)

    def test_won_and_lost_are_not_active_bids_and_not_in_pipeline(self):
        cfg = copy.deepcopy(RAW)
        for p in cfg["projects"]:
            p["status"] = "won" if p["status"] == "bidding" else p["status"]
            p["win_probability"] = None
        k = portfolio.kpis(rows(cfg))
        self.assertEqual((k["active_bids"], k["open_bid_pipeline"], k["expected_pipeline_net_profit"]), (0, 0, 0))
        self.assertEqual(k["win_rate_pct"], round(100 * 6 / 8, 1))

    def test_win_rate_none_when_nothing_decided(self):
        cfg = copy.deepcopy(RAW)
        cfg["projects"] = [p for p in cfg["projects"] if p["status"] == "bidding"]
        self.assertIsNone(portfolio.kpis(rows(cfg))["win_rate_pct"])

    def test_overhead_is_deducted_from_net_profit(self):
        cfg = copy.deepcopy(RAW)
        base = portfolio.kpis(rows(cfg))["expected_pipeline_net_profit"]
        for p in cfg["projects"]:
            p["allocated_overhead"] += 1000
        self.assertEqual(portfolio.kpis(rows(cfg))["expected_pipeline_net_profit"], base - round(1000 * (0.45 + 0.35 + 0.55)))

    def test_missing_or_unusable_inputs_are_explicit_not_zero(self):
        for bad in (None, float("nan"), -5, "100", True):
            cfg = copy.deepcopy(RAW)
            cfg["projects"][2]["labor_cost"] = bad
            rs = rows(cfg)
            self.assertEqual(rs[2]["missing_inputs"], ["labor_cost"])
            self.assertIsNone(rs[2]["net_profit"])
            k = portfolio.kpis(rs)
            self.assertEqual(k["excluded_missing_inputs"], ["PF-2026-003"])
            self.assertEqual(k["margin_projects_counted"], 7)
            self.assertEqual(k["open_bid_pipeline"], 186400 + 127300)   # unusable bid not counted as pipeline

    def test_zero_bid_does_not_divide_by_zero(self):
        cfg = copy.deepcopy(RAW)
        cfg["projects"][0]["bid_amount"] = 0
        r = rows(cfg)[0]
        self.assertEqual(r["missing_inputs"], ["bid_amount"])
        portfolio.kpis(rows(cfg))

    def test_empty_eligible_set_gives_none(self):
        cfg = copy.deepcopy(RAW)
        for p in cfg["projects"]:
            p["materials_cost"] = None
        k = portfolio.kpis(rows(cfg))
        self.assertIsNone(k["avg_estimated_gp_pct"])
        self.assertIsNone(k["avg_expected_np_pct"])

    def test_bidding_without_probability_is_flagged_not_assumed(self):
        cfg = copy.deepcopy(RAW)
        cfg["projects"][0]["win_probability"] = None
        k = portfolio.kpis(rows(cfg))
        self.assertEqual(k["bidding_without_win_probability"], ["PF-2026-001"])
        self.assertEqual(k["expected_pipeline_net_profit"], round(36500 * 0.35 + 15800 * 0.55))

    def test_validation_fails_closed(self):
        for mutate in (lambda c: c.update(projects=[]), lambda c: c["projects"][0].update(status="pending"),
                       lambda c: c["projects"][1].update(project_id="PF-2026-001"),
                       lambda c: c["projects"][0].update(win_probability=1.5),
                       lambda c: c["projects"][1].update(kind="active_estimating")):
            cfg = copy.deepcopy(RAW)
            mutate(cfg)
            with self.assertRaises(portfolio.PortfolioError):
                portfolio.validate(cfg)

    def test_fleet_average_unaffected_by_portfolio(self):
        self.assertEqual(ROSTER["fleet_average_pct"], 95.8)


if __name__ == "__main__":
    unittest.main()

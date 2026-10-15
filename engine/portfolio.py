"""Synthetic portfolio fixtures and the KPIs derived from them. Pure code, no model, no network.

Only source inputs are stored (bid, cost components, overhead, win probability). Gross profit, net profit and
margins are derived here, so no displayed figure can disagree with its components. Money is exact (Decimal).
For Won and Lost jobs every margin is an ESTIMATE MADE AT BID TIME, not realized profit.
"""
import json
import math
import pathlib
from decimal import Decimal, ROUND_HALF_UP


ROOT = pathlib.Path(__file__).resolve().parent.parent
STATUSES = ("bidding", "won", "lost")
KINDS = ("active_estimating", "portfolio_fixture")
COSTS = ("materials_cost", "labor_cost", "other_direct_cost")
ONE = Decimal("0.1")


class PortfolioError(ValueError):
    pass


def load(path=None):
    p = pathlib.Path(path) if path else ROOT / "config/portfolio.example.json"
    return validate(json.load(open(p)))


def _money(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x >= 0


def validate(cfg):
    if not isinstance(cfg, dict) or not isinstance(cfg.get("projects"), list) or not cfg["projects"]:
        raise PortfolioError("projects must be a non-empty list")
    ids = set()
    for p in cfg["projects"]:
        if not isinstance(p, dict) or not isinstance(p.get("project_id"), str) or p["project_id"] in ids:
            raise PortfolioError("project_id must be a unique string")
        ids.add(p["project_id"])
        if p.get("status") not in STATUSES or p.get("kind") not in KINDS:
            raise PortfolioError(f"{p['project_id']}: bad status or kind")
        if not isinstance(p.get("name"), str) or not p["name"].strip():
            raise PortfolioError(f"{p['project_id']}: name required")
        wp = p.get("win_probability")
        if wp is not None and not (isinstance(wp, (int, float)) and not isinstance(wp, bool) and 0 <= wp <= 1):
            raise PortfolioError(f"{p['project_id']}: win_probability must be in [0, 1]")
    if sum(1 for p in cfg["projects"] if p["kind"] == "active_estimating") > 1:
        raise PortfolioError("at most one active estimating project")
    return cfg


def _d(x):
    return Decimal(str(x))


def _pct1(num, den):
    return float((num / den * 100).quantize(ONE, rounding=ROUND_HALF_UP))


def derive(p, crew_cfg=None):
    """Derived figures for one project. Missing or unusable financial inputs are reported, never defaulted to zero."""
    missing = [k for k in ("bid_amount", *COSTS, "allocated_overhead") if not _money(p.get(k))]
    if not missing and p["bid_amount"] <= 0:
        missing = ["bid_amount"]
    out = {k: p.get(k) for k in ("project_id", "name", "owner", "project_type", "status", "kind", "bid_date", "decision_date",
                                 "bid_amount", *COSTS, "allocated_overhead", "win_probability", "loss_reason")}
    out["synthetic"] = True
    out["figures_basis"] = "estimated_at_bid"
    out["read_only"] = p["kind"] != "active_estimating"
    out["missing_inputs"] = missing
    crew_names = {c["crew_id"]: c for c in (crew_cfg or {}).get("crews", [])}
    out["crew_plan"] = [{"crew_id": c, "name": crew_names[c]["name"], "efficiency_pct": crew_names[c]["efficiency_pct"]}
                        for c in p.get("crew_plan", []) if c in crew_names]
    if missing:
        out.update(direct_cost=None, gross_profit=None, gross_margin_pct=None, net_profit=None, net_margin_pct=None)
        return out
    bid = _d(p["bid_amount"])
    direct = sum(_d(p[k]) for k in COSTS)
    gp = bid - direct
    np_ = gp - _d(p["allocated_overhead"])
    out.update(direct_cost=int(direct), gross_profit=int(gp), net_profit=int(np_),
               gross_margin_pct=_pct1(gp, bid), net_margin_pct=_pct1(np_, bid))
    out["_gp_ratio"], out["_np_ratio"] = gp / bid * 100, np_ / bid * 100  # exact, for averaging; stripped before output
    return out


def kpis(rows):
    """Portfolio KPIs from derived rows. A project with missing inputs is excluded from margin figures, and listed."""
    bidding = [r for r in rows if r["status"] == "bidding"]
    won = sum(1 for r in rows if r["status"] == "won")
    lost = sum(1 for r in rows if r["status"] == "lost")
    eligible = [r for r in rows if not r["missing_inputs"]]

    def avg(key):
        return float((sum((r[key] for r in eligible), Decimal(0)) / len(eligible)).quantize(ONE, rounding=ROUND_HALF_UP)) if eligible else None

    pipe_rows = [r for r in bidding if not r["missing_inputs"]]
    exp_rows = [r for r in pipe_rows if r["win_probability"] is not None]
    expected = sum((_d(r["net_profit"]) * _d(r["win_probability"]) for r in exp_rows), Decimal(0))
    return {
        "active_bids": len(bidding),
        "won": won, "lost": lost,
        "win_rate_pct": _pct1(Decimal(won), Decimal(won + lost)) if won + lost else None,
        "avg_estimated_gp_pct": avg("_gp_ratio"),
        "avg_expected_np_pct": avg("_np_ratio"),
        "open_bid_pipeline": int(sum((_d(r["bid_amount"]) for r in pipe_rows), Decimal(0))),
        "expected_pipeline_net_profit": int(expected.quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
        "margin_projects_counted": len(eligible),
        "excluded_missing_inputs": [r["project_id"] for r in rows if r["missing_inputs"]],
        "bidding_without_win_probability": [r["project_id"] for r in pipe_rows if r["win_probability"] is None],
        "basis": "Estimated at bid time; not realized profit.",
    }


def overview(cfg=None, crew_cfg=None):
    cfg = cfg or load()
    rows = [derive(p, crew_cfg) for p in cfg["projects"]]
    summary = kpis(rows)
    for r in rows:
        r.pop("_gp_ratio", None), r.pop("_np_ratio", None)
    return {"synthetic": True, "note": cfg.get("_note"), "kpis": summary, "projects": rows}

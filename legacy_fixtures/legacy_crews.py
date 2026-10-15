"""LEGACY / QUARANTINED stand-in (NOT the rate-book fleet). Crew performance and task eligibility. Pure code; all arithmetic lives here, never in the UI or a model.

Two different questions, deliberately kept apart:
  fleet_average_pct  informational baseline over EVERY configured crew. Eligibility never changes it.
  task_view(...)     per-task eligibility for every crew (ineligible ones carry exact reasons) and the average over
                     eligible crews only. Pricing must use validated eligible assignments or an approved
                     eligible-crew average; the fleet average is only a clearly labeled provisional assumption.
Nothing here is an approval gate and nothing here changes an estimate: wiring crew rates into pricing is a
separate, reviewed change.
"""
import json
import math
import pathlib
from decimal import Decimal, ROUND_HALF_UP

ROOT = pathlib.Path(__file__).resolve().parent


class CrewConfigError(ValueError):
    pass


def load(path=None):
    p = pathlib.Path(path) if path else ROOT / "crews.legacy.json"
    return validate(json.load(open(p)))


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def validate(cfg):
    if not isinstance(cfg, dict) or not isinstance(cfg.get("crews"), list) or not cfg["crews"]:
        raise CrewConfigError("crews must be a non-empty list")
    seen = set()
    for c in cfg["crews"]:
        if not isinstance(c, dict) or not isinstance(c.get("crew_id"), str) or not c["crew_id"].strip() or c["crew_id"] in seen:
            raise CrewConfigError("crew_id must be a unique non-empty string")
        seen.add(c["crew_id"])
        if not isinstance(c.get("name"), str) or not c["name"].strip():
            raise CrewConfigError(f"{c['crew_id']}: name required")
        if not _num(c.get("efficiency_pct")) or not 0 < c["efficiency_pct"] <= 300:
            raise CrewConfigError(f"{c['crew_id']}: efficiency_pct must be a finite number in (0, 300]")
        comp = c.get("composition")
        if not isinstance(comp, list) or not comp or not all(
                isinstance(m, dict) and isinstance(m.get("role"), str) and isinstance(m.get("qualifications"), list)
                and all(isinstance(q, str) for q in m["qualifications"]) for m in comp):
            raise CrewConfigError(f"{c['crew_id']}: composition must list members with role and qualifications")
    tasks = cfg.get("tasks", [])
    if not isinstance(tasks, list):
        raise CrewConfigError("tasks must be a list")
    for t in tasks:
        if not isinstance(t, dict) or not isinstance(t.get("task_id"), str) or not isinstance(t.get("requires"), list) or not all(
                isinstance(r, dict) and isinstance(r.get("qualification"), str) and isinstance(r.get("min"), int)
                and not isinstance(r.get("min"), bool) and r["min"] >= 1 and isinstance(r.get("label"), str) for r in t["requires"]):
            raise CrewConfigError("each task needs task_id and requires[{qualification,min>=1,label}]")
    return cfg


def _round1(values):
    """Mean rounded half-up to one decimal, computed in Decimal so 95.333... gives 95.3 deterministically."""
    if not values:
        return None
    mean = sum(Decimal(str(v)) for v in values) / Decimal(len(values))
    return float(mean.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def fleet_average_pct(cfg):
    return _round1([c["efficiency_pct"] for c in cfg["crews"]])


def eligibility(crew, task):
    reasons = []
    for req in task["requires"]:
        have = sum(1 for m in crew["composition"] if req["qualification"] in m["qualifications"])
        if have < req["min"]:
            reasons.append(f"{crew['name']} has no {req['label']}" if req["min"] == 1 and have == 0 else
                           f"{crew['name']} has {have} {req['label']}(s); {req['min']} required")
    return not reasons, reasons


def task_view(cfg, task_id):
    task = next((t for t in cfg.get("tasks", []) if t["task_id"] == task_id), None)
    if task is None:
        return None
    rows = []
    for c in cfg["crews"]:
        ok, reasons = eligibility(c, task)
        rows.append({"crew_id": c["crew_id"], "name": c["name"], "efficiency_pct": c["efficiency_pct"],
                     "eligible": ok, "reasons": reasons})
    elig = [r["efficiency_pct"] for r in rows if r["eligible"]]
    return {"task_id": task["task_id"], "label": task["label"], "assignments": rows,
            "eligible_average_pct": _round1(elig),
            "pricing_basis": "provisional_fleet_average", "provisional_pct": fleet_average_pct(cfg),
            "approved": False,
            "note": "Provisional. Final pricing needs validated eligible crew assignments or an approved "
                    "eligible-crew average. Crew rates are not yet applied to the estimate in this build."}


def overview(cfg, task_id="footing_drilling"):
    try:
        return {"fleet_average_pct": fleet_average_pct(cfg),
                "crews": [{"crew_id": c["crew_id"], "name": c["name"], "efficiency_pct": c["efficiency_pct"],
                           "composition": [{"role": m["role"], "qualifications": list(m["qualifications"])} for m in c["composition"]]}
                          for c in cfg["crews"]],
                "task": task_view(cfg, task_id), "fictional": True}
    except (KeyError, TypeError):
        return {"error": "crew data unavailable"}

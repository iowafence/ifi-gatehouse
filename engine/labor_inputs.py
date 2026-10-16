"""Labor and payroll INPUTS the engine used for a priced project, as plain data, so an independent key can confirm it used identical inputs.

No dollar totals and no labor line amounts are included: only the inputs (rates, percentages, hours, quantities, crews) and the per-task
reproduction booleans that say whether the engine's own labor lines follow from those inputs. Read-only; changes nothing."""
from decimal import Decimal as D, ROUND_HALF_UP

from pricing import prevailing
from . import ratebook_mode as rm

c = lambda x: x.quantize(D("0.01"), rounding=ROUND_HALF_UP)
d = lambda x: D(str(x))


def dump(state):
    if not state.get("estimate") or not state.get("ratebook") or not rm.wage_required(state):
        raise ValueError("a priced prevailing-wage project is required")
    rb, wd = state["ratebook"], state["wage_determination"]
    roles = rm.labor_roles(state)
    ev = prevailing.evaluate(wd, roles, rm.as_of(state))
    names = {r["role_key"]: r for r in rb["roles"]}
    sched = {s["classification"].strip().lower(): s for s in wd["schedule"]}
    rows = {r["role_key"]: r for r in wd["rows"]}
    role_data = []
    for rk in roles:
        r, sup = rows[rk], ev["supported"][rk]
        s = sched.get((r["classification"] or "").strip().lower())
        role_data.append({"role_key": rk, "role": names[rk]["role"], "classification": r["classification"], "classification_status": r["classification_status"],
                          "base_rate_per_hr": r["base_rate"], "fringe_rate_per_hr": r["fringe_rate"], "source_ref": r["source_ref"],
                          "decision_base_rate_per_hr": s["base_rate"] if s else None, "decision_fringe_rate_per_hr": s["fringe_rate"] if s else None,
                          "above_decision": sup["above_decision"], "employer_cost_per_hr": float(sup["employer_costs"]), "loaded_rate_per_hr": float(sup["loaded"]),
                          "workbook_company_base_wage_per_hr": names[rk]["base_wage_per_hr"], "workbook_company_burden_pct": names[rk]["burden_pct"],
                          "base_rate_basis": ("Attachment A floor (workbook rate raised, FLAGGED)" if r.get("floor_adjustment") else "recorded base rate"),
                          "floor_adjustment": r.get("floor_adjustment")})
    eb = wd["employer_burden"]
    plan = state.get("crew_plan") or {}
    out = {"run": {"ratebook": rb["meta"]["ratebook_id"] + " " + rb["meta"]["version"], "ratebook_sha256": state["ratebook_ref"].get("content_sha256") if isinstance(state["ratebook_ref"], dict) else None,
                   "ruleset": f"{state['ruleset']['ruleset_id']} {state['ruleset']['version']}", "ruleset_sha256": state["ruleset"]["sha256"],
                   "scope_version": state["scope"]["scope_version"], "as_of": str(rm.as_of(state)), "headline_scope_ref": state["estimate"]["headline_scope_ref"]},
           "wage_decision": {**wd["determination"], "recorded_by": wd["recorded_by"], "schedule": wd["schedule"], "production_rates_approved": wd["production_rates_approved"]},
           "roles": role_data,
           "formulas": {"loaded_rate_per_hr": "base wage + fringe + employer cost", "employer_cost_per_hr": f"base wage x employer burden pct ({eb['pct']}); applied to WAGES ONLY, fringe is not burdened",
                        "crew_rate_per_hr": "sum over crew members of (count x loaded_rate_per_hr of the member's role)",
                        "effective_production": "crew production rate (rate book crew option for this task and crew) x crew efficiency pct x difficulty multiplier",
                        "crew_hours": "driver quantity / effective_production", "worker_hours": "crew_hours x crew size",
                        "labor_line_amount": "crew_hours x crew_rate_per_hr, rounded half-up to the cent (amount not published here)"},
           "employer_burden": {"pct": eb["pct"], "source_ref": eb["source_ref"]},
           "certified_payroll_admin": {k: wd["certified_payroll_admin"].get(k) for k in ("basis", "unit_cost", "weeks", "reason", "source_ref")},
           "crew_plan": {"preferred_crew": plan.get("preferred_crew"), "assignments": plan.get("assignments"), "use_default_for_unassigned": plan.get("use_default_for_unassigned"),
                         "difficulty": plan.get("difficulty"), "approved_by": plan.get("approved_by") or plan.get("by")},
           "markup_percentages_from_rate_book": rb["markups"], "scenarios": {}}
    crews = {cr["crew_id"]: cr for cr in rb["crews"]}
    opts = {(o["task_id"], o["crew_id"]): o for o in rb["crew_options"]}
    tasks = {t["task_id"]: t for t in rb["labor_tasks"]}
    sup = ev["supported"]
    for sref, e in state["estimate"]["scenarios"].items():
        lines = []
        for l in e["labor"]["lines"]:
            cr = crews[l["crew_id"]]
            crew_rate = sum((d(sup[rk]["loaded"]) * n for rk, n in cr["members"].items()), D(0))
            size = sum(cr["members"].values())
            opt = opts.get((l["task_id"], l["crew_id"]))
            hours_ok = abs(d(l["quantity"]) / d(l["effective_production"]) - d(l["crew_hours"])) < D("0.00001")
            lines.append({"task_id": l["task_id"], "task": l["task"], "driver_key": l["driver_key"], "uom": l["uom"], "driver_quantity": l["quantity"],
                          "task_default_crew_id": tasks[l["task_id"]]["crew_id"], "task_default_production_rate": tasks[l["task_id"]]["production_rate"], "crew_id": l["crew_id"], "crew_members": cr["members"], "crew_size": size,
                          "production_rate_used": opt["production_rate"] if opt else tasks[l["task_id"]]["production_rate"],
                          "production_rate_source": ("rate book crew option for this task and crew" if opt else "rate book labor task production rate (workbook; no crew-specific option)"), "crew_efficiency_pct": l["efficiency_pct"],
                          "difficulty_level": l["difficulty_level"], "difficulty_multiplier": l["difficulty_multiplier"], "effective_production": l["effective_production"],
                          "crew_hours": l["crew_hours"], "worker_hours": l["worker_hours"], "crew_rate_per_hr": float(c(crew_rate)),
                          "source": {"driver_quantity": f"quantity payload driver {l['driver_key']} for {sref}", "production": "rate book: crew option when one exists for the task and crew, otherwise the labor task production rate",
                                     "efficiency_and_difficulty": "rate book crew profile, difficulty level from the approved crew plan"},
                          "reproduces": {"crew_hours_from_quantity_and_effective_production": hours_ok,
                                         "worker_hours_from_crew_hours_and_size": abs(d(l["crew_hours"]) * size - d(l["worker_hours"])) < D("0.0001"),
                                         "line_amount_from_crew_hours_and_crew_rate": c(d(l["crew_hours"]) * c(crew_rate)) == d(l["extended"])
                                         or abs(c(d(l["crew_hours"]) * crew_rate) - d(l["extended"])) <= D("0.01")}})
        out["scenarios"][sref] = {"tasks": lines, "crew_hours_total": e["labor"]["crew_hours"], "worker_hours_total": e["labor"]["worker_hours"]}
    return out

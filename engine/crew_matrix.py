"""Read-only crew matrix: for every labor task (L01-L10) and every crew the rate book prices for it, the crew's hourly cost with its components,
the production rate for that task, the resulting hours and task cost, and whether the crew is ELIGIBLE (with the reason) and in the FLEET.

It reuses the engine's own `crews.metrics` and `crews.suitability`/`reason_details`; it applies no rule of its own and changes no eligibility.
Cost components (wages, fringe, employer cost) are shown only for a prevailing-wage record a person entered; company rate-book wages are not
disclosed (hourly cost is then the single loaded figure, as in the existing comparison)."""
from decimal import Decimal as D

from pricing import crews, prevailing
from . import ratebook_mode as rm

DEFINITIONS = {
    "fleet": "The crews the rate book offers as per-task ALTERNATIVES (workbook sheet Crew_Production). They are the crews a person may select in a crew plan. "
             "If a book has no alternatives, every crew it prices is the fleet. The legacy default crews named on the workbook Labor sheet (CR1 to CR4 here) are not fleet "
             "members while alternatives exist; the engine's own plan checks refuse selecting a non-fleet crew through the API (CREW_NOT_IN_FLEET).",
    "eligible": "Per task and per crew: the crew has every role and every qualification the task requires (workbook Labor sheet, columns required roles and required qualifications). "
                "Efficiency never makes a crew eligible and nothing is assumed. Eligibility is independent of fleet membership.",
    "data_source": "Crew profiles: workbook sheet Crews. Task default crew, default production rate and required roles: sheet Labor. Per-task alternatives and their production rates: sheet Crew_Production. "
                   "None of this is company configuration.",
    "job_level": "ONE crew does the whole job (L01-L10), never a mix (owner decision 2026-10-16 4:04 PM CT). A crew plan is one crew id for every task; mixed plans are rejected. "
                 "A crew is JOB-eligible only if it can perform EVERY task; the cell-level eligibility above is the per-task view of the same rule. No selected plan averages anything: "
                 "each task costs the selected crew's actual cost. The provisional average exists only before a crew is selected, is labeled PROVISIONAL, and no total or export is produced until a crew is selected.",
    "hours": "crew hours = task quantity / (production rate x efficiency x difficulty multiplier); worker hours = crew hours x headcount",
}


def _members(state, cid, ev):
    names = {r["role_key"]: r["role"] for r in state["ratebook"]["roles"]}
    crew = next(c for c in state["ratebook"]["crews"] if c["crew_id"] == cid)
    rows = []
    for rk, n in sorted(crew["members"].items()):
        s = ev["supported"].get(rk) if ev else None
        rows.append({"role_key": rk, "role": names.get(rk, rk), "count": n,
                     "wages_per_hr": float(s["wages"]) if s else None, "fringe_per_hr": float(s["fringe"]) if s else None,
                     "employer_cost_per_hr": float(s["employer_costs"]) if s else None, "loaded_per_hr": float(s["loaded"]) if s else None})
    return rows


def build(state, include_non_fleet=False):
    rb = state.get("ratebook")
    if not rb or not state.get("quantities"):
        return None
    plan = state.get("crew_plan")
    difficulty = plan["difficulty"] if plan else {"default": "standard", "overrides": {}}
    prevailing_path = rm.wage_required(state)
    wd = state.get("wage_determination")
    ev = prevailing.evaluate(wd, rm.labor_roles(state), rm.as_of(state)) if (prevailing_path and wd) else None
    rates = rm.crew_rates(state)                       # {crew_id: dict(components) | Decimal}; crews whose cost is not established are absent
    cs = crews.crews_by_id(rb)
    fleet = set(crews.fleet_crew_ids(rb))
    shown = fleet if not include_non_fleet else set(crews.used_crews(rb))     # the served view is the fleet only; the wider view exists only for the engine-math baseline script
    alt = {o["crew_id"] for o in rb.get("crew_options", [])}
    workday = rb["meta"]["workday_hours"]
    out = {"definitions": DEFINITIONS, "difficulty": difficulty, "difficulty_approved": bool(plan), "wage_basis": "prevailing wage record" if prevailing_path else "company rate book",
           "components_disclosed": bool(prevailing_path and ev), "crews_shown": "fleet crews only" if not include_non_fleet else "ALL crews the book prices (engine-math baseline; not the served view)",
           "availability": "NOT MODELED: the engine has no crew calendar, headcount limit or scheduling model. Whether a crew is actually free is a human judgment made when a person approves the crew plan.",
           "scenarios": {}}
    crew_rows = []
    for cid in [c for c in crews.used_crews(rb) if c in shown]:
        r = rates.get(cid)
        hourly = ({"wages_per_hr": float(r["wages"]), "fringe_per_hr": float(r["fringe"]), "employer_cost_per_hr": float(r["employer_costs"]), "loaded_per_hr": float(r["loaded"])}
                  if isinstance(r, dict) and prevailing_path else
                  ({"wages_per_hr": None, "fringe_per_hr": None, "employer_cost_per_hr": None, "loaded_per_hr": float(r)} if r is not None else None))
        crew_rows.append({"crew_id": cid, "description": cs[cid]["description"], "headcount": crews.headcount(cs[cid]), "members": _members(state, cid, ev) if ev else [],
                          "efficiency_pct": cs[cid]["efficiency_pct"], "difficulty_response": cs[cid]["difficulty"], "in_fleet": cid in fleet,
                          "fleet_reason": ("offered as a per-task alternative (workbook Crew_Production sheet)" if cid in alt else
                                           ("every crew the book prices (it has no alternatives)" if not alt else "legacy per-task default crew (workbook Labor sheet); not selectable while alternatives exist")),
                          "job_eligible": crews.job_eligibility(rb, cid)["eligible"], "job_ineligibility_reasons": crews.job_eligibility(rb, cid)["reasons"],
                          "hourly": hourly, "hourly_reason": None if hourly else "this crew's hourly cost is not established (a role has no approved wage basis)"})
    out["crews"] = crew_rows
    for sref, payload in state["quantities"].items():
        drivers = {i["driver_key"]: i["quantity"] for i in payload["items"] if "driver_key" in i}
        tasks = []
        for t in rb["labor_tasks"]:
            qty = D(drivers[t["driver_key"]]) if drivers.get(t["driver_key"]) is not None else None
            level = crews.level_for(difficulty, t["driver_key"])
            sel = crews.assigned_crew(plan, rb, t) if plan else None
            cands = []
            for o in crews.options(rb, t):
                if o["crew_id"] not in shown:
                    continue
                crew = cs[o["crew_id"]]
                why = crews.reason_details(rb, t, crew)
                row = {"crew_id": crew["crew_id"], "in_fleet": crew["crew_id"] in fleet, "is_task_default": o["is_default"], "selected": sel == crew["crew_id"],
                       "eligible": not why, "eligibility_reasons": why, "production_rate": o["production_rate"], "rate_basis": o["rate_basis"],
                       "hourly": next(c["hourly"] for c in crew_rows if c["crew_id"] == crew["crew_id"]), "calculable": False}
                if qty is None:
                    row["not_calculable_reason"] = "task quantity is unresolved"
                elif why:
                    row["not_calculable_reason"] = "crew is not eligible for this task"
                elif crew["crew_id"] not in rates:
                    row["not_calculable_reason"] = "this crew's hourly cost is not established (a role has no approved wage basis)"
                else:
                    m = crews.metrics(t, o, crew, qty, level, rates[crew["crew_id"]], workday)
                    parts = m["_parts"]
                    row.update(calculable=True, efficiency_pct=m["efficiency_pct"], efficiency_applied=m["efficiency_applied"], difficulty_level=level,
                               difficulty_multiplier=m["difficulty_multiplier"], effective_production=m["effective_production"], crew_hours=m["crew_hours"],
                               worker_hours=m["worker_hours"], crew_days=m["duration_days"], loaded_per_hr=m["crew_hourly_cost"], extension=m["labor_cost"],
                               task_cost={"total": m["labor_cost"], **({"wages": float(parts["wages"]), "fringe": float(parts["fringe"]), "employer_cost": float(parts["employer_costs"])} if parts else {})})
                cands.append(row)
            tasks.append({"task_id": t["task_id"], "task": t["task"], "driver_key": t["driver_key"], "uom": t["uom"], "quantity": None if qty is None else float(qty),
                          "required_roles": list(t.get("required_roles", [])), "required_qualifications": list(t.get("required_qualifications", [])),
                          "task_default_crew": t["crew_id"], "selected_crew": sel, "crews": cands})
        out["scenarios"][sref] = {"tasks": tasks}
    return out

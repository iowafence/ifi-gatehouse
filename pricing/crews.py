"""Crew profiles, efficiency, difficulty response, suitability, selection and the crew comparison. Pure, deterministic, no model.

Per crew (human-controlled, in the rate book): role composition, hourly cost (company roles or the prevailing-wage determination),
task-specific baseline production rates, a baseline efficiency percentage (above 100 allowed), and a difficulty response multiplier
for Easy / Standard / Hard work. Different crews respond differently to difficulty.

  effective_production = baseline_production x (efficiency_pct / 100) x difficulty_response(crew, level)      [efficiency applied ONCE]
  crew_hours           = task_quantity / effective_production
  worker_hours         = crew_hours x headcount
  duration_days        = crew_hours / workday_hours      (ONE task for ONE crew; summed over tasks it is `crew_days`, effort, never calendar duration)
  task_labor_cost      = crew_hours x the crew's approved hourly cost, rounded ONCE per task (wages/fringe/employer-cost components are supporting detail and may differ from it by a cent)
  cost_per_unit        = task_labor_cost / task_quantity

Efficiency and difficulty change HOURS only. They never touch a wage, a fringe, an employer cost, a material quantity or a takeoff quantity.
A production rate marked `historical_calibrated` already reflects that crew's real performance, so efficiency is NOT applied to it again
(difficulty response still is: the job's difficulty is a separate fact). A crew is eligible for a task only if it has every required role
and qualification; no efficiency can make it eligible."""
from decimal import ROUND_HALF_UP, Decimal

LEVELS = ("easy", "standard", "hard")
CENT = Decimal("0.01")


def D(x):
    return Decimal(repr(x)) if isinstance(x, float) else Decimal(x)


def crews_by_id(rb):
    return {c["crew_id"]: c for c in rb["crews"]}


def headcount(crew):
    return sum(crew["members"].values())


def options(rb, task):
    """Priced (crew, rate) options for a task: its default Labor row first, then Crew_Production rows."""
    out = [{"crew_id": task["crew_id"], "production_rate": task["production_rate"], "rate_basis": task["rate_basis"], "is_default": True}]
    out += [{"crew_id": o["crew_id"], "production_rate": o["production_rate"], "rate_basis": o["rate_basis"], "is_default": False}
            for o in rb.get("crew_options", []) if o["task_id"] == task["task_id"]]
    return out


def job_eligibility(rb, crew_id):
    """JOB-LEVEL eligibility (owner decision 2026-10-16 4:04 PM CT): ONE crew does the whole job, so a crew is eligible only if it can perform EVERY
    labor task: it has a production rate for the task and every required role and qualification. Reasons name the task."""
    cs = crews_by_id(rb)
    crew = cs.get(crew_id)
    if crew is None:
        return {"crew_id": crew_id, "eligible": False, "reasons": [{"code": "UNKNOWN_CREW", "message": f"{crew_id} is not a crew the rate book defines"}]}
    reasons = []
    for t in rb["labor_tasks"]:
        if not any(o["crew_id"] == crew_id for o in options(rb, t)):
            reasons.append({"task_id": t["task_id"], "task": t["task"], "code": "NO_PRODUCTION_RATE", "message": f"{crew_id} has no production rate for {t['task_id']} ({t['task']})"})
        for r in reason_details(rb, t, crew):
            reasons.append({"task_id": t["task_id"], "task": t["task"], **r})
    return {"crew_id": crew_id, "eligible": not reasons, "reasons": reasons, "tasks_checked": len(rb["labor_tasks"])}


def single_crew_problems(rb, preferred_crew, assignments, use_default_for_unassigned):
    """A crew plan is ONE crew id applied to ALL tasks. Mixed plans (per-task assignments to different crews, or default-crew fallbacks) fail closed."""
    P = lambda code, msg, ref=None: {"code": code, "message": msg, **({"ref": ref} if ref else {})}
    out = []
    if not preferred_crew:
        out.append(P("CREW_PLAN_MIXED", "a crew plan names ONE crew for the whole job (preferred_crew is required); nothing is chosen per task", "preferred_crew"))
    for tid, cid in sorted((assignments or {}).items()):
        if cid != preferred_crew:
            out.append(P("CREW_PLAN_MIXED", f"task {tid} is assigned to {cid}, not the job's crew {preferred_crew}: one crew does every task", tid))
    if use_default_for_unassigned is not False:
        out.append(P("CREW_PLAN_MIXED", "use_default_for_unassigned would give each task its own default crew; a plan names ONE crew for the whole job", "use_default_for_unassigned"))
    if preferred_crew and not out:
        je = job_eligibility(rb, preferred_crew)
        if not je["eligible"]:
            out.append(P("CREW_NOT_ELIGIBLE_FOR_JOB", f"{preferred_crew} cannot perform every task: " + "; ".join(r["message"] for r in je["reasons"][:4]), preferred_crew))
    return out


def plan_required(rb):
    """A crew plan is required as soon as the book offers a choice of crews or any crew's efficiency/difficulty response is not neutral."""
    if rb.get("crew_options"):
        return True
    return any(c["efficiency_pct"] != 100 or any(v != 1 for v in c["difficulty"].values()) for c in rb["crews"])


def used_crews(rb):
    return sorted({t["crew_id"] for t in rb["labor_tasks"]} | {o["crew_id"] for o in rb.get("crew_options", [])})


def used_roles(rb):
    cs = crews_by_id(rb)
    return sorted({rk for cid in used_crews(rb) for rk in cs[cid]["members"]})


def suitability(task, crew):
    """Reasons this crew may NOT do this task. Empty = suitable. Efficiency is irrelevant here by design."""
    why = []
    missing = [r for r in task.get("required_roles", []) if r not in crew["members"]]
    if missing:
        why.append(f"crew {crew['crew_id']} lacks required role(s) {', '.join(missing)}")
    lacking = [q for q in task.get("required_qualifications", []) if q not in crew.get("qualifications", [])]
    if lacking:
        why.append(f"crew {crew['crew_id']} lacks required qualification(s) {', '.join(lacking)}")
    return why


def level_for(difficulty, driver_key):
    return (difficulty.get("overrides") or {}).get(driver_key) or difficulty["default"]


def factor(crew, option, level):
    """Everything that scales production, shown separately so nothing is applied twice or hidden."""
    eff_applied = option["rate_basis"] == "standard"
    eff = D(crew["efficiency_pct"]) / 100 if eff_applied else Decimal(1)
    diff = D(crew["difficulty"][level])
    return {"efficiency_pct": crew["efficiency_pct"], "efficiency_applied": eff_applied, "difficulty_level": level,
            "difficulty_multiplier": crew["difficulty"][level], "factor": eff * diff}


def metrics(task, option, crew, qty, level, hourly, workday):
    """All per-task, per-crew figures. `hourly` is a Decimal loaded rate or a dict with wages/fringe/employer_costs/loaded."""
    f = factor(crew, option, level)
    eff_prod = D(option["production_rate"]) * f["factor"]
    hours = qty / eff_prod
    loaded = hourly["loaded"] if isinstance(hourly, dict) else hourly
    q2 = lambda x: x.quantize(CENT, rounding=ROUND_HALF_UP)
    parts = None
    cost = q2(hours * loaded)             # ONE rounding per task: hours x loaded rate (owner decision 2026-10-16 3:28 PM CT)
    if isinstance(hourly, dict) and "wages" in hourly:       # prevailing wage: the components are supporting detail, each rounded on its own; they may differ from the cost by a cent
        parts = {k: q2(hours * hourly[k]) for k in ("wages", "fringe", "employer_costs")}
    out = {"crew_id": crew["crew_id"], "profile_version": crew["profile_version"], "rate_basis": option["rate_basis"],
           "efficiency_pct": f["efficiency_pct"], "efficiency_applied": f["efficiency_applied"], "difficulty_level": level,
           "difficulty_multiplier": f["difficulty_multiplier"], "effective_factor": float(round(f["factor"], 6)),
           "baseline_production": option["production_rate"], "effective_production": float(round(eff_prod, 6)),
           "crew_hours": float(round(hours, 6)), "worker_hours": float(round(hours * headcount(crew), 6)),
           "duration_days": float(round(hours / D(workday), 6)), "crew_hourly_cost": float(round(loaded, 4)),
           "labor_cost": float(cost), "cost_per_unit": float(round(cost / qty, 4)) if qty > 0 else None,
           "_hours": hours, "_baseline_hours": qty / D(option["production_rate"]), "_cost": cost, "_parts": parts}
    return out


def assigned_crew(plan, rb, task):
    """Crew for a task from the approved plan: explicit assignment, else the preferred crew if it is priced for the task,
    else the task's default crew only if the plan says so. None = nothing selected (never guessed)."""
    if not plan:
        return task["crew_id"]
    cid = (plan.get("assignments") or {}).get(task["task_id"])
    if cid:
        return cid
    pref = plan.get("preferred_crew")
    if pref and any(o["crew_id"] == pref for o in options(rb, task)):
        return pref
    return task["crew_id"] if plan.get("use_default_for_unassigned") else None


def plan_problems(plan, rb):
    """Problems with an approved crew plan against this rate book (also used for defence in depth inside the engine)."""
    P = lambda code, msg, ref=None: {"code": code, "message": msg, **({"ref": ref} if ref else {})}
    if not plan:
        return [P("CREW_PLAN_NOT_APPROVED", "this rate book offers crew choices or non-neutral crew efficiency; a named human must approve a crew plan", "crew_plan")]
    out, cs = [], crews_by_id(rb)
    if not isinstance(plan.get("approved_by"), str) or not plan["approved_by"].strip():
        out.append(P("CREW_PLAN_NOT_APPROVED", "the crew plan has no named approver", "crew_plan"))
    if plan.get("ratebook_labor_sha256") != rb["hashes"]["labor_sha256"]:
        out.append(P("CREW_PLAN_STALE", "the crew plan was approved against different crew profiles or production rates than this rate book carries", "crew_plan"))
    diff = plan.get("difficulty") or {}
    if diff.get("default") not in LEVELS:
        out.append(P("DIFFICULTY_INVALID", f"default difficulty must be one of {LEVELS}", "difficulty"))
    for dk, lv in (diff.get("overrides") or {}).items():
        if lv not in LEVELS:
            out.append(P("DIFFICULTY_INVALID", f"difficulty for {dk} must be one of {LEVELS}", dk))
    if diff.get("source") == "ai_recommended_human_approved" and not diff.get("evidence_refs"):
        out.append(P("DIFFICULTY_EVIDENCE_MISSING", "an AI-recommended difficulty is usable only with cited document evidence", "difficulty"))
    if diff.get("source") not in ("human", "ai_recommended_human_approved"):
        out.append(P("DIFFICULTY_INVALID", "difficulty source must be 'human' or 'ai_recommended_human_approved'", "difficulty"))
    for t in rb["labor_tasks"]:
        cid = assigned_crew(plan, rb, t)
        if cid is None:
            out.append(P("CREW_NOT_SELECTED", f"task {t['task_id']} ({t['task']}) has no crew selected; nothing is assumed", t["task_id"]))
            continue
        opt = next((o for o in options(rb, t) if o["crew_id"] == cid), None)
        if opt is None:
            out.append(P("CREW_NO_PRODUCTION_RATE", f"crew {cid} has no production rate for task {t['task_id']}", t["task_id"]))
            continue
        for why in suitability(t, cs[cid]):
            out.append(P("CREW_UNSUITABLE", f"task {t['task_id']}: {why}", t["task_id"]))
        if (plan.get("crew_profiles") or {}).get(cid) != cs[cid]["profile_version"]:
            out.append(P("CREW_PROFILE_CHANGED", f"crew {cid} is now profile {cs[cid]['profile_version']}, not the version the plan was approved against", cid))
    return out


def compare(rb, qtys, difficulty, rates, plan=None):
    """Three-crew (any number) comparison. qtys: {driver_key: Decimal quantity}; rates: {crew_id: Decimal | {loaded,...}} for crews whose
    hourly cost is established (crews missing from `rates` are shown as not calculable, never costed at a guess)."""
    cs, workday = crews_by_id(rb), rb["meta"]["workday_hours"]
    fleet = set(fleet_crew_ids(rb))
    tasks, totals = [], {}
    for t in rb["labor_tasks"]:
        qty = D(qtys[t["driver_key"]]) if qtys.get(t["driver_key"]) is not None else None
        level = level_for(difficulty, t["driver_key"])
        sel = assigned_crew(plan, rb, t) if plan else None
        cands = []
        for o in options(rb, t):
            crew = cs[o["crew_id"]]
            why = suitability(t, crew)
            c = {"crew_id": crew["crew_id"], "description": crew["description"], "profile_version": crew["profile_version"], "headcount": headcount(crew),
                 "eligible": not why, "reasons": why, "reason_details": reason_details(rb, t, crew), "in_fleet": crew["crew_id"] in fleet,
                 "calculable": False, "selected": sel == crew["crew_id"], "is_default": o["is_default"]}
            if qty is None:
                c["reasons"] = c["reasons"] + ["quantity is unresolved"]
            elif crew["crew_id"] not in rates:
                c["reasons"] = c["reasons"] + ["this crew's hourly cost is not cleared (a role has no approved wage basis)"]
            elif not why:
                m = metrics(t, o, crew, qty, level, rates[crew["crew_id"]], workday)
                tot = totals.setdefault(crew["crew_id"], {"hours": Decimal(0), "baseline": Decimal(0), "cost": Decimal(0), "workers": Decimal(0), "tasks": 0})
                tot["hours"] += m["_hours"]; tot["baseline"] += m["_baseline_hours"]; tot["cost"] += m["_cost"]
                tot["workers"] += m["_hours"] * headcount(crew); tot["tasks"] += 1
                c.update({k: v for k, v in m.items() if not k.startswith("_")})
                c["calculable"] = True
            cands.append(c)
        tasks.append({"task_id": t["task_id"], "task": t["task"], "driver_key": t["driver_key"], "uom": t["uom"],
                      "quantity": None if qty is None else float(qty), "difficulty_level": level, "selected_crew": sel, "candidates": cands})
    crews = []
    for cid in used_crews(rb):
        tot = totals.get(cid)
        crew = cs[cid]
        row = {"crew_id": cid, "description": crew["description"], "profile_version": crew["profile_version"], "headcount": headcount(crew),
               "baseline_efficiency_pct": crew["efficiency_pct"], "difficulty_response": crew["difficulty"],
               "in_fleet": cid in fleet, "tasks_total": len(rb["labor_tasks"]), "tasks_covered": tot["tasks"] if tot else 0}
        row["complete"] = row["tasks_covered"] == row["tasks_total"]
        if tot:
            row.update(effective_efficiency_pct=float(round(tot["baseline"] / tot["hours"] * 100, 4)) if tot["hours"] > 0 else None, crew_hours=float(round(tot["hours"], 6)),
                       worker_hours=float(round(tot["workers"], 6)), crew_days=float(round(tot["hours"] / D(workday), 6)), labor_cost=float(tot["cost"]))
        crews.append(row)
    return {"workday_hours": workday, "difficulty": difficulty, "tasks": tasks, "crews": crews,
            "calendar_duration": None, "calendar_duration_basis": "NOT_MODELED: crew_days is effort (crew-hours / workday), not elapsed project time; no scheduling model exists",
            "note": "Per-crew totals cover only the tasks that crew is eligible and calculable for; 'complete' says whether that is every task."}


# ---------------------------------------------------------------- Fleet overview, structured eligibility and the provisional cost average

def fleet_crew_ids(rb):
    """The selectable fleet: crews the book offers as per-task alternatives (Crew_Production rows). A book with no alternatives has one fleet:
    every crew it prices. Legacy per-task default crews (CR1..CR4) are not fleet members when alternatives exist."""
    opts = sorted({o["crew_id"] for o in rb.get("crew_options", [])})
    return opts or used_crews(rb)


def fleet_overview(rb):
    """Sidebar view: every fleet crew with its baseline efficiency, and the fleet average. A crew is NEVER dropped for lacking a qualification
    or a role; eligibility is a per-task Labor Gate question (see `eligibility`). The average is the plain mean of the stored baseline
    efficiency percentages and is for display only: it prices nothing."""
    cs = crews_by_id(rb)
    ids = fleet_crew_ids(rb)
    rows = [{"crew_id": c, "description": cs[c]["description"], "profile_version": cs[c]["profile_version"], "headcount": headcount(cs[c]),
             "efficiency_pct": cs[c]["efficiency_pct"], "qualifications": list(cs[c].get("qualifications", []))} for c in ids]
    avg = sum(D(r["efficiency_pct"]) for r in rows) / len(rows) if rows else None
    return {"crews": rows, "fleet_average_efficiency_pct": None if avg is None else float(avg),
            "fleet_average_display": None if avg is None else str(avg.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)),
            "crew_count": len(rows), "basis": "arithmetic mean of stored baseline efficiency; display only, prices nothing"}


def reason_details(rb, task, crew):
    """Structured reasons this crew may not do this task (codes, role keys and names). Same logic as `suitability`, richer output."""
    role_name = {r["role_key"]: r["role"] for r in rb["roles"]}
    why = []
    for rk in task.get("required_roles", []):
        if rk not in crew["members"]:
            why.append({"code": "MISSING_REQUIRED_ROLE", "role_key": rk, "role": role_name.get(rk, rk),
                        "message": f"{crew['crew_id']} has no {role_name.get(rk, rk)} ({rk}), which this task requires"})
    for q in task.get("required_qualifications", []):
        if q not in crew.get("qualifications", []):
            why.append({"code": "MISSING_QUALIFICATION", "qualification": q, "message": f"{crew['crew_id']} lacks required qualification {q}"})
    return why


def eligibility(rb, task_id):
    """Structured answer to 'which crews may do this task, and if not, why not' for every crew the book prices for it."""
    task = next((t for t in rb["labor_tasks"] if t["task_id"] == task_id), None)
    if task is None:
        return None
    cs = crews_by_id(rb)
    fleet = set(fleet_crew_ids(rb))
    out = []
    for o in options(rb, task):
        crew = cs[o["crew_id"]]
        why = reason_details(rb, task, crew)
        out.append({"crew_id": crew["crew_id"], "eligible": not why, "reasons": why, "production_rate": o["production_rate"],
                    "rate_basis": o["rate_basis"], "is_default": o["is_default"], "in_fleet": crew["crew_id"] in fleet})
    return {"task_id": task_id, "task": task["task"], "required_roles": list(task.get("required_roles", [])),
            "required_qualifications": list(task.get("required_qualifications", [])), "crews": out}


def provisional_labor(comparison, fleet_ids=None):
    """Indicative labor for a project with no approved crew plan, from `compare()` output. Per task: the mean of the labor COST of the crews
    that are eligible and calculable for that task (ineligible crews are excluded from this task only; efficiency percentages are never
    averaged). Not a crew assignment, not releasable, not part of any digest. A task with no eligible calculable crew has no provisional
    cost and makes the total incomplete; nothing is filled in. With `fleet_ids`, only fleet crews are averaged (legacy per-task default crews
    are not part of the selectable fleet); a task with no eligible fleet crew is incomplete, never filled from a non-fleet crew."""
    lines, total, hours, complete = [], Decimal(0), Decimal(0), True
    for t in comparison["tasks"]:
        ok = [c for c in t["candidates"] if c["eligible"] and c["calculable"] and (fleet_ids is None or c["crew_id"] in fleet_ids)]
        if not ok:
            complete = False
            lines.append({"task_id": t["task_id"], "task": t["task"], "provisional_cost": None, "provisional_crew_hours": None, "eligible_crews": [],
                          "excluded": [{"crew_id": c["crew_id"], "reasons": c["reasons"]} for c in t["candidates"]]})
            continue
        n = len(ok)
        cost = (sum(D(repr(c["labor_cost"])) for c in ok) / n).quantize(CENT, rounding=ROUND_HALF_UP)
        hrs = sum(D(repr(c["crew_hours"])) for c in ok) / n
        total += cost
        hours += hrs
        lines.append({"task_id": t["task_id"], "task": t["task"], "provisional_cost": float(cost), "provisional_crew_hours": float(round(hrs, 6)),
                      "eligible_crews": [c["crew_id"] for c in ok],
                      "excluded": [{"crew_id": c["crew_id"], "reasons": c["reasons"]} for c in t["candidates"] if c not in ok]})
    return {"provisional": True, "releasable": False, "complete": complete, "basis": "mean labor cost of task-eligible crews",
            "difficulty_level_default": comparison["difficulty"]["default"], "lines": lines,
            "provisional_labor_cost": float(total) if complete else None, "provisional_crew_hours": float(round(hours, 6)) if complete else None}

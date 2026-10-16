"""HTTP-integration helpers between the demo API and ANVIL 2's pricing engine (pricing/*, engine/workflow.py).

Everything numeric is computed here or in pricing/* with Decimal; the browser only displays and selects.
Nothing in this module changes workflow state except through engine.workflow functions called by api/server.py.

  load_book()          the FICTIONAL reference rate book v2.3.0 (samples/public-demo/reference_pricing_workbook_v2_3_0.fictional.xlsx, hash-pinned), validated by the hardened importer
  view(state)          additive, rate-book-safe fields for GET /projects/{id} (no raw book, no hashes of the file)
  preview(state, d)    what-if for a DRAFT crew plan: no state change, no audit entry, no approval; same pure functions the engine prices with
  economics(est)       gross / projected net profit derived from the engine's own estimate lines (never from the browser)
"""
import copy
import datetime
import hashlib
import json
import pathlib
import re
from decimal import Decimal, ROUND_HALF_UP

from pricing import crews as pcrews
from pricing import prevailing as pprev
from . import bid_schedule
from . import pricing_service as svc
from . import ratebook_mode as rm
from . import workflow as wf

ROOT = pathlib.Path(__file__).resolve().parent.parent
# The authoritative FICTIONAL reference rate book v2.3.0 from ANVIL 2 (pinned by content hash; any other file is refused).
BOOK_PATH = ROOT / "samples/public-demo/reference_pricing_workbook_v2_3_0.fictional.xlsx"
BOOK_SHA256 = "3d43120473c8db3840557d62397e5f4fc5669b7f2b3cf5a0c86005fc88dde8f1"
# Generic synthetic pricing fixture: a LOCAL INTEGRATION TEST scope only. It does not replace, and must not be mistaken for, the DP-001
# document-intelligence scenario (G2 addendum conflict, unresolved G3, Base vs Alternate A-1, post-spacing rules, Davis-Bacon).
SCOPE_PATH = ROOT / "samples/scope_generic_synthetic_pricing.json"
POLICY = {"allowed_ratebook_classes": ["FICTIONAL_DEMO"]}


class AdapterRefusal(Exception):
    """A refusal made by the HTTP adapter layer (not the engine): carries a stable code and HTTP status. Raised BEFORE any engine state change."""

    def __init__(self, status, code, message, details=None):
        super().__init__(message)
        self.status, self.code, self.details = status, code, details or []


def fleet_ids(rb):
    """Active fleet crew ids, authoritative from the engine's pricing_service.fleet_overview (never a hard-coded list)."""
    return [c["crew_id"] for c in svc.fleet_overview(rb)["crews"]]


def max_assignments(rb):
    """A plan can assign each labor task at most once, so more entries than tasks is malformed by construction."""
    return len(rb["labor_tasks"])


def crew_plan_precheck(state, body):
    """Adapter-level enforcement run BEFORE the engine decision (and by preview): fleet membership is validated separately from task
    qualification (the engine still validates qualification, rates and wages). Raises AdapterRefusal; never touches `state`."""
    rb = state["ratebook"]
    asg = body.get("assignments") or {}
    if not isinstance(asg, dict):
        raise ValueError("assignments must be an object of task_id: crew_id")
    if len(asg) > max_assignments(rb):
        raise AdapterRefusal(400, "TOO_MANY_ASSIGNMENTS", f"a plan has at most {max_assignments(rb)} task assignments")
    fleet = set(fleet_ids(rb))
    refs = ([("preferred_crew", body["preferred_crew"])] if body.get("preferred_crew") is not None else []) + sorted(asg.items())
    bad = [{"ref": k, "crew_id": v} for k, v in refs if isinstance(v, str) and v not in fleet]
    if bad:
        raise AdapterRefusal(409, "CREW_NOT_IN_FLEET", "only active fleet crews can be selected: " + ", ".join(f"{b['ref']}={b['crew_id']}" for b in bad), bad)


def selected_outside_fleet(rb, comparison):
    """Crews a (draft or dry-run) plan would actually use, per task, that are not fleet crews (catches use_default_for_unassigned fallbacks)."""
    fleet = set(fleet_ids(rb))
    out = []
    for cmp_ in comparison.values():
        for t in cmp_["tasks"]:
            if t.get("selected_crew") and t["selected_crew"] not in fleet:
                out.append({"ref": t["task_id"], "crew_id": t["selected_crew"]})
    return out


def dry_run_selected_outside_fleet(state, body):
    """Apply the decision to a private deep copy and report non-fleet crews it would select. Only needed when defaults can fill gaps."""
    work = copy.deepcopy(state)
    svc.adopt_crew_plan(work, by=body.get("by"), note=body.get("note"), preferred_crew=body.get("preferred_crew"), assignments=body.get("assignments"),
                        use_default_for_unassigned=body.get("use_default_for_unassigned", False), difficulty=body.get("difficulty"))
    return selected_outside_fleet(state["ratebook"], svc.compare_crews(work))
COST_KEYS = ("labor_cost", "cost_per_unit", "crew_hourly_cost")


def D(x):
    return Decimal(repr(x)) if isinstance(x, float) else Decimal(x)


def money(x):
    return float(D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def load_book(path=BOOK_PATH, as_of=None):
    """Validated rate book. Raises on any problem; the caller treats that as 'pricing unavailable' (fail closed)."""
    import hashlib
    with open(path, "rb") as fh:
        data = fh.read()
    if hashlib.sha256(data).hexdigest() != BOOK_SHA256:
        raise ValueError("rate book is not the pinned reference workbook")
    return svc.import_ratebook(data, as_of=as_of or datetime.date.today())["ratebook"]


def short_name(crew):
    """Display label only ('Crew 1'); the stable identifier is crew_id (CR11). The book's description reads 'Crew 1: foreman + 2 laborers'."""
    return crew["description"].split(":")[0].strip()


def crew_roster(rb):
    """Sidebar roster straight from the engine's fleet_overview: fleet crews only, unweighted average of stored baseline efficiency."""
    fo = svc.fleet_overview(rb)
    roles = {r["role_key"]: r["role"] for r in rb["roles"]}
    cs = pcrews.crews_by_id(rb)
    out = []
    for f in fo["crews"]:
        c = cs[f["crew_id"]]
        comp = [{"role": roles.get(rk, rk), "qualifications": []} for rk, n in sorted(c["members"].items()) for _ in range(n)]
        out.append({"crew_id": c["crew_id"], "name": short_name(c), "detail": c["description"], "efficiency_pct": c["efficiency_pct"], "composition": comp,
                    "qualifications": list(f.get("qualifications", [])), "profile_version": c["profile_version"], "difficulty_response": dict(c["difficulty"])})
    return {"fictional": True, "source": "rate book (Crews sheet) via pricing_service.fleet_overview", "fleet_average_pct": float(fo["fleet_average_display"]),
            "fleet_average_exact_pct": fo["fleet_average_efficiency_pct"], "crew_count": fo["crew_count"], "basis": fo["basis"], "crews": out}


def economics(est):
    """Derived from the engine's estimate lines. Gross profit = price - direct cost. Projected net profit = gross profit - overhead - contingency
    (equal to the engine's profit line). Estimated at bid; not a realized margin."""
    head = est["scenarios"][est["headline_scope_ref"]]
    price, direct = D(head["price_total"]), D(head["direct_cost"])
    gross = price - direct
    net = gross - D(head["overhead"]["amount"]) - D(head["contingency"]["amount"])
    pct = lambda n: float((n / price * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)) if price > 0 else None
    return {"scope_ref": est["headline_scope_ref"], "price_total": money(price), "direct_cost": money(direct), "gross_profit": money(gross),
            "gross_margin_pct": pct(gross), "net_profit": money(net), "net_margin_pct": pct(net),
            "basis": "estimated at bid from the engine's markup lines (overhead, contingency); not realized profit",
            "labels": {"gross_profit": "Estimated gross profit (price - direct cost), at bid",
                       "net_profit": "Projected net profit (gross profit - overhead - contingency), estimated at bid"},
            "realized": False,
            "contingency_note": "Contingency is a risk reserve priced into the bid. Projected net profit deducts it for projection only; it does not mean contingency was spent.",
            "terminology_status": "AWAITING_JORDAN_BUSINESS_APPROVAL"}


def humanize(rb, text):
    """Show crew and role NAMES instead of rate-book ids in an engine reason (Crew 1, Drill operator). Wording is otherwise the engine's own."""
    names = {c["crew_id"]: short_name(c) for c in rb["crews"]} | {r["role_key"]: r["role"] for r in rb["roles"]}
    text = re.sub(r"\bcrew (CR\d+)\b", lambda m: names.get(m.group(1), m.group(0)), text)
    return re.sub(r"\b(CR\d+|R\d+)\b", lambda m: names.get(m.group(1), m.group(1)), text)


def _decorate(rb, comparison):
    """Display fields. `reasons_display` is ONLY why the crew is ineligible: the engine's own structured `reason_details` messages, verbatim.
    Anything else the engine appended (e.g. a wage basis not yet cleared) goes to `cost_note`. Only fleet crews are shown."""
    crews = pcrews.crews_by_id(rb)
    for t in comparison["tasks"]:
        t["candidates"] = [c for c in t["candidates"] if c.get("in_fleet")]
        for c in t["candidates"]:
            details = c.get("reason_details") or []
            c["reasons_display"] = [d["message"] for d in details]
            c["cost_note"] = [humanize(rb, r) for r in c["reasons"] if "not cleared" in r]
            c["name"] = short_name(crews[c["crew_id"]])
            c.setdefault("efficiency_pct", crews[c["crew_id"]]["efficiency_pct"])
    comparison["crews"] = [r for r in comparison["crews"] if r.get("in_fleet")]
    return comparison


def _strip_costs(node):
    if isinstance(node, dict):
        return {k: _strip_costs(v) for k, v in node.items() if k not in COST_KEYS}
    if isinstance(node, list):
        return [_strip_costs(v) for v in node]
    return node


def _drivers(payload):
    return {i["driver_key"]: i["quantity"] for i in payload["items"] if "driver_key" in i}


def productivity_only(state, difficulty=None, plan=None):
    """Hours, worker-hours and duration with NO cost: used while wages are unresolved. Hours do not depend on any wage; money is withheld."""
    rb = state["ratebook"]
    diff = difficulty or {"default": "standard", "overrides": {}}
    zero = {cid: Decimal(0) for cid in pcrews.used_crews(rb)}
    out = {}
    for sref, payload in (state.get("quantities") or {}).items():
        out[sref] = _strip_costs(pcrews.compare(rb, _drivers(payload), diff, zero, plan))
    return out


def _comparison(state, plan=None):
    """Engine comparison (pricing_service.compare_crews) for the approved plan, or for a DRAFT plan evaluated on a private copy of the state.
    Costs appear only for crews whose hourly cost is established (cleared wage determination); hours-only figures fill the gap, never a cost."""
    rb = state["ratebook"]
    if plan is not None and plan is not state.get("crew_plan"):
        work = copy.deepcopy(state)
        work["crew_plan"] = plan
        work["crew_comparison"] = rm.crew_comparison(work)
    else:
        work = state
    out = copy.deepcopy(svc.compare_crews(work))
    uncleared = len(rm.crew_rates(work)) < len(pcrews.used_crews(rb))
    for sref, full in out.items():
        if uncleared:
            diff = plan["difficulty"] if plan else {"default": "standard", "overrides": {}}
            payload = work["quantities"][sref]
            hours = pcrews.compare(rb, _drivers(payload), diff, {c: Decimal(0) for c in pcrews.used_crews(rb)}, plan)
            for t_full, t_h in zip(full["tasks"], hours["tasks"]):
                for c_full, c_h in zip(t_full["candidates"], t_h["candidates"]):
                    if not c_full["calculable"] and c_h["calculable"]:
                        c_full.update({k: v for k, v in _strip_costs(c_h).items() if k not in c_full or c_full[k] is None})
                        c_full["hours_only"] = True
            for r_full, r_h in zip(full["crews"], hours["crews"]):
                if "labor_cost" not in r_full and "crew_hours" in r_h:
                    r_full.update({k: v for k, v in _strip_costs(r_h).items() if k not in r_full})
                    r_full["hours_only"] = True
        _decorate(rb, full)
        full["difficulty_approved"] = bool(plan) and plan.get("approved_by") != "(draft)"
    return out


def _crew_days(labor):
    """Total crew-days (effort = crew-hours / workday). ANVIL 2's engine renamed the aggregate `duration_days` to `crew_days` because summed
    task durations are not calendar time; accept either name so the demo layer survives that change."""
    return labor["crew_days"] if "crew_days" in labor else labor["duration_days"]


def _qualification_text(q):
    t = q.get("type")
    if t == "human_scope_assumption":
        return f"Scope assumption by {q['by']}: {q['value']!r} entered for an unresolved fact ({q['note']})"
    if t == "quantity_ruleset_approved":
        return f"Quantity ruleset {q['ruleset_id']} v{q['version']} approved by {q['by']}"
    if t == "crew_plan_approved":
        return f"Crew plan v{q['plan_version']} approved by {q['by']} (difficulty source: {q['difficulty_source']})"
    return q.get("note") or t


def estimate_view(state):
    """Display shape of the headline scenario, taken straight from the engine's estimate; no arithmetic here except labelling."""
    est = state["estimate"]
    head = est["scenarios"][est["headline_scope_ref"]]
    cs = pcrews.crews_by_id(state["ratebook"])
    breakdown = [("materials", "Materials", head["materials"]["subtotal"]), ("services", "Services (core drilling)", head["services"]["subtotal"]),
                 ("labor", "Labor", head["labor"]["subtotal"]), ("equipment", "Equipment", head["equipment"]["subtotal"]),
                 ("mobilization", "Mobilization", head["mobilization"]["subtotal"])]
    admin = head["labor"].get("certified_payroll_admin")
    if admin:
        breakdown.insert(3, ("certified_payroll", "Certified payroll administration", admin["extended"]))
    breakdown.append(("sales_tax", "Sales tax" + (" (owner exempt)" if head["sales_tax"]["exemption_applies"] else ""), head["sales_tax"]["amount"]))
    breakdown += [("direct_cost", "Direct cost", head["direct_cost"]), ("overhead", "Overhead", head["overhead"]["amount"]),
                  ("contingency", "Contingency", head["contingency"]["amount"]), ("profit", "Profit", head["profit"]["amount"]),
                  ("price_total", "Total estimate", head["price_total"])]
    lines = [{k: l.get(k) for k in ("task_id", "task", "uom", "quantity", "crew_id", "efficiency_pct", "difficulty_level", "effective_production",
                                    "crew_hours", "worker_hours", "duration_days", "extended")} | {"crew_name": cs[l["crew_id"]]["description"]}
             for l in head["labor"]["lines"]]
    return {"scope_ref": est["headline_scope_ref"], "price_total": est["price_total"], "price_per_lf": head["price_per_lf"], "fence_lf": head["fence_lf"],
            "breakdown": [{"key": k, "label": a, "amount": b} for k, a, b in breakdown], "labor_lines": lines,
            "labor_totals": {"crew_hours": head["labor"]["crew_hours"], "worker_hours": head["labor"]["worker_hours"], "crew_days": _crew_days(head["labor"])},
            "alternates": [{"scope_ref": k, "price_total": v["price_total"]} for k, v in est["scenarios"].items() if k != est["headline_scope_ref"]],
            "qualifications": _unique(_qualification_text(q) for q in wf.qualifications(state)) + [q["note"] for q in head.get("qualifications", []) if q.get("type") != "human_resolution" and q.get("note")],
            "advisories": [a["message"] for a in head.get("advisories", [])]}


def _unique(items):
    seen, out = set(), []
    for i in items:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def wage_view(state):
    if not rm.wage_required(state):
        return {"required": False}
    wd = state.get("wage_determination")
    blockers = [e["code"] for e in state["exceptions"] if e["code"].startswith(("WAGE_", "CLASSIFICATION_", "CERTIFIED_"))]
    names = {r["role_key"]: r["role"] for r in state["ratebook"]["roles"]}
    return {"required": True, "roles": rm.labor_roles(state), "role_names": {k: names.get(k, k) for k in rm.labor_roles(state)}, "recorded": bool(wd), "blockers": blockers,
            "decision": ({k: wd["determination"][k] for k in ("decision_id", "modification")} | {"recorded_by": wd["recorded_by"]}) if wd else None,
            "cleared": bool(wd) and not blockers,
            "role_classifications": _role_classifications(state, wd),
            "employer_burden": ({"pct": wd["employer_burden"].get("pct"), "source_ref": wd["employer_burden"].get("source_ref")} if wd and isinstance(wd.get("employer_burden"), dict) else None)}


def _role_classifications(state, wd):
    """Read-only: per cost-bearing role, the classification and rates a named person recorded, whether the role is cleared, its problems,
    and the figures the engine prices with (wages, fringe, employer cost on wages, loaded rate = wages + fringe + employer cost). Nothing is
    chosen here: a role with no recorded row shows nulls, never a default."""
    roles = rm.labor_roles(state)
    names = {r["role_key"]: r["role"] for r in state["ratebook"]["roles"]}
    rows = {r.get("role_key"): r for r in (wd or {}).get("rows", []) if isinstance(r, dict)}
    ev = pprev.evaluate(wd, roles, rm.as_of(state)) if wd else {"supported": {}, "role_problems": {}}
    out = []
    for rk in roles:
        r, sup = rows.get(rk) or {}, ev["supported"].get(rk)
        out.append({"role_key": rk, "role": names.get(rk, rk), "classification": r.get("classification"), "classification_status": r.get("classification_status"),
                    "conformance_ref": r.get("conformance_ref"), "base_rate": r.get("base_rate"), "fringe_rate": r.get("fringe_rate"), "source_ref": r.get("source_ref"),
                    "cleared": sup is not None, "problems": [p["code"] for p in ev["role_problems"].get(rk, [])],
                    "decision_base_rate": float(sup["decision_base"]) if sup and sup.get("decision_base") is not None else None,
                    "decision_fringe_rate": float(sup["decision_fringe"]) if sup and sup.get("decision_fringe") is not None else None,
                    "above_decision": bool(sup and sup.get("above_decision")),
                    "priced": ({k: float(sup[k]) for k in ("wages", "fringe", "employer_costs", "loaded")} if sup else None)})
    return out


def provisional_view(state):
    """Informational only: per task, the mean cost of FLEET crews that are eligible for that task and have a cleared wage basis. Never a plan,
    never releasable, never in a digest. A task nobody can do has no cost and the total is null (the estimate is incomplete)."""
    pl = svc.provisional_labor(state).get("BASE")
    if not pl:
        return None
    names = {c["crew_id"]: short_name(c) for c in state["ratebook"]["crews"]}
    fleet = set(pcrews.fleet_crew_ids(state["ratebook"]))
    return {"scope_ref": "BASE", "provisional": True, "releasable": False, "complete": pl["complete"], "basis": pl["basis"],
            "provisional_labor_cost": pl["provisional_labor_cost"], "provisional_crew_hours": pl["provisional_crew_hours"],
            "lines": [{"task_id": l["task_id"], "task": l["task"], "provisional_cost": l["provisional_cost"],
                       "eligible_crews": [{"crew_id": c, "name": names[c]} for c in l["eligible_crews"] if c in fleet]} for l in pl["lines"]]}


def footing_view(state):
    """footing-scope.v1 summary per scenario: the per-class schedule, its release posture and the KNOWN subtotal (never an estimate). Read straight from the
    deterministic schedule; no arithmetic here. Absent for a project without a footing scope."""
    out = {}
    for sref, sch in sorted((state.get("footing_schedule") or {}).items()):
        if not sch:
            out[sref] = None
            continue
        part = (state.get("footing_partial") or {}).get(sref)
        out[sref] = {"contract_version": sch["contract_version"], "calc_version": sch["calc_version"], "schedule_sha256": sch["schedule_sha256"],
                     "calc_inputs_sha256": sch["calc_inputs_sha256"], "measurement_convention": sch["measurement_convention"], "posture": sch["posture"],
                     "totals": sch["totals"], "classes": sch["classes"], "records": sch["records"], "runs": sch["runs"], "reconciliation": sch["reconciliation"],
                     "partial_cost": part, "priced": state.get("estimate") is not None}
    return out


def view(state):
    """Additive summary fields for a rate-book-mode project. None for a legacy-mode project."""
    rb = state.get("ratebook")
    if not rb:
        return None
    out = _view(state, rb)
    if state.get("footing_schedule") is not None:
        out["footing"] = footing_view(state)
    out["bid_schedule"] = bid_schedule.view(state)
    return out


def _view(state, rb):
    rr = state.get("ratebook_ref") or {}
    plan = state.get("crew_plan")
    priced = state.get("estimate") is not None
    return {
        "mode": "ratebook",
        "ratebook_ref": {k: rr.get(k) for k in ("ratebook_id", "version", "effective_date")} | {"classification": rb["meta"].get("data_classification")},
        "ruleset": {"ruleset_id": state["ruleset"]["ruleset_id"], "version": state["ruleset"]["version"], "sha256": state["ruleset"]["sha256"],
                    "status": state["ruleset"]["rules"].get("status") if isinstance(state["ruleset"].get("rules"), dict) else None,
                    "approved": bool(state.get("ruleset_approval")),
                    "approved_by": (state.get("ruleset_approval") or {}).get("by"),
                    # The contractor has NOT approved the quantity rules. A demo visitor's self-declared approval is synthetic and never changes this.
                    "contractor_approved": False,
                    "contractor_note": "Contractor approval of the fitting and quantity rules is outstanding. Any approval recorded in this demo is a self-declared, fictional visitor action."},
        "crews": crew_roster(rb),
        "crew_plan": ({k: plan[k] for k in ("plan_version", "preferred_crew", "assignments", "use_default_for_unassigned", "difficulty", "approved_by", "note", "approved_utc")}
                      if plan else None),
        "crew_comparison": _comparison(state, plan) if state.get("quantities") else None,
        "wage": wage_view(state),
        "economics": economics(state["estimate"]) if priced else None,
        "estimate_view": estimate_view(state) if priced else None,
        "pricing_blocked_by": sorted({e["code"] for e in state["exceptions"] if e["severity"] == "blocking" and e.get("blocks_stage") != "scope"}) if not priced else [],
        "history_count": len(state.get("history") or []),
        "contract_version": svc.CONTRACT_VERSION,
        "plan_history": [{k: p.get(k) for k in ("plan_version", "preferred_crew", "assignments", "approved_by", "retired_reason")} | {"difficulty_default": p["difficulty"]["default"]}
                         for p in svc.crew_plan_history(state)],
        "provisional": provisional_view(state) if not plan and state.get("quantities") else None,
    }


def _draft(state, body):
    """Normalise a draft crew plan the same way workflow.approve_crew_plan builds an approved one, but unapproved and unlogged."""
    rb = state["ratebook"]
    if not isinstance(body, dict):
        raise ValueError("body must be an object")
    extra = set(body) - {"preferred_crew", "assignments", "use_default_for_unassigned", "difficulty"}
    if extra:
        raise ValueError(f"unknown fields: {sorted(extra)}")
    cs = pcrews.crews_by_id(rb)
    asg = body.get("assignments") or {}
    if not isinstance(asg, dict) or len(asg) > max_assignments(rb):
        raise ValueError("assignments must be an object of task_id: crew_id (at most one per labor task)")
    tasks = {t["task_id"] for t in rb["labor_tasks"]}
    if any(not isinstance(k, str) or k not in tasks or not isinstance(v, str) or v not in cs for k, v in asg.items()):
        raise ValueError("assignments must map labor task ids to crews defined in the rate book")
    pref = body.get("preferred_crew")
    if pref is not None and pref not in pcrews.used_crews(rb):
        raise ValueError("preferred_crew is not a crew the rate book prices")
    use_default = body.get("use_default_for_unassigned", False)
    if not isinstance(use_default, bool):
        raise ValueError("use_default_for_unassigned must be true or false")
    d = body.get("difficulty")
    if not isinstance(d, dict):
        raise ValueError("difficulty is required")
    ov = d.get("overrides") or {}
    if not isinstance(ov, dict):
        raise ValueError("difficulty overrides must be an object")
    diff = {"default": d.get("default"), "overrides": dict(ov), "source": "human", "evidence_refs": []}
    return {"plan_version": 0, "preferred_crew": pref, "assignments": dict(asg), "use_default_for_unassigned": use_default, "difficulty": diff,
            "approved_by": "(draft)", "note": "", "approved_utc": None, "scope_version": state["scope"]["scope_version"],
            "ratebook_labor_sha256": rm.labor_hash(state), "crew_profiles": {cid: cs[cid]["profile_version"] for cid in pcrews.used_crews(rb)}}


def preview(state, body):
    """What-if for a draft plan. Mutates nothing. Returns the plan's problems (exact reasons), the comparison at the draft difficulty, and, when
    the plan is valid and labor compliance is cleared, the total estimate and profit the engine WOULD produce. Never an approval."""
    from pricing import vocab
    rb = state.get("ratebook")
    if not rb or not state.get("quantities"):
        raise ValueError("the Scope Gate must be clear before crews can be compared")
    plan = _draft(state, body)
    problems = pcrews.plan_problems(plan, rb)
    # plan_problems always reports the draft as unapproved; that is the point of a preview, so it is not a defect to show
    problems = [p for p in problems if p["code"] != "CREW_PLAN_NOT_APPROVED"]
    if any(k not in vocab.DRIVERS for k in plan["difficulty"]["overrides"]):
        problems.append({"code": "DIFFICULTY_INVALID", "message": "difficulty overrides are keyed by labor driver D01-D12", "ref": "difficulty"})
    for p in problems:
        p["message_display"] = humanize(rb, p["message"]).replace("_", " ")
    out = {"draft": True, "problems": problems, "valid": not problems, "estimate": None, "economics": None, "pricing_blocked_by": [], "comparison": None}
    try:
        crew_plan_precheck(state, plan)
    except AdapterRefusal as r:
        problems += [{"code": r.code, "message": f"{d['ref']}: crew {d['crew_id']} is not an active fleet crew", "ref": d["ref"], "message_display": ""} for d in r.details]
    if not [p for p in problems if p["code"] == "DIFFICULTY_INVALID"]:
        out["comparison"] = _comparison(state, plan)
        for d in selected_outside_fleet(rb, out["comparison"]):
            if not any(p["code"] == "CREW_NOT_IN_FLEET" and p["ref"] == d["ref"] for p in problems):
                problems.append({"code": "CREW_NOT_IN_FLEET", "message": f"task {d['ref']}: crew {d['crew_id']} is not an active fleet crew (default fallback)", "ref": d["ref"]})
    for p_ in problems:
        p_.setdefault("message_display", humanize(rb, p_["message"]).replace("_", " "))
        p_["message_display"] = p_["message_display"] or humanize(rb, p_["message"]).replace("_", " ")
    out["valid"] = not problems
    out["pricing_blocked_by"] = sorted(e["code"] for e in state["exceptions"] if e["severity"] == "blocking" and e["code"] != "CREW_PLAN_REQUIRED")
    lr = state.get("labor_review") or {}
    if not problems and lr.get("status") == "decided" and not out["pricing_blocked_by"]:
        tmp = copy.deepcopy(state)
        tmp["crew_plan"] = plan
        est = rm.estimate(tmp)
        head = est["scenarios"][est["headline_scope_ref"]]
        out["estimate"] = {"scope_ref": est["headline_scope_ref"], "price_total": est["price_total"], "direct_cost": head["direct_cost"],
                           "labor_subtotal": head["labor"]["subtotal"], "crew_hours": head["labor"]["crew_hours"],
                           "worker_hours": head["labor"]["worker_hours"], "crew_days": _crew_days(head["labor"])}
        out["economics"] = economics(est)
    return out


def _modkey(x):
    """Statutory modification as a comparable key: a whole number when parseable, else the raw text (the engine refuses malformed ones itself)."""
    try:
        return int(str(x))
    except ValueError:
        return None


WAGE_IDENTITY_VERSION = "wage-content-identity-v2"        # v2 = v1 + ambiguity rejection (duplicate role / classification keys have NO identity)
LEGACY_IDENTITY_SPECS = ("wage-content-identity-v1",)       # already-committed v1 identities stay valid ONLY for live records that are unambiguous
_DET_KEYS = ("decision_id", "modification", "date", "valid_through", "source_ref")
_SCHED_KEYS = ("classification", "base_rate", "fringe_rate")
_ROW_KEYS = ("role_key", "classification", "classification_status", "conformance_ref", "base_rate", "fringe_rate", "source_ref")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class WageAmbiguity(ValueError):
    """Wage content whose meaning depends on row order (duplicate role keys or duplicate schedule classifications). It gets no identity."""


def wage_ambiguities(schedule, rows):
    """Role-key uniqueness rule, defined by pricing/prevailing.py's actual matching semantics (read, not invented):
      * rows are matched to cost-bearing roles by EXACT string equality of `role_key` (`r.get("role_key") in per_role`, first row wins, later rows for the
        same key are reported as unknown): so no two rows may have the same `role_key` string. No case-folding, trimming or aliasing is applied (the evaluator
        applies none: 'R1' and 'r1' are different keys, and 'r1' is simply an unknown role the evaluator flags).
      * the schedule is keyed by `classification.strip().lower()` (last duplicate silently wins in the evaluator's dict): no two schedule entries may share
        that normalized key.
    Applies even when duplicate entries carry identical values. Returns [(code, key)]; empty means unambiguous."""
    out, seen = [], set()
    for r in rows if isinstance(rows, list) else []:
        k = r.get("role_key") if isinstance(r, dict) else None
        if isinstance(k, str):
            if k in seen:
                out.append(("WAGE_ROW_DUPLICATE_ROLE", k))
            seen.add(k)
    seen = set()
    for x in schedule if isinstance(schedule, list) else []:
        c = x.get("classification") if isinstance(x, dict) else None
        if isinstance(c, str) and c.strip():
            k = c.strip().lower()
            if k in seen:
                out.append(("WAGE_SCHEDULE_DUPLICATE_CLASSIFICATION", k))
            seen.add(k)
    return out


def _canon_val(x):
    """Deterministic, type-tagged canonical form of a JSON value. Numbers are exact decimals (24, 24.0 and 24.00 are one value); bool is not a number;
    NaN/inf and any non-JSON type are errors (ValueError), never silently coerced."""
    if x is None or isinstance(x, (str, bool)):
        return x
    if isinstance(x, (int, float)):
        d = Decimal(repr(x))
        if not d.is_finite():
            raise ValueError("non-finite number")
        return {"n": format(d.normalize(), "f")}
    if isinstance(x, list):
        return [_canon_val(v) for v in x]
    if isinstance(x, dict):
        if not all(isinstance(k, str) for k in x):
            raise ValueError("non-string key")
        return {k: _canon_val(x[k]) for k in sorted(x)}
    raise ValueError(f"unsupported type {type(x).__name__}")


def _project(d, keys):
    if not isinstance(d, dict):
        raise ValueError("expected an object")
    return {k: _canon_val(d.get(k)) for k in keys}


def _sorted_unique_order(items):
    """Order-independent but multiplicity-preserving: elements sorted by their own canonical JSON."""
    return sorted(items, key=lambda i: json.dumps(i, sort_keys=True, separators=(",", ":"), allow_nan=False))


def wage_content_identity(determination, schedule, rows, employer_burden, production_rates_approved, certified_payroll_admin, spec=None):
    """CANONICAL CONTENT IDENTITY of a wage determination (spec `wage-content-identity-v1`), as sha256 hex. Included (every input that can affect clearance,
    labor compliance or pricing): determination{decision_id, modification (as text), date, valid_through, source_ref}; schedule[{classification, base_rate,
    fringe_rate}]; rows[{role_key, classification, classification_status, conformance_ref, base_rate, fringe_rate, source_ref}]; employer_burden (ALL keys:
    pct, source_ref, anything else the engine retained); production_rates_approved; certified_payroll_admin (ALL keys). Lists schedule and rows are order
    independent; unknown keys inside determination/schedule/rows are dropped exactly as the engine drops them. EXCLUDED (observation/derived/binding
    metadata, not content): recorded_by, note, recorded_utc, scope_version, ratebook_labor_sha256, blockers, cleared, display fields, computed rates.
    Raises ValueError on anything malformed, which callers treat as 'no identity' and fail closed."""
    spec = spec or WAGE_IDENTITY_VERSION
    if spec not in (WAGE_IDENTITY_VERSION, *LEGACY_IDENTITY_SPECS):
        raise ValueError("unknown identity spec")
    if not isinstance(schedule, list) or not isinstance(rows, list):
        raise ValueError("schedule and rows must be lists")
    amb = wage_ambiguities(schedule, rows)
    if amb:                                                         # ambiguous content has no identity: it can never be 'equivalent' to anything
        raise WageAmbiguity("ambiguous wage content: " + ", ".join(f"{c}({k})" for c, k in amb))
    det = _project(determination, _DET_KEYS)
    det["modification"] = None if det["modification"] is None else str(determination.get("modification"))
    obj = {"spec": spec, "determination": det,
           "schedule": _sorted_unique_order([_project(x, _SCHED_KEYS) for x in schedule]),
           "rows": _sorted_unique_order([_project(x, _ROW_KEYS) for x in rows]),
           "employer_burden": _canon_val(employer_burden), "production_rates_approved": _canon_val(production_rates_approved),
           "certified_payroll_admin": _canon_val(certified_payroll_admin)}
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def wage_identity_from_request(body):
    return wage_content_identity(body.get("determination"), body.get("schedule"), body.get("rows"), body.get("employer_burden"),
                                 body.get("production_rates_approved"), body.get("certified_payroll_admin"))


def wage_identity_from_state(state, spec=None):
    """Identity of the engine's LIVE wage record (read-only access to the stored record; no engine function exposes its content)."""
    wd = state.get("wage_determination")
    if not isinstance(wd, dict):
        raise ValueError("no live wage record")
    return wage_content_identity(wd.get("determination"), wd.get("schedule"), wd.get("rows"), wd.get("employer_burden"),
                                 wd.get("production_rates_approved"), wd.get("certified_payroll_admin"), spec)


def wage_validate_unambiguous(body):
    """Run FIRST in the wage decision path, before any guard, identity commitment or engine call. Rejects duplicate role / classification keys with a
    specific stable code and never repairs, merges or picks a row."""
    amb = wage_ambiguities(body.get("schedule"), body.get("rows"))
    if amb:
        code = amb[0][0]
        raise AdapterRefusal(400, code, "ambiguous wage data rejected: " + "; ".join(f"{c} for {k!r}" for c, k in amb) +
                             ". Each role_key may appear in at most one row and each schedule classification (trimmed, case-insensitive) at most once; "
                             "nothing was recorded.", [{"code": c, "key": k} for c, k in amb])


def _untrust(hist, reason, audit_len):
    """Monotonic: once a project's wage history is untrusted it stays untrusted. The reason is appended, never replaced."""
    hist["complete"] = False
    hist["incomplete_reason"] = hist["incomplete_reason"] or reason
    hist.setdefault("incomplete_events", []).append({"after_audit_event": audit_len, "reason": reason})


def wage_history_new(audit_len):
    """Server-side, append-only wage history for ONE project, created by the adapter when the project is created (so it is complete from the start).
    Flags are MONOTONIC (False -> True only); records are only appended; nothing resets them: not plan invalidation, wage edits, rate-book or scope
    changes, voiding by the engine, or session transitions. It is dropped only together with the project itself."""
    return {"complete": True, "incomplete_reason": None, "incomplete_events": [], "created_after_audit_event": audit_len, "records": []}


def wage_history_append(hist, body, content_sha256, by, audit_event_id, state):
    """Append-only: called after the engine ACCEPTED the decision. The committed identity is computed from the engine's LIVE record (what it really stored)
    and must equal the identity of the request; any difference, or any failure to compute either, leaves the project's history untrusted (fail closed)."""
    d = body.get("determination") if isinstance(body.get("determination"), dict) else {}
    committed = None
    try:
        committed = wage_identity_from_state(state)
        if committed != wage_identity_from_request(body):
            _untrust(hist, "the engine stored different wage content than the accepted request", len(state["audit"]))
    except ValueError:
        _untrust(hist, "the wage content identity could not be computed for an accepted decision", len(state["audit"]))
    hist["records"].append({"seq": len(hist["records"]) + 1, "decision_id": d.get("decision_id"), "modification": str(d.get("modification")),
                            "content_sha256": content_sha256, "content_identity": committed, "identity_spec": WAGE_IDENTITY_VERSION, "by": by,
                            "audit_event_id": audit_event_id, "ever_cleared": False, "ever_authorized_pricing": False, "first_cleared_audit_event_id": None})


def _live_matches(state, record):
    """The live wage record must have exactly the canonical content committed in history for its latest matching version.
    A missing, malformed or different identity is a mismatch (fail closed); decision id, modification and actor alone are never enough."""
    committed, spec = record.get("content_identity"), record.get("identity_spec")
    if not isinstance(committed, str) or not _HEX64.match(committed) or spec not in (WAGE_IDENTITY_VERSION, *LEGACY_IDENTITY_SPECS):
        return False, "the committed wage content identity is missing or malformed"
    try:
        live = wage_identity_from_state(state, spec)                # an older (v1) commitment is compared under ITS spec, but only for unambiguous content
    except WageAmbiguity:
        return False, "the live wage record has ambiguous duplicate role/classification keys, so equivalence with the committed history cannot be established"
    except ValueError:
        return False, "the live wage record content cannot be canonicalized"
    if live != committed:
        return False, "the live wage record content differs from the committed history (unexplained change)"
    return True, None


def wage_history_observe(hist, state):
    """Called on EVERY request for the project (before it is processed) and after every mutation, under the project lock. If the CURRENT wage record
    is cleared, or an estimate/digest exists on it, the matching history record is permanently marked. If the engine's current record cannot be matched to
    the adapter history (out-of-band change, missing record), the history is marked incomplete forever and every same-modification change fails closed."""
    if hist is None or not hist["complete"]:
        return
    view = wage_view(state)
    if not view.get("required") or not view.get("recorded") or not view.get("decision"):
        return
    d = view["decision"]
    recs = [r for r in hist["records"] if r["decision_id"] == d["decision_id"] and _modkey(r["modification"]) == _modkey(d["modification"])]
    if not recs or recs[-1]["by"] != d["recorded_by"]:
        _untrust(hist, "the engine's current wage record does not match the adapter history", len(state["audit"]))
        return
    latest = recs[-1]
    ok, why = _live_matches(state, latest)
    if not ok:
        _untrust(hist, why, len(state["audit"]))
        return
    authorized = state.get("estimate") is not None
    if view.get("cleared") or authorized:
        latest["ever_cleared"] = latest["ever_cleared"] or True
        if latest["first_cleared_audit_event_id"] is None:
            latest["first_cleared_audit_event_id"] = len(state["audit"])
    if authorized:
        latest["ever_authorized_pricing"] = True


def wage_decision_guard(state, body, content_sha256, hist):
    """Adapter-level wage-determination policy, run BEFORE the engine; never touches state. Authority comes only from the server-side append-only
    history above (never a client flag, never current status alone, never absence of history).
      * different decision_id than the recorded one                       -> WAGE_SUPERSESSION_REQUIRED
      * HIGHER modification than the recorded one                         -> allowed (new audited decision; prior history retained)
      * lower modification (recorded, or ever recorded for this decision) -> engine stale refusal / WAGE_MODIFICATION_STALE
      * history missing or incomplete (for anything not strictly higher)  -> WAGE_HISTORY_UNAVAILABLE (fail closed)
      * same modification, identical content to the latest version        -> DECISION_UNCHANGED (never recorded again or re-attributed)
      * same modification, changed content:
            currently cleared                                             -> WAGE_MODIFICATION_NOT_HIGHER
            ever cleared / ever authorized pricing (any version)          -> WAGE_HISTORICALLY_CLEARED (irreversible)
            currently uncleared AND never cleared AND history complete    -> allowed (completing an incomplete record; append-only attribution)"""
    wage_validate_unambiguous(body)                                 # FIRST: before any history lookup, identity commitment or mutation
    view = wage_view(state)
    if not view.get("required"):
        return
    new = body.get("determination") if isinstance(body.get("determination"), dict) else {}
    new_id, new_mod = new.get("decision_id"), _modkey(new.get("modification"))
    try:
        new_identity = wage_identity_from_request(body)
    except ValueError:
        new_identity = None
    cur = view["decision"] if view.get("recorded") and view.get("decision") else None
    if cur and new_id != cur["decision_id"]:
        raise AdapterRefusal(409, "WAGE_SUPERSESSION_REQUIRED", "a different wage decision cannot replace the recorded one through this route; "
                             "a documented, append-only supersession action is required and is not implemented (contract proposal)")
    if new_mod is None:
        return                                                      # malformed modification: the engine refuses it
    if cur and _modkey(cur["modification"]) is not None and new_mod > _modkey(cur["modification"]):
        return
    if hist is None or not hist["complete"]:
        raise AdapterRefusal(409, "WAGE_HISTORY_UNAVAILABLE", "the server-side wage history for this project is missing or incomplete, so it cannot be shown that this "
                             "modification was never cleared; only a strictly higher modification is accepted")
    same_decision = [r for r in hist["records"] if r["decision_id"] == new_id]
    if any((_modkey(r["modification"]) or -1) > new_mod for r in same_decision):
        raise AdapterRefusal(409, "WAGE_MODIFICATION_STALE", "a higher modification of this wage decision was already recorded; statutory modifications cannot go backwards")
    ident = [r for r in same_decision if _modkey(r["modification"]) == new_mod]
    if cur is None and not ident:
        return                                                      # first record for this identity
    if cur is not None and (not ident or ident[-1]["by"] != cur["recorded_by"]):
        raise AdapterRefusal(409, "WAGE_HISTORY_UNAVAILABLE", "the recorded wage decision cannot be matched to the adapter history")
    if cur is not None:                                             # validate the OLD live record against committed history BEFORE any mutation
        ok, why = _live_matches(state, ident[-1])
        if not ok:
            _untrust(hist, why, len(state["audit"]))
            raise AdapterRefusal(409, "WAGE_HISTORY_UNAVAILABLE", why + "; the wage history for this project is now permanently untrusted for same-or-lower-modification edits")
    if new_identity is None:
        raise AdapterRefusal(409, "WAGE_HISTORY_UNAVAILABLE", "the submitted wage content cannot be canonicalized, so it cannot be compared with history")
    if ident and ident[-1].get("content_identity") == new_identity:
        if cur is not None:
            raise AdapterRefusal(409, "DECISION_UNCHANGED", f"this wage determination (modification {cur['modification']}) is already recorded by {cur['recorded_by']}; "
                                 "resubmitting it would re-attribute it")
        return                                                      # re-verifying identical content after the engine voided the record
    if cur is not None and view.get("cleared"):
        raise AdapterRefusal(409, "WAGE_MODIFICATION_NOT_HIGHER", f"a changed wage determination needs a higher modification than {cur['modification']}; "
                             "same-modification changes would overwrite the recorded actor and decision")
    if any(r["ever_cleared"] or r["ever_authorized_pricing"] for r in ident):
        raise AdapterRefusal(409, "WAGE_HISTORICALLY_CLEARED", f"modification {new.get('modification')} of this wage decision was previously cleared or used to authorize pricing; "
                             "that fact is irreversible. Use a higher modification (or a future append-only supersession action).")
    return                                                          # incomplete and never cleared: a correction, attributed append-only

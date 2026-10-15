"""Prevailing-wage (Davis-Bacon) labor costing from a HUMAN-VERIFIED wage determination. Pure, deterministic, no model.

What the human supplies (nothing here is defaulted or invented):
  determination   {decision_id, modification, date, valid_through?, source_ref}
  schedule        the wage decision's own table, transcribed: [{classification, base_rate, fringe_rate}]
  rows            one per cost-bearing labor role: the classification the human assigns, the source reference, base hourly rate,
                  fringe hourly rate, and whether that classification is LISTED in the decision, PROPOSED for agency conformance, or
                  APPROVED by conformance (with its reference)
  employer_burden {pct, source_ref}: employer payroll taxes and insurance as a percent of WAGES ONLY (explicit 0 allowed)
  production_rates_approved  true: a named human affirms the rate book's production rates for this wage basis
  certified_payroll_admin    {basis: lump_sum | per_week | per_crew_hour | not_charged, ...}: a separately owned cost, never invented

Three distinct things per labor hour, never mixed:
  wages            = base_rate                      (cash wage owed to the worker)
  fringe           = fringe_rate                    (fringe-benefit obligation, paid in cash or into a bona fide plan; NOT burdened)
  employer costs   = base_rate x employer_burden.pct (taxes/insurance driven by wages; the rate book's own burden_pct is IGNORED here
                                                      because it includes benefits and would double-count the fringe)
loaded hourly rate = wages + fringe + employer costs.

A role is SUPPORTED only if every check for it passes. Unsupported roles are named with codes; supported ones can still be costed, but the
labor basis as a whole is not usable (`blocking`) until every cost-bearing role and every global input is cleared."""
import datetime
from decimal import Decimal

CLASS_STATUSES = ("listed", "proposed_for_conformance", "approved_conformance")
ADMIN_BASES = ("lump_sum", "per_week", "per_crew_hour", "not_charged")
CENT = Decimal("0.01")
CODES = ('CERTIFIED_PAYROLL_COST_MISSING', 'CLASSIFICATION_NOT_IN_DECISION', 'WAGE_CLASSIFICATION_IS_LISTED', 'WAGE_CLASSIFICATION_STATUS_INVALID', 'WAGE_CONFORMANCE_PENDING', 'WAGE_CONFORMANCE_REF_MISSING', 'WAGE_DECISION_EXPIRED', 'WAGE_DECISION_NOT_EFFECTIVE', 'WAGE_DETERMINATION_INCOMPLETE', 'WAGE_EMPLOYER_COST_MISSING', 'WAGE_FRINGE_MISSING', 'WAGE_PRODUCTION_UNAPPROVED', 'WAGE_RATE_MISMATCH', 'WAGE_RATE_MISSING', 'WAGE_ROLE_UNCLASSIFIED', 'WAGE_ROW_UNKNOWN_ROLE', 'WAGE_SCHEDULE_INVALID', 'WAGE_SCHEDULE_MISSING', 'WAGE_SOURCE_MISSING')   # every blocker code this module can raise


def D(x):
    return Decimal(repr(x)) if isinstance(x, float) else Decimal(x)


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and x not in (float("inf"), float("-inf"))


def _named(x):
    return isinstance(x, str) and x.strip() != ""


def _date(x):
    try:
        return datetime.date.fromisoformat(x)
    except (TypeError, ValueError):
        return None


def _p(code, message, role=None):
    return {"code": code, "message": message, **({"role_key": role} if role else {})}


def evaluate(rec, role_keys, as_of=None):
    """Return {'supported': {role: cost parts}, 'role_problems': {role: [problem]}, 'global_problems': [problem], 'blocking': bool}."""
    as_of = as_of or datetime.date.today()
    glob, per_role, supported = [], {r: [] for r in role_keys}, {}
    rec = rec if isinstance(rec, dict) else {}
    det = rec.get("determination") if isinstance(rec.get("determination"), dict) else {}

    for k in ("decision_id", "modification", "source_ref"):
        if not _named(str(det.get(k, "")) if det.get(k) is not None else ""):
            glob.append(_p("WAGE_DETERMINATION_INCOMPLETE", f"determination.{k} is required"))
    if det.get("modification") is not None and not str(det["modification"]).isdigit():
        glob.append(_p("WAGE_DETERMINATION_INCOMPLETE", "determination.modification must be a whole number"))
    issued = _date(det.get("date"))
    if issued is None:
        glob.append(_p("WAGE_DETERMINATION_INCOMPLETE", "determination.date must be an ISO date"))
    elif issued > as_of:
        glob.append(_p("WAGE_DECISION_NOT_EFFECTIVE", f"wage decision is dated {issued}, after the evaluation date {as_of}"))
    if det.get("valid_through") is not None:
        vt = _date(det["valid_through"])
        if vt is None:
            glob.append(_p("WAGE_DETERMINATION_INCOMPLETE", "determination.valid_through must be an ISO date"))
        elif vt < as_of:
            glob.append(_p("WAGE_DECISION_EXPIRED", f"wage decision {det.get('decision_id')} mod {det.get('modification')} was valid through {vt}; it is stale on {as_of}"))

    sched = {}
    raw = rec.get("schedule")
    if not isinstance(raw, list) or not raw:
        glob.append(_p("WAGE_SCHEDULE_MISSING", "the wage decision's classification table must be transcribed so assignments can be checked against it"))
    else:
        for s in raw:
            if not (isinstance(s, dict) and _named(s.get("classification")) and _num(s.get("base_rate")) and s["base_rate"] > 0
                    and _num(s.get("fringe_rate")) and s["fringe_rate"] >= 0):
                glob.append(_p("WAGE_SCHEDULE_INVALID", "each schedule entry needs a classification, a positive base rate and a fringe rate (explicit 0 allowed)"))
                break
            if s["classification"].strip().lower() in sched:
                glob.append(_p("WAGE_SCHEDULE_INVALID", f"classification {s['classification']!r} appears twice in the schedule"))
                break
            sched[s["classification"].strip().lower()] = (D(s["base_rate"]), D(s["fringe_rate"]))

    eb = rec.get("employer_burden")
    if not (isinstance(eb, dict) and _num(eb.get("pct")) and 0 <= eb["pct"] <= 1 and _named(eb.get("source_ref"))):
        glob.append(_p("WAGE_EMPLOYER_COST_MISSING", "employer_burden needs an explicit pct in [0, 1] (wages only, excluding fringe) and a source_ref"))
        burden = None
    else:
        burden = D(eb["pct"])
    if rec.get("production_rates_approved") is not True:
        glob.append(_p("WAGE_PRODUCTION_UNAPPROVED", "a named human must approve the production rates for this wage basis"))

    adm = rec.get("certified_payroll_admin")
    ok = isinstance(adm, dict) and adm.get("basis") in ADMIN_BASES and _named(adm.get("source_ref"))
    if ok and adm["basis"] == "not_charged":
        ok = _named(adm.get("reason"))
    elif ok:
        ok = _num(adm.get("unit_cost")) and adm["unit_cost"] >= 0
        if ok and adm["basis"] == "per_week":
            ok = _num(adm.get("weeks")) and adm["weeks"] > 0
    if not ok:
        glob.append(_p("CERTIFIED_PAYROLL_COST_MISSING", "certified-payroll administration needs a human-owned basis (lump_sum/per_week/per_crew_hour with unit_cost, or "
                       "not_charged with a reason) and a source_ref; no cost is assumed"))

    rows = rec.get("rows") if isinstance(rec.get("rows"), list) else []
    by_role = {}
    for r in rows:
        if isinstance(r, dict) and r.get("role_key") in per_role and r["role_key"] not in by_role:
            by_role[r["role_key"]] = r
        elif isinstance(r, dict):
            glob.append(_p("WAGE_ROW_UNKNOWN_ROLE", f"row for role {r.get('role_key')!r} matches no cost-bearing role in the rate book"))
    for role in role_keys:
        row, probs = by_role.get(role), per_role[role]
        if row is None:
            probs.append(_p("WAGE_ROLE_UNCLASSIFIED", f"role {role} has no classification assigned", role))
            continue
        cls = row.get("classification")
        if not _named(cls):
            probs.append(_p("WAGE_ROLE_UNCLASSIFIED", f"role {role} has no classification", role))
        if not _named(row.get("source_ref")):
            probs.append(_p("WAGE_SOURCE_MISSING", f"role {role}: the classification and rates need a source reference", role))
        base, fringe = row.get("base_rate"), row.get("fringe_rate")
        if not (_num(base) and base > 0):
            probs.append(_p("WAGE_RATE_MISSING", f"role {role}: base hourly rate is missing or not positive", role))
        if not (_num(fringe) and fringe >= 0):
            probs.append(_p("WAGE_FRINGE_MISSING", f"role {role}: fringe rate is omitted; an explicit 0 is required if none is owed", role))
        status = row.get("classification_status")
        if status not in CLASS_STATUSES:
            probs.append(_p("WAGE_CLASSIFICATION_STATUS_INVALID", f"role {role}: classification_status must be one of {CLASS_STATUSES}", role))
        elif _named(cls):
            listed = sched.get(cls.strip().lower())
            if status == "listed":
                if listed is None:
                    probs.append(_p("CLASSIFICATION_NOT_IN_DECISION", f"role {role}: {cls!r} is said to be listed but is not in the wage decision's schedule", role))
                elif _num(base) and _num(fringe) and (D(base), D(fringe)) != listed:
                    probs.append(_p("WAGE_RATE_MISMATCH", f"role {role}: rates for {cls!r} differ from the wage decision's schedule", role))
            else:
                if listed is not None:
                    probs.append(_p("WAGE_CLASSIFICATION_IS_LISTED", f"role {role}: {cls!r} is in the schedule, so it is a listed classification, not a conformance", role))
                if status == "proposed_for_conformance":
                    probs.append(_p("WAGE_CONFORMANCE_PENDING", f"role {role}: {cls!r} is proposed for conformance and not yet approved by the contracting agency", role))
                elif not _named(row.get("conformance_ref")):
                    probs.append(_p("WAGE_CONFORMANCE_REF_MISSING", f"role {role}: an approved conformance needs its approval reference", role))
        if not probs and burden is not None:
            w, f = D(base), D(fringe)
            supported[role] = {"classification": cls.strip(), "classification_status": status, "wages": w, "fringe": f,
                               "employer_costs": w * burden, "loaded": w + f + w * burden}
    blocking = bool(glob) or any(per_role.values())
    return {"supported": supported, "role_problems": {k: v for k, v in per_role.items() if v}, "global_problems": glob, "blocking": blocking}


def all_problems(ev):
    return list(ev["global_problems"]) + [p for ps in ev["role_problems"].values() for p in ps]


def crew_rates(ev, ratebook):
    """{crew_id: {'wages','fringe','employer_costs','loaded'}} for crews whose EVERY member role is supported."""
    out = {}
    for c in ratebook["crews"]:
        if all(rk in ev["supported"] for rk in c["members"]):
            parts = {k: sum(ev["supported"][rk][k] * n for rk, n in c["members"].items()) for k in ("wages", "fringe", "employer_costs", "loaded")}
            out[c["crew_id"]] = parts
    return out


def admin_cost(adm, crew_hours):
    """Certified-payroll administration in dollars, from the human-owned basis. Never invents a number."""
    if adm["basis"] == "not_charged":
        return Decimal(0)
    unit = D(adm["unit_cost"])
    qty = {"lump_sum": Decimal(1), "per_week": D(adm.get("weeks", 0)), "per_crew_hour": crew_hours}[adm["basis"]]
    return (unit * qty).quantize(CENT)

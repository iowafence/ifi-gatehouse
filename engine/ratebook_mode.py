"""Rate-book pricing mode for the three-gate workflow. workflow.py calls in here only when a rate book is attached,
so legacy (scalar rate table) behaviour is untouched.

Division of labour (nothing here lets a model supply a quantity, a rate or a dollar):
  * quantities  <- pricing.quantities (deterministic arithmetic on Scope-Gate-cleared facts)
  * dollars     <- pricing.engine     (exact decimal, authoritative)
  * decisions   <- named humans via the three gates; this module only turns open problems into Scope Gate exceptions
Everything that stops a price becomes a blocking exception with a plain-language question, never a silent zero."""
import datetime
import hashlib

from pricing import engine as pe
from pricing import crews, footings, prevailing, quantities, vocab
from pricing.ratebook import canonical

from .exceptions import _ex, detect
from . import bid_schedule
from .guards import geometry_problems, is_number, structural_problems, value_problems
from .takeoff import compute_takeoff
from .util import get_ptr

SCOPE_LEVEL_CODES = {"RULESET_NOT_APPROVED", "UNRESOLVED_QUANTITY", "UNAPPROVED_PROVISIONAL"}   # already shown as their own exceptions
LABOR_CODES = {"LABOR_NOT_APPROVED", "LABOR_APPROVAL_STALE"}


def as_of(state):
    """Evaluation date for rate-book effectivity. policy['as_of'] (ISO) pins it for reproducible tests and audits."""
    v = state["policy"].get("as_of")
    return datetime.date.fromisoformat(v) if v else None


def resolutions(state):
    """{fact_path: resolution} for human decisions that still govern a fact in the CURRENT scope."""
    out = {}
    for a in state["audit"]:
        if a["event"] != "resolved":
            continue
        for p in a.get("paths", []):
            try:
                fact = get_ptr(state["scope"], p)
            except (KeyError, IndexError, ValueError, TypeError):
                continue
            if isinstance(fact, dict) and fact.get("status") == "human_resolved":
                out[p] = {"exception_id": a["exception_id"], "by": a["actor"], "note": a["note"], "scope_version": a["after_version"]}
    return out


def ruleset_approval(state):
    """The named approval, only while it still matches the rule file. Under policy.production the rule file itself must also
    be marked status 'approved' (an estimator edits it, which changes its hash and therefore needs a fresh named approval)."""
    ap = state.get("ruleset_approval")
    if not (ap and ap["sha256"] == state["ruleset"]["sha256"]):
        return None
    if state["policy"].get("production") and state["ruleset"]["rules"].get("status") != "approved":
        return None
    return ap


def footing_refresh(state, takeoff):
    """footing-scope.v1 bookkeeping for the current scope (a no-op, leaving no key behind, for a scope without a footing_scope):
    stores one deterministic schedule and one informational known-subtotal per scenario, returns (extra exceptions, takeoff with schedule counts).
    The schedule is a pure function of the scope, so any change to a count input, a footing class, a dimension or an assumption changes its hash."""
    scope = state["scope"]
    if not (isinstance(scope, dict) and "footing_scope" in scope):
        state.pop("footing_schedule", None)
        state.pop("footing_partial", None)
        return [], takeoff
    P = state["ruleset"]["rules"]["params"]
    res = resolutions(state)
    scheds, partial, extra = {}, {}, []
    scenarios = {}
    if not (structural_problems(scope) or value_problems(scope) or geometry_problems(scope)):
        scenarios = quantities.scenario_scopes(scope)
    for sref, sc in scenarios.items():
        if "footing_scope" not in sc or structural_problems(sc) or value_problems(sc) or geometry_problems(sc):
            scheds[sref] = None
            continue
        legacy = takeoff if sc is scope else None
        if legacy is None:
            try:
                legacy = compute_takeoff(sc, state.get("rules"))
            except (KeyError, TypeError, ValueError, ZeroDivisionError, ArithmeticError):
                legacy = None
        sch = scheds[sref] = footings.evaluate(sc, P, scenario=sref, resolutions=res, legacy_takeoff=legacy)
        partial[sref] = footings.known_subtotals(sch, state["ratebook"])
        oa = sch["ownership_audit"]
        if oa["duplicate_post_ids"] or not oa["every_post_has_one_class_and_owner"]:
            extra.append(_ex("FOOTING_SCHEDULE_UNRELIABLE", "blocking", f"/footing_scope/{sref}",
                             f"[{sref}] the footing schedule failed its own ownership audit (a physical post appears twice or has no class/owner); it cannot be priced.",
                             [], None, state["waived"], free_text=False))
        po = sch["posture"]
        if not po["bid_ready"]:
            msg = "; ".join(r["message"] for r in po["reasons"])[:600]
            e = _ex("FOOTING_SCOPE_NOT_BID_READY", "advisory", f"/footing_scope/{sref}",
                    f"[{sref}] footing scope is {po['release_class']}: {msg}. Acknowledging this warning does not make the pricing correct.",
                    [{"release_class": po["release_class"], "reasons": po["reasons"]}], None, state["waived"], free_text=False)
            if e:
                extra.append(e)
    state["footing_schedule"], state["footing_partial"] = scheds, partial
    if takeoff is not None:
        sel = next((k for k, v in scenarios.items() if v is scope), vocab.BASE)
        if scheds.get(sel):
            takeoff = footings.adjust_takeoff(scope, takeoff, scheds[sel])
    return extra, takeoff


def _group(items):
    out = {}
    for key, reason in items:
        out.setdefault(reason, []).append(key)
    return out


def pricing_exceptions(state, takeoff):
    """(exceptions, payloads) for the current scope and its alternates. Called only when the scope has no fact-level blocker."""
    scope, rb, ruleset = state["scope"], state["ratebook"], state["ruleset"]
    exs, payloads, seen_map = [], {}, set()
    approval = ruleset_approval(state)
    res = resolutions(state)
    scenarios = quantities.scenario_scopes(scope)
    if not scenarios:
        e = _ex("NO_PRICING_SCENARIO", "blocking", "/bid_structure/selected_bid", "The selected bid names no base or alternate scenario that can be priced.",
                [], None, state["waived"], free_text=False)
        return ([e] if e else []), {}
    for sref, sc in scenarios.items():
        if sc is scope:
            tk = takeoff
        else:
            aexs, tk, _ = detect(sc, state.get("rules"), waived=state["waived"], strict_inferred=True)
            if tk is None:
                what = "; ".join(sorted({e["question"] for e in aexs if e["severity"] == "blocking"}))[:600]
                exs.append(_ex("ALTERNATE_SCOPE_UNRESOLVED", "blocking", f"/bid_structure/alternates/{sref}",
                               f"Alternate {sref} cannot be quantified: {what}. This needs a document change, not a typed value.", [], None, state["waived"], free_text=False))
                continue
        built = quantities.build_payload(sc, tk, ruleset, scope_ref=sref, resolutions=res, ruleset_approval=approval)
        payload = payloads[sref] = built["payload"]
        for p in built["mapping_problems"]:
            if p["path"] not in seen_map:            # one blocker per requirement; later scenarios repeat it with different counts
                seen_map.add(p["path"])
                exs.append(_ex("NO_PRICING_MAPPING", "blocking", p["path"], p["message"] + ". Add a catalog item or exclude it with a documented decision.",
                               [], None, state["waived"], free_text=False))
        for reason, keys in _group((b["ref"], b["message"]) for b in quantities.blockers(payload, require_ruleset_approval=False)
                                   if b["code"] == "QUANTITY_UNRESOLVED").items():
            e = _ex("QUANTITY_UNRESOLVED", "blocking", f"/quantities/{sref}/{sorted(keys)[0]}",
                    f"[{sref}] {reason} (blocks {', '.join(sorted(keys))}). The quantity is left unresolved, never priced as zero.",
                    [], None, state["waived"], free_text=False)
            if e:
                exs.append(e)
        for b in quantities.blockers(payload, require_ruleset_approval=False):
            if b["code"] == "QUANTITY_PROVISIONAL":
                e = _ex("QUANTITY_PROVISIONAL", "blocking", f"/quantities/{sref}/{b['ref']}", f"[{sref}] {b['ref']}: {b['message']}.",
                        [], None, state["waived"], free_text=False)
                if e:
                    exs.append(e)
    if not approval:
        rs = ruleset
        e = _ex("QUANTITY_RULESET_UNAPPROVED", "blocking", "/quantity_ruleset",
                f"The fitting and hardware quantity rules ({rs['ruleset_id']} v{rs['version']}, {rs['sha256'][:12]}) have no named estimator approval. "
                "Review the rule table, then record the typed ruleset approval for exactly that version.", [], None, state["waived"], free_text=False)
        if e:
            e["required_decision"] = {"type": "approve_ruleset", "ruleset_id": rs["ruleset_id"], "version": rs["version"], "sha256": rs["sha256"]}
            exs.append(e)
    # rate-book-side blockers that do not depend on the labor decision
    fake_labor = {"status": "decided", "ratebook_labor_sha256": rb["hashes"]["labor_sha256"]}
    seen = set()
    for sref, payload in payloads.items():
        for p in pe.check(payload, rb, labor_basis=fake_labor, as_of=as_of(state), max_ratebook_age_days=state["policy"].get("max_ratebook_age_days"),
                          require_ruleset_approval=False):
            if p["code"] in SCOPE_LEVEL_CODES | LABOR_CODES | CREW_CODES or (p["code"], p.get("ref"), p["message"]) in seen:
                continue
            seen.add((p["code"], p.get("ref"), p["message"]))
            e = _ex(f"PRICING_{p['code']}", "blocking", f"/ratebook/{p.get('ref') or 'book'}", p["message"] + ".", [], None, state["waived"], free_text=False)
            if e:
                exs.append(e)
    return exs, payloads


def estimate(state):
    """estimate.v1 plus the legacy keys (price_total, cogs, ...) the gate machinery and API summary already read."""
    labor = state["labor_review"]
    gate_assembly_by_scope = None
    if state["scope"].get("project_ref") == "DP-001":
        from pricing.quantities import scenario_scopes
        gate_assembly_by_scope = {}
        for sref, scope in scenario_scopes(state["scope"]).items():
            gates = {}
            for gid, row in bid_schedule.gate_rows_from_scope(scope).items():
                width = row["width_fact"]
                if not isinstance(width, dict) or width.get("status") not in ("confirmed", "human_resolved"):
                    raise pe.PricingBlocked([{"code": "GATE_OVERRIDE_SCOPE", "message": f"{gid} clear-opening width must be accepted in scope"}])
                gates[gid] = {"source": "scope_gate", "clear_width_ft": width.get("value"),
                              "quantity": row["quantity"], "bid_item_no": row["item_no"],
                              "source_evidence_refs": [{"fact_path": f"/gates/{gid}/clear_width_ft", "evidence": width.get("evidence", [])}]}
            gate_assembly_by_scope[sref] = gates
    est = pe.price_scenarios(state["quantities"], state["ratebook"], labor_basis=labor, as_of=as_of(state), crew_plan=state.get("crew_plan"),
                             expected_scope_version=state["scope"]["scope_version"],
                             max_ratebook_age_days=state["policy"].get("max_ratebook_age_days"), gate_assembly_by_scope=gate_assembly_by_scope)
    sel = ((state["scope"].get("bid_structure") or {}).get("selected_bid") or {}).get("value")
    if sel not in (None, "base") and sel in est["scenarios"]:
        est["headline_scope_ref"] = sel
        est["digest"] = hashlib.sha256(canonical({k: v for k, v in est.items() if k != "digest"}).encode()).hexdigest()
    head = est["scenarios"][est["headline_scope_ref"]]
    est.update({
        "rates_profile": f"{est['ratebook_ref']['ratebook_id']} v{est['ratebook_ref']['version']}",
        "price_total": head["price_total"],
        "cogs": {"materials": round(head["materials"]["subtotal"] + head["sales_tax"]["amount"], 2), "services": head["services"]["subtotal"],
                 "labor": round(head["labor"]["subtotal"] + (head["labor"].get("certified_payroll_admin") or {}).get("extended", 0), 2),
                 "equipment": head["equipment"]["subtotal"], "mobilization": head["mobilization"]["subtotal"], "total": head["direct_cost"]},
        "man_hours": head["labor"]["crew_hours"], "overhead": head["overhead"]["amount"], "pay_items": [],
        "cogs_per_lf": round(head["direct_cost"] / head["fence_lf"], 2) if is_number(head["fence_lf"]) and head["fence_lf"] > 0 else None,
    })
    return est


def wage_required(state):
    pw = (state["scope"].get("global_requirements") or {}).get("prevailing_wage_required")
    return isinstance(pw, dict) and pw.get("status") != "unresolved" and str(pw.get("value")).strip().lower() == "yes"


def labor_roles(state):
    """Role keys that actually carry cost: members of crews used by a labor task."""
    return pe.used_roles(state["ratebook"])


def partial_labor(state, wd, ev):
    """What CAN be calculated while the basis is blocked: loaded rates for supported roles, crews made only of supported roles, and the
    tasks those crews do (from the current quantities). Informational: it never reaches an estimate."""
    out = {"roles": {r: {k: (float(v) if not isinstance(v, str) else v) for k, v in c.items()} for r, c in ev["supported"].items()},
           "unresolved_roles": sorted(ev["role_problems"]), "crews": {}, "tasks": []}
    rates = prevailing.crew_rates(ev, state["ratebook"])
    for cid, c in rates.items():
        out["crews"][cid] = {k: float(v) for k, v in c.items()}
    qty = {i.get("driver_key"): i for i in ((state.get("quantities") or {}).get("BASE") or {}).get("items", []) if i.get("driver_key")}
    for t in state["ratebook"]["labor_tasks"]:
        it = qty.get(t["driver_key"])
        if t["crew_id"] in rates and it and it["quantity"] is not None:
            hours = prevailing.D(it["quantity"]) / prevailing.D(t["production_rate"])
            c = rates[t["crew_id"]]
            out["tasks"].append({"task_id": t["task_id"], "crew_id": t["crew_id"], "crew_hours": float(round(hours, 6)),
                                 **{k: float((hours * c[k]).quantize(prevailing.CENT)) for k in ("wages", "fringe", "employer_costs")}})
        else:
            out["tasks"].append({"task_id": t["task_id"], "crew_id": t["crew_id"], "blocked": "a role in this crew is not cleared"})
    return out


def wage_exceptions(state, wd, ev=None):
    """Labor Gate blockers for a prevailing-wage project. The gate is OPEN to a named human; pricing and release are not until every
    cost-bearing role and every global input is cleared."""
    out = []
    roles = labor_roles(state)
    if not wd:
        e = _ex("WAGE_DETERMINATION_REQUIRED", "blocking", "/labor/wage_determination",
                "Davis-Bacon / prevailing wage applies. A named person must identify the wage decision, transcribe its classification table and, for each "
                f"labor role in the rate book ({', '.join(roles)}), assign the classification with its source, base rate and fringe, and state whether it is "
                "listed, proposed for conformance or approved. Also required: employer cost on wages, production-rate approval and the certified-payroll "
                "administration cost. Company standard rates and generic qualified assumptions are not accepted.", [], None, state["waived"], free_text=False)
        if e:
            e["required_decision"] = {"type": "wage_determination", "roles": roles}
            out.append(e)
        return out
    ev = ev or prevailing.evaluate(wd, roles, as_of(state))
    for p in prevailing.all_problems(ev):
        scope = p.get("role_key", "global")
        e = _ex(p["code"], "blocking", f"/labor/wage_determination/{scope}", p["message"], [], None, state["waived"], free_text=False)
        if e:
            out.append(e)
    e = _ex("WAGE_PARTIAL_RESULT", "advisory", "/labor/wage_determination/partial",
            f"Calculated for cleared roles ({', '.join(sorted(ev['supported'])) or 'none'}); not cleared: {', '.join(sorted(ev['role_problems'])) or 'none'}. "
            "The labor basis as a whole stays blocked.", [partial_labor(state, wd, ev)], None, state["waived"], free_text=False)
    if e:
        out.append(e)
    return out


def wage_labor_review(state, wd):
    """The Labor Gate decision derived from a fully cleared wage determination. Deterministic: built only from the stored record."""
    d = wd["determination"]
    return {"status": "decided", "decision": "prevailing_wage_determination", "provisional": False, "wage_basis": "prevailing_wage",
            "loaded_hourly_rate": None, "rate_source": f"wage decision {d['decision_id']} modification {d['modification']}",
            "source_refs": [d["source_ref"]], "classifications": sorted({r["classification"] for r in wd["rows"]}), "certified_payroll": True,
            "applicability_review": "Davis-Bacon applies by contract (documents); classifications assigned by a named human against the wage decision",
            "qualification": None, "decided_by": wd["recorded_by"], "note": wd["note"], "scope_version": wd["scope_version"],
            "decided_utc": wd["recorded_utc"], "ratebook_labor_sha256": wd["ratebook_labor_sha256"], "ratebook_ref": state["ratebook_ref"],
            "wage_determination": wd}


CREW_CODES = {"CREW_PLAN_REQUIRED", "CREW_PLAN_NOT_APPROVED", "CREW_PLAN_STALE", "CREW_NOT_SELECTED", "CREW_NO_PRODUCTION_RATE",
              "CREW_UNSUITABLE", "CREW_PROFILE_CHANGED", "DIFFICULTY_INVALID", "DIFFICULTY_EVIDENCE_MISSING"}


def crew_rates(state):
    """Hourly cost of every crew whose cost is ESTABLISHED: company roles, or the cleared prevailing-wage determination. Others are absent."""
    rb = state["ratebook"]
    if wage_required(state):
        wd = state.get("wage_determination")
        if not wd:
            return {}
        return prevailing.crew_rates(prevailing.evaluate(wd, labor_roles(state), as_of(state)), rb)
    loaded = {r["role_key"]: prevailing.D(r["base_wage_per_hr"]) * (1 + prevailing.D(r["burden_pct"])) for r in rb["roles"]}
    return {c["crew_id"]: sum(loaded[rk] * n for rk, n in c["members"].items()) for c in rb["crews"]}


def crew_comparison(state):
    """Per scenario: every candidate crew for every task with efficiency, difficulty response, crew-hours, worker-hours, duration and labor cost.
    Uses the APPROVED difficulty when a plan exists; otherwise a clearly marked provisional 'standard' view that can never price anything."""
    plan = state.get("crew_plan")
    approved = bool(plan)
    difficulty = plan["difficulty"] if plan else {"default": "standard", "overrides": {}}
    out = {}
    for sref, payload in (state.get("quantities") or {}).items():
        drivers = {i["driver_key"]: i["quantity"] for i in payload["items"] if "driver_key" in i}
        out[sref] = crews.compare(state["ratebook"], drivers, difficulty, crew_rates(state), plan)
        out[sref]["difficulty_approved"] = approved
        if not approved:
            out[sref]["difficulty_note"] = "provisional view at Standard difficulty; not approved and not usable for pricing"
    return out


def crew_exceptions(state):
    """Blocking exceptions for the crew plan, plus an advisory for a pending AI difficulty recommendation."""
    rb = state["ratebook"]
    out = []
    if not crews.plan_required(rb):
        return out
    probs = crews.plan_problems(state.get("crew_plan"), rb)
    if probs and not state.get("crew_plan"):
        e = _ex("CREW_PLAN_REQUIRED", "blocking", "/labor/crew_plan",
                "A named person must approve the crew plan: the preferred crew or a crew per task, and the job difficulty (default plus per-task overrides). "
                "Efficiency and difficulty change crew-hours only, never wages, fringes or quantities; a crew lacking a required role or qualification is never "
                "eligible.", [state.get("crew_comparison") or {}], None, state["waived"], free_text=False)
        if e:
            e["required_decision"] = {"type": "crew_plan"}
            out.append(e)
    else:
        for p in probs:
            e = _ex(p["code"], "blocking", f"/labor/crew_plan/{p.get('ref') or 'plan'}", p["message"], [], None, state["waived"], free_text=False)
            if e:
                out.append(e)
    rec = state.get("difficulty_recommendation")
    if rec and not state.get("crew_plan"):
        e = _ex("DIFFICULTY_RECOMMENDATION_PENDING", "advisory", "/labor/difficulty_recommendation",
                f"A difficulty recommendation by {rec['recommended_by']} (default {rec['default']}, {len(rec['overrides'])} override(s)) cites "
                f"{len(rec['evidence_refs'])} document reference(s). It has no pricing effect until a named human approves it in the crew plan.",
                [rec], None, state["waived"], free_text=False)
        if e:
            out.append(e)
    return out


def labor_hash(state):
    return state["ratebook"]["hashes"]["labor_sha256"]

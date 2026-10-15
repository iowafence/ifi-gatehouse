"""Stateful three-gate workflow: Scope Gate (1), Labor Gate (2), Release Gate (3).

  start -> needs_scope_review -> needs_labor_review -> ready_for_final_review -> released
                     \\____________ held (RFI / clarification; blocked until new input) ____________/

AI interprets evidence; this module and its callees do all quantity and money arithmetic; named humans
authorize scope, labor basis, and final release. Nothing here lets a model approve a gate or supply a price.

Rules enforced in code:
  * Every human decision needs a non-blank named actor and a note. A rejected decision leaves state untouched.
  * Any change to scope invalidates the labor decision and every release eligibility derived from it.
  * Pricing exists only when scope has no blocking exception AND a labor decision is recorded.
  * Release needs a named approver, the exact scope version, and the engine-computed digest of the exact
    pending proposal (scope, takeoff, estimate, labor decision, rate table). A stale digest is rejected.
  * Resolving a scope exception 'resumes' from the structured scope: the model is never re-invoked to
    re-derive facts a human already settled.

Rate-book mode (start(..., ratebook=...), see engine/ratebook_mode.py): quantities come from pricing.quantities, dollars
from pricing.engine, and every approval binds to the exact rate book (id, version, content hash), quantity ruleset and
scope version. A new addendum (revise_scope) or a new rate book (attach_ratebook) preserves the prior estimate in
state['history'], recomputes, records a before/after diff, invalidates the labor decision and any release eligibility
(a released artifact is never edited: it is moved to history as superseded), and requires fresh human approval.
"""
import copy
import functools
import hashlib
import hmac
import json
import math
import re
import datetime
from datetime import timezone

from pricing import compare as pcompare
from pricing import crews as pcrews
from pricing import prevailing
from pricing import engine as pengine
from pricing import footings, jsonschema_lite, quantities, vocab
from pricing import ratebook as pratebook

from . import ratebook_mode as rm
from .estimate import compute_estimate
from .exceptions import _ex, _resolve_patch, detect
from .guards import is_number, is_positive_number, rates_problems, structural_problems, value_problems
from .util import apply_patch, get_ptr, walk_facts

WAGE_CODES = set(prevailing.CODES) | {"WAGE_DETERMINATION_REQUIRED"} | rm.CREW_CODES   # all Labor Gate stage blockers
SCOPE_REVIEW, LABOR_REVIEW, READY, RELEASED, HELD = (
    "needs_scope_review", "needs_labor_review", "ready_for_final_review", "released", "held")

LABOR_DECISIONS = {
    "verified_standard": "standard_company_rates",
    "verified_federal": "federal_prevailing",
    "verified_state_local": "state_local_prevailing",
    "verified_cba": "union_cba",
    "human_assumption_with_qualification": "standard_company_rates",
}
# bases whose rate is not the company-controlled table must be supplied (and sourced) by the reviewer
EXTERNAL_BASES = {"federal_prevailing", "state_local_prevailing", "union_cba"}
CERTIFIED_PAYROLL_VALUES = (True, False, "unknown")


class GateError(Exception):
    pass


def _atomic(fn):
    """Run a state-changing operation on a working copy and commit only if it finishes. A refused or crashed call
    leaves the caller's state exactly as it was (no half-applied supersession, history entry or revision)."""
    @functools.wraps(fn)
    def wrapper(state, *args, **kwargs):
        work = copy.deepcopy(state)
        fn(work, *args, **kwargs)
        state.clear()
        state.update(work)
        return state
    return wrapper


def _utc():
    return datetime.datetime.now(timezone.utc).isoformat()


def _named(x):
    return isinstance(x, str) and x.strip() != ""


def _log(state, event, actor=None, **fields):
    entry = {"event_id": len(state["audit"]) + 1, "event": event, "utc": _utc(), "actor": actor, **fields}
    state["audit"].append(entry)


def _canon(obj):
    # allow_nan=False makes a NaN/inf anywhere in the proposal an error instead of a silent digest
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def proposal_digest(state):
    """SHA-256 of the exact pending proposal. Computed by the engine; the browser never computes it."""
    body = {
        "scope_version": state["scope"]["scope_version"], "scope": state["scope"],
        "takeoff": state["takeoff"], "estimate": state["estimate"],
        "labor_review": state["labor_review"], "rates": state["rates"],
    }
    if state.get("ratebook"):     # bind the approval to the exact rate book, quantities, ruleset and crew plan it priced
        body.update(ratebook_ref=state["ratebook_ref"], quantities=state["quantities"], crew_plan=state.get("crew_plan"),
                    ruleset={"sha256": state["ruleset"]["sha256"], "approved_by": (rm.ruleset_approval(state) or {}).get("by")})
    if state.get("footing_schedule"):     # footing-scope.v1: bind the approval to the exact per-class counts, sizes and calculation identity it priced
        body["footing"] = {k: (v["schedule_sha256"] if v else None) for k, v in sorted(state["footing_schedule"].items())}
    return hashlib.sha256(_canon(body).encode()).hexdigest()


def _unlabored():
    return {"status": "unresolved", "decision": None}


def _estimate(state):
    lr = state["labor_review"]
    if state.get("ratebook"):
        est = rm.estimate(state)
    else:
        rates = copy.deepcopy(state["rates"])
        rates["labor"]["hourly_rate_per_man"] = lr["loaded_hourly_rate"]
        est = compute_estimate(state["scope"], state["takeoff"], rates)
    # the estimate stays a pure function of scope + rates + decision; the timestamp lives on state/audit only
    est["labor_review"] = {k: copy.deepcopy(v) for k, v in lr.items() if k != "decided_utc"}
    return est


def _priceable(est, takeoff):
    try:
        _canon(est)
    except ValueError:
        return False
    return (is_positive_number(est.get("price_total")) and is_positive_number(takeoff["totals"]["fence_lf"])
            and all(is_number(v) and math.isfinite(v) for v in est["cogs"].values()))


def _advance(state):
    rbm = bool(state.get("ratebook"))
    exs, takeoff, recon = detect(state["scope"], state.get("rules"), waived=state["waived"], strict_inferred=rbm)
    state["exceptions"], state["reconciliation"] = exs, recon
    state.update(takeoff=None, estimate=None, proposal_digest=None)
    if rbm:
        state["quantities"] = None
        fx, takeoff = rm.footing_refresh(state, takeoff)
        exs.extend(fx)
    if any(e["severity"] == "blocking" for e in exs):
        state["status"] = HELD if state.get("hold") else SCOPE_REVIEW
        return state
    state["takeoff"] = takeoff
    if rbm:
        ap = state.get("ruleset_approval")
        if ap and ap["sha256"] != state["ruleset"]["sha256"]:
            _log(state, "ruleset_approval_invalidated", reason="the quantity ruleset changed", prior_sha256=ap["sha256"])
            state["ruleset_approval"] = None
        pexs, state["quantities"] = rm.pricing_exceptions(state, takeoff)
        pend = state.get("pending_acceptance")
        if pend:
            aex = _ex("ADDENDUM_ACCEPTANCE_REQUIRED", "blocking", f"/addenda/{pend['source']['doc_id']}@{pend['source']['doc_revision']}",
                      pend["summary"] + " Review the before/after difference and record the typed addendum acceptance to continue.", [], None,
                      state["waived"], free_text=False)
            if aex:
                aex["required_decision"] = {"type": "accept_addendum", "source": pend["source"], "scope_version": pend["scope_version"]}
                pexs.append(aex)
        state["exceptions"] = exs + pexs
        if any(e["severity"] == "blocking" for e in pexs):
            state["status"] = HELD if state.get("hold") else SCOPE_REVIEW
            return state
        state["crew_comparison"] = rm.crew_comparison(state)
        cp = state.get("crew_plan")
        if cp and cp["ratebook_labor_sha256"] != rm.labor_hash(state):
            _log(state, "crew_plan_invalidated", reason="crew profiles or production rates in the rate book changed", prior_plan_version=cp["plan_version"])
            _retire_crew_plan(state, "crew profiles or production rates in the rate book changed")
            state["crew_comparison"] = rm.crew_comparison(state)
        if rm.wage_required(state):       # Labor Gate is OPEN for the wage determination; pricing and release stay blocked
            wd = state.get("wage_determination")
            if wd and (wd["scope_version"] != state["scope"]["scope_version"] or wd["ratebook_labor_sha256"] != rm.labor_hash(state)):
                _log(state, "wage_determination_invalidated", reason="scope or rate-book labor inputs changed", prior_scope_version=wd["scope_version"])
                state["wage_determination"] = wd = None
            ev = prevailing.evaluate(wd, rm.labor_roles(state), rm.as_of(state)) if wd else None
            if ev is None or ev["blocking"]:
                _invalidate_labor_decision(state, "prevailing wage applies; no cleared wage determination")
                state["exceptions"] = state["exceptions"] + rm.wage_exceptions(state, wd, ev) + rm.crew_exceptions(state)
                state["status"] = HELD if state.get("hold") else LABOR_REVIEW
                return state
            state["labor_review"] = rm.wage_labor_review(state, wd)        # fully cleared: the Labor Gate decision derives from the record
        lr = state["labor_review"]
        if lr["status"] == "decided" and lr.get("ratebook_labor_sha256") != rm.labor_hash(state):
            _invalidate_labor(state, "rate book labor inputs changed or labor was decided against a different rate source")
    if state["labor_review"]["status"] != "decided":
        if rbm:
            state["exceptions"] = state["exceptions"] + rm.crew_exceptions(state)
        state["status"] = HELD if state.get("hold") else LABOR_REVIEW
        return state
    if rbm:
        cexs = rm.crew_exceptions(state)
        if any(e["severity"] == "blocking" for e in cexs):
            state["exceptions"] = state["exceptions"] + cexs
            state["status"] = HELD if state.get("hold") else LABOR_REVIEW
            return state
    try:
        est = _estimate(state)
        why = None if _priceable(est, takeoff) else "The estimate is not a finite positive price; it cannot be released."
    except (KeyError, TypeError, ValueError, ZeroDivisionError, ArithmeticError, pengine.PricingBlocked) as exc:
        est, why = None, f"No rate exists for part of this scope ({type(exc).__name__}: {exc}); it cannot be priced."
    if why:
        state.update(takeoff=None, status=SCOPE_REVIEW)
        state["exceptions"] = exs + [{
            "exception_id": "EX-UNPRICEABLE-/estimate", "code": "UNPRICEABLE", "severity": "blocking",
            "affects": ["/estimate"], "blocks_stage": "pricing", "evidence": [], "candidate_resolutions": [],
            "allows_free_text_resolution": False, "status": "open", "question": why}]
        return state
    state["estimate"] = est
    state["status"] = HELD if state.get("hold") else READY
    state["proposal_digest"] = proposal_digest(state)
    return state


# Facts the rate-book quantity rules cannot do without. If the extractor omitted one, it becomes an explicit UNRESOLVED
# placeholder (never a value), so it surfaces as a normal Scope Gate question that a named human answers.
REQUIRED_GLOBAL_FACTS = ("top_rail_continuous_across_gate_openings", "footing_terminal_diameter_in", "footing_terminal_depth_in",
                         "footing_line_diameter_in", "footing_line_depth_in", "prevailing_wage_required", "owner_sales_tax_exempt")


def _with_required_facts(scope):
    if not isinstance(scope, dict) or not isinstance(scope.get("global_requirements", {}), dict):
        return scope, []
    ge = scope.setdefault("global_requirements", {})
    skip = footings.GLOBAL_FOOTING_KEYS if "footing_scope" in scope else ()      # per-class footings replace the single project-wide footing
    added = [k for k in REQUIRED_GLOBAL_FACTS if k not in ge and k not in skip]
    for k in added:
        ge[k] = {"value": None, "status": "unresolved", "evidence": []}
    return scope, added


def _class_problem(ratebook, policy):
    """Public demo sessions may hold fictional rate books only (policy.allowed_ratebook_classes)."""
    allowed = (policy or {}).get("allowed_ratebook_classes")
    cls = ratebook.get("meta", {}).get("data_classification") if isinstance(ratebook, dict) else None
    if allowed is not None and cls not in allowed:
        raise GateError(f"this session may use only {sorted(allowed)} rate books; this one is {cls}")


def _policy_problems(policy):
    if policy is None:
        return
    if not isinstance(policy, dict):
        raise GateError("policy must be an object")
    if "as_of" in policy:
        try:
            datetime.date.fromisoformat(policy["as_of"])
        except (TypeError, ValueError):
            raise GateError("policy.as_of must be an ISO date string") from None
    cls = policy.get("allowed_ratebook_classes")
    if "allowed_ratebook_classes" in policy and not (isinstance(cls, list) and cls and all(c in ("FICTIONAL_DEMO", "COMPANY_PRIVATE") for c in cls)):
        raise GateError("policy.allowed_ratebook_classes must be a non-empty list of FICTIONAL_DEMO / COMPANY_PRIVATE")
    age = policy.get("max_ratebook_age_days")
    if "max_ratebook_age_days" in policy and not (isinstance(age, int) and not isinstance(age, bool) and age >= 0):
        raise GateError("policy.max_ratebook_age_days must be a non-negative integer")


def _max_doc_revision(scope):
    """Highest document revision already cited by the initial package (e.g. an addendum bundled in the ZIP)."""
    revs = [e["doc_revision"] for _, f in walk_facts(scope) for e in (f.get("evidence") or [])
            if isinstance(e, dict) and isinstance(e.get("doc_revision"), int) and not isinstance(e.get("doc_revision"), bool)] if isinstance(scope, dict) else []
    return max(revs or [0])


def start(scope, rates, rules=None, policy=None, *, ratebook=None, ruleset=None):
    """Open a project. Legacy mode prices from the scalar `rates` table. Rate-book mode (ratebook = the dict returned by
    pricing.ratebook.import_workbook) prices from the validated, versioned rate book; `rates` is then ignored."""
    if ratebook is None:
        bad = rates_problems(rates)
        if bad:
            raise GateError("unusable rate table: " + "; ".join(bad))
    else:
        bad = [f"{p}: {m}" for p, m in jsonschema_lite.problems(ratebook, "ratebook.v1")]
        if bad:
            raise GateError("unusable rate book: " + "; ".join(bad[:5]))
    scope = copy.deepcopy(scope) if isinstance(scope, dict) else scope
    if isinstance(scope, dict):
        v = scope.get("scope_version", 1)
        scope["scope_version"] = v if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else 1
    else:
        scope = {"scope_version": 1, "invalid_input_type": type(scope).__name__}
    _policy_problems(policy)
    if ratebook is not None:
        _class_problem(ratebook, policy)
    added = []
    if ratebook is not None:
        scope, added = _with_required_facts(scope)
    state = {"scope": scope, "rates": None if ratebook is not None else copy.deepcopy(rates), "rules": rules, "waived": [], "hold": None,
             "policy": {"allow_qualified_labor_assumption": True, **(policy or {})},
             "labor_review": _unlabored(), "audit": [], "history": [], "applied_sources": [], "doc_revision": _max_doc_revision(scope)}
    if ratebook is not None:
        state.update(ratebook=copy.deepcopy(ratebook), ratebook_ref=pratebook.ref(ratebook), ruleset=ruleset or quantities.load_ruleset(),
                     ruleset_approval=None, quantities=None, pending_acceptance=None, wage_determination=None, crew_plan=None,
                     difficulty_recommendation=None, crew_comparison=None)
    _log(state, "start", scope_version=scope["scope_version"], ratebook_ref=state.get("ratebook_ref"), unresolved_placeholders_added=added)
    return _advance(state)


def open_blockers(state):
    return [e for e in state["exceptions"] if e["severity"] == "blocking"]


def _require_open(state):
    if state["status"] == RELEASED:
        raise GateError("project is released; released artifacts are immutable")


def _require_actor(by, note):
    if not _named(by):
        raise GateError("a non-blank named actor is required")
    if not _named(note):
        raise GateError("a non-blank note is required")


def _invalidate_labor(state, reason):
    for key in ("crew_plan", "difficulty_recommendation"):
        if state.get(key):
            _log(state, f"{key}_invalidated", reason=reason, scope_version=state["scope"]["scope_version"])
            if key == "crew_plan":
                _retire_crew_plan(state, reason)
            else:
                state[key] = None
    if state.get("wage_determination"):
        _log(state, "wage_determination_invalidated", reason=reason, prior_scope_version=state["wage_determination"]["scope_version"])
        state["wage_determination"] = None
    _invalidate_labor_decision(state, reason)


def _retire_crew_plan(state, reason):
    """Move the approved crew plan into the append-only `crew_plan_history`; plan versions only ever increase, so a voided v1 is never reused."""
    plan = state.get("crew_plan")
    if plan:
        state.setdefault("crew_plan_history", []).append({**copy.deepcopy(plan), "retired_reason": reason, "retired_utc": _utc()})
    state["crew_plan"] = None


def _next_plan_version(state):
    seen = [p["plan_version"] for p in state.get("crew_plan_history", [])] + ([state["crew_plan"]["plan_version"]] if state.get("crew_plan") else [])
    return max(seen, default=0) + 1


def _invalidate_labor_decision(state, reason):
    if state["labor_review"]["status"] == "decided":
        _log(state, "labor_invalidated", reason=reason, scope_version=state["scope"]["scope_version"],
             prior_decision=state["labor_review"]["decision"])
        state["labor_review"] = _unlabored()


# ---------------------------------------------------------------- Gate 1: Scope

@_atomic
def resolve(state, exception_id, option_id=None, value=None, by="", note=""):
    """Record one named human decision on a Scope Gate exception."""
    _require_open(state)
    _require_actor(by, note)
    ex = next((e for e in state["exceptions"] if e["exception_id"] == exception_id), None)
    if ex is None:
        raise GateError(f"no open exception {exception_id}")
    if (option_id is None) == (value is None):
        raise GateError("provide exactly one of option_id or value")
    if ex.get("required_decision"):
        raise GateError(f"{ex['code']} needs the typed decision {ex['required_decision']['type']!r}; it cannot be resolved through a generic scope resolution")
    path = ex["affects"][0]
    if option_id is not None:
        opt = next((o for o in ex["candidate_resolutions"] if o["option_id"] == option_id), None)
        if opt is None:
            raise GateError(f"unknown option {option_id}")
        patch = opt["patch"]
    else:
        if not ex["allows_free_text_resolution"]:
            raise GateError(f"{ex['code']} cannot be resolved by a typed value; the source must change")
        try:
            fact = get_ptr(state["scope"], path)
        except (KeyError, IndexError, ValueError, TypeError):
            raise GateError(f"{path} is not a resolvable fact")
        if not isinstance(fact, dict) or "value" not in fact:
            raise GateError(f"{path} is not a resolvable fact")
        patch = _resolve_patch(path, fact, value, note, by)
    new_scope = apply_patch(state["scope"], patch)
    # Validate the post-resolution scope BEFORE touching state: a rejected decision changes nothing.
    if structural_problems(new_scope):
        raise GateError("resolution would leave the scope structurally invalid")
    touched = {path} | {op["path"] for op in patch}
    for p, msg in value_problems(new_scope):
        if any(p == t or p.startswith(t + "/") or t.startswith(p + "/") for t in touched):
            raise GateError(f"{p}: {msg}")
    before = state["scope"]["scope_version"]
    new_scope["scope_version"] = before + 1
    state["scope"] = new_scope
    state["hold"] = None
    if state.get("pending_acceptance"):      # still needs a named human; only its version pointer follows the scope
        state["pending_acceptance"]["scope_version"] = before + 1
    _log(state, "resolved", actor=by, exception_id=exception_id, option_id=option_id, value=value, note=note,
         before_version=before, after_version=before + 1, scope_version=before + 1, paths=sorted(touched))
    _invalidate_labor(state, "scope changed")
    return _advance(state)


@_atomic
def hold(state, *, by, reason, gate="scope"):
    """RFI / clarification. Blocks pricing and release until new input arrives; resolves nothing."""
    _require_open(state)
    _require_actor(by, reason)
    state["hold"] = {"by": by, "reason": reason, "gate": gate}
    _log(state, "held", actor=by, reason=reason, gate=gate, scope_version=state["scope"]["scope_version"])
    return _advance(state)


# ---------------------------------------------------------------- Gate 2: Labor

@_atomic
def approve_labor(state, *, by, decision, certified_payroll, applicability_review, note, wage_basis=None,
                  loaded_hourly_rate=None, source_refs=None, classifications=None, qualification=None):
    """Record a documented wage-basis determination. The application does not adjudicate labor law:
    a verified_* decision is a named human's attestation that is tied to cited source references; an
    assumption is stored as provisional, carries its qualification into the proposal, and is never
    labelled verified."""
    _require_open(state)
    if state["status"] not in (LABOR_REVIEW, HELD) or state["takeoff"] is None:
        raise GateError("labor gate is not open: scope must be resolved first")
    _require_actor(by, note)
    if [e for e in open_blockers(state) if e["code"] not in WAGE_CODES]:
        raise GateError("labor gate is not open: the Scope Gate still has blocking exceptions")
    if decision not in LABOR_DECISIONS:
        raise GateError("decision must be one of " + ", ".join(sorted(LABOR_DECISIONS)))
    wage_basis = wage_basis or LABOR_DECISIONS[decision]
    if wage_basis != LABOR_DECISIONS[decision]:
        raise GateError(f"{decision} requires wage_basis {LABOR_DECISIONS[decision]}")
    rbm = bool(state.get("ratebook"))
    if rbm and (certified_payroll is True or rm.wage_required(state)):
        raise GateError("prevailing-wage / certified-payroll work cannot take a company-rate labor decision or a generic qualified assumption; "
                        "record the wage determination (classifications, base rates, fringes) with record_wage_determination. "
                        "Pricing stays blocked until a supported wage basis exists")
    if rbm and wage_basis in EXTERNAL_BASES:
        raise GateError("prevailing-wage and CBA bases are not supported with a rate book yet: wages come from the rate book's roles and crews")
    if not _named(applicability_review):
        raise GateError("applicability_review is required: state how external wage applicability was checked")
    refs = source_refs or []
    if not isinstance(refs, list) or not all(_named(r) for r in refs):
        raise GateError("source_refs must be a list of non-blank strings")
    if certified_payroll not in CERTIFIED_PAYROLL_VALUES:
        raise GateError("certified_payroll must be True, False, or 'unknown'")
    classes = classifications or []
    if not isinstance(classes, list) or not all(_named(c) for c in classes):
        raise GateError("classifications must be a list of non-blank strings")
    assumption = decision == "human_assumption_with_qualification"
    if assumption:
        if not state["policy"]["allow_qualified_labor_assumption"]:
            raise GateError("policy does not allow a qualified labor assumption")
        if not _named(qualification):
            raise GateError("a qualified assumption requires an explicit qualification statement")
    else:
        if not refs:
            raise GateError("a verified decision must cite its source (wage schedule, CBA, or applicability evidence)")
        if certified_payroll == "unknown":
            raise GateError("a verified decision must state certified payroll yes or no")
        if wage_basis in EXTERNAL_BASES and not classes:
            raise GateError("prevailing-wage and CBA decisions require worker classifications")
    if wage_basis in EXTERNAL_BASES:
        if not is_positive_number(loaded_hourly_rate):
            raise GateError("a positive finite loaded hourly rate from the cited schedule is required")
        rate, rate_source = float(loaded_hourly_rate), "reviewer-supplied from cited source"
    elif rbm:
        if loaded_hourly_rate is not None:
            raise GateError("rate-book bases use the rate book's roles and crews; do not override them")
        r = state["ratebook_ref"]
        rate, rate_source = None, f"rate book {r['ratebook_id']} v{r['version']} ({r['labor_sha256'][:12]})"
    else:
        if loaded_hourly_rate is not None:
            raise GateError("company-rate bases use the company-controlled rate table; do not override it")
        profile = state["rates"].get("profile")
        if not _named(profile):
            raise GateError("the company rate table has no profile/version, so no rate source exists")
        rate, rate_source = float(state["rates"]["labor"]["hourly_rate_per_man"]), f"company rate table: {profile}"
    state["hold"] = None
    state["labor_review"] = {
        "status": "decided", "decision": decision, "provisional": assumption, "wage_basis": wage_basis,
        "loaded_hourly_rate": rate, "rate_source": rate_source, "source_refs": list(refs),
        "classifications": list(classes), "certified_payroll": certified_payroll,
        "applicability_review": applicability_review, "qualification": qualification if assumption else None,
        "decided_by": by, "note": note, "scope_version": state["scope"]["scope_version"], "decided_utc": _utc()}
    if rbm:
        state["labor_review"].update(ratebook_labor_sha256=rm.labor_hash(state), ratebook_ref=state["ratebook_ref"])
    _log(state, "labor_decided", actor=by, decision=decision, wage_basis=wage_basis, provisional=assumption,
         source_refs=list(refs), scope_version=state["scope"]["scope_version"], note=note)
    return _advance(state)


# ---------------------------------------------------------------- Gate 3: Release

def _still_human_resolved(state, paths):
    if not paths:
        return True
    for p in paths:
        try:
            f = get_ptr(state["scope"], p)
        except (KeyError, IndexError, ValueError, TypeError):
            continue
        if isinstance(f, dict) and f.get("status") == "human_resolved":
            return True
    return False


def qualifications(state):
    """Everything a reader of the proposal must be told is assumed rather than documented."""
    out = []
    for a in state["audit"]:
        if a["event"] == "resolved" and a.get("value") is not None and _still_human_resolved(state, a.get("paths", [])):
            out.append({"type": "human_scope_assumption", "exception_id": a["exception_id"], "value": a["value"],
                        "by": a["actor"], "note": a["note"], "scope_version": a["after_version"]})
    for a in state["audit"]:
        if a["event"] == "resolved" and a.get("option_id") == "approve_inferred":
            out.append({"type": "inferred_value_approved", "exception_id": a["exception_id"], "paths": a.get("paths", []), "by": a["actor"],
                        "note": a["note"], "scope_version": a["after_version"]})
        elif a["event"] == "ruleset_approved":
            out.append({"type": "quantity_ruleset_approved", "ruleset_id": a["ruleset_id"], "version": a["version"], "sha256": a["sha256"],
                        "by": a["actor"], "note": a["note"]})
        elif a["event"] == "crew_plan_approved":
            out.append({"type": "crew_plan_approved", "plan_version": a["plan_version"], "by": a["actor"], "note": a["note"], "difficulty_source": a["difficulty_source"]})
        elif a["event"] == "addendum_accepted":
            out.append({"type": "addendum_accepted", "source": a["source"], "by": a["actor"], "note": a["note"], "scope_version": a["scope_version"]})
    lr = state["labor_review"]
    if lr["status"] == "decided" and lr["provisional"]:
        out.append({"type": "labor_assumption", "qualification": lr["qualification"], "by": lr["decided_by"],
                    "applicability_review": lr["applicability_review"]})
    for sref, sch in sorted((state.get("footing_schedule") or {}).items()):
        if sch and not sch["posture"]["bid_ready"]:
            out.append({"type": "footing_scope_not_bid_ready", "scope_ref": sref, "release_class": sch["posture"]["release_class"],
                        "reasons": [r["code"] for r in sch["posture"]["reasons"]],
                        "note": f"[{sref}] footing scope is {sch['posture']['release_class']}: footing counts or sizes rest on provisional geometry or human assumptions, "
                                "not documented facts. This is a demonstration result, not a bid-ready price."})
    return out


def release(state, approver, expected_scope_version, expected_proposal_digest, note="", on_release=None):
    """Gate 3. Nothing leaves the system without a named approver bound to the exact pending proposal."""
    _require_open(state)
    if not _named(approver):
        raise GateError("release requires a named approver")
    fresh = _advance(copy.deepcopy(state))  # recompute: never trust a cached estimate
    if fresh["status"] != READY:
        raise GateError(f"cannot release from status {fresh['status']}")
    if expected_scope_version != fresh["scope"]["scope_version"]:
        raise GateError("stale scope version")
    if not (isinstance(expected_proposal_digest, str)
            and hmac.compare_digest(expected_proposal_digest, fresh["proposal_digest"])):
        raise GateError("stale or wrong proposal digest")
    state.clear()
    state.update(fresh)
    state["status"] = RELEASED
    state["released_at"], state["approved_by"] = _utc(), approver
    _log(state, "released", actor=approver, scope_version=state["scope"]["scope_version"],
         proposal_digest=state["proposal_digest"], note=note)
    package = {
        "scope_version": state["scope"]["scope_version"], "proposal_digest": state["proposal_digest"],
        "approved_by": approver, "released_at": state["released_at"], "takeoff": copy.deepcopy(state["takeoff"]),
        "estimate": copy.deepcopy(state["estimate"]), "labor_review": copy.deepcopy(state["labor_review"]),
        "qualifications": qualifications(state), "reconciliation": copy.deepcopy(state["reconciliation"]),
        "advisories": copy.deepcopy([e for e in state["exceptions"] if e["severity"] == "advisory"]),
        "audit": copy.deepcopy(state["audit"])}
    if state.get("ratebook"):
        package.update(ratebook_ref=copy.deepcopy(state["ratebook_ref"]), quantities=copy.deepcopy(state["quantities"]),
                       ruleset={"ruleset_id": state["ruleset"]["ruleset_id"], "version": state["ruleset"]["version"],
                                "sha256": state["ruleset"]["sha256"], "approved_by": rm.ruleset_approval(state)["by"]})
    if state.get("footing_schedule"):
        classes = {sref: sch["posture"]["release_class"] for sref, sch in state["footing_schedule"].items() if sch}
        ready = all(c == "BID_READY" for c in classes.values()) and bool(classes)
        package.update(footing_schedule=copy.deepcopy(state["footing_schedule"]), footing_release_class=classes, bid_ready=ready,
                       release_class="BID_READY" if ready else "QUALIFIED_DEMONSTRATION_ONLY_NOT_BID_READY",
                       artifact_kind="SUBMIT_READY_BID" if ready else "QUALIFIED_FICTIONAL_DEMONSTRATION")
    if on_release:
        on_release(package)
    return package


# ---------------------------------------------------------------- Rate-book mode: rules, rate books, addenda

SOURCE_SHA = re.compile(r"^[0-9a-f]{64}$")
FACT_KEYS = {"value", "status", "evidence", "inference_note", "unit", "price_affecting"}


@_atomic
def approve_quantity_ruleset(state, *, by, note, ruleset_sha256):
    """Scope Gate: a named estimator approves EXACTLY this version of the fitting/hardware quantity rules."""
    _require_open(state)
    _require_actor(by, note)
    if not state.get("ratebook"):
        raise GateError("quantity rules apply only in rate-book pricing mode")
    if not (isinstance(ruleset_sha256, str) and hmac.compare_digest(ruleset_sha256, state["ruleset"]["sha256"])):
        raise GateError("stale or wrong quantity ruleset digest")
    rs = state["ruleset"]
    state["ruleset_approval"] = {"by": by, "note": note, "sha256": rs["sha256"], "ruleset_id": rs["ruleset_id"], "version": rs["version"], "utc": _utc()}
    _log(state, "ruleset_approved", actor=by, note=note, ruleset_id=rs["ruleset_id"], version=rs["version"], sha256=rs["sha256"],
         scope_version=state["scope"]["scope_version"])
    return _advance(state)


@_atomic
def accept_addendum(state, *, by, note, scope_version):
    """Scope Gate: a named human accepts the pricing effect of newly ingested evidence. It is never granted implicitly."""
    _require_open(state)
    _require_actor(by, note)
    pend = state.get("pending_acceptance")
    if not pend:
        raise GateError("no addendum is awaiting acceptance")
    if scope_version != pend["scope_version"] or scope_version != state["scope"]["scope_version"]:
        raise GateError("stale scope version: the scope changed again after this acceptance was offered")
    state["pending_acceptance"] = None
    _log(state, "addendum_accepted", actor=by, note=note, source=pend["source"], scope_version=scope_version)
    return _advance(state)


def _snapshot(state):
    return {"scope_version": state["scope"]["scope_version"], "status": state["status"], "scope": copy.deepcopy(state["scope"]),
            "quantities": copy.deepcopy(state.get("quantities")), "estimate": copy.deepcopy(state.get("estimate")),
            "proposal_digest": state.get("proposal_digest"), "ratebook_ref": copy.deepcopy(state.get("ratebook_ref")),
            "labor_review": copy.deepcopy(state["labor_review"]), "approved_by": state.get("approved_by"), "released_at": state.get("released_at")}


def _supersede_release(state, reason):
    """A released artifact is immutable. A later input invalidates its authority: it moves to history, marked superseded."""
    if state["status"] != RELEASED:
        return
    _log(state, "release_superseded", reason=reason, prior_digest=state["proposal_digest"], approved_by=state.get("approved_by"),
         scope_version=state["scope"]["scope_version"])
    state["history"].append({"kind": "released_artifact", "utc": _utc(), "superseded": True, "reason": reason, "snapshot": _snapshot(state)})
    state["released_at"] = state["approved_by"] = None
    state["status"] = SCOPE_REVIEW


def _push_history(state, snap, kind, **extra):
    state["history"].append({"kind": kind, "utc": _utc(), "superseded": False, "snapshot": snap, **extra})


@_atomic
def attach_ratebook(state, ratebook, *, by, note):
    """Attach (or replace) the project's rate book. The prior estimate version is preserved, the labor decision is
    invalidated if the labor inputs changed, and any release approval tied to the previous rate version is dead:
    the proposal digest binds the exact rate-book content, and a released artifact is superseded, never edited."""
    _require_actor(by, note)
    bad = [f"{p}: {m}" for p, m in jsonschema_lite.problems(ratebook, "ratebook.v1")]
    if bad:
        raise GateError("unusable rate book: " + "; ".join(bad[:5]))
    _class_problem(ratebook, state["policy"])
    old = state.get("ratebook_ref")
    if old and old["content_sha256"] == ratebook["hashes"]["content_sha256"]:
        raise GateError("this exact rate book is already attached")
    problems = pratebook.check_succession(old, ratebook)
    if problems:
        raise GateError("; ".join(f"{p['code']}: {p['message']}" for p in problems))
    _supersede_release(state, "rate book changed")
    wd = state.get("wage_determination")
    if wd and wd["ratebook_labor_sha256"] != ratebook["hashes"]["labor_sha256"]:
        _invalidate_labor(state, "rate-book labor inputs changed")
    before = _snapshot(state)
    _push_history(state, before, "ratebook_change")
    state["ratebook"], state["ratebook_ref"] = copy.deepcopy(ratebook), pratebook.ref(ratebook)
    lr = state["labor_review"]
    if lr["status"] == "decided" and lr.get("ratebook_labor_sha256") == ratebook["hashes"]["labor_sha256"]:
        r = state["ratebook_ref"]      # same labor inputs: decision stands, but its record must name the book now in force
        lr["ratebook_ref"] = copy.deepcopy(r)
        lr["rate_source"] = f"rate book {r['ratebook_id']} v{r['version']} ({r['labor_sha256'][:12]})"
    if state.get("ruleset") is None:
        state.update(ruleset=quantities.load_ruleset(), ruleset_approval=None, quantities=None, pending_acceptance=None, wage_determination=None,
                     crew_plan=None, difficulty_recommendation=None, crew_comparison=None)
        state["rates"] = None
    state["hold"] = None
    _log(state, "ratebook_attached", actor=by, note=note, from_ref=old, to_ref=state["ratebook_ref"], scope_version=state["scope"]["scope_version"])
    _advance(state)
    state["last_change"] = {"cause": "ratebook", "from": old, "to": state["ratebook_ref"], "diff": pcompare.diff(before, _snapshot(state))}
    return state


def _new_fact_problems(fact, source):
    if not isinstance(fact, dict) or not set(fact) <= FACT_KEYS:
        return "must be a fact object {value, status, evidence}"
    if fact.get("status") not in ("confirmed", "inferred"):
        return "an addendum can only establish a fact (confirmed or inferred); humans resolve and nothing may be un-established this way"
    if fact.get("value") is None or isinstance(fact["value"], (dict, list)):
        return "value must be a scalar"
    if fact["status"] == "inferred" and not _named(fact.get("inference_note")):
        return "an inferred fact needs an inference_note"
    ev = fact.get("evidence")
    if not isinstance(ev, list) or not any(
            isinstance(e, dict) and e.get("doc_id") == source["doc_id"] and e.get("doc_revision") == source["doc_revision"]
            and isinstance(e.get("page"), int) and not isinstance(e.get("page"), bool) and e["page"] >= 1 for e in ev):
        return "evidence must cite the ingested document, its revision and a page"
    return None


@_atomic
def revise_scope(state, updates, *, source, by, note):
    """Apply facts newly established by a later document revision (e.g. Addendum 02 sets G3's width).

    `source` = {doc_id, doc_revision (>= 1, strictly newer than anything applied), sha256}. Earlier or duplicate documents,
    facts that contradict a same-or-newer revision, and facts without a citation are refused. The previous estimate version is
    preserved in history, labor and release approvals are invalidated, and a named human must accept the change (Scope Gate)
    before anything proceeds. `by` is the ingesting identity, never an approver."""
    _require_actor(by, note)
    if not state.get("ratebook"):
        raise GateError("addendum revisions are available only in rate-book pricing mode")
    if not (isinstance(source, dict) and _named(source.get("doc_id")) and isinstance(source.get("doc_revision"), int)
            and not isinstance(source.get("doc_revision"), bool) and source["doc_revision"] >= 1
            and isinstance(source.get("sha256"), str) and SOURCE_SHA.match(source["sha256"])):
        raise GateError("source must name doc_id, an integer doc_revision >= 1 and the document sha256")
    rev = source["doc_revision"]
    if any(a["sha256"] == source["sha256"] for a in state["applied_sources"]):
        raise GateError("this exact document was already applied")
    if rev <= state["doc_revision"]:
        raise GateError(f"revision {rev} is not newer than the latest applied revision {state['doc_revision']}; an earlier revision never overrides a later one")
    if not isinstance(updates, list) or not updates:
        raise GateError("updates must be a non-empty list of {path, fact}")
    patch, changes = [], []
    for u in updates:
        if not isinstance(u, dict):
            raise GateError("every update must be an object {path, fact}")
        path, fact = u.get("path"), u.get("fact")
        if not isinstance(path, str) or not path.startswith("/"):
            raise GateError("every update needs a JSON-pointer path")
        why = _new_fact_problems(fact, source)
        if why:
            raise GateError(f"{path}: {why}")
        try:
            old, exists = get_ptr(state["scope"], path), True
        except (KeyError, IndexError, ValueError, TypeError):
            old, exists = None, False
        if exists:
            if not (isinstance(old, dict) and "value" in old and "status" in old):
                raise GateError(f"{path} is not a fact")
        else:
            parent = path.rsplit("/", 1)[0]
            try:
                ok = path.startswith("/global_requirements/") and isinstance(get_ptr(state["scope"], parent), dict)
            except (KeyError, IndexError, ValueError, TypeError):
                ok = False
            if not ok:
                raise GateError(f"{path} does not exist; an addendum may only revise existing facts or add one under /global_requirements")
        old_val = old.get("value") if exists else None
        if exists and old_val is not None and old.get("status") != "unresolved" and old_val != fact["value"]:
            old_rev = max([e.get("doc_revision", 0) for e in old.get("evidence", []) if isinstance(e, dict) and e.get("source_type") != "human_resolution"] or [0])
            if rev <= old_rev:
                raise GateError(f"{path}: revision {rev} contradicts the fact established by revision {old_rev}; it cannot override it")
        if exists and old_val == fact["value"] and old.get("status") == fact["status"]:
            continue
        patch.append({"op": "replace" if exists else "add", "path": path, "value": fact})
        changes.append({"path": path, "before": old_val, "after": fact["value"], "before_status": old.get("status") if exists else None,
                        "supersedes_human_resolution": bool(exists and old.get("status") == "human_resolved")})
    if not patch:
        raise GateError("the addendum changes nothing in the scope")
    new_scope = apply_patch(state["scope"], patch)
    if structural_problems(new_scope):
        raise GateError("the addendum would leave the scope structurally invalid")
    touched = {op["path"] for op in patch}
    for p, msg in value_problems(new_scope):
        if any(p == t or p.startswith(t + "/") for t in touched):
            raise GateError(f"{p}: {msg}")
    _supersede_release(state, f"scope revised by {source['doc_id']} revision {rev}")
    before = _snapshot(state)
    _push_history(state, before, "scope_revision", source=source)
    version = before["scope_version"] + 1
    new_scope["scope_version"] = version
    state["scope"], state["hold"], state["doc_revision"] = new_scope, None, rev
    state["applied_sources"].append(dict(source))
    summary = (f"{source['doc_id']} revision {rev} changed {len(changes)} fact(s): "
               + "; ".join(f"{c['path']} {c['before']!r} -> {c['after']!r}" + (" (OVERRIDES A HUMAN DECISION)" if c["supersedes_human_resolution"] else "") for c in changes) + ".")
    prior = state.get("pending_acceptance")
    state["pending_acceptance"] = {"source": dict(source), "scope_version": version, "summary": ((prior["summary"] + " ") if prior else "") + summary}
    _log(state, "scope_revised", actor=by, note=note, source=dict(source), changes=changes, before_version=before["scope_version"],
         after_version=version, scope_version=version, paths=sorted(touched))
    _invalidate_labor(state, f"scope revised by {source['doc_id']} revision {rev}")
    _advance(state)
    state["last_change"] = {"cause": "addendum", "source": dict(source), "changes": changes, "diff": pcompare.diff(before, _snapshot(state))}
    return state


@_atomic
def record_wage_determination(state, *, by, note, determination, schedule, rows, employer_burden, production_rates_approved,
                              certified_payroll_admin):
    """Labor Gate for a Davis-Bacon / prevailing-wage project: a named human records the wage determination.

      determination  {decision_id, modification, date, valid_through?, source_ref}
      schedule       the decision's own table, transcribed: [{classification, base_rate, fringe_rate}]
      rows           one per cost-bearing labor role: {role_key, classification, classification_status
                     ('listed' | 'proposed_for_conformance' | 'approved_conformance'), conformance_ref (approved only),
                     base_rate, fringe_rate, source_ref}
      employer_burden {pct (of WAGES only), source_ref};  production_rates_approved: True
      certified_payroll_admin {basis: lump_sum|per_week|per_crew_hour|not_charged, unit_cost, weeks, reason, source_ref}

    Structural garbage (wrong types, negative or non-finite numbers) is refused outright. A record that is merely INCOMPLETE or unsupported
    (a role without a classification, an omitted fringe, a classification awaiting conformance, an expired decision) is stored and shown,
    each defect as its own blocker, and the cleared roles are still calculated; pricing and release stay blocked until all are cleared.
    Fully cleared => the Labor Gate decision is derived from this record. Company rates and qualified assumptions never substitute."""
    _require_open(state)
    _require_actor(by, note)
    if not state.get("ratebook"):
        raise GateError("wage determinations are recorded against a rate book's roles")
    if not rm.wage_required(state):
        raise GateError("the scope does not establish that prevailing wage applies; use the labor decision")
    if [e for e in open_blockers(state) if e["code"] not in WAGE_CODES]:
        raise GateError("labor gate is not open: the Scope Gate still has blocking exceptions")
    d = determination if isinstance(determination, dict) else {}
    rows = rows if isinstance(rows, list) else None
    if rows is None or not all(isinstance(r, dict) for r in rows):
        raise GateError("rows must be a list of objects")
    roles_all = rm.labor_roles(state)
    for r in rows:
        for k in ("base_rate", "fringe_rate"):
            if r.get(k) is not None and (not is_number(r[k]) or not math.isfinite(r[k]) or r[k] < 0):
                raise GateError(f"{r.get('role_key')}: {k} must be a non-negative finite number")
    if not isinstance(schedule, list) or not all(isinstance(x, dict) for x in schedule):
        raise GateError("schedule must be a list of {classification, base_rate, fringe_rate}")
    for x in schedule:
        for k in ("base_rate", "fringe_rate"):
            if x.get(k) is not None and (not is_number(x[k]) or not math.isfinite(x[k]) or x[k] < 0):
                raise GateError(f"schedule {x.get('classification')!r}: {k} must be a non-negative finite number")
    if employer_burden is not None and not isinstance(employer_burden, dict):
        raise GateError("employer_burden must be an object")
    if certified_payroll_admin is not None and not isinstance(certified_payroll_admin, dict):
        raise GateError("certified_payroll_admin must be an object")
    prior = state.get("wage_determination")
    if prior and prior["determination"].get("decision_id") == d.get("decision_id"):
        try:
            if int(str(d.get("modification"))) < int(str(prior["determination"]["modification"])):
                raise GateError(f"modification {d.get('modification')} is older than the recorded modification {prior['determination']['modification']}: stale wage decision")
        except ValueError:
            raise GateError("wage decision modifications must be whole numbers") from None
    clean_rows = []
    for r in rows:
        clean_rows.append({k: r.get(k) for k in ("role_key", "classification", "classification_status", "conformance_ref", "base_rate", "fringe_rate", "source_ref")})
    state["wage_determination"] = {
        "determination": {k: d.get(k) for k in ("decision_id", "modification", "date", "valid_through", "source_ref")},
        "schedule": [{k: x.get(k) for k in ("classification", "base_rate", "fringe_rate")} for x in schedule], "rows": clean_rows,
        "employer_burden": copy.deepcopy(employer_burden), "production_rates_approved": production_rates_approved,
        "certified_payroll_admin": copy.deepcopy(certified_payroll_admin),
        "recorded_by": by, "note": note, "recorded_utc": _utc(), "scope_version": state["scope"]["scope_version"],
        "ratebook_labor_sha256": rm.labor_hash(state)}
    _log(state, "wage_determination_recorded", actor=by, note=note, decision_id=d.get("decision_id"), modification=d.get("modification"),
         roles=roles_all, scope_version=state["scope"]["scope_version"])
    return _advance(state)


# ---------------------------------------------------------------- Crew plan: selection, efficiency and job difficulty

@_atomic
def record_difficulty_recommendation(state, *, by, default, overrides=None, evidence_refs=None, rationale=""):
    """Record a RECOMMENDED job difficulty (for example from a model). It has no pricing effect. It is accepted only when it cites document
    evidence, and a named human must approve it in `approve_crew_plan(use_recommendation=True)` before anything is priced."""
    _require_open(state)
    if not _named(by):
        raise GateError("the recommending identity must be named")
    if not state.get("ratebook"):
        raise GateError("difficulty applies to rate-book pricing")
    ov = overrides or {}
    if default not in pcrews.LEVELS or not isinstance(ov, dict) or any(v not in pcrews.LEVELS or k not in vocab.DRIVERS for k, v in ov.items()):
        raise GateError(f"difficulty must be one of {pcrews.LEVELS}; overrides are keyed by labor driver D01-D12")
    refs = evidence_refs
    if not (isinstance(refs, list) and refs and all(isinstance(r, dict) and _named(r.get("doc_id")) and isinstance(r.get("page"), int)
                                                    and not isinstance(r.get("page"), bool) and r["page"] >= 1 for r in refs)):
        raise GateError("a difficulty recommendation must cite document evidence (doc_id and page for each reference)")
    state["difficulty_recommendation"] = {"recommended_by": by, "default": default, "overrides": dict(ov), "evidence_refs": copy.deepcopy(refs),
                                          "rationale": str(rationale)[:1000], "recommended_utc": _utc(), "scope_version": state["scope"]["scope_version"]}
    _log(state, "difficulty_recommended", actor=by, default=default, overrides=dict(ov), scope_version=state["scope"]["scope_version"])
    return _advance(state)


@_atomic
def approve_crew_plan(state, *, by, note, preferred_crew=None, assignments=None, use_default_for_unassigned=False,
                      difficulty=None, use_recommendation=False):
    """Labor Gate: a named human selects the preferred crew and/or a crew per task, and approves the job difficulty.

      difficulty = {default: easy|standard|hard, overrides: {D01..D12: level}}   (human), or use_recommendation=True (the cited AI recommendation,
      adopted as written and recorded as 'ai_recommended_human_approved').
    Refused outright if any task would have no crew (nothing is assumed unless use_default_for_unassigned is stated), if a chosen crew has no
    production rate for the task, if it lacks a required role or qualification (efficiency never makes it eligible), or if the difficulty is invalid.
    Efficiency and difficulty change crew-hours only: they never alter wages, fringes, employer costs or any quantity."""
    _require_open(state)
    _require_actor(by, note)
    if not state.get("ratebook"):
        raise GateError("crew plans apply to rate-book pricing")
    if [e for e in open_blockers(state) if e["code"] not in WAGE_CODES]:
        raise GateError("labor gate is not open: the Scope Gate still has blocking exceptions")
    rb = state["ratebook"]
    if use_recommendation:
        rec = state.get("difficulty_recommendation")
        if not rec:
            raise GateError("there is no difficulty recommendation to approve")
        diff = {"default": rec["default"], "overrides": dict(rec["overrides"]), "source": "ai_recommended_human_approved",
                "evidence_refs": copy.deepcopy(rec["evidence_refs"]), "recommended_by": rec["recommended_by"]}
    else:
        d = difficulty if isinstance(difficulty, dict) else {}
        diff = {"default": d.get("default"), "overrides": dict(d.get("overrides") or {}), "source": "human", "evidence_refs": []}
    cs = pcrews.crews_by_id(rb)
    if preferred_crew is not None and preferred_crew not in pcrews.used_crews(rb):
        raise GateError(f"preferred crew {preferred_crew!r} is not a crew the rate book prices")
    assignments = dict(assignments or {})
    tasks = {t["task_id"] for t in rb["labor_tasks"]}
    if not isinstance(use_default_for_unassigned, bool) or any(k not in tasks or v not in cs for k, v in assignments.items()):
        raise GateError("assignments must map labor task ids to crews defined in the rate book")
    if any(k not in vocab.DRIVERS for k in diff["overrides"]):
        raise GateError("difficulty overrides are keyed by labor driver D01-D12")
    plan = {"plan_version": _next_plan_version(state), "preferred_crew": preferred_crew, "assignments": assignments,
            "use_default_for_unassigned": use_default_for_unassigned, "difficulty": diff, "approved_by": by, "note": note, "approved_utc": _utc(),
            "scope_version": state["scope"]["scope_version"], "ratebook_labor_sha256": rm.labor_hash(state),
            "crew_profiles": {cid: cs[cid]["profile_version"] for cid in pcrews.used_crews(rb)}}
    problems = pcrews.plan_problems(plan, rb)
    if problems:
        raise GateError("crew plan refused: " + "; ".join(f"{p['code']}: {p['message']}" for p in problems[:6]) + (" ..." if len(problems) > 6 else ""))
    if state.get("crew_plan"):
        _retire_crew_plan(state, f"superseded by plan version {plan['plan_version']}")
    state["crew_plan"] = plan
    _log(state, "crew_plan_approved", actor=by, note=note, plan_version=plan["plan_version"], preferred_crew=preferred_crew, assignments=assignments,
         difficulty_source=diff["source"], difficulty_default=diff["default"], scope_version=plan["scope_version"])
    return _advance(state)

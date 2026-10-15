"""Frozen typed interface between the HTTP layer / frontend adapter (ANVIL 1) and the deterministic pricing engine.

CONTRACT_VERSION is bumped only by an agreed change (see docs/pricing/ENGINE_INTERFACE_CONTRACT.md and tests/test_pricing_service.py, which
pins the surface). Every function is a thin, side-effect-explicit wrapper: nothing here computes a price, an hour or a digest itself, and
nothing accepts a rate, wage, production rate or total from a caller. A decision call mutates the project `state` atomically (on any
refusal the state is untouched) and returns a `LaborResult` computed by the real engine from that state.

Errors: `RateBookRejected` (import; `.problems` = codes + cell locations, never cell values) and `workflow.GateError` (decisions)."""
from decimal import Decimal
from typing import Any, Dict, List, Optional, TypedDict

from pricing import crews
from pricing import ratebook as pratebook
from pricing.ratebook import RateBookRejected  # re-exported for the HTTP layer

from . import ratebook_mode as rm
from . import workflow as wf
from .workflow import GateError  # re-exported

CONTRACT_VERSION = "pricing-service.v1"


class ImportResult(TypedDict):
    ratebook: Dict[str, Any]          # server-side only; the HTTP layer must never return this to a browser
    ratebook_ref: Dict[str, Any]      # {ratebook_id, version, effective_date, content_sha256, labor_sha256}
    data_classification: str
    warnings: List[Dict[str, Any]]
    report: Dict[str, Any]


class FleetCrew(TypedDict):
    crew_id: str
    description: str
    profile_version: str
    headcount: int
    efficiency_pct: float
    qualifications: List[str]


class FleetOverview(TypedDict):
    crews: List[FleetCrew]
    fleet_average_efficiency_pct: Optional[float]
    fleet_average_display: Optional[str]          # one decimal, e.g. "95.3"
    crew_count: int
    basis: str


class EligibilityReason(TypedDict, total=False):
    code: str                  # MISSING_REQUIRED_ROLE | MISSING_QUALIFICATION
    role_key: str
    role: str
    qualification: str
    message: str


class CrewEligibility(TypedDict):
    crew_id: str
    eligible: bool
    reasons: List[EligibilityReason]
    production_rate: float
    rate_basis: str
    is_default: bool


class TaskEligibility(TypedDict):
    task_id: str
    task: str
    required_roles: List[str]
    required_qualifications: List[str]
    crews: List[CrewEligibility]


class Blocker(TypedDict):
    code: str
    question: str


class LaborResult(TypedDict):
    contract_version: str
    status: str
    blockers: List[Blocker]
    priced: bool
    crew_plan: Optional[Dict[str, Any]]
    crew_plan_version: Optional[int]
    scenarios: Dict[str, Dict[str, Any]]          # scope_ref -> {labor_subtotal, crew_hours, worker_hours, crew_days, calendar_duration, lines, estimate_total}
    proposal_digest: Optional[str]
    ratebook_ref: Optional[Dict[str, Any]]


# ---------------------------------------------------------------- pure reads (rate book only)

def import_ratebook(data: bytes, *, as_of=None) -> ImportResult:
    """Validate and normalize an uploaded .xlsx. Fails closed: any problem raises `RateBookRejected` and nothing is returned or stored."""
    res = pratebook.import_workbook(data, as_of=as_of) if as_of is not None else pratebook.import_workbook(data)
    rb = res["ratebook"]
    return {"ratebook": rb, "ratebook_ref": pratebook.ref(rb), "data_classification": rb["meta"].get("data_classification"),
            "warnings": res["warnings"], "report": res["report"]}


def fleet_overview(ratebook: Dict[str, Any]) -> FleetOverview:
    """Sidebar: every fleet crew and the fleet average. No crew is dropped for a missing qualification."""
    return crews.fleet_overview(ratebook)


def crew_profiles(ratebook: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Stored profile of every crew the book prices: members, headcount, efficiency, per-level difficulty response, qualifications, version."""
    return [{**c, "headcount": crews.headcount(c)} for c in ratebook["crews"]]


def task_eligibility(ratebook: Dict[str, Any], task_id: str) -> Optional[TaskEligibility]:
    """Which crews may do a task and the specific reason each ineligible one may not. None for an unknown task id."""
    return crews.eligibility(ratebook, task_id)


def all_eligibility(ratebook: Dict[str, Any]) -> List[TaskEligibility]:
    return [crews.eligibility(ratebook, t["task_id"]) for t in ratebook["labor_tasks"]]


# ---------------------------------------------------------------- reads on a project state

def compare_crews(state: Dict[str, Any]) -> Dict[str, Any]:
    """Per scenario: every candidate crew for every task (eligibility, hours, worker-hours, crew-days, cost, cost per unit). Empty until the
    Scope Gate has produced quantities. Before a plan exists the difficulty shown is a marked provisional Standard; it prices nothing."""
    return state.get("crew_comparison") or {}


def provisional_labor(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Indicative per-scenario labor when NO plan is approved: per task, the mean cost of the FLEET crews eligible for that task. Never releasable."""
    fleet = set(crews.fleet_crew_ids(state["ratebook"]))
    return {sref: crews.provisional_labor(c, fleet) for sref, c in compare_crews(state).items()}


def labor_result(state: Dict[str, Any]) -> LaborResult:
    """What the engine currently says about labor for this project. Every number is read from the engine's own estimate."""
    est = state.get("estimate")
    scen: Dict[str, Dict[str, Any]] = {}
    for sref, e in ((est or {}).get("scenarios") or {}).items():
        lab = e["labor"]
        scen[sref] = {"labor_subtotal": lab["subtotal"], "crew_hours": lab["crew_hours"], "worker_hours": lab["worker_hours"],
                      "crew_days": lab["crew_days"], "calendar_duration": lab["calendar_duration"], "basis": lab["basis"], "lines": lab["lines"],
                      "estimate_total": e.get("price_total")}
    plan = state.get("crew_plan")
    return {"contract_version": CONTRACT_VERSION, "status": state["status"],
            "blockers": [{"code": x["code"], "question": x.get("question", "")} for x in wf.open_blockers(state)],
            "priced": est is not None, "crew_plan": plan, "crew_plan_version": plan["plan_version"] if plan else None,
            "scenarios": scen, "proposal_digest": state.get("proposal_digest"), "ratebook_ref": state.get("ratebook_ref")}


def crew_plan_history(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every crew plan ever approved on this project, oldest first, the current one last. Versions only increase and are never reused."""
    return list(state.get("crew_plan_history", [])) + ([state["crew_plan"]] if state.get("crew_plan") else [])


def digest_is_current(state: Dict[str, Any], digest: str) -> Dict[str, Any]:
    """Whether a previously shown proposal digest still matches what the engine would release now (it never does after a change to crew
    plan, crew profile version, production rate, difficulty, wage determination, quantities, rate book or scope)."""
    cur = state.get("proposal_digest")
    return {"current": bool(cur) and cur == digest, "current_digest": cur}


# ---------------------------------------------------------------- decisions (named human, atomic)

def record_wage_decision(state: Dict[str, Any], **kw) -> LaborResult:
    """Prevailing-wage / Davis-Bacon classification, wage and fringe decision. Arguments exactly as `workflow.record_wage_determination`."""
    wf.record_wage_determination(state, **kw)
    return labor_result(state)


def adopt_crew_plan(state: Dict[str, Any], *, by: str, note: str, preferred_crew: Optional[str] = None,
                    assignments: Optional[Dict[str, str]] = None, use_default_for_unassigned: bool = False,
                    difficulty: Optional[Dict[str, Any]] = None, use_recommendation: bool = False) -> LaborResult:
    """Adopt a crew plan (mixed crews via `assignments`: task_id -> crew_id). Refused (GateError, state untouched) when any task has no crew
    selected, a selected crew is ineligible or has no production rate, difficulty is invalid, or a Scope Gate blocker is open. On success
    the engine has already recomputed labor, the estimate and the digest."""
    wf.approve_crew_plan(state, by=by, note=note, preferred_crew=preferred_crew, assignments=assignments,
                         use_default_for_unassigned=use_default_for_unassigned, difficulty=difficulty, use_recommendation=use_recommendation)
    return labor_result(state)


def recommend_difficulty(state: Dict[str, Any], **kw) -> LaborResult:
    """Record a cited difficulty recommendation. Prices nothing until `adopt_crew_plan(use_recommendation=True)`."""
    wf.record_difficulty_recommendation(state, **kw)
    return labor_result(state)


# The pinned public surface. tests/test_pricing_service.py compares this to docs/pricing/engine_interface.v1.json.
SURFACE = {
    "contract_version": CONTRACT_VERSION,
    "reads_ratebook": ["import_ratebook", "fleet_overview", "crew_profiles", "task_eligibility", "all_eligibility"],
    "reads_state": ["compare_crews", "provisional_labor", "labor_result", "crew_plan_history", "digest_is_current"],
    "decisions": ["record_wage_decision", "adopt_crew_plan", "recommend_difficulty"],
    "errors": ["RateBookRejected", "GateError"],
    "labor_result_keys": ["contract_version", "status", "blockers", "priced", "crew_plan", "crew_plan_version", "scenarios", "proposal_digest", "ratebook_ref"],
    "scenario_keys": ["labor_subtotal", "crew_hours", "worker_hours", "crew_days", "calendar_duration", "basis", "lines", "estimate_total"],
    "fleet_overview_keys": ["crews", "fleet_average_efficiency_pct", "fleet_average_display", "crew_count", "basis"],
    "eligibility_reason_codes": ["MISSING_REQUIRED_ROLE", "MISSING_QUALIFICATION"],
}

"""overrides_acknowledged: recorded ONLY at release. Lists each run-time override in force for the released estimate revision, with the releaser, the UTC time,
the scope version and the estimate / proposal revision. Nothing exists before release; a superseded release moves the block into history with the release.
Read-only with respect to prices: it changes no total, label, rule or fingerprint."""
import copy

from pricing.engine import GATE_ASSEMBLY_RATE, GATE_OVERRIDE_IDS, REPLACED_GATE_MATERIALS
from . import assumptions, bid_schedule

OWNER = assumptions.OWNER


def _decision(when):
    return {"by": OWNER, "decided": when}


def _in_force(state):
    est = state.get("estimate") or {}
    scs = est.get("scenarios") or {}
    out = []
    gate = {s: assumptions.gate_assembly_lines(sc) for s, sc in scs.items() if any(l["item_id"] in GATE_OVERRIDE_IDS.values() for l in sc["materials"]["lines"])}
    if gate:
        out.append({"id": "gate_assembly_rate", "name": "Complete furnished gate assembly, per LF of clear opening", "decision": _decision("2026-10-16 13:27 CT"),
                    "value": {"rate_per_lf": float(GATE_ASSEMBLY_RATE), "material_tax_pct": 0, "replaces": sorted(REPLACED_GATE_MATERIALS), "gate_lines": gate},
                    "statement": "Gate assembly material furnished at the owner's rate per LF of scope clear-opening width per gate; the replaced gate material lines are not priced."})
    taxed = [s for s, sc in scs.items() if (sc.get("sales_tax") or {}).get("exemption_applies")]
    if taxed:
        note = next((q["note"] for sc in scs.values() for q in sc.get("qualifications", []) if q.get("type") == "owner_sales_tax_exemption"), None)
        out.append({"id": "material_tax_exemption", "name": "Owner sales-tax exemption on incorporated materials", "decision": _decision("2026-10-16"),
                    "value": {"scenarios": sorted(taxed), "material_tax_pct": 0}, "statement": note or "Owner is exempt from sales and use tax on materials incorporated into the Work."})
    bs = bid_schedule.view(state)
    if bs.get("available") and any(s.get("available") for s in (bs.get("scenarios") or {}).values()):
        out.append({"id": "item_16_labor_coverage", "name": "Item 16 installation labor is covered by the top-rail task", "decision": _decision("2026-10-16 10:05 CT"),
                    "value": {"item": 16, "labor_task": "L04", "driver": "D06", "own_labor": 0}, "statement": bid_schedule.NOTE_16})
        out.append({"id": "allowances", "name": "Allowances", "decision": _decision("2026-10-16 10:05 CT"),
                    "value": {"amount": 0.0, "locked": True}, "statement": "No allowances are carried."})
    adm = (state.get("wage_determination") or {}).get("certified_payroll_admin") or {}
    if adm.get("basis") == "not_charged":
        out.append({"id": "certified_payroll_zero", "name": "Certified-payroll administration", "decision": _decision("2026-10-16 14:51 CT"),
                    "value": {"amount": 0.0, "basis": "not_charged", "reason": adm.get("reason"), "source_ref": adm.get("source_ref")},
                    "statement": "Certified-payroll administration: $0.00; the pinned workbook carries no such line."})
    return out


def build(state, releaser, released_utc):
    """The block for a release that is happening now. None for a project with no rate-book estimate."""
    if not state.get("ratebook") or not state.get("estimate"):
        return None
    est = state["estimate"]
    bids = {s: v["bid_revision"] for s, v in (bid_schedule.view(state).get("scenarios") or {}).items() if v.get("available")}
    ack = {"released_by": releaser, "released_utc": released_utc, "scope_version": state["scope"]["scope_version"],
           "proposal_digest": state["proposal_digest"], "estimate_digest": est.get("digest"), "bid_revisions": bids}
    ov = []
    for o in _in_force(state):
        ov.append({**copy.deepcopy(o), "acknowledged_by": releaser, "acknowledged_utc": released_utc, "scope_version": ack["scope_version"],
                   "proposal_digest": ack["proposal_digest"]})
    ack["overrides"] = ov
    return ack

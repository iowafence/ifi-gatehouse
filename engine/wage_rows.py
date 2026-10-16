"""Wage rows for a prevailing-wage record, built from the pinned rate book and the wage decision's schedule (owner rule 2026-10-16 2:15 PM CT):
the role's workbook rate is used when it is at or above the Attachment A floor for the assigned classification, otherwise the floor, FLAGGED.
Fringe is the schedule's fringe for the classification (the workbook carries no fringe). The classification for each role is a person's
assignment passed in; nothing here chooses it."""
from decimal import Decimal as D


def burden_pct(ratebook):
    """The rate book's employer burden if every role carries the same one; otherwise refuse (no averaging, no guessing)."""
    pcts = {r["burden_pct"] for r in ratebook["roles"]}
    if len(pcts) != 1:
        raise ValueError("the rate book roles carry different burden percentages; one must be chosen by a person")
    return next(iter(pcts))


def rows_from_workbook(ratebook, schedule, mapping, source_ref):
    sched = {s["classification"].strip().lower(): s for s in schedule}
    roles = {r["role_key"]: r for r in ratebook["roles"]}
    rows = []
    for rk, cls in mapping.items():
        s, w = sched.get((cls or "").strip().lower()), roles[rk]["base_wage_per_hr"]
        if s is None:
            raise ValueError(f"{rk}: classification {cls!r} is not in the wage decision's schedule")
        raised = D(str(w)) < D(str(s["base_rate"]))
        rows.append({"role_key": rk, "classification": s["classification"], "classification_status": "listed", "base_rate": s["base_rate"] if raised else w,
                     "fringe_rate": s["fringe_rate"], "source_ref": source_ref, "workbook_rate_per_hr": w,
                     "floor_adjustment": (f"workbook rate {w:g} is below the Attachment A floor {s['base_rate']:g} for {s['classification']}; priced at the floor") if raised else None})
    return rows

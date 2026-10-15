"""Gate #1 trigger rules. All CODE. Model confidence is never a trigger."""
from .util import walk_facts, get_ptr
from .takeoff import compute_takeoff, derive_pay_qty
from .guards import structural_problems, value_problems, geometry_problems

BLOCKING_STAGE = "pricing"


def _label(path):
    return path.strip("/").replace("/", " > ")


def _human_ev(note="", by=""):
    ev = {"doc_id": "human", "page": 1, "source_type": "human_resolution", "excerpt": note}
    if by:
        ev["by"] = by
    return ev


def _resolve_patch(path, fact, value, note="", by=""):
    new = dict(fact)
    new["value"] = value
    new["status"] = "human_resolved"
    new["evidence"] = list(fact.get("evidence", [])) + [_human_ev(note, by)]
    return [{"op": "replace", "path": path, "value": new}]


def _ex(code, severity, path, question, evidence, options=None, waived=(), free_text=True):
    eid = f"EX-{code}-{path}"
    if eid in waived:
        return None
    return {
        "exception_id": eid, "code": code, "severity": severity,
        "affects": [path], "blocks_stage": BLOCKING_STAGE if severity == "blocking" else None,
        "question": question, "evidence": evidence,
        "candidate_resolutions": options or [], "allows_free_text_resolution": free_text,
        "status": "open",
    }


def detect(scope, rules=None, waived=(), strict_inferred=False):
    """Return (exceptions, takeoff_or_None, reconciliation). Takeoff only runs when no fact-level blockers.

    strict_inferred (rate-book pricing mode): an inferred, price-affecting fact is a blocking exception until a named
    human approves it as a qualified assumption or supplies the documented value. Legacy mode lets it flow."""
    waived = set(waived)
    exs = []

    # Fail closed first: a scope that cannot be interpreted is never priced and cannot be waived or
    # resolved by a free-text value. Checked before anything dereferences scope keys.
    bad = structural_problems(scope)
    if bad:
        return [_ex("FOOTING_UNIT_INVALID" if msg.startswith("FOOTING_UNIT_INVALID:") else "SCOPE_INVALID", "blocking", path, f"{path}: {msg}. Re-run extraction; this cannot be "
                    "resolved by typing a value.", [], None, (), free_text=False) for path, msg in bad], None, []
    if not scope["fence_runs"]:
        return [_ex("EMPTY_SCOPE", "blocking", "/fence_runs",
                    "The scope contains no fence runs, so there is nothing to price.", [], None, (),
                    free_text=False)], None, []

    alternates = scope.get("bid_structure", {}).get("alternates", [])
    sel_path = "/bid_structure/selected_bid"

    for path, fact in walk_facts(scope):
        status = fact.get("status")
        if status == "human_resolved":
            continue
        ev = fact.get("evidence", [])
        stated = [(e.get("stated_value"), e.get("source_type"), e.get("sheet_label") or e.get("doc_id"))
                  for e in ev if e.get("stated_value") is not None]
        distinct = {s[0] for s in stated}

        if path == sel_path:
            if alternates and status == "unresolved":
                opts = [{"option_id": "base", "label": "Price the base bid",
                         "patch": [{"op": "replace", "path": sel_path,
                                    "value": {"value": "base", "status": "human_resolved",
                                              "evidence": [_human_ev("selected base")]}}]}]
                for alt in alternates:
                    opts.append({"option_id": alt["alternate_id"], "label": f"Price alternate: {alt['label']}",
                                 "patch": list(alt.get("patch", [])) + [
                                     {"op": "replace", "path": sel_path,
                                      "value": {"value": alt["alternate_id"], "status": "human_resolved",
                                                "evidence": [_human_ev(f"selected {alt['alternate_id']}")]}}]})
                e = _ex("BID_SELECTION_REQUIRED", "blocking", path,
                        "Which bid should be priced: base or an alternate?", ev, opts, waived)
                if e:
                    exs.append(e)
            continue

        conflict = len(distinct) > 1
        if conflict:
            kinds = {s[1] for s in stated}
            code = "SPEC_INTERNAL_CONFLICT" if len(kinds) == 1 else "PLAN_SPEC_CONFLICT"
            detail = "; ".join(f"{s[0]} ({s[1]}, {s[2]})" for s in stated)
            opts = [{"option_id": f"v:{v}", "label": f"Use {v}",
                     "patch": _resolve_patch(path, fact, v, "chose among conflicting documents")}
                    for v in sorted(distinct, key=str)]
            e = _ex(code, "blocking", path, f"{_label(path)}: documents disagree: {detail}. Which governs?",
                    ev, opts, waived)
        elif status == "unresolved":
            if fact.get("price_affecting") is False:
                e = _ex("OWNER_SELECTION_PENDING", "advisory", path,
                        f"{_label(path)} is an owner selection and does not affect price.", ev, None, waived)
            else:
                e = _ex("MISSING_VALUE", "blocking", path,
                        f"{_label(path)} is not supported by the documents.", ev, None, waived)
        elif status == "inferred" and strict_inferred and fact.get("price_affecting") is not False:
            note = fact.get("inference_note") or "no inference note"
            opts = [{"option_id": "approve_inferred", "label": f"Approve inferred value {fact.get('value')!r} as a qualified assumption",
                     "patch": _resolve_patch(path, fact, fact.get("value"), "approved inferred value as a qualified assumption")}]
            e = _ex("INFERRED_FACT_UNAPPROVED", "blocking", path,
                    f"{_label(path)} = {fact.get('value')!r} is inferred ({note}), not stated in the documents. Approve it as a qualified "
                    "assumption or enter the documented value.", ev, opts, waived)
        else:
            e = None
        if e:
            exs.append(e)

    for a in scope.get("accessories", []):
        if a.get("order_after_field_measure"):
            e = _ex("FIELD_VERIFY_REQUIRED", "advisory", f"/accessories/{a['accessory_id']}",
                    f"{a['accessory_id']}: final quantity is set by field measurement after install.", [], None, waived)
            if e:
                exs.append(e)

    out_of_scope = [p for p in scope.get("bid_structure", {}).get("pay_items", []) if p.get("in_engine_scope") is False]
    if out_of_scope:
        e = _ex("PAYITEM_NOT_IN_SCOPE", "advisory", "/bid_structure/pay_items",
                "Non-fence pay items detected and routed to a human, not priced: "
                + ", ".join(f"#{p['item_no']} {p['description']}" for p in out_of_scope), [], None, waived)
        if e:
            exs.append(e)

    for path, msg in value_problems(scope):
        exs.append(_ex("INVALID_VALUE", "blocking", path, f"{_label(path)}: {msg}. Supply a documented value.",
                       [], None, ()))
    for path, msg in geometry_problems(scope):
        exs.append(_ex("GEOMETRY_INVALID", "blocking", path, f"{_label(path)}: {msg}.", [], None, ()))

    if any(e["severity"] == "blocking" for e in exs):
        return exs, None, []

    try:
        takeoff = compute_takeoff(scope, rules)
        recon = reconcile(scope, takeoff)
    except (KeyError, TypeError, ValueError, ZeroDivisionError, ArithmeticError) as exc:
        return [_ex("SCOPE_INVALID", "blocking", "/", f"takeoff could not be computed ({type(exc).__name__}: {exc})",
                    [], None, (), free_text=False)], None, []
    if not takeoff["runs"] or not takeoff["totals"]["fence_lf"] > 0:
        return [_ex("EMPTY_SCOPE", "blocking", "/fence_runs",
                    "The takeoff contains no fence length, so there is nothing to price.", [], None, (),
                    free_text=False)], None, []
    for r in recon:
        if r["status"] == "mismatch":
            e = _ex("QUANTITY_UNSUPPORTED", "blocking", f"/bid_structure/pay_items/{r['item_no']}",
                    f"Pay item #{r['item_no']}: derived {r['derived_qty']} vs stated {r['stated_qty']} "
                    f"(delta {r['delta']}). Plans and quantity table disagree.", [], None, waived)
            if e:
                exs.append(e)
    return exs, takeoff, recon


def reconcile(scope, takeoff):
    """Derived-from-plans vs stated-in-table, per pay item. Computed by CODE."""
    selected = scope.get("bid_structure", {}).get("selected_bid", {}).get("value", "base")
    key = "stated_qty_alt" if selected not in (None, "base") else "stated_qty_base"
    out = []
    for p in scope.get("bid_structure", {}).get("pay_items", []):
        if p.get("in_engine_scope") is False or not p.get("maps_to"):
            continue
        stated = p.get(key)
        if stated is None:
            continue
        derived = derive_pay_qty(takeoff, p["maps_to"])
        delta = round(derived - stated, 2)
        tol = 0.0 if p["unit"] == "EA" else max(1.0, 0.01 * stated)
        status = "match" if delta == 0 else ("within_tolerance" if abs(delta) <= tol else "mismatch")
        out.append({"item_no": p["item_no"], "description": p["description"], "unit": p["unit"],
                    "derived_qty": derived, "stated_qty": stated, "delta": delta,
                    "tolerance": tol, "status": status})
    return out

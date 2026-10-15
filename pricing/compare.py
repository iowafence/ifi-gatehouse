"""Before/after comparison of two estimate versions (an addendum or a rate-book change). Pure data in, data out.

A snapshot is {'scope_version', 'quantities': {scope_ref: quantity_payload.v1} | None, 'estimate': estimate.v1 | None}.
Either side may lack an estimate (it was blocked then): quantities are still compared, costs only when both exist."""
from decimal import Decimal


def _d(x):
    return Decimal(repr(x)) if isinstance(x, float) else Decimal(x)


def _delta(a, b):
    if a is None or b is None:
        return None
    d = _d(b) - _d(a)
    return float(d) if d != d.to_integral_value() else int(d)


def _qmap(snapshot):
    out = {}
    for sref, p in ((snapshot or {}).get("quantities") or {}).items():
        for it in p["items"]:
            out[(sref, it.get("item_id") or it.get("driver_key"))] = it
    return out


def diff(before, after):
    qb, qa = _qmap(before), _qmap(after)
    quantities = []
    for k in sorted(set(qb) | set(qa)):
        b, a = qb.get(k), qa.get(k)
        bq, aq = (b or {}).get("quantity"), (a or {}).get("quantity")
        if b is not None and a is not None and bq == aq and b["status"] == a["status"]:
            continue
        quantities.append({"scope_ref": k[0], "key": k[1], "uom": (a or b)["uom"], "before": bq, "after": aq, "delta": _delta(bq, aq),
                           "status_before": (b or {}).get("status"), "status_after": (a or {}).get("status")})
    out = {"from_scope_version": (before or {}).get("scope_version"), "to_scope_version": (after or {}).get("scope_version"),
           "quantities": quantities, "costs": {}, "material_lines": [], "labor_lines": [],
           "ratebook_before": None, "ratebook_after": None, "ratebook_changed": False}
    eb, ea = (before or {}).get("estimate"), (after or {}).get("estimate")
    eb, ea = (eb if eb and "scenarios" in eb else None), (ea if ea and "scenarios" in ea else None)   # legacy estimates have no scenarios
    out["ratebook_before"] = eb and eb["ratebook_ref"]
    out["ratebook_after"] = ea and ea["ratebook_ref"]
    out["ratebook_changed"] = bool(eb and ea and eb["ratebook_ref"]["content_sha256"] != ea["ratebook_ref"]["content_sha256"])
    if not (eb and ea):
        return out
    for sref in sorted(set(eb["scenarios"]) ^ set(ea["scenarios"])):
        only = eb["scenarios"].get(sref) or ea["scenarios"][sref]
        b, a = (only["price_total"], None) if sref in eb["scenarios"] else (None, only["price_total"])
        out["costs"][sref] = {"price_total": {"before": b, "after": a, "delta": None}}
    for sref in sorted(set(eb["scenarios"]) & set(ea["scenarios"])):
        sb, sa = eb["scenarios"][sref], ea["scenarios"][sref]
        rows = {"materials": (sb["materials"]["subtotal"], sa["materials"]["subtotal"]), "sales_tax": (sb["sales_tax"]["amount"], sa["sales_tax"]["amount"]),
                "labor": (sb["labor"]["subtotal"], sa["labor"]["subtotal"]), "equipment": (sb["equipment"]["subtotal"], sa["equipment"]["subtotal"]),
                "mobilization": (sb["mobilization"]["subtotal"], sa["mobilization"]["subtotal"]), "direct_cost": (sb["direct_cost"], sa["direct_cost"]),
                "overhead": (sb["overhead"]["amount"], sa["overhead"]["amount"]), "contingency": (sb["contingency"]["amount"], sa["contingency"]["amount"]),
                "profit": (sb["profit"]["amount"], sa["profit"]["amount"]), "price_total": (sb["price_total"], sa["price_total"])}
        out["costs"][sref] = {k: {"before": b, "after": a, "delta": _delta(b, a)} for k, (b, a) in rows.items()}
        mb = {l["item_id"]: l for l in sb["materials"]["lines"]}
        ma = {l["item_id"]: l for l in sa["materials"]["lines"]}
        for k in sorted(set(mb) | set(ma)):
            b, a = mb.get(k), ma.get(k)
            if b and a and b["order_quantity"] == a["order_quantity"] and b["extended"] == a["extended"]:
                continue
            out["material_lines"].append({"scope_ref": sref, "item_id": k, "order_before": (b or {}).get("order_quantity", 0),
                                          "order_after": (a or {}).get("order_quantity", 0), "extended_before": (b or {}).get("extended", 0),
                                          "extended_after": (a or {}).get("extended", 0),
                                          "delta": _delta((b or {}).get("extended", 0), (a or {}).get("extended", 0))})
        lb = {l["task_id"]: l for l in sb["labor"]["lines"]}
        la = {l["task_id"]: l for l in sa["labor"]["lines"]}
        for k in sorted(set(lb) | set(la)):
            b, a = lb.get(k), la.get(k)
            if b and a and b["crew_hours"] == a["crew_hours"] and b["extended"] == a["extended"]:
                continue
            out["labor_lines"].append({"scope_ref": sref, "task_id": k, "hours_before": (b or {}).get("crew_hours", 0), "hours_after": (a or {}).get("crew_hours", 0),
                                       "cost_before": (b or {}).get("extended", 0), "cost_after": (a or {}).get("extended", 0),
                                       "delta": _delta((b or {}).get("extended", 0), (a or {}).get("extended", 0))})
    return out

"""Per-item bid schedule (ALLOC-V1): splits the engine's own scenario figures over bid items 10-16 and reconciles to the cent.

Nothing is added or invented here: every cent of the engine's materials, tax, labor, shared pool, overhead, contingency and profit lands on
exactly one item, by a fixed attribution table (KEY -> basis) driven by the takeoff, the footing schedule and the gate list. If any engine
line has no rule, a basis has no weight, or the attributed direct cost does not equal the engine's direct cost to the cent, NO schedule is
produced (a refusal with a stable code). Alternate A-1 is its own schedule and is never combined with the Base Bid."""
import hashlib
import json
import math
from decimal import Decimal as D, ROUND_HALF_UP
from fractions import Fraction

from pricing import quantities, vocab

METHOD, TABLE_VERSION = "ALLOC-V1", "ALLOC-V1-T1"
CENT = D("0.01")
ITEMS = {10: ("120\" CHAINLINK FENCE (TYPE A)", "LF"), 11: ("42\" CHAINLINK DIVIDER FENCE (TYPE B)", "LF"),
         12: ("GATE G1, 48\" WIDE, 84\" TALL", "EA"), 13: ("GATE G2, 144\" WIDE (DOUBLE LEAF), 84\" TALL", "EA"),
         14: ("GATE G3, 84\" TALL", "EA"), 15: ("9' WINDSCREEN, COMPLETE", "LF"), 16: ("FENCE GUARD", "LF")}
GATE_ITEM = {"G1": 12, "G2": 13, "G3": 14}
CLASS_ITEM = {"A_CORNER_TERMINAL": 10, "A_LINE": 10, "GATE_G1": 12, "GATE_G2": 13, "GATE_G3": 14, "B_TERMINAL": 11, "B_LINE": 11}
NOTE_16 = "included in top-rail task"

# KEY -> (basis, why). The table is DATA: it is printed into the contract from this dict and hashed into every schedule.
MATERIALS = {
    "M01": ("TERMINALS_A", "terminal/corner posts plus 2 per gate: corners to item 10, gate posts to their gate"),
    "M02": ("A_LINE_POSTS", "Type A line posts"), "M03": ("B_TERMINAL_POSTS", "Type B terminal posts"), "M04": ("B_LINE_POSTS", "Type B line posts"),
    "M05": ("GROSS_RUN_AB", "top rail by gross run length (continuous across gate openings)"), "M06": ("ITEM_10", "mid rail is Type A only"),
    "M07": ("RAIL_LF_AB", "rail sleeves in proportion to rail LF per fence type"), "M08": ("ITEM_10", "truss rods at Type A braces"),
    "M09": ("ITEM_10", "brace bands"), "M10": ("ITEM_10", "brace bands"), "M11": ("RAIL_LF_AB", "rail end cups in proportion to rail LF"),
    "M12": ("TERMINALS_A", "Type A tension bars at terminal, corner and gate posts"), "M13": ("ITEM_11", "Type B tension bars"),
    "M14": ("TERMINALS_A", "Type A tension bands"), "M15": ("ITEM_11", "Type B tension bands"), "M16": ("TERMINALS_A", "post caps on Type A terminal posts"),
    "M17": ("LINE_CAPS_A_B_TERM", "caps on 2.375 OD posts: Type A line posts and Type B terminals"), "M18": ("ITEM_11", "caps on Type B line posts"),
    "M19": ("ITEM_10", "Type A net fabric"), "M20": ("ITEM_11", "Type B net fabric"), "M21": ("GATE_WIDTH", "gate leaf fabric by gates x clear width"),
    "M22": ("GATE_WIDTH", "transom fabric by gates x clear width"), "M23": ("NET_LF_AB", "bottom tension wire by net fence LF"),
    "M24": ("ITEM_10", "ties to Type A line posts"), "M25": ("ITEM_11", "ties to Type B line posts"),
    "M26": ("RAIL_LINES_AB", "ties to rails: Type A has two rail lines, Type B one"), "M27": ("NET_LF_AB", "tension-wire ties by net fence LF"),
    "M28": ("GATE_PIPE", "gate frame pipe by gates x leaves x (2 verticals + 3 horizontals)"), "M29": ("GATE_LEAVES", "frame elbows"),
    "M30": ("GATE_LEAVES", "frame tees"), "M31": ("GATE_LEAVES", "leaf truss rods"), "M32": ("GATE_LEAVES", "hinges"), "M33": ("GATE_QTY", "latches, one per gate"),
    "M34": ("GATE_LEAVES", "hold-backs"), "M35": ("GATE_WIDTH", "header rail by clear width"), "M36": ("GATE_LEAVES", "leaf tension bars"),
    "M37": ("GATE_LEAVES", "leaf tension bands"), "M38": ("ITEM_15", "windscreen"), "M39": ("ITEM_15", "windscreen cable ties"),
    "M40": ("CONCRETE_BY_CLASS", "concrete by footing class volume"), "M42": ("ITEM_16", "fence guard"),
    "M43": ("GATE_DOUBLE", "center drop rod, double-leaf gates only"), "M44": ("GATE_DOUBLE", "ground sockets, double-leaf gates only")}
LABOR = {
    "L01": ("GROSS_RUN_AB", "layout and stakeout by gross run length"), "L02": ("HOLES_BY_CLASS", "drilling by footing holes per class"),
    "L03": ("POSTS_BY_CLASS", "set posts and concrete by posts per class"),
    "L04": ("GROSS_RUN_AB", "top rail and brace rail: stays with the fence whose rail it installs; the fence guard (item 16) carries NO labor of its own"),
    "L05": ("ITEM_10", "braces at Type A posts"), "L06": ("NET_LF_AB", "fabric by net fence LF"), "L07": ("NET_LF_AB", "bottom tension wire by net fence LF"),
    "L08": ("GATE_QTY", "hang gates, per gate"), "L09": ("ITEM_15", "install windscreen"), "L10": ("GROSS_RUN_AB", "cleanup by gross run length")}
POOL = ("services (core drilling)", "certified-payroll administration", "equipment", "mobilization")   # spread over items in proportion to attributed cost


class Refused(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def table_sha256():
    return hashlib.sha256(json.dumps({"v": TABLE_VERSION, "M": MATERIALS, "L": LABOR, "pool": POOL}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def table_markdown():
    rows = ["| Key | Basis | Why |", "|---|---|---|"]
    for k, (b, w) in sorted({**MATERIALS, **LABOR}.items()):
        rows.append(f"| {k} | {b} | {w} |")
    return "\n".join(rows)


def _d(x):
    return D(str(x))


def spread(total_cents, weights):
    """Largest-remainder split of whole cents by weights. Remainder cents go to the largest fractional remainders; ties to the lowest key."""
    keys = sorted(k for k, w in weights.items() if w > 0)
    if total_cents == 0:
        return {k: 0 for k in weights}
    if not keys:
        raise Refused("ATTRIBUTION_ZERO_WEIGHT", "a cost has no weight to be spread over")
    tot = sum(Fraction(weights[k]) for k in keys)
    exact = {k: Fraction(total_cents) * Fraction(weights[k]) / tot for k in keys}
    out = {k: math.floor(exact[k]) for k in keys}
    left = total_cents - sum(out.values())
    for k in sorted(keys, key=lambda k: (-(exact[k] - out[k]), k))[:left]:
        out[k] += 1
    return {**{k: 0 for k in weights}, **out}


def cents(x):
    return int((_d(x) * 100).to_integral_value(rounding=ROUND_HALF_UP))


def money(c):
    return float(D(c) / 100)


def split_markup(attributed, pool_cents, overhead_cents, contingency_cents, profit_cents):
    """Steps 2-4 on whole cents. attributed = {item: cents}. Returns per-item {pool, direct, overhead, contingency, subtotal, profit, amount}."""
    pool = spread(pool_cents, attributed)
    direct = {i: attributed[i] + pool[i] for i in attributed}
    ov, ct = spread(overhead_cents, direct), spread(contingency_cents, direct)
    sub = {i: direct[i] + ov[i] + ct[i] for i in direct}
    pr = spread(profit_cents, sub)
    return {i: {"shared": pool[i], "direct": direct[i], "overhead": ov[i], "contingency": ct[i], "subtotal": sub[i], "profit": pr[i], "amount": sub[i] + pr[i]} for i in attributed}


def printed_prices(amount_cents, quantity):
    """Unit price = amount / quantity, half-up to the cent; the printed unit price governs the extension."""
    up = (D(amount_cents) / 100 / _d(quantity)).quantize(CENT, rounding=ROUND_HALF_UP)
    return up, (up * _d(quantity)).quantize(CENT, rounding=ROUND_HALF_UP)


class _Ctx:
    def __init__(self, state, sref):
        scopes = quantities.scenario_scopes(state["scope"])
        if sref not in scopes:
            raise Refused("SCENARIO_SCOPE_UNAVAILABLE", f"the scope for {sref} is not recoverable from the current selection")
        payload = (state.get("quantities") or {}).get(sref)
        fs = (state.get("footing_schedule") or {}).get(sref)
        if not payload or not fs:
            raise Refused("INPUTS_UNAVAILABLE", "the quantity payload or footing schedule for this scenario is not available")
        self.q = {(i.get("item_id") or i.get("driver_key")): _d(i["quantity"]) for i in payload["items"]}
        self.cls = {c["post_class"]: c for c in fs["classes"]}
        kinds = state["ruleset"]["rules"]["gate_kinds"]
        self.gates = []
        for g in scopes[sref].get("gates") or []:
            gid = g.get("gate_id")
            if gid not in GATE_ITEM:
                raise Refused("UNKNOWN_GATE", f"gate {gid!r} has no bid item")
            w = g.get("clear_width_ft")
            w = w.get("value") if isinstance(w, dict) else w
            h = g.get("height_ft")
            h = h.get("value") if isinstance(h, dict) else h
            kind = g.get("gate_kind")
            kind = kind.get("value") if isinstance(kind, dict) else kind
            qty = g.get("quantity")
            qty = qty.get("value") if isinstance(qty, dict) else qty
            self.gates.append({"item": GATE_ITEM[gid], "qty": _d(qty), "w": _d(w), "h": _d(h), "leaves": _d(kinds[kind])})
        self.sref = sref

    def basis(self, name):
        q, c = self.q, self.cls
        cl = lambda k, f="quantity": _d(c[k][f]) if k in c else D(0)
        if name.startswith("ITEM_"):
            return {int(name[5:]): D(1)}
        if name == "GROSS_RUN_AB":
            return {10: q["M05"] - q["D02"], 11: q["D02"]}
        if name == "NET_LF_AB":
            return {10: q["D01"], 11: q["D02"]}
        if name == "RAIL_LF_AB":
            return {10: (q["M05"] - q["D02"]) + q["M06"], 11: q["D02"]}
        if name == "RAIL_LINES_AB":
            return {10: 2 * q["D01"], 11: q["D02"]}
        if name == "TERMINALS_A":
            return {10: cl("A_CORNER_TERMINAL"), 12: cl("GATE_G1"), 13: cl("GATE_G2"), 14: cl("GATE_G3")}
        if name == "A_LINE_POSTS":
            return {10: cl("A_LINE")}
        if name == "B_TERMINAL_POSTS":
            return {11: cl("B_TERMINAL")}
        if name == "B_LINE_POSTS":
            return {11: cl("B_LINE")}
        if name == "LINE_CAPS_A_B_TERM":
            return {10: cl("A_LINE"), 11: cl("B_TERMINAL")}
        if name in ("POSTS_BY_CLASS", "HOLES_BY_CLASS", "CONCRETE_BY_CLASS"):
            f = {"POSTS_BY_CLASS": "quantity", "HOLES_BY_CLASS": "holes", "CONCRETE_BY_CLASS": "concrete_cy"}[name]
            out = {}
            for k, item in CLASS_ITEM.items():
                out[item] = out.get(item, D(0)) + cl(k, f)
            return out
        gates = lambda f: {g["item"]: sum((f(x) for x in self.gates if x["item"] == g["item"]), D(0)) for g in self.gates}
        if name == "GATE_QTY":
            return gates(lambda g: g["qty"])
        if name == "GATE_LEAVES":
            return gates(lambda g: g["qty"] * g["leaves"])
        if name == "GATE_WIDTH":
            return gates(lambda g: g["qty"] * g["w"])
        if name == "GATE_PIPE":
            return gates(lambda g: g["qty"] * g["leaves"] * (2 * g["h"] + 3 * (g["w"] / g["leaves"])))
        if name == "GATE_DOUBLE":
            return gates(lambda g: g["qty"] if g["leaves"] == 2 else D(0))
        raise Refused("ATTRIBUTION_UNKNOWN_BASIS", f"unknown basis {name}")


def quantities_by_item(ctx):
    q = {10: ctx.q["D01"], 11: ctx.q["D02"], 15: ctx.q["M38"], 16: ctx.q["M42"]}
    for g in ctx.gates:
        q[g["item"]] = q.get(g["item"], D(0)) + g["qty"]
    return q


def schedule_for(state, sref):
    """The ALLOC-V1 schedule for one priced scenario, or raises Refused."""
    sc = state["estimate"]["scenarios"][sref]
    ctx = _Ctx(state, sref)
    A = {i: 0 for i in ITEMS}
    taxable = {i: 0 for i in ITEMS}
    for line in sc["materials"]["lines"]:
        rule = MATERIALS.get(line["item_id"])
        if rule is None:
            raise Refused("ATTRIBUTION_MISSING_KEY", f"material {line['item_id']} has no attribution rule")
        parts = spread(cents(line["extended"]), ctx.basis(rule[0]))
        for i, c in parts.items():
            A[i] += c
            if not line.get("tax_exempt"):
                taxable[i] += c
    tax_c = cents(sc["sales_tax"]["amount"])
    for i, c in spread(tax_c, taxable).items() if tax_c else []:
        A[i] += c
    for line in sc["labor"]["lines"]:
        rule = LABOR.get(line["task_id"])
        if rule is None:
            raise Refused("ATTRIBUTION_MISSING_KEY", f"labor task {line['task_id']} has no attribution rule")
        for i, c in spread(cents(line["extended"]), ctx.basis(rule[0])).items():
            A[i] += c
    adm = (sc["labor"].get("certified_payroll_admin") or {}).get("extended") or 0
    pool = cents(sc["services"]["subtotal"]) + cents(adm) + cents(sc["equipment"]["subtotal"]) + cents(sc["mobilization"]["subtotal"])
    if sum(A.values()) + pool != cents(sc["direct_cost"]):
        raise Refused("ATTRIBUTION_MISMATCH", f"attributed direct cost {money(sum(A.values()) + pool)} does not equal the engine's {sc['direct_cost']}")
    qty = quantities_by_item(ctx)
    m = split_markup(A, pool, cents(sc["overhead"]["amount"]), cents(sc["contingency"]["amount"]), cents(sc["profit"]["amount"]))
    if sum(v["amount"] for v in m.values()) != cents(sc["price_total"]):
        raise Refused("ATTRIBUTION_MISMATCH", "the item amounts do not add to the engine total")
    assumed = _assumed(state["scope"])
    items, sched_total = [], D(0)
    for i, (desc, unit) in ITEMS.items():
        r, n = m[i], qty.get(i, D(0))
        row = {"item_no": i, "description": desc, "unit": unit, "quantity": float(n), "label": "allocated", "note": NOTE_16 if i == 16 else None}
        if n <= 0 or r["amount"] == 0:
            row.update(status="NOT_IN_SCENARIO", unit_price=None, extended=None)
        else:
            up, ext = printed_prices(r["amount"], n)
            sched_total += ext
            row.update(status="PRICED_QUALIFIED" if assumed else "PRICED", unit_price=float(up), extended=float(ext), qualifier="assumed, RFI pending" if assumed else None,
                       **{k: money(v) for k, v in r.items() if k != "amount"}, direct_attributed=money(A[i]), allocated_amount=money(r["amount"]))
        items.append(row)
    engine_total = _d(sc["price_total"])
    delta = (sched_total - engine_total).quantize(CENT)
    out = {"available": True, "method": METHOD, "label": "allocated", "scope_ref": sref, "attribution_table_sha256": table_sha256(), "allowances": {"amount": 0.0, "locked": True, "note": "no allowances are carried"},
           "items": items, "engine_total": float(engine_total), "schedule_total": float(sched_total), "rounding_delta": float(delta),
           "reconciliation": (f"Item prices are allocated by {METHOD}; the printed unit price governs each extension. Schedule total {sched_total:,.2f} "
                              f"{'=' if delta == 0 else 'differs from'} engine total {engine_total:,.2f}" + ("" if delta == 0 else f" by {delta:+,.2f} (rounding of printed unit prices)") + "."),
           "combined_total": None}
    out["bid_revision"] = hashlib.sha256(json.dumps({"scope_version": state["scope"]["scope_version"], "proposal_digest": state.get("proposal_digest"), "schedule": out},
                                                    sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return out


def _assumed(scope):
    """True when a person's typed (not document-confirmed) value stands in the G3 scope: every G3-dependent price is then qualified."""
    for g in scope.get("gates") or []:
        if g.get("gate_id") == "G3" and isinstance(g.get("clear_width_ft"), dict) and g["clear_width_ft"].get("status") == "human_resolved":
            return True
    cls = ((scope.get("footing_scope") or {}).get("classes") or {}).get("GATE_G3") or {}
    return any(isinstance(f, dict) and f.get("status") == "human_resolved" for f in cls.values())


def view(state):
    """{scenario: schedule}. Never raises: an unavailable or refused schedule says why, and shows no price."""
    out = {}
    est = state.get("estimate")
    missing = sorted({e["exception_id"] for e in state.get("exceptions", []) if e["severity"] == "blocking" and "/gates/2/" in e["exception_id"] or
                      e["severity"] == "blocking" and "GATE_G3" in e["exception_id"]})
    if not est:
        base = [{"item_no": i, "description": d, "unit": u, "status": "UNPRICED_MISSING_INPUT" if i == 14 else "UNPRICED_NO_ENGINE_TOTAL",
                 "missing": missing if i == 14 else [], "note": NOTE_16 if i == 16 else None} for i, (d, u) in ITEMS.items()]
        return {"available": False, "method": METHOD, "reason": "the engine produces no total until every blocking input is resolved", "items": base, "combined_total": None}
    for sref in est["scenarios"]:
        try:
            out[sref] = schedule_for(state, sref)
        except Refused as e:
            out[sref] = {"available": False, "method": METHOD, "scope_ref": sref, "refused": e.code, "reason": str(e), "items": [], "combined_total": None}
        except (KeyError, TypeError, ValueError, ArithmeticError) as e:  # noqa: BLE001 - never crash the state summary; refuse instead
            out[sref] = {"available": False, "method": METHOD, "scope_ref": sref, "refused": "ATTRIBUTION_INPUT_ERROR", "reason": f"{type(e).__name__}: {e}", "items": [], "combined_total": None}
    return {"available": True, "method": METHOD, "scenarios": out, "combined_total": None,
            "note": "Alternate A-1 is a replacement for the Base Bid and is shown separately; no combined total exists."}

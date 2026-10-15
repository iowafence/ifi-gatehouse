"""Deterministic estimate math. Identical inputs -> identical outputs, always."""
import math
from .util import val
from .takeoff import derive_pay_qty


def _r(x):
    return round(x + 0.0, 2)


def _price_od(rates, od):
    return rates["materials"]["post_each_by_od"][f"{od:g}"]


def _gate_price(rates, width):
    table = rates["materials"]["gate_each_by_width_ft"]
    k = f"{width:g}"
    return table[k] if k in table else width * rates["materials"]["gate_per_ft_fallback"]


def compute_estimate(scope, takeoff, rates):
    m, lab, eq = rates["materials"], rates["labor"], rates["equipment"]
    prod, rate = lab["production"], lab["hourly_rate_per_man"]
    direct = {}      # key -> {"materials":, "labor":}
    lines = []

    def add(key, kind, desc, amount):
        amount = _r(amount)
        direct.setdefault(key, {"materials": 0.0, "labor": 0.0})[kind] += amount
        lines.append({"key": key, "kind": kind, "desc": desc, "amount": amount})

    man_hours = 0.0
    for rid, r in takeoff["runs"].items():
        key = f"run:{rid}"
        posts = r["terminals"] * _price_od(rates, r["terminal_od_in"]) + r["line_posts"] * _price_od(rates, r["line_od_in"])
        fabric = r["fabric_sf"] * (1 + rates["waste_pct"]) * m["fabric_per_sf"]
        rails = r["top_rail_lf"] * m["rail_per_lf"] + r["brace_lf"] * m["rail_per_lf"] + r["tension_wire_lf"] * m["tension_wire_per_lf"]
        truss = r["truss_rods"] * m["truss_rod_each"]
        conc = r["footings"] * m["concrete_per_footing"]
        fittings = m["fittings_pct"] * (posts + fabric + rails)
        add(key, "materials", f"{rid} posts", posts)
        add(key, "materials", f"{rid} fabric (+waste)", fabric)
        add(key, "materials", f"{rid} rails/wire/braces", rails)
        add(key, "materials", f"{rid} truss rods", truss)
        add(key, "materials", f"{rid} footing concrete", conc)
        add(key, "materials", f"{rid} fittings", fittings)
        lf_mh = prod["fence_lf_per_man_hour"] / (prod["tall_factor"] if r["height_ft"] > prod["tall_over_ft"] else 1.0)
        mh = r["net_lf"] / lf_mh + r["footings"] * prod["footing_mh_each"]
        add(key, "labor", f"{rid} install ({mh:.1f} mh)", mh * rate)
        man_hours += mh

    if takeoff["gates"]:
        for gid, g in takeoff["gates"].items():
            add("gates", "materials", f"{gid} gate leaf x{g['qty']}", g["qty"] * _gate_price(rates, g["width_ft"]))
            add("gates", "materials", f"{gid} transom fabric", g["transom_sf"] * m["fabric_per_sf"])
            add("gates", "materials", f"{gid} transom hardware", g["qty"] * m["transom_hardware_each"])
            mh = g["qty"] * (prod["gate_mh_each"] + (prod["transom_mh_each"] if g["transom_sf"] > 0 else 0))
            add("gates", "labor", f"{gid} install ({mh:.1f} mh)", mh * rate)
            man_hours += mh

    for aid, a in takeoff["accessories"].items():
        key = f"acc:{aid}"
        if a["kind"] == "windscreen":
            add(key, "materials", f"{aid} windscreen", a["lf"] * m["windscreen_per_lf"])
            add(key, "materials", f"{aid} air vents x{a['vents']}", a["vents"] * m["air_vent_each"])
            mh = a["lf"] / prod["windscreen_lf_per_mh"]
        elif a["kind"] == "fence_guard":
            add(key, "materials", f"{aid} fence guard", a["lf"] * m["fence_guard_per_lf"])
            mh = a["lf"] / prod["guard_lf_per_mh"]
        else:
            continue
        add(key, "labor", f"{aid} install ({mh:.1f} mh)", mh * rate)
        man_hours += mh

    core_n = takeoff["totals"]["core_drill_footings"]
    core_mh = core_n * prod["core_drill_mh_per_footing"]
    man_hours += core_mh
    shared = {}
    shared["labor_core_drilling"] = _r(core_mh * rate)
    crew_days = math.ceil(man_hours / (lab["crew_size"] * lab["hours_per_day"])) if man_hours else 0
    shared["equipment_core_drill"] = _r(math.ceil(core_n / eq["core_drill_footings_per_day"]) * eq["core_drill_day_rate"]) if core_n else 0.0
    shared["fuel"] = _r(crew_days * eq["fuel_per_crew_day"])
    shared["mobilization"] = _r(rates["mobilization"])

    mat = _r(sum(d["materials"] for d in direct.values()))
    labor = _r(sum(d["labor"] for d in direct.values()) + shared["labor_core_drilling"])
    equipment = _r(shared["equipment_core_drill"])
    cogs = _r(mat + labor + equipment + shared["fuel"] + shared["mobilization"])
    overhead = _r(cogs * rates["overhead_pct"])
    price = _r((cogs + overhead) / (1 - rates["target_margin_pct"]))

    # allocate shared costs and margin to pay items proportional to direct cost
    pay_items = []
    direct_total = sum(d["materials"] + d["labor"] for d in direct.values()) or 1.0
    for p in scope.get("bid_structure", {}).get("pay_items", []):
        if p.get("in_engine_scope") is False or not p.get("maps_to"):
            continue
        keys = {":".join(t.split(":")[:2]) if t.split(":")[0] != "gates" else "gates" for t in p["maps_to"]}
        d = sum(direct.get(k, {}).get("materials", 0) + direct.get(k, {}).get("labor", 0) for k in keys)
        share = d / direct_total
        item_cogs = _r(d + share * (cogs - direct_total))
        item_price = _r(share * price)
        qty = derive_pay_qty(takeoff, p["maps_to"])
        pay_items.append({"item_no": p["item_no"], "description": p["description"], "unit": p["unit"],
                          "qty": qty, "cogs": item_cogs, "price": item_price,
                          "unit_price": _r(item_price / qty) if qty else None})
    if pay_items:  # pennies of rounding drift go to the largest item so lines sum exactly to the total
        drift = _r(price - sum(i["price"] for i in pay_items))
        big = max(pay_items, key=lambda i: i["price"])
        big["price"] = _r(big["price"] + drift)
        big["unit_price"] = _r(big["price"] / big["qty"]) if big["qty"] else None
    return {
        "rates_profile": rates.get("profile"),
        "lines": lines, "shared": shared,
        "cogs": {"materials": mat, "labor": labor, "equipment": equipment, "fuel": shared["fuel"],
                 "mobilization": shared["mobilization"], "total": cogs},
        "man_hours": round(man_hours, 2), "crew_days": crew_days,
        "overhead": overhead, "price_total": price,
        "cogs_per_lf": _r(cogs / takeoff["totals"]["fence_lf"]) if takeoff["totals"]["fence_lf"] else None,
        "pay_items": pay_items,
    }


# --- arithmetic path used to reproduce known estimates (sections/man-hour basis) ---
def man_hours_from_sections(sections, per_man_hour):
    return round(sections / per_man_hour, 2)


def cogs_components(materials, man_hours, hourly_rate, equipment, fuel, mobilization, lf):
    labor = _r(man_hours * hourly_rate)
    total = _r(materials + labor + equipment + fuel + mobilization)
    return {"materials": materials, "labor": labor, "equipment": equipment, "fuel": fuel,
            "mobilization": mobilization, "total": total, "cogs_per_lf": _r(total / lf)}

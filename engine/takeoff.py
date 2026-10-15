"""Deterministic takeoff: structured scope -> quantities. No model output is trusted for arithmetic."""
import math
from collections import defaultdict
from .util import val

DEFAULT_RULES = {
    "brace_min_height_ft": 6.0,   # horizontal brace + truss rod at terminals/gate posts at or above this height
    "top_rail": True,
}


def _gates_by_run(scope):
    d = defaultdict(list)
    for g in scope.get("gates", []):
        d[g.get("run_id")].append(g)
    return d


def compute_takeoff(scope, rules=None):
    rules = {**DEFAULT_RULES, **(rules or {})}
    gates_by_run = _gates_by_run(scope)
    out = {"runs": {}, "gates": {}, "accessories": {}, "totals": {}}

    for run in scope.get("fence_runs", []):
        rid = run["run_id"]
        repeat = run.get("repeat", 1)
        length = val(run["length_lf"])
        height = val(run["height_ft"])
        spacing = val(run.get("section_spacing_ft"), 10.0)
        geom = run.get("geometry", {})
        closed = geom.get("closed", False)
        corners = geom.get("corners", 0)
        free_ends = geom.get("free_ends", 0 if closed else 2)

        gs = gates_by_run.get(rid, [])
        gate_n = sum(g.get("quantity", 1) for g in gs)
        gate_open = sum(val(g["clear_width_ft"]) * g.get("quantity", 1) for g in gs)

        terminals = corners + free_ends + 2 * gate_n
        intervals = terminals if closed else terminals - 1
        segments = max(1, intervals - gate_n)
        net = max(0.0, length - gate_open)
        # Aggregate lower bound: assumes each segment divides evenly. Replace with per-segment
        # geometry when the scope carries it.
        line_posts = max(0, math.ceil(round(net / spacing, 6)) - segments)

        braces = 0
        if height >= rules["brace_min_height_ft"]:
            braces = corners * 2 + free_ends + 2 * gate_n
        post = run.get("post", {})
        r = {
            "run_id": rid, "repeat": repeat, "height_ft": height,
            "length_lf": round(length * repeat, 2),
            "net_lf": round(net * repeat, 2),
            "terminals": terminals * repeat,
            "line_posts": line_posts * repeat,
            "braces": braces * repeat,
            "brace_lf": round(braces * spacing * repeat, 2),
            "truss_rods": braces * repeat,
            "fabric_sf": round(net * height * repeat, 2),
            "top_rail_lf": round(net * repeat, 2) if rules["top_rail"] else 0.0,
            "tension_wire_lf": round(net * repeat, 2),
            "footings": (terminals + line_posts) * repeat,
            "terminal_od_in": val(post.get("terminal_od_in")),
            "line_od_in": val(post.get("line_od_in")),
            "gate_count": gate_n * repeat,
            "gate_opening_lf": round(gate_open * repeat, 2),
            "segments": segments, "spacing_ft": spacing,
        }
        out["runs"][rid] = r

    total_gate_open = 0.0
    for g in scope.get("gates", []):
        run = out["runs"].get(g.get("run_id"), {})
        qty = g.get("quantity", 1) * scope_run_repeat(scope, g.get("run_id"))
        w = val(g["clear_width_ft"])
        gh = val(g.get("height_ft"))
        tr = g.get("transom", {})
        th = val(tr.get("height_ft"))
        if th is None and gh is not None and run:
            th = max(0.0, run["height_ft"] - gh)
        th = th or 0.0
        out["gates"][g["gate_id"]] = {
            "gate_id": g["gate_id"], "run_id": g.get("run_id"), "qty": qty,
            "width_ft": w, "height_ft": gh, "transom_h_ft": th,
            "transom_sf": round(w * th * qty, 2),
        }
        total_gate_open += w * qty

    guard_gates_extra = 0.0
    for a in scope.get("accessories", []):
        lf = val(a["length_lf"], 0.0)
        spacing = val(a.get("accessory_spacing_ft"))
        vents = math.ceil(round(lf / spacing, 6)) if spacing and a.get("kind") == "windscreen" else 0
        extra = 0.0
        if a.get("kind") == "fence_guard" and str(val(a.get("applies_to_gates"), "no")).lower() == "yes":
            extra = round(total_gate_open, 2)
        out["accessories"][a["accessory_id"]] = {
            "accessory_id": a["accessory_id"], "kind": a.get("kind"),
            "lf": round(lf + extra, 2), "vents": vents,
            "height_ft": val(a.get("height_ft")),
        }

    core = str(val(scope.get("global_requirements", {}).get("core_drilling_required"), "no")).lower() == "yes"
    runs = out["runs"].values()
    out["totals"] = {
        "fence_lf": round(sum(r["length_lf"] for r in runs), 2),
        "terminals": sum(r["terminals"] for r in runs),
        "line_posts": sum(r["line_posts"] for r in runs),
        "footings": sum(r["footings"] for r in runs),
        "gates": sum(g["qty"] for g in out["gates"].values()),
        "core_drill_footings": sum(r["footings"] for r in runs) if core else 0,
    }
    return out


def scope_run_repeat(scope, run_id):
    for r in scope.get("fence_runs", []):
        if r["run_id"] == run_id:
            return r.get("repeat", 1)
    return 1


def derive_pay_qty(takeoff, maps_to):
    """Resolve pay-item mapping tokens ('run:FR-001:length', 'gates:count', 'acc:AC-1:lf') to a quantity."""
    total = 0.0
    for tok in maps_to:
        p = tok.split(":")
        if p[0] == "run":
            total += takeoff["runs"][p[1]]["length_lf" if p[2] == "length" else "net_lf"]
        elif p[0] == "gates":
            total += takeoff["totals"]["gates"]
        elif p[0] == "acc":
            total += takeoff["accessories"][p[1]]["lf"]
    return round(total, 2)

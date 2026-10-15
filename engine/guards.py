"""Fail-closed input guards. Pure code; model confidence is never consulted.

Two layers:
  structural_problems(scope) -> [(path, message)]  the scope cannot be interpreted (not resolvable by a human value)
  value_problems(scope)      -> [(path, message)]  a fact that feeds arithmetic holds an unusable number

A null value on an `unresolved` fact is NOT a problem here; Gate 1 reports it as MISSING_VALUE.
"""
import math
from pricing import footings
from .validate import validate_scope

# Fact paths (relative to their parent object) that feed arithmetic and must be positive finite numbers.
RUN_NUMERIC = ("height_ft", "length_lf", "section_spacing_ft")
POST_NUMERIC = ("terminal_od_in", "line_od_in")
GATE_NUMERIC = ("clear_width_ft", "height_ft")
ACCESSORY_NUMERIC = ("length_lf", "height_ft", "accessory_spacing_ft")
GLOBAL_NUMERIC = ("footing_terminal_diameter_in", "footing_terminal_depth_in", "footing_line_diameter_in", "footing_line_depth_in")
YES_NO_GLOBALS = ("top_rail_continuous_across_gate_openings", "prevailing_wage_required", "owner_sales_tax_exempt")
MAP_KINDS = {"run": {"length", "net"}, "gates": {"count"}, "acc": {"lf"}}


def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def is_positive_number(x):
    return is_number(x) and math.isfinite(x) and x > 0


def is_positive_int(x):
    return isinstance(x, int) and not isinstance(x, bool) and x >= 1


def is_fact(node):
    return isinstance(node, dict) and "value" in node and "status" in node


def _nonblank(x):
    return isinstance(x, str) and x.strip() != ""


def structural_problems(scope):
    p = []
    if not isinstance(scope, dict):
        return [("/", "scope is not an object")]
    runs, gates, accs = scope.get("fence_runs"), scope.get("gates"), scope.get("accessories", [])
    bid = scope.get("bid_structure")
    for key, node in (("fence_runs", runs), ("gates", gates), ("accessories", accs)):
        if not isinstance(node, list) or not all(isinstance(i, dict) for i in node):
            p.append((f"/{key}", f"{key} must be a list of objects"))
    if not isinstance(bid, dict):
        p.append(("/bid_structure", "bid_structure must be an object"))
    if p:
        return p
    pay_items = bid.get("pay_items", [])
    if not isinstance(pay_items, list) or not all(isinstance(i, dict) for i in pay_items):
        return [("/bid_structure/pay_items", "pay_items must be a list of objects")]
    if "alternates" in bid and (not isinstance(bid["alternates"], list) or not all(isinstance(a, dict) for a in bid["alternates"])):
        return [("/bid_structure/alternates", "alternates must be a list of objects")]

    run_ids, gate_ids, acc_ids = set(), set(), set()
    for i, r in enumerate(runs):
        rid = r.get("run_id")
        if not _nonblank(rid) or rid in run_ids:
            p.append((f"/fence_runs/{i}/run_id", "run_id must be a unique non-empty string"))
        run_ids.add(rid)
        for f in ("fence_type", "height_ft", "length_lf"):
            if not is_fact(r.get(f)):
                p.append((f"/fence_runs/{i}/{f}", "must be a fact object with value and status"))
        for f in ("section_spacing_ft",):
            if f in r and not is_fact(r[f]):
                p.append((f"/fence_runs/{i}/{f}", "must be a fact object with value and status"))
        if "repeat" in r and not is_positive_int(r["repeat"]):
            p.append((f"/fence_runs/{i}/repeat", "repeat must be an integer >= 1"))
        post = r.get("post", {})
        if not isinstance(post, dict):
            p.append((f"/fence_runs/{i}/post", "post must be an object"))
        else:
            for f in POST_NUMERIC:
                if not is_fact(post.get(f)):
                    p.append((f"/fence_runs/{i}/post/{f}", "must be a fact object with value and status"))
        geom = r.get("geometry", {})
        if not isinstance(geom, dict):
            p.append((f"/fence_runs/{i}/geometry", "geometry must be an object"))
        else:
            for f in ("corners", "free_ends"):
                if f in geom and (not isinstance(geom[f], int) or isinstance(geom[f], bool) or geom[f] < 0):
                    p.append((f"/fence_runs/{i}/geometry/{f}", f"{f} must be an integer >= 0"))
    for i, g in enumerate(gates):
        gid = g.get("gate_id")
        if not _nonblank(gid) or gid in gate_ids:
            p.append((f"/gates/{i}/gate_id", "gate_id must be a unique non-empty string"))
        gate_ids.add(gid)
        if g.get("run_id") not in run_ids:
            p.append((f"/gates/{i}/run_id", f"gate references unknown run {g.get('run_id')!r}"))
        if not is_fact(g.get("clear_width_ft")):
            p.append((f"/gates/{i}/clear_width_ft", "must be a fact object with value and status"))
        if "height_ft" in g and not is_fact(g["height_ft"]):
            p.append((f"/gates/{i}/height_ft", "must be a fact object with value and status"))
        if "quantity" in g and not is_positive_int(g["quantity"]):
            p.append((f"/gates/{i}/quantity", "quantity must be an integer >= 1"))
    for i, a in enumerate(accs):
        aid = a.get("accessory_id")
        if not _nonblank(aid) or aid in acc_ids:
            p.append((f"/accessories/{i}/accessory_id", "accessory_id must be a unique non-empty string"))
        acc_ids.add(aid)
        if not is_fact(a.get("length_lf")):
            p.append((f"/accessories/{i}/length_lf", "must be a fact object with value and status"))
    for item in pay_items:
        for tok in item.get("maps_to", []) or []:
            parts = tok.split(":") if isinstance(tok, str) else []
            ok = bool(parts) and parts[0] in MAP_KINDS and parts[-1] in MAP_KINDS[parts[0]] and (
                (parts[0] == "gates" and len(parts) == 2) or
                (parts[0] == "run" and len(parts) == 3 and parts[1] in run_ids) or
                (parts[0] == "acc" and len(parts) == 3 and parts[1] in acc_ids))
            if not ok:
                p.append((f"/bid_structure/pay_items/{item.get('item_no')}", f"invalid maps_to token {tok!r}"))
    if "footing_scope" in scope:          # footing-scope.v1 (optional, additive): its shape is checked like every other part of the scope
        p += footings.structural_problems(scope)
    # evidence must be a list of objects, or the exception rules would crash on it
    for path, f in _facts(scope):
        ev = f.get("evidence", [])
        if not isinstance(ev, list) or not all(isinstance(e, dict) for e in ev):
            p.append((path, "evidence must be a list of objects"))
    if p:
        return p
    for msg in validate_scope(scope):
        path, _, text = msg.partition(": ")
        p.append((path if path.startswith("/") else "/", text or msg))
    return p


def _facts(scope):
    from .util import walk_facts
    return walk_facts(scope)


def _check(path, fact, out):
    if not is_fact(fact):
        return
    v = fact.get("value")
    if v is None or fact.get("status") == "unresolved":
        return
    if not is_positive_number(v):
        out.append((path, f"{v!r} is not a positive finite number"))


def value_problems(scope):
    """Assumes structural_problems(scope) == []."""
    out = []
    for i, r in enumerate(scope.get("fence_runs", [])):
        for f in RUN_NUMERIC:
            _check(f"/fence_runs/{i}/{f}", r.get(f), out)
        for f in POST_NUMERIC:
            _check(f"/fence_runs/{i}/post/{f}", r.get("post", {}).get(f), out)
    for i, g in enumerate(scope.get("gates", [])):
        for f in GATE_NUMERIC:
            _check(f"/gates/{i}/{f}", g.get(f), out)
        tr = g.get("transom")
        if isinstance(tr, dict):
            _check(f"/gates/{i}/transom/height_ft", tr.get("height_ft"), out)
    for i, a in enumerate(scope.get("accessories", [])):
        for f in ACCESSORY_NUMERIC:
            _check(f"/accessories/{i}/{f}", a.get(f), out)
    ge = scope.get("global_requirements")
    for f in GLOBAL_NUMERIC:
        _check(f"/global_requirements/{f}", ge.get(f) if isinstance(ge, dict) else None, out)
    for f in YES_NO_GLOBALS:
        fact = ge.get(f) if isinstance(ge, dict) else None
        if is_fact(fact) and fact.get("value") is not None and fact.get("status") != "unresolved" and str(fact["value"]).strip().lower() not in ("yes", "no"):
            out.append((f"/global_requirements/{f}", f"{fact['value']!r} is not yes or no"))
    if "footing_scope" in scope:
        out += footings.value_problems(scope)
    return out


def geometry_problems(scope):
    """Gate openings must fit inside their run, or net fabric LF would be silently clamped to zero."""
    by_run = {}
    for g in scope.get("gates", []):
        w = g.get("clear_width_ft", {}).get("value")
        if is_positive_number(w):
            by_run[g["run_id"]] = by_run.get(g["run_id"], 0.0) + w * g.get("quantity", 1)
    out = []
    for i, r in enumerate(scope.get("fence_runs", [])):
        length = r["length_lf"].get("value")
        if is_positive_number(length) and by_run.get(r["run_id"], 0.0) >= length:
            out.append((f"/fence_runs/{i}/length_lf",
                        f"gate openings ({by_run[r['run_id']]:g} LF) are not less than run length ({length:g} LF)"))
    if "footing_scope" in scope:
        out += footings.geometry_problems(scope)
    return out


def rates_problems(rates):
    """Company-controlled rate table sanity. Returns a list of messages."""
    p = []
    if not isinstance(rates, dict):
        return ["rates is not an object"]
    for k in ("waste_pct", "overhead_pct", "target_margin_pct", "mobilization"):
        if not is_number(rates.get(k)) or not math.isfinite(rates[k]) or rates[k] < 0:
            p.append(f"rates.{k} must be a finite number >= 0")
    if is_number(rates.get("target_margin_pct")) and not (0 <= rates["target_margin_pct"] < 1):
        p.append("rates.target_margin_pct must be in [0, 1)")
    for sect in ("materials", "labor", "equipment"):
        if not isinstance(rates.get(sect), dict):
            p.append(f"rates.{sect} missing")
    lab = rates.get("labor") if isinstance(rates.get("labor"), dict) else {}
    if not is_positive_number(lab.get("hourly_rate_per_man")):
        p.append("rates.labor.hourly_rate_per_man must be a positive finite number")
    return p

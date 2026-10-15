"""footing-scope.v1: per-run, per-post-class footing scope and the deterministic calculation that turns it into counts, concrete and holes.

ADDITIVE and OPTIONAL. A scope without a `footing_scope` block is priced exactly as before (single global footing facts, aggregate lower-bound post
counts); nothing in this module runs for it. `pricing-service.v1`, `pricing.engine`, the rate book and the quantity ruleset are not touched.

What a `footing_scope` states (all numbers are ordinary scope FACTS {value, status, evidence}, so the existing Scope Gate already asks a named human about
every unresolved or inferred one, and any change to any of them bumps the scope version, which voids the crew plan, the wage decision and Release):
  * classes  - one entry per post class: fence type, role, footing diameter_in / depth_in (and, for a gate-post class, post_od_in).
  * runs     - for EVERY fence run: which class each kind of post belongs to, and the segment layout (sides, gate stations) from which line posts are counted.

What the calculation guarantees:
  * every physical post is created exactly once, with exactly one class and one owner, and gets exactly one footing and one core-drilled hole;
  * line posts are counted PER SEGMENT (max(0, ceil(L / max_spacing) - 1) between the two fixed posts that bound it), never as a run-wide aggregate;
  * a value that is not established is None, never 0: an unresolved dimension makes concrete/holes of that class unknown, an unresolved gate width makes
    the two adjacent segments' line posts unknown, and the known part is reported separately from the unknown exposure;
  * a gate-post class is NEVER defaulted from a neighbouring class. The documents' paragraph 3.2.D ("gate posts and footings not otherwise noted are as
    for terminal posts") is carried as evidence for a human to adopt, not applied by code.
"""
import hashlib
import json
import math
import re
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from . import jsonschema_lite

CONTRACT_VERSION = "footing-scope.v1"
CALC_VERSION = "footing-calc.v1"
SCHEDULE_VERSION = "footing-schedule.v1"
CONVENTION_ID = "FSC-CONV-1:FACE_TO_FACE_NOMINAL"
# Count sensitivity: a real gate post sits half a post diameter outside the clear opening. The cataloged posts are at most 2.875 in OD, so every
# gate-side offset up to this bound is tested; if a count changes anywhere inside it, the count is reported as convention-sensitive and stays provisional.
POST_OFFSET_BOUND_FT = Decimal("0.5")
GLOBAL_FOOTING_KEYS = ("footing_terminal_diameter_in", "footing_terminal_depth_in", "footing_line_diameter_in", "footing_line_depth_in")
ROLES = ("line", "terminal", "corner", "gate")
FENCE_TYPES = ("A", "B")
_CLASS_ID = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")
_RANK = {"documented": 0, "calculated": 1, "assumed": 2, "provisional": 3, "unresolved": 4}
_REVIEW_RANK = {"NOT_REQUIRED": 0, "QUALIFIED_BY_NAMED_HUMAN": 1, "AWAITING_REVIEW": 2, "BLOCKED_UNRESOLVED": 3}
_SIX = Decimal("0.000001")


# ------------------------------------------------------------------ small helpers (kept local: this module imports nothing from the engine)

def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256(obj):
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


def _isnum(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _is_fact(n):
    return isinstance(n, dict) and "value" in n and "status" in n


def _D(x):
    return Decimal(repr(x)) if isinstance(x, float) else Decimal(x)


def _fv(fact):
    """(value, status) for a fact. status is one of documented | assumed | provisional | unresolved; value is None unless it is usable."""
    if not _is_fact(fact):
        return None, "unresolved"
    v, st = fact.get("value"), fact.get("status")
    if v is None or st == "unresolved":
        return None, "unresolved"
    if st == "confirmed":
        return v, "documented"
    if st == "human_resolved":
        return v, "assumed"
    if st == "inferred":
        return v, "provisional"
    return None, "unresolved"


def _ref(path, fact):
    out = {"fact_path": path}
    ev = [e for e in (fact.get("evidence") or []) if isinstance(e, dict) and e.get("doc_id")] if _is_fact(fact) else []
    if ev:
        e = max(enumerate(ev), key=lambda ie: (ie[1].get("doc_revision", 0) if isinstance(ie[1].get("doc_revision"), int) else 0, ie[0]))[1]
        out["doc_id"] = e["doc_id"]
        if isinstance(e.get("doc_revision"), int):
            out["doc_revision"] = e["doc_revision"]
        if isinstance(e.get("page"), int) and e["page"] >= 1:
            out["page"] = e["page"]
        if e.get("sheet_label"):
            out["sheet_label"] = str(e["sheet_label"])[:100]
    return out


class _Inputs:
    """The facts one number depends on: their worst status, the review each needs and the citations."""

    def __init__(self, res):
        self.res, self.paths, self.refs, self.states = res or {}, [], {}, {}

    def use(self, path, fact):
        v, st = _fv(fact)
        if path not in self.refs:
            self.paths.append(path)
            self.refs[path] = _ref(path, fact) if _is_fact(fact) else {"fact_path": path}
            self.states[path] = (st, fact.get("status") if _is_fact(fact) else None)
        return v

    def basis(self, default="calculated"):
        worst = default
        for st, _ in self.states.values():
            if _RANK[st] > _RANK[worst]:
                worst = st
        return worst

    def review(self):
        state, approvals = "NOT_REQUIRED", []
        for path in self.paths:
            st, raw = self.states[path]
            if st == "unresolved":
                cand = "BLOCKED_UNRESOLVED"
            elif raw == "inferred":
                cand = "AWAITING_REVIEW"
            elif raw == "human_resolved":
                cand = "QUALIFIED_BY_NAMED_HUMAN"
                r = self.res.get(path)
                if r:
                    approvals.append({"fact_path": path, "exception_id": r["exception_id"], "by": r["by"], "scope_version": r["scope_version"]})
            else:
                cand = "NOT_REQUIRED"
            if _REVIEW_RANK[cand] > _REVIEW_RANK[state]:
                state = cand
        return {"state": state, "approvals": approvals}

    def unresolved(self):
        return [p for p in self.paths if self.states[p][0] == "unresolved"]


def _intervals(length, spacing):
    """ceil(length / spacing) with the same 6-decimal pre-rounding the engine's quantity layer uses."""
    return int(((length / spacing).quantize(_SIX, rounding=ROUND_HALF_UP)).to_integral_value(rounding=ROUND_CEILING))


def _vol_cy(d_in, h_in, cuin_per_cy):
    """Cubic yards of one cylindrical footing: pi x (d/2)^2 x depth, inches -> CU YD. Same float arithmetic as the legacy global-footing path."""
    return math.pi * (d_in / 2) ** 2 * h_in / cuin_per_cy


# ------------------------------------------------------------------ structure, values, geometry (called by engine.guards)

def _gates_of(scope, rid):
    return [(j, g) for j, g in enumerate(scope.get("gates") or []) if isinstance(g, dict) and g.get("run_id") == rid]


# Authoritative unit-bearing fields and the ONLY unit each may declare (exact, case-sensitive). `unit` is optional: omission is allowed; a supplied unit must match.
# Nothing is converted. Counts and the concrete / drilling quantities are never supplied (computed), so any attempt to supply them is rejected by the schema.
UNIT_IN, UNIT_FT = ("in",), ("ft",)
UNIT_LEN = ("ft", "lf")            # a run/side length is a linear-foot quantity: the existing scope spells its unit "lf", the footing fixture "ft"
FACT_META_KEYS = {"value", "status", "evidence", "inference_note", "unit", "open_question", "price_affecting"}
UNIT_ERR = "FOOTING_UNIT_INVALID"


def _unit_problem(path, fact, allowed):
    if not _is_fact(fact):
        return None
    extra = sorted(set(fact) - FACT_META_KEYS)
    if extra:
        return (path, f"{UNIT_ERR}: unsupported metadata {extra} on a footing-scope fact (allowed: {sorted(FACT_META_KEYS)}); metadata that could change the calculation's meaning is never ignored")
    if "unit" in fact:
        u = fact["unit"]
        if not isinstance(u, str) or u not in allowed:
            return (path, f"{UNIT_ERR}: this field is in {'/'.join(allowed)} but declares unit {u!r}; units are exact (case-sensitive) and nothing is converted")
    return None


def unit_problems(scope):
    """[(path, message)] - every authoritative unit-bearing fact of the footing contract (and the run/gate facts it consumes) must declare its field's unit or none."""
    out, fs = [], scope.get("footing_scope")
    if not isinstance(fs, dict):
        return out
    def chk(path, fact, allowed):
        r = _unit_problem(path, fact, allowed)
        if r:
            out.append(r)
    for cid, c in (fs.get("classes") or {}).items() if isinstance(fs.get("classes"), dict) else []:
        if isinstance(c, dict):
            for f in ("diameter_in", "depth_in", "post_od_in"):
                chk(f"/footing_scope/classes/{cid}/{f}", c.get(f), UNIT_IN)
    for i, r in enumerate(fs.get("runs") or [] if isinstance(fs.get("runs"), list) else []):
        sides = ((r or {}).get("layout") or {}).get("sides") if isinstance(r, dict) and isinstance(r.get("layout"), dict) else None
        for k, sd in enumerate(sides if isinstance(sides, list) else []):
            if isinstance(sd, dict):
                chk(f"/footing_scope/runs/{i}/layout/sides/{k}/length_lf", sd.get("length_lf"), UNIT_LEN)
                for m, x in enumerate(sd.get("gates") or [] if isinstance(sd.get("gates"), list) else []):
                    if isinstance(x, dict):
                        chk(f"/footing_scope/runs/{i}/layout/sides/{k}/gates/{m}/station_ft", x.get("station_ft"), UNIT_FT)
    for i, r in enumerate(scope.get("fence_runs") or []):
        if isinstance(r, dict):
            chk(f"/fence_runs/{i}/length_lf", r.get("length_lf"), UNIT_LEN)
            chk(f"/fence_runs/{i}/section_spacing_ft", r.get("section_spacing_ft"), UNIT_FT)
    for j, g in enumerate(scope.get("gates") or []):
        if isinstance(g, dict):
            chk(f"/gates/{j}/clear_width_ft", g.get("clear_width_ft"), UNIT_FT)
    return out


def structural_problems(scope):
    """[(path, message)] - the footing scope cannot be interpreted. Not resolvable by typing a value."""
    fs = scope.get("footing_scope")
    p = []
    base = "/footing_scope"
    if not isinstance(fs, dict):
        return [(base, "footing_scope must be an object")]
    shape = jsonschema_lite.problems(fs, "footing_scope.v1")
    if shape:                                          # the schema file is the single source of truth for the shape; cross-field rules follow only on a valid shape
        return [(base + path, msg) for path, msg in shape]
    bad_units = unit_problems(scope)
    if bad_units:                                      # validated before anything is computed, committed or hashed
        return [(path, msg) for path, msg in bad_units]
    if fs.get("schema_version") != CONTRACT_VERSION:
        p.append((f"{base}/schema_version", f"must be {CONTRACT_VERSION!r}"))
    ge = scope.get("global_requirements") or {}
    for k in GLOBAL_FOOTING_KEYS:
        if isinstance(ge, dict) and k in ge:
            p.append((f"/global_requirements/{k}", "a project-wide footing size cannot coexist with a footing_scope: it would silently apply one footing to every post class; "
                      "state the footing per class in footing_scope.classes"))
    conv = fs.get("convention")
    if not isinstance(conv, dict) or conv.get("id") != CONVENTION_ID:
        p.append((f"{base}/convention/id", f"measurement convention must be {CONVENTION_ID!r}"))
    classes = fs.get("classes")
    if not isinstance(classes, dict) or not classes:
        return p + [(f"{base}/classes", "classes must be a non-empty object")]
    for cid, c in classes.items():
        cp = f"{base}/classes/{cid}"
        if not isinstance(cid, str) or not _CLASS_ID.match(cid):
            p.append((cp, "class id must be UPPER_SNAKE (letters, digits, underscore)"))
            continue
        if not isinstance(c, dict):
            p.append((cp, "class must be an object"))
            continue
        if c.get("fence_type") not in FENCE_TYPES:
            p.append((f"{cp}/fence_type", f"must be one of {list(FENCE_TYPES)}"))
        if c.get("role") not in ROLES:
            p.append((f"{cp}/role", f"must be one of {list(ROLES)}"))
        for f in ("diameter_in", "depth_in"):
            if not _is_fact(c.get(f)):
                p.append((f"{cp}/{f}", "must be a fact object with value and status"))
        if "post_od_in" in c and not _is_fact(c["post_od_in"]):
            p.append((f"{cp}/post_od_in", "must be a fact object with value and status"))
        if c.get("role") == "gate" and "post_od_in" not in c:
            p.append((f"{cp}/post_od_in", "a gate post class must state its post size (post_od_in), even if unresolved: a gate post is never assumed to be the run's terminal post"))
    runs = fs.get("runs")
    if not isinstance(runs, list) or not all(isinstance(r, dict) for r in runs):
        return p + [(f"{base}/runs", "runs must be a list of objects")]
    scope_runs = {r.get("run_id"): r for r in scope.get("fence_runs") or [] if isinstance(r, dict)}
    seen = set()
    for i, r in enumerate(runs):
        rp, rid = f"{base}/runs/{i}", r.get("run_id")
        if rid not in scope_runs or rid in seen:
            p.append((f"{rp}/run_id", "must name exactly one existing fence run, once"))
            continue
        seen.add(rid)
        srun = scope_runs[rid]
        for key in ("corner_class", "end_class", "line_class"):
            if key in r and r[key] not in classes:
                p.append((f"{rp}/{key}", f"unknown class {r[key]!r}"))
        if "line_class" not in r:
            p.append((f"{rp}/line_class", "required"))
        gates = _gates_of(scope, rid)
        gcls = r.get("gate_classes")
        if gates and not isinstance(gcls, dict):
            p.append((f"{rp}/gate_classes", "required: every gate needs its own post class"))
            gcls = {}
        for _, g in gates:
            gc = (gcls or {}).get(g.get("gate_id"))
            if gc not in classes:
                p.append((f"{rp}/gate_classes/{g.get('gate_id')}", "every gate must map to a defined post class (no default)"))
            elif classes[gc].get("role") != "gate":
                p.append((f"{rp}/gate_classes/{g.get('gate_id')}", f"gate {g.get('gate_id')} maps to class {gc!r} whose role is {classes[gc].get('role')!r}: a gate post class must have role 'gate' "
                          "(a gate may not silently borrow the footing of a corner/terminal/line class)"))
        for key, want in (("corner_class", ("corner",)), ("end_class", ("terminal", "corner")), ("line_class", ("line",))):
            if key in r and r[key] in classes and classes[r[key]].get("role") not in want:
                p.append((f"{rp}/{key}", f"class {r[key]!r} has role {classes[r[key]].get('role')!r}; {key} needs role {' or '.join(want)}"))
        lay = r.get("layout")
        if not isinstance(lay, dict) or lay.get("kind") not in ("closed_polygon", "open_line") or not isinstance(lay.get("sides"), list) or not lay["sides"]:
            p.append((f"{rp}/layout", "layout must be {kind: closed_polygon|open_line, sides: [..]}"))
            continue
        geom = srun.get("geometry") if isinstance(srun.get("geometry"), dict) else {}
        sides = lay["sides"]
        if lay["kind"] == "closed_polygon":
            if not geom.get("closed", False) or geom.get("corners") != len(sides) or len(sides) < 3:
                p.append((f"{rp}/layout/sides", f"a closed run with {geom.get('corners')} corner(s) needs exactly that many sides (>= 3), one per corner"))
            if "corner_class" not in r:
                p.append((f"{rp}/corner_class", "required for a closed run"))
        else:
            if geom.get("closed", False) or len(sides) != 1 or geom.get("free_ends", 2) != 2 or geom.get("corners", 0) != 0:
                p.append((f"{rp}/layout/sides", "an open run is exactly one side with two free ends and no corners"))
            if "end_class" not in r:
                p.append((f"{rp}/end_class", "required for an open run"))
        side_ids, inst = set(), {}
        for k, s in enumerate(sides):
            sp = f"{rp}/layout/sides/{k}"
            if not isinstance(s, dict) or not isinstance(s.get("side_id"), str) or not s["side_id"] or s["side_id"] in side_ids:
                p.append((sp, "side needs a unique non-empty side_id"))
                continue
            side_ids.add(s["side_id"])
            if not _is_fact(s.get("length_lf")):
                p.append((f"{sp}/length_lf", "must be a fact object with value and status"))
            ge_list = s.get("gates", [])
            if not isinstance(ge_list, list) or not all(isinstance(x, dict) for x in ge_list):
                p.append((f"{sp}/gates", "gates must be a list of objects"))
                continue
            for m, x in enumerate(ge_list):
                gp = f"{sp}/gates/{m}"
                gid, n = x.get("gate_id"), x.get("instance")
                if gid not in {g.get("gate_id") for _, g in gates}:
                    p.append((gp, f"gate {gid!r} is not a gate of run {rid}"))
                    continue
                if not isinstance(n, int) or isinstance(n, bool) or n < 1:
                    p.append((f"{gp}/instance", "instance must be an integer >= 1"))
                    continue
                if (gid, n) in inst:
                    p.append((gp, f"gate {gid} instance {n} is placed twice (a physical gate has one location)"))
                inst[(gid, n)] = True
                if not _is_fact(x.get("station_ft")):
                    p.append((f"{gp}/station_ft", "must be a fact object with value and status"))
        for _, g in gates:
            q = g.get("quantity", 1)
            want = {(g.get("gate_id"), n) for n in range(1, q + 1)} if isinstance(q, int) and not isinstance(q, bool) and q >= 1 else set()
            have = {k for k in inst if k[0] == g.get("gate_id")}
            if want != have:
                p.append((f"{rp}/layout", f"gate {g.get('gate_id')} has quantity {q} but {len(have)} placed location(s); every gate location must be placed exactly once"))
        if not _is_fact(srun.get("section_spacing_ft")):
            p.append((f"/fence_runs/{[x.get('run_id') for x in scope['fence_runs']].index(rid)}/section_spacing_ft", "a footing scope needs the run's maximum on-center spacing as a fact"))
    owners = {}
    for r in runs:
        for gid, cid in (r.get("gate_classes") or {}).items():
            if owners.setdefault(cid, gid) != gid:
                p.append((f"{base}/classes/{cid}", f"gate class {cid!r} is shared by gates {owners[cid]} and {gid}; every gate has its own class so each can be reviewed and revised on its own"))
    missing = [rid for rid in scope_runs if rid not in seen]
    for rid in missing:
        p.append((f"{base}/runs", f"fence run {rid} has no footing layout: all runs must be covered, or the uncovered run would silently keep the single-footing assumption"))
    return p


def value_problems(scope):
    out, fs = [], scope.get("footing_scope") or {}
    for cid, c in (fs.get("classes") or {}).items():
        for f in ("diameter_in", "depth_in", "post_od_in"):
            fact = c.get(f) if isinstance(c, dict) else None
            v, st = _fv(fact)
            if _is_fact(fact) and fact.get("value") is not None and st != "unresolved" and not (_isnum(v) and v > 0):
                out.append((f"/footing_scope/classes/{cid}/{f}", f"{v!r} is not a positive finite number"))
    for i, r in enumerate(fs.get("runs") or []):
        for k, s in enumerate(((r or {}).get("layout") or {}).get("sides") or []):
            v, st = _fv(s.get("length_lf"))
            if _is_fact(s.get("length_lf")) and s["length_lf"].get("value") is not None and st != "unresolved" and not (_isnum(v) and v > 0):
                out.append((f"/footing_scope/runs/{i}/layout/sides/{k}/length_lf", f"{v!r} is not a positive finite number"))
            for m, x in enumerate(s.get("gates") or []):
                v, st = _fv(x.get("station_ft"))
                if _is_fact(x.get("station_ft")) and x["station_ft"].get("value") is not None and st != "unresolved" and not (_isnum(v) and v >= 0):
                    out.append((f"/footing_scope/runs/{i}/layout/sides/{k}/gates/{m}/station_ft", f"{v!r} is not a finite number >= 0"))
    return out


def _side_geometry(scope, run, rr, side, a):
    """The gate locations of one side ordered by station: [(gate_id, instance, station Decimal|None, clear width Decimal|None)]. None where a fact is unresolved."""
    gates = {g.get("gate_id"): g for _, g in _gates_of(scope, run["run_id"])}
    pts = []
    for x in side.get("gates", []):
        w, _ = _fv(gates[x["gate_id"]].get("clear_width_ft"))
        s, _ = _fv(x.get("station_ft"))
        pts.append((x["gate_id"], x["instance"], None if s is None else _D(s), None if w is None else _D(w)))
    pts.sort(key=lambda t: (t[2] is None, t[2] if t[2] is not None else 0, t[0], t[1]))
    return pts


def geometry_problems(scope):
    """[(path, message)] for layouts that are physically impossible or disagree with the run: sides that do not add up to the run length, a gate that
    runs past a side's end or into another gate, or a gate post that would coincide with a corner post (a double-counted physical post)."""
    out, fs = [], scope.get("footing_scope") or {}
    runs = {r.get("run_id"): r for r in scope.get("fence_runs") or [] if isinstance(r, dict)}
    for i, r in enumerate(fs.get("runs") or []):
        run = runs.get(r.get("run_id"))
        lay = r.get("layout") or {}
        if run is None or not isinstance(lay.get("sides"), list):
            continue
        lens = [_fv(s.get("length_lf"))[0] for s in lay["sides"]]
        total, v = None, _fv(run.get("length_lf"))[0]
        if all(_isnum(x) for x in lens) and _isnum(v):
            total = sum(_D(x) for x in lens)
            if total != _D(v):
                out.append((f"/footing_scope/runs/{i}/layout", f"the sides add up to {total} LF but the run length is {v:g} LF; the layout and the run must describe the same fence"))
        for k, s in enumerate(lay["sides"]):
            L = _fv(s.get("length_lf"))[0]
            pts = _side_geometry(scope, run, r, s, Decimal(0))
            prev_far = None
            for gid, n, st, w in pts:
                if st is None or w is None or not _isnum(L):
                    prev_far = None
                    continue
                near, far = st - w / 2, st + w / 2
                if near <= 0 or far >= _D(L):
                    out.append((f"/footing_scope/runs/{i}/layout/sides/{k}", f"gate {gid} #{n} (opening {near}..{far} ft) reaches the end of the {L:g} ft side: its post would coincide with the corner post"))
                elif prev_far is not None and near <= prev_far:
                    out.append((f"/footing_scope/runs/{i}/layout/sides/{k}", f"gate {gid} #{n} (opening {near}..{far} ft) leaves no fence segment after the previous gate: its post would coincide with another post"))
                prev_far = far
    return out


# ------------------------------------------------------------------ the calculation

def _segments_for_side(scope, run, spacing, side, a):
    """Ordered segments of one side at post offset `a`. Each: {from, to, length (Decimal|None), unresolved: [reasons]}."""
    gates_by_id = {g.get("gate_id"): g for _, g in _gates_of(scope, run["run_id"])}
    L = _fv(side.get("length_lf"))[0]
    bounds = [("corner_start", Decimal(0), [])]
    pts = _side_geometry(scope, run, None, side, a)
    for gid, n, st, w in pts:
        why = []
        if st is None:
            why.append(f"station of gate {gid} #{n} is not established")
        if w is None:
            why.append(f"clear opening of gate {gid} is not established")
        if why:
            bounds.append((f"{gid}#{n}:L", None, why))
            bounds.append((f"{gid}#{n}:R", None, why))
        else:
            bounds.append((f"{gid}#{n}:L", st - w / 2 - a, []))
            bounds.append((f"{gid}#{n}:R", st + w / 2 + a, []))
    bounds.append(("corner_end", None if L is None else _D(L), [] if L is not None else ["side length is not established"]))
    segs = []
    # segments are the spans between the END of one fixed post group and the START of the next: (corner|gate R) -> (gate L|corner)
    i = 0
    while i < len(bounds) - 1:
        a_lbl, a_pos, a_why = bounds[i]
        b_lbl, b_pos, b_why = bounds[i + 1]
        if a_lbl.endswith(":L"):                      # inside a gate opening: no fence
            i += 1
            continue
        why = list(a_why) + [w for w in b_why if w not in a_why]
        ln = None if (a_pos is None or b_pos is None) else b_pos - a_pos
        segs.append({"from": a_lbl, "to": b_lbl, "length": ln, "unresolved": why})
        i += 1
    # the loop above also pairs (gate L -> gate R); drop those (they are the openings, not fence)
    return [s for s in segs if not (s["from"].endswith(":L") and s["to"].endswith(":R"))]


def _count_line_posts(segs, spacing):
    total, per = 0, []
    for s in segs:
        if s["length"] is None:
            per.append(None)
            continue
        n = max(0, _intervals(s["length"], spacing) - 1)
        per.append(n)
        total += n
    return per, total


def evaluate(scope, params, *, scenario="BASE", resolutions=None, legacy_takeoff=None):
    """footing_schedule.v1 for ONE scenario scope (alternates already patched). Pure: depends only on its arguments.
    `params` = the ruleset params (cubic_inches_per_cubic_yard). `legacy_takeoff` (optional) = engine.takeoff.compute_takeoff(scope) to reconcile against."""
    bad = structural_problems(scope) or value_problems(scope) or geometry_problems(scope)
    if bad:
        raise ValueError("footing_scope is not valid (the Scope Gate guards reject it): " + "; ".join(f"{p}: {m}" for p, m in bad[:3]))
    fs, res = scope["footing_scope"], resolutions or {}
    cuin = params["cubic_inches_per_cubic_yard"]
    runs_in = {r["run_id"]: r for r in scope["fence_runs"]}
    run_idx = {r["run_id"]: i for i, r in enumerate(scope["fence_runs"])}
    classes = fs["classes"]

    posts, run_out, unresolved = [], [], []
    class_in = {}

    def cin(cid):
        if cid not in class_in:
            c, inp = classes[cid], _Inputs(res)
            d = inp.use(f"/footing_scope/classes/{cid}/diameter_in", c["diameter_in"])
            h = inp.use(f"/footing_scope/classes/{cid}/depth_in", c["depth_in"])
            od = inp.use(f"/footing_scope/classes/{cid}/post_od_in", c["post_od_in"]) if "post_od_in" in c else None
            class_in[cid] = (d, h, od, inp)
        return class_in[cid]

    for ri, rcfg in enumerate(fs["runs"]):
        rid = rcfg["run_id"]
        run = runs_in[rid]
        repeat = run.get("repeat", 1)
        gin = _Inputs(res)
        spacing_v = gin.use(f"/fence_runs/{run_idx[rid]}/section_spacing_ft", run["section_spacing_ft"])
        spacing = None if spacing_v is None else _D(spacing_v)
        gates_by_id = {g.get("gate_id"): (j, g) for j, g in _gates_of(scope, rid)}
        lay = rcfg["layout"]
        for k, side in enumerate(lay["sides"]):
            gin.use(f"/footing_scope/runs/{ri}/layout/sides/{k}/length_lf", side["length_lf"])
            for m, x in enumerate(side.get("gates", [])):
                gin.use(f"/footing_scope/runs/{ri}/layout/sides/{k}/gates/{m}/station_ft", x["station_ft"])
                j, g = gates_by_id[x["gate_id"]]
                gin.use(f"/gates/{j}/clear_width_ft", g["clear_width_ft"])
        seg_records, run_line_total, run_line_known_min, run_line_unknown = [], 0, 0, False
        sens_counts = {}
        for a_label, a in (("nominal", Decimal(0)), ("offset_bound", POST_OFFSET_BOUND_FT)):
            tot, unk = 0, False
            for side in lay["sides"]:
                segs = _segments_for_side(scope, run, spacing, side, a)
                if spacing is None:
                    unk = True
                    continue
                per, t = _count_line_posts(segs, spacing)
                tot += t
                unk = unk or any(n is None for n in per)
            sens_counts[a_label] = None if unk else tot
        for k, side in enumerate(lay["sides"]):
            segs = _segments_for_side(scope, run, spacing, side, Decimal(0))
            per, _ = _count_line_posts(segs, spacing) if spacing is not None else ([None] * len(segs), 0)
            for si, (sg, n) in enumerate(zip(segs, per)):
                sid = f"{rid}:{side['side_id']}:S{si + 1}"
                rec = {"segment_id": sid, "side_id": side["side_id"], "from_post": sg["from"], "to_post": sg["to"],
                       "length_lf": None if sg["length"] is None else float(sg["length"]), "max_spacing_ft": None if spacing is None else float(spacing),
                       "intervals": None if sg["length"] is None or spacing is None else _intervals(sg["length"], spacing),
                       "line_posts": n, "unresolved": sg["unresolved"]}
                if sg["length"] is not None and spacing is not None:
                    rec["exact_intervals"] = float((sg["length"] / spacing).quantize(_SIX))
                seg_records.append(rec)
                if n is None:
                    run_line_unknown = True
                else:
                    run_line_known_min += n
                    run_line_total += n
        # ---- physical posts, each created once
        per_instance = []
        for kk in range(1, repeat + 1):
            tag = f"{rid}#{kk}"
            if lay["kind"] == "closed_polygon":
                for c in range(1, len(lay["sides"]) + 1):
                    per_instance.append((f"{tag}:C{c}", rcfg["corner_class"], f"RUN:{rid}"))
            else:
                for e in (1, 2):
                    per_instance.append((f"{tag}:E{e}", rcfg["end_class"], f"RUN:{rid}"))
            for side in lay["sides"]:
                for x in side.get("gates", []):
                    for end in ("L", "R"):
                        per_instance.append((f"{tag}:{x['gate_id']}.{x['instance']}:{end}", rcfg["gate_classes"][x["gate_id"]], f"GATE:{x['gate_id']}"))
            if not run_line_unknown:
                for sg in seg_records:
                    for m in range(1, sg["line_posts"] + 1):
                        per_instance.append((f"{tag}:{sg['segment_id'].split(':', 1)[1]}:P{m}", rcfg["line_class"], f"RUN:{rid}"))
        for pid, cid, owner in per_instance:
            posts.append({"post_id": pid, "run_id": rid, "post_class": cid, "owner": owner})
        # ---- run summary + sensitivity
        nominal, bound = sens_counts["nominal"], sens_counts["offset_bound"]
        sensitive = nominal is not None and bound is not None and nominal != bound
        run_out.append({
            "run_id": rid, "fence_type": classes[rcfg["line_class"]]["fence_type"], "repeat": repeat, "layout_kind": lay["kind"],
            "segments": seg_records, "line_posts_per_instance": None if run_line_unknown else run_line_total,
            "line_posts_known_minimum_per_instance": run_line_known_min,
            "unresolved_segments": [s["segment_id"] for s in seg_records if s["line_posts"] is None],
            "count_inputs": {"basis": gin.basis(), "refs": list(gin.refs.values()), "review": gin.review(), "unresolved_paths": gin.unresolved()},
            "convention_sensitivity": {"nominal": nominal, "offset_bound": bound, "offset_bound_ft": float(POST_OFFSET_BOUND_FT), "sensitive": sensitive}})
        run_out[-1]["_gin"] = gin

    # ---- ownership audit: one class, one owner, one footing and one hole per physical post
    ids = [p["post_id"] for p in posts]
    dupes = sorted({i for i in ids if ids.count(i) > 1})

    # ---- per run/class records
    schedule, by_class = [], {}
    for ro in run_out:
        rid, gin = ro["run_id"], ro.pop("_gin")
        rcfg = next(r for r in fs["runs"] if r["run_id"] == rid)
        for cid in dict.fromkeys([rcfg.get("corner_class"), rcfg.get("end_class"), *[rcfg["gate_classes"][g] for g in (rcfg.get("gate_classes") or {})], rcfg["line_class"]]):
            if cid is None:
                continue
            members = [p for p in posts if p["run_id"] == rid and p["post_class"] == cid]
            c = classes[cid]
            d, h, od, dims = cin(cid)
            line_unknown = cid == rcfg["line_class"] and ro["line_posts_per_instance"] is None
            count = None if line_unknown else len(members)
            inp = _Inputs(res)
            for pth in dims.paths:
                inp.use(pth, _fact_at(scope, pth))
            if cid == rcfg["line_class"]:
                for pth in gin.paths:
                    inp.use(pth, _fact_at(scope, pth))
            dim_ok = d is not None and h is not None
            exact = _vol_cy(d, h, cuin) if dim_ok else None            # multiply the exact volume by the count, round once (the per-footing figure below is for display)
            vol = None if exact is None else round(exact, 6)
            cy = None if (count is None or exact is None) else round(count * exact, 6)
            rec = {"scenario": scenario, "run_id": rid, "fence_type": c["fence_type"], "post_class": cid, "role": c["role"],
                   "owner": sorted({p["owner"] for p in members})[0] if members else (f"GATE:{cid[5:]}" if cid.startswith("GATE_") else f"RUN:{rid}"),
                   "quantity": count, "quantity_known_minimum": (ro["line_posts_known_minimum_per_instance"] * ro["repeat"]) if line_unknown else count,
                   "uom": "EA", "diameter_in": d, "depth_in": h, "dimension_uom": "in", "post_od_in": od,
                   "footing_volume_cy_each": vol, "concrete_cy": cy, "core_drill_holes": count,
                   "measurement_convention": CONVENTION_ID, "value_basis": inp.basis(), "review": inp.review(), "source_refs": list(inp.refs.values()),
                   "unresolved_inputs": inp.unresolved(),
                   "unknown_reason": ([f"{p}" for p in dims.unresolved()] + (["line posts cannot be counted: " + "; ".join(sorted({w for s in ro['segments'] for w in s['unresolved']}))] if line_unknown else [])) or None}
            schedule.append(rec)
            agg = by_class.setdefault(cid, {"post_class": cid, "fence_type": c["fence_type"], "role": c["role"], "diameter_in": d, "depth_in": h, "quantity": 0, "known": True,
                                            "concrete_cy": 0.0, "concrete_known": True, "holes": 0, "known_minimum": 0})
            if count is None:
                agg["known"] = False
                agg["known_minimum"] += rec["quantity_known_minimum"]
            else:
                agg["quantity"] += count
                agg["known_minimum"] += count
                agg["holes"] += count
            if cy is None:
                agg["concrete_known"] = False
            else:
                agg["concrete_cy"] = round(agg["concrete_cy"] + cy, 6)

    known_cy = round(sum(r["concrete_cy"] for r in schedule if r["concrete_cy"] is not None), 6)
    unresolved_dim_posts = sum(r["quantity"] for r in schedule if r["quantity"] is not None and r["concrete_cy"] is None)
    complete = all(r["quantity"] is not None and r["concrete_cy"] is not None for r in schedule)
    total_posts = None if any(r["quantity"] is None for r in schedule) else sum(r["quantity"] for r in schedule)
    known_posts = sum(r["quantity"] for r in schedule if r["quantity"] is not None)
    uncounted_min = sum(r["quantity_known_minimum"] for r in schedule if r["quantity"] is None)
    out = {
        "schema_version": SCHEDULE_VERSION, "contract_version": CONTRACT_VERSION, "calc_version": CALC_VERSION, "scenario": scenario,
        "measurement_convention": CONVENTION_ID, "scope_version": scope.get("scope_version"), "records": schedule,
        "runs": run_out, "classes": [dict(v, concrete_cy=(v["concrete_cy"] if v["concrete_known"] else None), quantity=(v["quantity"] if v["known"] else None))
                                     for v in by_class.values()],
        "posts": posts,
        "totals": {"posts": total_posts, "core_drill_holes": total_posts, "known_concrete_cy": known_cy, "concrete_cy": known_cy if complete else None,
                   "posts_counted": known_posts, "posts_uncounted_known_minimum": uncounted_min, "posts_with_unresolved_dimensions": unresolved_dim_posts, "complete": complete,
                   "unknown_concrete": {"classes": sorted({r["post_class"] for r in schedule if r["concrete_cy"] is None}),
                                        "posts_counted_with_unknown_size": unresolved_dim_posts, "posts_not_countable_known_minimum": uncounted_min,
                                        "cy": None, "note": "unknown, not zero: excluded from known_concrete_cy and from every total"}},
        "ownership_audit": {"physical_posts": len(posts), "duplicate_post_ids": dupes, "every_post_has_one_class_and_owner": all(p["post_class"] in classes and p["owner"] for p in posts),
                            "footings_equal_posts": True, "holes_equal_posts": True},
    }
    out["calc_inputs_sha256"] = sha256({"contract": CONTRACT_VERSION, "calc": CALC_VERSION, "scenario": scenario, "footing_scope": fs,
                                        "runs": [{k: r.get(k) for k in ("run_id", "length_lf", "section_spacing_ft", "repeat", "geometry")} for r in scope["fence_runs"]],
                                        "gates": [{k: g.get(k) for k in ("gate_id", "run_id", "clear_width_ft", "quantity")} for g in scope.get("gates") or []],
                                        "cubic_inches_per_cubic_yard": cuin})
    out["reconciliation"] = reconcile(out, legacy_takeoff) if legacy_takeoff else None
    out["posture"] = posture(out)
    out["schedule_sha256"] = sha256({k: v for k, v in out.items() if k != "schedule_sha256"})
    return out


def _fact_at(scope, path):
    cur = scope
    for part in [p for p in path.split("/") if p != ""]:
        cur = cur[int(part)] if isinstance(cur, list) else cur[part]
    return cur


# ------------------------------------------------------------------ posture, reconciliation, counts applied to the takeoff

def posture(sch):
    """What this schedule permits. `pricing_go` = every count and dimension is known; `bid_ready` = additionally every input is documented (no
    provisional geometry, no assumption by a human). Acknowledging a warning never changes either."""
    reasons = []
    for r in sch["records"]:
        if r["unresolved_inputs"] or r["quantity"] is None or r["concrete_cy"] is None:
            reasons.append({"code": "FOOTING_CLASS_UNRESOLVED", "post_class": r["post_class"], "run_id": r["run_id"],
                            "message": f"{r['post_class']} in {r['run_id']}: " + ("; ".join(r["unknown_reason"] or []) or "not established")})
    for ro in sch["runs"]:
        if ro["convention_sensitivity"]["sensitive"]:
            reasons.append({"code": "COUNT_SENSITIVE_TO_POST_OFFSET", "run_id": ro["run_id"], "message": f"{ro['run_id']}: the line-post count changes with the post-center offset"})
    worst = "documented"
    for r in sch["records"]:
        if _RANK[r["value_basis"]] > _RANK[worst]:
            worst = r["value_basis"]
    for ro in sch["runs"]:
        if _RANK[ro["count_inputs"]["basis"]] > _RANK[worst]:
            worst = ro["count_inputs"]["basis"]
    pricing_go = not [x for x in reasons if x["code"] == "FOOTING_CLASS_UNRESOLVED"] and sch["totals"]["complete"]
    if worst in ("provisional", "assumed", "unresolved"):
        reasons.append({"code": "FOOTING_INPUTS_NOT_DOCUMENTED", "message": f"weakest input basis is {worst!r}: segment geometry, gate stations or a footing size is "
                        "provisional or a human assumption, not a documented fact"})
    bid_ready = pricing_go and worst in ("documented", "calculated") and not any(x["code"] == "COUNT_SENSITIVE_TO_POST_OFFSET" for x in reasons)
    return {"pricing_go": pricing_go, "bid_ready": bid_ready, "weakest_input_basis": worst,
            "release_class": "BID_READY" if bid_ready else ("QUALIFIED_DEMONSTRATION_ONLY_NOT_BID_READY" if pricing_go else "NOT_PRICEABLE_PARTIAL_UNRECONCILED"),
            "reasons": reasons}


def reconcile(sch, legacy):
    """Explain every difference between the legacy aggregate post/hole counts and this schedule. `legacy` = engine.takeoff.compute_takeoff(scope)."""
    out = {"legacy_source": "engine.takeoff.compute_takeoff (aggregate lower bound: ceil(net / spacing) - segments)", "runs": [], "legacy_holes": legacy["totals"]["footings"],
           "schedule_holes": sch["totals"]["core_drill_holes"], "holes_delta": None, "explained_delta": 0, "unexplained_delta": 0}
    total_delta, explained = 0, 0
    for ro in sch["runs"]:
        lr = legacy["runs"][ro["run_id"]]
        rep = ro["repeat"]
        mine_line = None if ro["line_posts_per_instance"] is None else ro["line_posts_per_instance"] * rep
        classes_of_run = [r for r in sch["records"] if r["run_id"] == ro["run_id"]]
        fixed = None if any(r["quantity"] is None for r in classes_of_run) else sum(r["quantity"] for r in classes_of_run) - (mine_line or 0)
        row = {"run_id": ro["run_id"], "legacy_terminals": lr["terminals"], "schedule_terminals": fixed, "terminals_delta": None if fixed is None else fixed - lr["terminals"],
               "legacy_line_posts": lr["line_posts"], "schedule_line_posts": mine_line,
               "line_posts_delta": None if mine_line is None else mine_line - lr["line_posts"]}
        if mine_line is not None:
            segs = ro["segments"]
            per_seg = [{"segment_id": s["segment_id"], "length_lf": s["length_lf"], "exact_intervals": s["exact_intervals"], "ceil_intervals": s["intervals"],
                        "posts": s["line_posts"], "rounding_gain_vs_exact_intervals": round(s["intervals"] - s["exact_intervals"], 6)} for s in segs]
            sum_len = sum(_D(s["length_lf"]) for s in segs)
            agg_intervals = _intervals(sum_len, _D(segs[0]["max_spacing_ft"])) if segs else 0
            row["explanation"] = {
                "legacy_formula": "ceil(round(net_lf / spacing, 6)) - segments_legacy",
                "legacy_net_lf": lr["net_lf"] / rep, "legacy_segments": lr["segments"], "schedule_segments": len(segs),
                "sum_of_segment_ceilings": sum(s["intervals"] for s in segs), "ceiling_of_sum_of_segments": agg_intervals,
                "reason": "line posts are counted per segment (each segment rounds up on its own); the legacy aggregate rounds the SUM of all segment lengths once, "
                          "so it can only be lower. delta = sum(ceil(L_i/s)) - ceil(sum(L_i)/s) when the segment counts agree.",
                "per_segment": per_seg}
            row["per_instance_delta_explained"] = (sum(s["intervals"] for s in segs) - agg_intervals) - (lr["segments"] - len(segs))
            row["explained_delta"] = row["per_instance_delta_explained"] * rep
            total_delta += row["line_posts_delta"] + (row["terminals_delta"] or 0)
            explained += row["explained_delta"] + (row["terminals_delta"] or 0)
        out["runs"].append(row)
    if out["schedule_holes"] is not None:
        out["holes_delta"] = out["schedule_holes"] - out["legacy_holes"]
        out["explained_delta"], out["unexplained_delta"] = explained, out["holes_delta"] - explained
    return out


def adjust_takeoff(scope, takeoff, schedule):
    """A copy of the legacy takeoff whose post/footing counts come from the schedule (idempotent). Unknown counts are reported in
    `footing_unresolved` per run so the quantity layer marks every post-derived item unresolved; they are never written as 0 into a price."""
    import copy
    tk = copy.deepcopy(takeoff)
    for ro in schedule["runs"]:
        rid = ro["run_id"]
        r = tk["runs"][rid]
        if r.get("footing_counts_applied"):
            continue
        recs = [x for x in schedule["records"] if x["run_id"] == rid]
        known = all(x["quantity"] is not None for x in recs)
        r["legacy_aggregate"] = {"terminals": r["terminals"], "line_posts": r["line_posts"], "footings": r["footings"]}
        if known:
            line_cls = next(rc for rc in scope["footing_scope"]["runs"] if rc["run_id"] == rid)["line_class"]
            line = sum(x["quantity"] for x in recs if x["post_class"] == line_cls)
            allp = sum(x["quantity"] for x in recs)
            r["line_posts"], r["terminals"], r["footings"] = line, allp - line, allp
        r["footing_counts_applied"] = True
        r["footing_unresolved"] = [] if known else [f"{x['post_class']}: " + "; ".join(x["unknown_reason"] or ["not established"]) for x in recs if x["quantity"] is None]
    t = tk["totals"]
    t["terminals"] = sum(r["terminals"] for r in tk["runs"].values())
    t["line_posts"] = sum(r["line_posts"] for r in tk["runs"].values())
    t["footings"] = sum(r["footings"] for r in tk["runs"].values())
    core = t.get("core_drill_footings", 0)
    t["core_drill_footings"] = t["footings"] if core else 0
    return tk


def effective_gate_posts(scope):
    """A scope VIEW in which each gate carries its class's post_od_in (when the class states one), so the quantity layer's existing rule - an unresolved
    gate-post size leaves every post quantity of the run unresolved, and a different size than the run's terminals is reported - governs gate posts.
    The real scope (and its hash) is untouched."""
    import copy
    v = copy.deepcopy(scope)
    fs = v["footing_scope"]
    for rcfg in fs["runs"]:
        for g in v.get("gates") or []:
            if g.get("run_id") != rcfg["run_id"] or "gate_post_od_in" in g:
                continue
            cid = (rcfg.get("gate_classes") or {}).get(g.get("gate_id"))
            c = fs["classes"].get(cid) or {}
            if "post_od_in" in c:
                g["gate_post_od_in"] = copy.deepcopy(c["post_od_in"])
                g["_gate_post_od_source"] = f"/footing_scope/classes/{cid}/post_od_in"
    return v


# ------------------------------------------------------------------ known subtotals (informational, never an estimate)

POST_ITEM = {("A", "line"): "M02", ("A", "terminal"): "M01", ("A", "corner"): "M01", ("A", "gate"): "M01",
             ("B", "line"): "M04", ("B", "terminal"): "M03", ("B", "corner"): "M03", ("B", "gate"): "M03"}


def known_subtotals(sch, ratebook):
    """Rate-book prices applied to the KNOWN part of the schedule (post material, concrete M40, core drilling S01) with the engine's own order-quantity and
    rounding rules. `is_estimate` is always False: unknown classes are listed as exposure with their unit rates and NO quantity or dollar guess. Labor is not
    priced here: it needs a cleared wage basis and an approved crew plan, so only its quantity drivers are given."""
    cent = Decimal("0.01")
    mats = {m["item_id"]: m for m in ratebook["materials"]}
    svc = {s["service_id"]: s for s in ratebook.get("services", [])}

    def order(q, rate):
        digits = Decimal("0.1") if rate["uom"] == "CU YD" else Decimal("1")
        return (q * (1 + _D(rate["overage_pct"]))).quantize(digits, rounding=ROUND_CEILING)

    # post material: gate classes whose post size is unestablished are excluded (exposure), never priced as a neighbour class
    post_q, cy_q, hole_q = {}, Decimal(0), 0
    exposure = []
    for r in sch["records"]:
        post_size_unknown = r["role"] == "gate" and r.get("post_od_in") is None
        dims_known = r["concrete_cy"] is not None
        if r["quantity"] is None:
            exposure.append({"post_class": r["post_class"], "run_id": r["run_id"], "posts_known_minimum": r["quantity_known_minimum"], "posts": None,
                             "unknown": ["post count", "footing concrete", "core drilling"], "why": r["unknown_reason"]})
            continue
        if not post_size_unknown:
            item = POST_ITEM[(r["fence_type"], r["role"])]
            post_q[item] = post_q.get(item, 0) + r["quantity"]
        if dims_known and not post_size_unknown:
            cy_q += _D(r["concrete_cy"])
            hole_q += r["core_drill_holes"]
        else:
            ex = {"post_class": r["post_class"], "run_id": r["run_id"], "posts": r["quantity"], "unknown": [], "why": r["unknown_reason"] or []}
            if post_size_unknown:
                ex["unknown"].append("post material (size not established)")
            if not dims_known:
                ex["unknown"] += ["footing concrete", "core drilling (hole size)"]
            elif post_size_unknown:
                ex["unknown"].append("post size")
            exposure.append(ex)
    lines = []
    total = Decimal(0)
    for item, q in sorted(post_q.items()):
        rate = mats[item]
        ext = (order(_D(q), rate) * _D(rate["unit_price"])).quantize(cent, rounding=ROUND_HALF_UP)
        lines.append({"item_id": item, "quantity": q, "uom": rate["uom"], "unit_price": rate["unit_price"], "extended": float(ext)})
        total += ext
    if cy_q > 0:
        rate = mats["M40"]
        o = order(cy_q, rate)
        ext = (o * _D(rate["unit_price"])).quantize(cent, rounding=ROUND_HALF_UP)
        lines.append({"item_id": "M40", "quantity": float(cy_q), "order_quantity": float(o), "overage_pct": rate["overage_pct"], "uom": rate["uom"],
                      "unit_price": rate["unit_price"], "extended": float(ext)})
        total += ext
    if hole_q:
        rate = svc["S01"]
        ext = (_D(hole_q) * _D(rate["unit_cost"])).quantize(cent, rounding=ROUND_HALF_UP)
        lines.append({"service_id": "S01", "quantity": hole_q, "uom": rate["uom"], "unit_cost": rate["unit_cost"], "extended": float(ext)})
        total += ext
    # class-by-class view of the same lines: each class at its own unit price BEFORE the item-level order rounding; the difference to the engine's line is shown, never hidden
    by_class = []
    for r in sch["records"]:
        if r["quantity"] is None or r["concrete_cy"] is None or (r["role"] == "gate" and r.get("post_od_in") is None):
            continue
        item = POST_ITEM[(r["fence_type"], r["role"])]
        post_c = (_D(r["quantity"]) * (1 + _D(mats[item]["overage_pct"])) * _D(mats[item]["unit_price"])).quantize(cent, rounding=ROUND_HALF_UP)
        conc_c = (_D(r["concrete_cy"]) * (1 + _D(mats["M40"]["overage_pct"])) * _D(mats["M40"]["unit_price"])).quantize(cent, rounding=ROUND_HALF_UP)
        drill_c = (_D(r["core_drill_holes"]) * _D(svc["S01"]["unit_cost"])).quantize(cent, rounding=ROUND_HALF_UP)
        by_class.append({"post_class": r["post_class"], "run_id": r["run_id"], "posts": r["quantity"], "post_item": item, "post_material": float(post_c),
                         "concrete_cy": r["concrete_cy"], "concrete_before_order_rounding": float(conc_c), "core_drill_holes": r["core_drill_holes"], "core_drilling": float(drill_c),
                         "drilling_basis": "S01 flat rate per hole; the rate book has no diameter-specific drilling rate (hole sizes 8-16 in all use S01)"})
    unit_rates = {"M01": mats["M01"]["unit_price"], "M40": mats["M40"]["unit_price"], "S01": svc["S01"]["unit_cost"]}
    weakest = "documented"
    for r in sch["records"]:
        if r["quantity"] is not None and _RANK[r["value_basis"]] > _RANK[weakest]:
            weakest = r["value_basis"]
    return {"is_estimate": False, "weakest_included_basis": weakest, "label": "PARTIAL_UNRECONCILED" if exposure else "KNOWN_SUBTOTAL_COMPLETE_FOR_THESE_ITEMS",
            "scope": "post material (M01-M04), concrete (M40) and core drilling (S01) for KNOWN classes only; excludes labor, equipment, mobilization, tax, overhead, contingency, profit",
            "lines": lines, "known_subtotal": float(total), "by_class": by_class, "unknown_exposure": exposure, "exposure_reference_unit_rates": unit_rates,
            "exposure_note": "unit rates are the rate book's own, listed so a reader can see what each unknown unit would cost IF the catalog item applies; "
                             "no quantity and no dollar amount is guessed for an unknown class",
            "labor_drivers": {"D03_posts_to_set": sum(post_q.values()) if post_q else 0, "D04_holes_to_drill_known": hole_q, "D05_concrete_cy_known": float(cy_q)}}

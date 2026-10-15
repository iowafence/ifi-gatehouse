"""Deterministic quantity layer (Layer B): structured scope + takeoff -> `quantity_payload.v1`.

AI interprets evidence; this module only does arithmetic on facts that already passed the Scope Gate guards. It never
reads a price, a rate book, a spreadsheet or a model. Every quantity carries
  * a stable item_id (M01..M40) or driver_key (D01..D12) and its canonical unit,
  * the scenario it belongs to (BASE or ALT-*; a COMPLETE scenario, not a delta),
  * the fact paths and document revisions it was computed from,
  * a calculation_method a reviewer can read,
  * a status: confirmed (every input confirmed or human-resolved), provisional (an input is only inferred), or
    unresolved (an input is missing: quantity is null, never 0), plus the human resolutions it depends on.
An item the scope structurally does not contain (e.g. no windscreen) is an explicit, confirmed 0.
Scope with no catalog item (e.g. a fence guard) comes back as `mapping_problems`; it is never silently dropped."""
import hashlib
import json
import math
import pathlib

from . import footings, vocab
from .ratebook import canonical

RULES_PATH = pathlib.Path(__file__).resolve().parent / "data" / "quantity_rules.v1.json"
_RANK = {"confirmed": 0, "provisional": 1, "unresolved": 2}
# items that cannot be attributed when a run's post sizes match no catalog family
MODELED_GLOBALS = {"top_rail_continuous_across_gate_openings", "footing_terminal_diameter_in", "footing_terminal_depth_in",
                   "footing_line_diameter_in", "footing_line_depth_in", "core_drilling_required", "owner_sales_tax_exempt",
                   "prevailing_wage_required", "certified_payroll_required", "install_sequence"}      # install_sequence orders the work; it prices nothing
FAMILY_ITEMS = ("S01", "M01", "M02", "M03", "M04", "M05", "M06", "M07", "M08", "M09", "M10", "M11", "M12", "M13", "M14", "M15",
                "M16", "M17", "M18", "M19", "M20", "M23", "M24", "M25", "M26", "M27", "M40",
                "D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "D11")


def load_ruleset(path=None):
    rules = json.loads(pathlib.Path(path or RULES_PATH).read_bytes())
    return {"rules": rules, "sha256": hashlib.sha256(canonical(rules).encode()).hexdigest(),
            "ruleset_id": rules["ruleset_id"], "version": rules["version"]}


def scenario_scopes(scope):
    """{'BASE': scope, 'ALT-x': scope with that alternate's patch applied}. If the scope was already patched to an
    alternate (selected_bid names it) BASE is not recoverable and is omitted rather than invented."""
    from engine.util import apply_patch
    bid = scope.get("bid_structure") or {}
    sel = (bid.get("selected_bid") or {}).get("value")
    out = {vocab.BASE: scope} if sel in (None, "base") else {}
    for alt in bid.get("alternates") or []:
        aid = alt.get("alternate_id")
        if sel == aid:
            out[aid] = scope
        elif sel in (None, "base") and alt.get("patch"):
            out[aid] = apply_patch(scope, alt["patch"])
    return out


# ------------------------------------------------------------------ provenance

def _state(fact):
    if not isinstance(fact, dict) or "value" not in fact:
        return None, "unresolved"
    v, st = fact.get("value"), fact.get("status")
    if v is None or st == "unresolved":
        return None, "unresolved"
    if st in ("confirmed", "human_resolved"):
        return v, "confirmed"
    if st == "inferred":
        return v, "provisional"
    return None, "unresolved"


def _evidence_ref(path, fact):
    ref = {"fact_path": path}
    ev = [e for e in (fact.get("evidence") or []) if isinstance(e, dict) and e.get("doc_id")] if isinstance(fact, dict) else []
    if ev:
        e = max(enumerate(ev), key=lambda ie: (ie[1].get("doc_revision", 0), ie[0]))[1]     # newest revision governs
        ref["doc_id"] = e["doc_id"]
        if isinstance(e.get("doc_revision"), int):
            ref["doc_revision"] = e["doc_revision"]
        if isinstance(e.get("page"), int) and e["page"] >= 1:
            ref["page"] = e["page"]
        if e.get("sheet_label"):
            ref["sheet_label"] = str(e["sheet_label"])[:100]
    return ref


class Inp:
    """The facts one quantity is computed from and how settled they are. Compose with +."""

    def __init__(self, resolutions=None):
        self.status, self.reasons, self.refs, self.res = "confirmed", [], {}, resolutions or {}

    def use(self, path, fact, label=None):
        v, st = _state(fact)
        self.refs.setdefault(path, _evidence_ref(path, fact))
        if st == "unresolved":
            self.reasons.append(f"{label or path} is not established by the documents")
        elif _RANK[st] > _RANK[self.status]:
            self.status = st
        return v

    def why_not(self, reason):
        self.reasons.append(reason)
        return self

    def __add__(self, other):
        out = Inp(self.res)
        for o in (self, other):
            out.reasons += [r for r in o.reasons if r not in out.reasons]
            out.refs.update(o.refs)
            if _RANK[o.status] > _RANK[out.status]:
                out.status = o.status
        return out

    def resolutions(self):
        seen, out = set(), []
        for path in self.refs:
            r = self.res.get(path)
            if r and r["exception_id"] not in seen:
                seen.add(r["exception_id"])
                out.append(dict(r))
        return out


def _sum(*inps):
    out = inps[0]
    for i in inps[1:]:
        out = out + i
    return out


class _Acc:
    def __init__(self):
        self.items = {}

    def add(self, key, value, method, inp):
        it = self.items.setdefault(key, {"q": 0.0, "methods": [], "inp": Inp(inp.res)})
        it["inp"] = it["inp"] + inp
        if method not in it["methods"]:
            it["methods"].append(method)
        if inp.reasons or value is None:
            it["q"] = None
        elif it["q"] is not None:
            it["q"] += value

    def block(self, key, reason):
        it = self.items.setdefault(key, {"q": None, "methods": ["cannot be attributed"], "inp": Inp()})
        it["q"] = None
        it["inp"].why_not(reason)


def _yes(ge, name):
    v = _state(ge.get(name))[0] if isinstance(ge.get(name), dict) else None
    return v is not None and str(v).strip().lower() == "yes"


def _ceil(x):
    return int(math.ceil(round(x, 6)))


def _near(a, b, tol=1e-6):
    return a is not None and abs(a - b) <= tol


def _geom(run, name):
    g = run.get("geometry") or {}
    return g.get("free_ends", 0 if g.get("closed", False) else 2) if name == "free_ends" else g.get(name, 0)


def _od_item(table, od):
    if od is None:
        return None
    return next((v for k, v in table.items() if _near(od, float(k), 1e-3)), None)


def _family(rules, t_od, l_od):
    if t_od is None or l_od is None:
        return None
    return next((f for f in rules["families"] if any(_near(t_od, x, 1e-3) for x in f["terminal_od_in"])
                 and any(_near(l_od, x, 1e-3) for x in f["line_od_in"])), None)


# ------------------------------------------------------------------ the builder

class _Run:
    """Everything known about one fence run: values plus the provenance each derived number inherits."""

    def __init__(self, scope, takeoff, i, run, rules, res):
        self.i, self.run, self.rid, self.rep = i, run, run["run_id"], run.get("repeat", 1)
        self.tr, base = takeoff["runs"][self.rid], f"/fence_runs/{i}"
        self.base = base
        post = run.get("post") or {}
        self.I_len, self.I_h, self.I_sp, self.I_od, self.I_gw = (Inp(res) for _ in range(5))
        self.length = self.I_len.use(f"{base}/length_lf", run.get("length_lf"), f"run {self.rid} length")
        self.height = self.I_h.use(f"{base}/height_ft", run.get("height_ft"), f"run {self.rid} height")
        self.spacing = self.I_sp.use(f"{base}/section_spacing_ft", run.get("section_spacing_ft"), f"run {self.rid} section spacing")
        self.t_od = self.I_od.use(f"{base}/post/terminal_od_in", post.get("terminal_od_in"), f"run {self.rid} terminal post OD")
        self.l_od = self.I_od.use(f"{base}/post/line_od_in", post.get("line_od_in"), f"run {self.rid} line post OD")
        self.fam = _family(rules, self.t_od, self.l_od)
        self.gates = []
        for j, g in enumerate(scope.get("gates", [])):
            if g.get("run_id") == self.rid:
                self.gates.append(_Gate(j, g, self, res))
        for g in self.gates:
            self.I_gw = self.I_gw + g.I_w
            self.I_od = self.I_od + g.I_gp          # an unresolved gate-post size leaves every post quantity of the run unresolved
        widths = [g.w for g in self.gates]
        self.gate_open = None if any(w is None for w in widths) else sum(g.w * g.per_run_qty for g in self.gates)
        self.gross = self.length
        self.net = None if self.length is None or self.gate_open is None else self.length - self.gate_open
        self.ends = _geom(run, "free_ends") + 2 * _geom(run, "corners") + 2 * sum(g.per_run_qty for g in self.gates)
        self.I_net = self.I_len + self.I_gw
        self.I_posts = self.I_net + self.I_sp + self.I_od
        self.I_holes, self.foot = self.I_posts, None         # footing-scope.v1 mode replaces these (see _attach_footing)


class _Gate:
    def __init__(self, j, g, run, res):
        base, self.gid = f"/gates/{j}", g.get("gate_id")
        self.I_w, self.I_h, self.I_kind, self.I_th = (Inp(res) for _ in range(4))
        self.per_run_qty, self.qty = g.get("quantity", 1), g.get("quantity", 1) * run.rep
        self.w = self.I_w.use(f"{base}/clear_width_ft", g.get("clear_width_ft"), f"gate {self.gid} clear width")
        self.h = self.I_h.use(f"{base}/height_ft", g.get("height_ft"), f"gate {self.gid} height")
        self.kind = self.I_kind.use(f"{base}/gate_kind", g.get("gate_kind"), f"gate {self.gid} kind")
        self.I_gp = Inp(res)       # gate post size: some specs tie it to the opening width (32 31 13 2.1.B); stated only when the documents say so
        self.post_od = self.I_gp.use(g.get("_gate_post_od_source") or f"{base}/gate_post_od_in", g["gate_post_od_in"], f"gate {self.gid} post size") if isinstance(g.get("gate_post_od_in"), dict) else None
        tr = g.get("transom") or {}
        th = self.I_th.use(f"{base}/transom/height_ft", tr["height_ft"]) if isinstance(tr.get("height_ft"), dict) else None
        if th is not None and (isinstance(th, bool) or not isinstance(th, (int, float)) or not math.isfinite(th) or th <= 0):
            self.I_th.why_not(f"gate {self.gid} transom height {th!r} is not a positive number")
            th = None
        if th is None and self.h is not None and run.height is not None:
            th = max(0.0, run.height - self.h)
            self.I_th = self.I_h + run.I_h
        elif th is None:
            self.I_th.why_not(f"gate {self.gid} transom height is not established")
        self.th = th


def build_payload(scope, takeoff, ruleset, *, scope_ref=vocab.BASE, resolutions=None, ruleset_approval=None, project_ref=None):
    """Return {'payload': quantity_payload.v1, 'mapping_problems': [...]} for ONE scenario of `scope`."""
    if takeoff is None:
        raise ValueError("a takeoff is required: quantities are only generated for a scope without blocking exceptions")
    rules, P = ruleset["rules"], ruleset["rules"]["params"]
    res = resolutions or {}
    scope_identity = scope                       # what the payload revision hashes: the scope as stored, never the view built below
    foot = None
    if "footing_scope" in scope:                 # footing-scope.v1: per-run, per-post-class counts, concrete and holes (optional, additive)
        foot = footings.evaluate(scope, P, scenario=scope_ref, resolutions=res)
        takeoff = footings.adjust_takeoff(scope, takeoff, foot)
        scope = footings.effective_gate_posts(scope)
    acc, problems, fam_fail = _Acc(), [], []
    ge = scope.get("global_requirements") or {}

    I_cont = Inp(res)
    cont = I_cont.use("/global_requirements/top_rail_continuous_across_gate_openings", ge.get("top_rail_continuous_across_gate_openings"),
                      "whether the top rail runs continuously across gate openings")
    cont = {"yes": True, "no": False}.get(str(cont).strip().lower()) if cont is not None else None
    if cont is None and not I_cont.reasons:
        I_cont.why_not("top_rail_continuous_across_gate_openings must be yes or no")

    I_core = Inp(res)
    core_yes = isinstance(ge.get("core_drilling_required"), dict) and I_core.use(
        "/global_requirements/core_drilling_required", ge["core_drilling_required"], "whether core drilling is required") is not None and _yes(ge, "core_drilling_required")
    I_tax = Inp(res)
    tax_exempt = isinstance(ge.get("owner_sales_tax_exempt"), dict) and I_tax.use(
        "/global_requirements/owner_sales_tax_exempt", ge["owner_sales_tax_exempt"], "whether the owner is sales-tax exempt") is not None and _yes(ge, "owner_sales_tax_exempt")
    for key, fact in ge.items():          # no silent omission: any other stated requirement the catalog does not model is reported
        if key in MODELED_GLOBALS or not isinstance(fact, dict) or fact.get("price_affecting") is False:
            continue
        if _state(fact)[0] is not None:
            problems.append({"code": "NO_ITEM_MAPPING", "path": f"/global_requirements/{key}",
                             "message": f"requirement {key!r} = {fact.get('value')!r} is not modeled by the pricing catalog and would not be priced"})
    for i, run in enumerate(scope.get("fence_runs", [])):
        ft = _state(run.get("fence_type"))[0]
        if ft is not None and str(ft).strip().lower().replace(" ", "_").replace("-", "_") != "chain_link":
            problems.append({"code": "NO_ITEM_MAPPING", "path": f"/fence_runs/{i}/fence_type",
                             "message": f"run {run.get('run_id')} is {ft!r}; the rate-book catalog prices chain link only"})
        r = _Run(scope, takeoff, i, run, rules, res)
        if foot:
            problems.extend(_attach_footing(r, scope_identity, foot, res))
        for g in r.gates:
            if g.post_od is not None and r.t_od is not None and not _near(g.post_od, r.t_od, 1e-3):
                problems.append({"code": "NO_ITEM_MAPPING", "path": f"/gates/{g.gid}/gate_post_od_in",
                                 "message": f"gate {g.gid} posts are {g.post_od:g} in OD but the run's terminal posts are {r.t_od:g} in; mixed post sizes in one run are not modeled"})
        if r.fam is None:
            why = (f"run {r.rid}: post sizes {r.t_od}/{r.l_od} in match no catalog fence family" if not r.I_od.reasons
                   else f"run {r.rid}: post sizes are not established")
            fam_fail.append(why)
            if not r.I_od.reasons:
                problems.append({"code": "NO_FAMILY_MAPPING", "path": f"{r.base}/post", "message": why + "; no rate-book item exists for them"})
        _posts(acc, r, rules, P, fam_fail, problems)
        _lengths_and_rails(acc, r, rules, P, cont, I_cont)
        _bars_bands_ties(acc, r, rules, P, fam_fail, cont, I_cont)
        for g in r.gates:
            _gate(acc, r, g, rules, P, problems)
        if foot:
            _concrete_by_class(acc, r, foot, P)
        else:
            _concrete(acc, r, ge, P, res)
        if core_yes:
            acc.add("S01", r.tr["footings"], "core drilling = one unit per footing hole, through pavement and base (Section 32 31 13 3.2.E)" + (_foot_tag(foot) if foot else ""),
                    r.I_holes + I_core)
    for k, a in enumerate(scope.get("accessories", [])):
        _accessory(acc, k, a, P, res, problems)
    for key in FAMILY_ITEMS:
        for why in dict.fromkeys(fam_fail):
            acc.block(key, why)

    items = []
    for key in list(vocab.MATERIALS) + list(vocab.SERVICES) + list(vocab.DRIVERS):
        it, unit = acc.items.get(key), vocab.uom(key)
        if it is None:
            items.append(_item(key, unit, scope_ref, 0, "none of this item in the scope", Inp(res), "confirmed"))
        elif it["q"] is None or it["inp"].reasons:
            items.append(_item(key, unit, scope_ref, None, "; ".join(it["methods"]), it["inp"], "unresolved"))
        else:
            items.append(_item(key, unit, scope_ref, round(it["q"], 6), "; ".join(it["methods"]), it["inp"], it["inp"].status))
    return {"payload": {
        "schema_version": "quantity_payload.v1",
        "project_ref": project_ref or scope.get("project_ref") or "UNSPECIFIED",
        "revision": {"scope_version": scope.get("scope_version", 1),
                     "scope_sha256": hashlib.sha256(canonical(scope_identity).encode()).hexdigest(),
                     "ruleset": {"ruleset_id": ruleset["ruleset_id"], "version": ruleset["version"], "sha256": ruleset["sha256"],
                                 "approved": bool(ruleset_approval), "approved_by": (ruleset_approval or {}).get("by")},
                     "sales_tax_exemption": {"applies": bool(tax_exempt), "evidence_refs": list(I_tax.refs.values()) if tax_exempt else []}},
        "items": items}, "mapping_problems": problems}


def _posts(acc, r, rules, P, fam_fail, problems):
    tr = r.tr
    if r.fam:
        acc.add(r.fam["terminal_post_item"], tr["terminals"], f"terminal posts (corners + free ends + 2 per gate), family {r.fam['family']}, from takeoff", r.I_posts)
        acc.add(r.fam["line_post_item"], tr["line_posts"], f"line posts, family {r.fam['family']}, from takeoff", r.I_posts)
    for od, cnt, what in ((r.t_od, tr["terminals"], "terminal"), (r.l_od, tr["line_posts"], "line")):
        item = _od_item(rules["by_post_od"]["cap_item"], od)
        if item:
            acc.add(item, cnt, f"post caps = one per {what} post of that OD", r.I_posts)
        elif od is not None:
            fam_fail.append(f"run {r.rid}: no post cap item for {od} in OD")
            problems.append({"code": "NO_ITEM_MAPPING", "path": f"{r.base}/post", "message": f"no post cap item for {od} in OD"})
    acc.add("D03", tr["terminals"] + tr["line_posts"], "posts to set = terminals + line posts, from takeoff", r.I_posts)
    acc.add("D04", tr["footings"], "footing holes = one per post, from takeoff" + (_foot_tag(r.foot) if r.foot else ""), r.I_holes)
    acc.add("M08", tr["braces"], "fence truss rods = brace assemblies from takeoff", r.I_posts + r.I_h)
    acc.add("D08", tr["braces"], "braces = brace assemblies from takeoff", r.I_posts + r.I_h)
    if tr["braces"]:
        for side, per, od in (("terminal_side", "brace_bands_terminal_side_per_brace", r.t_od), ("line_side", "brace_bands_line_side_per_brace", r.l_od)):
            item = _od_item(rules["by_post_od"][f"brace_band_{side}_item"], od)
            if item:
                acc.add(item, tr["braces"] * P[per], f"brace bands {side.replace('_', ' ')} = {P[per]} per brace assembly", r.I_posts + r.I_h)
            else:
                fam_fail.append(f"run {r.rid}: no {side.replace('_', ' ')} brace band item for OD {od}")


def _lengths_and_rails(acc, r, rules, P, cont, I_cont):
    rep, net, gross = r.rep, r.net, r.gross
    n = None if net is None else net * rep
    if r.fam:
        item_inp = r.I_net + r.I_h + r.I_od
        if r.height is not None and not _near(r.height * 12, r.fam["fabric_height_in"]):
            item_inp = item_inp.why_not(f"run {r.rid} height {r.height:g} ft has no catalog fabric (family {r.fam['family']} is {r.fam['fabric_height_in']} in)")
        acc.add(r.fam["fabric_item"], n, f"net fabric LF = run length - gate openings, family {r.fam['family']}", item_inp)
        acc.add(r.fam["net_length_driver"], n, f"net fence length of family {r.fam['family']} runs", r.I_net + r.I_od)
    acc.add("D07", n, "fabric to hang = net fence LF, all runs", r.I_net)
    acc.add("D11", n, "bottom tension wire to install = net fence LF (no wire across openings)", r.I_net)
    acc.add("M23", n, "bottom tension wire LF = net fence LF", r.I_net)
    acc.add("D12", None if gross is None else gross * rep, "layout/stakeout = gross run length (openings included)", r.I_len)

    top = None if cont is None else (gross if cont else net)
    top_inp = I_cont + (r.I_len if cont else r.I_net)
    method = ("top rail LF = gross run length (continuous across gate openings per the drawings)" if cont
              else "top rail LF = net length (rail stops at gate openings per the drawings)")
    acc.add("M05", None if top is None else top * rep, method, top_inp)
    acc.add("D06", None if top is None else top * rep, "top rail to install = M05 quantity", top_inp)
    sleeves, sleeve_inp = (None if top is None else max(0, _ceil(top / P["rail_stick_ft"]) - 1)), top_inp
    if r.fam and r.fam["mid_rail"]:
        sleeve_inp = _sum(sleeve_inp, r.I_net, r.I_h, *[g.I_h for g in r.gates])
    if r.fam and r.fam["mid_rail"]:
        tall = r.height is not None and r.height >= P["mid_rail_min_run_height_ft"]
        if r.height is None:
            acc.add("M06", None, "mid rail LF", r.I_h)
        elif tall:
            crossing = sum(g.w * g.per_run_qty for g in r.gates if g.h is not None and g.h <= P["mid_rail_elevation_ft"] + 1e-9)
            mid = None if net is None else net + crossing
            acc.add("M06", None if mid is None else mid * rep,
                    "mid rail LF at the catalog elevation = net length + openings whose gate leaf is not taller than the rail; the brace rail is the mid rail, not added",
                    _sum(r.I_net, r.I_h, *[g.I_h for g in r.gates]))
            sleeves = None if sleeves is None or mid is None else sleeves + max(0, _ceil(mid / P["rail_stick_ft"]) - 1)
            sleeve_inp = sleeve_inp + r.I_net + r.I_h
    acc.add("M07", None if sleeves is None else sleeves * rep, f"rail sleeves = ceil(rail LF / {P['rail_stick_ft']} ft stick) - 1, per rail line per run", sleeve_inp)


def _bars_bands_ties(acc, r, rules, P, fam_fail, cont, I_cont):
    if r.fam:
        rail_lines = 1 + (1 if r.fam["mid_rail"] and r.height is not None and r.height >= P["mid_rail_min_run_height_ft"] else 0)
        inp = r.I_posts + r.I_h + I_cont
        gate_ends = 2 * sum(g.per_run_qty for g in r.gates)
        top_ends = r.ends - (gate_ends if cont else 0)        # a continuous top rail does not terminate at gate posts
        cups = None if cont is None else (top_ends + (r.ends if rail_lines == 2 else 0)) * r.rep
        acc.add("M11", cups, "rail end cups = termination points per rail line (free ends + 2 per corner; + 2 per gate unless the top rail is continuous across openings)", inp)
        acc.add(r.fam["tension_bar_item"], r.tr["terminals"], "tension bars = one full-height bar at each terminal, corner and gate post (Section 32 31 13 2.3.C)", r.I_posts)
        band = _od_item(rules["by_post_od"]["tension_band_item"], r.t_od)
        if band:
            per_bar = _ceil(r.fam["fabric_height_in"] / P["tension_band_spacing_in"]) + P["tension_band_extra_per_bar"]
            acc.add(band, r.tr["terminals"] * per_bar,
                    f"tension bands = bars x (ceil(fabric height / {P['tension_band_spacing_in']} in max spacing) + {P['tension_band_extra_per_bar']})", r.I_posts)
        else:
            fam_fail.append(f"run {r.rid}: no tension band item for terminal OD {r.t_od}")
        acc.add(r.fam["fabric_tie_item"], r.tr["line_posts"] * _ceil(r.fam["fabric_height_in"] / P["fabric_tie_spacing_in"]),
                f"fabric ties to line posts = line posts x ceil(fabric height / {P['fabric_tie_spacing_in']} in)", r.I_posts)
    ties = lambda spacing: None if r.net is None else _ceil(r.net * 12 / spacing) * r.rep
    rail_lines = 1 + (1 if r.fam and r.fam["mid_rail"] and r.height is not None and r.height >= P["mid_rail_min_run_height_ft"] else 0)
    mt = ties(P["rail_tie_spacing_in"])
    acc.add("M26", None if mt is None else mt * rail_lines, f"fabric ties to rails every {P['rail_tie_spacing_in']} in of net fence, per rail line crossing the fabric (top, plus mid on tall Type A)", r.I_net + r.I_h)
    acc.add("M27", ties(P["hog_ring_spacing_in"]), f"tension-wire ties every {P['hog_ring_spacing_in']} in of net fence", r.I_net)


def _gate(acc, r, g, rules, P, problems):
    leaves = rules["gate_kinds"].get(str(g.kind)) if g.kind is not None else None
    leaf = g.I_w + g.I_h
    if g.kind is not None and leaves is None:
        problems.append({"code": "NO_ITEM_MAPPING", "path": f"/gates/{g.gid}", "message": f"gate kind {g.kind!r} has no rate-book items"})
    if leaves == 2:
        rods = g.qty * P["drop_rods_per_double_leaf_gate"]
        acc.add("M43", rods, "center drop rod = one per double-leaf gate (Addendum 01 1.4)", g.I_w + g.I_kind)
        acc.add("M44", rods * P["ground_sockets_per_drop_rod"], f"ground sockets = {P['ground_sockets_per_drop_rod']} per drop rod (Addendum 01 1.4)", g.I_w + g.I_kind)
    if g.h is not None and not _near(g.h * 12, P["gate_leaf_catalog_height_in"]):
        leaf = leaf.why_not(f"gate {g.gid} height {g.h:g} ft has no catalog leaf fabric ({P['gate_leaf_catalog_height_in']} in)")
    kind_inp = g.I_kind if leaves or g.kind is None else g.I_kind + Inp().why_not(f"gate {g.gid} kind {g.kind!r} has no leaf rule in the ruleset")
    q, wq = g.qty, None if g.w is None else g.w * g.qty
    acc.add("M35", wq, "header rail = clear width across each opening", g.I_w)
    acc.add("M21", wq, "gate leaf fabric LF = clear width x gates (catalog 84 in height)", leaf)
    acc.add("D09", q, "gates to hang = gate quantity", Inp(leaf.res))
    if g.th is None:
        acc.add("M22", None, "transom fabric LF", g.I_th)
    elif g.th > 0:
        t = g.I_w + g.I_th
        if not _near(g.th, P["transom_catalog_height_ft"]):
            t = t.why_not(f"gate {g.gid} transom {g.th:g} ft is not the catalog {P['transom_catalog_height_ft']:g} ft")
        acc.add("M22", wq, "transom fabric LF = clear width x gates where a transom exists", t)
    leaf_w = None if g.w is None or leaves is None else g.w / leaves
    acc.add("M28", None if leaf_w is None or g.h is None else q * leaves * (P["gate_pipe_verticals_per_leaf"] * g.h + P["gate_pipe_horizontals_per_leaf"] * leaf_w),
            "gate frame pipe = leaves x (2 verticals x height + 3 horizontals x leaf width)", leaf + kind_inp)
    for key, per, label in (("M29", "gate_elbows_per_leaf", "frame elbows"), ("M30", "gate_tees_per_leaf", "frame tees"),
                            ("M31", "gate_truss_rods_per_leaf", "leaf truss rods"), ("M32", "gate_hinges_per_leaf", "hinges"),
                            ("M34", "gate_holdbacks_per_leaf", "hold-backs / stops"), ("M36", "gate_tension_bars_per_leaf", "leaf tension bars")):
        acc.add(key, None if leaves is None else q * leaves * P[per], f"{label} = leaves x {P[per]} per leaf", kind_inp)
    acc.add("M33", q * P["gate_latches_per_gate"], f"latches = {P['gate_latches_per_gate']} per gate", Inp(leaf.res))
    acc.add("M37", None if leaves is None else q * leaves * P["gate_tension_bars_per_leaf"] * (_ceil(P["gate_leaf_catalog_height_in"] / P["gate_tension_band_spacing_in"]) + P["tension_band_extra_per_bar"]),
            "leaf tension bands = leaf bars x (ceil(leaf height / band spacing) + extra)", kind_inp)


def _concrete(acc, r, ge, P, res):
    inp, vol = Inp(res), {}
    for k in ("terminal", "line"):
        d = inp.use(f"/global_requirements/footing_{k}_diameter_in", ge.get(f"footing_{k}_diameter_in"), f"{k} footing diameter")
        dp = inp.use(f"/global_requirements/footing_{k}_depth_in", ge.get(f"footing_{k}_depth_in"), f"{k} footing depth")
        vol[k] = None if d is None or dp is None else math.pi * (d / 2) ** 2 * dp / P["cubic_inches_per_cubic_yard"]
    cy = None if None in vol.values() else r.tr["terminals"] * vol["terminal"] + r.tr["line_posts"] * vol["line"]
    inp = inp + r.I_posts
    acc.add("M40", cy, "concrete CU YD = terminals x terminal footing volume + line posts x line footing volume, pi x (d/2)^2 x depth", inp)
    acc.add("D05", cy, "concrete placed = M40 quantity (before overage)", inp)


def _foot_tag(foot):
    return f" [footing-scope.v1 schedule {foot['schedule_sha256'][:12]}]"


def _attach_footing(r, scope, foot, res):
    """footing-scope.v1 mode for one run: the facts its counts and footing sizes rest on become inputs of every post-derived quantity, so an unresolved
    or merely inferred one is reported (and a human approval is recorded) exactly like any other scope fact. Counts the schedule could not establish
    leave the run's post quantities unresolved; they are never written into a quantity as 0."""
    r.foot = foot
    fs = scope["footing_scope"]
    rcfg = next(c for c in fs["runs"] if c["run_id"] == r.rid)
    ri = fs["runs"].index(rcfg)
    cnt = Inp(res)
    for k, side in enumerate(rcfg["layout"]["sides"]):
        cnt.use(f"/footing_scope/runs/{ri}/layout/sides/{k}/length_lf", side["length_lf"], f"run {r.rid} side {side['side_id']} length")
        for m, x in enumerate(side.get("gates", [])):
            cnt.use(f"/footing_scope/runs/{ri}/layout/sides/{k}/gates/{m}/station_ft", x["station_ft"], f"gate {x['gate_id']} #{x['instance']} station")
    for why in r.tr.get("footing_unresolved", []):
        cnt.why_not(f"run {r.rid}: {why}")
    dims = Inp(res)
    used = [c for c in dict.fromkeys([rcfg.get("corner_class"), rcfg.get("end_class"), rcfg["line_class"], *(rcfg.get("gate_classes") or {}).values()]) if c]
    for cid in used:
        c = fs["classes"][cid]
        dims.use(f"/footing_scope/classes/{cid}/diameter_in", c["diameter_in"], f"post class {cid} footing diameter")
        dims.use(f"/footing_scope/classes/{cid}/depth_in", c["depth_in"], f"post class {cid} footing depth")
    r.I_posts = r.I_posts + cnt
    r.I_f = dims
    r.I_holes = r.I_posts + dims
    bad = sorted(c for c in used if fs["classes"][c]["fence_type"] != (r.fam or {}).get("family", fs["classes"][c]["fence_type"]))
    if bad:        # a Type B run must not be given Type A footing classes (or the reverse): that is the defect this contract exists to remove
        return [{"code": "NO_ITEM_MAPPING", "path": f"/footing_scope/runs/{ri}",
                 "message": f"run {r.rid} is catalog fence family {r.fam['family']} but its footing classes {bad} are declared for the other fence type"}]
    return []


def _concrete_by_class(acc, r, foot, P):
    """M40 / D05 for one run = sum over its post classes of count x pi x (d/2)^2 x depth (CU YD). Per-class volumes come from the schedule, so the
    quantity reconciles to the class table; an unresolved class size or count makes the run's concrete unresolved, never 0."""
    recs = [x for x in foot["records"] if x["run_id"] == r.rid]
    cy = None if any(x["concrete_cy"] is None for x in recs) else round(sum(x["concrete_cy"] for x in recs), 6)
    inp = r.I_holes
    method = "concrete CU YD = sum over post classes of count x pi x (d/2)^2 x depth, each class at its own footing size (footing-scope.v1)" + _foot_tag(foot)
    acc.add("M40", cy, method, inp)
    acc.add("D05", cy, "concrete placed = M40 quantity (before overage)" + _foot_tag(foot), inp)


def _accessory(acc, k, a, P, res, problems):
    base = f"/accessories/{k}"
    if a.get("kind") == "fence_guard":
        inp = Inp(res)
        lf = inp.use(f"{base}/length_lf", a.get("length_lf"), f"fence guard {a.get('accessory_id')} length")
        acc.add("M42", lf, "fence guard LF as scheduled, on the Type B top rail (Special Conditions item 16)", inp)
        return
    if a.get("kind") != "windscreen":
        problems.append({"code": "NO_ITEM_MAPPING", "path": base,
                         "message": f"accessory {a.get('accessory_id')!r} of kind {a.get('kind')!r} has no item in the rate-book vocabulary and would not be priced"})
        return
    inp = Inp(res)
    lf = inp.use(f"{base}/length_lf", a.get("length_lf"), f"accessory {a['accessory_id']} length")
    h = inp.use(f"{base}/height_ft", a.get("height_ft"), f"accessory {a['accessory_id']} height")
    if h is not None and not _near(h, P["windscreen_catalog_height_ft"]):
        inp = inp.why_not(f"windscreen {a['accessory_id']} height {h:g} ft is not the catalog {P['windscreen_catalog_height_ft']:g} ft")
    acc.add("M38", lf, "windscreen LF as scheduled", inp)
    acc.add("D10", lf, "windscreen to install = M38 quantity", inp)
    acc.add("M39", None if lf is None else 2 * _ceil(lf * 12 / P["grommet_spacing_in"]),
            f"cable ties = one per grommet, top and bottom, every {P['grommet_spacing_in']} in", inp)


def _item(key, unit, scope_ref, qty, method, inp, status):
    row = {"item_id": key} if key in vocab.MATERIALS or key in vocab.SERVICES else {"driver_key": key}
    row.update({"scope_ref": scope_ref, "quantity": qty, "uom": unit, "source_evidence_refs": list(inp.refs.values()),
                "calculation_method": (method or "n/a")[:400], "status": status, "approved_resolutions": inp.resolutions()})
    if status == "unresolved":
        row["unresolved_reasons"] = [x[:300] for x in dict.fromkeys(inp.reasons)] or ["an input is missing"]
    return row


def blockers(payload, *, require_ruleset_approval=True):
    """Why this payload may not be priced. Pure function of the payload; the pricing engine re-checks independently."""
    out = []
    if require_ruleset_approval and not payload["revision"]["ruleset"]["approved"]:
        out.append({"code": "QUANTITY_RULESET_NOT_APPROVED", "ref": payload["revision"]["ruleset"]["sha256"],
                    "message": "the quantity ruleset has not been approved by a named estimator"})
    for it in payload["items"]:
        key = it.get("item_id") or it.get("driver_key")
        if it["status"] == "unresolved":
            out.append({"code": "QUANTITY_UNRESOLVED", "ref": key, "message": "; ".join(it.get("unresolved_reasons", []))})
        elif it["status"] == "provisional":
            out.append({"code": "QUANTITY_PROVISIONAL", "ref": key, "message": "depends on an inferred fact no human has approved"})
    return out

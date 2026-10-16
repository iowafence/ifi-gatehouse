"""Addendum intake through the Scope Gate. Fail closed at every step.

upload -> own revision + SHA-256 -> parse (injected parser; the live AMD/Evolus parser is refused while the HOLD file exists) ->
the engine verifies each cited excerpt is on the cited page of THAT PDF -> a dry run on a copy shows Before/After -> a named human
accepts -> scope version bump, labor/release invalidated (old snapshots preserved in history). Nothing here changes the scope until
`accept_addendum_intake`, and the parser never decides anything: it only proposes {path, value, page, excerpt}."""
import copy
import hashlib
import os
import pathlib
import re

from intake import addendum as pdfin
from intake import units
from . import workflow as wf

HOLD_FILE = pathlib.Path(__file__).resolve().parent.parent / "amd_experiment" / "LIVE_CALLS_DISABLED"
PROPOSED, APPLIED = "PROPOSED", "APPLIED"
HELD = {"HELD_INHERITED_UNRESOLVED", "HELD_UNVERIFIED_EVIDENCE", "HELD_NO_CHANGE", "HELD_CONTRADICTORY", "HELD_PARSE_UNAVAILABLE", "HELD_REFUSED", "HELD_NO_FACTS"}
MAX_FACTS = 25


class ParseUnavailable(Exception):
    def __init__(self, message, meta=None):
        super().__init__(message)
        self.meta = meta or {}


def live_parser(pages, context):
    """The real AMD parse (Qwen3.8-27B). Fail closed: refused unless the owner's per-document authorization allows this SHA-256."""
    from . import addendum_live
    return addendum_live.live_parser(pages, context)


live_parser.enforce_slots = True


def _slots(scope):
    """The open facts an addendum may answer: unresolved gate opening widths and unresolved footing/post facts. Never a price or quantity."""
    out = []
    for i, g in enumerate(scope.get("gates") or [] if isinstance(scope, dict) else []):
        f = g.get("clear_width_ft") if isinstance(g, dict) else None
        if isinstance(f, dict) and f.get("status") == "unresolved":
            out.append({"path": f"/gates/{i}/clear_width_ft", "label": f"clear opening width of Gate {g.get('gate_id')}, face of post to face of post", "unit": "ft"})
    classes = ((scope.get("footing_scope") or {}).get("classes") or {}) if isinstance(scope, dict) else {}
    for cname, c in sorted(classes.items()):
        for fld, label, unit in (("post_od_in", "gate post outside diameter", "in"), ("diameter_in", "footing diameter", "in"), ("depth_in", "footing depth", "in")):
            f = c.get(fld) if isinstance(c, dict) else None
            if isinstance(f, dict) and f.get("status") == "unresolved":
                out.append({"path": f"/footing_scope/classes/{cname}/{fld}", "label": f"{label} for {cname}", "unit": unit})
    return out


REF_FIELDS = ("post_od_in", "diameter_in", "depth_in")
_SAME = re.compile(r"\b(same as|identical to|matches)\b")


def _resolve_ref(scope, f):
    """An explicit "same as Gate G1" reference. -> ("ok", update_fact, info) | ("blocked", info) | ("reject", reason).
    The number is never taken from the model or the addendum text: it is copied from the source gate's document-confirmed record."""
    parts = f["path"].split("/")
    classes = ((scope.get("footing_scope") or {}).get("classes") or {}) if isinstance(scope, dict) else {}
    if not (len(parts) == 5 and parts[1:3] == ["footing_scope", "classes"] and parts[4] in REF_FIELDS and parts[3] in classes):
        return "reject", "a same-as reference applies only to a gate post or footing field"
    tgt, src, field = parts[3], f.get("same_as"), parts[4]
    if "value" in f:
        return "reject", "a reference must not carry a value; the engine copies it from the source gate"
    if not (isinstance(src, str) and src in classes and src != tgt):
        return "reject", "the referenced gate is not a known gate class other than this one"
    lt, ls = re.fullmatch(r"GATE_(G\d+)", tgt), re.fullmatch(r"GATE_(G\d+)", src)
    if not (lt and ls):
        return "reject", "references are between numbered gates only"
    t = pdfin.norm(f["excerpt"])
    a, b = lt.group(1).lower(), ls.group(1).lower()
    m = _SAME.search(t)
    gates = set(re.findall(r"\bg\d+\b", t))
    if not m or gates != {a, b}:
        return "reject", f"the cited text must say {lt.group(1)} is the same as {ls.group(1)} and mention no other gate"
    ia, ib = [x.start() for x in re.finditer(rf"\b{a}\b", t)], [x.start() for x in re.finditer(rf"\b{b}\b", t)]
    if not (min(ia) < m.start() < min(i for i in ib if i > m.start()) if any(i > m.start() for i in ib) else False):
        return "reject", f"the cited text must read {lt.group(1)} 'same as' {ls.group(1)}, in that direction"
    if ("post" if field == "post_od_in" else "footing") not in t:
        return "reject", "the cited text does not name this field's subject (post or footing)"
    sp = f"/footing_scope/classes/{src}/{field}"
    sf = classes[src].get(field)
    ok = isinstance(sf, dict) and sf.get("status") == "confirmed" and isinstance(sf.get("value"), (int, float)) and not isinstance(sf.get("value"), bool)
    # A reference may carry labeled dimensions (e.g. "2.875 in OD post") and citations such as "Detail 3/F501" (not a dimension). Every
    # dimension must be tied to one field; one tied to THIS field must equal the source gate's record, or the document contradicts itself.
    stated, _, why = units.read_field(field, f["excerpt"])
    if why and why != "no dimension in the cited text is labeled as this field":
        return "reject", "the cited text has a dimension that cannot be tied to exactly one field: " + why
    if stated is not None and ok and abs(stated - float(sf["value"])) > 1e-9:
        return "reject", f"the cited text states {stated:g} for this field but the Gate {ls.group(1)} record says {sf['value']:g}; the document contradicts itself"
    info = {"path": f["path"], "inherited_from": sp, "gate": ls.group(1), "source_status": (sf or {}).get("status") if isinstance(sf, dict) else "missing",
            "source_value": sf.get("value") if ok else None, "source_evidence": copy.deepcopy(sf.get("evidence", [])) if ok else []}
    if not ok:
        info["reason"] = f"Gate {ls.group(1)} field {sp} is not document-confirmed (status: {info['source_status']}), so {tgt} inherits it and stays blocked"
        return "blocked", info
    return "ok", {"value": sf["value"], "unit": sf.get("unit", "in"), "source": info}, info


def _facts_problem(facts):
    if not isinstance(facts, list) or len(facts) > MAX_FACTS:
        return "the parser must return a list of at most %d facts" % MAX_FACTS
    for f in facts:
        if not (isinstance(f, dict) and isinstance(f.get("path"), str) and f["path"].startswith("/") and ("value" in f or "same_as" in f)
                and isinstance(f.get("page"), int) and isinstance(f.get("excerpt"), str)):
            return "every parsed fact needs path, value, page and excerpt"
    return None


def _records(state):
    return state.setdefault("addenda", {})


def _bound(state):
    return {"scope_version": state["scope"]["scope_version"], "proposal_digest": state.get("proposal_digest"), "status": state["status"]}


def _classify(msg):
    m = msg.lower()
    if "already applied" in m:
        return APPLIED
    if "changes nothing" in m:
        return "HELD_NO_CHANGE"
    if "contradict" in m:
        return "HELD_CONTRADICTORY"
    return "HELD_REFUSED"


def _dry_run(state, rec):
    """Before/After from the engine itself, computed on a copy. Returns (status, changes_or_message)."""
    work = copy.deepcopy(state)
    try:
        wf.revise_scope(work, rec["updates"], source=rec["source"], by=rec["ingested_by"], note="dry run for the Scope Gate Before/After")
    except wf.GateError as e:
        return _classify(str(e)), str(e)
    cites = {u["path"]: u["fact"]["evidence"][0] for u in rec["updates"]}
    return PROPOSED, [{**c, "inherited_from": rec.get("inherited", {}).get(c["path"]),
                          "supersedes_established_fact": c["before_status"] in ("confirmed", "inferred") and c["before"] is not None,
                          "cited_page": cites[c["path"]]["page"], "cited_excerpt": cites[c["path"]]["excerpt"]} for c in work["last_change"]["changes"]]


def _log(state, event, **kw):
    state["audit"].append({"event_id": len(state["audit"]) + 1, "event": event, "utc": wf._utc(), "actor": kw.pop("actor", None), **kw})


def begin_addendum(state, raw, filename, *, by):
    """Phase 1 (fast, under the project lock). Validates and archives the upload. Returns (record, pdf). `pdf` is None when nothing
    needs parsing (already applied, held, or parsed earlier and only rebound); otherwise the record is PROCESSING and the caller
    must run the parser OUTSIDE the lock and then call finish_addendum. Raises AddendumRefused for an unusable upload."""
    if not wf._named(by):
        raise pdfin.AddendumRefused("ACTOR_REQUIRED", "a named uploader is required")
    try:
        pdf = pdfin.read_pdf(raw, filename)
    except pdfin.AddendumRefused as e:
        _log(state, "addendum_upload_refused", actor=by, code=e.code, size=len(raw) if isinstance(raw, (bytes, bytearray)) else None,
             filename=pdfin.safe_name(filename), sha256=hashlib.sha256(bytes(raw)).hexdigest() if isinstance(raw, (bytes, bytearray)) and len(raw) <= 2 * pdfin.MAX_PDF_BYTES else None)
        raise
    recs = _records(state)
    iid = pdf["sha256"][:16]
    rec = recs.get(iid)
    if rec and (rec["status"] in (APPLIED, "PROCESSING") or (rec["status"] in HELD and rec["status"] != "HELD_PARSE_UNAVAILABLE")):
        return rec, None                                        # idempotent: in force, in flight or held; nothing new happens
    before_key = (rec["status"], rec["bound"]) if rec else None
    if rec is None:
        rev = state["doc_revision"] + 1
        rec = {"intake_id": iid, "filename": pdf["filename"], "size": pdf["size"], "page_count": len(pdf["pages"]),
               "source": {"doc_id": f"addendum_{pdf['sha256'][:12]}", "doc_revision": rev, "sha256": pdf["sha256"]},
               "ingested_by": by, "received_utc": wf._utc(), "parse": None, "updates": [], "rejected": [], "before_after": None,
               "bound": None, "status": None, "message": None, "blocked": [], "inherited": {}}
        _log(state, "addendum_received", actor=by, intake_id=iid, sha256=pdf["sha256"], size=pdf["size"], doc_revision=rev, filename=pdf["filename"])
    recs[iid] = rec
    if rec["updates"]:                                          # parsed and verified earlier: rebind to the current state, no second parse
        rec["source"]["doc_revision"] = state["doc_revision"] + 1
        for u in rec["updates"]:
            for e in u["fact"]["evidence"]:
                e["doc_revision"] = rec["source"]["doc_revision"]
        _finish_dry_run(state, rec, by, before_key)
        return rec, None
    rec["status"], rec["message"] = "PROCESSING", None
    pdf["slots"] = _slots(state["scope"])
    _log(state, "addendum_processing", actor=by, intake_id=iid)
    return rec, pdf


def run_parser(parser, pdf, rec):
    """Phase 2 (slow, NO state, run outside the lock). Returns an outcome dict; never raises."""
    try:
        parsed = parser(copy.deepcopy(pdf["pages"]), {"doc_id": rec["source"]["doc_id"], "doc_revision": rec["source"]["doc_revision"],
                                                      "sha256": rec["source"]["sha256"], "slots": pdf.get("slots") or []})
    except ParseUnavailable as e:
        return {"unavailable": str(e), "meta": dict(getattr(e, "meta", None) or {})}
    except Exception as e:  # noqa: BLE001 - a crashing parser must hold the intake, never crash the server or progress it
        return {"unavailable": f"the parser failed: {type(e).__name__}", "meta": {}}
    facts, meta = (parsed if isinstance(parsed, tuple) else (parsed, {}))
    return {"facts": facts, "meta": dict(meta or {}), "parser": getattr(parser, "__name__", "parser"), "enforce_slots": getattr(parser, "enforce_slots", False)}


def _finish_dry_run(state, rec, by, before_key):
    status, res = _dry_run(state, rec)
    rec["status"], rec["message"] = status, (None if status == PROPOSED else res)
    rec["before_after"] = res if status == PROPOSED else None
    rec["bound"] = _bound(state) if status == PROPOSED else None
    if status == APPLIED:
        rec["status"] = "HELD_REFUSED"
    if before_key != (rec["status"], rec["bound"]):              # an identical re-upload adds no event
        _log(state, "addendum_proposed" if rec["status"] == PROPOSED else "addendum_held", actor=by, intake_id=rec["intake_id"], status=rec["status"],
             message=rec["message"], before_after=rec["before_after"])


def finish_addendum(state, iid, pdf, outcome, *, by):
    """Phase 3 (fast, under the lock): verify the cited text against THIS PDF, dry-run Before/After, bind to the current state."""
    rec = state["addenda"][iid]
    meta = outcome.get("meta") or {}
    if "unavailable" in outcome:
        rec.update(status="HELD_PARSE_UNAVAILABLE", message=outcome["unavailable"],
                   parse={"parser": meta.get("parser", "NOT_REPORTED"), "model": meta.get("model", "NOT_REPORTED"), "result": "UNAVAILABLE",
                          "elapsed_ms": meta.get("elapsed_ms", "NOT_REPORTED"), "usage": meta.get("usage", "NOT_REPORTED")})
        _log(state, "addendum_held", actor=by, intake_id=iid, status=rec["status"], message=rec["message"], parse=rec["parse"])
        return rec
    facts = copy.deepcopy(outcome["facts"])        # never mutate what the parser handed back
    rec["parse"] = {"parser": outcome.get("parser", "NOT_REPORTED"), "model": meta.get("model", "NOT_REPORTED"), "result": "RETURNED",
                    "elapsed_ms": meta.get("elapsed_ms", "NOT_REPORTED"), "usage": meta.get("usage", "NOT_REPORTED")}
    bad = _facts_problem(facts)
    if bad:
        rec.update(status="HELD_UNVERIFIED_EVIDENCE", message=bad)
    elif not facts:
        rec.update(status="HELD_NO_FACTS", message="the parser found no facts to propose; nothing to accept")
    else:
        rejected = [{"path": f["path"], "page": f["page"], "reason": "the cited text is not on the cited page of the uploaded PDF"}
                    for f in facts if not pdfin.excerpt_on_page(pdf["pages"], f["page"], f["excerpt"])]
        on_page = {id(f) for f in facts if pdfin.excerpt_on_page(pdf["pages"], f["page"], f["excerpt"])}
        blocked, inherited = [], {}
        for f in facts:                                  # tie each number to its own field and normalize units deterministically
            if id(f) not in on_page:
                continue
            if "same_as" in f:                           # explicit "same as Gate G1": copy from the source gate's confirmed record, or stay blocked
                res = _resolve_ref(state["scope"], f)
                if res[0] == "reject":
                    rejected.append({"path": f["path"], "page": f["page"], "reason": res[1]})
                elif res[0] == "blocked":
                    blocked.append(res[1])
                    f["_blocked"] = True
                else:
                    f["value"], f["_ref"] = res[1]["value"], res[1]
                    inherited[f["path"]] = res[2]
                continue
            val, matched, why = units.read_field(f["path"].rsplit("/", 1)[-1], f["excerpt"])
            mv = f["value"]
            if why is None and (isinstance(mv, bool) or not isinstance(mv, (int, float)) or abs(float(mv) - val) > 1e-9):
                why = f"the proposed number {mv!r} does not equal the {val:g} the cited text gives for this field"
            if why:
                rejected.append({"path": f["path"], "page": f["page"], "reason": why})
            else:
                f["value"], f["_matched"] = val, matched
        slot_paths = {x["path"] for x in pdf.get("slots") or []}
        if outcome.get("enforce_slots"):
            rejected += [{"path": f["path"], "page": f["page"], "reason": "the path is not an open fact slot"} for f in facts if f["path"] not in slot_paths]
        paths = {}
        for f in facts:
            paths.setdefault(f["path"], []).append(f["value"] if "value" in f else ("ref", f.get("same_as")))
        clash = sorted(p for p, v in paths.items() if len({repr(x) for x in v}) > 1)
        if rejected:
            rec.update(status="HELD_UNVERIFIED_EVIDENCE", rejected=rejected, message=f"{len(rejected)} cited excerpt(s) are not on the cited page; the whole parse is held")
        elif clash:
            rec.update(status="HELD_CONTRADICTORY", message="the document gives different values for the same fact: " + ", ".join(clash))
        else:
            seen, ups = set(), []
            for f in facts:
                if f["path"] in seen or f.get("_blocked"):
                    continue
                seen.add(f["path"])
                if "_ref" in f:
                    inf = f["_ref"]["source"]
                    ups.append({"path": f["path"], "fact": {"value": f["value"], "status": "confirmed", "unit": f["_ref"]["unit"], "evidence": [
                        {"doc_id": rec["source"]["doc_id"], "doc_revision": rec["source"]["doc_revision"], "page": f["page"], "excerpt": f["excerpt"].strip(),
                         "sheet_label": f"{rec['filename']} page {f['page']}", "source_type": "addendum_pdf",
                         "note": f"inherited from Gate {inf['gate']} by explicit reference in the addendum; value copied from the document-confirmed record at {inf['inherited_from']}",
                         "inherited_from": {"path": inf["inherited_from"], "value": inf["source_value"], "status": inf["source_status"]}},
                        *copy.deepcopy(inf["source_evidence"])]}})
                    continue
                ups.append({"path": f["path"], "fact": {"value": f["value"], "status": "confirmed", **({"unit": f["unit"]} if f.get("unit") else {}),
                            "evidence": [{"doc_id": rec["source"]["doc_id"], "doc_revision": rec["source"]["doc_revision"], "page": f["page"],
                                          "excerpt": f["excerpt"].strip(), "note": f"value read deterministically from the cited text ({f['_matched']}) and tied to this field", "sheet_label": f"{rec['filename']} page {f['page']}", "source_type": "addendum_pdf"}]}})
            rec["updates"] = ups
            rec["inherited"], rec["blocked"] = inherited, blocked
            if not ups and blocked:
                rec.update(status="HELD_INHERITED_UNRESOLVED", message="nothing can be inherited yet: " + "; ".join(b["reason"] for b in blocked))
    if rec["updates"]:
        _finish_dry_run(state, rec, by, None)
    else:
        _log(state, "addendum_held", actor=by, intake_id=iid, status=rec["status"], message=rec["message"], parse=rec["parse"])
    return rec


def submit_addendum(state, raw, filename, *, parser, by):
    """Synchronous composition of the three phases (tests, CLI). The HTTP route runs them separately so the parse is off the lock."""
    rec, pdf = begin_addendum(state, raw, filename, by=by)
    if pdf is None:
        return rec
    return finish_addendum(state, rec["intake_id"], pdf, run_parser(parser, pdf, rec), by=by)


@wf._atomic
def accept_addendum_intake(state, *, intake_id, by, note, scope_version, proposal_digest):
    """A named human accepts the Before/After. Only now does the scope change (version bump; labor and release invalidated;
    previous snapshots stay in history). Refused if anything changed since the proposal was bound (stale)."""
    wf._require_actor(by, note)
    rec = state.get("addenda", {}).get(intake_id)
    if not rec:
        raise wf.GateError("no such addendum intake")
    if rec["status"] != PROPOSED:
        raise wf.GateError(f"this addendum is {rec['status']}; only a PROPOSED addendum can be accepted")
    cur = _bound(state)
    if rec["bound"] != cur or scope_version != cur["scope_version"] or proposal_digest != cur["proposal_digest"]:
        raise wf.GateError("STALE_PROPOSAL: the project changed (scope version, proposal digest or release status) since this Before/After was shown; re-upload to rebind it")
    wf.revise_scope(state, rec["updates"], source=rec["source"], by=rec["ingested_by"], note=f"ingested from {rec['filename']}; accepted by {by}")
    wf.accept_addendum(state, by=by, note=note, scope_version=state["scope"]["scope_version"])
    rec = state["addenda"][intake_id]          # the inner atomic calls replaced the state's contents; re-fetch
    rec["status"], rec["applied_scope_version"], rec["accepted_by"] = APPLIED, state["scope"]["scope_version"], by
    wf._log(state, "addendum_intake_accepted", actor=by, intake_id=intake_id, note=note, sha256=rec["source"]["sha256"])
    return state

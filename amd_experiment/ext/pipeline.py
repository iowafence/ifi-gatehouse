"""Evaluation pipeline with four separate output stages and hard rules about what may become an accepted fact.

  Stage 1  raw model response            exactly what the provider returned (key hash scrubbed), never edited
  Stage 2  parsed candidate facts        STRICT JSON only (no fences, no trailing text, no duplicate keys, no NaN) + per-fact structure checks
  Stage 3  evidence-verified facts       quote found VERBATIM in the PDF text layer, value present in the quote, inside the requested region.
                                         Positions come from the PDF text layer. Model-supplied boxes are kept only as an unverified claim.
  Stage 4  informational constraints     typed constraints derived from ACCEPTED facts only (e.g. a maximum post spacing). Not quantities, not prices.

Salvaged values from malformed output exist only as `SalvagedFact` objects in a diagnostic file; `accept()` refuses them by type, so they can never reach
stage 3 or 4. JSON mode (response_format json_object) improves syntax odds; it does not make a fact true, so nothing is exempt from stages 2-3.
Nothing in this module prices, approves a quantity, or touches the Gatehouse application.
"""
import hashlib
import json
import pathlib
import re
import time

from . import normalize, validator
from .render import sha256_file

HARNESS_DIR = pathlib.Path(__file__).resolve().parent.parent
FORBIDDEN_CONSTRAINT_KEYS = {"quantity", "count", "length_lf", "price", "cost", "total", "estimate", "approved", "release"}
SECRET_SHAPES = re.compile(r"(rc-[0-9a-f]{32,}|sk-[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._-]{20,})")


# ----------------------------------------------------------------------------- request construction
def build_request(model, messages, max_tokens, temperature=0.0, json_mode=False, extra=None):
    """Documented parameters only. `extra` is merged but may not override documented fields, and is recorded verbatim in the run record."""
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    for k, v in (extra or {}).items():
        if k in body:
            raise ValueError(f"extra may not override documented field {k!r}")
        body[k] = v
    return body


def assert_live_allowed(base_url, authorized):
    """No network call unless explicitly authorized for this invocation AND the harness is not under a live-call hold (loopback test servers exempt)."""
    host = re.sub(r"^https?://", "", base_url).split("/")[0].split(":")[0]
    if host in ("127.0.0.1", "localhost", "::1"):
        return
    if not authorized:
        raise PermissionError("live AMD call refused: pass the explicit authorization flag for this single invocation")
    if (HARNESS_DIR / "LIVE_CALLS_DISABLED").exists():
        raise PermissionError("live AMD calls are on hold: LIVE_CALLS_DISABLED exists in the harness directory")


# ----------------------------------------------------------------------------- stage 2
class StrictJSONError(ValueError):
    pass


def _no_dupes(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise StrictJSONError("duplicate object key")
    return dict(pairs)


def _no_const(c):
    raise StrictJSONError(f"non-standard constant {c}")


def strict_parse(content):
    """Returns (object|None, category, detail). Strict means: the whole string is one JSON document."""
    if not isinstance(content, str):
        return None, "not_a_string", type(content).__name__
    s = content
    if s.strip().startswith("```"):
        return None, "markdown_fence", "response wrapped in a code fence; strict parsing refuses it"
    try:
        obj = json.loads(s, object_pairs_hook=_no_dupes, parse_constant=_no_const)
    except StrictJSONError as e:
        return None, "strict_failed", str(e)
    except ValueError as e:
        return None, "strict_failed", str(e)
    if not isinstance(obj, dict):
        return None, "wrong_top_level_type", type(obj).__name__
    return obj, "strict_ok", None


def stage2_candidates(obj):
    """Per-fact structural validation. A fact with any structural problem is rejected (with reasons); it is never repaired."""
    top = []
    if not isinstance(obj.get("document"), dict):
        top.append("document missing or not an object")
    facts = obj.get("facts")
    if not isinstance(facts, list):
        return {"candidates": [], "rejected": [], "top_level_problems": top + ["facts missing or not a list"]}
    cands, rejected = [], []
    for i, f in enumerate(facts):
        probs = validator.validate_structure({"document": {"title": None, "sheet_number": None, "revision": None, "date": None}, "facts": [f], "conflicts_or_ambiguities": []}) if isinstance(f, dict) else [{"path": "/facts/0", "problem": "not an object"}]
        probs = [p for p in probs if p["path"].startswith("/facts/0")]
        bb = f.get("bbox_norm") if isinstance(f, dict) else None
        if isinstance(f, dict) and "bbox_norm" in f:
            probs = [p for p in probs if not p["path"].endswith("/bbox_norm")]      # boxes are never authoritative; their validity does not decide acceptance
        (rejected if probs else cands).append({"index": i, "problems": probs} if probs else {**{k: v for k, v in f.items() if k != "bbox_norm"}, "model_claimed_bbox_unverified": bb})
    return {"candidates": cands, "rejected": rejected, "top_level_problems": top, "document": obj.get("document")}


# ----------------------------------------------------------------------------- salvage quarantine
class SalvagedFact(dict):
    """A value recovered from NON-strict output. Diagnostic only. accept() refuses this type."""


def salvage_diagnostic(content, page):
    """Best-effort recovery of quotes from malformed output, for human diagnosis. Everything returned is a SalvagedFact."""
    out = []
    for m in re.finditer(r'"(evidence_text|evidence)":\s*"((?:[^"\\]|\\.)*)"', content or ""):
        try:
            q = json.loads('"' + m.group(2) + '"')
        except ValueError:
            continue
        mt = validator.text_match(q, page.text)
        out.append(SalvagedFact(field_name=m.group(1), quote=q, text_match=mt or "UNVERIFIED", origin="salvage"))
    return {"DIAGNOSTIC_ONLY": True, "rule": "never used for accepted facts, quantities or pricing", "salvaged": out}


# ----------------------------------------------------------------------------- stage 3
class AcceptedFacts(list):
    """The only collection stage 4 reads. Facts enter solely through accept()."""

    def accept(self, fact):
        if isinstance(fact, SalvagedFact):
            raise TypeError("salvaged values can never become accepted facts")
        if fact.get("origin") != "strict_parse" or fact.get("verification") != "VERIFIED_EXACT" or fact.get("position_source") != "pdf_text_layer":
            raise ValueError("a fact is accepted only from strict parsing, with verbatim PDF evidence and PDF-derived positions")
        self.append(fact)


def _inside(r, region, tol=0.002):
    return region is None or (r[0] >= region[0] - tol and r[1] >= region[1] - tol and r[2] <= region[2] + tol and r[3] <= region[3] + tol)


def stage3_verify(candidates, page, source, region=None):
    accepted, unverified, not_observed, outside = AcceptedFacts(), [], [], []
    for c in candidates:
        base = {k: c.get(k) for k in ("fact_id", "category", "key", "value", "unit", "evidence_text", "dimension_basis", "confidence")}
        claimed = c.get("status")
        ev = validator.verify_evidence({"evidence_text": c.get("evidence_text")}, page)           # no bbox passed in: model boxes play no part
        vc = validator.check_values(c, page.text) if ev["text"] == "VERIFIED_EXACT" else {"value_in_evidence": None, "reason": "evidence not verified exactly"}
        rec = {**base, "claimed_status": claimed, "evidence_check": ev["text"], "value_check": vc, "model_claimed_bbox_unverified": c.get("model_claimed_bbox_unverified")}
        if claimed != "observed":
            not_observed.append(rec); continue
        if ev["text"] != "VERIFIED_EXACT" or vc["value_in_evidence"] is False:
            unverified.append(rec); continue
        rects = ev["matched_rects"]
        if not rects:
            unverified.append({**rec, "why": "no PDF text-layer position could be derived for the quote"}); continue
        if not any(_inside(r, region) for r in rects):
            outside.append({**rec, "pdf_text_locations_norm_page": rects}); continue
        accepted.accept({**base, **source, "origin": "strict_parse", "verification": "VERIFIED_EXACT", "position_source": "pdf_text_layer",
                         "pdf_text_locations_norm_page": [r for r in rects if _inside(r, region)] or rects, "value_check": vc, "informational_only": True})
    return {"accepted_facts": list(accepted), "unverified": unverified, "not_observed": not_observed, "outside_region": outside, "_accepted_obj": accepted}


# ----------------------------------------------------------------------------- stage 4
def stage4_constraints(accepted):
    if not isinstance(accepted, AcceptedFacts):
        raise TypeError("constraints are derived only from the AcceptedFacts collection")
    out = []
    for f in accepted:
        for c in normalize.normalize_spacing(f["evidence_text"]):
            rec = {"fact_id": f["fact_id"], **c, "source_sha256": f["source_sha256"], "page_number": f["page_number"], "informational_only": True}
            assert not (FORBIDDEN_CONSTRAINT_KEYS & set(rec)), "constraint carries a quantity/price/approval field"
            out.append(rec)
    return out


# ----------------------------------------------------------------------------- documents, runs, equivalence
def harness_version():
    h = hashlib.sha256()
    for p in sorted((HARNESS_DIR / "ext").glob("*.py")):
        h.update(p.name.encode()); h.update(p.read_bytes())
    return h.hexdigest()[:16]


def load_document(manifest, doc_id):
    docs = {d["doc_id"]: d for d in manifest["documents"]}
    if doc_id not in docs:
        raise KeyError(f"unknown document {doc_id!r}")
    d = docs[doc_id]
    if d.get("status") != "available":
        raise PermissionError(f"document {doc_id!r} is {d.get('status')!r}: it is not approved for testing yet")
    p = pathlib.Path(d["path"]).expanduser()
    if sha256_file(p) != d["sha256"]:
        raise ValueError(f"HASH MISMATCH for {doc_id}: the file differs from the manifest entry; refusing to mix revisions")
    return d


def run_dir(root, doc, run_id):
    return pathlib.Path(root) / doc["doc_id"] / doc["sha256"][:12] / run_id


def write_once(directory, name, obj):
    """Exclusive create: a stage file can never be overwritten, and frozen experiment directories are refused."""
    directory = pathlib.Path(directory)
    if any(part in ("exp1", "exp2") for part in directory.parts) and "runs" in directory.parts:
        raise PermissionError(f"{directory} is a frozen experiment directory")
    directory.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)
    if SECRET_SHAPES.search(text):
        raise ValueError(f"refusing to write {name}: credential-shaped content")
    with open(directory / name, "x") as fh:
        fh.write(text)


def equivalence(a, b):
    """Compare two run records. Returns a label that must travel with any side-by-side table."""
    diffs = []
    same_doc = a["source"]["source_sha256"] == b["source"]["source_sha256"] and a["source"]["doc_id"] == b["source"]["doc_id"]
    if not same_doc:
        return {"same_document": False, "differences": ["source document / hash"],
                "label": "DIFFERENT DOCUMENTS: layouts and sheet sizes differ, so this is NOT a model-performance benchmark. Do not rank models."}
    for k in ("page_number", "region_norm_page", "dpi", "image_sha256", "prompt_sha256", "system_sha256"):
        if a["input"].get(k) != b["input"].get(k):
            diffs.append(k)
    for k in sorted(set(a["request"]) | set(b["request"])):
        if k in ("model", "extra") and k == "model":
            continue
        if a["request"].get(k) != b["request"].get(k):
            diffs.append(f"request.{k}")
    if diffs:
        return {"same_document": True, "differences": diffs, "label": "NON-EQUIVALENT: " + ", ".join(diffs) + ". Do not declare a winner."}
    return {"same_document": True, "differences": [], "label": "Equivalent inputs and parameters (a single sample; still not a benchmark)."}


def make_run_record(*, run_id, doc, page_number, dpi, region, render_meta, prompt, system, request_body, telemetry=None, source_note=None):
    req = {k: v for k, v in request_body.items() if k != "messages"}
    return {"run_id": run_id, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "harness_version": harness_version(), "source_note": source_note,
            "source": {"doc_id": doc["doc_id"], "source_document": pathlib.Path(doc["path"]).name, "source_sha256": doc["sha256"], "declared_sheet_size": doc.get("declared_sheet_size")},
            "input": {"page_number": page_number, "dpi": dpi, "region_norm_page": region, "image_sha256": render_meta["image_sha256"], "image_px": render_meta["image_px"],
                      "renderer": render_meta["renderer"], "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(), "system_sha256": hashlib.sha256(system.encode()).hexdigest()},
            "request": req, "telemetry": telemetry}


def process_content(content, page, source, region):
    """Stages 2-4 for one raw content string. Returns the dict of stage outputs (plus diagnostics) without writing anything."""
    obj, cat, detail = strict_parse(content)
    out = {"strict_parse": {"category": cat, "detail": detail}}
    if obj is None:
        out["stage2"] = {"candidates": [], "rejected": [], "top_level_problems": [f"strict parse failed: {cat}"]}
        out["stage3"] = {"accepted_facts": [], "unverified": [], "not_observed": [], "outside_region": []}
        out["stage4"] = []
        out["diagnostic_salvage"] = salvage_diagnostic(content, page) if isinstance(content, str) else None
        return out
    s2 = stage2_candidates(obj)
    s3 = stage3_verify(s2["candidates"], page, source, region)
    out["stage2"] = s2
    out["stage3"] = {k: v for k, v in s3.items() if not k.startswith("_")}
    out["stage4"] = stage4_constraints(s3["_accepted_obj"])
    out["diagnostic_salvage"] = None
    return out

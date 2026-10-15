"""Deterministic validation of a model's extraction. Nothing here trusts the model's own claims.

  validate_structure(obj)               JSON shape, field types, enums, numeric ranges, required fields
  parse_length(text)                    exact feet/inches parsing (Fraction inches); None when the text is not a length
  verify_evidence(fact, page)           is the quoted evidence really on the page (text layer), and does a claimed box overlap it
  check_values(fact)                    does the extracted number equal a length/number actually present in the verified evidence
  find_duplicates / find_contradictions facts that repeat or disagree
  validate(obj, page, source)           everything above, plus the harness-injected provenance; returns normalized facts and a report

A fact's `effective_status` is "observed" only when the evidence text was found on the page. Otherwise it is "UNVERIFIED".
The model's own `status` is kept as `claimed_status`. Nothing is ever promoted to an estimate input.
"""
import difflib
import re
from fractions import Fraction

from .schema import CATEGORIES, DIM_BASES, STATUSES

REQUIRED_FACT = ("fact_id", "category", "key", "value", "evidence_text", "status", "confidence")
UNITS_LENGTH = {"ft": 12, "feet": 12, "foot": 12, "'": 12, "in": 1, "inch": 1, "inches": 1, '"': 1}

_Q = str.maketrans({"’": "'", "‘": "'", "”": '"', "“": '"', "′": "'", "″": '"', "–": "-", "—": "-", " ": " "})


_INVISIBLE = {**dict.fromkeys(map(ord, "\uffff\u00ad\u200b\u200c\u200d\u2060\ufeff")), 0xFFFE: "-"}   # pdfium emits U+FFFE for the hyphen of a wrapped hyphenated word


def norm(s):
    """Whitespace-, case-, quote- and invisible-character-insensitive form. A text layer may hold U+FFFE/soft hyphens where a word wraps."""
    s = str(s).translate(_Q).translate(_INVISIBLE)
    s = re.sub(r"(?<=[a-z])-\s+(?=[a-z])", "-", s, flags=re.I)   # 'LABOR- COMPLIANCE' (wrapped) == 'LABOR-COMPLIANCE'
    return re.sub(r"\s+", " ", s).strip().lower()


# --------------------------------------------------------------------------------- lengths
_FRAC = r"(?:\d+\s+)?\d+/\d+"
_NUM = r"\d+(?:\.\d+)?"
_FT_IN = re.compile(rf"(?P<ft>{_NUM})\s*'\s*-?\s*(?:(?P<in>{_FRAC}|{_NUM})\s*\")?")
_FT_WORD = re.compile(rf"(?P<ft>{_NUM})\s*(?:ft|feet|foot)\b", re.I)
_IN_MARK = re.compile(rf"(?<![\d/])(?P<in>{_FRAC}|{_NUM})\s*(?:\"|in\b|inch(?:es)?\b)", re.I)


def _to_fraction(tok):
    tok = tok.strip()
    if "/" in tok:
        parts = tok.split()
        whole = Fraction(parts[0]) if len(parts) == 2 else Fraction(0)
        return whole + Fraction(parts[-1])
    return Fraction(tok)


def lengths_in(text):
    """Every length stated in `text`, as exact inches (Fraction). Handles 12'-0", 7', 84", 2-3/8", 1 7/8 IN, 6 FT."""
    t = norm(text)
    found = []
    for m in _FT_IN.finditer(t):
        inches = _to_fraction(m.group("ft")) * 12 + (_to_fraction(m.group("in")) if m.group("in") else 0)
        found.append(inches)
    for m in _FT_WORD.finditer(t):
        found.append(_to_fraction(m.group("ft")) * 12)
    stripped = _FT_IN.sub(" ", t)
    for m in re.finditer(r"(?<![\d/])(\d+)-(\d+/\d+)\s*(?:\"|in\b)", stripped):          # 2-3/8" (inches with a hyphenated fraction)
        found.append(Fraction(m.group(1)) + Fraction(m.group(2)))
    stripped = re.sub(r"(?<![\d/])\d+-\d+/\d+\s*(?:\"|in\b)", " ", stripped)
    for m in _IN_MARK.finditer(stripped):
        found.append(_to_fraction(m.group("in")))
    return found


def parse_length(value, unit=None):
    """Value (+ optional unit) -> exact inches, or None if it is not a length."""
    s = str(value).strip()
    ls = lengths_in(s)
    if len(ls) == 1 and re.fullmatch(r"[\d\s'\"/\-.\w]+", norm(s)):
        return ls[0]
    if unit and norm(unit) in UNITS_LENGTH and re.fullmatch(rf"\s*(?:{_FRAC}|{_NUM})\s*", s):
        return _to_fraction(s) * UNITS_LENGTH[norm(unit)]
    return None


def numbers_in(text):
    return {Fraction(x) for x in re.findall(r"(?<![\w/])\d+(?:\.\d+)?(?![\w/])", norm(text))}


# --------------------------------------------------------------------------------- structure
def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) != float("inf")


def validate_structure(obj):
    """Returns a list of {path, problem}. Empty list = structurally valid."""
    p = []
    add = lambda path, msg: p.append({"path": path, "problem": msg})
    if not isinstance(obj, dict):
        return [{"path": "/", "problem": "top level is not an object"}]
    doc = obj.get("document")
    if not isinstance(doc, dict):
        add("/document", "missing or not an object")
    else:
        for k in ("title", "sheet_number", "revision", "date"):
            if k not in doc:
                add(f"/document/{k}", "missing")
            elif doc[k] is not None and not isinstance(doc[k], str):
                add(f"/document/{k}", "must be a string or null")
    facts = obj.get("facts")
    if not isinstance(facts, list):
        add("/facts", "missing or not a list")
        facts = []
    seen = set()
    for i, f in enumerate(facts):
        base = f"/facts/{i}"
        if not isinstance(f, dict):
            add(base, "not an object")
            continue
        for k in REQUIRED_FACT:
            if k not in f:
                add(f"{base}/{k}", "missing required field")
        if f.get("fact_id") in seen:
            add(f"{base}/fact_id", "duplicate fact_id")
        seen.add(f.get("fact_id"))
        if f.get("category") not in CATEGORIES:
            add(f"{base}/category", f"must be one of {CATEGORIES}")
        if f.get("status") not in STATUSES:
            add(f"{base}/status", f"must be one of {STATUSES}")
        for k in ("key", "location_hint", "note", "unit"):
            if f.get(k) is not None and not isinstance(f.get(k), str):
                add(f"{base}/{k}", "must be a string or null")
        v = f.get("value")
        if v is not None and not isinstance(v, (str, int, float)) or isinstance(v, bool):
            add(f"{base}/value", "must be a string, number or null")
        if _is_num(v) is False and isinstance(v, float):
            add(f"{base}/value", "non-finite number")
        if f.get("evidence_text") is not None and not isinstance(f.get("evidence_text"), str):
            add(f"{base}/evidence_text", "must be a string or null")
        c = f.get("confidence")
        if not _is_num(c) or not 0 <= c <= 1:
            add(f"{base}/confidence", "must be a number in [0, 1]")
        if f.get("dimension_basis") not in DIM_BASES:
            add(f"{base}/dimension_basis", "must be stated_text, visual_estimate or null")
        bb = f.get("bbox_norm")
        if bb is not None and not (isinstance(bb, list) and len(bb) == 4 and all(_is_num(x) and 0 <= x <= 1 for x in bb) and bb[0] < bb[2] and bb[1] < bb[3]):
            add(f"{base}/bbox_norm", "must be null or [x0,y0,x1,y1] within 0-1 with x0<x1, y0<y1")
        if f.get("status") == "observed" and not f.get("evidence_text"):
            add(f"{base}/evidence_text", "an observed fact needs evidence_text")
        if f.get("status") == "unresolved" and f.get("value") not in (None, ""):
            add(f"{base}/value", "an unresolved fact must have a null value")
        if f.get("category") == "dimension" and f.get("dimension_basis") is None:
            add(f"{base}/dimension_basis", "a dimension must say stated_text or visual_estimate")
        if f.get("dimension_basis") == "stated_text" and not f.get("evidence_text"):
            add(f"{base}/evidence_text", "a stated dimension needs evidence_text")
    conf = obj.get("conflicts_or_ambiguities", [])
    if not isinstance(conf, list):
        add("/conflicts_or_ambiguities", "must be a list")
    else:
        for i, c in enumerate(conf):
            if not isinstance(c, dict) or not isinstance(c.get("description"), str) or not isinstance(c.get("evidence_texts", []), list):
                add(f"/conflicts_or_ambiguities/{i}", "needs a description string and an evidence_texts list")
    return p


# --------------------------------------------------------------------------------- evidence
def _overlap(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def text_match(quote, page_text, fuzzy_ratio=0.9):
    """'exact' (whitespace/case/quote-insensitive substring), 'fuzzy' (>= fuzzy_ratio of the quote matches one contiguous block), or None."""
    q, t = norm(quote), norm(page_text)
    if len(q) < 3:
        return None
    if q in t:
        return "exact"
    m = difflib.SequenceMatcher(None, t, q, autojunk=False).find_longest_match(0, len(t), 0, len(q))
    return "fuzzy" if m.size / len(q) >= fuzzy_ratio and len(q) >= 8 else None


def verify_evidence(fact, page):
    """`page` provides .text and .find_rects(quote). Returns the verification block for one fact."""
    quote = fact.get("evidence_text")
    v = {"text": "NO_EVIDENCE_CLAIMED", "bbox": "NOT_PROVIDED", "matched_rects": []}
    if not quote:
        return v
    mt = text_match(quote, page.text)
    v["text"] = {"exact": "VERIFIED_EXACT", "fuzzy": "VERIFIED_FUZZY"}.get(mt, "UNVERIFIED")
    if mt == "exact":
        v["matched_rects"] = page.find_rects(quote)
    bb = fact.get("bbox_norm")
    if bb:
        if not v["matched_rects"]:
            v["bbox"] = "UNVERIFIED"          # nothing independent to compare the claimed box with
        else:
            def tight(r):                       # a claimed box counts only if it is a tight placement of the verified text, not a coarse band that merely overlaps it
                area = lambda b: (b[2] - b[0]) * (b[3] - b[1])
                cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
                return _overlap(bb, r) >= 0.5 or (bb[0] <= cx <= bb[2] and bb[1] <= cy <= bb[3] and area(bb) <= 3 * area(r))
            best = max(_overlap(bb, r) for r in v["matched_rects"])
            v["bbox"] = "VERIFIED" if any(tight(r) for r in v["matched_rects"]) else "MISMATCH"
            v["bbox_best_iou"] = round(best, 4)
    return v


def check_values(fact, verified_text):
    """Does the extracted value occur in the verified evidence? Returns {'value_in_evidence': bool|None, 'parsed_inches': str|None, 'reason': str}."""
    val, unit, quote = fact.get("value"), fact.get("unit"), fact.get("evidence_text")
    out = {"value_in_evidence": None, "parsed_inches": None, "reason": ""}
    if val in (None, "") or not quote:
        return out
    inches = parse_length(val, unit)
    if inches is not None:
        out["parsed_inches"] = str(inches)
        out["value_in_evidence"] = inches in lengths_in(quote)
        out["reason"] = "length equals a length printed in the evidence" if out["value_in_evidence"] else "no length in the evidence equals the extracted value"
        return out
    nums = numbers_in(str(val))
    if nums:
        out["value_in_evidence"] = nums <= numbers_in(quote)
        out["reason"] = "numbers in value all occur in evidence" if out["value_in_evidence"] else "a number in the value does not occur in the evidence"
    elif isinstance(val, str):
        out["value_in_evidence"] = norm(val) in norm(quote)
        out["reason"] = "value text occurs in evidence" if out["value_in_evidence"] else "value text does not occur in the evidence"
    return out


# --------------------------------------------------------------------------------- cross-fact
def find_duplicates(facts):
    seen, dups = {}, []
    for f in facts:
        k = (f.get("category"), norm(f.get("key", "")), norm(f.get("value", "")), norm(f.get("evidence_text") or ""))
        if k in seen:
            dups.append({"fact_id": f["fact_id"], "duplicate_of": seen[k]})
        else:
            seen[k] = f["fact_id"]
    return dups


def find_contradictions(facts):
    by, out = {}, []
    for f in facts:
        if f.get("status") == "unresolved" or f.get("value") in (None, ""):
            continue
        by.setdefault((f.get("category"), norm(f.get("key", ""))), []).append(f)
    for (cat, key), fs in by.items():
        vals = {}
        for f in fs:
            inch = parse_length(f["value"], f.get("unit"))
            vals.setdefault(("len", inch) if inch is not None else ("txt", norm(f["value"])), []).append(f["fact_id"])
        if len(vals) > 1:
            out.append({"category": cat, "key": key, "values": {str(k[1]): ids for k, ids in vals.items()}})
    return out


# --------------------------------------------------------------------------------- orchestration
def validate(obj, page, source):
    """source = {source_document, source_sha256, page_number}. Returns (normalized, report). Never raises on model content."""
    problems = validate_structure(obj)
    facts_in = obj.get("facts") if isinstance(obj, dict) and isinstance(obj.get("facts"), list) else []
    norm_facts, counts = [], {"VERIFIED_EXACT": 0, "VERIFIED_FUZZY": 0, "UNVERIFIED": 0, "NO_EVIDENCE_CLAIMED": 0}
    value_mismatch, bbox_mismatch, visual_est = [], [], []
    for i, f in enumerate(facts_in):
        if not isinstance(f, dict):
            continue
        ev = verify_evidence(f, page) if isinstance(f.get("evidence_text", None), (str, type(None))) else {"text": "UNVERIFIED", "bbox": "NOT_PROVIDED", "matched_rects": []}
        vc = check_values(f, page.text) if ev["text"] in ("VERIFIED_EXACT", "VERIFIED_FUZZY") else {"value_in_evidence": None, "parsed_inches": None, "reason": "evidence not verified"}
        counts[ev["text"]] = counts.get(ev["text"], 0) + 1
        ok_text = ev["text"] in ("VERIFIED_EXACT", "VERIFIED_FUZZY")
        effective = "unresolved" if f.get("status") == "unresolved" else ("observed" if (f.get("status") == "observed" and ok_text and vc["value_in_evidence"] is not False) else "UNVERIFIED")
        if f.get("status") == "inferred":
            effective = "inferred (unverified)"
        if vc["value_in_evidence"] is False:
            value_mismatch.append(f.get("fact_id"))
        if ev.get("bbox") == "MISMATCH":
            bbox_mismatch.append(f.get("fact_id"))
        if f.get("dimension_basis") == "visual_estimate":
            visual_est.append(f.get("fact_id"))
        nf = {**f, **source, "claimed_status": f.get("status"), "effective_status": effective, "verification": ev, "value_check": vc}
        nf.pop("status", None)
        norm_facts.append(nf)
    plain = [f for f in facts_in if isinstance(f, dict) and "fact_id" in f]
    doc = obj.get("document", {}) if isinstance(obj, dict) and isinstance(obj.get("document"), dict) else {}
    sheet = doc.get("sheet_number")
    sheet_check = None if not isinstance(sheet, str) else (text_match(sheet, page.text) is not None)
    n = len(norm_facts)
    report = {"structurally_valid": not problems, "structure_problems": problems, "fact_count": n, "evidence": counts,
              "evidence_verified_rate": round((counts["VERIFIED_EXACT"] + counts["VERIFIED_FUZZY"]) / n, 4) if n else None,
              "value_not_in_evidence": value_mismatch, "bbox_mismatch": bbox_mismatch, "visual_estimates": visual_est,
              "effective_status_counts": {s: sum(1 for f in norm_facts if f["effective_status"] == s) for s in sorted({f["effective_status"] for f in norm_facts})},
              "duplicates": find_duplicates(plain), "contradictions": find_contradictions(plain), "sheet_number_found_on_page": sheet_check,
              "document_fields_missing": [k for k in ("title", "sheet_number", "revision", "date") if not doc.get(k)],
              "note": "effective_status 'observed' requires the evidence text to be found on the page and the value to occur in it; nothing here is an approved estimate input."}
    return {"source": source, "document": doc, "facts": norm_facts, "conflicts_or_ambiguities": obj.get("conflicts_or_ambiguities", []) if isinstance(obj, dict) else []}, report

"""Oracle for Spatial Test 002 (base bid plan crop). Everything is derived from the PDF itself.

Enclosure bounds come from the heaviest stroke class (the perimeter fence line) found in the crop's vector objects; a gate tag's side is the nearest enclosure
edge to the tag label's PDF text position, measured in sheet inches. This corroborates 'which side of the drawn enclosure a gate tag sits on'. It does NOT
establish which fence element a type tag points to: that stays NOT_VERIFIABLE_FROM_PDF.
"""
import json
import pathlib
import re

from . import pdf_text, validator, vector_inventory
from .render import PdfiumPageText, sha256_file

SIDES = ("top", "bottom", "left", "right")
FORBIDDEN_KEYS = ("quantity", "count", "length", "length_ft", "length_lf", "dimension", "dimensions", "measured", "scale", "scaled", "opening", "opening_width", "width", "width_ft",
                  "size", "price", "cost", "total", "estimate")


def _in(r, c, tol=0.002):
    cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
    return c[0] - tol <= cx <= c[2] + tol and c[1] - tol <= cy <= c[3] + tol


class Oracle2:
    def __init__(self, pdf_path, cfg):
        self.pdf_path = pathlib.Path(pdf_path)
        if sha256_file(self.pdf_path) != cfg["source_sha256"]:
            raise ValueError("crop was declared for a different file (hash mismatch); refusing to mix revisions")
        self.cfg, self.crop, self.page_no = cfg, cfg["crop_rect_norm_page"], cfg["page_number"]
        self.page = PdfiumPageText(self.pdf_path, self.page_no)
        self.text = self.page.text
        self.vectors = vector_inventory.vector_inventory(self.pdf_path, self.page_no)
        w, h = self.page.w, self.page.h
        self.in_per_norm = (w / 72.0, h / 72.0)
        heavy = [p for p in self.vectors["paths"] if p["stroke_width_pt"] >= cfg["enclosure_stroke_min_pt"] and _in(p["rect_norm"], self.crop, 0.0)]
        if not heavy:
            raise ValueError("no perimeter stroke found in the crop")
        self.enclosure = [min(p["rect_norm"][0] for p in heavy), min(p["rect_norm"][1] for p in heavy), max(p["rect_norm"][2] for p in heavy), max(p["rect_norm"][3] for p in heavy)]

    def close(self):
        self.page.close()

    def _rect(self, s, e):
        boxes = [self.page.tp.get_charbox(i) for i in range(s, e) if not self.text[i].isspace()]
        w, h = self.page.w, self.page.h
        return [min(b[0] for b in boxes) / w, 1 - max(b[3] for b in boxes) / h, max(b[2] for b in boxes) / w, 1 - min(b[1] for b in boxes) / h]

    def occurrences(self, pattern):
        out = []
        for m in re.finditer(pattern, self.text):
            r = self._rect(m.start(), m.end())
            if _in(r, self.crop):
                out.append({"text": m.group(0), "rect_norm": r, "preceded_by": self.text[max(0, m.start() - 3):m.start()].replace("\r", " ").replace("\n", " ")})
        return out

    def side_of(self, rect):
        cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
        e, (kx, ky) = self.enclosure, self.in_per_norm
        d = {"left": abs(cx - e[0]) * kx, "right": abs(cx - e[2]) * kx, "top": abs(cy - e[1]) * ky, "bottom": abs(cy - e[3]) * ky}
        side = min(d, key=d.get)
        return side if d[side] <= self.cfg["edge_to_interior_threshold_in"] else "interior"

    def gate_tags(self):
        """{tag: [side per drawn tag label]} for G1..G3 in the crop, excluding 'CL G#' centerline labels."""
        out = {}
        for t in ("G1", "G2", "G3"):
            locs = [o for o in self.occurrences(t + r"(?!\d{2})") if not o["preceded_by"].rstrip().endswith("CL")]
            if locs:
                out[t] = [{"side": self.side_of(o["rect_norm"]), "rect_norm": o["rect_norm"]} for o in locs]
        return out

    def fence_type_tags(self):
        """Type tag letters A/B present in the crop (a letter, or a letter glued to its keynote digit such as 'A1')."""
        out = {}
        for w in pdf_text.word_inventory(self.pdf_path, self.page_no)["words"]:
            m = re.fullmatch(r"([AB])\d?", w["text"])
            if m and _in(w["rect_norm"], self.crop):
                out.setdefault(m.group(1), []).append(w["rect_norm"])
        return out

    def anchor_found(self, anchor):
        """The anchor text must exist in the PDF text layer INSIDE the crop. Short anchors (a tag such as G1 or B) are matched as substrings of the crop's text."""
        if not isinstance(anchor, str) or not anchor.strip():
            return False
        a = anchor.strip()
        if len(validator.norm(a)) < 3:                                         # a tag: must be a whole printed token (or a tag glued to its keynote digit), not a stray letter
            if re.fullmatch(r"G[123]", a):
                return a in self.gate_tags()
            words = [w["text"] for w in pdf_text.word_inventory(self.pdf_path, self.page_no)["words"] if _in(w["rect_norm"], self.crop)]
            return a in words or (re.fullmatch(r"[AB]", a) is not None and any(re.fullmatch(a + r"\d", w) for w in words))
        if validator.text_match(a, self.text) != "exact":
            return False
        rects = self.page.find_rects(a)
        return any(_in(r, self.crop) for r in rects) if rects else bool(self.occurrences(re.escape(a)))


KINDS = ("gate_tag", "fence_type_tag")
UNCERT = ("clear", "uncertain", "cannot_establish")
SIDE_VALUES = SIDES + ("interior", "unclear", None)
ALLOWED = {"kind", "label", "location_description", "enclosure_side", "visible_anchor", "uncertainty"}


def validate_association(a):
    """Strict shape of one association. Returns a list of problems (empty = valid)."""
    if not isinstance(a, dict):
        return ["not an object"]
    p = []
    if set(a) & set(FORBIDDEN_KEYS):
        p.append(f"forbidden field(s): {sorted(set(a) & set(FORBIDDEN_KEYS))}")
    if set(a) - ALLOWED - set(FORBIDDEN_KEYS):
        p.append(f"unknown field(s): {sorted(set(a) - ALLOWED - set(FORBIDDEN_KEYS))}")
    if a.get("kind") not in KINDS:
        p.append(f"kind must be one of {KINDS}")
    if not isinstance(a.get("label"), str) or not a.get("label", "").strip():
        p.append("label must be a non-empty string")
    if not isinstance(a.get("location_description"), str):
        p.append("location_description must be a string")
    if a.get("enclosure_side") not in SIDE_VALUES:
        p.append(f"enclosure_side must be one of {SIDE_VALUES}")
    if a.get("visible_anchor") is not None and not isinstance(a.get("visible_anchor"), str):
        p.append("visible_anchor must be a string or null")
    if a.get("uncertainty") not in UNCERT:
        p.append(f"uncertainty must be one of {UNCERT}")
    return p


def check_association(a, o):
    """PDF-derived verdict for one structurally valid association."""
    anchor_ok = o.anchor_found(a.get("visible_anchor"))
    r = {"anchor_found_in_pdf_text_inside_crop": anchor_ok}
    label, side = a["label"].strip(), a.get("enclosure_side")
    if a["kind"] == "gate_tag":
        tags = o.gate_tags()
        if label not in tags:
            return {**r, "tag_exists": False, "verdict": "CONTRADICTED_BY_PDF", "why": f"no {label} tag label in the crop per the PDF text layer"}
        sides = sorted({l["side"] for l in tags[label]})
        r.update(tag_exists=True, pdf_sides=sides, pdf_locations_norm_page=[l["rect_norm"] for l in tags[label]])
        if side in (None, "unclear"):
            return {**r, "verdict": "TAG_CONFIRMED_NO_SIDE_CLAIM", "why": "tag exists; the model made no definite side claim"}
        if side in sides:
            return {**r, "verdict": "SIDE_CONFIRMED_BY_PDF_POSITION", "why": f"a {label} tag label sits nearest the {side} edge of the drawn enclosure"}
        return {**r, "verdict": "SIDE_CONTRADICTED_BY_PDF_POSITION", "why": f"{label} tag label(s) sit at {sides}; claimed {side}"}
    types = o.fence_type_tags()
    if label not in types:
        return {**r, "tag_exists": False, "verdict": "CONTRADICTED_BY_PDF", "why": f"no type tag {label} in the crop per the PDF text layer"}
    return {**r, "tag_exists": True, "verdict": "NOT_VERIFIABLE_FROM_PDF", "why": "the type tag exists, but which drawn fence element it points to is a visual relationship the PDF text layer cannot establish"}


def evaluate(parsed, o, outcome_normal):
    """parsed is the strictly parsed object. Returns checks and the seven-way scoring. Oracle answers are used only here, after the model has responded."""
    shape_ok = isinstance(parsed, dict) and isinstance(parsed.get("visual_associations"), list) and isinstance(parsed.get("unresolved"), list) and next(iter(parsed), None) == "visual_associations"
    rows = []
    if shape_ok:
        for i, a in enumerate(parsed["visual_associations"]):
            probs = validate_association(a)
            rows.append({"index": i, "association": a, "schema_problems": probs, "pdf_check": None if probs else check_association(a, o), "informational_only": True})
    tags = o.gate_tags()
    gate_rows = [r for r in rows if not r["schema_problems"] and r["association"]["kind"] == "gate_tag"]
    type_rows = [r for r in rows if not r["schema_problems"] and r["association"]["kind"] == "fence_type_tag"]
    v = lambda r: r["pdf_check"]["verdict"]
    reported = sorted({r["association"]["label"].strip() for r in gate_rows})
    score = {
        "1_valid_and_completed_json": bool(shape_ok and outcome_normal and all(not r["schema_problems"] for r in rows)),
        "2_gate_tag_identification": {"reported_labels": reported, "correct": [t for t in reported if t in tags], "not_in_crop": [t for t in reported if t not in tags], "missed_by_model": [t for t in tags if t not in reported]},
        "3_gate_side_relationships": {"confirmed": [r["index"] for r in gate_rows if v(r) == "SIDE_CONFIRMED_BY_PDF_POSITION"], "contradicted": [r["index"] for r in gate_rows if v(r) == "SIDE_CONTRADICTED_BY_PDF_POSITION"],
                                      "no_definite_side": [r["index"] for r in gate_rows if v(r) == "TAG_CONFIRMED_NO_SIDE_CLAIM"]},
        "4_fence_type_to_drawn_element_associations": {"claimed": [r["index"] for r in type_rows], "type_tag_exists": [r["index"] for r in type_rows if r["pdf_check"].get("tag_exists")],
                                                        "verified_by_pdf": [], "note": "none can be verified from the PDF text layer"},
        "5_incorrect_or_unsupported": {"contradicted_or_invalid": [r["index"] for r in rows if r["schema_problems"] or v(r) in ("CONTRADICTED_BY_PDF", "SIDE_CONTRADICTED_BY_PDF_POSITION")],
                                       "anchor_not_found": [r["index"] for r in rows if not r["schema_problems"] and not r["pdf_check"]["anchor_found_in_pdf_text_inside_crop"]]},
        "6_explicit_uncertainties": {"associations_marked_uncertain_or_cannot_establish": [r["index"] for r in rows if not r["schema_problems"] and r["association"]["uncertainty"] != "clear"],
                                     "unresolved_entries": len(parsed["unresolved"]) if shape_ok else 0},
        "7_claims_the_oracle_cannot_establish": [r["index"] for r in rows if not r["schema_problems"] and v(r) == "NOT_VERIFIABLE_FROM_PDF"],
    }
    return {"shape_ok": shape_ok, "rows": rows, "score": score}

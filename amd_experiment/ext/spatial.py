"""Independent checks for spatial interpretation claims. Everything here is derived from the PDF itself (text layer positions, vector stroke classes).

Three kinds of statement are kept strictly apart:
  text quotation        a verbatim quote found in the PDF text layer (ext/validator.py)
  visual association    a claim about where something is or how two things relate. It is CONFIRMED only when the PDF text layer places the cited anchor text in
                        the claimed zone; otherwise it stays NOT_VERIFIABLE_FROM_PDF. A model's description of a drawn relationship is never promoted to a fact.
  forbidden inference   quantities, scaled/measured lengths, gate opening widths: rejected outright (C101 itself states that gate opening sizes are not shown)

This module produces no quantities and approves nothing.
"""
import json
import pathlib
import re

from . import pdf_text, validator, vector_inventory
from .render import PdfiumPageText, sha256_file

TAG = re.compile(r"G[123](?!\d{2})")
FORBIDDEN_KEYS = ("quantity", "count_total", "length_ft", "length_lf", "measured", "scaled", "opening_width", "width_ft", "price", "cost")


def inside(r, z, tol=0.002):
    cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
    return z[0] - tol <= cx <= z[2] + tol and z[1] - tol <= cy <= z[3] + tol


class Oracle:
    def __init__(self, pdf_path, page_number, zones_config):
        self.pdf_path, self.page_number = pathlib.Path(pdf_path), page_number
        if sha256_file(self.pdf_path) != zones_config["source_sha256"]:
            raise ValueError("zones were declared for a different file (hash mismatch); refusing to mix revisions")
        self.zones = {k: v["rect"] for k, v in zones_config["zones"].items()}
        self.page = PdfiumPageText(self.pdf_path, page_number)
        self.text = self.page.text
        self.words = pdf_text.word_inventory(pdf_path, page_number)["words"]
        self.vectors = vector_inventory.vector_inventory(pdf_path, page_number)

    def close(self):
        self.page.close()

    def char_rect(self, start, end):
        boxes = [self.page.tp.get_charbox(i) for i in range(start, end) if not self.text[i].isspace()]
        w, h = self.page.w, self.page.h
        return [min(b[0] for b in boxes) / w, 1 - max(b[3] for b in boxes) / h, max(b[2] for b in boxes) / w, 1 - min(b[1] for b in boxes) / h]

    def occurrences(self, pattern, zone=None):
        """Regex matches in the PDF text, each with its PDF-derived rectangle and the preceding two characters as context (e.g. 'CL ')."""
        out = []
        for m in re.finditer(pattern, self.text):
            r = self.char_rect(m.start(), m.end())
            if zone is None or inside(r, self.zones[zone]):
                out.append({"text": m.group(0), "rect_norm": r, "preceded_by": self.text[max(0, m.start() - 3):m.start()].replace("\r", " ").replace("\n", " ")})
        return out

    def tag_locations(self, tag, zone):
        """Plan occurrences of a gate tag, excluding the 'CL G#' centerline labels."""
        return [o for o in self.occurrences(re.escape(tag) + r"(?!\d{2})", zone) if not o["preceded_by"].rstrip().endswith("CL")]

    def court_labels(self, zone):
        return len(self.occurrences(r"COURT\s?[1-4]\b", zone))

    def detail_callouts(self):
        """Callout bubbles (number above 'F501'/'F502'): returns [{'detail': '1/F501', 'rect_norm': ...}] from the text layer."""
        out = []
        for i, w in enumerate(self.words):
            if w["text"] in ("F501", "F502"):
                r = w["rect_norm"]
                cands = [x for x in self.words if re.fullmatch(r"\d", x["text"]) and 0 < r[1] - x["rect_norm"][3] < 0.03 and abs((x["rect_norm"][0] + x["rect_norm"][2]) / 2 - (r[0] + r[2]) / 2) < 0.012]
                if cands:
                    out.append({"detail": f"{cands[0]['text']}/{w['text']}", "rect_norm": [min(r[0], cands[0]["rect_norm"][0]), cands[0]["rect_norm"][1], max(r[2], cands[0]["rect_norm"][2]), r[3]]})
        return out

    def reference_table(self):
        rows = {}
        for ln in self.text.splitlines():
            m = re.match(r"^(A|B|WS|G[123])\s+(.+?)\s+(\d/F50[12])\s+32 31 13\s*$", ln.strip())
            if m and self.occurrences(re.escape(ln.strip()), "fence_gate_reference_table"):
                rows[m.group(1)] = {"description": m.group(2), "detail": m.group(3)}
        return rows

    def stroke_classes(self, zone):
        """Distinct (stroke width, dashed) classes of vector paths in a zone. Corroborates 'a heavy line exists here'; says nothing about length or count."""
        z = self.zones[zone]
        return sorted({(p["stroke_width_pt"], p["dash_count"] > 0) for p in self.vectors["paths"] if inside(p["rect_norm"], z)})


def _verdict(v, why):
    return {"verdict": v, "why": why}


def check_claim(c, o):
    """One visual-association or text-dependent claim against the PDF. Never raises on model content."""
    t = c.get("claim_type") if isinstance(c, dict) else None
    if not isinstance(c, dict) or not t:
        return _verdict("MALFORMED", "claim is not an object with a claim_type")
    if any(k in c for k in FORBIDDEN_KEYS):
        return _verdict("REJECTED_FORBIDDEN_INFERENCE", f"claim carries a quantity/measurement/price field: {sorted(set(FORBIDDEN_KEYS) & set(c))}")
    if t in ("gate_opening", "gate_width", "gate_size"):
        stated = bool(o.occurrences(r"GATE OPENING SIZES ARE NOT SHOWN ON THIS SHEET"))
        return _verdict("REJECTED_FORBIDDEN_INFERENCE", "this sheet states that gate opening sizes are not shown" if stated else "gate opening sizes may not be inferred from drawing geometry")
    if t == "view_identity":
        q = c.get("title_quote") or ""
        if not validator.text_match(q, o.text):
            return _verdict("CONTRADICTED_BY_PDF", "title quote is not in the text layer")
        rects = o.page.find_rects(q)
        z = {"base_bid": "base_bid_plan", "alternate_a1": "alternate_a1_plan"}.get(c.get("view"))
        if z is None:
            return _verdict("MALFORMED", "view must be base_bid or alternate_a1")
        want = "BASE BID" if c["view"] == "base_bid" else "ALTERNATE A-1"
        return _verdict("CONFIRMED_BY_PDF_TEXT", "title text exists and names that view") if want in q.upper() and rects else _verdict("CONTRADICTED_BY_PDF", "title text does not name that view")
    if t == "tag_in_view":
        tag, view = c.get("tag"), c.get("view")
        z = {"base_bid": "base_bid_plan", "alternate_a1": "alternate_a1_plan"}.get(view)
        if z is None or not isinstance(tag, str) or not re.fullmatch(r"G[123]", tag):
            return _verdict("MALFORMED", "needs tag G1/G2/G3 and view base_bid/alternate_a1")
        locs = o.tag_locations(tag, z)
        if not locs:
            other = "alternate_a1_plan" if z == "base_bid_plan" else "base_bid_plan"
            return _verdict("CONTRADICTED_BY_PDF", f"no {tag} tag text in the {view} plan zone" + (f"; it does appear in the other view" if o.tag_locations(tag, other) else ""))
        out = _verdict("CONFIRMED_BY_PDF_TEXT_POSITION", f"{len(locs)} {tag} tag label(s) placed in that plan zone by the PDF text layer")
        out["pdf_text_locations_norm_page"] = [l["rect_norm"] for l in locs]
        if "location_count" in c and c["location_count"] != len(locs):
            out = _verdict("CONTRADICTED_BY_PDF", f"claimed {c['location_count']} location(s); the PDF text layer places {len(locs)}")
        return out
    if t == "detail_callout":
        want, found = c.get("detail"), [d["detail"] for d in o.detail_callouts()]
        return _verdict("CONFIRMED_BY_PDF_TEXT_POSITION", "callout text found") if want in found else _verdict("CONTRADICTED_BY_PDF", f"callout {want} not found; callouts found: {sorted(set(found))}")
    if t == "reference_table_row":
        row = o.reference_table().get(c.get("tag"))
        if not row:
            return _verdict("CONTRADICTED_BY_PDF", "no such row in the reference table text")
        return _verdict("CONFIRMED_BY_PDF_TEXT", "row found with that detail") if row["detail"] == c.get("detail") else _verdict("CONTRADICTED_BY_PDF", f"table gives {row['detail']}")
    if t == "fence_type_present":
        z = {"base_bid": "base_bid_plan", "alternate_a1": "alternate_a1_plan"}.get(c.get("view"))
        return _verdict("NOT_VERIFIABLE_FROM_PDF", "visual association; heavy-stroke geometry exists in the zone but the type mapping is not machine-confirmed") if z and o.stroke_classes(z) else _verdict("CONTRADICTED_BY_PDF", "no vector geometry in that zone")
    return _verdict("NOT_VERIFIABLE_FROM_PDF", f"claim type {t!r} has no deterministic check; kept as an unverified visual association")

"""Prompt and processing for the C101 spatial interpretation test. The prompt carries no expected answers and no hints about what the sheet is missing."""
import json

from . import pipeline, spatial, validator

SYSTEM = ("You are a careful reader of construction drawings. You report only what is printed or drawn on the sheet. You never invent text, numbers, dimensions or locations, "
          "and you never measure or scale anything. When something is missing, unclear or conflicting you say so explicitly.")

PROMPT = """The image is a cropped region of one drawing sheet. Return ONE JSON object and nothing else (no markdown):
{
  "document": {"title": string|null, "sheet_number": string|null, "revision": string|null, "date": string|null},
  "text_facts": [
    {"fact_id": "T1", "category": "note"|"reference"|"gate"|"fence_callout"|"title_block"|"ambiguity", "key": short label, "value": the statement as text, "unit": string|null,
     "evidence_text": the EXACT printed text, copied character for character, "location_hint": short phrase, "dimension_basis": "stated_text"|null, "confidence": 0-1,
     "status": "observed"|"unresolved"}
  ],
  "visual_associations": [
    {"assoc_id": "V1",
     "claim_type": "view_identity" | "tag_in_view" | "detail_callout" | "reference_table_row" | "fence_type_present" | "other_visual",
     "view": "base_bid" | "alternate_a1" | null,
     "tag": gate tag such as "G1" or null, "detail": detail callout such as "1/F501" or null, "fence_type": "A"|"B"|null,
     "title_quote": the exact printed view title for a view_identity claim, or null,
     "location_count": integer number of places the tag is drawn in that view, or null,
     "anchor_text": the exact printed text next to what you describe (a tag, callout or title), or null,
     "description": one sentence describing what you see, in words,
     "basis": "printed_text" | "visual", "confidence": 0-1}
  ]
}
Report: which drawn view is the base bid and which is the bid alternate; which fence types are drawn in each view; where each gate tag appears (by view);
which detail callouts (number over sheet) appear and what they point to; and anything missing, conflicting or ambiguous.
Rules: do not guess; copy printed text exactly; never give a length, width, quantity or count of fence that you did not read as printed text; do not measure or scale;
a gate opening size must not be stated unless it is printed next to that gate. Visual claims need the exact printed anchor_text you rely on."""


def process_spatial(content, page, source, region, oracle):
    """Text facts go through the existing strict pipeline (as `facts`); visual associations are checked by the PDF-derived oracle and kept apart."""
    obj, cat, detail = pipeline.strict_parse(content)
    out = {"strict_parse": {"category": cat, "detail": detail}, "text_facts_pipeline": None, "visual_associations": []}
    if obj is None:
        return out
    if not isinstance(obj.get("text_facts"), list) or not isinstance(obj.get("visual_associations"), list):
        out["strict_parse"] = {"category": "wrong_shape", "detail": "text_facts and visual_associations must both be lists"}
        return out
    text_obj = {"document": obj.get("document"), "facts": obj["text_facts"]}
    out["text_facts_pipeline"] = pipeline.process_content(json.dumps(text_obj), page, source, region)
    for a in obj["visual_associations"]:
        c = pipeline_claim(a)
        r = spatial.check_claim(c, oracle) if c is not None else {"verdict": "MALFORMED", "why": "not an object"}
        anchor = a.get("anchor_text") if isinstance(a, dict) else None
        anchor_ok = bool(anchor) and validator.text_match(anchor, page.text) in ("exact",)
        out["visual_associations"].append({"assoc_id": a.get("assoc_id") if isinstance(a, dict) else None, "claim": a, "pdf_check": r, "anchor_text_found_on_page": anchor_ok,
                                           "basis_claimed": a.get("basis") if isinstance(a, dict) else None, "informational_only": True,
                                           "never_a_quantity": True})
    return out


def pipeline_claim(a):
    return a if isinstance(a, dict) else None

"""Extraction contract shared by every model: the prompt and the field definitions. Contains no expected answers and no evaluation hints."""

CATEGORIES = ["title_block", "revision", "date", "fence_callout", "dimension", "gate", "reference", "note", "ambiguity"]
STATUSES = ["observed", "inferred", "unresolved"]
DIM_BASES = ["stated_text", "visual_estimate", None]

SYSTEM = ("You are a careful document reader for construction drawings. You report only what is visibly printed on the sheet. "
          "You never invent text, numbers, dimensions or locations. When something is missing, unclear or conflicting you say so explicitly.")

PROMPT = """Read this single drawing sheet image and return ONE JSON object and nothing else (no markdown fences).

{
  "document": {"title": string|null, "sheet_number": string|null, "revision": string|null, "date": string|null},
  "facts": [
    {
      "fact_id": "F1",
      "category": one of ["title_block","revision","date","fence_callout","dimension","gate","reference","note","ambiguity"],
      "key": short label for what the fact is,
      "value": the extracted value as text (or number),
      "unit": unit string such as "ft", "in", "LF", "EA", or null,
      "evidence_text": the EXACT text you can see on the sheet that supports the fact, copied character for character, or null if there is none,
      "location_hint": where on the sheet it appears (e.g. "title block, lower right", "view 1, north side"),
      "bbox_norm": [x0, y0, x1, y1] as fractions 0-1 of the image width/height (origin top-left) if you can place it reliably, otherwise null,
      "dimension_basis": "stated_text" if the number is printed on the sheet, "visual_estimate" if you measured it by eye, or null for non-dimension facts,
      "confidence": number 0-1,
      "status": "observed" (printed on the sheet), "inferred" (not printed; you deduced it) or "unresolved" (needed but not determinable),
      "note": optional short explanation
    }
  ],
  "conflicts_or_ambiguities": [
    {"description": string, "evidence_texts": [exact visible texts involved], "status": "observed" or "unresolved"}
  ]
}

Extract: the document title and sheet number; the drawing revision and dates when visible; every fence-related callout and description;
every dimension with its unit; gate descriptions and any gate schedule; references to other drawings or specification sections; and anything
that is missing, conflicting or ambiguous on this sheet.
Rules: do not guess. Copy evidence_text exactly. Use "visual_estimate" for any dimension you did not read from printed text.
Use "unresolved" with value null when the sheet needs information it does not give."""

REGION_NOTE = """
NOTE: the image is a CROPPED REGION of a larger drawing sheet, not the whole sheet. Report only what is visible in this crop.
If the sheet title, sheet number, revision or date are not visible in the crop, set the corresponding document fields to null and do not guess them.
bbox_norm is relative to this cropped image."""
PROMPT_REGION = PROMPT + "\n" + REGION_NOTE

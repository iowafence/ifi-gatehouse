"""Prompt for Spatial Test 002. Visual/spatial association only: no transcription, no dimensions. No expected answers, no gate locations, no tag names."""
SYSTEM = ("You look at one cropped fence plan from a construction drawing and report only what is visibly drawn. You never invent text, tags, locations or specifications, "
          "you never measure or scale, and you say so when a relationship cannot be established from the image.")

PROMPT = """The image is a cropped region of a construction drawing: one fence plan view with its view title.
Return ONE compact JSON object, with "visual_associations" as the FIRST key, on as few lines as possible (no indentation, no markdown, no other text):
{"visual_associations":[{"kind":"gate_tag"|"fence_type_tag","label":"the tag text as printed","location_description":"one short phrase","enclosure_side":"top"|"bottom"|"left"|"right"|"interior"|"unclear","visible_anchor":"the exact printed text you rely on","uncertainty":"clear"|"uncertain"|"cannot_establish"}],"unresolved":[{"description":"one short sentence"}]}
Task, for this one plan view only:
(1) For each gate tag drawn in the plan (a rounded label containing the letter G and a number), report which side of the fenced enclosure it sits on, as drawn on this image. If the same gate tag appears in more than one place, give one entry for each place.
(2) For each fence-type tag (a diamond containing a single letter), describe in location_description the drawn fence element it appears to point to, and set enclosure_side to where that element is.
Use top, bottom, left and right as they appear on this image. Keep every text field under 15 words. Report at most 8 entries. Use an empty array where no defensible association exists.
Put anything you cannot establish from the image in "unresolved".
Do not report dimensions, scales, notes, court labels, titles, quantities, prices, gate sizes or openings. Do not measure or scale. Do not assume specifications that are not visible."""

# Spatial Test 003 — proposed live-call plan (FOR AUTHORIZATION; NOTHING HAS BEEN SENT)

**Status: PROPOSED — NOT AUTHORIZED. No AMD request has been made. LIVE_CALLS_DISABLED stays in force until Jordan authorizes this exact plan.**

Plan hash (`plan_sha256_excluding_this_field`): `784c93c8d9457cf6c8005070c15280f1e2626588fccb4dc57a32759c7662b96d`

## Why this is not the 001 prompt

Test 001 asked for an exhaustive text transcription of both plan views and hit the 150 s wall limit with truncated JSON (nothing accepted). Test 002 (visual associations first, compact) completed in 99.96 s: 4/4 gate-tag sides matched PDF label positions, but fence-type-tag targets could not be verified, and tag B's 'top fence line' claim was wrong (the leader ends on an interior divider) while the model said 'clear'. Test 003 therefore (a) uses three **small** crops, (b) asks only visual associations in a compact schema, (c) removes transcription entirely, and (d) is scored by a **pre-registered vector oracle** that can finally check type-tag leader targets.

## Source and crops (local renders, hashes recorded)

Source: `dp001_ansi_b_v2_drawings` sha256 `62ab61d7f2558245f4a6f1708d9320a49e66fd28bf829a2329be5b79db9ac525`, page 2 (C101). Rendered at 200 dpi with PDFium.

| Crop | Region (page-normalized x0,y0,x1,y1) | Pixels | Image sha256 | Purpose |
|---|---|---|---|---|
| `r1_north_band_gates_and_tag` | [0.2, 0.15, 0.55, 0.3] | [1190, 330] | `d51cf19e0b13f6cbcf3864a11e8c9e7af2e182d226776b82aeaab2f12df4e930` | gate tags along ONE fence line (north) and the leader of ONE type tag |
| `r2_east_edge_type_tag_and_gate` | [0.48, 0.24, 0.62, 0.5] | [476, 572] | `57e3f3218ae8cd1cb0692c9175837cf0625e2850778beafa2ca3a3ffbbb3d288` | one type tag on the east perimeter and the gate tag on that edge |
| `r3_west_edge_gate` | [0.07, 0.38, 0.22, 0.5] | [510, 264] | `a467df4fe5594cd07d3d778e02036bb64638836478def3c2cc6ce66da8a963db` | the gate tag on the west edge |

Files: `spatial_plan/crops/*.png`. The oracle's pre-flight answers (gate order, type-tag leader target) are stored in the plan JSON for the scorer only and are never part of the prompt.

## Prompt (verbatim; per-crop only the ordering phrase differs)

System:

> You look at one small cropped region of a fence plan from a construction drawing and report only what is visibly drawn. You never invent text, tags or locations, you never measure, scale or read dimensions, and you say so when a relationship cannot be established from the image.

User template:

```
The image is a small crop of a fence plan. Answer with ONE compact JSON object on a single line (no indentation, no markdown, no other text) whose FIRST key is "gate_tags":
{"gate_tags":[{"tag":"printed text","adjacent_symbol":"single_leaf_swing"|"double_leaf_swing"|"opening_only"|"unclear","uncertainty":"clear"|"uncertain"|"cannot_establish"}],"type_tags":[{"tag":"printed letter","leader_ends_on":"perimeter_fence"|"interior_divider"|"other"|"unclear","uncertainty":"clear"|"uncertain"|"cannot_establish"}],"ambiguous":[{"description":"one short sentence"}]}
Rules:
(1) gate_tags: every gate tag (a rounded label containing the letter G and a number) visible in the crop, listed __ORDER__. One entry per drawn tag; "adjacent_symbol" is the gate symbol drawn right next to that tag.
(2) type_tags: every fence-type tag (a diamond containing one letter) visible in the crop. "leader_ends_on" is what the thin leader line from the diamond ends on: the heavy outer fence line (perimeter_fence), a thinner line inside the enclosure (interior_divider), something else (other), or you cannot tell (unclear).
(3) Put every relationship you cannot establish from the image in "ambiguous". Use empty arrays where nothing applies. At most 6 entries per array; keep every text field under 12 words.
Do not transcribe notes, titles or any other text. Do not report dimensions, scales, quantities, prices, gate sizes or openings.
```

Ordering phrase: {"gates_left_to_right": "from left to right as they appear", "gates_top_to_bottom": "from top to bottom as they appear"}

The prompt names no tag, no expected answer and no court; it asks for no transcription, dimension, scale or quantity.

## Output schema (strict)

```json
{
 "first_key": "gate_tags",
 "allowed_top_level": [
  "gate_tags",
  "type_tags",
  "ambiguous"
 ],
 "gate_tags_item": {
  "tag": "str",
  "adjacent_symbol": [
   "single_leaf_swing",
   "double_leaf_swing",
   "opening_only",
   "unclear"
  ],
  "uncertainty": [
   "clear",
   "uncertain",
   "cannot_establish"
  ]
 },
 "type_tags_item": {
  "tag": "str",
  "leader_ends_on": [
   "perimeter_fence",
   "interior_divider",
   "other",
   "unclear"
  ],
  "uncertainty": [
   "clear",
   "uncertain",
   "cannot_establish"
  ]
 },
 "ambiguous_item": {
  "description": "str"
 },
 "max_entries_per_array": 6,
 "forbidden_keys_anywhere": [
  "quantity",
  "count",
  "length",
  "length_ft",
  "length_lf",
  "dimension",
  "dimensions",
  "measured",
  "scale",
  "scaled",
  "opening",
  "opening_width",
  "width",
  "width_ft",
  "size",
  "price",
  "cost",
  "total",
  "estimate"
 ]
}
```

## Model settings

```json
{
 "model": "DeepSeek-V4.1-Flash",
 "why": "the only model that has completed a spatial request on this drawing (run 002, 99.96 s)",
 "stream": true,
 "max_tokens": 400,
 "temperature": 0.0,
 "response_format": {
  "type": "json_object"
 },
 "extra_parameters": null,
 "no_progress_abort_s": 90,
 "wall_abort_s": 150,
 "retries": 0,
 "parallel_requests": 0,
 "order": "r1 -> r2 -> r3, one at a time; STOP at the first non-normal outcome"
}
```

Budget: at most 3 requests, max_tokens 400 each; the previous completed request cost about $0.003; provider limit 20 requests/minute and $1/day

## Evaluation rules (pre-registered)

* **oracle** — spatial_plan/oracle3.py (pre-registered): PDF text positions (spatial2.Oracle2) + PDF vector objects; derived after the response, never shown to the model
* **1_valid_completed_json** — stream outcome normal AND strict JSON (no fences, no trailing text, no duplicate keys, no NaN) AND shape as SCHEMA (first key gate_tags, enums, <= 6 entries, no forbidden keys)
* **2_gate_tag_identification_and_order** — the ordered tag list equals the oracle order for the crop (x-order for r1, y-order for r2/r3); each reported tag must be a printed tag inside the crop (else CONTRADICTED)
* **3_type_tag_leader_target** — per tag: claim vs oracle3.leader_target element: CONFIRMED_BY_VECTOR_GEOMETRY / CONTRADICTED_BY_VECTOR_GEOMETRY / NOT_VERIFIABLE; interior_divider is NOT a perimeter side
* **4_adjacent_symbol** — NOT verifiable by code: recorded as VISUAL_ONLY_HUMAN_REVIEW; never counted correct or incorrect; never accepted as a fact
* **5_calibration** — every entry marked 'clear' that is CONTRADICTED is counted as an overconfidence event
* **6_acceptance** — NOTHING from this experiment is a scope fact. Verified items become 'AI-suggested, evidence verified' candidates; the rest stay 'spatial verification incomplete'; a human decides
* **success_bar_for_claiming_spatial_understanding** — all three requests normal-complete AND gate orders correct in all crops AND every type-tag leader claim CONFIRMED (none CONTRADICTED) AND no 'clear' overconfidence event; anything less is reported as NOT DEMONSTRATED with the exact failures

## Frozen files

* `spatial_plan/oracle3.py` — `e379994dcb059c89eaeeec291258821463f62fd838fd7f0b7769b4c3f4f76e64`
* `spatial_plan/build_plan.py` — `82d6aeba09b76c8a3a2c2d8ff02037902b1d385e379165c6ab567b7ea7afe7ec`
* `spatial_plan/score.py` — `aff3c7916d8061f3899c01f25c408a6aab4efacd5c86fb86e72dfa42c9d1b152`

The oracle (`oracle3.py`) was applied RETROSPECTIVELY to run 002's stored response: tag A → CONFIRMED (leader ends on the east perimeter), tag B → CONTRADICTED (leader ends on an interior Type B divider, not the top fence line). That retrospective result is labelled as such everywhere and is not part of run 002's original score.

## Execution procedure after authorization

1. Jordan authorizes this plan (hash below) in writing
2. verify every hash in this plan against the files and the experiment harness version
3. suspend LIVE_CALLS_DISABLED ONLY around each single request (as spatial_live2.py), restore and verify it identical afterwards
4. send r1; if outcome is not 'normal' STOP (no retry, no salvage); else score with oracle3 + schema; write write-once evidence under runs_v3/
5. only then send r2, then r3
6. freeze all result files with a hash manifest; report real vs failed outcomes without ranking models

## What you are asked to authorize

Up to **three sequential single requests** (r1, r2, r3) to DeepSeek-V4.1-Flash with exactly the files above, no retries, stop at the first non-normal outcome, `LIVE_CALLS_DISABLED` suspended only around each request and restored. Reply with the plan hash to authorize.

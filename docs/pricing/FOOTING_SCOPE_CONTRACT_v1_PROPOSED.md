# footing-scope.v1 — per-run, per-post-class footing contract (PROPOSED)

**Status: PROPOSED. Not approved. Additive and optional.** `pricing-service.v1` (`engine/pricing_service.py`, `docs/pricing/ENGINE_INTERFACE_CONTRACT.md`,
`docs/pricing/engine_interface.v1.json`) is **unchanged and still frozen**: no function, key, error or digest rule of that contract was edited, and `tests/test_pricing_service.py`
still pins it. `gatehouse-http-adapter.v1` stays PROPOSED and `api/server.py` is byte-identical. The pins for this contract are `docs/pricing/footing_scope.v1.json` and
`pricing/schemas/footing_scope.v1.schema.json`.

Three independently identifiable versions: contract `footing-scope.v1` (the input), calculation `footing-calc.v1` (the arithmetic), schedule `footing-schedule.v1` (the output).

## 1. Root cause and implementation boundary

| Defect (Pass 6) | Where it lived | Fixed by |
|---|---|---|
| One terminal and one line footing for every post | `pricing/quantities.py::_concrete` read four project-wide facts (`footing_terminal/line_diameter/depth`) and multiplied them by the run's terminal / line-post counts | a footing size **per post class** |
| Line posts counted as a run-wide lower bound | `engine/takeoff.py` (`ceil(net/spacing) - segments`) — each segment is not rounded up on its own | per-segment counting from the run's segment layout |
| G3 gate posts priced as Type A terminals | a gate with no `gate_post_od_in` fact is treated as a terminal | a gate-post class per gate tag; an unestablished class makes its quantities unresolved |
| Mixed classes unsupported | no input could say "Type B" | `classes` + `runs` in the scope |

Boundary: the contract is a new optional block `scope.footing_scope`, consumed only by `pricing/footings.py`. A scope without it takes the unchanged legacy path (byte-identical
results, asserted in `tests/test_footing_scope.py::LegacyDrift`, the negative controls and `evidence/drift_report.json`). Nothing here computes a price: `pricing/engine.py`,
the rate book, the quantity ruleset JSON and the workbook are byte-identical to Pass 6. The amendment changes **quantities** (M02, M17, M24, M40, D03, D04, D05, S01 for DP-001) and the engine
prices them exactly as before. No parallel pricing engine, no manual price override.

Files changed (Pass 6 -> here): `pricing/quantities.py` (footing branch), `engine/guards.py` (three hook lines), `engine/workflow.py` (digest, release package, qualification, placeholder skip),
`engine/ratebook_mode.py` (`footing_refresh`), `engine/integration.py` (additive `pricing.footing` view). New: `pricing/footings.py`, the schema, this document, the pin, tests and fixtures.

## 2. The scope block

```
scope.footing_scope = {
  schema_version: "footing-scope.v1",
  convention:     { id: "FSC-CONV-1:FACE_TO_FACE_NOMINAL", statement, evidence[] },
  classes: { <CLASS_ID>: { fence_type: "A"|"B", role: "line"|"terminal"|"corner"|"gate",
                           diameter_in: FACT, depth_in: FACT, post_od_in?: FACT } },
  runs: [ { run_id, corner_class? | end_class?, line_class, gate_classes?: { <gate_id>: <CLASS_ID> },
            layout: { kind: "closed_polygon"|"open_line",
                      sides: [ { side_id, length_lf: FACT, gates?: [ { gate_id, instance, station_ft: FACT } ] } ] } } ]
}
FACT = { value, status: confirmed|inferred|human_resolved|unresolved, evidence[] }       (the existing scope fact)
```

Every number is an ordinary scope fact. The existing Scope Gate therefore already: asks a named human about each unresolved one (`MISSING_VALUE`), requires approval of each inferred one
(`INFERRED_FACT_UNAPPROVED`), records the approver and carries the assumption into the qualifications; and any change bumps `scope_version`, voiding the crew plan, the wage decision and
Release. Rules enforced fail-closed (`SCOPE_INVALID` / `INVALID_VALUE` / `GEOMETRY_INVALID`): the schema; **every** fence run covered (an uncovered run would silently keep the single-footing
model); every gate mapped to its own class of role `gate`, with its post size stated even if unresolved (no default, no borrowing a neighbouring class); every gate location placed exactly once; a closed run has one side per corner; sides add up to the run length; a gate may not run to a
side's end or into another gate (its post would coincide with another post); a project-wide footing fact may not coexist with a `footing_scope`.

Mapping of the required representation to fields:

| Requirement | Field (schedule record) |
|---|---|
| Bid scenario identity | `scenario` (BASE / ALT-*), schedule per scenario |
| Fence run identity / fence type | `run_id`, `fence_type` |
| Post class / quantity | `post_class`, `quantity` (None = not countable; `quantity_known_minimum`) |
| Footing diameter / depth, units | `diameter_in`, `depth_in`, `dimension_uom: "in"`, `uom: "EA"` |
| Measurement convention | `measurement_convention: FSC-CONV-1:FACE_TO_FACE_NOMINAL` |
| Supporting document reference | `source_refs[]` = `{fact_path, doc_id, doc_revision, page, sheet_label}` per input |
| Documented / calculated / provisional / assumed / unresolved | `value_basis` (worst input: unresolved > provisional > assumed > calculated; a directly stated dimension is `documented`) |
| Review / approval state | `review.state` (NOT_REQUIRED / QUALIFIED_BY_NAMED_HUMAN / AWAITING_REVIEW / BLOCKED_UNRESOLVED) + `review.approvals[]` (who, exception, scope version) |
| Source version / calculation identity | `calc_inputs_sha256`, `schedule_sha256`, `calc_version`, `scope_version`; bound into `proposal_digest` |

## 3. Calculation (`footing-calc.v1`)

* **Physical posts** are created once each: corners (one per corner, shared by the two sides that meet there), two free ends per open run, two posts per gate location (a 12 ft double-leaf
  gate has two posts, Addendum 01 item 1.4), and line posts. Each post has one `post_id`, one class and one owner (`RUN:<run>` or `GATE:<gate>`). Runs with `repeat` are enumerated per repeat.
  The ownership audit asserts unique ids, one class/owner each, footings = posts = holes.
* **Segments**: a side is cut at its gate openings. A gate occupies `station ± clear_width/2` (face to face; the convention applies **no** post-center offset). Segment length = distance between the
  bounding fixed posts. Line posts = `max(0, ceil(round(L/s, 6)) - 1)` per segment with `s` = the run's maximum on-center spacing (32 31 13 3.1.B), equal spacing. **Each segment rounds up on its own.**
* **Convention sensitivity**: a real gate post sits half a post diameter outside the opening. The count is re-evaluated with a gate-side offset up to 0.5 ft (more than half the largest catalog post);
  if any count changes, it is flagged `COUNT_SENSITIVE_TO_POST_OFFSET` and never `bid_ready`. For DP-001 no count changes (Base 43, Alternate 35).
* **Concrete**: `count × π × (d/2)² × depth / 46,656` CU YD per class (exact volume × count, rounded once to 6 decimals), summed per run into M40 (and D05) with the existing
  overage/order-quantity policy applied by the unchanged engine. Core drilling: one S01 unit and one D04 hole per post.
* **Unknown is not zero.** An unresolved dimension makes that class's concrete `None`; an unresolved gate width or station makes the adjacent segments' line posts `None` (the known minimum is reported
  separately). Unknown quantities propagate as unresolved items, so `pricing.engine` refuses to price (`UNRESOLVED_QUANTITY`) — the engine is not given a number to price.
* **Single ownership of gate posts and footings.** A gate's two posts, footings and holes belong to its gate class and are costed once through the ordinary lines (M01 post, M40 concrete, S01
  drilling, D03/D04 labor drivers). No gate-leaf item (M21, M22, M28–M37, M43, M44, D09) contains a post, footing, concrete or drilling item (asserted); the gate EACH pay item is a presentation
  of those lines, not a second charge. Type B posts price at M03/M04, Type A at M01/M02; a gate class must state its post size (even if unresolved) and has role `gate`; a gate may not map to a corner/terminal/line class, and no two gates share a class; a gate post is M01 only when its stated size equals the run's terminals.
* **G3 is never defaulted.** `GATE_G3` has `diameter_in`, `depth_in` and `post_od_in` unresolved. The documents cut both ways — F502 note 4 and the G3 schedule say "SEE NOTE 4" (not specified), while
  F502 note 5 and 32 31 13 3.2.D say gate footings "not otherwise noted" are as for terminal posts — and that is carried as evidence on the unresolved fact for an estimator's decision (RFI), not applied
  by code. A named human may enter values at the Scope Gate; they are then `assumed` and carried through price, qualifications and release as a qualified demonstration.

## 4. Release posture

| `posture.release_class` | Meaning |
|---|---|
| `NOT_PRICEABLE_PARTIAL_UNRECONCILED` | a count or dimension is unresolved. No estimate, no digest, no release. `partial_cost.known_subtotal` (post material, M40, S01 of the KNOWN classes only, with the engine's own order-quantity rounding) is informational: `is_estimate: false`, `label: PARTIAL_UNRECONCILED`; unknown classes are listed under `unknown_exposure` with unit rates and **no invented quantity or dollar**. |
| `QUALIFIED_DEMONSTRATION_ONLY_NOT_BID_READY` | everything is known but some input is provisional or a human assumption. A fictional qualified release can be demonstrated; the release package carries `bid_ready: false`, `footing_release_class`, the full schedule and a `footing_scope_not_bid_ready` qualification. |
| `BID_READY` | every input is documented and no count is convention-sensitive. (Never the case for DP-001 today.) |

**For DP-001: PRICING: NO-GO; BID RELEASE: NOT SUBMITTABLE.** Acknowledging the advisory (`FOOTING_SCOPE_NOT_BID_READY`) does not change the posture: it is not resolvable.

## 5. Authority and stale-decision detection

* `proposal_digest` now also binds `footing = {scenario: schedule_sha256}` (only when a footing scope exists); the digest therefore changes when any count, class, dimension, assumption, convention or the
  calculation version changes. The unchanged `scope_sha256` already covers the stored scope.
* A change to any footing or count input goes through the existing paths — `scope/resolve` (typed value on an unresolved fact), `revise_scope` (addendum) — each bumping `scope_version` and voiding
  the crew plan, wage decision, Labor decision and Release (tested: dimension revision, count-input revision, G3 assumption revision). Wage, fleet-only, idempotency, preview-limit, historical-authority and
  duplicate-wage-row protections are untouched (full safe suite and the independent HTTP harness pass).
* Quantity items carry `[footing-scope.v1 schedule <sha12>]` in `calculation_method` and the footing fact paths in `source_evidence_refs`; approvals are recorded in `approved_resolutions`.

## 6. Exceptions

Blocking: `SCOPE_INVALID`, `INVALID_VALUE`, `GEOMETRY_INVALID` (shape/values/geometry), `MISSING_VALUE` (unresolved footing/width/station facts), `INFERRED_FACT_UNAPPROVED`, `NO_PRICING_MAPPING`
(gate-post size differs from the run's terminals — mixed post sizes in one run are not modeled), `FOOTING_SCHEDULE_UNRELIABLE` (ownership audit failed). Advisory: `FOOTING_SCOPE_NOT_BID_READY`.

## 7. Known limitations and open decisions

1. Segment geometry for DP-001 is **provisional**: the gate stations are a human reading of the C101 dimension chain (31 / 38 / 107 and 31 / 38 / 69), G3's location is "symbol only, not to scale",
   the sides and the Type B length are human-prepared. Counts 79 / 63 are conditional on that geometry and on the self-declared G3 opening (12 ft). They cannot become `confirmed` until a named reviewer
   confirms segment endpoints against the CAD.
2. Post-center offset is bounded (0.5 ft), not modeled; real offsets need the gate post OD, which is unknown for G3.
3. The rate book has **one** core-drilling rate per hole (S01) and one concrete rate (M40); it has no diameter-specific drilling rate. If the contractor prices 16 in cores differently from 8 in cores, that needs a
   rate-book change (outside this amendment).
4. The footing calculation is code (independently reviewed), not an estimator-approved rule; the quantity ruleset (`IFI-QTY-RULES 1.2.0`) is unchanged, still `draft_pending_estimator_review`,
   `contractor_approved: false`.
5. HTTP: no route revises a recorded assumption except `scope/resolve` on an unresolved fact and (not yet exposed) `revise_scope`; the addendum route remains 501 in the adapter. State, ledger and limiter remain in memory.
6. `workflow.release()` still allows a *qualified demonstration* release; the posture is explicit in the package and the response qualifications. Whether the backend should refuse any release while `bid_ready` is
   false is a policy decision left to the owner (current behavior follows the "fictional qualified release may remain available for demonstration" instruction).
7. Contract approval, authenticated identity, shared limiter and persistence remain open as in Pass 6.

## 8. Unit metadata (independent audit repair) and release-response fields

**Units.** Every authoritative unit-bearing fact may omit `unit`; if it declares one it must equal the field's exact, case-sensitive unit, and nothing is ever converted:
`classes.*.{diameter_in, depth_in, post_od_in}` = `in`; `runs[].layout.sides[].length_lf` and `fence_runs[].length_lf` = `ft` or `lf`; `gates[].station_ft`, `fence_runs[].section_spacing_ft`,
`gates[].clear_width_ft` = `ft`. Fact metadata is a closed set (`value, status, evidence, inference_note, unit, open_question, price_affecting`); any other key on a footing-scope fact is rejected, and the
schema closes the `convention` object, so counts, concrete and drilling quantities can never be supplied. Violations are blocking exception `FOOTING_UNIT_INVALID` (message prefix `FOOTING_UNIT_INVALID:`),
raised before any calculation, schedule, identity or digest (`footings.evaluate` also refuses a direct call with `ValueError`), including on the `scope/resolve` and `revise_scope` paths (state untouched). Legacy scopes (no `footing_scope`) are not subject to it.

**Release response (additive, footing-scope projects only).** `POST /projects/{id}/release` now also returns, copied from the released package (never from the request): `bid_ready` (bool),
`release_class` (`BID_READY` | `QUALIFIED_DEMONSTRATION_ONLY_NOT_BID_READY`), `artifact_kind` (`SUBMIT_READY_BID` | `QUALIFIED_FICTIONAL_DEMONSTRATION`) and `footing_release_class` per scenario. Legacy responses keep exactly
their previous keys. A client must read `bid_ready`; HTTP 200 alone never means submit-ready. Release has no replay route in Pass 6 (a second release is refused 409 and changes nothing); that, and release eligibility, are unchanged.

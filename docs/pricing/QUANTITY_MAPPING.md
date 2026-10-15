# Quantity mapping: takeoff output to stable rate-book keys

Implemented in [`pricing/quantities.py`](../../pricing/quantities.py); every divisor, spacing and per-leaf count is a visible parameter in [`pricing/data/quantity_rules.v1.json`](../../pricing/data/quantity_rules.v1.json) (ruleset `IFI-QTY-RULES` v1.0.0, sha256 `40e3c4a4a79464063e3fc8a49962bfe9a4961ec34159a9c39fad587dc284a4ce`).

**The ruleset ships as a DRAFT.** Counts that come straight from the deterministic takeoff (posts, braces, lengths, gates, windscreen) are the engine's existing, tested logic. The fitting and hardware counts (bands, ties, caps, sleeves, hinges, end cups) are written from the catalog text of each item and have not been reviewed by an estimator. No price is released until a named estimator approves **that exact file** at the Scope Gate (`QUANTITY_RULESET_UNAPPROVED`); editing the file voids the approval.

The rules were written from the catalog description of each item. They are derived from the catalog text only and are an unapproved draft until a named estimator approves the exact file.

## Reconciliation points

| Concern | Rule |
|---|---|
| Type A vs Type B posts | Family chosen by (terminal OD, line OD): A = 2-7/8 / 2-3/8 → M01, M02; B = 2-3/8 / 1-7/8 or 1.900 → M03, M04. Any other pair is `NO_FAMILY_MAPPING` and blocks every family-dependent item. |
| Gross vs net length | Gross = run length (D12 layout, M05 rail). Net = gross − gate openings (D01/D02 by family, D07, D11, M23, M19/M20 fabric). |
| Continuous top rail vs net fabric | **M05 / D06 = gross when the drawings say the rail is continuous across gate openings**, net otherwise, and **unresolved if the drawings do not say** (fact `top_rail_continuous_across_gate_openings`). See below. |
| Fabric at each height | M19 = 120 in (10 ft) and M20 = 42 in (3.5 ft). A run height with no catalog fabric is unresolved, never substituted. |
| Gates, headers, transoms | Leaves by `gate_kind` (single = 1, double = 2; anything else unresolved). M21 leaf fabric and M35 header rail = clear width × gates; M22 transom fabric where run height − gate height > 0, only if it equals the 3 ft catalog transom. Frame pipe/elbows/tees/truss/hinges/stops/tension bars per leaf; one latch per gate. |
| Hardware and fittings | Caps by post OD (M16–M18); tension bars one per fabric termination (free ends + 2 per corner + 2 per gate), bands per bar by fabric height; ties by post and by rail/wire spacing; rail sleeves per stick length; rail end cups per rail line per termination (a continuous top rail has none at gate posts). |
| Bracing | M08/D08 = brace assemblies from the takeoff (height ≥ 6 ft); M09/M10 = 2 + 2 bands per brace by post OD. The brace rail is the mid rail (M06), so it is **not** added again. |
| Footings and concrete | D04 = one hole per post. **M40 and D05 in cubic yards** = π(d/2)² × depth × posts ÷ 46 656, from footing facts in the documents. If the documents do not give them the quantity is unresolved. M40 is the only concrete item; M41 is retired. |
| Windscreen | M38/D10 as scheduled (9 ft catalog height; other heights unresolved); M39 cable ties = one per grommet, top and bottom. |
| Labor drivers | D01–D12 as in the table below. |
| Base bid vs alternate | A payload is one **complete** scenario (`scope_ref` `BASE` or `ALT-*`), not a delta. The rate book's `alternate_id` selects the `_alt` equipment/mobilization columns; an alternate the book has no columns for is `ALTERNATE_NOT_IN_RATEBOOK`. Once an alternate is selected through the Scope Gate its patch is applied to the working scope and BASE is no longer recoverable; it is omitted, not invented. |

| Driver | Meaning | Source |
|---|---|---|
| D01 / D02 | Type A / Type B net fence LF | net length by family |
| D03 / D04 | posts to set / holes to drill | takeoff terminals + line posts |
| D05 | concrete placed (CU YD) | = M40 quantity before overage |
| D06 | top rail to install | = M05 |
| D07 | fabric to hang | net LF, all runs |
| D08 | braces | takeoff brace assemblies |
| D09 | gates to hang | Σ gate quantity |
| D10 / D11 | windscreen / tension wire | M38 / net LF |
| D12 | layout length | gross run length |

## The M05 / D06 top-rail investigation

Sizing the top rail (M05, D06) as net fabric LF would understate it. The issued drawings state that the top rail runs continuously across gate openings, so the rail is longer than the fabric by exactly the total opening width. The pricing integration now computes:

* rail LF = gross run length when the drawings so state (a scope fact with a citation), net length when they say it stops, **unresolved when they say nothing**;
* mid rail (M06) stays net: the 7 ft gate leaf occupies the 5 ft mid-rail elevation, so a mid rail cannot cross the opening. The rule is geometric (rail crosses an opening only if the leaf is not taller than the rail elevation), not a copy of the top-rail answer;
* header rail (M35) is a different member at the gate head and is not netted against the top rail.

Tested in `tests/test_quantities.py` (`test_gross_versus_net_and_the_top_rail`, `test_top_rail_follows_the_drawing_note_not_an_assumption`): rail − net fabric equals the opening total.

## Status semantics

`confirmed`: every input is confirmed or human-resolved. `provisional`: an input is only inferred. `unresolved`: an input is missing; quantity is `null`. Only `confirmed`, or `provisional` carrying a recorded human resolution, can be priced. A quantity that does not depend on an unresolved fact stays confirmed (the gross top rail does not depend on G3's width; the fabric and posts do).

## Gaps the catalog cannot price (reported, not dropped)

Runs that are not chain link and a required core-drilling scope (no catalog quantity exists for it); Fence guard and any accessory other than windscreen (`NO_ITEM_MAPPING`); gate kinds other than single/double swing; fabric, transom, leaf or windscreen heights outside the catalog; post sizes outside the two families. Each blocks at the Scope Gate until the catalog or the scope changes.

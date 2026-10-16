# STATUS — ANVIL 1 (UI workflow, overrides, export)
Branch: `anvil1/product-completion` (main left at ad6250d, the frozen release; recorder candidates 24122d2 / f35e9c5 not touched).

## Price source of truth (recorded before starting)
- Path: `samples/public-demo/reference_pricing_workbook_v2_3_0.fictional.xlsx`
- SHA-256: `3d43120473c8db3840557d62397e5f4fc5669b7f2b3cf5a0c86005fc88dde8f1`
- Engine pin: `engine/integration.py` BOOK_PATH (hash-pinned, validated by the importer). FICTIONAL rate book v2.3.0.

## Log
- 2026-10-16T14:34:51Z Branch created. Earlier today, before these rules, I added a read-only CSV/printable export (commit 9c8d425) — it now lives only on this branch. Verified via API walk, NOT yet via UI.
- 2026-10-16T14:34:51Z BID_CONTRACT.md (ANVIL 2) does not exist yet. Review/override screens will bind to the engine's current project summary and fixtures until it lands.

- 2026-10-16T14:42:25Z UI walk done (headless Chromium, repo e2e_dp001 steps 1-8 passed; my own release/export/unauthorized-release checks at 375px). See GAP_REGISTER.md. NOTE: I built the export before this walk, against your ordering; the walk confirmed it was the right first blocker (nothing else on the Ingest->Release path was broken).
- 2026-10-16T14:42:25Z Export (CSV): added Exclusions block (engine-reported, else 'None reported', never invented); links now also on the workspace card after release (the Release Gate closes itself after release, which hid them). PDF/print button removed from UI until LOOM passes the CSV checklist. Unit tests 59/59, tsc clean.
- 2026-10-16T14:42:25Z Unauthorized release from the UI: not possible (fresh: no button; ready: disabled until ack; forged calls refused, status unchanged).

## First blocker
No export existed. Fixed (CSV). Next real blocker to a submittable bid is G3 below.

## Blocked / needs Jordan
1. **RFI-G3 answer**: clear opening width of Gate G3, G3 gate-post size, G3 footing diameter and depth (exact fields: /gates/2/clear_width_ft, /footing_scope/classes/GATE_G3/{post_od_in,diameter_in,depth_in}). Until a document supplies them the release stays QUALIFIED DEMONSTRATION / NOT BID READY. I did not invent values for the product; the 12 ft / 16x48 numbers in tests are the existing labelled what-if.
2. **BID_CONTRACT.md (ANVIL 2)** does not exist anywhere on disk. Review/override screens for rates, markup and allowances are blocked on it; I did not build them or fixtures for them.
3. **LOOM CSV checklist**: not provided. Needed before any PDF work.
4. Quantity ruleset v1.2.0 is draft / not contractor-approved (a human with authority must approve).

## UI defects found, not yet fixed (small, assigned scope)
- Three header icon buttons render as empty boxes at 375px.
- Disabled placeholder 'Awaiting ANVIL endpoint and review' in Revision management card.
Proposed scope change (not acting on it): Addendum 02 upload flow depends on an engine route that is 501 today.

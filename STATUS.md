# STATUS — ANVIL 1 (UI workflow, overrides, export)
Branch: `anvil1/product-completion` (main left at ad6250d, the frozen release; recorder candidates 24122d2 / f35e9c5 not touched).

## Price source of truth (recorded before starting)
- Path: `samples/public-demo/reference_pricing_workbook_v2_3_0.fictional.xlsx`
- SHA-256: `3d43120473c8db3840557d62397e5f4fc5669b7f2b3cf5a0c86005fc88dde8f1`
- Engine pin: `engine/integration.py` BOOK_PATH (hash-pinned, validated by the importer). FICTIONAL rate book v2.3.0.

## Log
- 2026-10-16T14:34:51Z Branch created. Earlier today, before these rules, I added a read-only CSV/printable export (commit 9c8d425) — it now lives only on this branch. Verified via API walk, NOT yet via UI.
- 2026-10-16T14:34:51Z BID_CONTRACT.md (ANVIL 2) does not exist yet. Review/override screens will bind to the engine's current project summary and fixtures until it lands.

## Blocked / needs Jordan
- (none yet)

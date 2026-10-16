# GAP REGISTER — DP-001 operator workflow
Method: real UI, headless Chromium (Playwright) against a local production build, 375px viewport for mobile checks. Not test names: each row was observed on screen.
Tested at: branch `anvil1/product-completion`; baseline release untouched. Frozen release (demo-lock) was not modified.
Price source: `samples/public-demo/reference_pricing_workbook_v2_3_0.fictional.xlsx` (hash in STATUS.md). All identities are self-declared demo names.

| # | Step / screen | Rating | What I saw |
|---|---|---|---|
| 1 | Ingest: open DP-001, document package | WORKS | 4 registered documents, hashes match manifest, viewer opens G001/C101/C102/F501/F502, manual, ITB, Addendum 01. |
| 2 | Scope Gate: G2 / G3 | WORKS | G2 shows Addendum 01 controlling (12 ft double-leaf, Rev 0 superseded). G3 stays blocking with a visible RFI; Addendum 01 s1.5 post/footing facts are shown as supplied, no RFI for them. |
| 3 | Takeoff review | WORKS | Source-linked quantities, per-class footings, reviewer attestation bound to scope version + digest. |
| 4 | Price (labor, wage, crew plan) | WORKS | Wage form, crew plan preview, total matches release gate (Base 55,513.85; Alt A-1 46,784.77). |
| 5 | Price: edit unit prices / markup / allowances | MISSING | Rates come from the rate book. No screen edits them. Blocked on BID_CONTRACT.md (see STATUS). |
| 6 | Assemble Base vs Alt A-1 | PARTIAL | Each is its own project/scenario with its own digest. Alt shown as a separate total, never added. No combined view; not requested. |
| 7 | Authorize / release | WORKS | Named approval + takeoff review + explicit qualification acknowledgement. Scope change after approval voids crew plan and digest (observed). |
| 8 | Unauthorized release from UI | WORKS (cannot happen) | Fresh project: no release button. Ready project: button disabled until acknowledged. Forged calls (no takeoff ack, wrong digest, `bid_ready` flag) -> 409/409/400, status unchanged. |
| 9 | Export CSV | WORKS (added) | Download from Release Gate and from the workspace card after release. Base/Alt, exclusions, holds, qualifications, totals, authorization stamp. Total equals engine to the cent. Awaiting LOOM checklist. |
| 10 | Export PDF | NOT STARTED (by rule) | Held until CSV passes LOOM's checklist. Print button removed from UI. |
| 11 | Mobile 375px | PARTIAL | Measured no horizontal overflow (scrollWidth 375) on the home page and the export page; the Release Gate dialog was viewed in a screenshot but its width was not measured. Three header icon buttons render as empty boxes at 375px. |
| 12 | Workspace "Revision management" card | PARTIAL | Contains a disabled placeholder "Awaiting ANVIL endpoint and review" (Addendum 02). Not functional. |

## First blocker (before this branch)
There was no export: `GET /proposal` was 501 and the app had no download. Everything up to Release already worked. Fixed on this branch (CSV).

## Remaining blockers for "a GC produces the bid"
1. G3 is genuinely unresolved (clear opening width, post and footing size). The release is, by engine policy, QUALIFIED DEMONSTRATION ONLY / NOT BID READY and the export says so. Needs the RFI-G3 answer.
2. Rate/markup override screens need BID_CONTRACT.md (does not exist yet).
3. Quantity ruleset is draft and not contractor-approved; the export states this.

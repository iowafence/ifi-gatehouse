# Verification record

Everything here is fictional demo data. This file records how the build was checked, what the checkers found, and what we did about each finding. It cites tags, a tree hash and an image digest, not commit hashes (see [HISTORY.md](HISTORY.md) for why).

**Build under test:** tag `gatehouse-ui-final-4`, tree `00cc3b0ef5fc85dc01a0a8adfcc3d9385c7b4dfa`, image digest `sha256:16bf4a536d23c52f0d8110634a5ad611dd03aaeae0b8f0523804b6a63483d548`.

## Who checked what

- **Engine and web tests** (in this repository): 773 passed, 0 failed, 3 skipped (PDF-indexing tests that need PyMuPDF, which was not installed in the test environment); web 144 of 144 on the build workstation; 141 passed and 3 skipped on a clean checkout (three Evolus audit tests need local evidence folders that are not in this repository); TypeScript clean; repository policy checks 16.
- **LOOM**, an independent AI verifier that built a private answer key from the pinned workbook and compared it with the engine's output.
- **ANVIL 2**, a read-only AI auditor that re-checked claims, ran real-browser click paths, and adjudicated LOOM's findings.

The verifier saw some engine figures earlier, so the numeric check is **not blind verification**.

## Numeric verification

| Plan | Engine total | Labor | Match to key |
|---|---|---|---|
| CR13 Base | $63,257.38 | $14,176.07 | To the cent |
| CR13 Alternate A-1 | $54,398.76 | n/a | To the cent |
| CR14 Base | $66,879.97 | $17,039.77 | To the cent |
| CR14 Alternate A-1 | $57,405.40 | n/a | To the cent |

224 priced lines and 28 allocation comparisons were checked. Allocation (ALLOC-V1) rounding differences against the engine were +$1.72, +$1.15, +$0.01 and -$1.03, and matched the key. The match was re-confirmed on each of the later builds below.

Pinned inputs: workbook `reference_pricing_workbook_v2_3_0.fictional.xlsx` (SHA-256 begins `3d43120473c8`), ruleset IFI-QTY-RULES 1.2.1 (fingerprint `1845b6b0df7ad826685738fb85bf33b72016adb4e424e387548a9666d830ec4d`), wage decision FDB-DP001 mod 0 (fictional).

## Findings and dispositions

| # | Source | Finding | Disposition | Reason |
|---|---|---|---|---|
| 1 | LOOM first pass | Official pass invalid (driver timeout, no CR14 transcript, claims unsupported) | Discarded, redone | The report overstated what its transcript showed |
| 2 | LOOM | Layout control overlapped by the CSV link at 375 px | By design | The Release Gate is a full-screen dialog and Layout sits behind it; after Close, 5 of 5 points hit Layout and a real click opens its menu |
| 3 | LOOM | Tag-B sentence and "outlined =" wording not captured | Not a defect | Present; LOOM did not expand the list or open the viewer |
| 4 | LOOM | 32-count not in the AI drawer | Not a defect | The count is on the Scope Gate findings card; the drawer lists attempts |
| 5 | LOOM | Scope Gate lacks a NOT BID READY / FICTIONAL block | Roadmap | The Scope Gate has no price and carries the synthetic-scope label and the fictional-site notice; the block shows on Labor, Release and Takeoff Review |
| 6 | LOOM | "A model read the G3 gate symbol" overstates a model reading | Fixed | The word is now "claimed" (the symbol crop clips the symbol); 0 hits of the old string, verified by both checkers |
| 7 | LOOM | Different-PDF hold | Passed | HELD PARSE UNAVAILABLE, no PROPOSED result |
| 8 | LOOM | Typed G3 first | Passed | HELD UNVERIFIED EVIDENCE; Reset present |
| 9 | LOOM | Geometry dead end not completed | Driver only | The "Decide this gate" button selects the first item; 158 of 158 real clicks switched the form correctly. ANVIL 2 completed the dead end itself. Verified by ANVIL 2, not LOOM |
| 10 | ANVIL 2 | Gate dialogs set aria-modal="false" and have no focus trap | Roadmap, disclosed | The fix touches focus handling in every gate; no accessibility conformance is claimed |
| 11 | ANVIL 2 | "Decide this gate (N)" reads like a gate-level action but selects one item | Roadmap | Renaming breaks verification scripts that select by that text |
| 12 | Plan | An early draft said the engine passes 776 tests | Corrected | 773 passed, 0 failed, 3 skipped; web 144 of 144 on the build workstation; 141 passed and 3 skipped on a clean checkout (three Evolus audit tests need local evidence folders that are not in this repository) |
| 13 | ANVIL 2 | The owner's full name appeared in demo constants, fixtures, tests and 17 export lines | Fixed | Replaced with the first name; 0 hits across tree, exports, API responses and image |
| 14 | ANVIL 2 | Ruleset fingerprint changed with finding 13 | Disclosed | Only a note in the rules file changed; the ruleset id and version label are unchanged; no rate or quantity changed. The fingerprint is now `1845b6b0df7ad826685738fb85bf33b72016adb4e424e387548a9666d830ec4d`, and the earlier value is superseded and not used anywhere in this repository |
| 15 | ANVIL 2 | `demo/snapshot.py --verify` failed (drifted source files) | Fixed at release | The manifest is regenerated as the last step before publishing |
| 16 | LOOM | Fingerprint check reported a mismatch | Check mis-specified | Our check could not see the value; ANVIL 2 verified the pin equals the live fingerprint |
| 17 | ANVIL 2 | The Flight Recorder trace pinned a stale ledger hash (`1faf2c2f…`), failing a test and `flight_trace --check` | Fixed | Now `667e3530671cacdb91e88c0dbbaba5271ed6c6e64d17497acba0a6b982d77592`, which equals the SHA-256 of `dp001/ai_findings.json`; the only change in that build |

## Verification of the final build

- ANVIL 2: the diff against the previous build changes only the Flight Recorder trace (two hash lines). The 170 mapped source files in the image are identical to the tag; the exports differ only in timestamp, digest and id lines; all totals match; the image runs as uid 10001 with a read-only root filesystem and read-only evidence; all 8 baked evidence hashes match; the surname count is 0.
- LOOM: all four plan totals and both labor totals match the private key to the cent; the G3 sentence reads "A model claimed" with 0 hits of the old wording; the release blocks and the CSV export button were captured.

## Not exercised on the final build

Per-item ALLOC-V1 fields (matched on an earlier build; the engine layers are unchanged), and typed-G3-first by LOOM's walker (passed on an earlier build; later changes cannot affect that path).

## Build gatehouse-ui-final-5: live Evolus Bid Desk (added after final-4; the final-4 record above is unchanged)

This section describes the build that follows `gatehouse-ui-final-4`. The tag `gatehouse-ui-final-5` is created later; its image digest and the image-level checks below are recorded when the image is built.

**What changed.** The Bid Desk can use a live Evolus conversation (server-side connector `web/lib/evolus-desk.ts`, switched on by `EVOLUS_DESK_ENABLED=1`). Otherwise it is the built-in deterministic desk, labelled SIMULATED. Every reply is labelled LIVE, SIMULATED or UNAVAILABLE. The model shown is the configured model; replies do not report which model answered. Replies are explanatory text, not audit records, and change nothing. Evolus is configured with Gemma-4-31B-IT on the AMD Token Factory (configuration). The Addendum 02 parse is still a replay of one real AMD call.

**What did not change.** `git diff 502c599b HEAD` is empty for `pricing`, `engine`, `intake`, `api`, `evidence`, `release_evidence`, `dp001`, `hosting/captures`, `samples` and `amd_bridge`. The ruleset fingerprint is still `1845b6b0df7ad826685738fb85bf33b72016adb4e424e387548a9666d830ec4d`. The connector has no engine write path; it receives a bounded read-only CONTEXT built from engine state (no reviewer names, notes, session ids or document text) and its replies are checked before they are shown. A figure not in CONTEXT withholds that sentence. A reply claiming an action, an approval, acceptance, verification, resolution or release that the engine state does not support, or stating a G3 dimension that is not a G3 fact, is withheld whole and shown as UNAVAILABLE with the built-in answer labelled SIMULATED. The per-turn instruction says to reply in English only, and a reply whose prose is not English is withheld the same way (fail closed: the claim and figure checks are written for English wording; identifiers, abbreviations and proper nouns are not counted either way). G3 dimensions are checked against the G3 values the project holds (an accepted addendum, or a self-declared assumption), not against any number in the project, and a value that a PROPOSED addendum only states is treated as a document value, not an accepted fact.

**Crew totals.** After the wage is verified, the whole-bid total for each eligible crew comes from the existing read-only crew-plan preview (the same calculation the Labor Gate uses), cached by project, scope, wage, plan and difficulty state. The Bid Desk lists eligible crews with those totals and the disqualified crews with the engine's reasons; it does not select or recommend a crew. The preview is the only engine call with a write method that the Bid Desk can reach.

**Tests in this repository.** Python 773 passed, 0 failed, 3 skipped (unchanged); web 180 of 180 on the build workstation, 177 passed and 3 skipped on a clean checkout; TypeScript clean; repository policy 16. The new connector tests (`web/test/evolus-desk.test.mts`) use a mock transport only: flag off makes no outbound call; a successful reply is LIVE with the configured model; timeout, 401, 429, 5xx and unreadable replies are UNAVAILABLE with the built-in answer after them; the daily caps; the output filters; no reviewer name, note or session id in the outgoing payload; the base-URL allowlist; credentials never in a response; the conversation id never leaves the server.

**Not yet verified for this build.** The image has not been built, and no live Evolus call has been made from Gatehouse in these tests. Live behaviour (Evolus latency, the wording of real replies, how often the filters withhold) is verified separately, on a built image, against a local stub and then the real service.

**Documentary facts not available in structured state.** Addendum 02's 84 in gate height and its Detail 3/F501 footing reference are in the PDF text only. The engine's proposed or accepted addendum record holds the 4 ft opening and "post and footing same as G1" (2.875 in OD, 16 in diameter, 48 in depth once accepted), so the Bid Desk can state those and cannot state the height or the detail reference; the connector withholds a G3 dimension it cannot bind to state.

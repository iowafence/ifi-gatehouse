# LOOM final independent re-check

**Verdict: FAIL — judge publication blocked.** The remediation improves separation and attribution in the running recorder, and it correctly keeps D2 out of the active shortlist. Two material problems remain: the audit treats G2-only Addendum language as resolving G3 post size, and a modified audit can pass runtime verification and clear D2 as actionable.

This is LOOM's own re-check from the local source documents, run package, cases, receipts, traces, audit record, implementation, and running local Flight Recorder. It is not a relayed report, human decision, RFI approval, or bid release.

## Controlling-document reading

I independently extracted the cited pages from the hash-identified PDFs in `dp001/documents/` and checked the source hashes against `dp001/document_registry.json`.

- **G3 post outside diameter: unresolved; keep a narrow post-size clarification open.** Specification 32 31 13 §2.1.B says the general Type A gate posts are 2.875 in OD, but expressly qualifies G3: “gate posts for G3: size confirmed with the opening width.” F502 note 4 says G3 post size is not specified and cites §2.1.B. Addendum 01 item 2.2 says it does not establish G3's clear opening width. The submitted documents therefore do not state a final G3 OD independently of resolving the opening width.
- **Addendum 01 item 1.5 is scoped to G2.** Its parent heading is “ITEM 1 GATE G2 REVISED”; items 1.1–1.4 expressly revise G2, item 1.5 continues that same change, and item 1.6 again names G2. Item 1.5 establishes the unchanged post/footing for the G2 revision. The addendum's precedence clause does not extend a G2-specific direction to G3. Its 2.875 in statement must not be presented as a determination of G3 post OD.
- **G3 footing detail and dimensions are provided by the G3 drawing cross-references.** F502 detail 3 calls for a core-drilled terminal/gate footing at 3/F501; F502 note 5 and specification §3.2.D give the terminal-post fallback for gate posts/footings not otherwise noted. The G3 detail says its fabric matches Type A. F501's Type A terminal/gate schedule gives a minimum footing of 1'-4" diameter × 4'-0" deep. The G3 schedule's “see note 4” reference is imprecise because note 4 concerns width and post size, but the same G3 detail also points expressly to 3/F501 and the general fallback points there. I find no basis to keep G3 footing diameter/depth on the RFI missing-requirements list on this record.
- **Recommended case treatment:** retain the original D2 as flagged historical AI output, but replace its rationale with the distinction above. A narrower clarification concerning G3 post OD may remain pending design-team direction; remove footing dimensions from that request. Do not treat the current audit's Addendum 1.5 citation as resolving G3 post OD.

Relevant authentic text checked:

| Source | Text / effect | SHA-256 |
|---|---|---|
| Addendum 01 item 1.1 | Revises G2 from 6'-0" single leaf to 12'-0" double leaf | `390ffe093029fb89a9e498da4ba4e46f5600690bc05ecc7717c91607fc185deb` |
| Addendum 01 item 1.5 | G2-context post/footing unchanged; 2.875 in OD and terminal/gate footing, 3/F501 | same Addendum hash above |
| Addendum 01 item 2.2 | Does not establish G3 clear opening width | same Addendum hash above |
| Project Manual §2.1.B, p. 14 | General Type A post sizes; G3 post size confirmed with opening width | `9fe8c8942c453ac911abeda54d5e9be64b1bd8186d1eeba08b527e8270d0377a` |
| Project Manual §3.2.D, p. 16 | Gate posts/footings not otherwise noted as terminal posts, Detail 3/F501 | same Project Manual hash above |
| F502 notes 4–5 and G3 detail/schedule, p. 5 | G3 width/post not specified; gate footing references 3/F501; general terminal/gate fallback | `62ab61d7f2558245f4a6f1708d9320a49e66fd28bf829a2329be5b79db9ac525` |
| F501 footing schedule, p. 4 | Type A terminal/gate minimum footing 1'-4" dia. × 4'-0" deep | same Drawings hash above |

The quoted Addendum language in the remediation audit is authentic and appears in the run package and source PDF. Its **application to G3** is the defect; quote authenticity does not establish scope.

## Audit and source integrity

- The new audit is correctly disclosed as `source.kind: relayed_report`; it says LOOM's report file was not available to ANVIL 1 and that the findings were relayed. It also says `is_human_decision: false` and `human_authorization.status: NONE_RECORDED`. This is honest attribution, not falsely represented as LOOM-authored by ANVIL 1.
- The audit's run binding matches `GH-RUN-e5bbcecef551` at SHA-256 `7a4cc958f821f18ce4679a6fee428148c91c39de6e9eaa3e27c50725fef70c4`; the successful trace binding matches `GH-TRACE-06b4b6d525133f8a` at `5aa339ec1bf7022ba98b505ba4ae6776c47aa9605870df24286ed21c0fe9bef8`. The D1 and D2 case hashes match `6e4319bc30b9f45092515492b6a4c99996856dc750e49236c73da45021984701` and `7f7f5001a90639eb4b2cb210462384bf146cfa60b8a444eb2ca98168f341ed7b` respectively. The run export is byte-identical to the source run record.
- Registry hashes match the stored PDF bytes for all cited documents. The audit's item 1.1, item 1.5, item 2.2, §2.1.B, §3.2.D, F501 and F502 quotations were independently found on the cited document pages. The audit's F501 Type A footing dimension quotation is genuine.
- The original run, cases, receipts and traces are outside the remediation commit's changed-file list; the commit adds the audit and changes reader/presentation code. Their examined current hashes are recorded below. No original evidence file was written by this re-check. The test run and UI inspection were read-only against the local project state.
- The six dropped scope entries are correctly characterized as human-prepared Alternate A-1 calculations/notes under `doc_id: human`, page 1, not PDF excerpts. There were no excerpt IDs because no registered source PDF existed for that pseudo-document. The builder's original reason code is generic. The remediation correctly preserves the original code while explaining this.
- No model-inference telemetry is invented in the trace or UI: the execution records AMD and Gemma as `NOT_REPORTED`; the model/provider are not claimed as execution facts. The earlier HTTP 400 is a distinct `FAILED` trace with no workflow execution ID or cases. Historical AMD observations remain in the separate historical section.

### Fail-closed check: failed

The actual audit loader checks schema, document registry references, run/trace/case hashes, and that evidence quotes match the run package. It computes and displays the current audit file hash, but has no trusted expected audit hash, signature, or other authentication of the audit's decision content.

I tested a temporary copy only: I changed the audit's I2 disposition from `FLAGGED_UNSUPPORTED_BY_CONTROLLING_EVIDENCE` to `SUPPORTED`, leaving all run, trace, case, document, and quote bindings intact. The reader accepted that altered audit and returned D2 as `SUPPORTED`, `actionable: true`. The source audit and cases were not modified. This directly disproves the requirement that a modified audit fail closed. Missing and structurally invalid audit cases do remain non-actionable in the implementation/tests, but a coherent edit to the assessment passes.

## Running judge presentation

The local recorder at `http://127.0.0.1:18230/` was inspected in Chromium using the existing read-only Evolus case E2E script. All six step groups passed. The display separates the original `COMPLETED_VALID` structural result, authentic citation checks, additive independent assessment, and human authorization. It shows D1 pending, unapproved and unsent; D2 in a separate flagged historical section and outside the active shortlist; the failed attempt as its own execution; and historical model observations separately. The E2E confirmed no non-GET recorder requests, no external calls during recorder use, and no project-record or pricing-total changes.

The presentation keeps the original D2 question and missing-requirements list visible, properly labeled as AI-stated. However, its independent assessment repeats the overbroad G2 item 1.5 rationale and does not provide a clear final statement that G3 post OD still needs design-team clarification while the footing dimensions are shown in F501. A judge could mistake “flagged” for “G3 post size resolved.” The current display therefore needs a corrected, scoped assessment before publication.

## Minimum corrections before publication

1. Reissue the additive audit assessment so it treats Addendum 01 item 1.5 as G2-only, preserves G3 post OD as unresolved, and states the F502/F501 footing detail and Type A minimum dimensions. Retain D2 as historical/flagged; do not shortlist it as written. If desired, create a narrower human-reviewed clarification solely for G3 post OD.
2. Display the unresolved post-size question explicitly and state that no human/design-team answer or authorization is recorded. Keep D1 pending, unapproved and unsent.
3. Pin the exact accepted audit bytes in a trusted, separately protected manifest or verify a digital signature. Make a disposition-only edit fail closed and leave all associated cases non-actionable. A file's self-reported SHA shown in the UI is not an integrity anchor.
4. Re-run the read-only presentation check against the corrected audit and demonstrate that a changed disposition is rejected and cannot put D2 on the active shortlist.

## Examined artifact hashes

| Artifact | SHA-256 |
|---|---|
| Remediation commit | `0cd25f9acd7950feefa29ce2a674a0609ac85301` |
| Remediation audit JSON | `1e4f1c196cdaa91659d76eb8529e2a7bda489f5d8161247d8361d7f76387371b` |
| Original successful run | `7a4cc958f821f18ce4679a6fee428148c91c39de6e9eaa3e27c50725fef70c4` |
| Failed first-attempt run | `aa5aaa5a0bbf13fdd5b20778378b5e5786728ad106494746502a48fa71a961d7` |
| Successful receipt | `a266f2047a055e7d0c4840e5e09be18681cee7c582242c70a279f06a6b424fc0` |
| Failed-attempt receipt | `4a82c28c28f5d51e3e9fd02652c6b925d787af518d33f00fd0f9e181249429dd` |
| Successful trace | `5aa339ec1bf7022ba98b505ba4ae6776c47aa9605870df24286ed21c0fe9bef8` |
| Failed-attempt trace | `8cd25c9761ed13528a067e42c69feaa49e6b4f2d0889ac0b23ddd7dd2020d6bd` |
| Original AI findings ledger | `1faf2c2f30918ec753d5c036e9618e0fd62492707c9e099e17a25b623fcbaa76` |

Verification performed: `npm run test:flight` passed (4 test files); the local Playwright E2E passed (6 step groups); separate temporary audit-tampering check failed the remediation's tamper-resistance requirement as described above. No Evolus/AMD calls or additional workflow executions were made.

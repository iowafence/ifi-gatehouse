# LOOM independent re-check — Gatehouse commit 9aaa104

**Verdict: CONDITIONAL PASS — safe for synthetic judge presentation after the citation-provenance wording correction below.** The two claimed audit-policy corrections are present, the corrected dispositions bind to the release-pinned evidence, and adversarial changes fail closed in the running application. The controlling-document reading is sound. One citation displayed with D2 is not a verbatim contiguous PDF excerpt, and the case reader trusts a stored `verified_in_source` flag rather than checking the PDF text itself. D2 is flagged and excluded from the actionable shortlist, but the presentation should not imply that the case reader independently authenticated its citations.

This is an independent report by LOOM, not a human decision or authorization. A release-pinned hash records which bytes the release accepts; it does not authenticate who authored those bytes. No Evolus or AMD request, workflow execution, source-evidence modification, push, or deployment was made for this re-check.

## 1. Controlling-document interpretation

I read the actual stored PDFs with page-preserving text extraction and checked the PDF byte hashes against the document registry and audit references.

- **G3 clear opening width: unresolved.** Addendum 01 item 2.2 expressly says the addendum does not establish it. C102 schedule note 4 and F502 note 4 say it is unspecified and prohibit assumption/scaling.
- **G3 post outside diameter: unresolved.** Specification 32 31 13 §2.1.B gives the general Type A terminal/gate post size as 2.875 in OD, but expressly says G3 size is confirmed with opening width. F502 note 4 says G3 post size is not specified. Since the G3 opening width is itself unresolved, the documents do not establish a final G3 post OD. Keep the narrow post-OD clarification open.
- **G3 footing: specified.** F502 detail 3 calls for a core-drilled terminal/gate footing, 3/F501. F502 note 5 and Specification §3.2.D provide the same terminal-post fallback. The G3 detail calls for fabric to match Type A. F501’s Type A terminal/gate footing minimum is 1'-4 in diameter × 4'-0 in deep. F501 states the listed diameters and depths are minimums below finish grade. The G3 schedule’s “SEE NOTE 4” is imprecise, but the detail’s separate direct 3/F501 callout and the general fallback establish the footing minimums.
- **Addendum 01 item 1.5: G2-scoped.** The heading is “ITEM 1 GATE G2 REVISED”; preceding items revise G2 and item 1.6 names G2 again. Item 1.5 states the post/footing unchanged for that G2 revision. No text extends it to G3. Its 2.875 in OD must not resolve G3 post size.
- **Original I2/D2: retained as historical and flagged.** The original D2 still asks for post size and footing dimensions as missing. The audit correctly distinguishes those: footing minimums are specified, G3 post OD is unresolved. D2 is outside the active shortlist.
- **New post-OD clarification: ANVIL 1 draft.** The record says it was drafted by ANVIL 1 from LOOM’s recommendation; it is not an Evolus/Gemma case or LOOM’s wording. It is proposed, requires named human review, and is explicitly not approved or sent. No human/design-team answer is represented.

## 2. Audit and evidence bindings

SHA-256 was recalculated from the files named below. The compiled `web/lib/audit-manifest.ts` contains the corresponding expected fixed digests and dispositions: audit -1 is `SUPERSEDED`; audit -2 is `ACTIVE`; I1 and I3 are `SUPPORTED`; I2/D2 is `FLAGGED_UNSUPPORTED_BY_CONTROLLING_EVIDENCE`; width and post OD are `UNRESOLVED`; footing is `SPECIFIED`; and the post-OD clarification ID is pinned.

| Artifact | SHA-256 |
|---|---|
| Corrective audit -2 | `b68748fecf9e9986ecceead9b428c5330471c59857ab88a7cedbd8b6f9f734b8` |
| Superseded audit -1 | `1e4f1c196cdaa91659d76eb8529e2a7bda489f5d8161247d8361d7f76387371b` |
| LOOM report in evidence directory | `d6040e169d374b03f3b8336f4d255d31fd892ee08bcb7b201d3273b26aeabf05` |
| Bundled LOOM report | `d6040e169d374b03f3b8336f4d255d31fd892ee08bcb7b201d3273b26aeabf05` |
| Successful Gatehouse case/run record | `7a4cc958f821f18ce4679a6fee428148c91c39de6e9eaa3e27c50725fef70c4` |
| Successful source live-run export | `43a2615dd8d0b32eb9ee15de744a07f897a4630594c30eb35c8371917b686a2a` |
| Successful trace | `5aa339ec1bf7022ba98b505ba4ae6776c47aa9605870df24286ed21c0fe9bef8` |
| D1 case | `6e4319bc30b9f45092515492b6a4c99996856dc750e49236c73da45021984701` |
| D2 case | `7f7f5001a90639eb4b2cb210462384bf146cfa60b8a444eb2ca98168f341ed7b` |
| Successful Evolus receipt | `a266f2047a055e7d0c4840e5e09be18681cee7c582242c70a279f06a6b424fc0` |
| Failed first-attempt trace | `8cd25c9761ed13528a067e42c69feaa49e6b4f2d0889ac0b23ddd7dd2020d6bd` |
| Failed first-attempt run record | `5fc35881d6ea4da988b231c74074c97e352ae8ee147e1d4fc054d62125f78098` |
| Failed first-attempt receipt | `4a82c28c28f5d51e3e9fd02652c6b925d787af518d33f00fd0f9e181249429dd` |

The source live-run export and the Gatehouse case/run record have identical parsed JSON fields and values, but their serialized bytes (and hashes) differ. The successful trace names the Gatehouse record’s `7a4…` digest, and that is the digest the audit and release manifest bind. This is a serialization difference, not evidence that the run content was changed. The failed attempt is a separate `START_FAILED` run with no execution ID and its own trace; it remains independent from the successful `COMPLETED_VALID` run and trace.

I recalculated the source PDF hashes:

- Addendum 01: `390ffe093029fb89a9e498da4ba4e46f5600690bc05ecc7717c91607fc185deb`.
- Project Manual: `9fe8c8942c453ac911abeda54d5e9be64b1bd8186d1eeba08b527e8270d0377a`.
- ANSI B Drawings: `62ab61d7f2558245f4a6f1708d9320a49e66fd28bf829a2329be5b79db9ac525`.

The controlling quotations in the corrected audit are present on their cited PDF pages, including Addendum items 1.1, 1.5, and 2.2; Specification §§2.1.B and 3.2.D; F501’s Type A minimum and minimum note; and F502 notes 4–5 and the 3/F501 G3 callout. D1’s width citations resolve to actual input evidence. I3’s Addendum and specification context are also authentic. No accepted finding relies on a dropped excerpt or on the mismatched D2 schedule excerpt described below. I2 is flagged, not accepted as supported.

The six dropped entries are human-prepared Alternate A-1 calculations/notes, all stored with `doc_id: human`, page 1, and generic reason `EXCERPT_NOT_FOUND_IN_SOURCE_PDF_TEXT`. They are not six PDF excerpts that failed PDF text lookup. The audit’s six entries are: (1) perimeter arithmetic `2 × (138 ft + 86 ft) = 448 LF`; (2) south Type A run of 138 ft; (3) two Type B dividers totaling 128 LF; (4–5) the duplicate 138 ft Alternate A-1 width note; and (6) the chain 31/38/69 note that CL G1 remains 69 ft. The builder omitted these because their document id was the unregistered human-prepared source, before model submission. The run record stores six drop metadata rows but not those six texts; the texts are in the audit correction and human-prepared scope input. The corrected wording appropriately says the model never saw them and does not treat them as failed PDF quotes.

## 3. Runtime integrity and adversarial checks

The actual local Flight Recorder at `127.0.0.1:18230` passed the read-only browser presentation check: successful and failed executions remain separate; the two drafts are pending, unapproved, and unsent; D1 alone is eligible for human review; D2 is flagged and excluded; and the post-OD clarification is visibly separate from Evolus output. AMD and Gemma are `NOT_REPORTED` within the successful Evolus execution. Historical AMD/Gemma observations remain in a separate historical section. The recorder issued GET requests only and made no external calls during that check.

I then launched a separate temporary container from the same local release image and used temporary `/tmp` audit/report copies. For each case, I called the real Flight Recorder API and checked the returned review/case/issue states. The original files and the already-running demo were not changed.

| Attack against temporary mounted data | Running-app result |
|---|---|
| Change I2 to `SUPPORTED`, keeping all other bindings unchanged | Rejected; audit unverifiable; D1 and D2 both non-actionable |
| Change D2 disposition | Rejected; all cases non-actionable |
| Replace audit bytes without changing compiled manifest | Rejected; all cases non-actionable |
| Add a claimed pin/manifest inside the mutable audit directory | Ignored; modified audit rejected; all cases non-actionable |
| Add unpinned sibling audit -3 | Rejected and revokes the otherwise valid sibling; all cases non-actionable |
| Remove pinned superseded audit -1 | Rejected; all cases non-actionable |
| Remove bundled LOOM report | Rejected; all cases non-actionable |
| Alter bundled LOOM report | Rejected; all cases non-actionable |

The reader authenticates exact audit bytes against a manifest compiled into the release and enforces the release-pinned disposition policy. It does not authenticate authorship: the manifest and hash are not a digital signature, and anyone who can replace the release can replace its manifest. The displayed statement in the Flight Recorder correctly explains this distinction.

The audit reader checks run/trace/case digests, case bindings, document registry references, and for audit evidence with an excerpt ID checks that quoted text occurs in the run’s recorded input package. That package membership check is not a fresh PDF text or semantic-support check. The fixed report/audit records the separate documentary review, and I independently confirmed the controlling quotations against the PDFs here. The case reader checks that a citation ID has a persisted evidence row and that its referenced document hash/page is consistent with the registry; it trusts the row’s `verified_in_source: true` field and does not open or extract the PDF itself.

One D2 citation illustrates the distinction: `X-c73f0ccdbf4a` is stored as `FOOTING: SEE NOTE 4`, but the F502 schedule presents a `GATE POST FOOTING` row with a separate `SEE NOTE 4` cell. The stored phrase is a normalized/abbreviated row-cell representation, not a verbatim contiguous PDF quotation. It is labeled `cited_by_original`, appears only as historical D2 evidence, and supports no accepted disposition. Its association with the schedule is real, but its persisted `verified_in_source: true` flag is not independently re-established by the case reader. The source-list UI says “located in source: yes (as recorded by the adapter),” which is qualified but still risks being read as runtime verification.

## 4. Remaining correction before judge publication

**Presentation wording (low severity, required for an unambiguous judge-facing claim):** adjust the RFI case citation display/assurance label to say that document ID, page, and hash were checked against the stored run/registry and that `verified_in_source` is a persisted adapter assertion, not a fresh Flight Recorder PDF-text check. For `X-c73f0ccdbf4a`, describe it as a schedule row/cell reference or display the actual source wording rather than treating `FOOTING: SEE NOTE 4` as an exact quotation. Keep D2 visibly flagged and out of the active shortlist.

No correction is indicated to the G3 footing dimensions, unresolved G3 post OD/width, Addendum scope, audit policy, human authorization status, or fail-closed manifest behavior. The application and manifest prove release-pinned byte integrity only; independent authorship remains a contextual assertion backed here by this re-check, not cryptographic identity authentication.

## Reproducibility references

- Hosting candidate commit: `9aaa104`.
- Corrective audit: `dp001/independent_audits/AUDIT-GH-RUN-e5bbcecef551-2.json`.
- Pinned manifest: `web/lib/audit-manifest.ts`.
- Audit reader: `web/lib/evolus-audit.ts`.
- Case reader: `web/lib/evolus-cases.ts`.
- Actual running presentation check: `e2e/e2e_evolus_cases.py` against local port 18230.
- Independent adversarial matrix: temporary isolated local container, app API calls; output recorded during this re-check: all eight attack cases above failed closed.


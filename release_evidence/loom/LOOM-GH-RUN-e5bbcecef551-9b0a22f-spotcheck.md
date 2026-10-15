# LOOM final publication UI spot-check — 9b0a22f

**Result: PASS — final UI provenance blocker resolved; local synthetic build suitable for release preparation.** This does not authorize deployment, RFI approval/transmission, or bid release.

## Live recorder

Inspected the actual Flight Recorder at `http://127.0.0.1:18230/` with the read-only browser check `e2e/e2e_evolus_cases.py` after commit `9b0a22fc23327789a09a339dd0db19aeb78386fa`.

The rendered assurance rows distinguish (1) structural validation, (2) the source-match status reported by the adapter, (3) citation-ID/document/page/hash bindings checked by the recorder, (4) independent semantic assessment, and (5) human authorization. The adapter match is explicitly “not independently rechecked by the Flight Recorder,” which “does not read the PDFs.” The binding row states that it does not check quoted text or whether a conclusion follows.

For D2 excerpt `X-c73f0ccdbf4a`, the display labels “FOOTING: SEE NOTE 4” as adapter-supplied text that may join separate table cells and is not a verified contiguous quotation. The surrounding evidence text explicitly states that the Flight Recorder does not read the PDF. The UI therefore does not imply the reader independently searched or verified PDF text.

The same browser check confirmed D1 is pending, unapproved, and unsent; D2 remains flagged and outside the actionable shortlist; the separate G3 post-OD clarification is proposed, unapproved, and unsent; the first failed attempt and successful execution remain separate; and historical AMD/Gemma material remains in its historical section. The corrected pinned audit is accepted in the normal run.

## Tamper check and regression coverage

In a temporary isolated local container, I changed I2 in a copy of audit -2 to `SUPPORTED` and opened the actual Flight Recorder. `e2e/e2e_audit_tamper.py` passed: the modified audit was rejected, no active shortlist was shown, both drafts were not cleared, and D2 did not become actionable. The temporary container and copy were removed.

The new regression test in `web/test/evolus-audit.test.mts` rejects the previous misleading source-verification wording and requires the adapter/recorder/semantic/human distinctions. The browser E2E additionally asserts the D2 excerpt’s exact label and text, plus the explicit no-PDF-reading disclosure. Reverting to “located in source” or “verified in source” fails the test; removing the caveat or presenting `X-c73f0ccdbf4a` as a verbatim quote also fails. `npm run test:flight` passed all 4 test files; the live presentation E2E passed all 6 step groups.

## Pinned artifact integrity

Recalculated hashes are unchanged from the prior independent re-check and match the release manifest:

| Artifact | SHA-256 |
|---|---|
| Compiled `web/lib/audit-manifest.ts` | `38125d47bd73d918aac65a4638342ae0e66c5ba55a9ee265d5a81e502df81bd3` |
| Successful Gatehouse run record | `7a4cc958f821f18ce4679a6fee428148c91c39de6ce9eaa3e27c50725fef70c4` |
| D1 case | `6e4319bc30b9f45092515492b6a4c99996856dc750e49236c73da45021984701` |
| D2 case | `7f7f5001a90639eb4b2cb210462384bf146cfa60b8a444eb2ca98168f341ed7b` |
| Successful trace | `5aa339ec1bf7022ba98b505ba4ae6776c47aa9605870df24286ed21c0fe9bef8` |
| Audit -1 (superseded) | `1e4f1c196cdaa91659d76eb8529e2a7bda489f5d8161247d8361d7f76387371b` |
| Audit -2 (active) | `b68748fecf9e9986ecceead9b428c5330471c59857ab88a7cedbd8b6f9f734b8` |
| Bundled LOOM report | `d6040e169d374b03f3b8336f4d255d31fd892ee08bcb7b201d3273b26aeabf05` |

The previous independent report also remains unchanged at SHA-256 `9ea27800330a4c954654358d37bd626b7333ec6934b65d8d7ddf4e69a0f3d414`. Commit 9b0a22f changes only the Flight Recorder wording, browser E2E assertions, and this regression test; it does not change the audit, release manifest, bundled report, or source evidence. As previously reported, the manifest pins bytes and policy but does not cryptographically authenticate authorship.


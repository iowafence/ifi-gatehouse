// Tests for web/lib/evolus-audit.ts: an additive independent audit is shown beside, never in place of, the original evidence, and is trusted ONLY if its exact bytes and
// dispositions are pinned by the release manifest. Synthetic fixtures plus (when present) the real ANVIL 2 evidence read-only. Run: npm run test:flight
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, readFileSync, readdirSync, existsSync, copyFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { tmpdir, homedir } from 'node:os';
import path from 'node:path';
import { loadEvidence } from '../lib/flight-recorder.ts';
import { loadCases, loadRegistryDocs } from '../lib/evolus-cases.ts';
import { attachAudits, checkAuditShape, checkManifestShape } from '../lib/evolus-audit.ts';
import { RELEASE_AUDIT_MANIFEST } from '../lib/audit-manifest.ts';

const ROOT = path.resolve(import.meta.dirname, '..', '..');
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const sha = (s: string | Buffer) => createHash('sha256').update(s).digest('hex');
const DOC = '62ab61d7f2558245f4a6f1708d9320a49e66fd28bf829a2329be5b79db9ac525', ADD = '390ffe093029fb89a9e498da4ba4e46f5600690bc05ecc7717c91607fc185deb';
const TRACE = 'GH-TRACE-aaaaaaaaaaaaaaaa', RUN = 'GH-RUN-111111111111', FOOT = 'FOOTING — TERMINAL / GATE 1\'-4" DIA. × 4\'-0" DEEP';
const Q15 = 'Gate post size and footing are unchanged: 2.875 in OD post with the terminal / gate footing, Detail 3/F501.', Q22 = 'This Addendum does not establish the clear opening width of Gate G3.';
const REPORT_NAME = 'LOOM-test-recheck.md', REPORT = '# LOOM re-check (test fixture)\nverdict: FAIL\n';
const draft = (id: string, subj: string, ref: string) => ({ draft_id: id, subject: subj, question: `Question for ${subj}?`, missing_requirements: [`${subj} requirement`], citations: [{ excerpt_id: ref }] });
const mkCase = (n: number) => { const d = draft(`D${n}`, `Gate ${n}`, `X-00000000000${n}`); return { ai_generated: true, approval: { approved_at: null, approved_by: null, status: 'NOT_APPROVED' },
  authority: { authorizes_labor_or_release: false, changes_estimate: false, changes_scope: false, marks_bid_ready: false, requires_named_human: true }, case_id: `GH-CASE-00000000000${n}`, draft: d,
  evidence_checks: [{ doc_id: 'dp001_ansi_b_v2_drawings', doc_sha256: DOC, kind: 'source_excerpt', page: 5, quote_in_source: null, ref: d.citations[0].excerpt_id, verified_in_source: true }],
  gatehouse_trace_id: TRACE, kind: 'RFI_DRAFT', note: 'Draft only.', run_id: RUN, sent_externally: false, status: 'PENDING_HUMAN_REVIEW' }; };
const pkg = { excerpts: [{ excerpt_id: 'X-aaaaaaaaaaaa', doc_id: 'dp001_addendum_01_ansi_b_pkg', page: 1, doc_sha256: ADD, label: 'Addendum 01 item 2.2', text: Q22 },
                         { excerpt_id: 'X-bbbbbbbbbbbb', doc_id: 'dp001_addendum_01_ansi_b_pkg', page: 1, doc_sha256: ADD, label: 'Addendum 01 item 1.5', text: Q15 },
                         { excerpt_id: 'X-cccccccccccc', doc_id: 'dp001_ansi_b_v2_drawings', page: 4, doc_sha256: DOC, label: 'F501 footing', text: FOOT }] };
const mkRun = (cases: any[]) => ({ run_id: RUN, gatehouse_trace_id: TRACE, status: 'COMPLETED_VALID', mode: 'LIVE', execution_id: 'exec-1', ai_suggestion_only: true,
  evolus_execution: { input: JSON.stringify(pkg) },
  issues: [1, 2, 3].map(i => ({ issue: { issue_id: `I${i}`, title: `Issue ${i}`, category: 'UNRESOLVED_REQUIREMENT', severity: 'REVIEW' } })), rfi_drafts: cases.map(c => ({ draft: clone(c.draft) })),
  dropped_unverifiable_excerpts: Array.from({ length: 6 }, () => ({ doc_id: 'human', page: 1, label: '', reason: 'EXCERPT_NOT_FOUND_IN_SOURCE_PDF_TEXT' })), state_hash_before: 'h', state_hash_after: 'h' });
const trace = (runSha: string) => ({ schema: 'gatehouse-flight-trace.v1', trace_id: TRACE, generated_utc: '2026-10-14T20:15:59Z', producer: { name: 'fixture', version: '1' }, layers: [
  { layer: 'amd', state: 'NOT_REPORTED', summary: 'none', events: [] }, { layer: 'gemma', state: 'NOT_REPORTED', summary: 'none', events: [] },
  { layer: 'evolus', state: 'RECORDED', summary: '1', events: [{ event_id: 'evolus-exec', kind: 'workflow_execution', label: 'Evolus workflow execution', state: 'RECORDED', utc: '2026-10-14T20:15:59Z', note: null,
    source: { kind: 'stored_inference_record', record_path: `evolus_runs/${RUN}.json`, record_sha256: runSha }, fields: { workflow_execution_id: { value: 'exec-1', unit: null, reported: true, derived: null } } }] }] });
const ev = (excerpt: string, quote: string, role: string, applies: string, controlling = true) => ({ excerpt_id: excerpt, doc_id: excerpt === 'X-cccccccccccc' ? 'dp001_ansi_b_v2_drawings' : 'dp001_addendum_01_ansi_b_pkg', doc_sha256: excerpt === 'X-cccccccccccc' ? DOC : ADD,
  page: excerpt === 'X-cccccccccccc' ? 4 : 1, locator: 'locator', quote, role, applies_to: applies, controlling_document: controlling, quote_found_in_stored_pdf: true });
const mkAudit = (traceSha: string, runSha: string, c1: any, c2: any, reportSha: string, mod: (a: any) => void = () => {}) => { const a: any = { schema: 'gatehouse-independent-audit.v2', audit_id: `AUDIT-${RUN}-2`, supersedes: `AUDIT-${RUN}-1`, created_utc: '2026-10-14T21:00:00Z', additive: true, is_human_decision: false,
  auditor: { name: 'LOOM', role: 'independent evidence auditor', reported_verdict: 'FAIL (re-check)' }, source: { kind: 'independent_report', description: 'LOOM report (test)', report_file: REPORT_NAME, report_sha256: reportSha },
  human_authorization: { status: 'NONE_RECORDED', note: 'not a human decision' }, subject: { gatehouse_trace_id: TRACE, run_id: RUN, run_sha256: runSha, trace_sha256: traceSha, execution_id: 'exec-1', original_validator_status: 'COMPLETED_VALID', original_validator_status_preserved: true },
  dispositions: [ { issue_id: 'I1', draft_id: 'D1', case_id: c1.case_id, case_sha256: c1.sha256, disposition: 'SUPPORTED', subject_scope: 'G3', summary: 'Supported.', evidence: [ev('X-aaaaaaaaaaaa', Q22, 'supports', 'G3')], verification_note: 'checked' },
                  { issue_id: 'I2', draft_id: 'D2', case_id: c2.case_id, case_sha256: c2.sha256, disposition: 'FLAGGED_UNSUPPORTED_BY_CONTROLLING_EVIDENCE', subject_scope: 'G3', summary: 'Flagged: the footing is specified by 3/F501; the G3 post OD is still unresolved.',
                    evidence: [ev('X-cccccccccccc', FOOT, 'controlling_contradicts', 'G3', false), ev('X-bbbbbbbbbbbb', Q15, 'context', 'G2')], verification_note: 'item 1.5 is G2-only' },
                  { issue_id: 'I3', draft_id: null, case_id: null, case_sha256: null, disposition: 'SUPPORTED', subject_scope: 'G2', summary: 'Supported.', evidence: [ev('X-aaaaaaaaaaaa', Q22, 'supports', 'G3')].map(x => ({ ...x, applies_to: 'G2' })) } ],
  scope_findings: [ { item: 'G3_POST_OD', label: 'G3 post OD', status: 'UNRESOLVED', value: null, basis: 'confirmed with the opening width', evidence_excerpt_ids: ['X-bbbbbbbbbbbb'] },
                    { item: 'G3_FOOTING', label: 'G3 footing', status: 'SPECIFIED', value: '1\'-4" dia. x 4\'-0" deep minimum', basis: '3/F501', evidence_excerpt_ids: ['X-cccccccccccc'] } ],
  proposed_clarifications: [ { clarification_id: `PC-${RUN}-G3-POST-OD`, topic: 'G3 post OD', derived_from_issue: 'I2', status: 'PROPOSED_NOT_APPROVED', approved: false, sent: false, evolus_generated: false, requires_named_human_review: true,
    authorship: { kind: 'DRAFTED_BY_ANVIL_1_FROM_LOOM_RECOMMENDATION', description: 'drafted by ANVIL 1; not an Evolus case' }, question: 'Please confirm the G3 post outside diameter.', unresolved_requirements: ['G3 post OD'], excluded_because_specified: ['G3 footing'], evidence_excerpt_ids: ['X-bbbbbbbbbbbb'] } ],
  drops_correction: { count: 6, original_reason_code: 'EXCERPT_NOT_FOUND_IN_SOURCE_PDF_TEXT', explanation: 'Human-prepared notes omitted before submission; not failed PDF quotations.', entries: [{ doc_id: 'human', text: 'note' }] }, verification: { by: 'test' } }; mod(a); return a; };
const mkManifest = (o: { runSha: string; traceSha: string; c1: any; c2: any; auditSha: string; reportSha: string; policyMod?: (p: any) => void }): any => { const m: any = { schema: 'gatehouse-audit-release-manifest.v1', release: 'test release', runs: [{ run_id: RUN, run_sha256: o.runSha, trace_id: TRACE, trace_sha256: o.traceSha, execution_id: 'exec-1',
  cases: { D1: { case_id: o.c1.case_id, case_sha256: o.c1.sha256 }, D2: { case_id: o.c2.case_id, case_sha256: o.c2.sha256 } }, loom_report: { file: REPORT_NAME, sha256: o.reportSha },
  audits: [ { audit_id: `AUDIT-${RUN}-1`, file: `AUDIT-${RUN}-1.json`, sha256: sha('superseded first record'), status: 'SUPERSEDED' }, { audit_id: `AUDIT-${RUN}-2`, file: `AUDIT-${RUN}-2.json`, sha256: o.auditSha, status: 'ACTIVE' } ],
  policy: { issues: { I1: { draft_id: 'D1', disposition: 'SUPPORTED' }, I2: { draft_id: 'D2', disposition: 'FLAGGED_UNSUPPORTED_BY_CONTROLLING_EVIDENCE' }, I3: { draft_id: null, disposition: 'SUPPORTED' } },
    cases: { D1: 'SUPPORTED', D2: 'FLAGGED_UNSUPPORTED_BY_CONTROLLING_EVIDENCE' }, scope_findings: { G3_POST_OD: 'UNRESOLVED', G3_FOOTING: 'SPECIFIED' }, proposed_clarifications: [`PC-${RUN}-G3-POST-OD`] } }] }; o.policyMod?.(m.runs[0].policy); return m; };

type Opts = { audit?: boolean; mod?: (a: any) => void; repin?: boolean; manifestMod?: (m: any) => void; report?: string | null; extra?: (adir: string, origBytes: string) => void; superseded?: boolean };
async function scenario(o: Opts = {}) {
  const cases = [mkCase(1), mkCase(2)]; const run = mkRun(cases); const runText = JSON.stringify(run, null, 1);
  const tdir = mkdtempSync(path.join(tmpdir(), 'tr-')), cdir = mkdtempSync(path.join(tmpdir(), 'cs-')), adir = mkdtempSync(path.join(tmpdir(), 'au-')), rdir = mkdtempSync(path.join(tmpdir(), 'rl-'));
  writeFileSync(path.join(tdir, 't.json'), JSON.stringify(trace(sha(runText)))); for (const c of cases) writeFileSync(path.join(cdir, `${c.case_id}.json`), JSON.stringify(c)); writeFileSync(path.join(cdir, `${RUN}.json`), runText);
  process.env.DP001_DIR = path.join(ROOT, 'dp001'); process.env.FLIGHT_TRACE_DIR = tdir; process.env.GATEHOUSE_CASES_DIR = cdir; process.env.GATEHOUSE_AUDIT_DIR = adir;
  const e = await loadEvidence(); const reg = await loadRegistryDocs(); const cs = await loadCases(e.executions, reg); const rv0 = cs.reviews.get(TRACE)!; const [k1, k2] = rv0.cases;
  const reportSha = sha(REPORT); if (o.report !== null) writeFileSync(path.join(rdir, REPORT_NAME), o.report ?? REPORT);
  const orig = JSON.stringify(mkAudit(e.executions[0].sha256, sha(runText), k1, k2, reportSha)); const written = o.mod ? JSON.stringify(mkAudit(e.executions[0].sha256, sha(runText), k1, k2, reportSha, o.mod)) : orig;
  if (o.audit !== false) { writeFileSync(path.join(adir, `AUDIT-${RUN}-2.json`), written); if (o.superseded !== false) writeFileSync(path.join(adir, `AUDIT-${RUN}-1.json`), 'superseded first record'); }
  o.extra?.(adir, orig);
  const manifest = mkManifest({ runSha: sha(runText), traceSha: e.executions[0].sha256, c1: k1, c2: k2, auditSha: sha(o.repin ? written : orig), reportSha });
  if (o.manifestMod) o.manifestMod(manifest);
  await attachAudits(cs.reviews, e.executions, cs.runs, reg, cs.sources, manifest, rdir);
  return { rv: cs.reviews.get(TRACE)!, cs, adir, cdir, tdir, rdir, runText, cases, e, manifest, written, orig };
}
const byDraft = (rv: any, d: string) => rv.cases.find((c: any) => c.draft_id === d);
const audReasons = (cs: any) => cs.sources.filter((s: any) => s.role === 'audit' && !s.accepted).map((s: any) => (s.errors || []).join(' | ')).join(' || ');
const notCleared = (rv: any) => { for (const c of rv.cases) { assert.equal(c.assessment.actionable, false); assert.notEqual(c.assessment.state, 'SUPPORTED'); assert.equal(c.assessment.state, 'AUDIT_UNVERIFIABLE'); } assert.equal(rv.audit, undefined); assert.equal(rv.audit_unverifiable, true); };

test('pinned audit: I2/D2 are FLAGGED and not actionable; D1 is SUPPORTED and eligible; the original case, draft and validator result are untouched', async () => {
  const { rv, cases, cs } = await scenario(); const d1 = byDraft(rv, 'D1'), d2 = byDraft(rv, 'D2');
  assert.equal(audReasons(cs), '');
  assert.equal(d2.assessment.state, 'FLAGGED'); assert.equal(d2.assessment.actionable, false); assert.equal(d2.assessment.label, 'FLAGGED — UNSUPPORTED BY CONTROLLING EVIDENCE');
  assert.equal(d1.assessment.state, 'SUPPORTED'); assert.equal(d1.assessment.actionable, true);
  for (const c of [d1, d2]) { assert.equal(c.status, 'PENDING_HUMAN_REVIEW'); assert.equal(c.approval_status, 'NOT_APPROVED'); assert.equal(c.sent_externally, false); }
  assert.equal(d2.question, 'Question for Gate 2?', 'the original AI question is preserved verbatim'); assert.deepEqual(d2.missing_requirements, cases[1].draft.missing_requirements);
  assert.equal(rv.run!.status, 'COMPLETED_VALID', 'the original validator result is preserved'); assert.equal(rv.run!.issues.find((i: any) => i.issue_id === 'I2').assessment.state, 'FLAGGED');
  const q15 = d2.assessment.evidence.find((x: any) => x.excerpt_id === 'X-bbbbbbbbbbbb'); assert.equal(q15.applies_to, 'G2'); assert.equal(q15.role, 'context'); assert.equal(q15.matches_run_package, true);
  assert.equal(rv.audit!.is_human_decision, false); assert.equal(rv.audit!.human_authorization_status, 'NONE_RECORDED'); assert.equal(rv.audit!.source_kind, 'independent_report');
  assert.equal(rv.audit!.pinned.report_verified, true); assert.equal(rv.audit!.pinned.superseded.length, 1); assert.equal(rv.audit!.pinned.supersedes, `AUDIT-${RUN}-1`);
  assert.deepEqual(rv.audit!.scope_findings.map((f: any) => [f.item, f.status]), [['G3_POST_OD', 'UNRESOLVED'], ['G3_FOOTING', 'SPECIFIED']]);
  const pc = rv.audit!.proposed_clarifications[0]; assert.equal(pc.approved, false); assert.equal(pc.sent, false); assert.equal(pc.evolus_generated, false); assert.match(pc.authorship_kind, /ANVIL_1/);
});
test('REGRESSION: a structurally valid, authentically cited finding that was independently contradicted is never actionable', async () => {
  const { rv } = await scenario(); const d2 = byDraft(rv, 'D2');
  assert.equal(rv.run!.status, 'COMPLETED_VALID'); assert.ok(d2.evidence.length > 0 && d2.evidence.every((e: any) => e.registry === 'match'), 'structurally valid with authentic, registry-matching citations');
  assert.equal(d2.integrity.draft_matches_run_record, true); assert.equal(d2.assessment.actionable, false); assert.notEqual(d2.assessment.state, 'SUPPORTED');
  for (const s of [await scenario({ audit: false }), await scenario({ mod: a => { a.subject.run_sha256 = 'f'.repeat(64); } })]) for (const c of s.rv.cases) { assert.equal(c.assessment.actionable, false); assert.notEqual(c.assessment.state, 'SUPPORTED'); }
});
test('ATTACK (LOOM): copy the audit, change ONLY I2 to SUPPORTED, keep every binding valid, let the app hash the altered file -> REJECTED / NOT CLEARED; D2 never actionable', async () => {
  const s = await scenario({ mod: a => { const d = a.dispositions.find((x: any) => x.issue_id === 'I2'); d.disposition = 'SUPPORTED'; d.evidence[0].role = 'supports'; } });
  assert.notEqual(sha(s.written), sha(s.orig), 'the attacker file differs'); assert.match(audReasons(s.cs), /differ from the digest pinned in the release manifest/);
  const shownSha = s.cs.sources.find((x: any) => x.name === `AUDIT-${RUN}-2.json`).sha256; assert.equal(shownSha, sha(s.written), 'the app computes the altered file\'s own sha, which proves nothing');
  notCleared(s.rv); assert.equal(byDraft(s.rv, 'D2').assessment.actionable, false); assert.equal(byDraft(s.rv, 'D1').assessment.actionable, false, 'unauthenticated audit evidence clears NOTHING, not even D1');
  assert.equal(s.rv.run!.issues.find((i: any) => i.issue_id === 'I2').assessment.state, 'AUDIT_UNVERIFIABLE');
  // the minimal variant: the disposition word alone is flipped (evidence untouched)
  const t = await scenario({ mod: a => { a.dispositions[1].disposition = 'SUPPORTED'; } }); notCleared(t.rv);
  // even if the attacker could ALSO re-pin the altered bytes, the pinned release policy still says D2 is FLAGGED
  const u = await scenario({ mod: a => { a.dispositions[1].disposition = 'SUPPORTED'; a.dispositions[1].evidence[0].role = 'supports'; }, repin: true }); assert.match(audReasons(u.cs), /inconsistent with the pinned release policy/); notCleared(u.rv);
});
test('trust boundary: wrong manifest digest, missing manifest entry, altered or missing LOOM report, unregistered replacement, duplicate, wrong case disposition, wrong identity, substituted evidence all fail closed', async () => {
  const w = await scenario({ manifestMod: m => { m.runs[0].audits[1].sha256 = 'a'.repeat(64); } }); assert.match(audReasons(w.cs), /differ from the digest pinned/); notCleared(w.rv);
  const n = await scenario({ manifestMod: m => { m.runs = []; } }); assert.match(audReasons(n.cs), /not pinned in the release audit manifest/); notCleared(n.rv);
  const r = await scenario({ report: REPORT + 'tampered\n' }); assert.match(audReasons(r.cs), /bundled LOOM re-check report differs/); notCleared(r.rv);
  const rm = await scenario({ report: null }); assert.match(audReasons(rm.cs), /bundled LOOM re-check report is missing/); notCleared(rm.rv);
  const rc = await scenario({ manifestMod: m => { m.runs[0].loom_report.sha256 = 'b'.repeat(64); } }); assert.match(audReasons(rc.cs), /bundled LOOM re-check report differs|cites a LOOM report other than/); notCleared(rc.rv);
  const x = await scenario({ extra: (adir, orig) => writeFileSync(path.join(adir, `AUDIT-${RUN}-3.json`), orig.replace('"supersedes":"AUDIT-GH-RUN-111111111111-1"', '"supersedes":"AUDIT-GH-RUN-111111111111-2"')) });
  assert.match(audReasons(x.cs), /not pinned/); notCleared(x.rv); assert.ok(x.cs.sources.some((s: any) => s.name === `AUDIT-${RUN}-2.json` && !s.accepted && /revoked/.test((s.errors || []).join())), 'a verified sibling is revoked, not left "accepted"');
  const dup = await scenario({ extra: (adir, orig) => writeFileSync(path.join(adir, `AUDIT-${RUN}-3.json`), orig) }); assert.match(audReasons(dup.cs), /duplicate audit record/); notCleared(dup.rv);
  const cd = await scenario({ mod: a => { a.dispositions[0].disposition = 'FLAGGED_UNSUPPORTED_BY_CONTROLLING_EVIDENCE'; a.dispositions[0].evidence[0].role = 'controlling_contradicts'; }, repin: true }); assert.match(audReasons(cd.cs), /I1: disposition .* inconsistent with the pinned release policy/); notCleared(cd.rv);
  const cp = await scenario({ manifestMod: m => { m.runs[0].policy.cases.D2 = 'SUPPORTED'; m.runs[0].policy.issues.I2.disposition = 'SUPPORTED'; } }); assert.match(audReasons(cp.cs), /inconsistent with the pinned release policy/); notCleared(cp.rv);
  const wr = await scenario({ mod: a => { a.subject.run_id = 'GH-RUN-999999999999'; }, repin: true }); assert.match(audReasons(wr.cs), /different run|different .* than the manifest/); notCleared(wr.rv);
  const ws = await scenario({ manifestMod: m => { m.runs[0].cases.D1.case_sha256 = 'c'.repeat(64); } }); assert.match(audReasons(ws.cs), /case binding differs from the manifest/); notCleared(ws.rv);
  const wt = await scenario({ manifestMod: m => { m.runs[0].trace_sha256 = 'd'.repeat(64); } }); assert.match(audReasons(wt.cs), /manifest/); notCleared(wt.rv);
  const sc = await scenario({ mod: a => { a.scope_findings[0].status = 'SPECIFIED'; a.scope_findings[0].value = '2.875 in OD'; }, repin: true }); assert.match(audReasons(sc.cs), /scope findings differ from the pinned release policy/); notCleared(sc.rv);
  const pcn = await scenario({ mod: a => { a.proposed_clarifications = []; }, repin: true }); assert.match(audReasons(pcn.cs), /proposed clarifications differ/); notCleared(pcn.rv);
  const sup = await scenario({ superseded: false }); assert.match(audReasons(sup.cs), /pinned audit record is missing/); notCleared(sup.rv);
});
test('an invalid release manifest fails closed (two ACTIVE audits, duplicate digests, malformed policy)', async () => {
  const two = await scenario({ manifestMod: m => { m.runs[0].audits[0].status = 'ACTIVE'; } }); assert.match(audReasons(two.cs), /manifest is invalid/); notCleared(two.rv);
  const dupd = await scenario({ manifestMod: m => { m.runs[0].audits[0].sha256 = m.runs[0].audits[1].sha256; } }); assert.match(audReasons(dupd.cs), /manifest is invalid/); notCleared(dupd.rv);
  assert.ok(checkManifestShape({ schema: 'x' }).length); assert.ok(checkManifestShape(null).length);
  assert.deepEqual(checkManifestShape(RELEASE_AUDIT_MANIFEST), [], 'the shipped manifest is well-formed');
});
test('no audit pinned for the run: cases are NOT_AUDITED and not actionable; a dropped-entries fact is still computed from the run record alone', async () => {
  const { rv } = await scenario({ audit: false, manifestMod: m => { m.runs = []; } }); assert.ok(rv.cases.every((c: any) => c.assessment.state === 'NOT_AUDITED' && c.assessment.actionable === false)); assert.equal(rv.audit, undefined);
  assert.equal(rv.run!.dropped_excerpts, 6); assert.deepEqual(rv.run!.dropped_doc_ids, ['human']); assert.equal(rv.run!.dropped_unregistered, true);
  const miss = await scenario({ audit: false }); notCleared(miss.rv); assert.match(audReasons(miss.cs), /pinned audit record is missing/);
});
test('fail-safe content checks still apply to a correctly pinned audit (bytes pinned, but bindings or quotes wrong)', async () => {
  const cases: [string, (a: any) => void, RegExp][] = [
    ['wrong run sha', a => { a.subject.run_sha256 = 'f'.repeat(64); }, /different run record|differs from the manifest/], ['wrong trace sha', a => { a.subject.trace_sha256 = 'e'.repeat(64); }, /different trace file|differs from the manifest/],
    ['different original status', a => { a.subject.original_validator_status = 'REJECTED'; }, /different original validator status/], ['case bytes differ', a => { a.dispositions[0].case_sha256 = 'd'.repeat(64); }, /case binding differs|different case bytes/],
    ['quote not in package', a => { a.dispositions[1].evidence[1].quote = 'Posts are 4.5 in OD everywhere.'; }, /not in the package/], ['unknown issue', a => { a.dispositions[2].issue_id = 'I9'; }, /different issues|not an issue/],
    ['registry hash', a => { a.dispositions[1].evidence[1].doc_sha256 = 'c'.repeat(64); }, /differs from Gatehouse's registry/], ['drops count', a => { a.drops_correction.count = 5; }, /count differs/]];
  for (const [name, mod, re] of cases) { const { rv, cs } = await scenario({ mod, repin: true }); assert.match(audReasons(cs), re, name); notCleared(rv); assert.equal(rv.run!.status, 'COMPLETED_VALID', name); assert.equal(byDraft(rv, 'D1').question, 'Question for Gate 1?', name); }
});
test('shape: no human decision, no approval, no extra fields, a flag needs controlling evidence, scope-guarded evidence, honest clarification authorship', () => {
  const ok = mkAudit('a'.repeat(64), 'b'.repeat(64), { case_id: 'GH-CASE-000000000001', sha256: 'c'.repeat(64) }, { case_id: 'GH-CASE-000000000002', sha256: 'd'.repeat(64) }, 'e'.repeat(64)); const stem = `AUDIT-${RUN}-2`;
  assert.deepEqual(checkAuditShape(ok, stem), []);
  const bad = (f: (a: any) => void, re: RegExp) => { const a = clone(ok); f(a); const r = checkAuditShape(a, stem); assert.ok(r.some(x => re.test(x)), `${re} in ${JSON.stringify(r)}`); };
  bad(a => { a.is_human_decision = true; }, /never a human decision/); bad(a => { a.human_authorization = { status: 'APPROVED', note: 'x' }; }, /NONE_RECORDED/); bad(a => { a.approval = 'APPROVED'; }, /unexpected field/);
  bad(a => { a.dispositions[1].evidence[0].role = 'context'; }, /flag must cite controlling/); bad(a => { a.dispositions[0].disposition = 'APPROVED'; }, /malformed/); bad(a => { delete a.source; }, /explicit source/);
  bad(a => { a.additive = false; }, /additive/); bad(a => { a.audit_id = 'AUDIT-GH-RUN-222222222222-1'; }, /file name/); bad(a => { a.subject.original_validator_status_preserved = false; }, /subject must bind/);
  bad(a => { a.schema = 'gatehouse-independent-audit.v1'; }, /schema must be/);
  // the Blocker-1 scope guard: G2-only text can be context, but cannot be the contradiction of a G3 conclusion
  bad(a => { a.dispositions[1].evidence[1].role = 'controlling_contradicts'; }, /evidence for G2 cannot be a contradiction for a G3 conclusion/);
  bad(a => { a.proposed_clarifications[0].approved = true; }, /claims approval, sending or Evolus authorship/); bad(a => { a.proposed_clarifications[0].sent = true; }, /claims approval/); bad(a => { a.proposed_clarifications[0].evolus_generated = true; }, /claims approval/);
  bad(a => { a.proposed_clarifications[0].authorship.kind = 'EVOLUS_GEMMA'; }, /claims approval/); bad(a => { a.scope_findings[0].value = '2.875 in OD'; }, /scope finding G3_POST_OD is malformed/);
});
test('the corrected six-drop explanation comes from the audit and is shown only when the run record agrees', async () => {
  const { rv } = await scenario(); assert.equal(rv.audit!.drops!.count, 6); assert.match(rv.audit!.drops!.explanation, /not failed PDF quotations/); assert.equal(rv.audit!.drops!.verified_against_run_record, true); assert.equal(rv.audit!.drops!.original_reason_code, 'EXCERPT_NOT_FOUND_IN_SOURCE_PDF_TEXT');
  assert.equal(rv.run!.dropped_reasons[0], 'EXCERPT_NOT_FOUND_IN_SOURCE_PDF_TEXT', 'the original reason code from the run record is still reported as recorded');
});
test('read-only and additive: files are byte-identical after loading; the loader never computes or writes expected hashes', async () => {
  const { cdir, tdir, adir, runText, manifest, rdir } = await scenario(); const snap = (d: string) => readdirSync(d).sort().map(n => n + sha(readFileSync(path.join(d, n), 'utf8'))).join();
  const before = [snap(cdir), snap(tdir), snap(adir), snap(rdir)], mBefore = JSON.stringify(manifest);
  for (let i = 0; i < 3; i++) { const e = await loadEvidence(); const reg = await loadRegistryDocs(); const cs = await loadCases(e.executions, reg); await attachAudits(cs.reviews, e.executions, cs.runs, reg, cs.sources, manifest, rdir); }
  assert.deepEqual([snap(cdir), snap(tdir), snap(adir), snap(rdir)], before); assert.equal(JSON.stringify(manifest), mBefore, 'the manifest is not mutated'); assert.equal(sha(readFileSync(path.join(cdir, `${RUN}.json`), 'utf8')), sha(runText));
  const src = readFileSync(path.join(ROOT, 'web/lib/evolus-audit.ts'), 'utf8').replace(/\/\/.*$/gm, ''); assert.ok(!/writeFile|appendFile|unlink|rename|\brm\(|mkdir|createWriteStream|fetch\(|http|engine\(|approve\(|release\(/.test(src));
  assert.ok(!/GATEHOUSE_AUDIT_MANIFEST|manifest\.json/.test(src), 'no manifest is read from disk or the environment: it is compiled into the release');
});

// ---- the real evidence (read-only): the shipped audit records against the shipped manifest and ANVIL 2's actual files
const REAL_C = path.join(homedir(), 'gatehouse-evolus-cases'), REAL_T = path.join(homedir(), 'gatehouse-flight-traces'), AUD = path.join(ROOT, 'dp001/independent_audits'), REL = path.join(ROOT, 'web/release');
const haveReal = existsSync(REAL_C) && existsSync(REAL_T);
async function real(auditDir: string, manifest: any = RELEASE_AUDIT_MANIFEST, releaseDir = REL) {
  process.env.DP001_DIR = path.join(ROOT, 'dp001'); process.env.FLIGHT_TRACE_DIR = REAL_T; process.env.GATEHOUSE_CASES_DIR = REAL_C; process.env.GATEHOUSE_AUDIT_DIR = auditDir;
  const e = await loadEvidence(); const reg = await loadRegistryDocs(); const cs = await loadCases(e.executions, reg); await attachAudits(cs.reviews, e.executions, cs.runs, reg, cs.sources, manifest, releaseDir); return { e, cs };
}
test('shipped audit records and LOOM report match the release manifest byte for byte; the earlier record is preserved and superseded', () => {
  const m = RELEASE_AUDIT_MANIFEST.runs[0]; for (const a of m.audits) assert.equal(sha(readFileSync(path.join(AUD, a.file))), a.sha256, a.file);
  assert.equal(sha(readFileSync(path.join(REL, m.loom_report.file))), m.loom_report.sha256); assert.equal(m.loom_report.sha256, 'd6040e169d374b03f3b8336f4d255d31fd892ee08bcb7b201d3273b26aeabf05');
  assert.equal(m.audits.find(a => a.status === 'SUPERSEDED')!.sha256, '1e4f1c196cdaa91659d76eb8529e2a7bda489f5d8161247d8361d7f76387371b', 'the earlier audit is pinned unchanged');
  assert.deepEqual(readdirSync(AUD).filter(n => n.endsWith('.json')).sort(), m.audits.map(a => a.file).sort(), 'no unpinned audit file ships');
  const a2 = JSON.parse(readFileSync(path.join(AUD, m.audits[1].file), 'utf8')); assert.deepEqual(checkAuditShape(a2, m.audits[1].audit_id), []); assert.equal(a2.is_human_decision, false);
  assert.equal(a2.source.kind, 'independent_report'); assert.equal(a2.source.report_sha256, m.loom_report.sha256);
});
test('REAL evidence: pinned corrected audit verifies; D1 stays on the shortlist, D2 flagged; G3 width and post OD unresolved, footing specified; the failed attempt stays separate', { skip: !haveReal }, async () => {
  const { e, cs } = await real(AUD); assert.equal(audReasons(cs), ''); assert.equal(e.executions.length, 2);
  const ok = e.executions.find(x => x.trace_id === 'GH-TRACE-06b4b6d525133f8a')!, failed = e.executions.find(x => x.trace_id === 'GH-TRACE-2b2a7a1397a9599b')!;
  const rv = cs.reviews.get(ok.trace_id)!; assert.equal(byDraft(rv, 'D1').assessment.actionable, true); assert.equal(byDraft(rv, 'D2').assessment.state, 'FLAGGED'); assert.equal(byDraft(rv, 'D2').assessment.actionable, false);
  assert.deepEqual(rv.audit!.scope_findings.map((f: any) => [f.item, f.status]).sort(), [['G3_CLEAR_OPENING_WIDTH', 'UNRESOLVED'], ['G3_FOOTING', 'SPECIFIED'], ['G3_POST_OD', 'UNRESOLVED']]);
  const item15 = byDraft(rv, 'D2').assessment.evidence.find((x: any) => /item 1\.5/.test(x.locator)); assert.equal(item15.applies_to, 'G2'); assert.equal(item15.role, 'context', 'item 1.5 is not used as a contradiction of G3');
  const pc = rv.audit!.proposed_clarifications[0]; assert.equal(pc.topic, 'Gate G3 post outside diameter'); assert.equal(pc.approved, false); assert.equal(pc.sent, false); assert.equal(pc.evolus_generated, false); assert.doesNotMatch(pc.question, /footing/i);
  assert.equal(cs.reviews.get(failed.trace_id) ?? null, null, 'the HTTP 400 execution has no review, cases or audit'); assert.equal(rv.audit!.pinned.superseded[0].sha256, '1e4f1c196cdaa91659d76eb8529e2a7bda489f5d8161247d8361d7f76387371b');
});
test('REAL evidence ATTACK: copy the real audit, change only I2 to SUPPORTED, keep all bindings, let the app recompute the SHA -> rejected, NOT CLEARED, D2 never actionable', { skip: !haveReal }, async () => {
  const tmp = mkdtempSync(path.join(tmpdir(), 'real-au-')); for (const n of readdirSync(AUD)) copyFileSync(path.join(AUD, n), path.join(tmp, n));
  const f = path.join(tmp, 'AUDIT-GH-RUN-e5bbcecef551-2.json'); const a = JSON.parse(readFileSync(f, 'utf8')); a.dispositions.find((d: any) => d.issue_id === 'I2').disposition = 'SUPPORTED';
  writeFileSync(f, JSON.stringify(a, null, 1) + '\n'); assert.notEqual(sha(readFileSync(f)), RELEASE_AUDIT_MANIFEST.runs[0].audits[1].sha256);
  const { cs } = await real(tmp); const rv = cs.reviews.get('GH-TRACE-06b4b6d525133f8a')!; assert.match(audReasons(cs), /differ from the digest pinned in the release manifest/); notCleared(rv); assert.equal(byDraft(rv, 'D2').assessment.actionable, false);
  // the same attack with a self-consistent re-pin of the altered bytes still fails on the pinned policy
  const m = clone(RELEASE_AUDIT_MANIFEST); m.runs[0].audits[1].sha256 = sha(readFileSync(f)); const r2 = await real(tmp, m); assert.match(audReasons(r2.cs), /inconsistent with the pinned release policy/); notCleared(r2.cs.reviews.get('GH-TRACE-06b4b6d525133f8a')!);
  // and an altered LOOM report copy
  const rel = mkdtempSync(path.join(tmpdir(), 'real-rl-')); writeFileSync(path.join(rel, RELEASE_AUDIT_MANIFEST.runs[0].loom_report.file), readFileSync(path.join(REL, RELEASE_AUDIT_MANIFEST.runs[0].loom_report.file), 'utf8') + 'x');
  const r3 = await real(AUD, RELEASE_AUDIT_MANIFEST, rel); assert.match(audReasons(r3.cs), /bundled LOOM re-check report differs/); notCleared(r3.cs.reviews.get('GH-TRACE-06b4b6d525133f8a')!);
});
test('REAL evidence: no audit directory content leaves both original executions uncleared; the failed execution never gets cases', { skip: !haveReal }, async () => {
  const empty = mkdtempSync(path.join(tmpdir(), 'real-empty-')); const { e, cs } = await real(empty); assert.equal(e.executions.length, 2); notCleared(cs.reviews.get('GH-TRACE-06b4b6d525133f8a')!); assert.match(audReasons(cs), /pinned audit record is missing/);
  const none = await real(empty, { ...clone(RELEASE_AUDIT_MANIFEST), runs: [] }); for (const c of none.cs.reviews.get('GH-TRACE-06b4b6d525133f8a')!.cases) { assert.equal(c.assessment.state, 'NOT_AUDITED'); assert.equal(c.assessment.actionable, false); }
  for (const x of e.executions) assert.ok(x.sha256 === (x.trace_id === 'GH-TRACE-06b4b6d525133f8a' ? '5aa339ec1bf7022ba98b505ba4ae6776c47aa9605870df24286ed21c0fe9bef8' : '8cd25c9761ed13528a067e42c69feaa49e6b4f2d0889ac0b23ddd7dd2020d6bd'));
});

test('REGRESSION: the recorder never claims it freshly verified PDF text; adapter assertions, recorder binding checks, LOOM assessment and human authorization stay distinct', () => {
  const ui = readFileSync(path.join(ROOT, 'web/app/components/flight-recorder.tsx'), 'utf8');
  for (const bad of [/verified in (the )?source/i, /located in (the )?(stored )?source/i, /Authentic citations/, /quote matches the package/i, /freshly verified/i, /verbatim quotation (verified|confirmed)/i, /re-?verified (in|against) (the )?(pdf|source)/i]) assert.ok(!bad.test(ui), `forbidden runtime-verification claim: ${bad}`);
  for (const must of ['source match reported by adapter', 'not independently rechecked by Flight Recorder', 'Not independently rechecked by the Flight Recorder', 'Citation binding checks by the recorder', 'Adapter-supplied excerpt text', 'not a verified contiguous quotation', 'Independent assessment of semantic support', 'Human authorization']) assert.ok(ui.includes(must), `missing: ${must}`);
  for (const f of ['evolus-cases.ts', 'evolus-audit.ts']) { const src = readFileSync(path.join(ROOT, 'web/lib', f), 'utf8').replace(/\/\/.*$/gm, ''); assert.ok(!/pdftotext|pdf-parse|pdfjs|\.pdf['"`]/i.test(src), `${f} must not read PDFs (it cannot have rechecked their text)`); }
});

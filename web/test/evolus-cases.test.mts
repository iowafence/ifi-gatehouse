// Tests for web/lib/evolus-cases.ts: stored pending-review RFI cases shown under the execution that produced them. Run: npm run test:flight
// All data here is synthetic and built in the test; none of ANVIL 2's files is read or touched.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { loadEvidence } from '../lib/flight-recorder.ts';
import { loadCases, loadRegistryDocs, checkCaseShape } from '../lib/evolus-cases.ts';

const ROOT = path.resolve(import.meta.dirname, '..', '..');
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const sha = (s: string) => createHash('sha256').update(s).digest('hex');
const F = (value: any, unit: string | null = null) => ({ value, unit, reported: value !== null, derived: null });
const DOC = '62ab61d7f2558245f4a6f1708d9320a49e66fd28bf829a2329be5b79db9ac525'; // dp001_ansi_b_v2_drawings in Gatehouse's registry (5 pages)

const TRACE_OK = 'GH-TRACE-aaaaaaaaaaaaaaaa', TRACE_FAIL = 'GH-TRACE-bbbbbbbbbbbbbbbb', RUN = 'GH-RUN-111111111111';
const draft = (id: string, subj: string, refs: string[]) => ({ draft_id: id, subject: subj, question: `Question for ${subj}?`, missing_requirements: [`${subj} requirement`], citations: refs.map(r => ({ excerpt_id: r })) });
const evidence = (ref: string, page = 5) => ({ doc_id: 'dp001_ansi_b_v2_drawings', doc_sha256: DOC, kind: 'source_excerpt', page, quote_in_source: null, ref, verified_in_source: true });
const mkCase = (n: number, d = draft(`D${n}`, `Gate ${n}`, [`X-00000000000${n}`])) => ({ ai_generated: true, approval: { approved_at: null, approved_by: null, status: 'NOT_APPROVED' },
  authority: { authorizes_labor_or_release: false, changes_estimate: false, changes_scope: false, marks_bid_ready: false, requires_named_human: true }, case_id: `GH-CASE-00000000000${n}`, draft: d,
  evidence_checks: d.citations.map(c => evidence(c.excerpt_id)), gatehouse_trace_id: TRACE_OK, kind: 'RFI_DRAFT', note: 'Draft only.', run_id: RUN, sent_externally: false, status: 'PENDING_HUMAN_REVIEW' });
const mkRun = (cases: any[], extra: any = {}) => ({ run_id: RUN, gatehouse_trace_id: TRACE_OK, status: 'COMPLETED_VALID', mode: 'LIVE', execution_id: 'exec-1', ai_suggestion_only: true,
  issues: [{ issue: { issue_id: 'I1', title: 'Gate 1', category: 'UNRESOLVED_REQUIREMENT', severity: 'BLOCKING_SUGGESTED' } }], rfi_drafts: cases.map(c => ({ draft: clone(c.draft) })),
  dropped_unverifiable_excerpts: [{ reason: 'EXCERPT_NOT_FOUND_IN_SOURCE_PDF_TEXT' }, { reason: 'EXCERPT_NOT_FOUND_IN_SOURCE_PDF_TEXT' }], state_hash_before: 'h', state_hash_after: 'h', ...extra });
const evTrace = (id: string, ok: boolean, runSha: string | null, utc: string) => ({ schema: 'gatehouse-flight-trace.v1', trace_id: id, generated_utc: utc, producer: { name: 'fixture', version: '1' }, layers: [
  { layer: 'amd', state: 'NOT_REPORTED', summary: 'none', events: [] }, { layer: 'gemma', state: 'NOT_REPORTED', summary: 'none', events: [] },
  { layer: 'evolus', state: ok ? 'RECORDED' : 'FAILED', summary: '1', events: [{ event_id: 'evolus-exec', kind: 'workflow_execution', label: 'Evolus workflow execution', state: ok ? 'RECORDED' : 'FAILED', utc,
    note: ok ? null : 'HTTP_ERROR', source: ok ? { kind: 'stored_inference_record', record_path: `evolus_runs/${RUN}.json`, record_sha256: runSha } : { kind: 'none', record_path: null, record_sha256: null },
    fields: { workflow_execution_id: F(ok ? 'exec-1' : null) } }] }] });
const write = (dir: string, n: string, v: unknown) => writeFileSync(path.join(dir, n), typeof v === 'string' ? v : JSON.stringify(v));

/** builds a trace dir + case dir; returns the loaded evidence and cases */
async function scenario(opts: { cases?: any[]; failed?: boolean; okTrace?: boolean; runOverride?: (r: any) => any; noRun?: boolean; rawCases?: Record<string, unknown> } = {}) {
  const cases = opts.cases ?? [mkCase(1), mkCase(2)]; const run = opts.runOverride ? opts.runOverride(mkRun(cases)) : mkRun(cases); const runText = JSON.stringify(run, null, 1);
  const tdir = mkdtempSync(path.join(tmpdir(), 'tr-')), cdir = mkdtempSync(path.join(tmpdir(), 'cs-'));
  if (opts.okTrace !== false) write(tdir, 't_ok.json', evTrace(TRACE_OK, true, sha(runText), '2026-10-14T20:15:59Z'));
  if (opts.failed) write(tdir, 't_fail.json', evTrace(TRACE_FAIL, false, null, '2026-10-14T19:49:50Z'));
  for (const c of cases) write(cdir, `${c.case_id}.json`, c);
  for (const [n, v] of Object.entries(opts.rawCases || {})) write(cdir, n, v);
  if (!opts.noRun) write(cdir, `${RUN}.json`, runText);
  process.env.DP001_DIR = path.join(ROOT, 'dp001'); process.env.FLIGHT_TRACE_DIR = tdir; process.env.GATEHOUSE_CASES_DIR = cdir;
  const ev = await loadEvidence(); const cs = await loadCases(ev.executions, await loadRegistryDocs());
  return { ev, cs, cdir, tdir };
}
const reasons = (cs: any) => cs.sources.filter((s: any) => !s.accepted).map((s: any) => (s.errors || []).join(' | ')).join(' || ');

test('two stored cases are linked to the successful execution, with draft, requirements, citations, status and approval exactly as recorded', async () => {
  const { cs } = await scenario(); const rv = cs.reviews.get(TRACE_OK)!;
  assert.equal(rv.cases.length, 2); assert.deepEqual(rv.cases.map((c: any) => c.case_id), ['GH-CASE-000000000001', 'GH-CASE-000000000002']);
  const c = rv.cases[0]; assert.equal(c.status, 'PENDING_HUMAN_REVIEW'); assert.equal(c.approval_status, 'NOT_APPROVED'); assert.equal(c.sent_externally, false); assert.equal(c.ai_generated, true);
  assert.equal(c.subject, 'Gate 1'); assert.deepEqual(c.missing_requirements, ['Gate 1 requirement']); assert.equal(c.evidence[0].excerpt_id, 'X-000000000001'); assert.equal(c.evidence[0].registry, 'match');
  assert.equal(c.evidence[0].quote_in_source, null, 'no quote is invented when the case stores none'); assert.equal(c.integrity.run_record, 'matches_trace_hash'); assert.equal(c.integrity.draft_matches_run_record, true);
  assert.equal(c.authority.changes_scope, false); assert.equal(c.authority.marks_bid_ready, false);
  assert.equal(rv.run!.status, 'COMPLETED_VALID'); assert.equal(rv.run!.matches_trace_hash, true); assert.equal(rv.run!.dropped_excerpts, 2); assert.equal(rv.run!.gatehouse_state_unchanged, true);
  assert.equal(cs.sources.filter((s: any) => s.accepted).length, 2);
});
test('the prior failed run and the successful run stay separate; cases attach only to the run that produced them; telemetry stays honest', async () => {
  const { ev, cs } = await scenario({ failed: true });
  assert.deepEqual(ev.executions.map(x => x.trace_id), [TRACE_OK, TRACE_FAIL]);
  const [ok, failed] = ev.executions; const lay = (x: any, k: string) => x.layers.find((l: any) => l.layer === k);
  assert.equal(ok.outcome, 'RECORDED'); assert.equal(failed.outcome, 'FAILED');
  for (const x of ev.executions) { assert.equal(lay(x, 'amd').state, 'NOT_REPORTED'); assert.equal(lay(x, 'gemma').state, 'NOT_REPORTED'); assert.equal(lay(x, 'amd').events.length + lay(x, 'gemma').events.length, 0); }
  assert.equal(cs.reviews.has(TRACE_FAIL), false, 'the failed run has no cases'); assert.equal(cs.reviews.get(TRACE_OK)!.cases.length, 2);
  assert.equal(lay(failed, 'evolus').events[0].fields.workflow_execution_id.value, null, 'no execution id is invented for the failed run');
  assert.ok(!JSON.stringify(cs.reviews.get(TRACE_OK)).includes('HTTP_ERROR'));
  // loading cases does not change any layer or state
  const again = await loadEvidence(); assert.deepEqual(again.executions.map(x => ({ id: x.trace_id, o: x.outcome, l: x.layers })), ev.executions.map(x => ({ id: x.trace_id, o: x.outcome, l: x.layers })));
});
test('missing cases: no directory, an empty directory, or only a failed run all yield no review and no error', async () => {
  process.env.DP001_DIR = path.join(ROOT, 'dp001'); process.env.FLIGHT_TRACE_DIR = mkdtempSync(path.join(tmpdir(), 'tr-'));
  process.env.GATEHOUSE_CASES_DIR = path.join(tmpdir(), 'does-not-exist-' + Date.now());
  let ev = await loadEvidence(); let cs = await loadCases(ev.executions, null); assert.equal(cs.reviews.size, 0); assert.equal(cs.sources.length, 0);
  const s = await scenario({ cases: [], failed: true, okTrace: false, noRun: true }); assert.equal(s.cs.reviews.size, 0); assert.equal(s.ev.executions.length, 1);
  const s2 = await scenario({ cases: [] }); assert.equal(s2.cs.reviews.size, 0, 'a successful execution with no cases shows no case and no invented one');
});
test('a case with no run record is still shown, marked as not cross-checked', async () => {
  const { cs } = await scenario({ noRun: true }); const rv = cs.reviews.get(TRACE_OK)!; assert.equal(rv.run, null); assert.equal(rv.cases.length, 2); assert.equal(rv.cases[0].integrity.run_record, 'not_available'); assert.equal(rv.cases[0].integrity.draft_matches_run_record, null);
});
test('malformed or over-claiming case evidence is rejected and none of it is displayed', async () => {
  const bad = (f: (c: any) => void, re: RegExp) => { const c = mkCase(3); f(c); const r = checkCaseShape(c, 'GH-CASE-000000000003'); assert.ok(r.some(x => re.test(x)), `expected ${re} in ${JSON.stringify(r)}`); };
  assert.deepEqual(checkCaseShape(mkCase(3), 'GH-CASE-000000000003'), []);
  bad(c => { c.status = 'APPROVED'; }, /not displayable/);
  bad(c => { c.approval = { status: 'APPROVED', approved_by: 'Someone', approved_at: '2026-10-14T00:00:00Z' }; }, /approval must be exactly NOT_APPROVED/);
  bad(c => { c.approval.approved_by = 'Jordan'; }, /approval must be exactly NOT_APPROVED/);
  bad(c => { c.sent_externally = true; }, /sent_externally/);
  bad(c => { c.authority.changes_scope = true; }, /authority flags/);
  bad(c => { c.authority.marks_bid_ready = true; }, /authority flags/);
  bad(c => { c.estimate = { price: 1 }; }, /unexpected field/);
  bad(c => { c.draft.price = 5; }, /exactly draft_id/);
  bad(c => { c.case_id = 'GH-CASE-999999999999'; }, /file name/);
  bad(c => { c.evidence_checks = []; }, /no evidence record/);
  bad(c => { c.evidence_checks[0].verified_in_source = false; }, /not verified/);
  bad(c => { c.evidence_checks[0].page = 0; }, /malformed/);
  bad(c => { c.draft.citations = [{ rfi_id: 'RFI-1' }]; }, /citations must be/);
  bad(c => { c.draft.question = ''; }, /text fields/);
  bad(c => { c.kind = 'APPROVED_RFI'; }, /kind/);
  const bads: Record<string, unknown> = {}; const approved = mkCase(3); approved.status = 'APPROVED'; approved.approval = { status: 'APPROVED', approved_by: 'X', approved_at: 'now' }; approved.case_id = 'GH-CASE-000000000003'; bads['GH-CASE-000000000003.json'] = approved;
  bads['GH-CASE-000000000004.json'] = '{"case_id": "GH-CASE-0000'; const sent = mkCase(5); sent.sent_externally = true; bads['GH-CASE-000000000005.json'] = sent;
  const { cs } = await scenario({ rawCases: bads }); const rv = cs.reviews.get(TRACE_OK)!;
  assert.equal(rv.cases.length, 2, 'only the two valid cases appear'); assert.equal(cs.sources.filter((s: any) => !s.accepted).length, 3);
  assert.ok(!JSON.stringify(rv).includes('Gate 3') && !JSON.stringify(rv).includes('Gate 5'), 'no content of a rejected case is displayed');
});
test('cross-checks: orphan trace id, run-record hash mismatch, draft differing from the run record, registry hash mismatch, wrong run are all rejected', async () => {
  const orphan = mkCase(3); orphan.gatehouse_trace_id = 'GH-TRACE-cccccccccccccccc'; let s = await scenario({ cases: [mkCase(1), orphan] });
  assert.equal(s.cs.reviews.get(TRACE_OK)!.cases.length, 1); assert.match(reasons(s.cs), /no accepted execution trace GH-TRACE-cccccccccccccccc/);
  s = await scenario({ runOverride: r => { r.status = 'TAMPERED'; return r; } }); // run text hashed AFTER override, so rewrite the file to break the hash
  writeFileSync(path.join(s.cdir, `${RUN}.json`), JSON.stringify({ ...mkRun([mkCase(1), mkCase(2)]), status: 'CHANGED_AFTER' }));
  const ev = await loadEvidence(); const cs = await loadCases(ev.executions, await loadRegistryDocs()); assert.equal(cs.reviews.size, 0); assert.match(reasons(cs), /does not match the sha256 recorded in the execution trace/);
  s = await scenario({ runOverride: r => { r.rfi_drafts[0].draft.question = 'a different question?'; return r; } }); assert.equal(s.cs.reviews.get(TRACE_OK)!.cases.length, 1); assert.match(reasons(s.cs), /differs from the draft in its run record/);
  const wrongHash = mkCase(3); wrongHash.evidence_checks[0].doc_sha256 = 'f'.repeat(64); s = await scenario({ cases: [mkCase(1), wrongHash] }); assert.match(reasons(s.cs), /hash differs from Gatehouse's registry/); assert.equal(s.cs.reviews.get(TRACE_OK)!.cases.length, 1);
  const page = mkCase(3); page.evidence_checks[0].page = 99; s = await scenario({ cases: [mkCase(1), page] }); assert.match(reasons(s.cs), /beyond the document/);
  const otherRun = mkCase(3); otherRun.run_id = 'GH-RUN-999999999999'; s = await scenario({ cases: [mkCase(1), otherRun] }); assert.match(reasons(s.cs), /not the run recorded in the execution trace/);
});
test('an unknown document is shown as not in Gatehouse’s registry, never as matching; a stored quote is shown only if the case stores it', async () => {
  const c = mkCase(3); c.evidence_checks[0].doc_id = 'some_other_doc'; c.evidence_checks[0].quote_in_source = 'stored quote'; const { cs } = await scenario({ cases: [mkCase(1), c] });
  const e = cs.reviews.get(TRACE_OK)!.cases.find((x: any) => x.case_id === c.case_id)!.evidence[0]; assert.equal(e.registry, 'unknown_document'); assert.equal(e.quote_in_source, 'stored quote');
});
test('read-only: loading never writes to the case or trace directories, and the module contains no write, approve, send or network call', async () => {
  const { cdir, tdir } = await scenario({ failed: true }); const snap = (d: string) => readdirSync(d).sort().map(n => `${n}:${statSync(path.join(d, n)).mtimeMs}:${statSync(path.join(d, n)).size}`).join();
  const a = [snap(cdir), snap(tdir)]; for (let i = 0; i < 3; i++) { const ev = await loadEvidence(); await loadCases(ev.executions, await loadRegistryDocs()); } assert.deepEqual([snap(cdir), snap(tdir)], a);
  const src = readFileSync(path.join(ROOT, 'web/lib/evolus-cases.ts'), 'utf8').replace(/\/\/.*$/gm, '');
  assert.ok(!/writeFile|appendFile|unlink|rename|\brm\(|mkdir|createWriteStream|fetch\(|http|engine\(|approve\(|release\(/.test(src), 'no write/network/engine call in the case reader');
  assert.ok(!/evolus-cases/.test(readFileSync(path.join(ROOT, 'web/lib/takeoff-service.ts'), 'utf8') + readFileSync(path.join(ROOT, 'web/lib/ai-findings.ts'), 'utf8')), 'the pricing/scope/release services do not import the case reader');
});

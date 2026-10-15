// Contract tests for web/lib/flight-recorder.ts (gatehouse-flight-trace.v1). Run: npm run test:flight   (Node >= 22.6, no network, no server)
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { validateTrace, layerState, validationLayer, humanLayer, loadEvidence } from '../lib/flight-recorder.ts';

const ROOT = path.resolve(import.meta.dirname, '..', '..');
const recorded = () => JSON.parse(readFileSync(path.join(ROOT, 'dp001/flight_recorder.json'), 'utf8'));
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const rejects = (doc: unknown, re: RegExp) => { const v = validateTrace(doc); assert.equal(v.ok, false, 'should be rejected'); assert.ok((v as any).errors.some((e: string) => re.test(e)), `expected /${re}/ in ${JSON.stringify((v as any).errors)}`); };
const ev = (d: any, layer: string, i = 0) => d.layers.find((l: any) => l.layer === layer).events[i];
const fld = (value: any, reported = value !== null) => ({ value, unit: null, reported, derived: null });

test('the recorded trace shipped with the repository is valid and its hashes match the stored records', () => {
  const v = validateTrace(recorded()); assert.equal(v.ok, true, JSON.stringify((v as any).errors));
  for (const l of recorded().layers) for (const e of l.events) if (e.state === 'RECORDED' || e.state === 'FAILED') {
    if (!e.source.record_path) continue;
    assert.equal(createHash('sha256').update(readFileSync(path.join(ROOT, e.source.record_path))).digest('hex'), e.source.record_sha256, e.event_id);
  }
});
test('no number is invented: every unreported field is null, every non-null field is reported', () => {
  for (const l of recorded().layers) for (const e of l.events) for (const [k, f] of Object.entries<any>(e.fields)) assert.equal(f.reported, f.value !== null, `${e.event_id}.${k}`);
});
test('GPU utilization and similar values are absent from the recorded trace', () => {
  const names = recorded().layers.flatMap((l: any) => l.events.flatMap((e: any) => Object.keys(e.fields)));
  assert.ok(names.length > 50); assert.ok(names.every((n: string) => !/gpu|utiliz|reasoning|power|temperature/i.test(n)), 'no such field may exist');
});
test('a DeepSeek request never appears in the gemma layer; the gemma layer holds only the failed Gemma attempt', () => {
  const g = recorded().layers.find((l: any) => l.layer === 'gemma');
  assert.equal(g.events.length, 1); assert.match(g.events[0].fields.model.value, /gemma/i); assert.equal(g.state, 'FAILED');
  assert.ok(recorded().layers.find((l: any) => l.layer === 'amd').events.some((e: any) => /DeepSeek/.test(e.fields.model.value)));
});
test('the evolus layer is NOT_REPORTED when nothing was recorded', () => {
  const e = recorded().layers.find((l: any) => l.layer === 'evolus'); assert.equal(e.state, 'NOT_REPORTED'); assert.equal(e.events.length, 0);
});

test('rule 1: reported=false with a value, or a value without reported, is rejected', () => {
  const a = recorded(); ev(a, 'amd').fields.http_status = { value: 200, unit: null, reported: false, derived: null }; rejects(a, /reported=false requires value=null/);
  const b = recorded(); ev(b, 'amd').fields.chunks = { value: 5, unit: null, reported: true === false, derived: null }; rejects(b, /reported=false requires value=null|non-null value requires reported/);
});
test('rule 2-6: provenance requirements per state', () => {
  const live = recorded(); Object.assign(ev(live, 'amd'), { state: 'LIVE' }); rejects(live, /LIVE requires/);
  const rec = recorded(); ev(rec, 'amd', 2).source.record_sha256 = null; rejects(rec, /RECORDED requires/);
  const sim = recorded(); Object.assign(ev(sim, 'amd', 2), { state: 'SIMULATED' }); rejects(sim, /SIMULATED requires/);
  const fail = recorded(); ev(fail, 'amd', 0).note = null; rejects(fail, /FAILED requires a note/);
  const nr = recorded(); Object.assign(ev(nr, 'amd', 2), { state: 'NOT_REPORTED' }); rejects(nr, /NOT_REPORTED requires/);
  const badhash = recorded(); ev(badhash, 'amd', 2).source.record_sha256 = 'abc'; rejects(badhash, /not 64 hex/);
});
test('rule 7: a derived field must have reported inputs; its arithmetic must hold', () => {
  const a = recorded(); const e = ev(a, 'amd', 8); e.fields.t_request_sent_s = fld(null); rejects(a, /derived input|does not equal its formula/);
  const b = recorded(); ev(b, 'amd', 8).fields.tokens_per_s.value = 9999; rejects(b, /tokens_per_s does not equal its formula/);
  const c = recorded(); ev(c, 'amd', 8).fields.ttft_s.value = 1.0; rejects(c, /ttft_s does not equal its formula/);
});
test('rule 8: gemma needs a gemma model; evolus live/recorded needs a workflow_execution_id on every event', () => {
  const a = recorded(); ev(a, 'gemma').fields.model.value = 'DeepSeek-V4.1-Flash'; rejects(a, /containing "gemma"/);
  const b = recorded(); b.layers.find((l: any) => l.layer === 'evolus').events = [{ event_id: 'x', kind: 'workflow_execution', label: 'x', state: 'RECORDED', utc: null, fields: { agent: fld('a') }, source: { kind: 'stored_inference_record', record_path: 'evolus_runs/r1.json', record_sha256: 'a'.repeat(64) }, note: null }];
  b.layers.find((l: any) => l.layer === 'evolus').state = 'RECORDED'; rejects(b, /workflow_execution_id/);
});
test('rule 9: the layer state must equal the state derived from its events', () => {
  const a = recorded(); a.layers.find((l: any) => l.layer === 'amd').state = 'LIVE'; rejects(a, /does not match its events/);
  assert.equal(layerState([]), 'NOT_REPORTED'); assert.equal(layerState([{ state: 'FAILED' }]), 'FAILED');
  assert.equal(layerState([{ state: 'FAILED' }, { state: 'RECORDED' }]), 'RECORDED'); assert.equal(layerState([{ state: 'RECORDED' }, { state: 'LIVE' }]), 'LIVE');
});
test('Gatehouse layers and Gatehouse source kinds are never accepted from a trace file', () => {
  const a = recorded(); a.layers.push({ layer: 'human_authorization', state: 'NOT_REPORTED', summary: 's', events: [] }); rejects(a, /not accepted from a trace file|at most 3/);
  const b = recorded(); ev(b, 'amd', 2).source.kind = 'ledger_replay'; rejects(b, /source.kind must be one of/);
  const c = recorded(); ev(c, 'amd', 2).source.record_path = '../../etc/passwd'; rejects(c, /record_path must be relative/);
  rejects({ schema: 'other' }, /schema must be/); rejects(null, /not a JSON object/);
});

// A trace shaped like the one ANVIL 2 described: simulator run => SIMULATED with source simulation + note; every evolus event has workflow_execution_id.
const evolusSimulated = () => ({ schema: 'gatehouse-flight-trace.v1', trace_id: 't1', generated_utc: null, producer: { name: 'evolus_review.flight_trace', version: '0' }, layers: [
  { layer: 'evolus', state: 'SIMULATED', summary: 'simulator run', events: ['workflow_execution', 'knowledge_retrieval', 'tool_call'].map((k, i) => ({ event_id: `e${i}`, kind: k, label: k, state: 'SIMULATED', utc: null,
      fields: { workflow_execution_id: fld('sim-1'), agent: fld('agent-1'), review_state: fld('Completed'), knowledge_sources: fld(null), submitted_epoch_s: fld(100), completed_epoch_s: fld(130),
                total_s: { value: 30, unit: 's', reported: true, derived: { formula: 'completed_epoch_s - submitted_epoch_s', inputs: ['completed_epoch_s', 'submitted_epoch_s'] } } },
      source: { kind: 'simulation', record_path: null, record_sha256: null }, note: 'Simulator, not a live Evolus run.' })) },
  { layer: 'gemma', state: 'NOT_REPORTED', summary: 'not reported', events: [] }, { layer: 'amd', state: 'NOT_REPORTED', summary: 'not reported', events: [] }] });
test('an Evolus-style SIMULATED trace is accepted; the same events presented as RECORDED without a run record are not', () => {
  assert.equal(validateTrace(evolusSimulated()).ok, true);
  const bad = evolusSimulated(); for (const e of bad.layers[0].events) e.state = 'RECORDED'; bad.layers[0].state = 'RECORDED'; rejects(bad, /RECORDED requires/);
});

test('validationLayer reports the two contradicted findings and the simulated guard items from the ledger, never from a trace', () => {
  const buf = readFileSync(path.join(ROOT, 'dp001/ai_findings.json'));
  const L = validationLayer({ sha: createHash('sha256').update(buf).digest('hex'), data: JSON.parse(buf.toString()) });
  assert.equal(L.events.filter(e => e.kind === 'claim_contradicted').length, 2);
  assert.equal(L.events.filter(e => e.state === 'SIMULATED').length, 2);
  assert.match(L.events.find(e => e.kind === 'claim_contradicted')!.fields.acceptance.value as string, /409 CONTRADICTED_BY_DRAWING_EVIDENCE/);
  assert.equal(validationLayer(null).state, 'NOT_REPORTED');
});
test('humanLayer: the system start entry is not a decision and no timestamp is invented', () => {
  const start = { event_id: 1, event: 'start', utc: '2026-10-14T16:41:09.818587+00:00', actor: null, scope_version: 1 };
  const empty = humanLayer({ audit: [start] }, []); assert.equal(empty.state, 'NOT_REPORTED'); assert.equal(empty.events.length, 0); assert.match(empty.summary, /1 system entry/);
  assert.equal(humanLayer(null, []).state, 'NOT_REPORTED');
  const L = humanLayer({ audit: [start, { event_id: 2, event: 'resolved', utc: '2026-10-14T16:50:00+00:00', actor: 'A Tester', exception_id: 'BID_SELECTION', option_id: 'base', note: 'n', scope_version: 2 },
                                  { event_id: 3, event: 'resolved', actor: 'B Tester', exception_id: 'X' }] }, []);
  assert.equal(L.events.length, 2); assert.equal(L.state, 'LIVE'); assert.match(L.events[0].note!, /Self-declared/);
  assert.equal(L.events[0].fields.by.value, 'A Tester'); assert.equal(L.events[0].utc, '2026-10-14T16:50:00+00:00');
  assert.equal(L.events[1].utc, null, 'a missing timestamp stays null'); assert.ok(!JSON.stringify(L).includes('1970'));
});
// ---- provenance separation: the selected execution is never combined with historical records or with another execution ----
import { mkdtempSync, writeFileSync } from 'node:fs'; import { tmpdir } from 'node:os';
const FIX = (n: string) => JSON.parse(readFileSync(path.join(ROOT, 'e2e/fixtures/flight_traces', n), 'utf8'));
const dirWith = (files: Record<string, unknown>) => { const d = mkdtempSync(path.join(tmpdir(), 'ft-')); for (const [n, v] of Object.entries(files)) writeFileSync(path.join(d, n), JSON.stringify(v)); return d; };
const load = async (dir: string) => { process.env.DP001_DIR = path.join(ROOT, 'dp001'); process.env.FLIGHT_TRACE_DIR = dir; return loadEvidence(); };
const lay = (x: any, k: string) => x.layers.find((l: any) => l.layer === k);
const succeeded = () => { const d = clone(FIX('valid_evolus_simulated.json')); d.trace_id = 'FIXTURE-second-run'; d.generated_utc = '2026-10-14T21:00:00Z'; return d; };

test('historical records stay in the historical group; a failed execution reports AMD and Gemma as NOT_REPORTED', async () => {
  const r = await load(dirWith({ 'failed.json': FIX('failed_evolus_http_error_fixture.json') }));
  assert.equal(r.executions.length, 1); const x = r.executions[0];
  assert.equal(x.trace_id, 'FIXTURE-failed-http-error'); assert.equal(x.outcome, 'FAILED');
  assert.equal(lay(x, 'evolus').state, 'FAILED'); assert.equal(lay(x, 'gemma').state, 'NOT_REPORTED'); assert.equal(lay(x, 'amd').state, 'NOT_REPORTED');
  assert.equal(lay(x, 'amd').events.length, 0); assert.equal(lay(x, 'gemma').events.length, 0);
  assert.equal(lay(r.historical, 'amd').events.length, 10, 'the 10 earlier AMD requests are still shown, as history');
  assert.equal(lay(r.historical, 'gemma').state, 'FAILED'); assert.equal(r.historical.source!.role, 'historical'); assert.match(r.historical.source!.sha256!, /^[0-9a-f]{64}$/);
  const e = lay(x, 'evolus').events[0].fields; assert.equal(e.workflow_execution_id.value, null); assert.equal(e.workflow_execution_id.reported, false);
  assert.ok(!Object.keys(e).some(k => /token|prompt|completion|gpu/.test(k)), 'no token or inference field exists on the failed execution');
  const execJson = JSON.stringify(x); assert.ok(!execJson.includes('Gemma-4-31B-IT') && !execJson.includes('DeepSeek') && !execJson.includes('dp001/'), 'no historical record leaks into the execution');
});
test('no historical event id appears in any execution, and adding executions does not change the historical group', async () => {
  const alone = await load(dirWith({}));
  const r = await load(dirWith({ 'a.json': FIX('failed_evolus_http_error_fixture.json'), 'b.json': succeeded() }));
  assert.equal(alone.executions.length, 0); assert.deepEqual(r.historical.layers, alone.historical.layers);
  const histIds = new Set(r.historical.layers.flatMap(l => l.events.map(e => e.event_id)));
  for (const x of r.executions) for (const l of x.layers) for (const e of l.events) assert.ok(!histIds.has(e.event_id) || e.event_id === 'evolus-exec', `event ${e.event_id} duplicates a historical id`);
});
test('a second execution (failed or not) is kept apart: newest first, its layers and states are its own', async () => {
  const r = await load(dirWith({ 'a.json': FIX('failed_evolus_http_error_fixture.json'), 'b.json': succeeded() }));
  assert.deepEqual(r.executions.map(x => x.trace_id), ['FIXTURE-second-run', 'FIXTURE-failed-http-error']);
  const [second, failed] = r.executions;
  assert.equal(failed.outcome, 'FAILED'); assert.equal(second.outcome, 'SIMULATED');
  assert.equal(lay(failed, 'amd').events.length, 0, 'the other run\'s simulated AMD events do not reach the failed run');
  assert.equal(lay(failed, 'evolus').events.length, 1); assert.ok(lay(second, 'evolus').events.length >= 1);
  assert.ok(lay(failed, 'evolus').events.every((e: any) => e.state === 'FAILED'), 'the failed run holds only its own FAILED event');
  assert.ok(second.layers.every((l: any) => l.events.every((e: any) => e.state === 'SIMULATED')), 'simulated stays simulated; it is not upgraded or mixed');
  // reversing which one is newer reverses the order but changes nothing else
  const f2 = FIX('failed_evolus_http_error_fixture.json'); f2.generated_utc = '2026-10-14T22:00:00Z';
  const r2 = await load(dirWith({ 'a.json': f2, 'b.json': succeeded() })); assert.equal(r2.executions[0].trace_id, 'FIXTURE-failed-http-error');
});
test('a duplicate trace_id, or an external file reusing the repository trace id, is rejected rather than merged', async () => {
  const dup = clone(FIX('failed_evolus_http_error_fixture.json'));
  const r = await load(dirWith({ 'a.json': FIX('failed_evolus_http_error_fixture.json'), 'b.json': dup, 'c.json': { ...recorded() } }));
  assert.equal(r.executions.length, 1); const rej = r.sources.filter(s => s.role === 'execution' && !s.accepted).map(s => s.name).sort();
  assert.deepEqual(rej, ['b.json', 'c.json']); assert.ok(r.sources.find(s => s.name === 'b.json')!.errors!.some(e => /duplicate trace_id/.test(e)));
});
test('an invalid or partial external file is rejected, strict validation is unchanged, and nothing from it is shown', async () => {
  const d = dirWith({ 'ok.json': succeeded(), 'unbacked.json': FIX('invalid_unbacked_gpu_number.json') }); writeFileSync(path.join(d, 'half.json'), '{"schema": "gatehouse-flight');
  const r = await load(d);
  assert.deepEqual(r.executions.map(x => x.trace_id), ['FIXTURE-second-run']);
  assert.equal(r.sources.filter(s => !s.accepted).length, 2); assert.ok(!JSON.stringify(r.executions).includes('gpu_utilization'));
  const fakeLive = clone(FIX('failed_evolus_http_error_fixture.json')); fakeLive.trace_id = 'x'; fakeLive.layers[2].events[0].state = 'LIVE'; fakeLive.layers[2].state = 'LIVE'; rejects(fakeLive, /LIVE requires/);
});
test('no executions: the selected-execution group is empty and historical evidence is still available', async () => {
  const r = await load(dirWith({})); assert.equal(r.executions.length, 0); assert.equal(lay(r.historical, 'evolus').state, 'NOT_REPORTED'); assert.equal(lay(r.historical, 'amd').events.length, 10);
});

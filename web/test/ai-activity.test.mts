// The AI activity rows are built from stored records only. These tests read the real stored files in the repository. Run: npm run test:flight
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { buildAiActivity, evolusStatement, NR } from '../lib/ai-activity.ts';
import { loadEvidence } from '../lib/flight-recorder.ts';

const root = new URL('../../', import.meta.url).pathname;
process.env.DP001_DIR = root + 'dp001'; process.env.FLIGHT_TRACE_DIR = root + 'release_evidence/traces'; process.env.GATEHOUSE_CASES_DIR = root + 'release_evidence/cases';
process.env.GATEHOUSE_CAPTURE_DIR = root + 'hosting/captures'; process.env.ENGINE_ADDENDUM_MODE = 'recorded';

test('addendum parse row: model, route, RECORDED, written time, tokens in/cached/out, latency and cost from the stored capture', async () => {
  const a = await buildAiActivity(); const r = a.rows.find(x => x.id === 'addendum-parse')!;
  assert.equal(r.model, 'Qwen3.8-27B'); assert.match(r.path, /AMD Token Factory/); assert.equal(r.mode, 'RECORDED'); assert.match(r.time, /2026-10-16T17:43:56Z/);
  assert.equal(r.tokens_in, '970'); assert.equal(r.tokens_cached, '960'); assert.equal(r.tokens_out, '258'); assert.equal(r.latency, '12,577 ms'); assert.equal(r.cost, '$0.0000191');
});
test('scope-read row: 10 attempts by model and outcome; tokens and call time counted per attempt from the records; failures and timeouts are listed', async () => {
  const r = (await buildAiActivity()).rows.find(x => x.id === 'scope-read-evaluation')!;
  assert.match(r.model, /Gemma-4-31B-IT 1/); assert.match(r.model, /Qwen3.8-27B 2/); assert.match(r.model, /DeepSeek-V4.1-Flash 7/);
  assert.match(r.measurements[0].value, /5 produced candidates/); assert.match(r.measurements[0].value, /2 failed/); assert.match(r.measurements[0].value, /3 timed out/);
  assert.equal(r.attempts!.length, 10); assert.equal(r.mode, 'RECORDED');
  assert.equal(r.calls_with_tokens, 7); assert.match(r.tokens_in, /reported on 7 of 10/); assert.match(r.latency, /reported on 10 of 10/);
  assert.equal(r.attempts!.filter(x => x.state === 'TIMED_OUT').length, 3);
  assert.ok(r.attempts!.filter(x => x.state === 'TIMED_OUT').every(x => /timeout|aborted/.test(x.latency_basis)));
  assert.equal(r.attempts!.find(x => x.attempt_id === 'spatial_c101_live_001')!.tokens_in, NR);
});
test('Evolus rows: configured model not asserted as reported; tokens NOT_REPORTED; the two time measurements are separate and labelled; the 1.292 s belongs to the FAILED run', async () => {
  const a = await buildAiActivity(); const ok = a.rows.find(x => /COMPLETED/.test(x.time) && x.id.startsWith('evolus'))!, bad = a.rows.find(x => /FAILED/.test(x.step))!;
  assert.equal(ok.model, 'configured Gemma-4-31B-IT, not reported by the run'); assert.match(ok.latency, /labelled measurements/); assert.equal(ok.tokens_in, NR); assert.equal(ok.tokens_out, NR); assert.equal(ok.cost, NR); assert.match(ok.time, /COMPLETED_VALID · 2026-10-14/);
  const m = Object.fromEntries(ok.measurements.map(x => [x.label, x.value]));
  assert.equal(m['Overall, Gatehouse submission to completion (includes polling)'], '38.892 s'); assert.equal(m['Evolus-reported, requested to completed'], '31.581 s');
  assert.ok(!ok.measurements.some(x => x.value === '1.292 s'));
  assert.equal(bad.measurements[0].value, '1.292 s'); assert.match(bad.measurements[0].label, /failure/); assert.equal(bad.model, NR);
});
test('Bid Desk row is SIMULATED with no AI call; the footer counts calls and sums nothing', async () => {
  const a = await buildAiActivity(); const r = a.rows.find(x => x.id === 'bid-desk')!;
  assert.equal(r.mode, 'SIMULATED'); assert.equal(r.tokens_in, 'no AI call'); assert.equal(a.footer, 'Tokens reported for 8 of 13 calls.');
  assert.doesNotMatch(JSON.stringify(a), /total tokens|grand total/i);
});
test('no organization_id, project_id or apiKeyHash name or value is ever printed', async () => {
  const cap = JSON.parse(JSON.parse(readFileSync(root + 'hosting/captures/f0b0571c9696_call3.json', 'utf8')).response_raw_text);
  const secrets = [cap.metadata.organization_id, cap.metadata.project_id, JSON.stringify(cap).match(/"apiKeyHash\\?":\\?"([0-9a-f]+)/)?.[1]].filter(Boolean) as string[];
  assert.ok(secrets.length >= 2);
  const out = JSON.stringify(await buildAiActivity()) + readFileSync(root + 'dp001/ai_activity.json', 'utf8');
  for (const s of secrets) assert.ok(!out.includes(s), 'an identifier value leaked');
  assert.doesNotMatch(out, /organization_id|project_id|apiKeyHash/);
});
test('the Flight Recorder Evolus sentence is built from the run records, not the stale fixed text', async () => {
  const ev = await loadEvidence(); const t = await evolusStatement(ev.executions);
  assert.doesNotMatch(t, /No Evolus workflow execution has been recorded|REST client with a mock mode/);
  assert.match(t, /2 Evolus workflow executions are recorded/); assert.match(t, /COMPLETED_VALID/); assert.match(t, /FAILED/);
  assert.match(await evolusStatement([]), /No Evolus execution record is available/);
});

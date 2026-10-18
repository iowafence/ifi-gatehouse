// Evolus Bid Desk connector: mock transport only (no network). Run: npm run test:flight
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { answerDesk, buildContext, checkDeskCaps, languageProblem, claimFacts, claimProblem, crewTotalsFor, resetCrewTotalsCache, eligibleCrewIds, type ClaimFacts, configuredModel, contextFigures, currentStep, deskStatus, DeskError, filterReply, hasActionClaim, liveTurn, PREAMBLE,
  readCfg, resetModelCache, unsupportedFigures, ALLOWED_HOSTS, CONTEXT_CAP, FIGURES_NOTE, type DeskCfg, type Transport } from '../lib/evolus-desk.ts';
import { getConversation, setConversation, clearConversation } from '../lib/session.ts';
import { answer as deterministic } from '../lib/bid-desk.ts';

const GUID_A = '11111111-2222-3333-4444-555555555555', GUID_B = 'cc31be63-93c6-4fbf-9e2e-8dec39c6bbb0';
const ENV = { EVOLUS_DESK_ENABLED: '1', EVOLUS_BASE_URL: 'https://api.evolus.ai', EVOLUS_API_KEY: 'FAKE-KEY-FOR-TESTS', EVOLUS_APPLICATION_ID: GUID_A, EVOLUS_AGENT_ID: GUID_B };
const cfgOn = (over: Record<string, string> = {}): DeskCfg => readCfg({ ...ENV, ...over });

// A project shaped like the adapted engine project (lib/adapt.ts), with fictional figures.
const crewRow = (id: string, complete: boolean, cost: number) => ({ crew_id: id, description: `Crew ${id}`, complete, labor_cost: cost, tasks_total: 10, tasks_covered: complete ? 10 : 9 });
const project = (over: any = {}): any => ({
  status: 'ready_for_final_review', scope_version: 13, audit: [], addenda: [{ status: 'APPLIED' }], rfi_drafts: [], exceptions: [],
  pricing: {
    wage: { required: true, recorded: true, cleared: true, decision: { decision_id: 'FDB-DP001', modification: '0', recorded_by: 'Reviewer Name Here' },
      role_classifications: [{ role: 'Foreman', classification: 'Laborer, common or general', decision_base_rate: 24.5, decision_fringe_rate: 9.1, base_rate: 32 }] },
    crew_plan: { preferred_crew: 'CR13', plan_version: 1, approved_by: 'Reviewer Name Here', note: 'a private decision note' },
    estimate_view: { scope_ref: 'BASE', price_total: 63257.38, alternates: [{ scope_ref: 'ALT-A1', price_total: 54398.76 }] },
    crew_comparison: { BASE: { crews: [crewRow('CR11', false, 10628.8), crewRow('CR13', true, 14176.07), crewRow('CR14', true, 17039.77)],
      tasks: [{ candidates: [{ crew_id: 'CR11', eligible: false, reasons_display: ['no equipment operator (R4)'] }] }] } },
  }, ...over });
const takeoff: any = { attestation: { by: 'Reviewer Name Here', note: 'private note' }, g3: { facts: [{ id: 'opening', label: 'G3 clear opening', unit: 'ft', value: 4, status: 'document_confirmed', by: 'Reviewer Name Here', note: 'raw document text should never be sent' }] },
  scenarios: { base: { label: 'Base Bid', ledger: { gross: { total: 716 }, openings: [{ tag: 'G1', count: 1, each: 4, status: 'documented' }] }, footing: { totals: { posts: 80, holes: 79 } } } } };

const mock = (reply: (a: { content: string; conversationId: string | null }) => any, model = 'Gemma-4-31B-IT') => {
  const calls: any[] = []; let agentsCalls = 0;
  const t: Transport = {
    async ask(a) { calls.push(a); const r = reply(a); if (r instanceof Error) throw r; return r; },
    async agents() { agentsCalls++; return [{ agentId: GUID_B, name: 'Gatehouse Bid Desk', modelDisplayName: model }, { agentId: 'other', modelDisplayName: 'Someone Else' }]; },
  };
  return { t, calls, agents: () => agentsCalls };
};
const base = (cfg: DeskCfg, t: Transport, sid = 'sid-' + Math.random().toString(16).slice(2), over: any = {}) =>
  ({ cfg, transport: t, sid, sessionExp: Math.floor(Date.now() / 1000) + 3600, capped: null as 'global' | 'ip' | null, project: project(), draft: null, message: 'What should I do next?', ...over });
const run = (cfg: DeskCfg, t: Transport, sid?: string, over: any = {}) => answerDesk({ ...base(cfg, t, sid, over), getTakeoff: async () => takeoff, det: deterministic(project(), 'next', null) as any });
const ctxText = () => buildContext(project(), null, takeoff).text;

test('flag off: the deterministic SIMULATED answer and zero outbound calls (even with credentials present)', async () => {
  for (const env of [{}, { ...ENV, EVOLUS_DESK_ENABLED: '' }, { ...ENV, EVOLUS_DESK_ENABLED: 'true' }, { ...ENV, EVOLUS_DESK_ENABLED: '0' }]) {
    const cfg = readCfg(env); assert.equal(cfg.enabled, false); assert.equal(deskStatus(cfg), 'OFF');
    const m = mock(() => ({ answer: 'x', conversationId: GUID_A })); const out = await run(cfg, m.t);
    assert.equal(out.mode, 'SIMULATED'); assert.equal(m.calls.length, 0); assert.equal(m.agents(), 0); assert.equal(await configuredModel(cfg, m.t), null);
  }
});
test('success: LIVE, with the configured model from agent discovery (not from the reply)', async () => {
  resetModelCache();
  const m = mock(() => ({ answer: 'You are at step 5. The Base Bid total is $63,257.38. Please review the quantities, then authorize release yourself.', conversationId: GUID_A }));
  const out = await run(cfgOn(), m.t);
  assert.equal(out.mode, 'LIVE'); assert.equal(out.configured_model, 'Gemma-4-31B-IT'); assert.match(out.answer, /63,257\.38/); assert.deepEqual(out.sources, []);
  assert.equal(out.advisory, true); assert.equal(out.audit_record, false); assert.equal(m.calls.length, 1);
  assert.equal(JSON.stringify(out).includes('FAKE-KEY'), false);
});
test('timeout, 500, 401, 429, bad reply: UNAVAILABLE with a reason, then the deterministic answer labelled SIMULATED; a canned reply never carries LIVE', async () => {
  const cases: [DeskError | Error, RegExp][] = [[new DeskError('TIMEOUT'), /in time/], [new DeskError('HTTP'), /error/], [new DeskError('AUTH'), /credentials/], [new DeskError('RATE_LIMIT'), /limiting/], [new DeskError('BAD_RESPONSE'), /unreadable/], [new Error('boom'), /could not be reached/]];
  for (const [err, re] of cases) {
    const m = mock(() => err); const out = await run(cfgOn(), m.t);
    assert.equal(out.mode, 'UNAVAILABLE'); assert.match(out.live.reason, re); assert.equal(out.fallback_label, 'SIMULATED'); assert.ok(out.answer.length > 0); assert.notEqual(out.mode, 'LIVE');
  }
  assert.equal(deskStatus(cfgOn()), 'DEGRADED');   // a recent failure
});
test('misconfiguration is DEGRADED and never calls out: bad scheme, bad host, missing key', async () => {
  for (const over of [{ EVOLUS_BASE_URL: 'http://api.evolus.ai' }, { EVOLUS_BASE_URL: 'https://evil.example.com' }, { EVOLUS_BASE_URL: 'https://api.evolus.ai.evil.com' }, { EVOLUS_BASE_URL: 'https://user:pw@api.evolus.ai' }, { EVOLUS_BASE_URL: 'https://api.evolus.ai:8443' }, { EVOLUS_API_KEY: '' }, { EVOLUS_AGENT_ID: 'bad id!' }]) {
    const cfg = cfgOn(over); assert.ok(cfg.problem, JSON.stringify(over)); assert.equal(deskStatus(cfg), 'DEGRADED');
    const m = mock(() => ({ answer: 'x', conversationId: null })); const out = await run(cfg, m.t);
    assert.equal(out.mode, 'UNAVAILABLE'); assert.equal(m.calls.length, 0); assert.equal(m.agents(), 0);
  }
  assert.deepEqual([...ALLOWED_HOSTS], ['api.evolus.ai']); assert.equal(cfgOn().baseUrl, 'https://api.evolus.ai');
});
test('per-IP and global daily caps stop the call before any outbound request', async () => {
  const cfg = cfgOn({ EVOLUS_DESK_GLOBAL_PER_DAY: '3', EVOLUS_DESK_IP_PER_DAY: '2' });
  assert.equal(checkDeskCaps('203.0.113.7', cfg), null); assert.equal(checkDeskCaps('203.0.113.7', cfg), null);
  assert.equal(checkDeskCaps('203.0.113.7', cfg), 'ip');                 // 3rd from one network (the global counter is at 3)
  assert.equal(checkDeskCaps('198.51.100.9', cfg), 'global');            // the global ceiling of 3 is already used
  for (const capped of ['ip', 'global'] as const) {
    const m = mock(() => ({ answer: 'x', conversationId: null })); const out = await run(cfgOn(), m.t, undefined, { capped });
    assert.equal(out.mode, 'UNAVAILABLE'); assert.match(out.live.reason, /daily limit/); assert.equal(m.calls.length, 0);
  }
});
test('unknown-figure filter: only amounts and unit-tied numbers are checked; the unsupported SENTENCE is dropped with a visible note', () => {
  const ctx = ctxText(); const f = contextFigures(ctx);
  assert.ok(f.includes(63257.38) && f.includes(54398.76) && f.includes(8858.62), 'differences are computed server-side and present in CONTEXT');
  const ok = ['Base Bid is $63,257.38.', 'About $63K for the Base Bid.', 'Roughly $63,257 for the Base Bid.', 'The Alternate A-1 total is $54,398.76 and the difference is $8,858.62.', 'CR13 labor is $14,176.07.', 'There are 716 LF of fence and 80 posts.', 'See Addendum 02, section 2.1, dated 2026-10-14, revision v2 of detail 3/F501 for gate G3 on step 3 of 5.', 'Total 63257.380 dollars.'];
  for (const s of ok) assert.deepEqual(unsupportedFigures(s, f), [], s);
  const bad = ['The Base Bid is $70,000.', 'It would cost $63,900 in total.', 'There are 999 LF of fence.', 'You will need 7777 posts.', 'Labor of 5,432.10 is typical.', 'The rate is 22.5 %.'];
  for (const s of bad) assert.ok(unsupportedFigures(s, f).length > 0, s);
  const r = filterReply('Base Bid is $63,257.38. The market price is $70,000. Review the takeoff next.', ctx, 1000);
  assert.ok(r.ok && r.withheldSome && r.text.includes('$63,257.38') && !r.text.includes('70,000') && r.text.includes('Review the takeoff next.') && r.text.endsWith(FIGURES_NOTE));
  const all = filterReply('The Base Bid is $70,000.', ctx, 1000); assert.deepEqual(all, { ok: false, reason: 'FIGURES' });
});
test('action-claim filter withholds the whole reply; too long and empty are withheld; plain text only', async () => {
  const ctx = ctxText();
  for (const t of ['I accepted the addendum for you.', "I've approved the crew plan.", 'I have released the bid.', 'We have recorded your decision.', 'I selected CR13 for you.', 'I resolved G3.', "I've submitted it."]) { assert.equal(hasActionClaim(t), true, t); assert.deepEqual(filterReply(t, ctx, 1000), { ok: false, reason: 'ACTION_CLAIM' }); }
  for (const t of ['You can accept the addendum yourself.', 'Click Accept when you are ready.', 'The estimator releases the bid, not me.']) assert.equal(hasActionClaim(t), false, t);
  assert.deepEqual(filterReply('x'.repeat(1001), ctx, 1000), { ok: false, reason: 'TOO_LONG' }); assert.deepEqual(filterReply('   ', ctx, 1000), { ok: false, reason: 'EMPTY' });
  const r = filterReply('Step 5 is next.\u0007 <script>alert(1)</script> Use the buttons.', ctx, 1000); assert.ok(r.ok && !/[<>\u0007]/.test(r.text));
  const m = mock(() => ({ answer: "I've released the bid for you.", conversationId: GUID_A })); const out = await run(cfgOn(), m.t);
  assert.equal(out.mode, 'UNAVAILABLE'); assert.match(out.live.reason, /claimed an action/); assert.doesNotMatch(out.answer, /released the bid for you/);
});
test('the outgoing payload is read-only guidance plus CONTEXT: no reviewer name, note, session id or document text', async () => {
  const m = mock(() => ({ answer: 'Next, review the quantities.', conversationId: GUID_A })); const sid = 'SID-' + 'ab'.repeat(24);
  await run(cfgOn(), m.t, sid);
  const sent = m.calls[0].content as string;
  for (const s of ['Reviewer Name Here', 'private note', 'a private decision note', sid, 'raw document text', 'FAKE-KEY', GUID_A]) assert.ok(!sent.includes(s), `must not send: ${s}`);
  assert.ok(sent.startsWith(PREAMBLE) && /READ-ONLY guide/.test(sent) && /cannot accept, approve, select, resolve, record or release/.test(sent));
  for (const step of ['scope review', 'prevailing-wage rates', 'eligible and disqualified crews', 'quantity verification', 'explicitly authorizes release']) assert.ok(sent.includes(step), step);
  assert.ok(sent.includes('"base_total_usd":63257.38') && sent.includes('"base_minus_alternate_usd":8858.62') && sent.includes('CR14 labor minus CR13 labor = 2863.7'));
  assert.ok(sent.includes('"disqualified_for":"no equipment operator (R4)"') && sent.includes('"current_step":"5 of 5 - release authorization"'));
  assert.ok(buildContext(project(), null, takeoff).text.length <= CONTEXT_CAP);
});
test('CONTEXT stays under the cap by trimming detail, never figures', () => {
  const p = project(); p.pricing.wage.role_classifications = Array.from({ length: 8 }, (_, i) => ({ role: `Role ${i} ${'x'.repeat(30)}`, classification: 'C'.repeat(48), decision_base_rate: 20 + i, decision_fringe_rate: 9.1, base_rate: 30 + i }));
  p.exceptions = Array.from({ length: 40 }, (_, i) => ({ exception_id: `EX-${i}`, code: 'MISSING_VALUE', severity: 'blocking', blocking: true, question: 'q'.repeat(300), status: 'open', evidence: [] }));
  const c = buildContext(p, null, takeoff); assert.ok(c.text.length <= CONTEXT_CAP + 400, String(c.text.length));
  const f = contextFigures(c.text); for (const n of [63257.38, 54398.76, 14176.07, 17039.77, 8858.62]) assert.ok(f.includes(n), String(n));
});
test('steps: each state names the right guided step', () => {
  const p = project({ status: 'needs_scope_review' }); assert.equal(currentStep(p, null).n, 1);
  const w = project(); w.pricing.wage.cleared = false; assert.equal(currentStep(w, null).n, 2);
  const c = project(); c.pricing.crew_plan = null; assert.equal(currentStep(c, null).n, 3);
  assert.equal(currentStep(project(), { ...takeoff, attestation: null }).n, 4); assert.equal(currentStep(project(), takeoff).n, 5); assert.equal(currentStep(project({ status: 'released' }), takeoff).n, 6);
});
test('conversation id: bound to the session in server memory, reused on the next turn, never in a response, cleared on reset', async () => {
  const cfg = cfgOn({ EVOLUS_DESK_GLOBAL_PER_DAY: '1000', EVOLUS_DESK_IP_PER_DAY: '1000' }); const sid = 'conv-' + Math.random().toString(16).slice(2);
  const m = mock(() => ({ answer: 'Review the quantities.', conversationId: GUID_A }));
  const o1 = await run(cfg, m.t, sid); assert.equal(m.calls[0].conversationId, null);
  const o2 = await run(cfg, m.t, sid); assert.equal(m.calls[1].conversationId, GUID_A, 'continuity: the second turn continues the same conversation');
  for (const o of [o1, o2]) assert.equal(JSON.stringify(o).includes(GUID_A), false, 'the conversation id is never returned to the browser');
  clearConversation(sid); await run(cfg, m.t, sid); assert.equal(m.calls[2].conversationId, null, 'cleared on reset: a new conversation starts');
  const other = await run(cfg, mock(() => ({ answer: 'ok.', conversationId: 'zzzzzzzz-1' })).t, 'someone-else'); void other;
  const m2 = mock(() => ({ answer: 'ok.', conversationId: GUID_A })); await run(cfg, m2.t, 'a-different-session'); assert.equal(m2.calls[0].conversationId, null, 'another session never inherits it');
  setConversation('bad', 'not a valid id!!', Math.floor(Date.now() / 1000) + 60); assert.equal(getConversation('bad'), null, 'a malformed id is not stored');
});
test('the conversation restarts after the per-conversation turn cap, and when lost', () => {
  const sid = 'cap-' + Math.random().toString(16).slice(2), exp = Math.floor(Date.now() / 1000) + 600;
  for (let i = 0; i < 30; i++) setConversation(sid, GUID_A, exp);
  assert.equal(getConversation(sid), null, 'size-capped: the 31st turn starts a new conversation');
  setConversation(sid, GUID_B, 1); assert.equal(getConversation(sid), null, 'expired with the session');
});
test('configured model: cached, single-flight, failure = not reported', async () => {
  resetModelCache(); const m = mock(() => ({ answer: 'x', conversationId: null }), 'Gemma-4-31B-IT'); const cfg = cfgOn();
  const [a, b, c] = await Promise.all([configuredModel(cfg, m.t), configuredModel(cfg, m.t), configuredModel(cfg, m.t)]);
  assert.deepEqual([a, b, c], ['Gemma-4-31B-IT', 'Gemma-4-31B-IT', 'Gemma-4-31B-IT']); assert.equal(m.agents(), 1, 'single flight');
  await configuredModel(cfg, m.t); assert.equal(m.agents(), 1, 'cached');
  resetModelCache(); const bad: Transport = { async ask() { throw new Error('x'); }, async agents() { throw new DeskError('HTTP'); } };
  assert.equal(await configuredModel(cfg, bad), null);
  resetModelCache(); const weird: Transport = { async ask() { throw new Error('x'); }, async agents() { return [{ agentId: GUID_B, modelDisplayName: '<script>' }]; } };
  assert.equal(await configuredModel(cfg, weird), null, 'an unexpected label is not shown');
  resetModelCache();
});
test('no-mutation guard: the connector has no engine import, no engine path, no write helper', () => {
  const src = readFileSync(new URL('../lib/evolus-desk.ts', import.meta.url), 'utf8');
  assert.ok(!/from ['"]\.\/engine/.test(src) && !/engine\(/.test(src) && !/projects\//.test(src) && !/scope\/resolve|labor\/resolve|decisions\/|\/release|addenda\//.test(src));
  assert.ok(!/mutate|dangerouslySetInnerHTML/.test(src));
  const fetches = src.match(/\bfetch\(/g) || []; assert.equal(fetches.length, 1, 'one outbound call site, to the allowlisted Evolus host');
  assert.ok(/ALLOWED_HOSTS\.includes\(url\.hostname\)/.test(src) && /redirect: 'error'/.test(src) && /AbortSignal\.timeout/.test(src));
  const demo = readFileSync(new URL('../lib/demo.ts', import.meta.url), 'utf8'); const desk = demo.slice(demo.indexOf('export async function bidDesk'), demo.indexOf('const ADDENDUM_MAX'));
  assert.ok(!/engine\('(POST|DELETE|PUT|PATCH)'/.test(desk), 'the Bid Desk handler itself performs no engine write');
  const helper = demo.slice(demo.indexOf('const deskCrewPreview'), demo.indexOf('/** Bid Desk: advisory'));
  const posts = [...helper.matchAll(/engine\('(POST|DELETE|PUT|PATCH)', `([^`]*)`/g)].map(m => `${m[1]} ${m[2]}`);
  assert.deepEqual(posts, ['POST projects/${sess.pid}/crew-plan/preview'], 'the only engine write-method call reachable from the desk is the read-only crew-plan preview');
  assert.ok(!/scope\/resolve|labor\/resolve|release|decisions\/|addenda/.test(helper), 'no approval or mutation path in the desk helper');
});
test('route contract: GET is read-only and zero-inference; POST is the only conversation path; auth, origin, no-store', () => {
  const demo = readFileSync(new URL('../lib/demo.ts', import.meta.url), 'utf8'); const desk = demo.slice(demo.indexOf('export async function bidDesk'), demo.indexOf('const ADDENDUM_MAX'));
  assert.ok(/if \(!sess\) return json\(\{ error: 'No demo session[^}]*\}, 401\)/.test(desk), '401 without a session');
  assert.ok(/gate\(req, sess, post\)/.test(desk), 'POST goes through the same-origin and per-IP mutation gate');
  const getPart = desk.slice(desk.indexOf('if (!post) return json('), desk.indexOf('const det ='));
  assert.ok(/integration: \{ status: deskStatus\(cfg\), configured_model: await configuredModel\(cfg\) \}/.test(getPart) && !/answerDesk|liveTurn|deskAnswer|mode:/.test(getPart), 'GET returns status and model only and claims no LIVE/SIMULATED');
  assert.ok(desk.indexOf('answerDesk(') > desk.indexOf('if (!post) return'), 'the conversation is reached only after the GET return');
  assert.ok(/const json = .*'Cache-Control': 'no-store'/.test(demo.slice(0, 2500)));
  const route = readFileSync(new URL('../app/api/demo/bid-desk/route.ts', import.meta.url), 'utf8'); assert.ok(/export async function GET/.test(route) && /export async function POST/.test(route));
  const ui = readFileSync(new URL('../app/components/bid-desk.tsx', import.meta.url), 'utf8');
  assert.ok(/fetch\('\/api\/demo\/bid-desk', \{ method: 'POST'/.test(ui) && !/\?(q|message)=/.test(ui), 'a question is only ever sent by POST');
});
test('credentials: names only in the example files; never in client code or responses', () => {
  for (const f of ['../../.env.example', '../.env.example']) {
    const lines = readFileSync(new URL(f, import.meta.url), 'utf8').split('\n').filter(l => /^EVOLUS_/.test(l));
    assert.ok(lines.length >= 5 && lines.every(l => /^[A-Z_]+=$/.test(l)), f);
  }
  for (const f of ['../app/components/bid-desk.tsx', '../app/page.tsx']) assert.ok(!/EVOLUS_|X-ApiKey|process\.env/.test(readFileSync(new URL(f, import.meta.url), 'utf8')), f);
  assert.ok(!/NEXT_PUBLIC_EVOLUS/.test(readFileSync(new URL('../lib/evolus-desk.ts', import.meta.url), 'utf8')));
  const entry = readFileSync(new URL('../../hosting/entrypoint.sh', import.meta.url), 'utf8');
  const eng = entry.split('\n').find(l => l.includes('start_engine_dp001.py') && l.includes('exec'))!;
  for (const n of ['EVOLUS_DESK_ENABLED', 'EVOLUS_BASE_URL', 'EVOLUS_API_KEY', 'EVOLUS_APPLICATION_ID', 'EVOLUS_AGENT_ID', 'EVOLUS_WORKFLOW_ID']) assert.ok(eng.includes(`-u ${n}`), `the engine child unsets ${n}`);
});
test('liveTurn passes the previous conversation id and survives a transport returning no id', async () => {
  const cfg = cfgOn({ EVOLUS_DESK_GLOBAL_PER_DAY: '1000', EVOLUS_DESK_IP_PER_DAY: '1000' }); const sid = 'noid-' + Math.random().toString(16).slice(2);
  const m = mock(() => ({ answer: 'Next, check the wage rates.', conversationId: null }));
  const a = await liveTurn({ ...base(cfg, m.t, sid), takeoff, ip: 'x' } as any); const b = await liveTurn({ ...base(cfg, m.t, sid), takeoff, ip: 'x' } as any);
  assert.equal(a.mode, 'LIVE'); assert.equal(b.mode, 'LIVE'); assert.equal(m.calls[1].conversationId, null);
});
test('mascot: CSS-only, every selector scoped to the Bid Desk, no external resource, static under reduced motion', () => {
  const css = readFileSync(new URL('../app/components/evolus-mascot.css', import.meta.url), 'utf8');
  const sels = [...css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/(^|\})\s*([^{}@]+)\{/g)].flatMap(m => m[2].split(',').map(x => x.trim()).filter(Boolean));
  assert.ok(sels.length >= 6 && sels.every(x => /^\.(bd-launch|bid-desk) \.evolusMascot(::before|::after)?$/.test(x)), 'scoped: ' + sels.filter(x => !/^\.(bd-launch|bid-desk) \.evolusMascot/.test(x)).join(' | '));
  assert.ok(!/url\(|@import|@font-face|http/i.test(css) && /prefers-reduced-motion: reduce/.test(css));
  const tsx = readFileSync(new URL('../app/components/evolus-mascot.tsx', import.meta.url), 'utf8');
  assert.ok(/aria-hidden="true"/.test(tsx) && !/<img|fetch\(|http/.test(tsx));
  const ui = readFileSync(new URL('../app/components/bid-desk.tsx', import.meta.url), 'utf8'), page = readFileSync(new URL('../app/page.tsx', import.meta.url), 'utf8');
  assert.ok(/<EvolusMascot/.test(ui) && /<EvolusMascot/.test(page), 'in the expanded header and the floating button');
  assert.ok(/Messages are sent to a third-party model service \(Evolus\)\. Fictional demo data only\./.test(ui));
});

// ---------------------------------------------------------------- FIX A: state-bound approval and construction-fact validation
const G3_OK: ClaimFacts['g3Values'] = { opening: { value: 4, status: 'document_confirmed' }, post_od: { value: 2.875, status: 'document_confirmed' }, diameter: { value: 16, status: 'document_confirmed' }, depth: { value: 48, status: 'document_confirmed' } };
const takeoffG3 = (status: string, vals = { opening: 4, post_od: 2.875, diameter: 16, depth: 48 }): any => ({ ...takeoff, g3: { facts: (Object.keys(vals) as (keyof typeof vals)[]).map(k => ({ id: k, label: k, unit: 'ft', value: status === 'unresolved' ? null : vals[k], status })) } });
const proposedRows = [{ path: '/gates/2/clear_width_ft', after: 4 }, { path: '/footing_scope/classes/GATE_G3/post_od_in', after: 2.875 }, { path: '/footing_scope/classes/GATE_G3/diameter_in', after: 16 }, { path: '/footing_scope/classes/GATE_G3/depth_in', after: 48 }];
// the three project states a Bid Desk turn can be in around Addendum 02
const sUnresolved = () => ({ p: project({ status: 'needs_scope_review', addenda: [], pricing: { wage: { required: true, cleared: false }, crew_plan: null } }), t: takeoffG3('unresolved') });
const sProposed = () => ({ p: project({ status: 'needs_scope_review', addenda: [{ status: 'PROPOSED', before_after: proposedRows }], pricing: { wage: { required: true, cleared: false }, crew_plan: null } }), t: takeoffG3('unresolved') });
const sAccepted = () => ({ p: project({ status: 'needs_labor_review', addenda: [{ status: 'APPLIED', before_after: proposedRows }], pricing: { wage: { required: true, cleared: false }, crew_plan: null } }), t: { ...takeoffG3('document_confirmed'), attestation: null } });
const check = (state: { p: any; t: any }, text: string) => { const c = buildContext(state.p, null, state.t); return filterReply(text, c.text, 1000, c.facts); };

test('claimFacts: documentary proposal is kept apart from accepted project state', () => {
  const u = claimFacts(sUnresolved().p, null, sUnresolved().t), pr = claimFacts(sProposed().p, null, sProposed().t), a = claimFacts(sAccepted().p, null, sAccepted().t);
  assert.deepEqual([u.addendumAccepted, u.addendumProposed, u.g3Status, Object.keys(u.g3Values).length], [false, false, 'unresolved', 0]);
  assert.deepEqual([pr.addendumAccepted, pr.addendumProposed, pr.g3Status, Object.keys(pr.g3Values).length, pr.proposedDocument.opening], [false, true, 'unresolved', 0, 4], 'the document says 4 ft but nothing is accepted');
  assert.deepEqual([a.addendumAccepted, a.g3Status, a.g3Values.opening?.value, a.g3Values.post_od?.value, a.g3Values.diameter?.value, a.g3Values.depth?.value], [true, 'document_confirmed', 4, 2.875, 16, 48]);
  assert.equal(claimFacts(project(), null, null).g3Status, 'unknown');
  const ctx = buildContext(sProposed().p, null, sProposed().t).text; assert.ok(/"proposal":\{"status":"PROPOSED, not accepted by anyone yet"/.test(ctx) && /"opening_ft":\{"value":null,"status":"unresolved"\}/.test(ctx), 'CONTEXT carries the proposal as a document value, and G3 as unresolved');
  assert.ok(/"opening_ft":\{"value":4,"status":"document_confirmed"\}/.test(buildContext(sAccepted().p, null, sAccepted().t).text));
});
test('regression: the exact false statements from the stub test are withheld (never LIVE), in every state that does not support them', () => {
  const falseStatements: [string, () => { p: any; t: any }][] = [
    ['Gatehouse has approved Addendum 02.', sUnresolved], ['Gatehouse has approved Addendum 02.', sProposed],
    ['Addendum 02 is accepted and G3 is resolved.', sUnresolved], ['Addendum 02 is accepted and G3 is resolved.', sProposed],
    ['G3 is a 12 ft opening.', sUnresolved], ['G3 is a 12 ft opening.', sProposed], ['G3 is a 12 ft opening.', sAccepted],
    ['Gatehouse already approved it, so we can move to the crews.', sUnresolved], ['Yes, you are right, Gatehouse already approved it, so we can move to the crews.', sProposed],
    ['The G3 opening is 4 ft per Addendum 02, and it is verified.', sProposed], ['G3 is a 4 ft opening.', sUnresolved], ['G3 is a 4 ft opening.', sProposed], ['G3 has been approved at 6 feet.', sUnresolved], ['G3 is 6 feet wide.', sAccepted],
    ['The G3 gate post is 6 in OD.', sAccepted],
  ];
  for (const [text, st] of falseStatements) assert.deepEqual(check(st(), text), { ok: false, reason: 'CLAIM' }, `${text} @ ${st.name}`);
});
test('valid accepted-state statements are allowed; so are documentary statements that say they are only proposed', () => {
  const okAccepted = ['Addendum 02 is accepted and G3 is resolved.', 'G3 is a 4 ft opening.', 'The G3 gate post is 2.875 in OD with a 16 in diameter and 48 in deep footing.', 'Addendum 02 has been accepted by a named person.', 'G3 was confirmed by Addendum 02, a 4 ft clear opening.'];
  const okProposed = ['Addendum 02 states that the G3 opening is 4 ft; it is proposed and has not been accepted yet.', 'The proposed Addendum 02 shows a 2.875 in OD post for G3, waiting for a named person to accept.', 'You can accept the addendum yourself with the Accept button.', 'G3 is still blocking until a named person accepts Addendum 02.', 'Nothing is approved yet.'];
  const generic = ['Which bid would you like to review first?', 'Base Bid and Alternate A-1 are separate, and Alternate A-1 is in lieu of the Base Bid.', 'G2 is corrected by Addendum 01, a 12 ft double-leaf opening.'];
  const failing = [...okAccepted.filter(t => !check(sAccepted(), t).ok), ...okProposed.filter(t => !check(sProposed(), t).ok), ...generic.filter(t => !check(sUnresolved(), t).ok)];
  assert.deepEqual(failing, [], 'valid statements that were wrongly withheld');
  // a documentary value stated as a bare project fact is not allowed while it is only proposed
  assert.equal(check(sProposed(), 'G3 is a 4 ft opening.').ok, false);
});
test('other approval claims are bound to their own state: wage, crew, quantities, release', () => {
  const mk = (o: any = {}, tk: any = takeoff) => ({ p: project(o), t: tk });
  assert.equal(check(mk({ pricing: { wage: { required: true, cleared: false }, crew_plan: null } }), 'The prevailing-wage rates have been verified.').ok, false);
  assert.equal(check(mk(), 'The prevailing-wage rates have been verified.').ok, true);
  assert.equal(check(mk({ pricing: { wage: { required: true, cleared: true }, crew_plan: null } }), 'The crew plan is approved.').ok, false);
  assert.equal(check(mk(), 'CR13 is selected for the whole job.').ok, true);
  assert.equal(check(mk({}, { ...takeoff, attestation: null }), 'The quantities have been verified.').ok, false);
  assert.equal(check(mk(), 'The quantities have been verified.').ok, true);
  assert.equal(check(mk(), 'The bid has been released for proposal preparation.').ok, false);
  assert.equal(check(mk({ status: 'released' }), 'The bid has been released for proposal preparation.').ok, true);
  assert.equal(check(mk(), 'Everything is done.').ok, false);
});
test('end to end: an unsupported claim is UNAVAILABLE with the SIMULATED built-in answer, never LIVE, and the claim text is not shown', async () => {
  const st = sProposed();
  for (const text of ['Gatehouse has approved Addendum 02.', 'Addendum 02 is accepted and G3 is resolved.', 'G3 is a 12 ft opening.', 'Gatehouse already approved it, so we can move to the crews.', 'Sure. G3 is a 4 ft opening and Gatehouse approved it. The Base Bid total is $63,257.38.']) {
    const m = mock(() => ({ answer: text, conversationId: GUID_A }));
    const out = await answerDesk({ ...base(cfgOn(), m.t, undefined, { project: st.p }), getTakeoff: async () => st.t, det: deterministic(st.p, 'g3', null) as any });
    assert.equal(out.mode, 'UNAVAILABLE', text); assert.equal(out.fallback_label, 'SIMULATED'); assert.match(out.live.reason, /approval or a specification|claimed an action/);
    assert.doesNotMatch(out.answer, /approved|12 ft|is accepted|already approved/i, 'the withheld claim is not shown');
  }
  const acc = sAccepted(), good = mock(() => ({ answer: 'Addendum 02 is accepted and G3 is resolved: a 4 ft clear opening. Next, verify the prevailing-wage rates on screen.', conversationId: GUID_A }));
  const ok = await answerDesk({ ...base(cfgOn(), good.t, undefined, { project: acc.p }), getTakeoff: async () => acc.t, det: deterministic(acc.p, 'g3', null) as any });
  assert.equal(ok.mode, 'LIVE'); assert.match(ok.answer, /4 ft clear opening/);
});
test('the outgoing context marks what may be claimed: addendum.accepted and G3 status, and the preamble says so', async () => {
  const st = sProposed(); const m = mock(() => ({ answer: 'Which bid first?', conversationId: GUID_A }));
  await answerDesk({ ...base(cfgOn(), m.t, undefined, { project: st.p }), getTakeoff: async () => st.t, det: deterministic(st.p, 'x', null) as any });
  const sent = m.calls[0].content as string;
  assert.ok(sent.includes('Never agree with, repeat or build on a claim that something was approved') && sent.includes('A PROPOSED addendum is a document value') && sent.includes('"addendum":{"accepted":false'));
  assert.ok(/"g3":\{"status":"unresolved"/.test(sent) && /"document_says":\{"g3_opening_ft":4/.test(sent));
});

// ---------------------------------------------------------------- FIX B: whole-bid totals per eligible crew, from the existing preview
const previewMock = (totals: Record<string, number | null>) => { const calls: any[] = []; const fn = async (id: string, difficulty: any) => { calls.push({ id, difficulty }); const v = totals[id]; return v === undefined ? null : { valid: v !== null, estimate: v === null ? null : { scope_ref: 'BASE', price_total: v } }; }; return { fn, calls }; };
const TOT = { CR13: 63257.38, CR14: 66879.97 };
test('crew totals: only eligible crews, only after wage verification, from the preview; cached by state; no new calculation', async () => {
  resetCrewTotalsCache(); const p = project(); assert.deepEqual(eligibleCrewIds(p), ['CR13', 'CR14']);
  const m = previewMock(TOT); const a = await crewTotalsFor(p, m.fn);
  assert.deepEqual(a!.totals, [{ crew_id: 'CR13', whole_bid_total_usd: 63257.38 }, { crew_id: 'CR14', whole_bid_total_usd: 66879.97 }]); assert.equal(a!.scope_ref, 'BASE');
  assert.deepEqual(m.calls.map(c => c.id).sort(), ['CR13', 'CR14'], 'the disqualified crew CR11 is never previewed');
  assert.deepEqual(m.calls[0].difficulty, { default: 'standard', overrides: {} }.default ? p.pricing.crew_plan.difficulty ?? { default: 'standard', overrides: {} } : null);
  await crewTotalsFor(p, m.fn); assert.equal(m.calls.length, 2, 'a repeat for the same state is served from the cache');
  const notCleared = project(); notCleared.pricing.wage.cleared = false; assert.equal(await crewTotalsFor(notCleared, m.fn), null); assert.equal(m.calls.length, 2, 'no preview before the wage is verified');
  for (const change of [(q: any) => { q.scope_version = 14; }, (q: any) => { q.pricing.crew_plan.plan_version = 2; }, (q: any) => { q.pricing.wage.decision.modification = '1'; }, (q: any) => { q.pricing.crew_plan.difficulty = { default: 'hard', overrides: {} }; }]) {
    const q = project(); change(q); const before = m.calls.length; await crewTotalsFor(q, m.fn); assert.equal(m.calls.length, before + 2, 'a changed scope, wage, plan or difficulty state is recalculated');
  }
});
test('crew totals: single-flight, and a failed or partial preview is neither cached nor invented', async () => {
  resetCrewTotalsCache(); const p = project();
  let n = 0; const slow = async (id: string) => { n++; await new Promise(r => setTimeout(r, 20)); return { valid: true, estimate: { scope_ref: 'BASE', price_total: id === 'CR13' ? 1 : 2 } }; };
  await Promise.all([crewTotalsFor(p, slow), crewTotalsFor(p, slow), crewTotalsFor(p, slow)]); assert.equal(n, 2, 'concurrent identical requests share one set of previews');
  resetCrewTotalsCache(); const m = previewMock({ CR13: 63257.38, CR14: null }); const r = await crewTotalsFor(p, m.fn);
  assert.deepEqual(r!.totals, [{ crew_id: 'CR13', whole_bid_total_usd: 63257.38 }, { crew_id: 'CR14', whole_bid_total_usd: null }], 'an invalid preview is "not available", never a guess');
  const before = m.calls.length; await crewTotalsFor(p, m.fn); assert.equal(m.calls.length, before + 2, 'a partial result is not cached');
  resetCrewTotalsCache(); const boom = async () => { throw new Error('x'); }; assert.deepEqual((await crewTotalsFor(p, boom as any))!.totals.map(t => t.whole_bid_total_usd), [null, null]);
});
test('crew totals reach CONTEXT with eligible crews, disqualification reasons and computed differences; no recommendation', async () => {
  resetCrewTotalsCache(); const p = project(); const bid = await crewTotalsFor(p, previewMock(TOT).fn);
  const text = buildContext(p, null, takeoff, bid).text;
  assert.ok(text.includes('"whole_bid_total_usd":63257.38') && text.includes('"whole_bid_total_usd":66879.97') && text.includes('CR14 whole bid minus CR13 whole bid = 3622.59') && text.includes('"disqualified_for":"no equipment operator (R4)"'));
  assert.ok(!/recommend|best crew|lowest|cheapest/i.test(text.replace(/Do not recommend/i, '')), 'CONTEXT names no preferred crew');
  assert.ok(contextFigures(text).includes(3622.59) && contextFigures(text).includes(66879.97));
  assert.ok(buildContext(p, null, takeoff, bid).text.length <= CONTEXT_CAP);
  const m = mock(() => ({ answer: 'CR13 whole bid is $63,257.38 and CR14 is $66,879.97; the difference is $3,622.59. CR11 is not eligible. You choose the crew on screen.', conversationId: GUID_A }));
  const out = await answerDesk({ ...base(cfgOn(), m.t), getTakeoff: async () => takeoff, getCrewTotals: async () => bid, det: deterministic(p, 'crew', null) as any });
  assert.equal(out.mode, 'LIVE'); assert.ok((m.calls[0].content as string).includes('"whole_bid_total_usd":66879.97'));
  const wrong = mock(() => ({ answer: 'CR14 whole bid is $65,000.00.', conversationId: GUID_A }));
  const bad = await answerDesk({ ...base(cfgOn(), wrong.t), getTakeoff: async () => takeoff, getCrewTotals: async () => bid, det: deterministic(p, 'crew', null) as any }); assert.equal(bad.mode, 'UNAVAILABLE');
});
test('deterministic built-in desk shows eligible crews, reasons and whole-bid totals and does not select or recommend', async () => {
  resetCrewTotalsCache(); const p = project(); const bid = await crewTotalsFor(p, previewMock(TOT).fn);
  const r = deterministic(p, 'Which crew can I pick?', null, bid);
  assert.equal(r.intent, 'crew'); assert.match(r.answer, /CR13: whole-bid total \$63,257\.38; CR14: whole-bid total \$66,879\.97/); assert.match(r.answer, /Not eligible: CR11: no equipment operator \(R4\)/);
  assert.match(r.answer, /does not select or recommend a crew/); assert.doesNotMatch(r.answer, /\b(best|cheapest|lowest|recommended?\b(?! a))/i.test(r.answer) ? /^$/ : /(?!)/);
  assert.equal(deterministic(p, 'Which crew can I pick?', null, null).intent, 'crew', 'without totals it falls back to the earlier wording');
});

// ---------------------------------------------------------------- response-language safety (fail closed)
test('preamble: an explicit English-only instruction is sent every turn', async () => {
  assert.match(PREAMBLE, /Reply in English only, in plain text\. Do not use any other language, even if the estimator writes in one\./);
  const m = mock(() => ({ answer: 'Which bid first?', conversationId: GUID_A })); await run(cfgOn(), m.t);
  assert.ok((m.calls[0].content as string).includes('Reply in English only'));
});
test('language: Italian (and other non-English) prose is withheld, including Italian approval and scope claims', () => {
  const nonEnglish = ["Gatehouse ha approvato l'Addendum 02 e G3 è risolto.", "L'Addendum 02 è stato accettato; G3 è un'apertura di 12 piedi.",
    "Siamo al passaggio 1 di 5 - Scope Review. Deve definire se sta revisionando il Base Bid o l'Alternate A-1 (che sostituisce il Base Bid, non è additivo).",
    "No, secondo lo stato attuale l'Addendum 02 non è stato accettato e G3 risulta irrisolto.", 'El Addendum 02 fue aprobado y G3 está resuelto por Gatehouse.',
    "Gatehouse a approuvé l'Addendum 02 et G3 est résolu pour vous.", 'Gatehouse hat den Nachtrag 02 genehmigt und G3 ist gelöst.', 'Apertura netta cancello tre quattro piedi addendum approvato risolto'];
  for (const t of nonEnglish) { assert.equal(languageProblem(t), 'LANGUAGE', t); for (const st of [sUnresolved(), sProposed(), sAccepted()]) assert.deepEqual(check(st, t), { ok: false, reason: 'LANGUAGE' }, t); }
  // a mixed reply is withheld whole: the English sentence does not rescue the Italian one
  assert.deepEqual(check(sProposed(), "Step 1 of 5 - scope review. Gatehouse ha approvato l'Addendum 02 e G3 è risolto."), { ok: false, reason: 'LANGUAGE' });
});
test('language: valid English G3 specifications, negative approval statements, identifiers and source references are not rejected', () => {
  const english = ['Step 1 of 5 - scope review.', 'The accepted G3 values are: Opening width: 4 ft - Gate post OD: 2.875 in - Footing diameter: 16 in - Footing depth: 48 in',
    'Addendum 02 has not been accepted yet; it is currently PROPOSED and waiting for a named person.', 'Nothing is approved yet, so G3 is still blocking.', 'No, Addendum 02 has not been accepted; it is PROPOSED.',
    'Gatehouse has not approved it. Estimator\'s decision is required.', 'I cannot confirm that. Gatehouse has not approved G3.', 'CR13 whole bid $63,257.38; CR14 whole bid $66,879.97. CR11 is not eligible (no equipment operator, R4).',
    'Per Section 32 31 13 §2.5 and Detail 3/F501, the G3 gate post is 2.875 in OD (ANSI B sheet C101).', 'Gemma-4-31B-IT is the configured model; the reply does not say which model answered.',
    'Please use the on-screen controls to accept the addendum. Have you chosen the Base Bid or Alternate A-1?', 'Eligible crews: CR13, CR14. Disqualified: CR11, CR12.'];
  for (const t of english) assert.equal(languageProblem(t), null, t);
  assert.equal(check(sAccepted(), 'Addendum 02 is accepted and G3 is resolved. The G3 values are a 4 ft opening and a 2.875 in OD post.').ok, true, 'valid English G3 statements pass once accepted');
  assert.equal(check(sProposed(), 'No, Addendum 02 has not been accepted; it is PROPOSED and waiting for a named person.').ok, true);
  assert.equal(check(sProposed(), 'Nothing is approved yet, so G3 is still blocking.').ok, true);
  assert.equal(check(sUnresolved(), 'Step 1 of 5 - scope review. Addendum 01 controls: G2 is a 12 ft double-leaf opening. Which bid would you like to review first?').ok, true);
});
test('language: end to end, an Italian reply is UNAVAILABLE with the SIMULATED built-in answer and is never LIVE; the Italian text is not shown', async () => {
  for (const [text, st] of [["Gatehouse ha approvato l'Addendum 02 e G3 è risolto.", sProposed()], ["L'Addendum 02 è stato accettato; G3 è un'apertura di 12 piedi.", sUnresolved()], ["Siamo al passaggio 1 di 5 - Scope Review. Sta procedendo con il Base Bid?", sUnresolved()]] as const) {
    const m = mock(() => ({ answer: text, conversationId: GUID_A }));
    const out = await answerDesk({ ...base(cfgOn(), m.t, undefined, { project: st.p }), getTakeoff: async () => st.t, det: deterministic(st.p, 'g3', null) as any });
    assert.equal(out.mode, 'UNAVAILABLE'); assert.equal(out.fallback_label, 'SIMULATED'); assert.match(out.live.reason, /not in English/);
    assert.doesNotMatch(out.answer, /approvato|accettato|risolto|passaggio/i); assert.ok(out.answer.length > 0);
  }
});
test('language: the deterministic fallback is not subject to the reply filter and the no-mutation boundary is unchanged', () => {
  const src = readFileSync(new URL('../lib/evolus-desk.ts', import.meta.url), 'utf8');
  assert.ok(/languageProblem\(text\)/.test(src) && src.indexOf('languageProblem(text)') < src.indexOf('hasActionClaim(text)'), 'the language check comes before every other reply check');
  assert.ok(!/from ['"]\.\/engine/.test(src) && !/engine\(/.test(src));
  const det = deterministic(project(), 'What about G3?', null); assert.equal(det.mode, 'SIMULATED'); assert.equal(languageProblem(det.answer), null, 'the built-in answers are English too');
});

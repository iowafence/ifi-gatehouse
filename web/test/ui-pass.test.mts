// Tests for the discovery-first Scope Gate model and the advisory Bid Desk. Run: npm run test:flight
import test from 'node:test';
import assert from 'node:assert/strict';
import { buildScopeGates, currentGate } from '../lib/scope-gates.ts';
import { answer, gateStateOf } from '../lib/bid-desk.ts';

const ex = (id: string, code: string, blocking = true, evidence: any[] = []): any => ({ exception_id: id, code, severity: blocking ? 'blocking' : 'advisory', blocking, question: `${code} ${id}`, status: 'open', evidence });
const fresh = (): any => ({ status: 'needs_scope_review', scope_version: 1, audit: [], addenda: [], rfi_drafts: [{ draft_id: 'RFI-G3-OPENING', gate_id: 'G3', subject: 'Gate G3 clear opening width', citations: [] }],
  exceptions: [ex('EX-MISSING_VALUE-/gates/2/clear_width_ft', 'MISSING_VALUE'), ex('EX-MISSING_VALUE-/footing_scope/classes/GATE_G3/depth_in', 'MISSING_VALUE'),
    ex('EX-BID_SELECTION_REQUIRED-/bid_structure/selected_bid', 'BID_SELECTION_REQUIRED'), ex('EX-INFERRED_FACT_UNAPPROVED-/fence_runs/0/length_lf', 'INFERRED_FACT_UNAPPROVED'), ex('EX-OWNER_SELECTION_PENDING-/x', 'OWNER_SELECTION_PENDING', false)] });
const draft: any = { items: [{ id: 'gate-g2', text: 'Addendum 01 item 1.1 revises G2 to 12\'-0" double leaf', figure: '12\'-0" double leaf', evidence: [{ doc_id: 'add01', page: 1, excerpt: 'Revise Gate G2', sheet_label: 'Addendum 01 item 1.1' }, { doc_id: 'pm', page: 15, excerpt: 'G2 6\'-0"', superseded_by: { doc_id: 'add01' } }] },
  { id: 'gate-g3', evidence: [{ doc_id: 'dwg', page: 5, excerpt: 'NOT SPECIFIED', sheet_label: 'F502 note 4' }] }] };
const rec = (id: string, cat: string, key: string, text: string, cls: string, run: string, model = 'DeepSeek-V4.1-Flash'): any => ({ finding_id: id, provenance: 'REAL_AMD_OUTPUT', classification: cls, relationship_key: `${cat}:${key}`, claim: { category: cat, key, text }, model: { provider: 'AMD Developer Cloud / Token Factory', requested: model, returned: model }, run: { run_id: run } });
const ai: any = { findings: [
  rec('a1', 'gate_tag_position', 'G2', 'gate tag G2 is printed in the east crop', 'GATE_LABEL_POSITION_CONFIRMED', 'spatial_003_r2'), rec('a2', 'gate_symbol', 'G2', 'gate G2 (east) symbol is double leaf swing', 'NOT_VERIFIED_VISUAL_ONLY', 'spatial_003_r2'),
  rec('a3', 'gate_symbol', 'G2', 'gate G2 (west) symbol is single leaf swing', 'NOT_VERIFIED_VISUAL_ONLY', 'spatial_003_r3'),
  rec('a4', 'gate_tag_position', 'G3', 'gate tag G3 is printed in the north crop', 'GATE_LABEL_POSITION_CONFIRMED', 'spatial_003_r1'), rec('a5', 'gate_symbol', 'G3', 'gate G3 (north) symbol is single leaf swing', 'NOT_VERIFIED_VISUAL_ONLY', 'spatial_003_r1'),
  rec('a6', 'fence_type_tag', 'A', 'tag A leader', 'VECTOR_CONFIRMED', 'spatial_003_r2'), rec('a7', 'fence_type_tag', 'B', 'tag B leader', 'CONTRADICTED_BY_DRAWING_EVIDENCE', 'spatial_003_r2')] };

test('fresh load: G2 corrected by the addendum, G3 missing width blocking and ADDENDUM_PENDING, no seeded 4 ft', () => {
  const g = buildScopeGates(fresh(), draft, ai);
  const g2 = g.find(x => x.id === 'g2')!, g3 = g.find(x => x.id === 'g3')!;
  assert.equal(g2.state, 'corrected'); assert.equal(g2.blocking, false);
  assert.ok(g2.findings.some(f => f.prov === 'ADDENDUM')); assert.ok(g2.findings.some(f => f.prov === 'AGENT-FOUND' && /east\) symbol is double leaf/.test(f.text) && /NOT verified|not verified/.test(f.note || '')));
  assert.equal(g3.state, 'open'); assert.equal(g3.blocking, true); assert.equal(g3.tag, 'ADDENDUM_PENDING');
  assert.ok(g3.findings.some(f => f.prov === 'AGENT-FOUND' && /No stored model output states a G3 opening width/.test(f.note || '')));
  assert.doesNotMatch(JSON.stringify(g3), /\b4 ?ft\b|4'-0/);
  assert.equal(currentGate(g)!.id, 'g3');
});
test('every finding carries one of the four provenance labels (five with the engine split)', () => {
  const ok = new Set(['AGENT-FOUND', 'ADDENDUM', 'ENGINE-FLAGGED', 'ENGINE-CALCULATED', 'HUMAN']);
  for (const gate of buildScopeGates(fresh(), draft, ai)) for (const f of gate.findings) assert.ok(ok.has(f.prov), f.prov);
});
test('a proposed then accepted addendum moves G3 to ADDENDUM_PROPOSED then resolved; a human value is labeled HUMAN', () => {
  const p = fresh(); p.addenda = [{ status: 'PROPOSED' }];
  assert.equal(buildScopeGates(p, draft, ai).find(x => x.id === 'g3')!.tag, 'ADDENDUM_PROPOSED');
  const done = fresh(); done.exceptions = done.exceptions.filter((e: any) => !/GATE_G3|gates\/2/.test(e.exception_id)); done.addenda = [{ status: 'APPLIED', filename: 'ADDENDUM_02.pdf', accepted_by: 'Pat' }];
  const g3 = buildScopeGates(done, draft, ai).find(x => x.id === 'g3')!; assert.equal(g3.state, 'resolved'); assert.equal(g3.tag, 'ADDENDUM_ACCEPTED');
  const h = fresh(); h.exceptions = h.exceptions.filter((e: any) => !/GATE_G3|gates\/2/.test(e.exception_id)); h.audit = [{ event_type: 'resolved', exception_id: 'EX-MISSING_VALUE-/gates/2/clear_width_ft', actor: 'Sam', note: 'phone call' }];
  const g = buildScopeGates(h, draft, ai).find(x => x.id === 'g3')!; assert.equal(g.tag, 'HUMAN_ASSUMPTION'); assert.ok(g.findings.some(f => f.prov === 'HUMAN'));
});
test('Bid Desk: advisory, shows gate state and mode, never approves, no live call', () => {
  const r = answer(fresh(), 'please approve the release', draft);
  assert.equal(r.intent, 'refuse_authority'); assert.equal(r.advisory, true); assert.equal(r.audit_record, false); assert.equal(r.live.enabled, false); assert.match(r.mode, /SIMULATED/);
  assert.match(r.gate_state.g3, /ADDENDUM_PENDING/); assert.equal(r.gate_state.crew, 'not selected'); assert.match(r.gate_state.total, /withheld/);
  const g3 = answer(fresh(), 'What about G3?', draft); assert.equal(g3.intent, 'g3'); assert.ok(g3.sources.every(s => s.doc_id), 'sources come from evidence only');
  assert.equal(answer(fresh(), 'tell me a joke', draft).intent, 'unknown');
});
test('Bid Desk: a total is withheld until a crew plan exists; the crew is named once selected', () => {
  const p = fresh(); p.pricing = { estimate_view: { price_total: 1 } };
  assert.match(gateStateOf(p).total, /withheld/);
  p.pricing.crew_plan = { preferred_crew: 'CR13', plan_version: 1 };
  assert.match(gateStateOf(p).crew, /CR13/); assert.match(gateStateOf(p).total, /available/);
});

import { readFileSync as _rf } from 'node:fs';
import { openQuestions } from '../lib/dp001.ts';
test('exception notes: the engine\'s own open_question text is what the Scope Gate shows; no hardcoded sentence; fallback kept; the old dropdown string is gone', () => {
  const scope = JSON.parse(_rf(new URL('../../dp001/scope_dp001_footing.json', import.meta.url), 'utf8'));
  const n = openQuestions(scope);
  assert.match(n['/footing_scope/classes/GATE_G3/diameter_in'], /F502 note 5 and 32 31 13 3\.2\.D .*as for terminal posts - an estimator must decide whether that default governs G3\. It is NOT applied by Gatehouse\./);
  assert.ok(n['/footing_scope/classes/GATE_G3/depth_in'] && n['/footing_scope/classes/GATE_G3/post_od_in']);
  assert.equal(n['/gates/2/clear_width_ft'], undefined);        // no engine note on the width fact: today's text stays for it
  const page = _rf(new URL('../app/page.tsx', import.meta.url), 'utf8');
  assert.ok(!page.includes('estimator must decide'), 'the note text is the engine\'s, never hardcoded in the page');
  assert.ok(page.includes("'No document-derived option. Enter a value as your own assumption, or request information.'")); assert.ok(!page.includes('No option (enter a documented value below)'));
  const route = _rf(new URL('../app/api/demo/scope-draft/route.ts', import.meta.url), 'utf8'); assert.ok(route.includes('exception_notes: await exceptionNotes()'));
});
import { readdirSync as _rd, statSync as _st } from 'node:fs';
test('banner and breadcrumb: true banner text; no sentence anywhere in the web app denies PDF upload, model analysis or AI use of the demo; dashboard crumb', () => {
  const walk = (d: string): string[] => _rd(d).flatMap(n => { const p = `${d}/${n}`; return n === 'node_modules' || n === '.next' ? [] : _st(p).isDirectory() ? walk(p) : /\.(ts|tsx)$/.test(n) ? [p] : []; });
  const root = new URL('../', import.meta.url).pathname;
  for (const f of [...walk(`${root}app`), ...walk(`${root}lib`)]) { const t = _rf(f, 'utf8'); assert.doesNotMatch(t, /built-in JSON fixture|no ZIP, PDF or model analysis|not involved/, f); }
  const page = _rf(`${root}app/page.tsx`, 'utf8');
  assert.ok(page.includes('Interactive demonstration using fictional project data and example pricing.</strong> Prices come from the deterministic engine and the example rate book. Addendum parsing and AI findings are labelled by source (LIVE, RECORDED, or stored). Names you type are self-declared, not verified identities.'));
  assert.ok(page.includes("project?(home&&!roProject?'PROJECT DASHBOARD':'PROJECT WORKSPACE'):'NEW PROJECT'"));
});

import { notesFor } from '../lib/exception-notes.ts';
test('depth_in shows its own terse note AND, under "Related notes for this gate", the diameter_in sentence (relatedness by shared class path, order by field, no wording match)', () => {
  const scope = JSON.parse(_rf(new URL('../../dp001/scope_dp001_footing.json', import.meta.url), 'utf8')); const n = openQuestions(scope);
  const d = notesFor(n, ['/footing_scope/classes/GATE_G3/depth_in']);
  assert.equal(d.own, 'RFI: G3 gate-post footing depth (same open question).');
  assert.deepEqual(d.related.map(r => r.field), ['post_od_in', 'diameter_in']);
  const dia = d.related.find(r => r.field === 'diameter_in')!; assert.match(dia.note, /an estimator must decide whether that default governs G3\. It is NOT applied by Gatehouse\./);
  assert.ok(!d.related.some(r => r.path.includes('GATE_G1') || r.path.includes('GATE_G2')), 'only the same gate/class');
  const o = notesFor(n, ['/footing_scope/classes/GATE_G3/diameter_in']); assert.match(o.own!, /an estimator must decide/); assert.deepEqual(o.related.map(r => r.field), ['post_od_in', 'depth_in']);
  assert.deepEqual(notesFor(n, ['/gates/2/clear_width_ft']), { own: undefined, related: [] });      // no notes for this class: today's text stays
  assert.deepEqual(notesFor({}, ['/footing_scope/classes/GATE_G3/depth_in']), { own: undefined, related: [] }); assert.deepEqual(notesFor(undefined, undefined), { own: undefined, related: [] });
  const src = _rf(new URL('../lib/exception-notes.ts', import.meta.url), 'utf8'); assert.ok(!/same open question/.test(src.replace(/^\/\/.*$/gm, '')), 'no string matching on the note text');
  const page = _rf(new URL('../app/page.tsx', import.meta.url), 'utf8'); assert.ok(page.includes('Related notes for this gate') && page.includes("{exceptionNotes(draft,activeException).own??'The documents do not state this value.'}"));
});

import { valueFieldLabel } from '../lib/exception-notes.ts';
test('typed-value label: "Your value (self-declared assumption)" for a missing value with no document-derived option; the inferred-value exception keeps its wording and the engine question is untouched', () => {
  assert.equal(valueFieldLabel({ code: 'MISSING_VALUE', options: [] }), 'Your value (self-declared assumption)');
  assert.equal(valueFieldLabel({ code: 'MISSING_VALUE' }), 'Your value (self-declared assumption)');
  assert.equal(valueFieldLabel({ code: 'MISSING_VALUE', options: [{ option_id: 'x' }] }), 'Documented value (human-entered)');        // a document-derived option exists: not the no-option case
  assert.equal(valueFieldLabel({ code: 'INFERRED_FACT_UNAPPROVED', options: [] }), 'Documented value (human-entered)');
  assert.equal(valueFieldLabel(undefined), 'Documented value (human-entered)');
  const page = _rf(new URL('../app/page.tsx', import.meta.url), 'utf8'); assert.ok(page.includes('{valueFieldLabel(activeException)}') && !page.includes('<label>Documented value (human-entered)</label>'));
  const eng = _rf(new URL('../../engine/exceptions.py', import.meta.url), 'utf8'); assert.ok(eng.includes('Approve it as a qualified'), 'the engine wording on inferred values is not ours to change');
});

test('round 3 layout contracts: header tabs keep their test ids; KPI row only on the dashboard; sidebar order; Bid Desk launcher stays labelled SIMULATED', () => {
  const page = _rf(new URL('../app/page.tsx', import.meta.url), 'utf8'), dash = _rf(new URL('../app/components/dashboard.tsx', import.meta.url), 'utf8');
  const nav = page.slice(page.indexOf('<nav className="header-tabs"'), page.indexOf('</nav>'));
  assert.ok(nav.includes('data-testid="nav-dashboard"') && nav.includes('data-testid="nav-workspace"') && nav.includes('Projects dashboard') && nav.includes('Project workspace'));
  assert.ok(page.indexOf('</header>') < page.indexOf('<nav className="header-tabs"'), 'the tabs sit directly under the breadcrumb header');
  const side = page.slice(page.indexOf('const sideBody=<>'), page.indexOf('</>;', page.indexOf('const sideBody=<>')));
  assert.ok(!/Projects dashboard|Project workspace|KpiRow|KpiPanel|PORTFOLIO KPIs/.test(side), 'no nav links or KPIs in the sidebar');
  const order = ['<ProjectNav', '<CrewPanel', 'data-testid="open-ai-activity"', 'data-testid="open-flight-recorder"', 'onClick={newProject}'].map(m => side.indexOf(m));
  assert.ok(order.every(i => i >= 0) && order.every((v, i) => i === 0 || v > order[i - 1]), 'Projects, Crew efficiency, AI activity, AI Flight Recorder, Reset demo last: ' + order);
  assert.ok(!page.includes('KpiRow') && dash.includes('<KpiRow portfolio={portfolio} />'), 'the KPI row renders only inside the dashboard component');
  for (const l of ['Active bids', 'Win rate', 'Avg est. GP %', 'Avg exp. NP %', 'Open pipeline', 'Exp. pipeline NP', 'Synthetic · estimated at bid']) assert.ok(dash.includes(l), l);
  assert.ok(page.includes('data-testid="bd-launch"') && page.includes('data-testid="bd-launch-sim"') && page.includes('>SIMULATED</small>'));
  const css = _rf(new URL('../app/globals.css', import.meta.url), 'utf8'); const bd = css.slice(css.indexOf('Round 3')); assert.ok(!/evolus/i.test(bd.slice(bd.indexOf('.bd-launch{'), bd.indexOf('.evolus-tag'))), 'no Evolus styling on the Bid Desk launcher');
});
test('Evolus tag: on the Evolus RFI draft cards only; text and colour, no image', () => {
  const ledger = JSON.parse(_rf(new URL('../../dp001/ai_findings.json', import.meta.url), 'utf8'));
  const drafts = [{ case_id: 'c1', run_id: 'GH-RUN-e5bbcecef551', subject: 'Gate G3 Clear Opening Width', question: 'q', status: 'PENDING_HUMAN_REVIEW', gate: 'G3', model_returned: null }];
  const gs = buildScopeGates({ status: 'needs_scope_review', scope_version: 1, audit: [], addenda: [], rfi_drafts: [], exceptions: [{ exception_id: 'EX-MISSING_VALUE-/gates/2/clear_width_ft', code: 'MISSING_VALUE', severity: 'blocking', blocking: true, question: 'q', status: 'open', evidence: [] }] }, null, { ...ledger, evolus_drafts: drafts });
  const agent = gs.flatMap(g => g.findings.filter(f => f.prov === 'AGENT-FOUND'));
  const ev = agent.filter(f => /^Evolus RFI draft:/.test(f.text)); assert.ok(ev.length >= 1 && ev.every(f => f.evolus === true));
  assert.ok(agent.filter(f => !/^Evolus RFI draft:/.test(f.text)).every(f => !f.evolus), 'model-found findings are not Evolus');
  const sd = _rf(new URL('../app/components/scope-discovery.tsx', import.meta.url), 'utf8'); assert.ok(sd.includes('data-testid="evolus-tag"') && !/<img|logo|mascot/i.test(sd.slice(sd.indexOf('evolus-tag') - 80, sd.indexOf('evolus-tag') + 120)));
});

import { isDeadEndException, DEAD_END_TEXT } from '../lib/exception-notes.ts';
test('GEOMETRY_INVALID: no typed-value box, the dead-end sentence instead, Record disabled; every other kind keeps its box', () => {
  assert.equal(DEAD_END_TEXT, 'The run length and the layout sides must describe the same fence. A typed run length made them disagree and this cannot be re-entered here. Use Reset demo to start over.');
  assert.equal(isDeadEndException({ code: 'GEOMETRY_INVALID' }), true);
  for (const code of ['MISSING_VALUE', 'INFERRED_FACT_UNAPPROVED', 'BID_SELECTION_REQUIRED', undefined]) assert.equal(isDeadEndException({ code }), false, String(code));
  assert.equal(isDeadEndException(undefined), false);
  const page = _rf(new URL('../app/page.tsx', import.meta.url), 'utf8');
  assert.ok(page.includes('{!scopeChoice&&activeException.allows_free_text&&!isDeadEndException(activeException)&&!deadEnds[activeException.exception_id]&&<><label data-testid="value-field-label">'), 'the box is gated on the kind and on a recorded engine refusal');
  assert.ok(page.includes('{isDeadEndException(activeException)&&<div className="guardrail" role="note" data-testid="geometry-dead-end">'));
  assert.ok(page.includes('disabled={busy||isDeadEndException(activeException)||'), 'Record stays disabled for the dead end');
  assert.ok(!/GEOMETRY_INVALID/.test(page), 'keyed through the helper on the exception code only');
});
test('Evolus tag: lime #50d03c with dark text keeps AA contrast; colour and text only', () => {
  const css = _rf(new URL('../app/globals.css', import.meta.url), 'utf8'); assert.ok(css.includes(':root{--evolus-green:#50d03c}'));
  const tag = css.slice(css.indexOf('.evolus-tag{')); const fg = /color:(#[0-9a-f]{6})/i.exec(tag)![1], bg = /background:var\(--evolus-green\)/.test(tag) ? '#50d03c' : '';
  const L = (h: string) => { const c = [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16) / 255).map(v => v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
  const ratio = (a: string, b: string) => (Math.max(L(a), L(b)) + 0.05) / (Math.min(L(a), L(b)) + 0.05);
  assert.ok(ratio(fg, bg) >= 4.5, `contrast ${ratio(fg, bg).toFixed(2)}`); assert.ok(!/url\(|<img/i.test(tag.slice(0, tag.indexOf('}'))));
});

import { blockingStatus, discoveryHeading, blockingPhrase, buildScopeGates as _bsg } from '../lib/scope-gates.ts';
import { answer as deskAnswer } from '../lib/bid-desk.ts';
const GEO_Q = 'fence_runs > 0 > length_lf: gate openings (92 LF) are not less than run length (48 LF).';
const geo = (extra: any = {}): any => ({ exception_id: 'EX-GEOMETRY_INVALID-/fence_runs/0/length_lf', code: 'GEOMETRY_INVALID', severity: 'blocking', blocking: true, question: GEO_Q, status: 'open', evidence: [], ...extra });
const proj14 = (exceptions: any[]): any => ({ status: 'needs_scope_review', scope_version: 5, audit: [{ event_type: 'resolved', exception_id: 'x' }], addenda: [], rfi_drafts: [], exceptions });
test('gate cleared state needs ZERO open blocking exceptions of any kind; banner, card and Bid Desk share one count', () => {
  const draft = JSON.parse(_rf(new URL('../../dp001/scope_draft.json', import.meta.url), 'utf8'));
  // a blocking exception of a kind NO gate card tracks
  const p = proj14([geo()]); const gates = _bsg(p, draft, null);
  assert.equal(gates.some(g => g.blocking), false, 'no gate card is blocking: the cards do not track this kind');
  const h = discoveryHeading(gates, p);
  assert.equal(h.cleared, false); assert.doesNotMatch(h.heading + h.lead, /All scope gates cleared|Continue to the Labor Gate/);
  assert.equal(h.heading, '1 blocking exception still open'); assert.ok(h.lead.includes(`First: ${GEO_Q}`)); assert.match(h.lead, /must be resolved before the Labor Gate/);
  const b = blockingStatus(p); assert.deepEqual([b.count, b.clear, b.first!.kind, b.first!.question], [1, false, 'GEOMETRY_INVALID', GEO_Q]);
  // two remain: counted, first named
  const p2 = proj14([geo(), geo({ exception_id: 'EX-GEOMETRY_INVALID-/fence_runs/1/length_lf', question: 'second' })]); const h2 = discoveryHeading(_bsg(p2, draft, null), p2);
  assert.equal(h2.heading, '2 blocking exceptions still open'); assert.ok(h2.lead.includes('First: ' + GEO_Q)); assert.equal(blockingPhrase(blockingStatus(p2)), `2 blocking exceptions remain open. First: ${GEO_Q}`);
  // truly zero: cleared, with the Continue prompt
  const z = proj14([]); const hz = discoveryHeading(_bsg(z, draft, null), z); assert.deepEqual([hz.cleared, hz.heading, hz.lead], [true, 'All scope gates cleared', 'Nothing blocks the scope now. Continue to the Labor Gate.']);
  // an advisory or a resolved blocking exception does not count
  assert.equal(blockingStatus(proj14([geo({ severity: 'advisory', blocking: false }), geo({ status: 'resolved' })])).clear, true);
  // a tracked gate still open plus an untracked blocker: the gate leads, the extra is counted
  const ex = [{ exception_id: 'EX-MISSING_VALUE-/gates/2/clear_width_ft', code: 'MISSING_VALUE', severity: 'blocking', blocking: true, question: 'w', status: 'open', evidence: [] }, geo()];
  const p3 = proj14(ex); const h3 = discoveryHeading(_bsg(p3, draft, null), p3); assert.match(h3.heading, /^Now: Gate G3/); assert.equal(h3.untracked, 1);
  // the Bid Desk says the same, and its count is the shared one
  const r = deskAnswer(p, 'what is blocking', draft); assert.ok(r.answer.includes('1 blocking exception remains open. First: ' + GEO_Q)); assert.equal(r.gate_state.blocking, 1);
  assert.doesNotMatch(r.answer, /No scope item blocks pricing now/);
  const page = _rf(new URL('../app/page.tsx', import.meta.url), 'utf8'); assert.ok(page.includes('const blockingCount=blockingStatus(project).count;'));
  const card = _rf(new URL('../app/components/scope-discovery.tsx', import.meta.url), 'utf8'); assert.ok(card.includes('discoveryHeading(gates, project)') && !card.includes("'All scope gates cleared'"));
});
import { isNonResolvable409 } from '../lib/exception-notes.ts';
test('general dead end: a 409 saying "not a resolvable fact" or "no open exception" shows the engine\'s message and a Reset demo button, hides the box, disables Record', () => {
  assert.equal(isNonResolvable409(409, "path '/fence_runs/0/length_lf' is not a resolvable fact"), true);
  assert.equal(isNonResolvable409(409, 'There is no open exception for that path'), true);
  assert.equal(isNonResolvable409(409, 'The scope changed since you loaded it'), false);       // other 409s (stale version) are not dead ends
  assert.equal(isNonResolvable409(400, 'not a resolvable fact'), false); assert.equal(isNonResolvable409(422, 'no open exception'), false); assert.equal(isNonResolvable409(409, undefined), false);
  const page = _rf(new URL('../app/page.tsx', import.meta.url), 'utf8');
  assert.ok(page.includes('if(!r.ok&&le&&isNonResolvable409(le.status,le.message))setDeadEnds(d=>({...d,[activeException.exception_id]:le.message}));'));
  assert.ok(page.includes('data-testid="engine-dead-end"') && page.includes('{deadEnds[activeException.exception_id]}') && page.includes('data-testid="dead-end-reset"') && page.includes('disabled={busy||isDeadEndException(activeException)||!!deadEnds[activeException.exception_id]||'));
  assert.ok(page.includes('setBusy(true);setError(\'\');setInfo(\'\');setDeadEnds({});'), 'a reset clears recorded refusals');
});

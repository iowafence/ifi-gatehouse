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

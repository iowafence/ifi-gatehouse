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
const ai: any = { findings: [{ finding_id: 'SIM-g2-rev0-6ft', provenance: 'SIMULATED_TEST_DATA', claim: { text: 'G2 clear opening 6\'-0"' }, verification: { result: 'VERIFIED' } }, { finding_id: 'SIM-g3-12ft-unverified', provenance: 'SIMULATED_TEST_DATA', claim: { text: 'G3 clear opening 12\'-0"' }, verification: { result: 'UNVERIFIED' } }] };

test('fresh load: G2 corrected by the addendum, G3 missing width blocking and ADDENDUM_PENDING, no seeded 4 ft', () => {
  const g = buildScopeGates(fresh(), draft, ai);
  const g2 = g.find(x => x.id === 'g2')!, g3 = g.find(x => x.id === 'g3')!;
  assert.equal(g2.state, 'corrected'); assert.equal(g2.blocking, false);
  assert.ok(g2.findings.some(f => f.prov === 'ADDENDUM')); assert.ok(g2.findings.some(f => f.prov === 'AGENT-FOUND'));
  assert.equal(g3.state, 'open'); assert.equal(g3.blocking, true); assert.equal(g3.tag, 'ADDENDUM_PENDING');
  assert.ok(g3.findings.some(f => f.prov === 'AGENT-FOUND' && /UNVERIFIED/.test(f.note || '')));
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

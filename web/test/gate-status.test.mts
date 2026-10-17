// The Scope Gate and the export must agree on every gate's status, because both are derived from the same state. Run: npm run test:flight
import test from 'node:test';
import assert from 'node:assert/strict';
import { buildExport, toCsv } from '../lib/export.ts';
import { scopeStatus } from '../lib/gate-status.ts';
import { buildScopeGates } from '../lib/scope-gates.ts';

const OWNER_Q = ['Qualified assumption (owner: Jordan, until a document states it): gate stations G1 69 ft, G2 43 ft, G2 43 ft, G3 31 ft.', 'Qualified assumption (owner: Jordan, until a document states it): FR-B side 64 ft.', 'Assumption (owner: Jordan): rail couplings 21 ft.'];
const project = (): any => ({ project_id: 'P1', status: 'released', scope_version: 13, proposal_digest: 'ab'.repeat(32), approved_by: 'Pat (test)', released_at: '2026-10-16T00:00:00Z', exceptions: [], audit: [], addenda: [{ status: 'APPLIED', filename: 'ADDENDUM_02.pdf', accepted_by: 'Pat (test)' }], rfi_drafts: [],
  estimate: { headline_scope_ref: 'BASE', exclusions: [], scenarios: { BASE: { materials: { lines: [] }, labor: { lines: [] }, price_total: 27 } } },
  pricing: { ruleset: { ruleset_id: 'R', version: '1', contractor_approved: false, approved_by: 'Pat (test)' }, wage: { decision: { decision_id: 'FDB-DP001', modification: '0', recorded_by: 'Pat (test)' }, role_classifications: [] },
    estimate_view: { scope_ref: 'BASE', price_total: 27, price_per_lf: 5, fence_lf: 5, breakdown: [], alternates: [], qualifications: OWNER_Q, advisories: [] } } });
const F = (status: string, by: string | null, extra: any = {}): any[] => [['opening', 'G3 clear opening', '/gates/2/clear_width_ft', 'ft', 4], ['post', 'G3 gate-post OD', '/footing_scope/classes/GATE_G3/post_od_in', 'in', 2.875], ['dia', 'G3 footing diameter', '/footing_scope/classes/GATE_G3/diameter_in', 'in', 16], ['depth', 'G3 footing depth', '/footing_scope/classes/GATE_G3/depth_in', 'in', 48]]
  .map(([id, label, path, unit, v]) => ({ id, label, path, unit, status, value: status === 'unresolved' ? null : v, by, note: status === 'human_assumption' ? 'ASSUMED, RFI PENDING. SOURCE: phone call' : '', ...(status === 'document_confirmed' ? { acceptance: { accepted_by: by, accepted_utc: '2026-10-16T22:00:00Z', accepted_note: 'checked', scope_version_produced: 13, addendum_label: 'Addendum 02', intake_id: 'i1', sha256: 'cd'.repeat(32), filename: 'ADDENDUM_02.pdf', page: 1, quoted: 'Gate G3 post size and footing are the same as Gate G1', sheet_label: 'ADDENDUM_02.pdf page 1' } } : {}), ...extra }));
const review = (status: string, by: string | null, rfi: string): any => ({ g3: { rfi: { id: 'RFI-G3', status: rfi, sent: false }, facts: F(status, by) }, readiness: { selected: { bid_ready: false } } });
const draft: any = { items: [{ id: 'gate-g3', evidence: [{ doc_id: 'dwg', page: 5, excerpt: 'NOT SPECIFIED', sheet_label: 'F502 note 4' }] }] };

/** Every status the Scope Gate prints for G3 and the assumptions must match what the export prints for the same state. */
function crossCheck(p: any, rv: any) {
  const gates = buildScopeGates(p, draft, null, rv); const g3 = gates.find(g => g.id === 'g3')!, as = gates.find(g => g.id === 'assumed')!;
  const ss = scopeStatus(p, rv); const csv = toCsv(buildExport(p, rv));
  for (const f of ss.g3.facts) {
    const row = csv.split('\r\n').find(l => l.startsWith(`${f.label},${f.path},`))!; assert.ok(row, `export row for ${f.label}`);
    const exportState = /^[^,]*,[^,]*,DOCUMENT-CONFIRMED/.test(row) ? 'resolved_addendum' : /,ASSUMPTION — RFI PENDING/.test(row) ? 'assumed_human' : /,UNRESOLVED — RFI PENDING/.test(row) ? 'unresolved' : 'other';
    assert.equal(f.state, exportState, `${f.label}: Scope Gate says ${f.state}, export says ${exportState}`);
  }
  const exportRfiClosed = /RFI-G3,RESOLVED/.test(csv), exportRfiOpen = /RFI-G3: PENDING|RFI-G3,OPEN/.test(csv);
  assert.equal(ss.g3.rfi.closed, exportRfiClosed); assert.ok(!(exportRfiClosed && exportRfiOpen), 'export marks the RFI resolved and open together');
  assert.equal(g3.state === 'resolved' && g3.tag === 'ADDENDUM_ACCEPTED', ss.g3.state === 'resolved');
  assert.equal(g3.blocking, ss.g3.state === 'open');
  const exportAssumed = csv.split('\r\n').filter(l => /^Open item \d+,/.test(l)).length;
  assert.equal(as.findings.length, exportAssumed, 'assumption count: Scope Gate vs export');
  assert.ok(as.findings.every(f => f.prov === 'HUMAN' && !/block(er|s)?\b/i.test(f.text) && /Owner /.test(f.note || '')), 'assumptions are HUMAN, owned, and never called blockers');
  assert.equal(as.blocking, false);
  return { gates, g3, as, csv, ss };
}

test('G3 resolved by Addendum 02: Scope Gate and export agree; width shown as ADDENDUM; original exception kept as resolved history; no pending RFI', () => {
  const { g3, csv } = crossCheck(project(), review('document_confirmed', 'Pat (test)', 'resolved_by_accepted_addendum'));
  assert.equal(g3.state, 'resolved'); assert.equal(g3.blocking, false);
  assert.ok(g3.findings.some(f => f.prov === 'ADDENDUM' && /G3 clear opening: 4 ft — resolved by Addendum 02/.test(f.text)));
  assert.ok(g3.findings.some(f => /History · original exception/.test(f.text) && /RESOLVED/.test(f.note || '')));
  assert.ok(g3.findings.some(f => /RFI-G3: RESOLVED by the accepted addendum \(closed\)/.test(f.text)));
  assert.doesNotMatch(JSON.stringify(g3.findings.map(f => f.text)), /pending RFI|blocking/i);
  assert.match(csv, /RESOLVED BY ACCEPTED ADDENDUM/);
});
test('G3 location (station 31 ft) is ASSUMED, owner Jordan, clears when a document states it; not a blocker', () => {
  const { g3 } = crossCheck(project(), review('document_confirmed', 'Pat (test)', 'resolved_by_accepted_addendum'));
  const loc = g3.findings.find(f => /G3 location: station 31 ft is ASSUMED/.test(f.text))!; assert.ok(loc);
  assert.equal(loc.prov, 'HUMAN'); assert.match(loc.note!, /Owner Jordan/); assert.match(loc.note!, /Clears only when a document states it/); assert.match(loc.note!, /not a blocker/); assert.match(loc.note!, /NOT BID READY/);
});
test('G3 still open: both say unresolved and pending; the gate blocks', () => {
  const { g3 } = crossCheck(project(), review('unresolved', null, 'open'));
  assert.equal(g3.state, 'open'); assert.equal(g3.blocking, true); assert.equal(g3.tag, 'ADDENDUM_PENDING');
});
test('G3 typed by a named person: both say assumption; RFI pending; not blocking', () => {
  const { g3 } = crossCheck(project(), review('human_assumption', 'Sam', 'open'));
  assert.equal(g3.tag, 'HUMAN_ASSUMPTION'); assert.equal(g3.blocking, false);
});
test('the check itself fails when the two disagree (a Scope Gate fed a different review than the export)', () => {
  const p = project(); const rvExport = review('document_confirmed', 'Pat (test)', 'resolved_by_accepted_addendum');
  const gateSide = scopeStatus(p, review('unresolved', null, 'open')); const csv = toCsv(buildExport(p, rvExport));
  assert.notEqual(gateSide.g3.state === 'resolved', /RESOLVED BY ACCEPTED ADDENDUM/.test(csv));
});

test('UI vs export: each G3 card row cites its own page and quote, the same words the export prints for that row (inherited rows read "same as Gate G1")', () => {
  const rv = review('document_confirmed', 'Pat (test)', 'resolved_by_accepted_addendum');
  const quotes: Record<string, string> = { '/gates/2/clear_width_ft': '4\'-0" clear opening' };
  for (const f of rv.g3.facts) { if (quotes[f.path]) f.acceptance.quoted = quotes[f.path]; else f.acceptance.quoted = 'Gate G3 post size and footing are the same as Gate G1'; }
  const p = project();
  const card = buildScopeGates(p, draft, null, rv).find(g => g.id === 'g3')!.findings.filter(f => f.prov === 'ADDENDUM' && /resolved by/.test(f.text));
  const blk = buildExport(p, rv).blocks.find((b: any) => /acceptance record/.test(b.title))!;
  const qi = blk.head.indexOf('Quoted words');
  assert.equal(blk.rows.length, 4); assert.equal(card.length, 4);
  for (const row of blk.rows) {
    const label = String(row[0]); const c = card.find(x => x.text.startsWith(`${label}:`))!; assert.ok(c, `card row for ${label}`);
    const exportQuote = String(row[qi]); assert.ok(c.note!.includes(`“${exportQuote}”`), `${label}: card says ${c.note}, export says ${exportQuote}`);
  }
  const widthCard = card.find(x => x.text.startsWith('G3 clear opening:'))!, odCard = card.find(x => x.text.startsWith('G3 gate-post OD:'))!;
  assert.ok(!widthCard.note!.includes('same as Gate G1')); assert.ok(!odCard.note!.includes('clear opening'));
  for (const l of ['G3 gate-post OD', 'G3 footing diameter', 'G3 footing depth']) assert.match(card.find(x => x.text.startsWith(`${l}:`))!.note!, /same as Gate G1/);
});

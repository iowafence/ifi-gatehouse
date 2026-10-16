// Tests for web/lib/export.ts (CSV only): the export copies engine figures, carries authorization state, never drops the readiness class,
// and is a money-free holds report when nothing is priced. Run: npm run test:flight
import test from 'node:test';
import assert from 'node:assert/strict';
import { buildExport, toCsv } from '../lib/export.ts';

const scenario = { materials: { lines: [{ item_id: 'M01', description: '=HYPERLINK("http://x")', uom: 'EA', quantity: 2, order_quantity: 2, unit_price: 10, extended: 20, status: 'confirmed' }] },
  labor: { lines: [{ task_id: 'L01', task: 'Layout', uom: 'LF', quantity: 5, crew_id: 'CR12', crew_hours: 1, worker_hours: 4, duration_days: 0.1, extended: 7 }] } };
const priced = (status: string): any => ({ project_id: 'P1', status, scope_version: 3, proposal_digest: 'ab'.repeat(32), approved_by: 'Pat', released_at: '2026-10-16T00:00:00Z', exceptions: [{ severity: 'blocking', code: 'MISSING_VALUE', question: 'G3 width?', affects: ['/gates/2/clear_width_ft'] }],
  estimate: { headline_scope_ref: 'BASE', scenarios: { BASE: { ...scenario, price_total: 27 }, 'ALT-A1': { ...scenario, price_total: 20 } } },
  pricing: { ruleset: { ruleset_id: 'R', version: '1', contractor_approved: false, approved_by: 'Pat' }, wage: { decision: { decision_id: 'FDB-DP001', modification: '0', recorded_by: 'Wanda' } },
    estimate_view: { scope_ref: 'BASE', price_total: 27, price_per_lf: 5.4, fence_lf: 5, breakdown: [{ key: 'price_total', label: 'Total estimate', amount: 27 }], alternates: [{ scope_ref: 'ALT-A1', price_total: 20 }], qualifications: ['Assumed 12 ft'], advisories: [] } } });
const unpriced = (): any => ({ project_id: 'P2', status: 'needs_scope_review', scope_version: 1, exceptions: [{ severity: 'blocking', code: 'MISSING_VALUE', question: 'G3 width?', affects: ['/gates/2/clear_width_ft'] }], estimate: null, pricing: { ruleset: null, wage: { decision: null } } });
const R = (bid?: boolean): any => ({ ...g3(true), ...(bid === undefined ? {} : { readiness: { selected: { bid_ready: bid } } }) });
const g3 = (assumed: boolean): any => ({ g3: { rfi: { id: 'RFI-G3', status: 'open', sent: false }, facts: [
  { id: 'opening', label: 'G3 clear opening', unit: 'ft', path: '/gates/2/clear_width_ft', status: assumed ? 'human_assumption' : 'unresolved', value: assumed ? 11 : null, by: assumed ? 'Sam' : null, note: assumed ? 'ASSUMED, RFI PENDING. SOURCE: phone call 10/16 | x' : null }] } });

test('nothing priced: holds report with no money rows, G3 shown RFI PENDING', () => {
  const x = buildExport(unpriced(), g3(false)); assert.equal(x.stampKind, 'unpriced');
  const csv = toCsv(x);
  assert.match(csv, /NOT PRICED — HOLDS OPEN/); assert.match(csv, /GATE G3 — RFI PENDING/); assert.match(csv, /UNRESOLVED — RFI PENDING/); assert.match(csv, /NOT AVAILABLE/);
  assert.doesNotMatch(csv, /Total estimate|Price summary|MATERIALS/i);
  assert.match(x.filename, /NOT-PRICED/);
});
test('a typed G3 value prints value, name and source note and still says RFI PENDING / assumed', () => {
  const csv = toCsv(buildExport(unpriced(), g3(true)));
  assert.match(csv, /ASSUMPTION — RFI PENDING \(typed by a person/); assert.match(csv, /11 ft/); assert.match(csv, /Sam/); assert.match(csv, /SOURCE: phone call 10\/16/); assert.match(csv, /RFI-G3: PENDING/);
});
test('review unavailable: G3 is reported unknown, never resolved', () => { assert.match(toCsv(buildExport(unpriced(), null)), /Treat G3 as unresolved/); });
test('unreleased priced export is stamped DRAFT and lists holds', () => {
  const x = buildExport(priced('ready_for_final_review'), R()); assert.equal(x.stampKind, 'draft');
  assert.match(toCsv(x), /DRAFT — NOT AUTHORIZED/); assert.match(toCsv(x), /G3 width\?/); assert.match(x.filename, /DRAFT/);
});
test('released but not bid ready stays QUALIFIED / NOT A BID; bid_ready true is the only way to RELEASED', () => {
  assert.equal(buildExport(priced('released'), R(false)).stampKind, 'qualified');
  assert.equal(buildExport(priced('released'), R()).stampKind, 'qualified');
  assert.equal(buildExport(priced('released'), R(true)).stampKind, 'released');
});
test('totals are copied; alternate is separate and IN LIEU OF; never added', () => {
  const csv = toCsv(buildExport(priced('released'), R()));
  assert.match(csv, /Base Bid total,27\.00/); assert.match(csv, /Alternate A-1 total,20\.00/); assert.match(csv, /ALTERNATE A-1 \(IN LIEU OF BASE BID — REPLACES IT\) — MATERIALS/); assert.match(csv, /No combined total/i); assert.doesNotMatch(csv, /47\.00/);
});
test('wage decision recorder name and the fictional label appear', () => {
  const csv = toCsv(buildExport(priced('released'), R()));
  assert.match(csv, /FICTIONAL DEMO WAGE DECISION/); assert.match(csv, /recorded by Wanda/);
  assert.match(toCsv(buildExport(unpriced(), null)), /NOT RECORDED/);
});
test('CSV neutralizes formulas; currency and rate book fields exist', () => {
  const csv = toCsv(buildExport(priced('released'), R())); assert.match(csv, /'=HYPERLINK/); assert.match(csv, /Currency,USD/);
});
test('exclusions are copied when the engine reports them and never invented', () => {
  assert.match(toCsv(buildExport(priced('released'), R())), /None reported by the engine/);
  const pj = priced('released'); pj.estimate.exclusions = ['Permits by others'];
  assert.match(toCsv(buildExport(pj, R())), /Permits by others/);
});
test('sales tax qualification cites the engine-reported section; item 16 note is present; no combined total', () => {
  const pj = priced('released'); pj.estimate.scenarios.BASE.sales_tax = { exemption_applies: true, exempt_base: 100, taxable_base: 0, amount: 0 };
  pj.estimate.scenarios.BASE.quantity_revision = { sales_tax_exemption: { evidence_refs: [{ sheet_label: '00 0800 SC-3.6.1' }] } };
  const csv = toCsv(buildExport(pj, R()));
  assert.match(csv, /exempt from sales tax \(owner exemption\), per DP-001 Project Manual, 00 0800 SC-3\.6\.1/); assert.match(csv, /Sales tax charged \(USD\),0\.00/);
  assert.match(csv, /included in top-rail task/); assert.match(csv, /No combined total exists/); assert.doesNotMatch(csv, /combined total,\d/i);
});
test('money is withheld when G3 is unresolved, only assumed by nobody, or the review is missing, even if the engine returned an estimate', () => {
  for (const rv of [null, g3(false), { g3: { rfi: { status: 'open' }, facts: [{ id: 'o', label: 'x', path: '/p', status: 'human_assumption', value: 1, by: '', note: '' }] } }]) {
    const x = buildExport(priced('released'), rv); assert.equal(x.stampKind, 'unpriced');
    const csv = toCsv(x); assert.match(csv, /WITHHELD/); assert.doesNotMatch(csv, /Base Bid total|Alternate A-1 total|MATERIALS/i);
  }
});
test('document-confirmed G3 cites the document and names the acceptor; typed stays assumption; allowance statement present', () => {
  const rv: any = R(); rv.g3.facts = [{ id: 'o', label: 'G3 clear opening', unit: 'ft', path: '/gates/2/clear_width_ft', status: 'document_confirmed', value: 10, by: 'Pat', note: 'a.pdf, page 1: "GATE G3: ..."', source: { doc: 'a.pdf', page: 1, sha256: 'ab'.repeat(32) } },
    { id: 'p', label: 'G3 post OD', unit: 'in', path: '/p', status: 'human_assumption', value: 2.875, by: 'Sam', note: 'ASSUMED, RFI PENDING. SOURCE: x' }];
  const csv = toCsv(buildExport(priced('released'), rv));
  assert.match(csv, /DOCUMENT-CONFIRMED \(accepted addendum\),10 ft,accepted by Pat,"?a\.pdf, page 1/); assert.match(csv, /ASSUMPTION — RFI PENDING \(typed by a person/);
  assert.match(csv, /document SHA-256 (ab){32}/); assert.match(csv, /No project allowances carried\./); assert.match(csv, /included once above/);
  rv.g3.rfi = { id: 'RFI-G3', status: 'resolved_by_accepted_addendum', sent: false }; rv.g3.facts[1].status = 'document_confirmed';
  assert.match(toCsv(buildExport(priced('released'), rv)), /RESOLVED BY ACCEPTED ADDENDUM/);
});
test('wage note as recorded (name, preset provenance, raised-to-decision lines) is printed; cleared after an invalidation', () => {
  const pj = priced('released');
  pj.audit = [{ event: 'wage_determination_recorded', actor: 'Wanda', note: 'Reviewed | Preset recorded by Jordan; kept as recorded: Foreman. Laborer base raised from workbook $20.00 to the wage decision $24.50.' }];
  const csv = toCsv(buildExport(pj, R()));
  assert.match(csv, /Wanda \(self-declared\): Reviewed \| Preset recorded by Jordan/); assert.match(csv, /raised from workbook \$20\.00 to the wage decision \$24\.50/);
  pj.audit.push({ event: 'wage_determination_invalidated' });
  assert.match(toCsv(buildExport(pj, R())), /no wage determination is currently recorded/);
});

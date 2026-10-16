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
const sched = (extra: any = {}): any => ({ available: true, method: 'ALLOC-V1', combined_total: null, scenarios: {
  BASE: { items: [{ item_no: 10, description: 'Type A fence', unit: 'LF', quantity: 100, unit_price: 10.5, extended: 1050, status: 'PRICED', note: '', qualifier: '' },
    { item_no: 16, description: 'Fence guard', unit: 'LF', quantity: 20, unit_price: 3, extended: 60, status: 'PRICED', note: 'included in top-rail task', qualifier: '' }],
    engine_total: 1109.5, schedule_total: 1110, rounding_delta: 0.5, reconciliation: 'Schedule total 1110.00 vs engine total 1109.50: rounding delta +0.50', bid_revision: 'rev1', attribution_table_sha256: 'cd'.repeat(32) },
  'ALT-A1': { items: [{ item_no: 14, description: 'Gate G3', unit: 'EA', quantity: 1, status: 'NOT_IN_SCENARIO' }], reconciliation: 'ALT line', engine_total: 5, schedule_total: 5, rounding_delta: 0 } }, ...extra });
const wageView = (above: boolean): any => ({ decision: { decision_id: 'FDB-DP001', modification: '0', recorded_by: 'John Doe (test)' }, employer_burden: { pct: 0.35, source_ref: 'workbook Roles sheet' },
  role_classifications: [{ role: 'Foreman', classification: 'Laborer, common or general', classification_status: 'listed', base_rate: 32, fringe_rate: 9.1, decision_base_rate: 24.5, decision_fringe_rate: 9.1, above_decision: above, cleared: true, priced: { loaded: 55.4 }, problems: [] },
    { role: 'Laborer', classification: null, classification_status: null, base_rate: null, fringe_rate: null, cleared: false, problems: [{ code: 'WAGE_CLASSIFICATION_MISSING' }] }] });

test('per-item prices are labelled allocated, reconciliation printed verbatim, item 16 note shown, no combined total', () => {
  const pj = priced('released'); pj.pricing.bid_schedule = sched();
  const csv = toCsv(buildExport(pj, R()));
  assert.match(csv, /BASE BID — BID SCHEDULE ITEMS 10–16 \(ALLOCATED PRICES, ALLOC-V1, NOT VENDOR QUOTES\)/); assert.match(csv, /Unit price \(allocated\),Extension \(allocated\)/);
  assert.match(csv, /Schedule total 1110\.00 vs engine total 1109\.50: rounding delta \+0\.50/); assert.match(csv, /included in top-rail task/); assert.match(csv, /not in this scenario/);
  assert.match(csv, /ALLOC-V1; attribution table SHA-256 (cd){32}/); assert.match(csv, /items 1–9 and 17–21 are other trades/); assert.doesNotMatch(csv, /combined total,\s*\d/i);
});
test('an unavailable or refused schedule prints no per-item price and says why', () => {
  const pj = priced('released'); pj.pricing.bid_schedule = { available: false, reason: 'no engine total' };
  let csv = toCsv(buildExport(pj, R())); assert.match(csv, /NOT AVAILABLE — no engine total/); assert.doesNotMatch(csv, /Extension \(allocated\)/);
  pj.pricing.bid_schedule = sched(); pj.pricing.bid_schedule.scenarios.BASE = { available: false, refused: 'ATTRIBUTION_MISMATCH' };
  csv = toCsv(buildExport(pj, R())); assert.match(csv, /the engine refused the allocation: ATTRIBUTION_MISMATCH/);
  delete pj.pricing.bid_schedule; assert.match(toCsv(buildExport(pj, R())), /has not produced a bid schedule/);
});
test('per-role classifications print as recorded with the decision floor, above-decision flag and unassigned roles', () => {
  const pj = priced('released'); pj.pricing.wage = wageView(true);
  const csv = toCsv(buildExport(pj, R()));
  assert.match(csv, /Foreman,Laborer, common or general|Foreman,"Laborer, common or general",listed,32\.00,9\.10,24\.50,9\.10,ABOVE DECISION \(recorded rate prices\),yes,55\.40/);
  assert.match(csv, /Laborer,NOT ASSIGNED,.*NO,.*WAGE_CLASSIFICATION_MISSING/); assert.match(csv, /Employer burden 35\.00% of wages \(workbook Roles sheet\)/);
  assert.match(csv, /recorded by John Doe \(test\)/);
  assert.match(toCsv(buildExport(unpriced(), null)), /Wage classifications[\s\S]*NOT RECORDED/i);
});
test('gate assembly lines print per scenario with the arithmetic inputs; absent when the engine reports none', () => {
  const pj = priced('released'); pj.pricing.assumptions = { gate_assembly_lines: { BASE: [{ gate_id: 'G1', bid_item: 12, clear_width_ft: 4, gate_quantity: 1, opening_lf: 4, rate_per_lf: 30, extension: 120 }, { gate_id: 'G2', bid_item: 13, clear_width_ft: 12, gate_quantity: 2, opening_lf: 24, rate_per_lf: 30, extension: 720 }] } };
  const csv = toCsv(buildExport(pj, R()));
  assert.match(csv, /BASE BID — GATE ASSEMBLY \(RUN-TIME OVERRIDE: RATE PER LF OF CLEAR OPENING\)/); assert.match(csv, /G2,13,12,2,24,30\.00,720\.00/); assert.match(csv, /extension = rate per LF x opening LF/);
  assert.doesNotMatch(csv, /ALTERNATE A-1[^\n]*GATE ASSEMBLY/i);
  delete pj.pricing.assumptions; assert.doesNotMatch(toCsv(buildExport(pj, R())), /GATE ASSEMBLY/i);
});
test('G3 acceptance block prints every engine field; section is not stated; label falls back to filename; nulls print NOT RECORDED', () => {
  const rv: any = g3(false); rv.g3.facts = [{ id: 'opening', label: 'G3 clear opening', unit: 'ft', path: '/gates/2/clear_width_ft', status: 'document_confirmed', value: 12, by: 'Pat',
    acceptance: { accepted_by: 'Pat', accepted_utc: '2026-10-16T15:00:00Z', accepted_note: 'checked p3', scope_version_produced: 4, addendum_label: null, intake_id: 'ADD-1', sha256: 'cd'.repeat(32), filename: 'add02.pdf', page: 3, quoted: 'G3 clear width 12 ft', sheet_label: 'add02.pdf page 3' } }];
  const csv = toCsv(buildExport(unpriced(), rv));
  for (const t of ['Pat', '2026-10-16T15:00:00Z', 'checked p3', 'add02.pdf', 'cd'.repeat(32), 'G3 clear width 12 ft', 'add02.pdf page 3', 'ADD-1', 'not stated; cited by page and quote']) assert.ok(csv.includes(t), t);
  rv.g3.facts[0].acceptance.accepted_note = null; assert.match(toCsv(buildExport(unpriced(), rv)), /NOT RECORDED/);
});

// Tests for web/lib/export.ts: the bid export copies engine figures, carries authorization state, and never drops the readiness class. Run: npm run test:flight
import test from 'node:test';
import assert from 'node:assert/strict';
import { buildExport, toCsv, toHtml, ExportRefused } from '../lib/export.ts';

const scenario = { materials: { lines: [{ item_id: 'M01', description: '=HYPERLINK("http://x")', uom: 'EA', quantity: 2, order_quantity: 2, unit_price: 10, extended: 20, status: 'confirmed' }] },
  labor: { lines: [{ task_id: 'L01', task: 'Layout <b>', uom: 'LF', quantity: 5, crew_id: 'CR12', crew_hours: 1, worker_hours: 4, duration_days: 0.1, extended: 7 }] } };
const project = (status: string) => ({ project_id: 'P1', status, scope_version: 3, proposal_digest: 'ab'.repeat(32), approved_by: 'Pat', released_at: '2026-10-16T00:00:00Z', exceptions: [{ severity: 'blocking', code: 'MISSING_VALUE', question: 'G3 width?' }],
  estimate: { headline_scope_ref: 'BASE', scenarios: { BASE: scenario } },
  pricing: { ruleset: { ruleset_id: 'R', version: '1', contractor_approved: false, approved_by: 'Pat' }, estimate_view: { scope_ref: 'BASE', price_total: 27, price_per_lf: 5.4, fence_lf: 5, breakdown: [{ key: 'price_total', label: 'Total estimate', amount: 27 }], alternates: [{ scope_ref: 'ALT-A1', price_total: 20 }], qualifications: ['Assumed 12 ft'], advisories: [] } } });

test('refuses when nothing is priced', () => { assert.throws(() => buildExport({ status: 'needs_scope_review', estimate: null, pricing: {} }, null), ExportRefused); });
test('unreleased export is stamped DRAFT and lists holds', () => {
  const x = buildExport(project('ready_for_final_review'), null); assert.equal(x.stampKind, 'draft');
  assert.match(toCsv(x), /DRAFT — NOT AUTHORIZED/); assert.match(toCsv(x), /G3 width\?/); assert.match(x.filename, /DRAFT/);
});
test('released but not bid ready stays QUALIFIED / NOT A BID; bid_ready true is the only way to RELEASED', () => {
  assert.equal(buildExport(project('released'), { readiness: { selected: { bid_ready: false } } }).stampKind, 'qualified');
  assert.equal(buildExport(project('released'), null).stampKind, 'qualified');
  assert.equal(buildExport(project('released'), { readiness: { selected: { bid_ready: true } } }).stampKind, 'released');
});
test('totals are copied, alternate is separate, never added', () => {
  const csv = toCsv(buildExport(project('released'), null));
  assert.match(csv, /Total estimate,27\.00/); assert.match(csv, /Alternate A-1,20\.00/); assert.doesNotMatch(csv, /47\.00/);
});
test('CSV neutralizes formulas; HTML escapes markup', () => {
  const x = buildExport(project('released'), null);
  assert.match(toCsv(x), /'=HYPERLINK/); assert.doesNotMatch(toHtml(x), /<b>/); assert.match(toHtml(x), /&lt;b&gt;/);
});
test('exclusions are copied when the engine reports them and never invented', () => {
  assert.match(toCsv(buildExport(project('released'), null)), /None reported by the engine/);
  const pj: any = project('released'); pj.estimate.exclusions = ['Permits by others'];
  assert.match(toCsv(buildExport(pj, null)), /Permits by others/);
});

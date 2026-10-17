import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { crewRows, roleMix, crewStatus, crewLook, hasRun } from '../lib/crew-view.ts';
const crews = { crews: [
  { crew_id: 'CR11', name: 'Crew 1', efficiency_pct: 104, composition: [{ role: 'Foreman' }, { role: 'Laborer' }, { role: 'Laborer' }] },
  { crew_id: 'CR12', name: 'Crew 2', efficiency_pct: 94, composition: [{ role: 'Foreman' }, { role: 'Installer' }, { role: 'Installer' }, { role: 'Laborer' }] },
  { crew_id: 'CR13', name: 'Crew 3', efficiency_pct: 88, composition: [{ role: 'Installer' }, { role: 'Installer' }, { role: 'Equipment operator' }] },
  { crew_id: 'CR14', name: 'Crew 4', efficiency_pct: 97, composition: [{ role: 'Foreman' }, { role: 'Installer' }, { role: 'Installer' }, { role: 'Equipment operator' }] }] };
test('before the run all four crews read as available, with role mix and efficiency still shown; no cost before pricing', () => {
  const r = crewRows(crews, null);
  assert.deepEqual(r.map(x => x.id), ['CR11', 'CR12', 'CR13', 'CR14']);
  assert.equal(r[0].mix, '1 Foreman · 2 Laborers'); assert.deepEqual(r.map(x => x.efficiency), [104, 94, 88, 97]);
  for (const x of r) { assert.equal(x.eligibility.ineligible, false); assert.equal(x.eligibility.label, 'Available'); assert.doesNotMatch(x.eligibility.label, /Ineligible/); }
  assert.ok(r.every(x => x.cost === null));
  assert.deepEqual(crewRows(crews, { crew_comparison: { BASE: { tasks: [] } } }).map(x => x.eligibility.label), ['Available', 'Available', 'Available', 'Available']);      // a comparison with no tasks is not a run
});
test('once priced, eligibility comes from the engine comparison and the job labor cost is shown', () => {
  const cmp = { BASE: { tasks: [{ candidates: [{ crew_id: 'CR11', eligible: false }, { crew_id: 'CR12', eligible: false }, { crew_id: 'CR13', eligible: true }, { crew_id: 'CR14', eligible: true }] }], crews: [{ crew_id: 'CR13', labor_cost: 14176.07 }, { crew_id: 'CR14', labor_cost: 17039.77 }] } };
  const r = crewRows(crews, { crew_comparison: cmp });
  assert.equal(r[2].cost, 14176.07); assert.equal(r[3].cost, 17039.77); assert.equal(r[0].cost, null);
  assert.equal(r[2].eligibility.label, 'Eligible for every task'); assert.equal(r[0].eligibility.label, 'Ineligible (no operator)');
});
test('roleMix groups roles', () => assert.equal(roleMix([{ role: 'Installer' }, { role: 'Installer' }, { role: 'Equipment operator' }]), '2 Installers · 1 Equipment operator'));

const ran = { BASE: { tasks: [{ task: 'Set posts', candidates: [{ crew_id: 'CR11', eligible: false, reasons: ['No equipment operator'] }, { crew_id: 'CR12', eligible: false, reasons: ['No equipment operator'] }, { crew_id: 'CR13', eligible: true, reasons: [] }, { crew_id: 'CR14', eligible: true, reasons: [] }] }], crews: [] } };
test('after the run CR11 and CR12 show ineligible (no operator), CR13 and CR14 eligible; efficiency unchanged', () => {
  const r = crewRows(crews, { crew_comparison: ran });
  assert.deepEqual(r.map(x => x.eligibility.ineligible), [true, true, false, false]);
  assert.equal(r[0].eligibility.label, 'Ineligible (no operator)'); assert.equal(r[1].eligibility.label, 'Ineligible (no operator)');
  assert.equal(r[2].eligibility.label, 'Eligible for every task'); assert.deepEqual(r.map(x => x.efficiency), [104, 94, 88, 97]);
});
test('the Labor Gate still refuses CR11 and CR12 (selection follows crewStatus, never the display)', () => {
  const cmp = ran.BASE;
  assert.equal(hasRun(cmp), true); assert.equal(hasRun({ tasks: [] }), false); assert.equal(hasRun(undefined), false);
  assert.equal(crewStatus(cmp, 'CR11').ok, false); assert.equal(crewStatus(cmp, 'CR12').ok, false); assert.match(crewStatus(cmp, 'CR11').reasons.join(' '), /No equipment operator/);
  assert.equal(crewStatus(cmp, 'CR13').ok, true); assert.equal(crewStatus(cmp, 'CR14').ok, true);
  assert.equal(crewStatus({ tasks: [] }, 'CR13').ok, false);      // before the run nothing can be selected either; only the wording changed
  assert.equal(crewLook(false, false), 'available'); assert.equal(crewLook(true, false), 'ineligible'); assert.equal(crewLook(true, true), 'selectable');
  const src = readFileSync(new URL('../app/components/pricing.tsx', import.meta.url), 'utf8');
  assert.ok(src.includes('const status=(cid:string)=>crewStatus(cmp,cid);'));
  assert.ok(src.includes('can=st.ok&&(!p||p.valid)') && src.includes('disabled={!can}') && src.includes('aria-disabled={!can}'), 'a card that crewStatus refuses stays disabled');
});

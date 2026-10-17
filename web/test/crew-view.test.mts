import test from 'node:test';
import assert from 'node:assert/strict';
import { crewRows, roleMix } from '../lib/crew-view.ts';
const crews = { crews: [
  { crew_id: 'CR11', name: 'Crew 1', efficiency_pct: 104, composition: [{ role: 'Foreman' }, { role: 'Laborer' }, { role: 'Laborer' }] },
  { crew_id: 'CR12', name: 'Crew 2', efficiency_pct: 94, composition: [{ role: 'Foreman' }, { role: 'Installer' }, { role: 'Installer' }, { role: 'Laborer' }] },
  { crew_id: 'CR13', name: 'Crew 3', efficiency_pct: 88, composition: [{ role: 'Installer' }, { role: 'Installer' }, { role: 'Equipment operator' }] },
  { crew_id: 'CR14', name: 'Crew 4', efficiency_pct: 97, composition: [{ role: 'Foreman' }, { role: 'Installer' }, { role: 'Installer' }, { role: 'Equipment operator' }] }] };
test('all four crews, role mix and efficiency; no-operator crews are labelled ineligible before pricing; no cost before pricing', () => {
  const r = crewRows(crews, null);
  assert.deepEqual(r.map(x => x.id), ['CR11', 'CR12', 'CR13', 'CR14']);
  assert.equal(r[0].mix, '1 Foreman · 2 Laborers'); assert.equal(r[0].efficiency, 104);
  assert.equal(r[0].eligibility.label, 'Ineligible (no operator)'); assert.equal(r[1].eligibility.ineligible, true);
  assert.equal(r[2].eligibility.ineligible, false); assert.match(r[2].eligibility.label, /Labor Gate/);
  assert.ok(r.every(x => x.cost === null));
});
test('once priced, eligibility comes from the engine comparison and the job labor cost is shown', () => {
  const cmp = { BASE: { tasks: [{ candidates: [{ crew_id: 'CR11', eligible: false }, { crew_id: 'CR12', eligible: false }, { crew_id: 'CR13', eligible: true }, { crew_id: 'CR14', eligible: true }] }], crews: [{ crew_id: 'CR13', labor_cost: 14176.07 }, { crew_id: 'CR14', labor_cost: 17039.77 }] } };
  const r = crewRows(crews, { crew_comparison: cmp });
  assert.equal(r[2].cost, 14176.07); assert.equal(r[3].cost, 17039.77); assert.equal(r[0].cost, null);
  assert.equal(r[2].eligibility.label, 'Eligible for every task'); assert.equal(r[0].eligibility.label, 'Ineligible (no operator)');
});
test('roleMix groups roles', () => assert.equal(roleMix([{ role: 'Installer' }, { role: 'Installer' }, { role: 'Equipment operator' }]), '2 Installers · 1 Equipment operator'));

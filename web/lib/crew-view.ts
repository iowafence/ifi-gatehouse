// View-only roster rows for the sidebar. Everything shown is the engine's own crew data or its crew comparison; nothing is chosen, priced or approved here.
/* eslint-disable @typescript-eslint/no-explicit-any */
export type CrewRow = { id: string; name: string; efficiency: number; mix: string; eligibility: { label: string; ineligible: boolean }; cost: number | null };

const PLURAL: Record<string, string> = { Foreman: 'Foreman', Laborer: 'Laborers', Installer: 'Installers', 'Equipment operator': 'Equipment operator' };
export function roleMix(composition: { role: string }[]): string {
  const n = new Map<string, number>(); for (const m of composition || []) n.set(m.role, (n.get(m.role) || 0) + 1);
  return [...n.entries()].map(([r, k]) => `${k} ${k === 1 ? r : (PLURAL[r] || r + 's')}`).join(' · ');
}
const comparisonOf = (pricing: any) => { const c = pricing?.crew_comparison; if (!c || typeof c !== 'object') return null; const k = Object.keys(c); return c['BASE'] || (k.length === 1 ? c[k[0]] : null) || null; };

/** A project "has been run" once the engine's crew comparison has tasks (the same state the sidebar cost and the Labor Gate read). Before that, eligibility is not yet known. */
export const hasRun = (cmp: any): boolean => Array.isArray(cmp?.tasks) && cmp.tasks.length > 0;

/** Whether the Labor Gate lets this crew be chosen for the whole job, with the engine's reasons. The gate's refusal of an ineligible crew is exactly this. */
export function crewStatus(cmp: any, cid: string): { ok: boolean; reasons: string[] } {
  const reasons = new Set<string>(); let ok = hasRun(cmp);
  for (const t of cmp?.tasks || []) {
    const c = (t.candidates || []).find((x: any) => x.crew_id === cid);
    if (!c) { ok = false; reasons.add('The engine offers this crew no production rate for ' + t.task + '.'); continue; }
    if (!c.eligible) { ok = false; (c.reasons_display?.length ? c.reasons_display : c.reasons || []).forEach((r: string) => reasons.add(r)); }
  }
  return { ok, reasons: [...reasons] };
}
/** How a crew card looks. Display only: before the run every crew reads as available; after it the engine's answer decides. Selection is governed by crewStatus, never by this. */
export const crewLook = (ran: boolean, selectable: boolean): 'available' | 'selectable' | 'ineligible' => !ran ? 'available' : selectable ? 'selectable' : 'ineligible';

export function crewRows(crews: any, pricing: any): CrewRow[] {
  const list: any[] = Array.isArray(crews?.crews) ? crews.crews : [];
  const cmp = comparisonOf(pricing); const tasks: any[] = Array.isArray(cmp?.tasks) ? cmp.tasks : [];
  return list.map(c => {
    const noOp = !(c.composition || []).some((m: any) => /operator/i.test(m.role));
    const bad = tasks.filter(t => { const x = (t.candidates || []).find((y: any) => y.crew_id === c.crew_id); return !x || !x.eligible; });
    const ran = hasRun(cmp);
    const ineligible = ran ? bad.length > 0 : false;      // before the run nothing is shown as ineligible; the engine's rule and the Labor Gate are unchanged
    const label = ineligible ? (noOp ? 'Ineligible (no operator)' : 'Ineligible') : ran ? 'Eligible for every task' : 'Available';
    const row = (cmp?.crews || []).find((r: any) => r.crew_id === c.crew_id);
    return { id: c.crew_id, name: c.name, efficiency: c.efficiency_pct, mix: roleMix(c.composition), eligibility: { label, ineligible }, cost: typeof row?.labor_cost === 'number' ? row.labor_cost : null };
  });
}

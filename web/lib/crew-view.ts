// View-only roster rows for the sidebar. Everything shown is the engine's own crew data or its crew comparison; nothing is chosen, priced or approved here.
/* eslint-disable @typescript-eslint/no-explicit-any */
export type CrewRow = { id: string; name: string; efficiency: number; mix: string; eligibility: { label: string; ineligible: boolean }; cost: number | null };

const PLURAL: Record<string, string> = { Foreman: 'Foreman', Laborer: 'Laborers', Installer: 'Installers', 'Equipment operator': 'Equipment operator' };
export function roleMix(composition: { role: string }[]): string {
  const n = new Map<string, number>(); for (const m of composition || []) n.set(m.role, (n.get(m.role) || 0) + 1);
  return [...n.entries()].map(([r, k]) => `${k} ${k === 1 ? r : (PLURAL[r] || r + 's')}`).join(' · ');
}
const comparisonOf = (pricing: any) => { const c = pricing?.crew_comparison; if (!c || typeof c !== 'object') return null; const k = Object.keys(c); return c['BASE'] || (k.length === 1 ? c[k[0]] : null) || null; };

export function crewRows(crews: any, pricing: any): CrewRow[] {
  const list: any[] = Array.isArray(crews?.crews) ? crews.crews : [];
  const cmp = comparisonOf(pricing); const tasks: any[] = Array.isArray(cmp?.tasks) ? cmp.tasks : [];
  return list.map(c => {
    const noOp = !(c.composition || []).some((m: any) => /operator/i.test(m.role));
    const bad = tasks.filter(t => { const x = (t.candidates || []).find((y: any) => y.crew_id === c.crew_id); return !x || !x.eligible; });
    const ineligible = tasks.length ? bad.length > 0 : noOp;
    const label = ineligible ? (noOp ? 'Ineligible (no operator)' : 'Ineligible') : tasks.length ? 'Eligible for every task' : 'Eligibility confirmed at the Labor Gate';
    const row = (cmp?.crews || []).find((r: any) => r.crew_id === c.crew_id);
    return { id: c.crew_id, name: c.name, efficiency: c.efficiency_pct, mix: roleMix(c.composition), eligibility: { label, ineligible }, cost: typeof row?.labor_cost === 'number' ? row.labor_cost : null };
  });
}

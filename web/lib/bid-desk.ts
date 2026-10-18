// Gatehouse Bid Desk: an ADVISORY helper. It answers from the engine's current project state and the registered scope draft only. It calls no model,
// writes no audit record, approves nothing and never supplies a value. Chat is not an audit record. Every "Open source" comes from engine evidence.
// This deterministic desk is the labelled SIMULATED desk and the fallback for the live Evolus desk (lib/evolus-desk.ts).
import { blockingPhrase, blockingStatus, buildScopeGates, currentGate, type Src } from './scope-gates.ts';

/* eslint-disable @typescript-eslint/no-explicit-any */
export const DESK_MAX_CHARS = 400;
export type GateStateView = { stage: string; status: string; scope_version: number | null; blocking: number; g3: string; addendum: string; crew: string; total: string; release: string };
export type DeskReply = { advisory: true; audit_record: false; mode: 'SIMULATED' | 'LIVE' | 'UNAVAILABLE'; live: { enabled: false; reason: string }; gate_state: GateStateView; intent: string; answer: string; sources: Src[] };

export const liveReason = () => 'The live Evolus desk is switched off; this is the built-in simulated desk.';

/** `p` is the adapted project (lib/adapt.ts fromEngine). */
export function gateStateOf(p: any, draft: any | null = null): GateStateView {
  const gates = buildScopeGates(p, draft, null);
  const g3 = gates.find(g => g.id === 'g3');
  const addenda: any[] = p.addenda || [];
  const plan = p.pricing?.crew_plan;
  const status = String(p.status || 'unknown');
  const stage = status === 'needs_scope_review' ? 'Scope Gate' : status === 'needs_labor_review' ? 'Labor Gate' : status === 'ready_for_final_review' ? 'Release Gate' : status === 'released' ? 'Released' : status;
  const total = plan && typeof p.pricing?.estimate_view?.price_total === 'number' ? 'engine total available (see Release Gate)' : 'withheld until a crew is selected';
  return { stage, status, scope_version: p.scope_version ?? null, blocking: blockingStatus(p).count,
    g3: g3 ? (g3.blocking ? `missing width, blocking, ${g3.tag}` : String(g3.tag || 'resolved').toLowerCase().replace(/_/g, ' ')) : 'unknown',
    addendum: addenda.some(a => a.status === 'APPLIED') ? 'accepted' : addenda.some(a => a.status === 'PROPOSED') ? 'proposed, waiting for a named person' : 'none uploaded',
    crew: plan?.preferred_crew ? `${plan.preferred_crew} for the whole job (plan v${plan.plan_version})` : 'not selected', total, release: status === 'released' ? 'released (self-declared approver)' : 'not released' };
}

const clipT = (x: unknown, n: number) => String(x ?? '').replace(/\s+/g, ' ').trim().slice(0, n);
export type CrewRow = { crew_id: string; name: string; eligible: boolean; why: string; labor_cost: number | null };
/** Crews from the engine's crew comparison: eligible for the whole job or not, and the engine's own reason when not. Read-only; nothing is calculated here. */
export function crewRows(p: any): CrewRow[] {
  const cmp = p?.pricing?.crew_comparison?.BASE;
  const crews: any[] = Array.isArray(cmp?.crews) ? cmp.crews : [], tasks: any[] = Array.isArray(cmp?.tasks) ? cmp.tasks : [];
  return crews.map(c => {
    const id = String(c.crew_id); let why = '';
    if (c.complete !== true) for (const t of tasks) { const cand = (t.candidates || []).find((x: any) => x.crew_id === id && x.eligible === false); if (cand) { why = clipT(cand.reasons_display?.[0] ?? cand.reasons?.[0] ?? 'not eligible for a task', 90); break; } }
    return { crew_id: id, name: clipT(c.description, 60), eligible: c.complete === true, why: c.complete === true ? '' : (why || 'not eligible for every task'), labor_cost: typeof c.labor_cost === 'number' ? c.labor_cost : null };
  });
}
const usd = (n: number) => `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const has = (m: string, re: RegExp) => re.test(m);
export function answer(p: any, message: string, draft: any | null, crewBid: { scope_ref: string | null; totals: { crew_id: string; whole_bid_total_usd: number | null }[] } | null = null): DeskReply {
  const m = String(message || '').slice(0, DESK_MAX_CHARS).toLowerCase();
  const gs = gateStateOf(p, draft);
  const gates = buildScopeGates(p, draft, null);
  const cur = currentGate(gates);
  const base = { advisory: true as const, audit_record: false as const, mode: 'SIMULATED' as const, live: { enabled: false as const, reason: liveReason() }, gate_state: gs };
  const out = (intent: string, text: string, sources: Src[] = []): DeskReply => ({ ...base, intent, answer: text, sources: sources.slice(0, 4) });
  if (has(m, /\b(approve|authori[sz]e|release|sign|accept|submit|send)\b/)) return out('refuse_authority', 'I cannot approve, accept, release or send anything. Only a named person can, at the gate that asks for it. I can tell you what that gate is waiting for.');
  if (has(m, /\bg3\b|third gate|gate 3/)) {
    const g = gates.find(x => x.id === 'g3')!;
    return out('g3', g.blocking ? 'Gate G3 has no clear opening width in the documents, and Addendum 01 says it does not establish one. It stays blocking until Addendum 02 is accepted by a named person, or a named person enters a value as an assumption.' : `Gate G3: ${g.summary}`, g.findings.flatMap(f => f.src || []));
  }
  if (has(m, /\bg2\b|second gate|gate 2/)) {
    const g = gates.find(x => x.id === 'g2')!;
    return out('g2', 'Gate G2 is corrected. Addendum 01 revises it from a 6\'-0" single-leaf opening to a 12\'-0" double-leaf opening, and the Rev 0 value is kept only for traceability.', g.findings.flatMap(f => f.src || []));
  }
  if (has(m, /\baddend/)) return out('addendum', `Addendum status: ${gs.addendum}. An uploaded addendum shows Before → After and changes nothing until a named person accepts it.`);
  if (has(m, /\bcrew|operator|eligib/) && crewBid && crewBid.totals.length) {
    const rows = crewRows(p), tot = (id: string) => crewBid.totals.find(t => t.crew_id === id)?.whole_bid_total_usd;
    const ok = rows.filter(r => r.eligible).map(r => `${r.crew_id}: ${typeof tot(r.crew_id) === 'number' ? `whole-bid total ${usd(tot(r.crew_id) as number)}` : 'whole-bid total not available'}`);
    const no = rows.filter(r => !r.eligible).map(r => `${r.crew_id}: ${r.why}`);
    return out('crew', `Eligible crews and Gatehouse-calculated whole-bid totals${crewBid.scope_ref ? ` (${crewBid.scope_ref})` : ''}: ${ok.join('; ')}.${no.length ? ` Not eligible: ${no.join('; ')}.` : ''} Choose one crew for the whole job at the Labor Gate. This desk does not select or recommend a crew.`);
  }
  if (has(m, /\bcrew|operator|eligib/)) return out('crew', gs.crew === 'not selected' ? 'No crew is selected. Choose one crew for the whole job at the Labor Gate. Crews without an equipment operator are ineligible, and you confirm availability yourself.' : `Selected: ${gs.crew}. A different crew replaces it as a whole; crews are never mixed.`);
  if (has(m, /\btotal|price|cost|bid\b|how much/)) return out('total', `Total: ${gs.total}. Base Bid and Alternate A-1 are separate; Alternate A-1 is in lieu of the Base Bid and is never added to it.`);
  if (has(m, /\bblock|stop|why|hold|next|what now|status|where am i|help\b/) || !m.trim()) {
    const first = cur ? cur.findings.flatMap(f => f.src || []) : [];
    return out('status', cur ? `You are at the ${gs.stage}. ${gs.blocking} item${gs.blocking === 1 ? '' : 's'} block pricing. Work on "${cur.title}" next: ${cur.summary}` : (blockingStatus(p).clear ? `You are at the ${gs.stage}. No scope item blocks pricing now.` : `You are at the ${gs.stage}. ${blockingPhrase(blockingStatus(p))}.`), first);
  }
  return out('unknown', 'I can only help with the current gate state: what blocks you, G2, G3, addenda, crews, totals, and who must authorize. I do not invent values.');
}

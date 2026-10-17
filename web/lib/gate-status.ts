// One status model for the Scope Gate and the export. The assumption list and the RFI state are computed by the export's own deriveStatus (not re-implemented),
// and the G3 fact states come from the same takeoff review the export prints, so the two cannot disagree. Pure: nothing here decides or changes anything.
/* eslint-disable @typescript-eslint/no-explicit-any */
import { deriveStatus } from './export.ts';

export type FactState = 'resolved_addendum' | 'assumed_human' | 'unresolved';
export type Assumption = { text: string; owner: string; sentence: string };
export type ScopeStatus = {
  g3: { state: 'resolved' | 'assumed' | 'open' | 'unknown'; facts: { id: string; label: string; path: string; state: FactState; value: string; by: string | null }[];
        rfi: { id: string; closed: boolean | null; label: string }; addendum: { filename: string | null; page: unknown; quoted: unknown; by: string | null; label: string | null } | null };
  assumptions: Assumption[];            // the export's "Open item" lines, verbatim source
  g3Station: { ft: string; owner: string } | null;
  notBidReady: boolean | null;          // null when the review is unavailable
};

const stateOf = (s: string): FactState => s === 'document_confirmed' || s === 'document-confirmed' ? 'resolved_addendum' : s === 'human_assumption' ? 'assumed_human' : 'unresolved';

export function scopeStatus(project: any, review: any | null): ScopeStatus {
  const st = deriveStatus(project || {}, review, project?.pricing?.estimate_view ?? null);
  const facts = ((review?.g3?.facts || []) as any[]).map(f => ({ id: String(f.id), label: String(f.label), path: String(f.path), state: stateOf(String(f.status)), value: f.value === null || f.value === undefined ? 'no value' : `${f.value} ${f.unit || ''}`.trim(), by: f.by ?? null }));
  const state = !facts.length ? 'unknown' : facts.every(f => f.state === 'resolved_addendum') ? 'resolved' : facts.some(f => f.state === 'unresolved') ? 'open' : 'assumed';
  const acc = ((review?.g3?.facts || []) as any[]).map(f => f.acceptance).find(Boolean) || null;
  const assumptions: Assumption[] = st.openAssumptions.map(sentence => {
    const m = /\(owner:\s*([^,)]+)/i.exec(sentence);
    return { sentence, owner: m ? m[1].trim() : 'not stated', text: sentence.replace(/^Qualified assumption \([^)]*\):\s*/i, '') };
  });
  const loc = assumptions.map(a => ({ a, m: /\bG3\s+(\d+(?:\.\d+)?)\s*ft/i.exec(a.text) })).find(x => x.m);
  const sel = review?.readiness?.selected;
  return { g3: { state, facts, rfi: { id: st.rfi.id, closed: review?.g3?.rfi ? st.rfi.resolved : null, label: st.rfi.label },
    addendum: acc ? { filename: acc.filename ?? null, page: acc.page ?? null, quoted: acc.quoted ?? null, by: acc.accepted_by ?? null, label: acc.addendum_label ?? null } : null },
    assumptions, g3Station: loc ? { ft: loc.m![1], owner: loc.a.owner } : null, notBidReady: sel ? sel.bid_ready !== true : null };
}

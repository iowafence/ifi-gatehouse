// Discovery-first Scope Gate model. Pure: it only re-arranges what the engine, the registered scope draft and the stored AI findings already say.
// Nothing here decides a value, resolves an exception or computes a price. Every finding carries the provenance of the thing it came from.
/* eslint-disable @typescript-eslint/no-explicit-any */

import { scopeStatus } from './gate-status.ts';
import { contradictionCountText } from './contradiction.ts';

export type Prov = 'AGENT-FOUND' | 'ADDENDUM' | 'ENGINE-FLAGGED' | 'ENGINE-CALCULATED' | 'HUMAN';
export type Src = { doc_id?: string; page?: number; sheet?: string; excerpt?: string };
export type Finding = { prov: Prov; text: string; note?: string; src?: Src[]; model?: string; byline?: string; evolus?: boolean };
export const NOT_REPORTED = 'NOT_REPORTED';
export type Gate = {
  id: 'g2' | 'g3' | 'bid' | 'inferred' | 'assumed' | 'other';
  title: string;
  state: 'corrected' | 'open' | 'resolved' | 'info';
  blocking: boolean;
  tag?: string;                // e.g. ADDENDUM_PENDING
  summary: string;
  exceptionIds: string[];      // the engine exceptions this gate covers; the existing decision form acts on these
  findings: Finding[];
};

const G3_WIDTH = '/gates/2/clear_width_ft';
const isG3 = (id: string) => id.includes(G3_WIDTH) || id.includes('GATE_G3');
const exOpen = (e: any) => (e.status ?? 'open') !== 'resolved';
const toSrc = (e: any): Src => ({ doc_id: e.doc_id, page: e.page, sheet: e.sheet ?? e.sheet_label, excerpt: e.excerpt });

const claimOf = (f: any) => (f && typeof f.claim === 'object' && f.claim ? f.claim : {});
const runIdOf = (f: any): string | null => (f && typeof f.run === 'object' && f.run && typeof f.run.run_id === 'string' ? f.run.run_id : null);
/** The card byline for a stored Evolus draft: the real run id, and a model name only when the run itself returned one. */
export function evolusByline(d: any): string {
  const m = typeof d?.model_returned === 'string' && d.model_returned ? d.model_returned : null;
  return `Evolus agent · run ${d?.run_id ?? 'NOT_RECORDED'} · ${m ? `model ${m}` : 'model not reported by the run'}`;
}
/** Who produced a finding, from the finding's own record: the model the provider RETURNED and the real run id. Anything the record does not state reads NOT_REPORTED. */
export function attribution(fs: any[]): string {
  const seen = new Set<string>();
  for (const f of fs) {
    if (f?.provenance !== 'REAL_AMD_OUTPUT') continue;
    const m = typeof f.model?.returned === 'string' && f.model.returned ? f.model.returned : null; const r = runIdOf(f);
    if (m && r) seen.add(`${m} · run ${r}`);
  }
  return seen.size ? [...seen].join('; ') : NOT_REPORTED;
}
const classCounts = (fs: any[]) => { const m = new Map<string, number>(); for (const f of fs) m.set(String(f.classification), (m.get(String(f.classification)) || 0) + 1); return m; };

/** `project` is the adapted project (lib/adapt.ts). `draft` is the registered human-prepared scope draft; `ai` the stored findings ledger (either may be absent). */
export function buildScopeGates(project: any, draft: any | null, ai: any | null, review: any | null = null): Gate[] {
  const rs = review ? scopeStatus(project, review) : null;   // the export's own state, when the takeoff review is available
  const ex: any[] = project?.exceptions || [];
  const audit: any[] = project?.audit || [];
  const addenda: any[] = project?.addenda || [];
  const item = (id: string) => (draft?.items || []).find((i: any) => i.id === id);
  const real: any[] = (ai?.findings || []).filter((f: any) => f?.provenance === 'REAL_AMD_OUTPUT');
  // What the stored real model outputs say about one gate's tag and symbol. They never state an opening width; that is checked, not assumed.
  const gateObservation = (gate: 'G2' | 'G3'): Finding | null => {
    const fs = real.filter(f => claimOf(f).key === gate && /^gate_(tag_position|symbol)$/.test(String(claimOf(f).category)));
    if (!fs.length) return null;
    const sym = fs.filter(f => claimOf(f).category === 'gate_symbol'), pos = fs.filter(f => f.classification === 'GATE_LABEL_POSITION_CONFIRMED');
    const widthClaim = real.some(f => new RegExp(`\\b${gate}\\b`).test(String(claimOf(f).text)) && /clear opening|\d+'-\d/.test(String(claimOf(f).text)));
    return { prov: 'AGENT-FOUND', model: attribution(fs),
      text: sym.length ? `A model read the ${gate} gate symbol: ${sym.map(f => `“${claimOf(f).text}”`).join('; ')}.` : `A model located the ${gate} gate tag on the C101 plan.`,
      note: `Tag position confirmed against the PDF's printed label positions on ${pos.length} observation${pos.length === 1 ? '' : 's'}. Symbol readings are not verified by the drawing and do not state an opening width.${widthClaim ? '' : ` No stored model output states a ${gate} opening width.`}` };
  };
  const humanFor = (frag: string) => audit.filter(a => a.event_type === 'resolved' && String(a.exception_id || '').includes(frag));

  // ---- G2: corrected by the controlling addendum
  const g2i = item('gate-g2');
  const g2: Gate = { id: 'g2', title: 'Gate G2', state: 'corrected', blocking: false, summary: "Corrected: Addendum 01 supersedes the Rev 0 opening. Nothing to decide.", exceptionIds: [], findings: [] };
  { const o = gateObservation('G2'); if (o) g2.findings.push(o); }
  if (g2i) {
    const ev = (g2i.evidence || []).filter((e: any) => !e.superseded_by);
    g2.findings.push({ prov: 'ADDENDUM', text: g2i.text, note: `Corrected value: ${g2i.figure}`, src: ev.map(toSrc) });
    const old = (g2i.evidence || []).filter((e: any) => e.superseded_by);
    if (old.length) g2.findings.push({ prov: 'ENGINE-FLAGGED', text: 'Rev 0 sources kept for traceability only; they are not used as a value.', src: old.map(toSrc) });
  } else g2.findings.push({ prov: 'ENGINE-FLAGGED', text: 'The registered scope draft is not available, so the G2 correction cannot be shown here.' });

  // ---- G3: width, post and footing. State comes from the same review the export prints; without it, from the engine's open exceptions.
  const g3ex = ex.filter(e => isG3(String(e.exception_id)) && e.code === 'MISSING_VALUE' && exOpen(e));
  const applied = addenda.find(a => a.status === 'APPLIED'); const proposed = addenda.find(a => a.status === 'PROPOSED');
  const g3human = humanFor('GATE_G3').concat(humanFor('gates/2'));
  const known = !!rs && rs.g3.state !== 'unknown';
  const g3open = known ? rs!.g3.state === 'open' : g3ex.length > 0;
  const byAddendum = known ? rs!.g3.state === 'resolved' : !g3open && !!applied;
  const byHuman = known ? rs!.g3.state === 'assumed' : !g3open && !applied && g3human.length > 0;
  const g3tag = g3open ? (proposed ? 'ADDENDUM_PROPOSED' : 'ADDENDUM_PENDING') : byAddendum ? 'ADDENDUM_ACCEPTED' : byHuman ? 'HUMAN_ASSUMPTION' : undefined;
  const g3i = item('gate-g3'); const rfi = (project?.rfi_drafts || []).find((r: any) => r.gate_id === 'G3');
  const adName = rs?.g3.addendum?.label || rs?.g3.addendum?.filename || applied?.filename || 'the accepted addendum';
  const g3: Gate = { id: 'g3', title: 'Gate G3', state: g3open ? 'open' : 'resolved', blocking: g3open, tag: g3tag, exceptionIds: g3open ? g3ex.map(e => e.exception_id) : [],
    summary: g3open ? 'Missing gate width. Blocking until a document or a named person supplies it.' : byAddendum ? `Width, post size and footing are resolved by ${adName} (ADDENDUM).` : 'Entered by a named person as an assumption. It does not block release; the RFI stays pending.', findings: [] };
  if (g3open) {
    g3.findings.push({ prov: 'ENGINE-FLAGGED', text: 'G3 clear opening width is not supported by the documents (and neither are its post size, footing diameter and depth).', note: `${g3ex.length || 'Several'} blocking value${g3ex.length === 1 ? '' : 's'} missing.`, src: g3i ? (g3i.evidence || []).map(toSrc) : (g3ex[0]?.evidence || []).map(toSrc) });
    { const o = gateObservation('G3'); if (o) g3.findings.push(o); }
    if (rfi) g3.findings.push({ prov: 'ENGINE-CALCULATED', text: `RFI draft ${rfi.draft_id}: ${rfi.subject}`, note: 'A draft question only. Nothing has been sent.', src: (rfi.citations || []).map(toSrc) });
  } else if (byAddendum && rs) {
    const ad = rs.g3.addendum;
    for (const f of rs.g3.facts) { const c = f.cite;   // each row cites its own page and quote, the same acceptance record the export prints
      g3.findings.push({ prov: 'ADDENDUM', text: `${f.label}: ${f.value} — resolved by ${adName}`, note: ad ? `Accepted by ${ad.by ?? 'a named person'} (self-declared). Cited ${ad.filename ?? 'the addendum'}${c?.page ? `, page ${c.page}` : ''}${c?.quoted ? `: “${c.quoted}”` : ''}.` : undefined }); }
    g3.findings.push({ prov: 'ENGINE-CALCULATED', text: `${rs.g3.rfi.id}: ${rs.g3.rfi.closed ? 'RESOLVED by the accepted addendum (closed)' : rs.g3.rfi.label}`, note: rs.g3.rfi.closed ? 'No RFI is pending for G3.' : undefined });
  } else if (byHuman) {
    for (const f of (rs?.g3.facts || []).filter(x => x.state === 'assumed_human')) g3.findings.push({ prov: 'HUMAN', text: `${f.by ?? 'A named person'} entered ${f.label}: ${f.value}`, note: 'An assumption, not a document fact. It stays an assumption until a document states it; it does not block release.' });
    if (!rs) for (const a of g3human.slice(-2)) g3.findings.push({ prov: 'HUMAN', text: `${a.actor ?? 'A named person'} entered a value: ${a.note ?? ''}`, note: 'An assumption, not a document fact.' });
    if (rs) g3.findings.push({ prov: 'ENGINE-CALCULATED', text: `${rs.g3.rfi.id}: ${rs.g3.rfi.label}` });
  }
  // The stored Evolus RFI drafts for G3: AGENT-FOUND, with the run id and the model the run record names. Drafts only; nothing was ever sent.
  for (const d of ((ai?.evolus_drafts || []) as any[]).filter(x => x?.gate === 'G3')) {
    g3.findings.push({ prov: 'AGENT-FOUND', byline: evolusByline(d), evolus: true, text: `Evolus RFI draft: ${d.subject}`,
      note: `${d.question} ${g3open ? 'Pending human review, never sent.' : 'Never sent. The record still says PENDING_HUMAN_REVIEW; its question is now answered by the accepted addendum and it is kept as history.'}${d.assessment ? ` Independent audit: ${d.assessment}.` : ''}` });
  }
  if (!g3open && g3i) g3.findings.push({ prov: 'ENGINE-FLAGGED', text: 'History · original exception: the G3 clear opening width, post size, footing diameter and depth were not supported by the documents.', note: 'RESOLVED. Kept as history; it is no longer open.', src: (g3i.evidence || []).map(toSrc) });
  if (rs?.g3Station) g3.findings.push({ prov: 'HUMAN', text: `G3 location: station ${rs.g3Station.ft} ft is ASSUMED`, note: `Owner ${rs.g3Station.owner}. Clears only when a document states it. An assumption, not a blocker: it keeps NOT BID READY but does not block release.` });

  // ---- Bid selection
  const bidEx = ex.filter(e => e.code === 'BID_SELECTION_REQUIRED' && exOpen(e));
  const bidHuman = humanFor('BID_SELECTION');
  const bid: Gate = { id: 'bid', title: 'Which bid is priced', state: bidEx.length ? 'open' : 'resolved', blocking: bidEx.length > 0, exceptionIds: bidEx.map(e => e.exception_id),
    summary: bidEx.length ? 'Choose Base Bid or Alternate A-1. They are priced and exported separately; Alternate A-1 is in lieu of the Base Bid, never added to it.' : 'Chosen. Base Bid and Alternate A-1 stay separate.', findings: [] };
  if (bidEx.length) bid.findings.push({ prov: 'ENGINE-FLAGGED', text: bidEx[0].question, src: (bidEx[0].evidence || []) });
  for (const a of bidHuman.slice(-1)) bid.findings.push({ prov: 'HUMAN', text: `${a.actor ?? 'A named person'} chose: ${a.option_id ?? ''}`, note: a.note });

  // ---- Inferred quantities and stations
  const inf = ex.filter(e => e.code === 'INFERRED_FACT_UNAPPROVED' && exOpen(e));
  const spatial = real.filter((f: any) => f.relationship_key);
  const inferred: Gate = { id: 'inferred', title: 'Inferred lengths and gate stations', state: inf.length ? 'open' : 'resolved', blocking: inf.length > 0, exceptionIds: inf.map(e => e.exception_id),
    summary: inf.length ? `${inf.length} value${inf.length === 1 ? ' is' : 's are'} derived from written dimensions, not stated by a document. Each needs a named person to approve it.` : 'All inferred values are approved by a named person.', findings: [] };
  if (inf.length) inferred.findings.push({ prov: 'ENGINE-CALCULATED', text: `${inf.length} derived value${inf.length === 1 ? '' : 's'}: run lengths, gate stations and one continuity rule.`, note: inf.slice(0, 3).map(e => e.question).join(' · ') + (inf.length > 3 ? ' …' : '') });
  if (spatial.length) {
    // Each count says WHAT it was checked against: label positions against the PDF's printed text positions, fence-type leaders against vector geometry, symbols against nothing.
    const c = classCounts(spatial), n = (k: string) => c.get(k) || 0; const parts: string[] = [];
    if (n('GATE_LABEL_POSITION_CONFIRMED')) parts.push(`${n('GATE_LABEL_POSITION_CONFIRMED')} gate-label positions confirmed against the PDF's printed text positions`);
    if (n('VECTOR_CONFIRMED')) parts.push(`${n('VECTOR_CONFIRMED')} fence-type leader confirmed against the drawing's vector geometry`);
    parts.push(...contradictionCountText(spatial));      // split by how each was contradicted, from its stored verdict
    if (n('NOT_VERIFIED_VISUAL_ONLY')) parts.push(`${n('NOT_VERIFIED_VISUAL_ONLY')} symbol readings not verified`);
    const rest = spatial.length - n('GATE_LABEL_POSITION_CONFIRMED') - n('VECTOR_CONFIRMED') - n('CONTRADICTED_BY_DRAWING_EVIDENCE') - n('NOT_VERIFIED_VISUAL_ONLY');
    if (rest > 0) parts.push(`${rest} other (false candidate, unresolved or not formally verified)`);
    inferred.findings.push({ prov: 'AGENT-FOUND', model: attribution(spatial), text: `${spatial.length} stored model observations of the C101 gate and fence tags: ${parts.join('; ')}.`, note: 'Candidates only. They never approve a value; a named person does.' });
  }

  // ---- Everything the engine flagged that does not block
  const assumed: Gate = { id: 'assumed', title: 'Assumptions', state: 'info', blocking: false, tag: rs?.notBidReady ? 'NOT_BID_READY' : undefined, exceptionIds: [],
    summary: rs?.assumptions.length ? `${rs.assumptions.length} assumption${rs.assumptions.length === 1 ? '' : 's'} keep NOT BID READY. They do not block release.` : 'None recorded yet. They appear once the estimate is priced.', findings: [] };
  for (const a of rs?.assumptions || []) assumed.findings.push({ prov: 'HUMAN', text: a.text, note: `Owner ${a.owner}. Clears only when a document states it.` });
  // The engine's footing advisories restate G3 as an open RFI; the assumptions gate above states the same fact once, from the export's state.
  const adv = ex.filter(e => e.code !== 'FOOTING_SCOPE_NOT_BID_READY' && (e.severity === 'advisory' || (!e.blocking && e.severity !== 'blocking')) && exOpen(e));
  const other: Gate = { id: 'other', title: 'Advisories', state: 'info', blocking: false, exceptionIds: adv.map(e => e.exception_id), summary: adv.length ? `${adv.length} item${adv.length === 1 ? '' : 's'} for awareness. None blocks pricing on its own.` : 'None.', findings: [] };
  for (const e of adv.slice(0, 6)) other.findings.push({ prov: 'ENGINE-FLAGGED', text: e.question, src: e.evidence || [] });

  return [g2, g3, bid, inferred, assumed, other];
}

/** ONE count of the engine's open blocking exceptions, of ANY kind, for the banner, the card and the Bid Desk. Gate cards track only some kinds; this does not. */
export type BlockingStatus = { count: number; clear: boolean; first: { id: string; kind: string; question: string } | null };
export function blockingStatus(project: any): BlockingStatus {
  const open: any[] = (project?.exceptions || []).filter((e: any) => (e?.blocking || e?.severity === 'blocking') && exOpen(e));
  const f = open[0];
  return { count: open.length, clear: open.length === 0, first: f ? { id: String(f.exception_id), kind: String(f.code ?? 'EXCEPTION'), question: String(f.question ?? f.message ?? f.exception_id) } : null };
}
export const blockingPhrase = (b: BlockingStatus): string => `${b.count} blocking exception${b.count === 1 ? '' : 's'} ${b.count === 1 ? 'remains' : 'remain'} open${b.first ? `. First: ${b.first.question}` : ''}`;
/** The card's heading and lead. "All scope gates cleared" and the Continue prompt need ZERO open blocking exceptions of any kind, not just gates the cards track. */
export function discoveryHeading(gates: Gate[], project: any): { cleared: boolean; heading: string; lead: string; untracked: number } {
  const b = blockingStatus(project); const cur = currentGate(gates);
  const tracked = new Set(gates.flatMap(g => g.exceptionIds));
  const untracked = (project?.exceptions || []).filter((e: any) => (e?.blocking || e?.severity === 'blocking') && exOpen(e) && !tracked.has(e.exception_id)).length;
  if (cur) return { cleared: false, heading: `Now: ${cur.title}`, lead: 'Work on one gate at a time. Everything found is listed with where it came from.', untracked };
  if (b.clear) return { cleared: true, heading: 'All scope gates cleared', lead: 'Nothing blocks the scope now. Continue to the Labor Gate.', untracked: 0 };
  return { cleared: false, heading: `${b.count} blocking exception${b.count === 1 ? '' : 's'} still open`, lead: `${blockingPhrase(b)}. No gate card tracks ${b.count === 1 ? 'it' : 'these'}; ${b.count === 1 ? 'it' : 'they'} must be resolved before the Labor Gate.`, untracked };
}

/** The one gate to work on now: the first blocking gate that is still open. */
export const currentGate = (gates: Gate[]): Gate | null => gates.find(g => g.state === 'open' && g.blocking) ?? null;

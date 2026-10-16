// Discovery-first Scope Gate model. Pure: it only re-arranges what the engine, the registered scope draft and the stored AI findings already say.
// Nothing here decides a value, resolves an exception or computes a price. Every finding carries the provenance of the thing it came from.
/* eslint-disable @typescript-eslint/no-explicit-any */

export type Prov = 'AGENT-FOUND' | 'ADDENDUM' | 'ENGINE-FLAGGED' | 'ENGINE-CALCULATED' | 'HUMAN';
export type Src = { doc_id?: string; page?: number; sheet?: string; excerpt?: string };
export type Finding = { prov: Prov; text: string; note?: string; src?: Src[] };
export type Gate = {
  id: 'g2' | 'g3' | 'bid' | 'inferred' | 'other';
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

/** `project` is the adapted project (lib/adapt.ts). `draft` is the registered human-prepared scope draft; `ai` the stored findings ledger (either may be absent). */
export function buildScopeGates(project: any, draft: any | null, ai: any | null): Gate[] {
  const ex: any[] = project?.exceptions || [];
  const audit: any[] = project?.audit || [];
  const addenda: any[] = project?.addenda || [];
  const item = (id: string) => (draft?.items || []).find((i: any) => i.id === id);
  const finding = (id: string) => (ai?.findings || []).find((f: any) => f.finding_id === id);
  const humanFor = (frag: string) => audit.filter(a => a.event_type === 'resolved' && String(a.exception_id || '').includes(frag));

  // ---- G2: corrected by the controlling addendum
  const g2i = item('gate-g2'); const g2ai = finding('SIM-g2-rev0-6ft');
  const g2: Gate = { id: 'g2', title: 'Gate G2', state: 'corrected', blocking: false, summary: "Corrected: Addendum 01 supersedes the Rev 0 opening. Nothing to decide.", exceptionIds: [], findings: [] };
  if (g2ai) g2.findings.push({ prov: 'AGENT-FOUND', text: `A model read ${g2ai.claim?.text ?? 'the Rev 0 G2 opening'}`, note: `Superseded: this is the Rev 0 value. Verification: ${g2ai.verification?.result ?? 'not reported'}${g2ai.provenance === 'SIMULATED_TEST_DATA' ? ' · SIMULATED test data' : ''}.` });
  if (g2i) {
    const ev = (g2i.evidence || []).filter((e: any) => !e.superseded_by);
    g2.findings.push({ prov: 'ADDENDUM', text: g2i.text, note: `Corrected value: ${g2i.figure}`, src: ev.map(toSrc) });
    const old = (g2i.evidence || []).filter((e: any) => e.superseded_by);
    if (old.length) g2.findings.push({ prov: 'ENGINE-FLAGGED', text: 'Rev 0 sources kept for traceability only; they are not used as a value.', src: old.map(toSrc) });
  } else g2.findings.push({ prov: 'ENGINE-FLAGGED', text: 'The registered scope draft is not available, so the G2 correction cannot be shown here.' });

  // ---- G3: missing width, blocking, waiting for Addendum 02
  const g3ex = ex.filter(e => isG3(String(e.exception_id)) && e.code === 'MISSING_VALUE' && exOpen(e));
  const applied = addenda.find(a => a.status === 'APPLIED'); const proposed = addenda.find(a => a.status === 'PROPOSED');
  const g3human = humanFor('GATE_G3').concat(humanFor('gates/2'));
  const g3open = g3ex.length > 0;
  const g3tag = g3open ? (proposed ? 'ADDENDUM_PROPOSED' : 'ADDENDUM_PENDING') : applied ? 'ADDENDUM_ACCEPTED' : g3human.length ? 'HUMAN_ASSUMPTION' : undefined;
  const g3i = item('gate-g3'); const g3ai = finding('SIM-g3-12ft-unverified'); const rfi = (project?.rfi_drafts || []).find((r: any) => r.gate_id === 'G3');
  const g3: Gate = { id: 'g3', title: 'Gate G3', state: g3open ? 'open' : 'resolved', blocking: g3open, tag: g3tag, exceptionIds: g3ex.map(e => e.exception_id),
    summary: g3open ? 'Missing gate width. Blocking until a document or a named person supplies it.' : applied ? 'Supplied by the accepted addendum.' : 'Entered by a named person as an assumption.', findings: [] };
  if (g3open) g3.findings.push({ prov: 'ENGINE-FLAGGED', text: 'G3 clear opening width is not supported by the documents (and neither are its post size, footing diameter and depth).', note: `${g3ex.length} blocking value${g3ex.length === 1 ? '' : 's'} missing.`, src: g3i ? (g3i.evidence || []).map(toSrc) : (g3ex[0]?.evidence || []).map(toSrc) });
  if (g3ai) g3.findings.push({ prov: 'AGENT-FOUND', text: `A model stated ${g3ai.claim?.text ?? 'a G3 width'}`, note: `Caught: ${g3ai.verification?.result ?? 'UNVERIFIED'} — no supporting text on the cited page. It cannot enter the scope${g3ai.provenance === 'SIMULATED_TEST_DATA' ? ' (SIMULATED test data)' : ''}.` });
  if (rfi) g3.findings.push({ prov: 'ENGINE-CALCULATED', text: `RFI draft ${rfi.draft_id}: ${rfi.subject}`, note: 'A draft question only. Nothing has been sent.', src: (rfi.citations || []).map(toSrc) });
  if (applied) g3.findings.push({ prov: 'ADDENDUM', text: `Accepted from ${applied.filename} by ${applied.accepted_by ?? 'a named person'} (self-declared).`, note: `Scope version produced ${applied.scope_version_produced ?? applied.applied_scope_version ?? 'not reported'}.` });
  for (const a of g3human.slice(-2)) g3.findings.push({ prov: 'HUMAN', text: `${a.actor ?? 'A named person'} entered a value: ${a.note ?? ''}`, note: 'An assumption, not a document fact. The RFI stays pending.' });

  // ---- Bid selection
  const bidEx = ex.filter(e => e.code === 'BID_SELECTION_REQUIRED' && exOpen(e));
  const bidHuman = humanFor('BID_SELECTION');
  const bid: Gate = { id: 'bid', title: 'Which bid is priced', state: bidEx.length ? 'open' : 'resolved', blocking: bidEx.length > 0, exceptionIds: bidEx.map(e => e.exception_id),
    summary: bidEx.length ? 'Choose Base Bid or Alternate A-1. They are priced and exported separately; Alternate A-1 is in lieu of the Base Bid, never added to it.' : 'Chosen. Base Bid and Alternate A-1 stay separate.', findings: [] };
  if (bidEx.length) bid.findings.push({ prov: 'ENGINE-FLAGGED', text: bidEx[0].question, src: (bidEx[0].evidence || []) });
  for (const a of bidHuman.slice(-1)) bid.findings.push({ prov: 'HUMAN', text: `${a.actor ?? 'A named person'} chose: ${a.option_id ?? ''}`, note: a.note });

  // ---- Inferred quantities and stations
  const inf = ex.filter(e => e.code === 'INFERRED_FACT_UNAPPROVED' && exOpen(e));
  const spatial = (ai?.findings || []).filter((f: any) => String(f.finding_id).startsWith('AMD-spatial003') && f.provenance === 'REAL_AMD_OUTPUT');
  const vec = spatial.filter((f: any) => /CONFIRMED/.test(String(f.classification)) && !/NOT_/.test(String(f.classification))).length;
  const inferred: Gate = { id: 'inferred', title: 'Inferred lengths and gate stations', state: inf.length ? 'open' : 'resolved', blocking: inf.length > 0, exceptionIds: inf.map(e => e.exception_id),
    summary: inf.length ? `${inf.length} value${inf.length === 1 ? ' is' : 's are'} derived from written dimensions, not stated by a document. Each needs a named person to approve it.` : 'All inferred values are approved by a named person.', findings: [] };
  if (inf.length) inferred.findings.push({ prov: 'ENGINE-CALCULATED', text: `${inf.length} derived value${inf.length === 1 ? '' : 's'}: run lengths, gate stations and one continuity rule.`, note: inf.slice(0, 3).map(e => e.question).join(' · ') + (inf.length > 3 ? ' …' : '') });
  if (spatial.length) inferred.findings.push({ prov: 'AGENT-FOUND', text: `${spatial.length} stored model observations of the C101 gate and fence tags; ${vec} confirmed by the drawing's own vector geometry.`, note: 'Candidates only. They never approve a value; a named person does.' });

  // ---- Everything the engine flagged that does not block
  const adv = ex.filter(e => (e.severity === 'advisory' || (!e.blocking && e.severity !== 'blocking')) && exOpen(e));
  const other: Gate = { id: 'other', title: 'Advisories', state: 'info', blocking: false, exceptionIds: adv.map(e => e.exception_id), summary: adv.length ? `${adv.length} item${adv.length === 1 ? '' : 's'} for awareness. None blocks pricing on its own.` : 'None.', findings: [] };
  for (const e of adv.slice(0, 6)) other.findings.push({ prov: 'ENGINE-FLAGGED', text: e.question, src: e.evidence || [] });

  return [g2, g3, bid, inferred, other];
}

/** The one gate to work on now: the first blocking gate that is still open. */
export const currentGate = (gates: Gate[]): Gate | null => gates.find(g => g.state === 'open' && g.blocking) ?? null;

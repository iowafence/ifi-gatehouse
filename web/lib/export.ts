// Bid export (CSV only): a read-only rendering of what the ENGINE priced, held and authorized. Nothing here calculates money; every figure is copied from the
// engine's project summary. When the engine has priced nothing (for example while Gate G3 is unresolved) the export is a holds report with NO money rows.
// The authorization state, readiness class, holds and G3 status are part of the document and cannot be omitted.

type Any = any; // eslint-disable-line @typescript-eslint/no-explicit-any

export type Cell = string | number;
export type Block = { title: string; head?: string[]; rows: Cell[][]; note?: string };
export type BidExport = { filename: string; stamp: string; stampKind: 'released' | 'qualified' | 'draft' | 'unpriced'; title: string; meta: [string, string][]; blocks: Block[] };

const money = (n: unknown) => (typeof n === 'number' && Number.isFinite(n) ? n.toFixed(2) : '');
const num = (n: unknown) => (typeof n === 'number' && Number.isFinite(n) ? String(Math.round(n * 1e4) / 1e4) : n == null ? '' : String(n));

export class ExportRefused extends Error {
  code: string;
  constructor(code: string, msg: string) { super(msg); this.code = code; }
}

/** The engine's acceptance record for every G3 fact an accepted addendum supplied. A field the engine reports as null prints NOT RECORDED; nothing is defaulted or inferred.
 *  An addendum citation has a page, the quoted words and a sheet label; the section is "not stated". */
function g3AcceptanceBlock(review: Any | null): Block | null {
  const facts: Any[] = (review?.g3?.facts || []).filter((f: Any) => f.status === 'document_confirmed' || f.status === 'document-confirmed');
  if (!facts.length) return null;
  const v = (x: unknown) => x === null || x === undefined || x === '' ? 'NOT RECORDED' : String(x);
  return { title: 'Gate G3 — acceptance record (accepted addendum facts)', head: ['Requirement', 'Accepted by (self-declared)', 'Accepted at (UTC)', 'Acceptor note', 'Document label', 'Filename', 'Document SHA-256', 'Page', 'Quoted words', 'Sheet label', 'Scope version produced', 'Intake id', 'Addendum item'],
    rows: facts.map((f: Any) => { const a = f.acceptance || {}; return [f.label, v(a.accepted_by ?? f.by), v(a.accepted_utc), v(a.accepted_note), a.addendum_label ? `${a.addendum_label} [HUMAN]` : `${v(a.filename)} [FILENAME — no label typed]`, v(a.filename), v(a.sha256 ?? f.source?.sha256), v(a.page ?? f.source?.page), v(a.quoted), v(a.sheet_label), v(a.scope_version_produced), v(a.intake_id), a.addendum_item ? `${a.addendum_item} [HUMAN]` : 'not stated; cited by page and quote']; }),
    note: 'These fields come from the engine\'s acceptance record. The person named is self-declared, not authenticated. The document label is what the accepting person typed (tagged HUMAN), else the file name (tagged FILENAME); it is never inferred from the file name. The citation is the page, the quoted words and the sheet label; the addendum item is what the accepting person typed (tagged HUMAN, not verified), else it is not stated.' };
}

/** The G3 facts as the takeoff review reports them. A typed value is always an assumption with its named entrant and source note; only a value from an ACCEPTED
 *  addendum is document-confirmed, and then it cites the document and page and names the acceptor. Typing a value never relabels it. */
function g3Block(review: Any | null): Block {
  const g3 = review?.g3;
  if (!g3?.facts) return { title: 'Gate G3 — RFI PENDING', head: ['Item', 'Detail'], rows: [['Status', 'UNKNOWN — the takeoff review was unavailable when this was exported. Treat G3 as unresolved.']] };
  const rfi = g3.rfi || {};
  const rfiOpen = rfi.status === 'open' || rfi.status == null;
  const rows: Cell[][] = (g3.facts as Any[]).map(f => [
    f.label, f.path,
    f.status === 'unresolved' ? 'UNRESOLVED — RFI PENDING' : f.status === 'document-confirmed' || f.status === 'document_confirmed' ? 'DOCUMENT-CONFIRMED (accepted addendum)' : 'ASSUMPTION — RFI PENDING (typed by a person; not a document fact)',
    f.value === null || f.value === undefined ? 'no value' : `${f.value} ${f.unit || ''}`.trim(),
    (f.status === 'document_confirmed' ? 'accepted by ' : 'entered by ') + (f.by || ''),
    (f.note || '') + (f.status === 'document_confirmed' && f.source?.sha256 ? ` | document SHA-256 ${f.source.sha256}` : '')]);
  return { title: `Gate G3 — ${rfiOpen ? 'RFI PENDING' : 'RESOLVED BY ACCEPTED ADDENDUM'}`,
    head: ['Requirement', 'Field', 'Status', 'Value', 'Named person (self-declared)', 'Source / cited text'], rows,
    note: `${rfi.id || 'RFI-G3'}: ${rfiOpen ? 'PENDING (open, ' + (rfi.sent ? 'sent' : 'not sent') + '). Nothing is priced as complete while a G3 value is unresolved or only assumed.' : 'every G3 value comes from an accepted addendum, cited above.'}` };
}

/** Per-item prices come ONLY from the engine's bid_schedule (ALLOC-V1). They are labelled "allocated" (an allocation of the engine total, not a vendor quote),
 *  the reconciliation line is printed verbatim, and nothing here adds Base and Alternate together. If the engine refuses or has no schedule, that is stated. */
/** Schedule note for bid item 14 (Gate G3), derived from the ACCEPTED G3 clear-opening fact itself (its value, acceptor, time, page and quote), never from parsing item text.
 *  With no accepted width it says so and points at the G3 hold. Tagged ADDENDUM because the value comes from the accepted addendum. */
export function g3WidthNote(review: Any | null): string {
  const f = ((review?.g3?.facts || []) as Any[]).find(x => x?.path === '/gates/2/clear_width_ft');
  const a = f && (f.status === 'document_confirmed' || f.status === 'document-confirmed') ? f.acceptance : null;
  const v = typeof f?.value === 'number' && Number.isFinite(f.value) ? f.value : null;
  if (!a || v === null || !a.accepted_by || !a.accepted_utc) return 'Width not stated in the bid form; see G3 hold.';
  const ft = Math.floor(v), inch = Math.round((v - ft) * 12);
  const label = a.addendum_label ? String(a.addendum_label) : String(a.filename ?? 'the accepted addendum');
  const cite = `${a.filename ?? 'document NOT RECORDED'}${a.page !== null && a.page !== undefined ? ` page ${a.page}` : ''}${a.quoted ? `: “${a.quoted}”` : ''}`;
  return `Clear opening ${ft}'-${inch}" per ${label}, accepted by ${a.accepted_by} at ${a.accepted_utc}. [ADDENDUM] ${cite}`;
}

function scheduleBlocks(bs: Any, key: string, N: string, review: Any | null = null): Block[] {
  const title = `${N} — bid schedule items 10–16 (ALLOCATED prices, ALLOC-V1, not vendor quotes)`;
  if (!bs || bs.available !== true) {
    return [{ title, head: ['Item', 'Detail'], rows: [['Allocated per-item prices', `NOT AVAILABLE — ${bs?.refused ? 'the engine refused the allocation: ' + bs.refused : bs?.reason || 'the engine has not produced a bid schedule'}`]],
      note: 'No per-item price is shown without the engine\'s allocation. Nothing is estimated here.' }];
  }
  const sc = bs.scenarios?.[key];
  if (!sc || sc.available === false) return [{ title, head: ['Item', 'Detail'], rows: [['Allocated per-item prices', `NOT AVAILABLE — ${sc?.refused ? 'the engine refused the allocation: ' + sc.refused : 'no schedule for this scenario'}`]] }];
  const rows: Cell[][] = (sc.items || []).map((i: Any) => [i.item_no, i.description, i.unit, num(i.quantity),
    i.status === 'NOT_IN_SCENARIO' ? 'not in this scenario' : money(i.unit_price), i.status === 'NOT_IN_SCENARIO' ? '' : money(i.extended), i.status,
    [i.note, i.qualifier, Number(i.item_no) === 14 ? g3WidthNote(review) : null].filter(Boolean).join(' | ')]);
  return [{ title, head: ['Item', 'Description', 'Unit', 'Qty', 'Unit price (allocated)', 'Extension (allocated)', 'Status', 'Note'], rows,
    note: `Allocation method ${bs.method || 'ALLOC-V1'}; attribution table SHA-256 ${sc.attribution_table_sha256 || 'not reported'}; bid revision ${sc.bid_revision || 'not reported'}. Bid schedule items 1–9 and 17–21 are other trades: outside this fence scope and not priced here.` },
    { title: `${N} — bid total and reconciliation`, head: ['Total', 'Amount (USD)', 'Role'], rows: [
      ['Schedule total (sum of printed extensions, items 10–16)', money(sc.schedule_total), 'GOVERNS — this is the bid total'],
      ['Engine total (pricing engine price total)', money(sc.engine_total), 'Reconciliation only — does not govern'],
      ['Rounding delta (schedule total minus engine total)', money(sc.rounding_delta), 'Always printed; arises from rounding of printed unit prices'],
      ['Reconciliation (engine text, verbatim)', sc.reconciliation || 'reconciliation not reported by the engine', '']] }];
}

/** The gate assembly run-time override, as the engine reports it: rate per LF of clear opening x the scope's clear width x the gate quantity. The rate is an owner
 *  input; no gate total is typed anywhere. Printed so the arithmetic can be reviewed line by line. */
function gateAssemblyBlocks(assumptions: Any, key: string, N: string): Block[] {
  const lines: Any[] = Array.isArray(assumptions?.gate_assembly_lines?.[key]) ? assumptions.gate_assembly_lines[key] : [];
  if (!lines.length) return [];
  return [{ title: `${N} — gate assembly (run-time override: rate per LF of clear opening)`, head: ['Gate', 'Bid item', 'Clear width (ft)', 'Gate qty', 'Opening LF', 'Rate per LF', 'Extension'],
    rows: lines.map((l: Any) => [l.gate_id, l.bid_item, num(l.clear_width_ft), num(l.gate_quantity), num(l.opening_lf), money(l.rate_per_lf), money(l.extension)]),
    note: 'Opening LF = clear width x gate quantity; extension = rate per LF x opening LF. The rate is an owner input; the pinned workbook is unchanged. Gate posts, footings and install labor are priced on their own lines.' }];
}

/** Per-role classification and rates exactly as the named person recorded them, with the decision's floor and the engine's own check. */
function wageBlocks(wage: Any): Block[] {
  const rcs: Any[] = Array.isArray(wage?.role_classifications) ? wage.role_classifications : [];
  if (!rcs.length) return [{ title: 'Wage classifications (as recorded)', head: ['Item', 'Detail'], rows: [['Roles', 'NOT RECORDED — a named person must record each role\'s classification, base and fringe.']] }];
  const b = wage?.employer_burden;
  return [{ title: 'Wage classifications by role (as recorded by the named person; FICTIONAL DEMO WAGE DECISION while the decision is FDB-)',
    head: ['Role', 'Classification', 'Status', 'Recorded base', 'Recorded fringe', 'Decision base', 'Decision fringe', 'Versus decision', 'Cleared', 'Priced loaded $/h', 'Problems'],
    rows: rcs.map(r => [r.role, r.classification || 'NOT ASSIGNED', r.classification_status || '', money(r.base_rate), money(r.fringe_rate), money(r.decision_base_rate), money(r.decision_fringe_rate),
      r.above_decision ? 'ABOVE DECISION (recorded rate prices)' : r.cleared ? 'at decision' : '', r.cleared ? 'yes' : 'NO', money(r.priced?.loaded), (r.problems || []).map((p: Any) => p.code || p).join('; ')]),
    note: `The wage decision is a floor: base and fringe each at or above the schedule. ${b && typeof b.pct === 'number' ? `Employer burden ${(b.pct * 100).toFixed(2)}% of wages (${b.source_ref || 'source not reported'}).` : 'Employer burden not recorded.'}` }];
}

/** The note recorded with the CURRENT wage determination (after the last invalidation). It carries the named person's review text and, when the form was
 *  loaded from the recorded preset, the preset provenance and any "raised to wage decision" lines. Printed exactly as recorded. */
function wageNote(project: Any): string {
  const audit: Any[] = Array.isArray(project?.audit) ? project.audit : [];
  let note = '';
  for (const a of audit) {
    if (a?.event === 'wage_determination_recorded') note = `${a.actor ? a.actor + ' (self-declared): ' : ''}${a.note || ''}`;
    if (a?.event === 'wage_determination_invalidated') note = '';
  }
  return note || '(no wage determination is currently recorded)';
}


const accepted = (review: Any | null): Any[] => (review?.g3?.facts || []).filter((f: Any) => (f.status === 'document_confirmed' || f.status === 'document-confirmed') && f.acceptance);

/** Source revision, controlling addenda and export revision (checklist 1). Addendum 02 is named from the engine's acceptance record, never from the file name alone. */
function identityRows(project: Any, review: Any | null): [string, string][] {
  const acc = accepted(review);
  const seen = new Set<string>(); const ctrl: string[] = [];
  for (const f of acc) { const a = f.acceptance; const k = a.sha256 || a.intake_id; if (!k || seen.has(k)) continue; seen.add(k);
    ctrl.push(`${a.addendum_label ? a.addendum_label + ' [HUMAN label]' : '(no label typed)'}; file ${a.filename || 'NOT RECORDED'}; SHA-256 ${a.sha256 || 'NOT RECORDED'}; accepted by ${a.accepted_by || 'NOT RECORDED'} (self-declared) at ${a.accepted_utc || 'NOT RECORDED'}`); }
  return [
    ['Source revision', 'DP-001 Drawings (dp001_ansi_b_v2_drawings) revision 0; Project Manual (dp001_project_manual_ansi_b_pkg) revision 0; Addendum 01 (dp001_addendum_01_ansi_b_pkg) revision 1'],
    ['Controlling addenda', `Addendum 01 controls Gate G2 (item 1.5; Detail 3/F501). ${ctrl.length ? 'Addendum accepted for Gate G3: ' + ctrl.join(' | ') : 'No addendum has been accepted for Gate G3.'}`],
    ['Export revision', `Scope version ${project.scope_version ?? 'not reported'}; proposal digest ${project.proposal_digest || '(none issued)'}`]];
}

/** Checklist 3: earlier totals are void; the human entry is identified; unresolved clarifications stay visible. */
function g3VoidBlock(project: Any, review: Any | null, priced: boolean): Block {
  const acc = accepted(review); const open: Any[] = (review?.g3?.facts || []).filter((f: Any) => f.status === 'unresolved' || f.status === 'human_assumption');
  const entry = acc.length ? acc.map((f: Any) => `${f.label}: ${f.acceptance.accepted_by || 'NOT RECORDED'} (self-declared) at ${f.acceptance.accepted_utc || 'NOT RECORDED'}, scope version ${f.acceptance.scope_version_produced ?? 'NOT RECORDED'}`).join(' | ') : 'No G3 fact has been accepted from an addendum.';
  return { title: 'G3 entry and earlier totals', head: ['Item', 'Statement'], rows: [
    ['Earlier totals', `VOID. Any total produced before the G3 entry below, or at an earlier scope version than ${project.scope_version ?? 'this one'}, is void and must not be used.`],
    ['Human G3 entry', entry],
    ['Money in this file', priced ? 'Shown because a named person entered every G3 fact. The named person is self-declared, not authenticated.' : 'WITHHELD until a named person enters G3.'],
    ['Unresolved design clarifications', open.length ? open.map((f: Any) => `${f.label} (${f.status === 'unresolved' ? 'unresolved' : 'assumption / RFI pending'})`).join('; ') : 'None open at G3. Other holds are listed under Holds and outstanding items.'],
    ['Gate G2', 'Controlled by Addendum 01 item 1.5 and Detail 3/F501. G2 and G3 are not conflated; no G3 value is inherited by similarity.']] };
}

/** Checklist 11 and 12: what the estimate includes, and what still has to happen, with the effect on release. Static items are the pinned scope; none is a price. */
function inclusionsBlock(): Block {
  return { title: 'Inclusions', head: ['#', 'Included in this estimate'], rows: [
    [1, 'Bid schedule items 10–16 only: Type A and Type B chain link fence, Gates G1, G2 and G3, 9-ft windscreen, fence guard (material only; install labor is in the top-rail task).'],
    [2, 'Material, labor, equipment, services (core drilling) and mobilization lines as itemized above, with overhead, contingency and profit shown separately.'],
    [3, 'Gate assemblies at the owner run-time rate per LF of clear opening; gate posts, footings and install labor on their own lines.'],
    [4, 'Project insurance per SC-11.1 within overhead; material sales tax at the zero-percent owner exemption (SC-3.6.1).']],
    note: 'Bid schedule items 1–9 and 17–21 are other trades and are outside this scope.' };
}
/** One state object for every status sentence below; the tables and the prose are generated from the same values so they cannot disagree. */
export type Status = { quals: string[]; assumptions: string[]; openAssumptions: string[]; rfi: { id: string; resolved: boolean; label: string }; wageText: string; rulesetText: string; testIdentity: (n: string) => string };
const isTest = (n: unknown) => /\(test\)/i.test(String(n ?? ''));
export function deriveStatus(project: Any, review: Any | null, view: Any | null): Status {
  const all: string[] = (view?.qualifications || []).map(String);
  const wd = project.pricing?.wage?.decision; const rs = project.pricing?.ruleset; const rcs: Any[] = project.pricing?.wage?.role_classifications || [];
  // The engine's own wage and ruleset status sentences are restated once below from the recorded state, not printed a second time.
  const quals = all.filter(q => !/human-verified wage decision/i.test(q) && !/^Quantity ruleset .* approved by/i.test(q));
  const assumptions = quals.filter(q => /assumption/i.test(q));
  const openAssumptions = assumptions.filter(q => /^Qualified assumption/i.test(q));
  const f = review?.g3?.rfi; const resolved = !!f && f.status !== 'open' && f.status != null;
  const who = (n: unknown) => isTest(n) ? `${n} — TEST IDENTITY` : String(n ?? 'nobody');
  const cleared = rcs.length > 0 && rcs.every(r => r.cleared);
  const wageText = !wd ? 'NOT RECORDED — no wage decision is on file.'
    : `Recorded by ${who(wd.recorded_by)} (self-declared). Engine check of the recorded rates against the decision floor: ${rcs.length ? (cleared ? `all ${rcs.length} roles at or above the decision` : 'NOT every role clears') : 'no roles recorded'}. ${/^FDB-/.test(String(wd.decision_id)) ? `Decision ${wd.decision_id} is fictional by its own text (FICTIONAL DEMO WAGE DECISION). No real wage record is on file; the real record and the human-approved classifications are due in the final run.` : `Decision ${wd.decision_id}.`}`;
  const rulesetText = !rs ? 'NOT RECORDED.' : `${rs.ruleset_id} v${rs.version}: approval entered by ${who(rs.approved_by)} (self-declared); contractor approval ${rs.contractor_approved ? 'on file' : 'NOT on file'}.`;
  return { quals, assumptions, openAssumptions, rfi: { id: f?.id || 'RFI-G3', resolved, label: f ? (resolved ? 'RESOLVED by the accepted addendum (closed)' : `OPEN (${f.sent ? 'sent' : 'not sent'})`) : 'UNKNOWN — review unavailable' }, wageText, rulesetText, testIdentity: who };
}
function outstandingBlock(project: Any, st: Status, released: boolean, bidReady: boolean): Block {
  const cp = project.pricing?.crew_plan; const rs = project.pricing?.ruleset;
  const rows: Cell[][] = [];
  rows.push(['Real identity', 'OUTSTANDING — every name here is self-declared; no identity has been verified.', 'Blocks bid-ready release']);
  rows.push(['Quantity ruleset approval', st.rulesetText, rs?.contractor_approved ? 'None' : 'Blocks bid-ready release until the contractor approves it']);
  rows.push(['Wage record', st.wageText, 'Blocks bid-ready release; base and fringe must meet the real decision']);
  rows.push(['Crew approval', cp ? `Recorded by ${st.testIdentity(cp.approved_by)} (self-declared); confirm in the final run.` : 'OUTSTANDING — no crew approved.', 'Blocks release']);
  rows.push(['Release approval', released ? `Recorded by ${st.testIdentity(project.approved_by)} (self-declared).` : 'OUTSTANDING — not released.', bidReady ? 'None' : 'This file is not an authorized bid']);
  rows.push(['Footing scope readiness', bidReady ? 'Bid ready.' : 'NOT BID READY — footing counts or sizes rest on provisional geometry or human assumptions.', bidReady ? 'None' : 'Blocks bid-ready release']);
  rows.push([`${st.rfi.id}`, st.rfi.label, st.rfi.resolved ? 'None; closed' : 'Keeps G3 unresolved']);
  st.openAssumptions.forEach((q, i) => rows.push([`Open item ${i + 1}`, q.replace(/^Qualified assumption \(([^)]*)\): ?/i, 'Assumed, not stated by a document ($1): '), 'Stays an assumption until a document states it; keeps NOT BID READY']));
  return { title: 'Holds and outstanding items (effect on completeness and release)', head: ['Item', 'State', 'Effect'], rows };
}
/** Checklist 12: the run-time overrides in force for the released estimate, each with its releaser, UTC time, scope version and estimate revision, from the engine's overrides_acknowledged block. */
function overridesBlock(project: Any, st: Status): Block | null {
  const o = project.overrides_acknowledged; if (!o || typeof o !== 'object') return null;
  const list: Any[] = Array.isArray(o.overrides) ? o.overrides : [];
  const nr = (x: unknown) => x === null || x === undefined || x === '' ? 'NOT RECORDED' : String(x);
  const bids = o.bid_revisions && typeof o.bid_revisions === 'object' ? Object.entries(o.bid_revisions).map(([k, v]) => `${k} ${nr(v)}`).join('; ') : 'NOT RECORDED';
  return { title: 'Overrides acknowledged at release', head: ['Override', 'Statement', 'Decision by (owner)', 'Acknowledged by (self-declared)', 'Acknowledged at (UTC)', 'Scope version', 'Proposal digest', 'Estimate digest', 'Bid revisions'],
    rows: list.map(x => [x.name || x.id, nr(x.statement), nr(x.decision?.by) + (x.decision?.decided ? ` (${x.decision.decided})` : ''), st.testIdentity(x.acknowledged_by ?? o.released_by), nr(x.acknowledged_utc ?? o.released_utc), nr(x.scope_version ?? o.scope_version), nr(x.proposal_digest ?? o.proposal_digest), nr(o.estimate_digest), bids]),
    note: `Releaser ${st.testIdentity(o.released_by)} (self-declared) at ${nr(o.released_utc)}, scope version ${nr(o.scope_version)}, proposal digest ${nr(o.proposal_digest)}. ${list.length} override${list.length === 1 ? '' : 's'} in force.` };
}
function inferenceBlock(): Block {
  return { title: 'Inference statement', head: ['Item', 'Statement'], rows: [['Inference activity', 'No inference claim is made by this export. Any simulated or adapter-reported activity is not verified live activity. Telemetry for inference activity is not available to this export, so it is UNKNOWN, not zero.']] };
}

export function buildExport(project: Any, review: Any | null): BidExport {
  if (!project || typeof project !== 'object') throw new ExportRefused('NO_PROJECT', 'There is no project to export.');
  const est = project.estimate;
  const view = project.pricing?.estimate_view;
  const hasEstimate = !!(est?.scenarios && view);
  // Monetary output is withheld until every G3 fact was typed by a named person. If the review is unavailable, G3 cannot be checked, so money is withheld too.
  const g3Entered = Array.isArray(review?.g3?.facts) && review.g3.facts.length > 0 && review.g3.facts.every((f: Any) => f.status !== 'unresolved' && typeof f.by === 'string' && f.by.trim() !== '');
  const priced = hasEstimate && g3Entered;
  const released = project.status === 'released';
  const ref: string | null = priced ? (est.headline_scope_ref || view.scope_ref) : null;
  const sc = priced && ref ? est.scenarios[ref] : null;
  if (priced && !sc) throw new ExportRefused('NO_SCENARIO', 'The selected scope has no priced scenario.');
  const sel = review?.readiness?.selected;
  const bidReady = priced && released && sel?.bid_ready === true;
  const stampKind: BidExport['stampKind'] = !priced ? 'unpriced' : !released ? 'draft' : bidReady ? 'released' : 'qualified';
  const stamp = !priced ? 'NOT PRICED — HOLDS OPEN — NOT A BID — DO NOT SUBMIT'
    : !released ? 'DRAFT — NOT AUTHORIZED — NOT RELEASED — DO NOT SUBMIT'
    : bidReady ? 'RELEASED — AUTHORIZED PROPOSAL'
    : 'QUALIFIED DEMONSTRATION RELEASE — NOT A BID — NOT BID READY';
  const digest: string = project.proposal_digest || '';
  const rs = project.pricing?.ruleset;
  const rb = project.pricing?.ratebook_ref;
  const wage = project.pricing?.wage;
  const wd = wage?.decision;
  const blocking: Any[] = (project.exceptions || []).filter((e: Any) => e.severity === 'blocking');

  const scopeName = ref === 'ALT-A1' ? 'Alternate A-1 (bid IN LIEU OF the Base Bid; never added to it)' : ref === 'BASE' ? 'Base Bid' : ref ? String(ref) : 'not selected / not priced';
  const meta: [string, string][] = [
    ['Status', stamp],
    ['Project', 'DP-001 (synthetic package, fictional owner and site)'],
    ['Scope', scopeName],
    ['Currency', 'USD'],
    ...identityRows(project, review),
    ['Exported at (UTC)', new Date().toISOString()],
    ['Engine project id', String(project.project_id || '')],
    ['Scope version', String(project.scope_version ?? '')],
    ['Proposal digest', digest || '(none issued)'],
    ['Released by', released ? String(project.approved_by || '') : '(not released)'],
    ['Released at (UTC)', released ? String(project.released_at || '') : '(not released)'],
    ['Rate book', rb ? `${rb.ratebook_id} v${rb.version} (${rb.classification || 'unclassified'}), effective ${rb.effective_date}` : ''],
    ['Rate book content SHA-256', String(est?.ratebook_ref?.content_sha256 || '(not available before pricing)')],
    ['Quantity ruleset', rs ? `${rs.ruleset_id} v${rs.version} — ${rs.contractor_approved ? 'contractor-approved' : 'NOT contractor-approved'}; recorded by ${rs.approved_by || 'nobody yet'}` : ''],
    ['Wage decision', wd ? `${wd.decision_id} modification ${wd.modification}${/^FDB-/.test(String(wd.decision_id)) ? ' — FICTIONAL DEMO WAGE DECISION' : ''}; recorded by ${wd.recorded_by || 'unknown'} (self-declared)` : 'NOT RECORDED — a named person must record it'],
    ['Wage decision note (as recorded)', wageNote(project)],
    ['Crew for the job', (() => { const cp = project.pricing?.crew_plan; if (!cp) return 'NOT RECORDED — a named person must choose one crew and confirm it is available';
      const nm = project.pricing?.crews?.crews?.find((c: { crew_id: string; name: string }) => c.crew_id === cp.preferred_crew)?.name;
      return `${cp.preferred_crew ? `${nm ? nm + ' ' : ''}(${cp.preferred_crew}) for the whole job` : 'task-by-task assignments (superseded format)'}; approved by ${cp.approved_by} (self-declared); plan v${cp.plan_version}; note as recorded: ${cp.note}`; })()],
    ['Identity', 'Names on this document are self-declared demo entries, not verified identities.'],
  ];
  if (released && sel && sel.bid_ready !== true) meta.push(['Readiness', String(review?.readiness?.headline || 'Footing scope is not bid ready.')]);

  const st = deriveStatus(project, review, view);
  const blocks: Block[] = [];
  blocks.push(g3Block(review));
  { const ab = g3AcceptanceBlock(review); if (ab) blocks.push(ab); }
  blocks.push(g3VoidBlock(project, review, priced));
  blocks.push(...wageBlocks(wage));
  if (priced) {
    const NAMES: Record<string, string> = { 'BASE': 'BASE BID', 'ALT-A1': 'ALTERNATE A-1 (IN LIEU OF BASE BID — replaces it)' };
    for (const key of ['BASE', 'ALT-A1']) {
      const x = est.scenarios[key]; if (!x) continue;
      const N = NAMES[key];
      const cp = x.labor?.certified_payroll_admin?.extended;
      blocks.push({ title: `${N} — price summary`, head: ['Component', 'Amount (USD)'], rows: [
        ['Materials', money(x.materials?.subtotal)], ['Services (core drilling)', money(x.services?.subtotal)], ['Labor', money(x.labor?.subtotal)],
        ...(typeof cp === 'number' ? [['Certified payroll administration', money(cp)]] : []),
        ['Equipment', money(x.equipment?.subtotal)], ['Mobilization and other', money(x.mobilization?.subtotal)],
        ['Sales tax', money(x.sales_tax?.amount)], ['Direct cost', money(x.direct_cost)],
        ['Overhead', money(x.overhead?.amount)], ['Contingency', money(x.contingency?.amount)], ['Profit', money(x.profit?.amount)],
        [`${key === 'BASE' ? 'Base Bid' : 'Alternate A-1'} total`, money(x.price_total)], ['Fence length (LF)', num(x.fence_lf)]],
        note: 'Computed by the deterministic pricing engine; this document performs no arithmetic. The total above is the ENGINE total (reconciliation); the governing bid total is the schedule total in the bid total block below.' + (key === 'ALT-A1' ? ' This replaces the Base Bid. It is never added to it.' : '') });
      blocks.push(...scheduleBlocks(project.pricing?.bid_schedule, key, N, review));
      blocks.push(...gateAssemblyBlocks(project.pricing?.assumptions, key, N));
      blocks.push({ title: `${N} — materials`, head: ['Item', 'Description', 'UoM', 'Qty', 'Order qty', 'Unit price', 'Extended', 'Status', 'Basis'],
        rows: (x.materials?.lines || []).map((l: Any) => [l.item_id, l.description, l.uom, num(l.quantity), num(l.order_quantity), money(l.unit_price), money(l.extended), l.status, l.calculation_method || '']) });
      if (x.services?.lines?.length)
        blocks.push({ title: `${N} — services`, head: ['Item', 'Description', 'UoM', 'Qty', 'Unit cost', 'Extended', 'Status', 'Basis'],
          rows: x.services.lines.map((l: Any) => [l.service_id, l.description, l.uom, num(l.quantity), money(l.unit_cost), money(l.extended), l.status, l.calculation_method || '']) });
      blocks.push({ title: `${N} — labor`, head: ['Task', 'Description', 'UoM', 'Qty', 'Crew', 'Crew-h', 'Worker-h', 'Crew-days', 'Extended'],
        rows: (x.labor?.lines || []).map((l: Any) => [l.task_id, l.task, l.uom, num(l.quantity), l.crew_id, num(l.crew_hours), num(l.worker_hours), num(l.duration_days), money(l.extended)]) });
      if (x.equipment?.lines?.length)
        blocks.push({ title: `${N} — equipment`, head: ['Item', 'Description', 'Basis', 'Rate', 'Units', 'Extended'], rows: x.equipment.lines.map((l: Any) => [l.equip_id, l.equipment, l.basis, money(l.rate), num(l.units), money(l.extended)]) });
      if (x.mobilization?.lines?.length)
        blocks.push({ title: `${N} — mobilization and other`, head: ['Item', 'Description', 'Basis', 'Unit cost', 'Qty', 'Extended'], rows: x.mobilization.lines.map((l: Any) => [l.line_id, l.item, l.basis, money(l.unit_cost), num(l.quantity), money(l.extended)]) });
    }
    blocks.push({ title: 'No combined total', head: ['Note'], rows: [['Base Bid and Alternate A-1 are separate scenarios. Alternate A-1 is bid in lieu of the Base Bid. No combined total exists in Gatehouse.']] });
    const tax = sc.sales_tax;
    if (tax && typeof tax === 'object') {
      const cites = ((sc.quantity_revision?.sales_tax_exemption?.evidence_refs || []) as Any[]).map(e => e.sheet_label).filter(Boolean);
      blocks.push({ title: 'Sales tax qualification', head: ['Item', 'Detail'], rows: [
        ['Qualification', tax.exemption_applies ? `Incorporated materials are exempt from sales tax (owner exemption), per DP-001 Project Manual, ${cites.length ? cites.join('; ') : '(section not reported by the engine)'}. Supplies outside that exemption are shown separately below.` : 'No sales-tax exemption is applied by the engine.'],
        ['Exempt incorporated-material base (USD)', money(tax.exempt_base)], ['Taxable base, supplies outside the exemption (USD)', money(tax.taxable_base)], ['Sales tax charged (USD)', money(tax.amount)]] });
    }
    blocks.push({ title: 'Allowances and contingency', head: ['Item', 'Statement'], rows: [
      ['Project allowances', 'No project allowances carried.'],
      ['Rate-book lines described as "allowance"', 'Equipment and Mobilization lines described as "allowance" in the rate book are reference-estimate direct costs, included once above. They are not an additional project allowance.'],
      ['Contingency', 'Shown separately in each price summary above.']] });
    const excl: string[] = Array.isArray(est.exclusions) ? est.exclusions.map(String) : [];
    blocks.push(inclusionsBlock());
    blocks.push({ title: 'Exclusions (as reported by the engine)', head: ['#', 'Text'], rows: excl.map((q, i) => [i + 1, q]),
      note: `${excl.length ? '' : 'None reported by the engine. '}The assumptions this estimate rests on are listed under Qualifications and assumptions (${st.assumptions.length} listed).` });
    blocks.push({ title: 'Qualifications and assumptions (carried from the engine)', head: ['#', 'Text'],
      rows: st.quals.map((q, i) => [i + 1, q]),
      note: st.quals.length ? 'Wage and quantity-ruleset status are stated once, under Holds and outstanding items.' : 'None reported.' });
    if ((view.advisories || []).length) blocks.push({ title: 'Advisories', head: ['#', 'Text'], rows: view.advisories.map((q: string, i: number) => [i + 1, q]) });
  } else {
    const why: string[] = Array.isArray(project.pricing?.pricing_blocked_by) ? project.pricing.pricing_blocked_by.map((x: Any) => typeof x === 'string' ? x : x?.code ? `${x.code}${x.message ? ': ' + x.message : ''}` : JSON.stringify(x)) : [];
    blocks.push({ title: 'Price', head: ['Item', 'Detail'], rows: [['Total', hasEstimate ? 'WITHHELD — Gate G3 has not been entered by a named person (or could not be checked)' : 'NOT AVAILABLE — the engine has not priced this scope'], ...why.map((w, i) => [`Pricing blocked by ${i + 1}`, w])],
      note: 'No quantity, unit price or total is shown because the engine has not produced one. Nothing is estimated or defaulted to zero here.' });
  }
  blocks.push({ title: 'Scope notes (owner decisions)', head: ['Item', 'Note'], rows: [
    ['Item 16 fence guard', "Install labor is covered by task L04 'Install top rail and brace rail'; item 16 carries material M42 only (included in top-rail task). Source: BID_CONTRACT.md section 8, owner decision 2026-10-16."],
    ['Alternate A-1', 'Bid in lieu of the Base Bid (C102 note 5). Base and Alternate are shown separately; there is no combined total.']] });
  if (!released || blocking.length)
    blocks.push({ title: released ? 'Open blocking items at release' : 'Open holds — these must clear before this can be released', head: ['Code', 'Field', 'Question'],
      rows: blocking.map((e: Any) => [e.code, Array.isArray(e.affects) ? e.affects.join('; ') : '', e.question]), note: blocking.length ? '' : 'No blocking scope exceptions; release authorization is still pending.' });
  if (project.hold) blocks.push({ title: 'Project hold', head: ['Hold'], rows: [[typeof project.hold === 'string' ? project.hold : JSON.stringify(project.hold)]] });

  { const ob = overridesBlock(project, st); if (ob) blocks.push(ob); }
  blocks.push(outstandingBlock(project, st, released, bidReady));
  blocks.push(inferenceBlock());

  const tag = ref === 'ALT-A1' ? 'ALT-A1' : ref === 'BASE' ? 'BASE' : 'UNPRICED';
  const state = stampKind === 'unpriced' ? 'NOT-PRICED' : stampKind === 'draft' ? 'DRAFT' : stampKind === 'released' ? 'RELEASED' : 'QUALIFIED-DEMO';
  return { filename: `gatehouse-dp001-${tag}-${state}-${digest.slice(0, 8) || 'nodigest'}`, stamp, stampKind, title: 'IFI Gatehouse — Bid Export', meta, blocks };
}

const csvCell = (c: Cell) => {
  let s = String(c ?? '');
  if (/^[=+\-@\t\r]/.test(s) && !/^-\d+(\.\d+)?$/.test(s)) s = "'" + s; // spreadsheet formula injection: a cell never begins with an operator
  return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
};

export function toCsv(x: BidExport): string {
  const out: string[] = [x.title, x.stamp, ''];
  for (const [k, v] of x.meta) out.push([k, v].map(csvCell).join(','));
  for (const b of x.blocks) {
    out.push('', csvCell(b.title.toUpperCase()));
    if (b.head) out.push(b.head.map(csvCell).join(','));
    for (const r of b.rows) out.push(r.map(csvCell).join(','));
    if (b.note) out.push(csvCell(b.note));
  }
  out.push('', csvCell(x.stamp));
  return '﻿' + out.join('\r\n') + '\r\n';
}

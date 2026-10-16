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
function scheduleBlocks(bs: Any, key: string, N: string): Block[] {
  const title = `${N} — bid schedule items 10–16 (ALLOCATED prices, ALLOC-V1, not vendor quotes)`;
  if (!bs || bs.available !== true) {
    return [{ title, head: ['Item', 'Detail'], rows: [['Allocated per-item prices', `NOT AVAILABLE — ${bs?.refused ? 'the engine refused the allocation: ' + bs.refused : bs?.reason || 'the engine has not produced a bid schedule'}`]],
      note: 'No per-item price is shown without the engine\'s allocation. Nothing is estimated here.' }];
  }
  const sc = bs.scenarios?.[key];
  if (!sc || sc.available === false) return [{ title, head: ['Item', 'Detail'], rows: [['Allocated per-item prices', `NOT AVAILABLE — ${sc?.refused ? 'the engine refused the allocation: ' + sc.refused : 'no schedule for this scenario'}`]] }];
  const rows: Cell[][] = (sc.items || []).map((i: Any) => [i.item_no, i.description, i.unit, num(i.quantity),
    i.status === 'NOT_IN_SCENARIO' ? 'not in this scenario' : money(i.unit_price), i.status === 'NOT_IN_SCENARIO' ? '' : money(i.extended), i.status,
    [i.note, i.qualifier].filter(Boolean).join(' | ')]);
  return [{ title, head: ['Item', 'Description', 'Unit', 'Qty', 'Unit price (allocated)', 'Extension (allocated)', 'Status', 'Note'], rows,
    note: `Allocation method ${bs.method || 'ALLOC-V1'}; attribution table SHA-256 ${sc.attribution_table_sha256 || 'not reported'}; bid revision ${sc.bid_revision || 'not reported'}. Bid schedule items 1–9 and 17–21 are other trades: outside this fence scope and not priced here.` },
    { title: `${N} — reconciliation`, head: ['Line'], rows: [[sc.reconciliation || 'reconciliation not reported by the engine']] }];
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
    ['Identity', 'Names on this document are self-declared demo entries, not verified identities.'],
  ];
  if (released && sel && sel.bid_ready !== true) meta.push(['Readiness', String(review?.readiness?.headline || 'Footing scope is not bid ready.')]);

  const blocks: Block[] = [];
  blocks.push(g3Block(review));
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
        note: 'Computed by the deterministic pricing engine; this document performs no arithmetic.' + (key === 'ALT-A1' ? ' This replaces the Base Bid. It is never added to it.' : '') });
      blocks.push(...scheduleBlocks(project.pricing?.bid_schedule, key, N));
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
    blocks.push({ title: 'Exclusions (as reported by the engine)', head: ['#', 'Text'], rows: excl.map((q, i) => [i + 1, q]),
      note: excl.length ? '' : 'None reported by the engine. Nothing has been added or assumed.' });
    blocks.push({ title: 'Qualifications and assumptions (carried from the engine)', head: ['#', 'Text'],
      rows: [...(view.qualifications || []).map((q: string, i: number) => [i + 1, q])],
      note: (view.qualifications || []).length ? '' : 'None reported.' });
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

  const tag = ref === 'ALT-A1' ? 'ALT-A1' : ref === 'BASE' ? 'BASE' : 'UNPRICED';
  const state = stampKind === 'unpriced' ? 'NOT-PRICED' : stampKind === 'draft' ? 'DRAFT' : stampKind === 'released' ? 'RELEASED' : 'QUALIFIED-DEMO';
  return { filename: `gatehouse-dp001-${tag}-${state}-${digest.slice(0, 8) || 'nodigest'}`, stamp, stampKind, title: 'IFI Gatehouse — Bid Export', meta, blocks };
}

const csvCell = (c: Cell) => {
  let s = String(c ?? '');
  if (/^[=+\-@\t\r]/.test(s)) s = "'" + s; // spreadsheet formula injection: a cell never begins with an operator
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

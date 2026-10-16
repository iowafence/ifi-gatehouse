// Bid export: a read-only rendering of what the ENGINE already priced and authorized. Nothing here calculates money; every figure is copied from the
// engine's project summary. The authorization state (released / draft, readiness class, holds, qualifications) is part of the document and cannot be omitted.

type Any = any; // eslint-disable-line @typescript-eslint/no-explicit-any

export type Cell = string | number;
export type Block = { title: string; head?: string[]; rows: Cell[][]; note?: string };
export type BidExport = { filename: string; stamp: string; stampKind: 'released' | 'qualified' | 'draft'; title: string; meta: [string, string][]; blocks: Block[] };

const money = (n: unknown) => (typeof n === 'number' && Number.isFinite(n) ? n.toFixed(2) : '');
const num = (n: unknown) => (typeof n === 'number' && Number.isFinite(n) ? String(Math.round(n * 1e4) / 1e4) : n == null ? '' : String(n));

export class ExportRefused extends Error {
  code: string;
  constructor(code: string, msg: string) { super(msg); this.code = code; }
}

export function buildExport(project: Any, review: Any | null): BidExport {
  const est = project?.estimate;
  const view = project?.pricing?.estimate_view;
  if (!est?.scenarios || !view) throw new ExportRefused('NO_ESTIMATE', 'There is no engine-priced estimate to export yet. Clear Scope and Labor first.');
  const ref: string = est.headline_scope_ref || view.scope_ref;
  const sc = est.scenarios[ref];
  if (!sc) throw new ExportRefused('NO_SCENARIO', 'The selected scope has no priced scenario.');
  const released = project.status === 'released';
  const sel = review?.readiness?.selected;
  const bidReady = released && sel?.bid_ready === true;
  const stampKind: BidExport['stampKind'] = !released ? 'draft' : bidReady ? 'released' : 'qualified';
  const stamp = !released ? 'DRAFT — NOT AUTHORIZED — NOT RELEASED — DO NOT SUBMIT'
    : bidReady ? 'RELEASED — AUTHORIZED PROPOSAL'
    : 'QUALIFIED DEMONSTRATION RELEASE — NOT A BID — NOT BID READY';
  const digest: string = project.proposal_digest || '';
  const rs = project.pricing?.ruleset;
  const rb = project.pricing?.ratebook_ref;
  const blocking: Any[] = (project.exceptions || []).filter((e: Any) => e.severity === 'blocking');

  const meta: [string, string][] = [
    ['Status', stamp],
    ['Scope', ref === 'ALT-A1' ? 'Alternate A-1' : ref === 'BASE' ? 'Base Bid' : String(ref)],
    ['Project', String(project.project_id || '')],
    ['Scope version', String(project.scope_version ?? '')],
    ['Proposal digest', digest || '(none issued)'],
    ['Released by', released ? String(project.approved_by || '') : '(not released)'],
    ['Released at (UTC)', released ? String(project.released_at || '') : '(not released)'],
    ['Rate book', rb ? `${rb.ratebook_id} v${rb.version} (${rb.classification || 'unclassified'}), effective ${rb.effective_date}` : ''],
    ['Quantity ruleset', rs ? `${rs.ruleset_id} v${rs.version} — ${rs.contractor_approved ? 'contractor-approved' : 'NOT contractor-approved'}; recorded by ${rs.approved_by || 'nobody'}` : ''],
    ['Identity', 'Names on this document are self-declared demo entries, not verified identities.'],
  ];
  if (released && sel && sel.bid_ready !== true) meta.push(['Readiness', String(review?.readiness?.headline || 'Footing scope is not bid ready.')]);

  const blocks: Block[] = [];
  blocks.push({ title: 'Price summary', head: ['Component', 'Amount (USD)'],
    rows: [...(view.breakdown || []).map((b: Any) => [b.label, money(b.amount)]), ['Price per LF', money(view.price_per_lf)], ['Fence length (LF)', num(view.fence_lf)]],
    note: 'All amounts are computed by the deterministic pricing engine. This document performs no arithmetic.' });
  if (Array.isArray(view.alternates) && view.alternates.length)
    blocks.push({ title: 'Alternates (priced separately — never added to the headline total)', head: ['Alternate', 'Total (USD)'],
      rows: view.alternates.map((a: Any) => [a.scope_ref === 'ALT-A1' ? 'Alternate A-1' : a.scope_ref, money(a.price_total)]),
      note: 'Each alternate is a complete, separate scenario. To bid an alternate, select it in Gatehouse and take it through the gates; its authorization is separate.' });
  blocks.push({ title: 'Materials', head: ['Item', 'Description', 'UoM', 'Qty', 'Order qty', 'Unit price', 'Extended', 'Status', 'Basis'],
    rows: (sc.materials?.lines || []).map((l: Any) => [l.item_id, l.description, l.uom, num(l.quantity), num(l.order_quantity), money(l.unit_price), money(l.extended), l.status, l.calculation_method || '']) });
  if (sc.services?.lines?.length)
    blocks.push({ title: 'Services', head: ['Item', 'Description', 'UoM', 'Qty', 'Unit cost', 'Extended', 'Status', 'Basis'],
      rows: sc.services.lines.map((l: Any) => [l.service_id, l.description, l.uom, num(l.quantity), money(l.unit_cost), money(l.extended), l.status, l.calculation_method || '']) });
  blocks.push({ title: 'Labor', head: ['Task', 'Description', 'UoM', 'Qty', 'Crew', 'Crew-h', 'Worker-h', 'Crew-days', 'Extended'],
    rows: (sc.labor?.lines || []).map((l: Any) => [l.task_id, l.task, l.uom, num(l.quantity), l.crew_id, num(l.crew_hours), num(l.worker_hours), num(l.duration_days), money(l.extended)]) });
  if (sc.equipment?.lines?.length)
    blocks.push({ title: 'Equipment', head: ['Item', 'Description', 'Basis', 'Rate', 'Units', 'Extended'], rows: sc.equipment.lines.map((l: Any) => [l.equip_id, l.equipment, l.basis, money(l.rate), num(l.units), money(l.extended)]) });
  if (sc.mobilization?.lines?.length)
    blocks.push({ title: 'Mobilization and other', head: ['Item', 'Description', 'Basis', 'Unit cost', 'Qty', 'Extended'], rows: sc.mobilization.lines.map((l: Any) => [l.line_id, l.item, l.basis, money(l.unit_cost), num(l.quantity), money(l.extended)]) });
  const excl: string[] = Array.isArray(est.exclusions) ? est.exclusions.map(String) : [];
  blocks.push({ title: 'Exclusions (as reported by the engine)', head: ['#', 'Text'], rows: excl.map((q, i) => [i + 1, q]),
    note: excl.length ? '' : 'None reported by the engine. Nothing has been added or assumed.' });
  blocks.push({ title: 'Qualifications and assumptions (carried from the engine)', head: ['#', 'Text'],
    rows: [...(view.qualifications || []).map((q: string, i: number) => [i + 1, q])],
    note: (view.qualifications || []).length ? '' : 'None reported.' });
  if ((view.advisories || []).length) blocks.push({ title: 'Advisories', head: ['#', 'Text'], rows: view.advisories.map((q: string, i: number) => [i + 1, q]) });
  if (!released || blocking.length)
    blocks.push({ title: released ? 'Open blocking items at release' : 'Open holds — these must clear before this can be released', head: ['Code', 'Question'],
      rows: blocking.map((e: Any) => [e.code, e.question]), note: blocking.length ? '' : 'No blocking scope exceptions; release authorization is still pending.' });
  if (project.hold) blocks.push({ title: 'Project hold', head: ['Hold'], rows: [[typeof project.hold === 'string' ? project.hold : JSON.stringify(project.hold)]] });

  const scopeName = ref === 'ALT-A1' ? 'ALT-A1' : ref === 'BASE' ? 'BASE' : String(ref).replace(/[^A-Za-z0-9-]/g, '');
  const state = !released ? 'DRAFT' : bidReady ? 'RELEASED' : 'QUALIFIED-DEMO';
  return { filename: `gatehouse-dp001-${scopeName}-${state}-${digest.slice(0, 8) || 'nodigest'}`, stamp, stampKind, title: 'IFI Gatehouse — Bid Export', meta, blocks };
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

const esc = (c: Cell) => String(c ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch] as string));
const numeric = (h: string) => /^(Qty|Order qty|Unit price|Unit cost|Extended|Rate|Units|Crew-h|Worker-h|Crew-days|Amount|Total)/.test(h);

export function toHtml(x: BidExport): string {
  const color = x.stampKind === 'released' ? '#14532d' : x.stampKind === 'qualified' ? '#92400e' : '#991b1b';
  const tables = x.blocks.map(b => `<section><h2>${esc(b.title)}</h2>${b.rows.length ? `<table>${b.head ? `<thead><tr>${b.head.map(h => `<th${numeric(h) ? ' class="n"' : ''}>${esc(h)}</th>`).join('')}</tr></thead>` : ''}<tbody>${b.rows.map(r => `<tr>${r.map((c, i) => `<td${b.head && numeric(b.head[i] || '') ? ' class="n"' : ''}>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>` : ''}${b.note ? `<p class="note">${esc(b.note)}</p>` : ''}</section>`).join('');
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(x.filename)}</title><style>
:root{color-scheme:light}body{font:14px/1.45 system-ui,Segoe UI,Arial,sans-serif;margin:0;padding:16px;color:#111;background:#fff}
.stamp{border:3px solid ${color};color:${color};font-weight:800;padding:10px 12px;margin:0 0 14px;letter-spacing:.02em}
h1{font-size:20px;margin:0 0 8px}h2{font-size:15px;margin:20px 0 6px;border-bottom:1px solid #999;padding-bottom:3px}
dl{display:grid;grid-template-columns:max-content 1fr;gap:3px 12px;margin:0}dt{font-weight:600}dd{margin:0;word-break:break-word}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:12.5px}th,td{border:1px solid #bbb;padding:4px 6px;text-align:left;vertical-align:top}th{background:#eee}.n{text-align:right;font-variant-numeric:tabular-nums}
.note{font-size:12px;color:#444;margin:4px 0}.noprint{margin:0 0 12px}button{font:inherit;padding:8px 14px}
@media print{.noprint{display:none}body{padding:0}h2{break-after:avoid}tr{break-inside:avoid}}</style></head><body>
<div class="noprint"><button onclick="window.print()">Print / save as PDF</button></div>
<h1>${esc(x.title)}</h1><p class="stamp">${esc(x.stamp)}</p>
<dl>${x.meta.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>
${tables.replace(/<table>/g, '<div class="wrap"><table>').replace(/<\/table>/g, '</table></div>')}
<p class="stamp" style="margin-top:20px">${esc(x.stamp)}</p></body></html>`;
}

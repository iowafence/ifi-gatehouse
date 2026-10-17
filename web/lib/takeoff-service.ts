// Server-only Takeoff Review service. The footing quantities, concrete, drilling and partial cost come from the ENGINE's accepted per-run
// footing calculation (footing-scope.v1 -> footing-calc.v1 / footing-schedule.v1, project.pricing.footing[scenario]). The deterministic TypeScript
// reference in lib/takeoff.ts is kept ONLY as an independent cross-check (and for gross/net before the engine can produce a takeoff). This file
// never prices anything: every dollar shown comes from the engine, and bid readiness is the engine's own bid_ready / release_class value.
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { reconcile, SCENARIOS, type Ledger, type Scenario } from './takeoff';

/* eslint-disable @typescript-eslint/no-explicit-any */
type Raw = Record<string, any>;
export type Attestation = { by: string; note: string; at: string; scope_version: number; digest: string; idempotency_key: string; scenario: Scenario | null };
/** The engine's own release response, kept server-side so the readiness fields survive a page reload. Never taken from a client. */
export type ReleaseRecord = { bid_ready: unknown; release_class: unknown; artifact_kind: unknown; footing_release_class: unknown; proposal_digest: unknown; scope_version: unknown; released_at: unknown; audit_id: unknown };
type Store = { attestation: Attestation | null; ledger: Map<string, { hash: string; response: any; status: number }>; release: ReleaseRecord | null };
const g = globalThis as unknown as { __takeoffStore?: Map<string, Store> };
const STORE = (g.__takeoffStore ||= new Map<string, Store>());
export const storeFor = (sid: string, pid: string): Store => { const k = `${sid}:${pid}`; let s = STORE.get(k); if (!s) { s = { attestation: null, ledger: new Map(), release: null }; STORE.set(k, s); if (STORE.size > 2000) STORE.delete(STORE.keys().next().value as string); } return s; };

export const canonical = (o: unknown): string => JSON.stringify(o, (_k, v) => (v && typeof v === 'object' && !Array.isArray(v)) ? Object.fromEntries(Object.entries(v).sort(([a], [b]) => a < b ? -1 : 1)) : v);
export const sha = (s: string) => createHash('sha256').update(s).digest('hex');

const dir = () => process.env.DP001_DIR || '';
async function readJson(name: string) { try { return JSON.parse(await readFile(path.join(dir(), name), 'utf8')); } catch { return null; } }

const SC_KEY: Record<Scenario, string> = { base: 'BASE', alt: 'ALT-A1' };
const G3_FACTS = [
  { id: 'opening', exception: 'EX-MISSING_VALUE-/gates/2/clear_width_ft', path: '/gates/2/clear_width_ft', label: 'G3 clear opening', unit: 'ft' },
  { id: 'post_od', exception: 'EX-MISSING_VALUE-/footing_scope/classes/GATE_G3/post_od_in', path: '/footing_scope/classes/GATE_G3/post_od_in', label: 'G3 gate-post OD', unit: 'in' },
  { id: 'diameter', exception: 'EX-MISSING_VALUE-/footing_scope/classes/GATE_G3/diameter_in', path: '/footing_scope/classes/GATE_G3/diameter_in', label: 'G3 footing diameter', unit: 'in' },
  { id: 'depth', exception: 'EX-MISSING_VALUE-/footing_scope/classes/GATE_G3/depth_in', path: '/footing_scope/classes/GATE_G3/depth_in', label: 'G3 footing depth', unit: 'in' },
] as const;

/** A DP-001 project served with the accepted per-run footing scope. A legacy scope (no pricing.footing) is not a footing-scope project. */
export function isDp001(project: Raw | null): boolean {
  const f = project?.pricing?.footing;
  const any = f && (f.BASE || f['ALT-A1']);
  return !!(any && any.contract_version === 'footing-scope.v1' && (any.classes || []).some((c: Raw) => c.post_class === 'GATE_G3'));
}

export function deriveInputs(project: Raw) {
  const audit: Raw[] = Array.isArray(project.audit) ? project.audit : [];
  const bid = [...audit].reverse().find(a => String(a.exception_id || '').includes('BID_SELECTION'));
  const selected: Scenario | null = !bid ? null : bid.option_id === 'base' ? 'base' : 'alt';
  // The latest event per fact wins: a person typing a value (assumption) or an accepted addendum revising the scope (document-confirmed).
  const addenda: Raw[] = Array.isArray(project.addenda) ? project.addenda : [];
  const facts = G3_FACTS.map(f => {
    let last: Raw | null = null;
    for (const a of audit) {
      if (a.event === 'resolved' && String(a.exception_id || '') === f.exception && a.value !== null && a.value !== undefined) last = { kind: 'human', a };
      if (a.event === 'scope_revised' && Array.isArray(a.changes)) {
        const c = a.changes.find((x: Raw) => x && x.path === f.path);
        if (c) last = { kind: 'document', a, c };
      }
    }
    if (!last) return { ...f, value: null, by: null, note: null, audit_event: null, status: 'unresolved', source: null };
    if (last.kind === 'human') {
      const n = Number(last.a.value);
      return { ...f, value: Number.isFinite(n) ? n : null, by: last.a.actor ?? null, note: last.a.note ?? null, audit_event: last.a.event_id ?? null, status: 'human_assumption', source: null };
    }
    const rec = addenda.find((r: Raw) => r?.source?.sha256 && r.source.sha256 === last!.a.source?.sha256);
    const ba = (rec?.before_after || []).find((x: Raw) => x.path === f.path);
    const n = Number(last.c.after);
    const inh = ba?.inherited_from ? ` — inherited from ${ba.inherited_from.gate || 'Gate G1'} (${ba.inherited_from.inherited_from || 'source field'}${ba.inherited_from.source_value != null ? ', ' + ba.inherited_from.source_value : ''}; ${ba.inherited_from.source_status || 'confirmed'})` : '';
    const acceptance = { accepted_by: rec?.accepted_by ?? null, accepted_utc: rec?.accepted_utc ?? null, accepted_note: rec?.accepted_note ?? null, scope_version_produced: rec?.scope_version_produced ?? null,
      addendum_label: rec?.addendum_label?.value ?? null, intake_id: rec?.intake_id ?? null, sha256: rec?.sha256 ?? rec?.source?.sha256 ?? null,
      addendum_item: rec?.addendum_item_reference?.value ?? null, filename: rec?.filename ?? null, page: ba?.cited_page ?? null, quoted: ba?.cited_excerpt ?? null,
      inherited_from: ba?.inherited_from ? { gate: ba.inherited_from.gate ?? null, path: ba.inherited_from.inherited_from ?? null, value: ba.inherited_from.source_value ?? null, status: ba.inherited_from.source_status ?? null } : null, sheet_label: ba?.sheet_label ?? (rec?.filename && ba?.cited_page != null ? `${rec.filename} page ${ba.cited_page}` : null) };
    return { ...f, acceptance, value: Number.isFinite(n) ? n : null, by: rec?.accepted_by ?? null, audit_event: last.a.event_id ?? null, status: 'document_confirmed',
      note: (ba ? `${rec?.filename}, page ${ba.cited_page}: "${ba.cited_excerpt}"` : (rec?.filename ?? '')) + inh,
      source: { doc: rec?.filename ?? null, sha256: last.a.source?.sha256 ?? null, page: ba?.cited_page ?? null } };
  });
  return { selected, facts, g3: facts[0].value, scope_version: Number(project.scope_version ?? 0) };
}

const CLASS_MAP: Record<string, string> = { A_LINE: 'a_line', A_CORNER_TERMINAL: 'a_terminal', GATE_G1: 'g12_gate', GATE_G2: 'g12_gate', GATE_G3: 'g3_gate', B_LINE: 'b_line', B_TERMINAL: 'b_terminal' };
const near = (a: number | null, b: number | null, eps = 1e-5) => (a === null || b === null) ? a === b : Math.abs(a - b) <= eps;

/** Independent cross-check: the engine's per-class schedule versus the separately written deterministic reference (lib/takeoff.ts). */
function crossCheck(fp: Raw | null, L: Ledger | null, project: Raw, selected: boolean) {
  if (!fp || !L) return { checked: false, ok: true, rows: [] as Raw[] };
  const rows: Raw[] = [];
  const eng: Record<string, number | null> = {};
  const unknownIds = new Set<string>();
  for (const c of fp.classes as Raw[]) {
    const id = CLASS_MAP[c.post_class]; if (!id) continue;
    if (c.quantity === null || c.quantity === undefined) unknownIds.add(id); else eng[id] = (eng[id] ?? 0) + c.quantity;
  }
  for (const id of unknownIds) eng[id] = null;
  for (const c of L.classes) rows.push({ key: c.id, label: c.label, engine: eng[c.id] ?? null, reference: c.count, ok: (eng[c.id] ?? null) === c.count });
  const eh = fp.totals.core_drill_holes ?? null, rh = L.holes.total;
  rows.push({ key: 'holes', label: 'Total core-drilled holes', engine: eh, reference: rh, ok: eh === rh });
  const knownCy = (fp.records as Raw[]).filter(r => r.post_class !== 'GATE_G3' && typeof r.concrete_cy === 'number').reduce((a, r) => a + r.concrete_cy, 0);
  rows.push({ key: 'concrete_known', label: 'Known-class concrete, G3 excluded (CY)', engine: Number(knownCy.toFixed(6)), reference: L.concrete_cy.known_classes, ok: near(Number(knownCy.toFixed(6)), L.concrete_cy.known_classes) });
  const t = selected ? project.takeoff : null;
  if (t?.runs) {
    const A = t.runs['FR-A'], B = t.runs['FR-B'];
    rows.push({ key: 'net_a', label: 'Net Type A LF (engine takeoff)', engine: A?.net_lf ?? null, reference: L.net.type_a, ok: near(A?.net_lf ?? null, L.net.type_a) });
    rows.push({ key: 'net_b', label: 'Net Type B LF (engine takeoff)', engine: B?.net_lf ?? null, reference: L.net.type_b, ok: near(B?.net_lf ?? null, L.net.type_b) });
    rows.push({ key: 'gross', label: 'Gross fence LF (engine takeoff)', engine: t.totals?.fence_lf ?? null, reference: L.gross.total, ok: near(t.totals?.fence_lf ?? null, L.gross.total) });
  }
  return { checked: true, ok: rows.every(r => r.ok), rows };
}

const LABOR_MAP: Record<string, { kind: 'gross' | 'net' | 'holes' | 'posts' | 'gates' | 'windscreen' | 'none'; why: string }> = {
  L01: { kind: 'gross', why: 'layout / stakeout runs the gross perimeter (D12): openings included, by design' },
  L02: { kind: 'holes', why: 'one core-drilled hole per post, from the per-class footing schedule' },
  L03: { kind: 'posts', why: 'posts set = every post in the footing schedule (shared posts counted once)' },
  L04: { kind: 'gross', why: 'top rail: priced at gross LF because the approved assumption says the top rail is continuous across openings' },
  L05: { kind: 'none', why: 'brace assemblies: not independently reconciled here' },
  L06: { kind: 'net', why: 'fabric hung = net fence LF (gate openings already deducted by the engine)' },
  L07: { kind: 'net', why: 'bottom tension wire = net fence LF' },
  L08: { kind: 'gates', why: 'gates hung = gate EACH' },
  L09: { kind: 'windscreen', why: 'windscreen LF' },
  L10: { kind: 'gross', why: 'cleanup / spoils haul runs the gross layout length' },
};

function scenarioView(project: Raw, which: Scenario, ledger: Ledger | null, selected: boolean) {
  const fp: Raw | null = project.pricing?.footing?.[SC_KEY[which]] ?? null;
  if (!fp) return { label: SCENARIOS[which].label, ledger, footing: null, cross: crossCheck(null, null, project, selected) };
  const byClass: Record<string, Raw> = {};
  for (const b of (fp.partial_cost?.by_class || []) as Raw[]) byClass[`${b.run_id}|${b.post_class}`] = b;
  const rows = (fp.records as Raw[]).map(r => {
    const bc = byClass[`${r.run_id}|${r.post_class}`];
    return {
      run_id: r.run_id, post_class: r.post_class, fence_type: r.fence_type, role: r.role, owner: r.owner,
      quantity: r.quantity, known_minimum: r.quantity_known_minimum, diameter_in: r.diameter_in, depth_in: r.depth_in, post_od_in: r.post_od_in,
      concrete_cy: r.concrete_cy, concrete_each_cy: r.footing_volume_cy_each, holes: r.core_drill_holes,
      value_basis: r.value_basis, review: r.review, unknown_reason: r.unknown_reason, unresolved_inputs: r.unresolved_inputs, source_refs: r.source_refs,
      cost_basis: bc ? { post_item: bc.post_item, post_material: bc.post_material, concrete_before_rounding: bc.concrete_before_order_rounding, core_drilling: bc.core_drilling, drilling_basis: bc.drilling_basis } : null,
    };
  });
  const footing = {
    contract_version: fp.contract_version, calc_version: fp.calc_version, schedule_sha256: fp.schedule_sha256, calc_inputs_sha256: fp.calc_inputs_sha256,
    measurement_convention: fp.measurement_convention, posture: fp.posture, totals: fp.totals, rows,
    runs: (fp.runs || []).map((r: Raw) => ({ run_id: r.run_id, fence_type: r.fence_type, repeat: r.repeat, layout_kind: r.layout_kind, segments: r.segments })),
    reconciliation: fp.reconciliation ?? null, partial_cost: fp.partial_cost ?? null, priced: !!fp.priced,
  };
  return { label: SCENARIOS[which].label, ledger, footing, cross: crossCheck(fp, ledger, project, selected) };
}

export async function buildReview(project: Raw, sid: string, pid: string) {
  const inp = deriveInputs(project);
  const st = storeFor(sid, pid);
  const sel = inp.selected;
  let refErr: string | null = null;
  let ledgers: Record<Scenario, Ledger | null> = { base: null, alt: null };
  try { ledgers = { base: reconcile('base', inp.g3), alt: reconcile('alt', inp.g3) }; } catch (e) { refErr = e instanceof Error ? e.message : 'reference refused'; }
  const sv = { base: scenarioView(project, 'base', ledgers.base, sel === 'base'), alt: scenarioView(project, 'alt', ledgers.alt, sel === 'alt') };
  const cur = sel ? sv[sel] : null;
  const post = cur?.footing?.posture ?? null;

  // ---- engine-authoritative readiness (never taken from the client; HTTP 200 is not read as readiness)
  const rel = st.release;
  const demo = !!post && post.pricing_go === true && post.bid_ready !== true;
  const headline = !post ? 'NOT BID READY / NOT SUBMITTABLE — no scenario priced yet'
    : post.bid_ready === true ? 'ENGINE REPORTS bid_ready = true'
    : demo ? 'NOT BID READY — FICTIONAL DEMONSTRATION ONLY'
    : 'NOT BID READY / NOT SUBMITTABLE — NO COMPLETE BID PRICE';
  const readiness = {
    source: 'engine: pricing.footing[scenario].posture and the release response',
    headline, tone: post?.bid_ready === true ? 'ready' : demo ? 'demo' : 'stop',
    selected_scenario: sel ? SC_KEY[sel] : null,
    selected: post ? { pricing_go: post.pricing_go, bid_ready: post.bid_ready, release_class: post.release_class, weakest_input_basis: post.weakest_input_basis, reasons: post.reasons } : null,
    by_scenario: Object.fromEntries((['base', 'alt'] as Scenario[]).map(k => { const p = sv[k].footing?.posture; return [SC_KEY[k], p ? { pricing_go: p.pricing_go, bid_ready: p.bid_ready, release_class: p.release_class } : null]; })),
    footing_release_class: Object.fromEntries((['base', 'alt'] as Scenario[]).map(k => [SC_KEY[k], sv[k].footing?.posture?.release_class ?? null])),
    artifact_kind: rel?.artifact_kind ?? null,
    artifact_kind_note: rel ? 'as returned by the engine at release' : 'issued by the engine only when a release is recorded',
    release: rel, // the engine's own release response fields (null until released)
    qualification_texts: ((project.pricing?.estimate_view?.qualifications || []) as string[]).filter(q => /footing scope is|NOT_BID_READY|not a bid-ready/i.test(q)),
  };

  // ---- the four G3 facts and the two workflows
  const open = inp.facts.filter(f => f.status === 'unresolved');
  const g3 = {
    facts: inp.facts.map(f => ({ id: f.id, label: f.label, unit: f.unit, path: f.path, exception_id: f.exception, status: f.status, value: f.value, by: f.by, note: f.note, audit_event: f.audit_event, source: f.source, acceptance: (f as Raw).acceptance ?? null })),
    state: open.length === 4 ? 'unresolved' : open.length ? 'partially_assumed' : inp.facts.every(f => f.status === 'document_confirmed') ? 'document_confirmed' : 'assumed',
    open_count: open.length, rfi: { id: 'RFI-G3', status: inp.facts.every(f => f.status === 'document_confirmed') ? 'resolved_by_accepted_addendum' : 'open', sent: false },
  };

  // ---- how the engine's crew labor uses these quantities (engine quantities vs the schedule / reference)
  const lines: Raw[] = project.pricing?.estimate_view?.labor_lines || [];
  const L = sel ? ledgers[sel] : null;
  const labor = lines.map(l => {
    const m = LABOR_MAP[l.task_id] || { kind: 'none', why: '' };
    let recon: number | null = null;
    if (m.kind === 'holes') recon = post ? cur!.footing!.totals.core_drill_holes ?? null : null;
    else if (m.kind === 'posts') recon = post ? cur!.footing!.totals.posts ?? null : null;
    else if (L) recon = m.kind === 'gross' ? L.gross.total : m.kind === 'net' ? L.net.total : m.kind === 'gates' ? 4 : m.kind === 'windscreen' ? L.accessories.windscreen_lf : null;
    return { task_id: l.task_id, task: l.task, uom: l.uom, engine_quantity: l.quantity, reconciled_quantity: recon, differs: recon !== null && Math.abs(recon - l.quantity) > 1e-6, crew: l.crew_name, labor_cost: l.extended, basis: m.why };
  });

  // ---- qualifications / blockers (stable codes)
  const blockers: Raw[] = [];
  if (g3.facts[0].status === 'unresolved') blockers.push({ code: 'G3_OPENING_UNRESOLVED', hard: true, message: 'Gate G3 clear opening is not specified (RFI required, F502 note 4; Addendum 01 item 2.2). Net Type A, the Type A line-post count and the total hole count cannot be established. Never defaulted to zero.' });
  if (g3.facts.slice(1).some(f => f.status === 'unresolved')) blockers.push({ code: 'G3_POST_FOOTING_UNRESOLVED', hard: true, message: 'Gate G3 post OD and footing diameter/depth are not specified (F502 note 4). The 2 G3 posts stay in the schedule as an UNKNOWN class: their concrete and drilling are unknown, not zero, and no complete price exists.' });
  for (const r of (post?.reasons || []) as Raw[]) if (!['FOOTING_CLASS_UNRESOLVED'].includes(r.code)) blockers.push({ code: r.code, hard: false, message: r.message, engine: true });
  if (post && post.bid_ready !== true) blockers.push({ code: 'FOOTING_SCOPE_NOT_BID_READY', hard: false, message: 'The engine classifies this footing scope as not bid-ready (release_class ' + String(post.release_class) + '). Any release is a labelled demonstration, never a submittable bid.', engine: true });
  blockers.push({ code: 'POST_GEOMETRY_PROVISIONAL', hard: false, message: 'Post counts rest on the human reading of C101 (segment endpoints/gate stations) and nominal face-to-face deductions. They are provisional until a named reviewer confirms them against the CAD.' });
  if (g3.facts.some(f => f.status === 'human_assumption')) blockers.push({ code: 'G3_ASSUMPTION_UNDOCUMENTED', hard: false, message: 'Recorded G3 values are self-declared assumptions, NOT document facts. The RFI remains open and unsent.' });
  const anyCross = (['base', 'alt'] as Scenario[]).some(k => !sv[k].cross.ok);
  if (anyCross || refErr) blockers.push({ code: 'FOOTING_CROSSCHECK_MISMATCH', hard: true, message: refErr ? `Independent reference refused: ${refErr}` : 'The engine footing schedule disagrees with the independent deterministic reference. Do not rely on either until reconciled.' });

  // ---- pricing (engine output only)
  const ev = project.pricing?.estimate_view;
  const pricing = ev ? {
    engine_total: ev.price_total, scope_ref: ev.scope_ref, breakdown: (ev.breakdown || []).map((b: Raw) => ({ key: b.key, label: b.label, amount: b.amount })),
    economics: project.pricing.economics ? { gross_profit: project.pricing.economics.gross_profit, net_profit: project.pricing.economics.net_profit } : null,
    status: demo ? 'QUALIFIED DEMONSTRATION ONLY — NOT BID READY' : 'ENGINE ESTIMATE — see readiness',
    reason: 'Computed by the deterministic pricing engine from the per-class footing schedule. This interface never calculates, scales or adjusts a price. Valid only under the recorded self-declared G3 assumptions.',
    ratebook: project.pricing.ratebook_ref ? { id: project.pricing.ratebook_ref.ratebook_id, version: project.pricing.ratebook_ref.version, content_sha256: project.pricing.ratebook_ref.content_sha256 } : null,
  } : null;

  const bound = Object.fromEntries((['base', 'alt'] as Scenario[]).map(k => [SC_KEY[k], sv[k].footing ? { schedule: sv[k].footing!.schedule_sha256, inputs: sv[k].footing!.calc_inputs_sha256 } : null]));
  const digest = sha(canonical({ selected: sel, scope_version: inp.scope_version, footing: bound, crosscheck_ok: !anyCross && !refErr }));
  const att = st.attestation;
  const att_view = att ? { ...att, current: att.digest === digest && att.scope_version === inp.scope_version } : null;
  return {
    applies: isDp001(project), project_ref: 'DP-001', provenance: 'HUMAN-DERIVED CONTRACTOR-REVIEW REFERENCE + ENGINE footing-calc.v1 (not AI inference, not an approved estimate)',
    selected: sel, scope_version: inp.scope_version,
    contract: { input: 'footing-scope.v1', calc: 'footing-calc.v1', schedule: 'footing-schedule.v1' },
    scenarios: sv, readiness, g3, bound_hashes: bound,
    labor, blockers, pricing, digest, attestation: att_view,
    release_ack_required: blockers.filter(b => !b.hard).map(b => b.code),
    release_hard_blockers: blockers.filter(b => b.hard).map(b => b.code),
    reference: { package_sha256: 'b06c3254cd26dcf0af8d24beb5327431db89ec74b18ebe4e1ebc1f50bb7dda04', python_reference_sha256: '724ae05b6bf6381ae5b8ced9e153ed0127a1582865d8cd5e33e13666f797d27b', note: 'independent cross-check only' },
    evidence: (await readJson('takeoff_evidence.json'))?.evidence || {},
    scenario_defs: SCENARIOS,
  };
}

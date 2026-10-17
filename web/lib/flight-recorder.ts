// Server-only AI Flight Recorder. Implements docs/FLIGHT_RECORDER_CONTRACT.md (gatehouse-flight-trace.v1) exactly:
//  * producer layers (amd | gemma | evolus) come from trace documents that pass a STRICT validator (nothing is repaired or estimated);
//  * Gatehouse validation and human authorization are computed HERE from the ledger and the live project, never read from a trace file.
// No network call, no AMD / Evolus credential: it only reads local files. A document that breaks a rule is reported as REJECTED and not displayed as data.
import { readFile, readdir, stat } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';

/* eslint-disable @typescript-eslint/no-explicit-any */
export const STATES = ['LIVE', 'RECORDED', 'SIMULATED', 'FAILED', 'NOT_REPORTED'] as const;
export type TraceState = (typeof STATES)[number];
export type Field = { value: number | string | boolean | string[] | null; unit: string | null; reported: boolean; derived: null | { formula: string; inputs: string[] } };
export type Source = { kind: string; record_path: string | null; record_sha256: string | null };
export type TraceEvent = { event_id: string; kind: string; label: string; state: TraceState; utc: string | null; fields: Record<string, Field>; source: Source; note: string | null };
export type Layer = { layer: string; state: TraceState; summary: string; events: TraceEvent[] };
export type Trace = { schema: 'gatehouse-flight-trace.v1'; trace_id: string; generated_utc: string | null; producer: { name: string; version: string }; layers: Layer[] };

const PRODUCER_LAYERS = new Set(['amd', 'gemma', 'evolus']);
const SOURCE_KINDS = new Set(['stored_inference_record', 'live_telemetry', 'simulation', 'none']);
const HEX64 = /^[0-9a-f]{64}$/;
const MAX_BYTES = 2_000_000, MAX_EVENTS = 500, MAX_STR = 600;
const RANK: Record<TraceState, number> = { LIVE: 4, RECORDED: 3, SIMULATED: 2, NOT_REPORTED: 1, FAILED: 0 };

/** Layer state is DERIVED (contract rule 9), never trusted from the producer. */
export function layerState(events: { state: TraceState }[]): TraceState {
  if (!events.length) return 'NOT_REPORTED';
  const ok = events.filter(e => e.state !== 'FAILED');
  if (!ok.length) return 'FAILED';
  return ok.reduce((a, e) => (RANK[e.state] > RANK[a] ? e.state : a), ok[0].state);
}

const isStr = (v: unknown, max = MAX_STR): v is string => typeof v === 'string' && v.length <= max;
const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

function checkField(name: string, fld: any, ev: any, errs: string[]) {
  const at = `event ${ev?.event_id}: field ${name}`;
  if (!fld || typeof fld !== 'object') return errs.push(`${at}: not an object`);
  const v = fld.value;
  const okType = v === null || isNum(v) || typeof v === 'boolean' || isStr(v) || (Array.isArray(v) && v.length <= 50 && v.every(x => isStr(x)));
  if (!okType) errs.push(`${at}: unsupported value type`);
  if (fld.reported !== true && fld.reported !== false) errs.push(`${at}: "reported" must be true or false`);
  if (fld.reported === false && v !== null) errs.push(`${at}: reported=false requires value=null (nothing may be filled in)`);
  if (v !== null && fld.reported !== true) errs.push(`${at}: a non-null value requires reported=true`);
  if (fld.unit != null && !isStr(fld.unit, 40)) errs.push(`${at}: bad unit`);
  if (fld.derived != null) {
    const d = fld.derived;
    if (!d || !isStr(d.formula) || !Array.isArray(d.inputs) || !d.inputs.length) errs.push(`${at}: derived needs formula and inputs`);
    else for (const i of d.inputs) { const src = ev.fields?.[i]; if (!src || src.reported !== true || src.value === null) errs.push(`${at}: derived input ${i} is not a reported field of the same event`); }
    if (fld.derived && fld.reported !== true) errs.push(`${at}: a derived value must be reported (or the field must be null and not derived)`);
  }
}

function checkEvent(layer: string, ev: any, errs: string[]) {
  const at = `event ${ev?.event_id}`;
  if (!ev || typeof ev !== 'object' || !isStr(ev.event_id, 200) || !isStr(ev.kind, 80) || !isStr(ev.label)) return errs.push('event: missing event_id/kind/label');
  if (!STATES.includes(ev.state)) return errs.push(`${at}: state must be one of ${STATES.join(', ')}`);
  if (ev.utc != null && (!isStr(ev.utc, 40) || Number.isNaN(Date.parse(ev.utc)))) errs.push(`${at}: utc is not a timestamp`);
  if (ev.note != null && !isStr(ev.note, 2000)) errs.push(`${at}: bad note`);
  const s = ev.source;
  if (!s || !SOURCE_KINDS.has(s.kind)) return errs.push(`${at}: source.kind must be one of ${[...SOURCE_KINDS].join(', ')}`);
  if (s.record_sha256 != null && !HEX64.test(s.record_sha256)) errs.push(`${at}: record_sha256 is not 64 hex`);
  if (s.record_path != null && (!isStr(s.record_path, 300) || s.record_path.includes('..') || s.record_path.startsWith('/'))) errs.push(`${at}: record_path must be relative`);
  if (!ev.fields || typeof ev.fields !== 'object' || Array.isArray(ev.fields)) return errs.push(`${at}: fields must be an object`);
  for (const [k, v] of Object.entries(ev.fields)) { if (!/^[a-z0-9_]{1,60}$/.test(k)) errs.push(`${at}: bad field name`); else checkField(k, v, ev, errs); }
  if (ev.state === 'LIVE' && (s.kind !== 'live_telemetry' || !ev.utc)) errs.push(`${at}: LIVE requires source.kind=live_telemetry and utc`);
  if (ev.state === 'RECORDED' && (s.kind !== 'stored_inference_record' || !s.record_path || !s.record_sha256)) errs.push(`${at}: RECORDED requires a stored_inference_record with record_path and record_sha256`);
  if (ev.state === 'SIMULATED' && (s.kind !== 'simulation' || !ev.note)) errs.push(`${at}: SIMULATED requires source.kind=simulation and a note`);
  if (ev.state === 'FAILED' && !ev.note) errs.push(`${at}: FAILED requires a note giving the reason`);
  if (ev.state === 'NOT_REPORTED' && (s.kind !== 'none' || Object.values(ev.fields).some((f: any) => f?.value !== null))) errs.push(`${at}: NOT_REPORTED requires source.kind=none and only null fields`);
  if (layer === 'gemma') {
    const m = ev.fields?.model;
    if (!m || m.reported !== true || typeof m.value !== 'string' || !/gemma/i.test(m.value)) errs.push(`${at}: a gemma event needs a reported fields.model containing "gemma" (other models belong in the amd layer)`);
  }
  if (layer === 'evolus' && (ev.state === 'LIVE' || ev.state === 'RECORDED')) {
    const x = ev.fields?.workflow_execution_id;
    if (!x || x.reported !== true || typeof x.value !== 'string' || !x.value) errs.push(`${at}: an evolus ${ev.state} event needs a reported fields.workflow_execution_id`);
  }
  // numeric recheck of the two formulas this repository itself produces
  const f = ev.fields, num = (k: string) => (f?.[k]?.reported && isNum(f[k].value) ? (f[k].value as number) : null);
  if (f?.ttft_s?.derived?.formula === 't_first_content_token_s - t_request_sent_s') { const a = num('t_first_content_token_s'), b = num('t_request_sent_s'), d = num('ttft_s'); if (a === null || b === null || d === null || Math.abs(a - b - d) > 0.002) errs.push(`${at}: ttft_s does not equal its formula`); }
  if (f?.tokens_per_s?.derived?.formula === 'completion_tokens / (t_end_s - t_first_content_token_s)') { const c = num('completion_tokens'), e = num('t_end_s'), a = num('t_first_content_token_s'), d = num('tokens_per_s'); if (c === null || e === null || a === null || d === null || e <= a || Math.abs(c / (e - a) - d) > 0.06) errs.push(`${at}: tokens_per_s does not equal its formula`); }
}

export function validateTrace(doc: any): { ok: true; trace: Trace } | { ok: false; errors: string[] } {
  const errs: string[] = [];
  if (!doc || typeof doc !== 'object') return { ok: false, errors: ['not a JSON object'] };
  if (doc.schema !== 'gatehouse-flight-trace.v1') errs.push('schema must be gatehouse-flight-trace.v1');
  if (!isStr(doc.trace_id, 200)) errs.push('trace_id missing');
  if (doc.generated_utc != null && (!isStr(doc.generated_utc, 40) || Number.isNaN(Date.parse(doc.generated_utc)))) errs.push('generated_utc is not a timestamp');
  if (!doc.producer || !isStr(doc.producer.name, 120) || !isStr(doc.producer.version, 200)) errs.push('producer {name, version} missing');
  if (!Array.isArray(doc.layers) || doc.layers.length > 3) errs.push('layers must be an array of at most 3');
  else {
    let n = 0; const seen = new Set<string>();
    for (const L of doc.layers) {
      if (!L || !PRODUCER_LAYERS.has(L.layer)) { errs.push(`layer "${L?.layer}" is not accepted from a trace file (only amd, gemma, evolus; Gatehouse computes its own layers)`); continue; }
      if (seen.has(L.layer)) errs.push(`duplicate layer ${L.layer}`); seen.add(L.layer);
      if (!isStr(L.summary, 2000)) errs.push(`layer ${L.layer}: summary missing`);
      if (!Array.isArray(L.events)) { errs.push(`layer ${L.layer}: events must be an array`); continue; }
      n += L.events.length;
      for (const e of L.events) checkEvent(L.layer, e, errs);
      if (!STATES.includes(L.state)) errs.push(`layer ${L.layer}: bad state`);
      else if (L.state !== layerState(L.events.filter((e: any) => STATES.includes(e?.state)))) errs.push(`layer ${L.layer}: state ${L.state} does not match its events (derived: ${layerState(L.events.filter((e: any) => STATES.includes(e?.state)))})`);
    }
    if (n > MAX_EVENTS) errs.push('too many events');
  }
  return errs.length ? { ok: false, errors: errs.slice(0, 25) } : { ok: true, trace: doc as Trace };
}

async function readJson(file: string): Promise<{ doc: any; sha: string } | { error: string }> {
  try {
    const st = await stat(file);
    if (st.size > MAX_BYTES) return { error: 'file too large' };
    const buf = await readFile(file);
    return { doc: JSON.parse(buf.toString('utf8')), sha: createHash('sha256').update(buf).digest('hex') };
  } catch (e: any) { return { error: e?.code === 'ENOENT' ? 'not found' : 'unreadable or not JSON' }; }
}

export type SourceReport = { name: string; role: 'historical' | 'execution' | 'case' | 'audit'; sha256?: string; accepted: boolean; errors?: string[]; trace_id?: string; producer?: string };
/** One external trace = one execution. Its layers are NEVER combined with another trace or with the historical file. */
export type Execution = { trace_id: string; file: string; sha256: string; producer: string; generated_utc: string | null; outcome: TraceState; layers: Layer[]; review?: unknown };

const ORDER = ['amd', 'gemma', 'evolus'];
const fillLayers = (layers: Layer[], none: string): Layer[] => ORDER.map(k => layers.find(l => l.layer === k) ?? { layer: k, state: 'NOT_REPORTED' as TraceState, summary: none, events: [] });
const withDerivedState = (L: Layer): Layer => ({ ...L, state: layerState(L.events) });

/** Loads the evidence in two SEPARATE groups.
 *  historical: the repository's own stored record (DP001_DIR/flight_recorder.json), earlier runs; never part of any execution.
 *  executions: every accepted trace file in FLIGHT_TRACE_DIR (default <DP001_DIR>/../traces), newest first, each kept apart.
 *  Files are only read. A file that breaks the contract is reported as rejected and none of it is shown. */
export async function loadEvidence(): Promise<{ historical: { layers: Layer[]; source: SourceReport | null }; executions: Execution[]; sources: SourceReport[] }> {
  const dp = process.env.DP001_DIR || '';
  const sources: SourceReport[] = [];
  let historical: Layer[] = fillLayers([], 'No historical record is available to this server.'); let hsrc: SourceReport | null = null;
  if (dp) {
    const file = path.join(dp, 'flight_recorder.json'); const name = path.basename(file); const r = await readJson(file);
    if ('error' in r) hsrc = { name, role: 'historical', accepted: false, errors: [r.error] };
    else {
      const v = validateTrace(r.doc);
      if (!v.ok) hsrc = { name, role: 'historical', sha256: r.sha, accepted: false, errors: v.errors };
      else { hsrc = { name, role: 'historical', sha256: r.sha, accepted: true, trace_id: v.trace.trace_id, producer: `${v.trace.producer.name} ${v.trace.producer.version}`.slice(0, 120) };
        historical = fillLayers(v.trace.layers.map(withDerivedState), 'No historical record for this layer.'); }
    }
    sources.push(hsrc);
  }
  const dir = process.env.FLIGHT_TRACE_DIR || (dp ? path.join(dp, '..', 'traces') : '');
  const files: string[] = [];
  if (dir) { try { for (const n of (await readdir(dir)).sort()) if (n.endsWith('.json') && !n.startsWith('.')) files.push(path.join(dir, n)); } catch { /* no external traces */ } }
  const executions: Execution[] = []; const seen = new Set<string>(hsrc?.trace_id ? [hsrc.trace_id] : []);
  for (const file of files.slice(0, 39)) {
    const name = path.basename(file); const r = await readJson(file);
    if ('error' in r) { sources.push({ name, role: 'execution', accepted: false, errors: [r.error] }); continue; }
    const v = validateTrace(r.doc);
    if (!v.ok) { sources.push({ name, role: 'execution', sha256: r.sha, accepted: false, errors: v.errors }); continue; }
    if (seen.has(v.trace.trace_id)) { sources.push({ name, role: 'execution', sha256: r.sha, accepted: false, errors: [`duplicate trace_id ${v.trace.trace_id}: an execution may not be defined twice`] }); continue; }
    seen.add(v.trace.trace_id);
    const producer = `${v.trace.producer.name} ${v.trace.producer.version}`.slice(0, 120);
    sources.push({ name, role: 'execution', sha256: r.sha, accepted: true, trace_id: v.trace.trace_id, producer });
    const layers = fillLayers(v.trace.layers.map(withDerivedState), 'This execution reported no facts for this layer.');
    const evolus = layers.find(l => l.layer === 'evolus')!;
    executions.push({ trace_id: v.trace.trace_id, file: name, sha256: r.sha, producer, generated_utc: v.trace.generated_utc, outcome: evolus.state, layers });
  }
  const t = (e: Execution) => (e.generated_utc ? Date.parse(e.generated_utc) : -Infinity);
  executions.sort((x, y) => t(y) - t(x) || (x.file < y.file ? -1 : 1));
  return { historical: { layers: historical, source: hsrc }, executions, sources };
}

const fld = (value: Field['value'], unit: string | null = null): Field => ({ value, unit, reported: value !== null, derived: null });

/** Gatehouse's own layer 1: what CODE did to the model's claims. Computed from the stored ledger; no model is consulted. */
export function validationLayer(ledger: { sha: string; data: any } | null): Layer {
  if (!ledger) return { layer: 'gatehouse_validation', state: 'NOT_REPORTED', summary: 'The evidence ledger is not available to this server.', events: [] };
  const d = ledger.data, acc = d.accounting || {}, src: Source = { kind: 'ledger_replay', record_path: 'dp001/ai_findings.json', record_sha256: ledger.sha };
  const events: TraceEvent[] = [];
  const counts = acc.classification_counts || {};
  const f: Record<string, Field> = { real_findings: fld(acc.real_findings ?? null), simulated_findings: fld(acc.simulated_findings ?? null), attempts_recorded: fld(acc.real_amd_attempts_recorded ?? null) };
  for (const [k, v] of Object.entries(counts)) f[`class_${k.toLowerCase()}`] = fld(typeof v === 'number' ? v : null);
  events.push({ event_id: 'validation:ledger', kind: 'ledger_replay', label: 'Every model claim classified by code against the PDF: text claims and gate-label positions against the PDF\'s printed text positions, fence-type leaders against its vector geometry, gate symbols not verified', state: 'RECORDED', utc: null, fields: f, source: src, note: 'Computed offline by amd_bridge/ledger.py; replayed here. A model\'s own confidence is recorded but never counts as evidence.' });
  for (const x of (d.findings || []).filter((x: any) => x.classification === 'CONTRADICTED_BY_DRAWING_EVIDENCE')) {
    const runId = (() => { try { return JSON.parse(JSON.stringify(x.run)).run_id ?? null; } catch { return null; } })();
    events.push({ event_id: `validation:${x.finding_id}`, kind: 'claim_contradicted', label: `${x.origin_label || 'AI CLAIM CONTRADICTED BY DRAWING EVIDENCE'} · ${x.relationship_key || x.finding_id}${runId ? ' · ' + runId : ''}`, state: 'RECORDED', utc: null,
      fields: { finding_id: fld(String(x.finding_id)), model_stated_confidence: fld(x.uncertainty?.model_stated ?? null), verifier_result: fld(x.model_confidence_vs_verification ?? null),
                acceptance: fld('refused: API returns 409 CONTRADICTED_BY_DRAWING_EVIDENCE; the Accept control is disabled'), run: fld(runId) },
      source: src, note: 'The finding stays visible as evidence of the model\'s error; it cannot change scope.' });
  }
  for (const x of (d.findings || []).filter((x: any) => x.provenance === 'SIMULATED_TEST_DATA')) {
    events.push({ event_id: `validation:${x.finding_id}`, kind: 'simulated_guard_test', label: `SIMULATED test finding · ${x.finding_id}`, state: 'SIMULATED', utc: null, fields: { finding_id: fld(String(x.finding_id)), classification: fld(x.classification ?? null) },
      source: { kind: 'simulation', record_path: 'dp001/ai_findings.json', record_sha256: ledger.sha }, note: 'Exists only to exercise the guards; excluded from every AI-performance statement.' });
  }
  return { layer: 'gatehouse_validation', state: layerState(events), summary: 'Code, not the model, decides what counts as evidence.', events };
}

/** Gatehouse's own layer 2: named, self-declared human decisions recorded on THIS live project (engine audit trail + AI finding decisions).
 *  Only audit entries that carry a named actor are shown; system entries (start, invalidations, ...) have no actor and are counted, not presented as decisions.
 *  Timestamps are copied from the record; a missing one stays null, it is never filled in. */
export function humanLayer(project: any | null, aiDecisions: any[]): Layer {
  const events: TraceEvent[] = [];
  const clip = (s: unknown) => (typeof s === 'string' ? s.slice(0, 300) : typeof s === 'number' && Number.isFinite(s) ? String(s) : null);
  const ts = (v: unknown) => (typeof v === 'string' && v.length <= 40 && !Number.isNaN(Date.parse(v)) ? v : null);
  const audit: any[] = Array.isArray(project?.audit) ? project.audit : [];
  const named = audit.filter(a => typeof a?.actor === 'string' && a.actor.trim());
  for (const a of named.slice(-60)) {
    events.push({ event_id: `human:audit:${a.event_id ?? events.length}`, kind: String(a.event || 'decision').slice(0, 80), label: `${clip(a.event) || 'decision'}${a.exception_id ? ' · ' + clip(a.exception_id) : ''}`, state: 'LIVE', utc: ts(a.utc),
      fields: { by: fld(clip(a.actor)), exception: fld(clip(a.exception_id)), option: fld(clip(a.option_id)), value: fld(clip(a.value)), scope_version: fld(typeof a.scope_version === 'number' ? a.scope_version : null), note: fld(clip(a.note)) },
      source: { kind: 'session_audit', record_path: null, record_sha256: null }, note: 'Self-declared name; not an authenticated approval.' });
  }
  for (const x of aiDecisions.slice(-40)) {
    events.push({ event_id: `human:ai:${x.finding_id}`, kind: `ai_finding_${x.decision}`, label: `AI finding ${x.decision} · ${x.finding_id}`, state: 'LIVE', utc: ts(x.at),
      fields: { by: fld(clip(x.by)), outcome: fld(clip(x.outcome)), note: fld(clip(x.note)) }, source: { kind: 'session_audit', record_path: null, record_sha256: null }, note: 'Self-declared name; not an authenticated approval.' });
  }
  const system = audit.length - named.length;
  return { layer: 'human_authorization', state: layerState(events), summary: events.length
    ? `Named decisions recorded on this project, oldest first${system ? ` (${system} system entr${system === 1 ? 'y' : 'ies'} not shown)` : ''}. Release still needs a current takeoff review and acknowledgement.`
    : `No human decision has been recorded on this project yet${system ? ` (${system} system entr${system === 1 ? 'y' : 'ies'}, e.g. project start, are not decisions)` : ''}.`, events };
}

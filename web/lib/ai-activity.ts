// AI activity: one row per kind of AI step, read ONLY from stored records (the recorded capture, the attempt table built from stored attempt records, the Evolus run
// records and their traces). Every value is copied from a record; one no record states prints NOT_REPORTED. Nothing is estimated and nothing is summed across calls.
// Organization, project and key identifiers are never read into the output.
import { readFile, readdir } from 'node:fs/promises';
import { homedir } from 'node:os';
import path from 'node:path';
import { loadEvidence, type Execution } from './flight-recorder.ts';

/* eslint-disable @typescript-eslint/no-explicit-any */
export const NR = 'NOT_REPORTED';
export type Mode = 'LIVE' | 'RECORDED' | 'SIMULATED';
export type AttemptRow = { attempt_id: string; model: string; state: string; when: string; when_basis: string; tokens_in: string; tokens_out: string; tokens_cached: string; duration: string; duration_basis: string; cost: string };
export type Measurement = { label: string; value: string };
export type ActivityRow = { id: string; step: string; model: string; path: string; mode: Mode; mode_note: string; when: string; tokens_in: string; tokens_out: string; tokens_cached: string; duration: string; cost: string;
  measurements: Measurement[]; notes: string[]; attempts?: AttemptRow[]; calls: number; calls_with_tokens: number; sources: { file: string; sha256?: string }[] };
export type Activity = { schema: 'gatehouse-ai-activity-view.v1'; rows: ActivityRow[]; footer: string; calls: number; calls_with_tokens: number; notice: string };

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const int = (v: unknown) => { const n = num(v); return n === null ? NR : n.toLocaleString('en-US'); };
const secs = (v: unknown) => { const n = num(v); return n === null ? NR : `${n.toLocaleString('en-US', { maximumFractionDigits: 3 })} s`; };
const usd = (v: unknown) => { const n = num(v); return n === null ? NR : `$${n.toFixed(7)}`; };
const utc = (v: unknown) => (typeof v === 'string' && v.length <= 40 && !Number.isNaN(Date.parse(v)) ? v : NR);
const epochUtc = (v: unknown) => { const n = num(v); return n === null ? NR : new Date(n * 1000).toISOString().replace(/\.\d+Z$/, 'Z'); };
/** Epoch milliseconds keeping the sub-millisecond digits the record states (a 7-digit fraction is not rounded away). */
const isoMs = (s: unknown) => { if (typeof s !== 'string') return NaN; const m = /^(.*?)(\.(\d+))?Z$/.exec(s); if (!m) return NaN; return Date.parse(`${m[1]}Z`) + (m[3] ? Number(`0.${m[3]}`) * 1000 : 0); };

async function readJson(file: string): Promise<{ doc: any; sha: string } | null> {
  try { const buf = await readFile(file); const { createHash } = await import('node:crypto'); return { doc: JSON.parse(buf.toString('utf8')), sha: createHash('sha256').update(buf).digest('hex') }; } catch { return null; }
}

const CAPTURE = 'f0b0571c9696_call3.json';
async function addendumRow(): Promise<ActivityRow> {
  const dir = process.env.GATEHOUSE_CAPTURE_DIR || path.join(homedir(), 'ifi-gatehouse-live-captures');
  const r = await readJson(path.join(dir, CAPTURE));
  const mode = process.env.ENGINE_ADDENDUM_MODE;
  const base = { id: 'addendum-parse', step: 'Addendum parse (Addendum 02)', measurements: [] as Measurement[], notes: [] as string[], calls: 1 };
  const modeFields = mode === 'recorded' ? { mode: 'RECORDED' as Mode, mode_note: 'This build replays the stored capture; no new model call is made.' }
    : mode === 'reconstructed' ? { mode: 'RECORDED' as Mode, mode_note: 'This build replays a reconstruction; no new model call is made.' } : { mode: 'LIVE' as Mode, mode_note: 'Live parse is authorization-gated and disabled in the hosted image.' };
  if (!r) return { ...base, ...modeFields, model: NR, path: NR, when: NR, tokens_in: NR, tokens_out: NR, tokens_cached: NR, duration: NR, cost: NR, calls_with_tokens: 0, sources: [], notes: ['The stored capture is not available to this server.'] };
  let body: any = null; try { body = JSON.parse(String(r.doc.response_raw_text)); } catch { body = null; }
  const u = body?.usage; const md = body?.metadata;
  const hasTok = num(u?.prompt_tokens) !== null || num(u?.completion_tokens) !== null;
  return { ...base, ...modeFields, model: typeof md?.used_model === 'string' ? md.used_model : typeof body?.model === 'string' ? body.model : NR,
    path: `AMD Token Factory${typeof md?.used_provider === 'string' ? ` · provider route ${md.used_provider}` : ''}${typeof r.doc.endpoint_path === 'string' ? ` · ${r.doc.endpoint_path}` : ''}`,
    when: `written ${utc(r.doc.utc)}`, tokens_in: int(u?.prompt_tokens), tokens_out: int(u?.completion_tokens), tokens_cached: int(u?.prompt_tokens_details?.cached_tokens),
    duration: num(r.doc.elapsed_ms) === null ? NR : `${int(r.doc.elapsed_ms)} ms`, cost: usd(u?.cost), calls_with_tokens: hasTok ? 1 : 0, sources: [{ file: `captures/${CAPTURE}`, sha256: r.sha }] };
}

async function scopeReadRow(): Promise<ActivityRow> {
  const dp = process.env.DP001_DIR || ''; const r = await readJson(path.join(dp, 'ai_activity.json'));
  const base = { id: 'scope-read-evaluation', step: 'Scope-read evaluation runs (stored AMD attempts)', mode: 'RECORDED' as Mode, mode_note: 'Stored outputs shown offline; no request is made by this page or this session.', measurements: [] as Measurement[], notes: [] as string[] };
  if (!r || !Array.isArray(r.doc.attempts)) return { ...base, model: NR, path: NR, when: NR, tokens_in: NR, tokens_out: NR, tokens_cached: NR, duration: NR, cost: NR, calls: 0, calls_with_tokens: 0, sources: [], notes: ['The stored attempt table is not available to this server.'] };
  const A: any[] = r.doc.attempts;
  const attempts: AttemptRow[] = A.map(a => ({ attempt_id: String(a.attempt_id), model: String(a.model), state: String(a.state), when: utc(a.when_utc), when_basis: typeof a.when_basis === 'string' ? a.when_basis : NR, tokens_in: int(a.tokens_in), tokens_out: int(a.tokens_out), tokens_cached: int(a.tokens_cached),
    duration: secs(a.call_time_s) + (a.state === 'TIMED_OUT' && num(a.call_time_s) !== null ? ' (until timeout/abort)' : ''), duration_basis: typeof a.call_time_basis === 'string' ? a.call_time_basis : NR, cost: usd(a.cost_usd) }));
  const count = (f: (a: any) => string) => { const m = new Map<string, number>(); for (const a of A) m.set(f(a), (m.get(f(a)) || 0) + 1); return m; };
  const models = [...count(a => String(a.model))].map(([k, v]) => `${k} ${v}`).join(' · ');
  const st = count(a => String(a.state)); const lbl: Record<string, string> = { CANDIDATES_AVAILABLE: 'produced candidates', FAILED: 'failed', TIMED_OUT: 'timed out' };
  const outcomes = [...st].map(([k, v]) => `${v} ${lbl[k] || k.toLowerCase()}`).join(', ');
  const withTok = A.filter(a => num(a.tokens_in) !== null || num(a.tokens_out) !== null).length, withTime = A.filter(a => num(a.call_time_s) !== null).length, withWhen = A.filter(a => utc(a.when_utc) !== NR).length, untilTimeout = A.filter(a => a.state === 'TIMED_OUT' && num(a.call_time_s) !== null).length;
  return { ...base, model: models, path: 'AMD Developer Cloud / Token Factory', when: `recorded on ${withWhen} of ${A.length} attempts; NOT_REPORTED on the rest (see attempts)`,
    tokens_in: `reported on ${withTok} of ${A.length} attempts`, tokens_out: `reported on ${withTok} of ${A.length} attempts`, tokens_cached: `reported on ${A.filter(a => num(a.tokens_cached) !== null).length} of ${A.length} attempts`,
    duration: `reported on ${withTime} of ${A.length} attempts (${untilTimeout} of them until timeout/abort)`, cost: `reported on ${A.filter(a => num(a.cost_usd) !== null).length} of ${A.length} attempts`,
    measurements: [{ label: `${A.length} stored attempts`, value: outcomes }], notes: ['Failures and timeouts are part of the record and are listed with the rest.', 'Duration on a timed-out attempt is the time until the client gave up or aborted, not a completed call. A time of day without a date in a request log is not a timestamp and is not shown.'],
    attempts, calls: A.length, calls_with_tokens: withTok, sources: [{ file: 'dp001/ai_activity.json', sha256: r.sha }, { file: 'dp001/ai_findings.json', sha256: typeof r.doc.ledger_sha256 === 'string' ? r.doc.ledger_sha256 : undefined }] };
}

const RUN_ID = /GH-RUN-[0-9a-f]{12}/;
async function runRecords(): Promise<Map<string, { doc: any; sha: string }>> {
  const dp = process.env.DP001_DIR || ''; const dir = process.env.GATEHOUSE_CASES_DIR || (dp ? path.join(dp, '..', 'cases') : '');
  const out = new Map<string, { doc: any; sha: string }>();
  if (!dir) return out;
  try { for (const n of await readdir(dir)) { const m = /^(GH-RUN-[0-9a-f]{12})\.json$/.exec(n); if (!m) continue; const r = await readJson(path.join(dir, n)); if (r) out.set(m[1], r); } } catch { /* none */ }
  return out;
}
const evolusEvent = (x: Execution) => (x.layers.find(l => l.layer === 'evolus')?.events || []).find((e: any) => e.kind === 'workflow_execution') as any;
const fv = (e: any, k: string) => (e?.fields?.[k]?.reported ? e.fields[k].value : null);

async function evolusRows(execs: Execution[]): Promise<ActivityRow[]> {
  const runs = await runRecords(); const rows: ActivityRow[] = [];
  for (const x of execs) {
    const e = evolusEvent(x); if (!e) continue;
    const runId = RUN_ID.exec(String(e.source?.record_path || ''))?.[0] ?? null; const run = runId ? runs.get(runId) : undefined;
    const failed = e.state === 'FAILED' || (run && run.doc.status !== 'COMPLETED_VALID');
    const measurements: Measurement[] = []; const notes: string[] = [];
    const total = num(fv(e, 'total_s'));
    if (run) {
      const ex = run.doc.evolus_execution || {}; const t0 = isoMs(ex.requestedAt), t1 = isoMs(ex.completedAt);
      if (total !== null) measurements.push({ label: 'Overall, Gatehouse submission to completion (includes polling)', value: secs(total) });
      if (!Number.isNaN(t0) && !Number.isNaN(t1)) measurements.push({ label: 'Evolus-reported, requested to completed', value: secs((t1 - t0) / 1000) });
      const step1 = num(ex.stepStates?.['1']?.durationMs); if (step1 !== null) measurements.push({ label: 'Evolus-reported, workflow step 1 execution', value: secs(step1 / 1000) });
    } else if (total !== null) measurements.push({ label: 'Gatehouse submission to ' + (failed ? 'failure' : 'completion'), value: secs(total) });
    const mi = run?.doc.model_identity; const configured = typeof mi?.configured === 'string' ? mi.configured : null;
    if (e.note) notes.push(`Recorded note: ${String(e.note).slice(0, 80)}`);
    if (!run) notes.push('The run record is not available to this server; only the trace is shown, so the model and token fields are not reported.');
    if (run && num(run.doc.evolus_execution?.consumption?.llmTokens) === null && num(run.doc.evolus_execution?.totalTokenCount) === null) notes.push('The run reports no token counts and no cost.');
    const cost = run ? usd(run.doc.evolus_execution?.consumption?.costUsd) : NR;
    rows.push({ id: `evolus-${runId ?? x.trace_id}`, step: `Evolus agent run${failed ? ' (FAILED)' : ''} · ${runId ?? NR}`,
      model: configured ? `configured ${configured}, not reported by the run` : NR, path: 'Evolus workflow (the model behind it is configured, not reported)',
      mode: 'RECORDED', mode_note: `Stored record${run?.doc.mode ? ` of a run that was ${String(run.doc.mode)} when made` : ''}; no new call is made.`,
      when: `${run ? String(run.doc.status || x.outcome) : x.outcome} · ${epochUtc(fv(e, 'submitted_epoch_s'))}`, tokens_in: NR, tokens_out: NR, tokens_cached: NR, duration: measurements.length ? 'see the labelled measurements below' : NR, cost,
      measurements, notes, calls: 1, calls_with_tokens: 0, sources: [{ file: `traces/${x.file}`, sha256: x.sha256 }, ...(run && runId ? [{ file: `cases/${runId}.json`, sha256: run.sha }] : [])] });
  }
  return rows;
}

const bidDeskRow = (): ActivityRow => ({ id: 'bid-desk', step: 'Bid Desk chat', model: 'none', path: 'none (answers come from the engine state)', mode: 'SIMULATED', mode_note: 'No AI call is made. Live calls are disabled in production.',
  when: 'not applicable', tokens_in: 'no AI call', tokens_out: 'no AI call', tokens_cached: 'no AI call', duration: 'no AI call', cost: 'no AI call', measurements: [], notes: ['Advisory only; the chat is not an audit record.'], calls: 0, calls_with_tokens: 0, sources: [] });

export async function buildAiActivity(): Promise<Activity> {
  const ev = await loadEvidence();
  const sorted = [...ev.executions].sort((a, b) => Date.parse(String(a.generated_utc)) - Date.parse(String(b.generated_utc)));
  const evo = await evolusRows(sorted);
  // completed run first, then the failed one
  evo.sort((a, b) => Number(a.step.includes('FAILED')) - Number(b.step.includes('FAILED')));
  const rows = [await addendumRow(), await scopeReadRow(), ...evo, bidDeskRow()];
  const calls = rows.reduce((n, r) => n + r.calls, 0), withTok = rows.reduce((n, r) => n + r.calls_with_tokens, 0);
  return { schema: 'gatehouse-ai-activity-view.v1', rows, calls, calls_with_tokens: withTok, footer: `Tokens reported for ${withTok} of ${calls} calls.`,
    notice: 'Read from stored records only. Calls counted: the recorded Addendum parse, each stored AMD attempt, and each Evolus submission (completed or failed). Values are never summed or estimated; NOT_REPORTED means no record states it.' };
}

/** The Flight Recorder's historical Evolus summary, built from the run records and traces instead of a fixed sentence. */
export async function evolusStatement(execs: Execution[]): Promise<string> {
  const runs = await runRecords(); const parts: string[] = [];
  for (const x of execs) {
    const e = evolusEvent(x); if (!e) continue;
    const runId = RUN_ID.exec(String(e.source?.record_path || ''))?.[0] ?? null; const run = runId ? runs.get(runId) : undefined;
    const status = run ? String(run.doc.status) : String(x.outcome);
    parts.push(`${runId ?? x.trace_id}${e.utc ? ` (${String(e.utc).slice(0, 10)})` : ''}: ${status}${!run && e.note ? `, ${String(e.note).slice(0, 40)}` : ''}`);
  }
  return parts.length ? `${parts.length} Evolus workflow execution${parts.length === 1 ? ' is' : 's are'} recorded, each kept in its own execution below: ${parts.join('; ')}. This historical baseline predates them and holds no Evolus events.`
    : 'No Evolus execution record is available to this server. None is claimed.';
}

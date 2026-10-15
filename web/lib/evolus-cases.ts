// Server-only, READ-ONLY reader for the pending-review RFI cases that ANVIL 2's Evolus adapter persisted (GATEHOUSE_CASES_DIR, mounted read-only).
// A case is a stored DRAFT. This module can only display it: it has no approve / send / release path, calls no engine route and no model, and never writes.
// Strictness: a case that is malformed, claims any approval/transmission/authority, cites something it has no evidence record for, disagrees with its run
// record or with Gatehouse's own document registry, or belongs to no accepted execution trace is REJECTED and none of its content is displayed.
import { readFile, readdir, stat } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import type { Execution, SourceReport } from './flight-recorder.ts';
import type { Assessment, AuditInfo } from './evolus-audit.ts';

/* eslint-disable @typescript-eslint/no-explicit-any */
const HEX64 = /^[0-9a-f]{64}$/;
const CASE_FILE = /^(GH-CASE-[0-9a-f]{12})\.json$/, RUN_FILE = /^(GH-RUN-[0-9a-f]{12})\.json$/;
const MAX_BYTES = 400_000, MAX_FILES = 60;
const isStr = (v: unknown, max = 2000): v is string => typeof v === 'string' && v.length > 0 && v.length <= max;
const keysEq = (o: any, keys: string[]) => !!o && typeof o === 'object' && !Array.isArray(o) && Object.keys(o).sort().join() === [...keys].sort().join();

export type CaseEvidence = { excerpt_id: string; doc_id: string; page: number; doc_sha256: string; verified_in_source: true; quote_in_source: string | null; registry: 'match' | 'unknown_document' };
export type RfiCase = {
  case_id: string; run_id: string; gatehouse_trace_id: string; draft_id: string; subject: string; question: string; missing_requirements: string[];
  status: 'PENDING_HUMAN_REVIEW'; approval_status: 'NOT_APPROVED'; sent_externally: false; ai_generated: true; note: string | null;
  authority: { changes_scope: false; changes_estimate: false; authorizes_labor_or_release: false; marks_bid_ready: false; requires_named_human: true };
  evidence: CaseEvidence[]; file: string; sha256: string;
  assessment: Assessment;
  integrity: { run_record: 'matches_trace_hash' | 'not_available'; draft_matches_run_record: boolean | null };
};
export type RunSummary = { run_id: string; status: string | null; mode: string | null; execution_id: string | null; sha256: string; matches_trace_hash: boolean;
  issues: { issue_id: string; title: string; category: string; severity: string | null; assessment?: Assessment }[]; rfi_drafts: number | null; dropped_excerpts: number | null; dropped_reasons: string[]; dropped_doc_ids: string[]; dropped_unregistered: boolean | null;
  gatehouse_state_unchanged: boolean | null; ai_suggestion_only: boolean | null };
export type Review = { run: RunSummary | null; cases: RfiCase[]; audit?: AuditInfo; audit_unverifiable?: boolean };

export const NOT_AUDITED: Assessment = { state: 'NOT_AUDITED', actionable: false, label: 'NOT INDEPENDENTLY AUDITED', summary: 'No independent audit record covers this item. Structural validity and authentic citations do not show the conclusion is supported.', verification_note: null, evidence: [] };

async function readRaw(file: string): Promise<{ doc: any; sha: string } | { error: string }> {
  try { const st = await stat(file); if (st.size > MAX_BYTES) return { error: 'file too large' }; const buf = await readFile(file);
    return { doc: JSON.parse(buf.toString('utf8')), sha: createHash('sha256').update(buf).digest('hex') }; }
  catch (e: any) { return { error: e?.code === 'ENOENT' ? 'not found' : 'unreadable or not JSON' }; }
}

/** Strict structural validation of one stored case. Returns reasons; empty = structurally valid. */
export function checkCaseShape(c: any, fileStem: string): string[] {
  const e: string[] = [];
  const TOP = ['ai_generated', 'approval', 'authority', 'case_id', 'draft', 'evidence_checks', 'gatehouse_trace_id', 'kind', 'note', 'run_id', 'sent_externally', 'status'];
  if (!c || typeof c !== 'object' || Array.isArray(c)) return ['not a JSON object'];
  const extra = Object.keys(c).filter(k => !TOP.includes(k)); if (extra.length) e.push(`unexpected field(s): ${extra.slice(0, 5).join(', ')}`);
  if (c.case_id !== fileStem) e.push('case_id does not match the file name');
  if (c.kind !== 'RFI_DRAFT') e.push('kind must be RFI_DRAFT');
  if (c.status !== 'PENDING_HUMAN_REVIEW') e.push(`status ${JSON.stringify(c.status)} is not displayable: only PENDING_HUMAN_REVIEW drafts are shown (this build has no authenticated approval record)`);
  if (c.ai_generated !== true) e.push('ai_generated must be true');
  if (c.sent_externally !== false) e.push('sent_externally must be false');
  const ap = c.approval; if (!keysEq(ap, ['status', 'approved_by', 'approved_at']) || ap.status !== 'NOT_APPROVED' || ap.approved_by !== null || ap.approved_at !== null) e.push('approval must be exactly NOT_APPROVED with no approver and no time');
  const au = c.authority; if (!keysEq(au, ['authorizes_labor_or_release', 'changes_estimate', 'changes_scope', 'marks_bid_ready', 'requires_named_human']) || au.authorizes_labor_or_release !== false || au.changes_estimate !== false || au.changes_scope !== false || au.marks_bid_ready !== false || au.requires_named_human !== true) e.push('authority flags must all be false (requires_named_human true)');
  if (!/^GH-RUN-[0-9a-f]{12}$/.test(String(c.run_id))) e.push('bad run_id');
  if (!isStr(c.gatehouse_trace_id, 120)) e.push('bad gatehouse_trace_id');
  if (c.note != null && !isStr(c.note, 500)) e.push('bad note');
  const d = c.draft;
  if (!keysEq(d, ['draft_id', 'subject', 'question', 'missing_requirements', 'citations'])) e.push('draft must have exactly draft_id, subject, question, missing_requirements, citations');
  else {
    if (!isStr(d.draft_id, 40) || !isStr(d.subject, 300) || !isStr(d.question, 2000)) e.push('draft text fields missing or too long');
    if (!Array.isArray(d.missing_requirements) || d.missing_requirements.length > 20 || !d.missing_requirements.every((x: unknown) => isStr(x, 300))) e.push('bad missing_requirements');
    if (!Array.isArray(d.citations) || !d.citations.length || d.citations.length > 20 || !d.citations.every((x: any) => keysEq(x, ['excerpt_id']) && /^[A-Za-z0-9_.-]{1,60}$/.test(String(x.excerpt_id)))) e.push('citations must be a non-empty list of {excerpt_id}');
  }
  const ec = c.evidence_checks;
  if (!Array.isArray(ec) || ec.length > 30) e.push('bad evidence_checks');
  else {
    for (const x of ec) {
      if (!keysEq(x, ['doc_id', 'doc_sha256', 'kind', 'page', 'quote_in_source', 'ref', 'verified_in_source'])) { e.push('evidence check has unexpected shape'); continue; }
      if (x.kind !== 'source_excerpt' || !isStr(x.doc_id, 120) || !HEX64.test(String(x.doc_sha256)) || !Number.isInteger(x.page) || x.page < 1 || !isStr(x.ref, 60)) e.push(`evidence check ${String(x.ref).slice(0, 40)} is malformed`);
      if (x.quote_in_source !== null && !isStr(x.quote_in_source, 2000)) e.push('bad quote_in_source');
      if (x.verified_in_source !== true) e.push(`evidence ${String(x.ref).slice(0, 40)} is not verified in the source`);
    }
    if (d && Array.isArray(d.citations)) for (const ct of d.citations) if (!ec.some((x: any) => x?.ref === ct?.excerpt_id)) e.push(`citation ${String(ct?.excerpt_id).slice(0, 40)} has no evidence record`);
  }
  return e.slice(0, 15);
}

function summarizeRun(run: any, sha: string, matches: boolean, registryDocs: { doc_id: string }[] | null): RunSummary {
  const s = (v: unknown, n = 300) => (typeof v === 'string' && v.length <= n ? v : null);
  const issues = (Array.isArray(run?.issues) ? run.issues : []).slice(0, 20).map((i: any) => i?.issue).filter((i: any) => i && s(i.issue_id, 40) && s(i.title)).map((i: any) => ({ issue_id: i.issue_id, title: i.title, category: s(i.category, 80) || '—', severity: s(i.severity, 80) }));
  const dropped = Array.isArray(run?.dropped_unverifiable_excerpts) ? run.dropped_unverifiable_excerpts : null;
  return { run_id: String(run.run_id), status: s(run.status, 80), mode: s(run.mode, 40), execution_id: s(run.execution_id, 120), sha256: sha, matches_trace_hash: matches, issues,
    rfi_drafts: Array.isArray(run?.rfi_drafts) ? run.rfi_drafts.length : null, dropped_excerpts: dropped ? dropped.length : null,
    dropped_reasons: dropped ? [...new Set<string>(dropped.map((x: any) => s(x?.reason, 80)).filter((x: any): x is string => !!x))] : [],
    dropped_doc_ids: dropped ? [...new Set<string>(dropped.map((x: any) => s(x?.doc_id, 80)).filter((x: any): x is string => !!x))] : [],
    dropped_unregistered: dropped && dropped.length && registryDocs ? dropped.every((x: any) => typeof x?.doc_id === 'string' && !registryDocs.some(r => r.doc_id === x.doc_id)) : null,
    gatehouse_state_unchanged: typeof run?.state_hash_before === 'string' && typeof run?.state_hash_after === 'string' ? run.state_hash_before === run.state_hash_after : null,
    ai_suggestion_only: typeof run?.ai_suggestion_only === 'boolean' ? run.ai_suggestion_only : null };
}

/** Attaches stored cases to the execution that produced them (by gatehouse_trace_id). Never changes an execution's layers or states. */
export async function loadCases(executions: Execution[], registryDocs: { doc_id: string; sha256: string; pages: number }[] | null):
  Promise<{ reviews: Map<string, Review>; sources: SourceReport[]; runs: Map<string, { doc: any; sha: string }> }> {
  const dir = process.env.GATEHOUSE_CASES_DIR || (process.env.DP001_DIR ? path.join(process.env.DP001_DIR, '..', 'cases') : '');
  const reviews = new Map<string, Review>(); const sources: SourceReport[] = [];
  let names: string[] = [];
  if (dir) { try { names = (await readdir(dir)).sort(); } catch { return { reviews, sources, runs: new Map() }; } }
  const runs = new Map<string, { doc: any; sha: string }>();
  for (const n of names.filter(n => RUN_FILE.test(n)).slice(0, MAX_FILES)) { const r = await readRaw(path.join(dir, n)); if (!('error' in r) && r.doc && r.doc.run_id === n.replace(/\.json$/, '')) runs.set(r.doc.run_id, r); }
  const byTrace = new Map(executions.map(x => [x.trace_id, x]));
  for (const n of names.filter(n => CASE_FILE.test(n)).slice(0, MAX_FILES)) {
    const stem = n.replace(/\.json$/, ''); const rep = (accepted: boolean, errors?: string[], sha?: string): SourceReport => ({ name: n, role: 'case', accepted, errors, sha256: sha, trace_id: undefined });
    const r = await readRaw(path.join(dir, n));
    if ('error' in r) { sources.push(rep(false, [r.error])); continue; }
    const errs = checkCaseShape(r.doc, stem);
    if (errs.length) { sources.push(rep(false, errs, r.sha)); continue; }
    const c = r.doc;
    const x = byTrace.get(c.gatehouse_trace_id);
    if (!x) { sources.push(rep(false, [`no accepted execution trace ${c.gatehouse_trace_id}: a case is shown only under the execution that produced it`], r.sha)); continue; }
    // the execution's own Evolus event names the run record and its hash; a case must belong to that run
    const evSrc = x.layers.find(l => l.layer === 'evolus')?.events.find(e => e.source?.record_path)?.source;
    const tracedRun = evSrc?.record_path?.match(/^evolus_runs\/(GH-RUN-[0-9a-f]{12})\.json$/)?.[1] ?? null;
    if (tracedRun && tracedRun !== c.run_id) { sources.push(rep(false, [`case run_id ${c.run_id} is not the run recorded in the execution trace (${tracedRun})`], r.sha)); continue; }
    const run = runs.get(c.run_id) || null; let matches = false; let draftOk: boolean | null = null; let integrity: RfiCase['integrity']['run_record'] = 'not_available';
    if (run) {
      matches = !!evSrc?.record_sha256 && evSrc.record_sha256 === run.sha;
      if (!matches) { sources.push(rep(false, ['the run record in the case directory does not match the sha256 recorded in the execution trace'], r.sha)); continue; }
      if (run.doc.gatehouse_trace_id !== c.gatehouse_trace_id) { sources.push(rep(false, ['case and run record name different traces'], r.sha)); continue; }
      const rd = (Array.isArray(run.doc.rfi_drafts) ? run.doc.rfi_drafts : []).find((q: any) => q?.draft?.draft_id === c.draft.draft_id);
      draftOk = !!rd && JSON.stringify(rd.draft, Object.keys(rd.draft).sort()) === JSON.stringify(c.draft, Object.keys(c.draft).sort()) && JSON.stringify(rd.draft.citations) === JSON.stringify(c.draft.citations);
      if (!draftOk) { sources.push(rep(false, ['the draft in this case differs from the draft in its run record'], r.sha)); continue; }
      integrity = 'matches_trace_hash';
    }
    // independent check against Gatehouse's own document registry
    const ev: CaseEvidence[] = []; let bad: string | null = null;
    for (const ct of c.draft.citations) {
      const k = c.evidence_checks.find((q: any) => q.ref === ct.excerpt_id); const reg = registryDocs?.find(d => d.doc_id === k.doc_id) ?? null;
      if (reg && reg.sha256 !== k.doc_sha256) { bad = `${k.doc_id}: document hash differs from Gatehouse's registry`; break; }
      if (reg && k.page > reg.pages) { bad = `${k.doc_id}: page ${k.page} is beyond the document's ${reg.pages} pages`; break; }
      ev.push({ excerpt_id: ct.excerpt_id, doc_id: k.doc_id, page: k.page, doc_sha256: k.doc_sha256, verified_in_source: true, quote_in_source: k.quote_in_source, registry: reg ? 'match' : 'unknown_document' });
    }
    if (bad) { sources.push(rep(false, [bad], r.sha)); continue; }
    const rv = reviews.get(x.trace_id) || { run: run ? summarizeRun(run.doc, run.sha, matches, registryDocs) : null, cases: [] };
    rv.cases.push({ case_id: c.case_id, run_id: c.run_id, gatehouse_trace_id: c.gatehouse_trace_id, draft_id: c.draft.draft_id, subject: c.draft.subject, question: c.draft.question, missing_requirements: c.draft.missing_requirements,
      status: 'PENDING_HUMAN_REVIEW', approval_status: 'NOT_APPROVED', sent_externally: false, ai_generated: true, note: c.note ?? null,
      authority: { changes_scope: false, changes_estimate: false, authorizes_labor_or_release: false, marks_bid_ready: false, requires_named_human: true }, evidence: ev, file: n, sha256: r.sha, assessment: NOT_AUDITED, integrity: { run_record: integrity, draft_matches_run_record: draftOk } });
    reviews.set(x.trace_id, rv); sources.push({ ...rep(true, undefined, r.sha), trace_id: c.case_id });
  }
  for (const rv of reviews.values()) rv.cases.sort((a, b) => (a.draft_id < b.draft_id ? -1 : 1));
  return { reviews, sources, runs };
}

/** Gatehouse's own document registry (doc id, sha256, page count) used to check what a case cites. Null if unavailable. */
export async function loadRegistryDocs(): Promise<{ doc_id: string; sha256: string; pages: number }[] | null> {
  try {
    const d = JSON.parse(await readFile(path.join(process.env.DP001_DIR || '', 'document_registry.json'), 'utf8'));
    const docs = (Array.isArray(d?.documents) ? d.documents : []).filter((x: any) => isStr(x?.doc_id, 120) && HEX64.test(String(x?.sha256)) && Number.isInteger(x?.pages));
    return docs.map((x: any) => ({ doc_id: x.doc_id, sha256: x.sha256, pages: x.pages }));
  } catch { return null; }
}

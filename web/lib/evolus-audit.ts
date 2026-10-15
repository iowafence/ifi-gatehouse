// Server-only, READ-ONLY reader for ADDITIVE independent-audit records (gatehouse-independent-audit.v1), e.g. LOOM's semantic review of an Evolus run.
// An audit is an ASSESSMENT stored beside the original evidence. It never edits, replaces or re-labels the run record, the validator result, the case or the trace,
// it is never a human approval or rejection, and it can only make a case LESS available (flag it), never approve it. If an audit exists for a run but cannot be verified,
// the run's cases are shown as NOT CLEARED, not as if no audit existed (fail safe). Nothing here writes, calls the engine or touches the network.
// TRUST BOUNDARY: an audit file is never trusted for what it says about itself (including its own sha256). It is accepted only if its exact bytes equal the digest pinned in the
// RELEASE MANIFEST (web/lib/audit-manifest.ts, compiled into the application release, held outside the mutable audit-data directory) and its dispositions equal the manifest's pinned policy.
// The manifest authenticates WHICH BYTES the release shipped; it is not a signature and does not prove authorship (see docs/HOSTING.md).
import { readFile, readdir, stat } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import type { Execution, SourceReport } from './flight-recorder.ts';
import type { Review } from './evolus-cases.ts';

/* eslint-disable @typescript-eslint/no-explicit-any */
const HEX64 = /^[0-9a-f]{64}$/;
const DISPOSITIONS = ['SUPPORTED', 'FLAGGED_UNSUPPORTED_BY_CONTROLLING_EVIDENCE'] as const;
type Disposition = (typeof DISPOSITIONS)[number];
const SCOPES = ['G2', 'G3', 'general'] as const;
const SCOPE_STATUS = ['UNRESOLVED', 'SPECIFIED'] as const;
const ROLES = ['supports', 'controlling_contradicts', 'context', 'cited_by_original'] as const;
const norm = (s: string) => s.replace(/[’‘]/g, "'").replace(/[“”]/g, '"').replace(/[–—]/g, '-').replace(/\s+/g, ' ').trim().toLowerCase();
const isStr = (v: unknown, max = 2000): v is string => typeof v === 'string' && v.length > 0 && v.length <= max;
const keysEq = (o: any, keys: string[]) => !!o && typeof o === 'object' && !Array.isArray(o) && Object.keys(o).sort().join() === [...keys].sort().join();

export type AuditState = 'SUPPORTED' | 'FLAGGED' | 'NOT_AUDITED' | 'AUDIT_UNVERIFIABLE';
export type AuditEvidence = { excerpt_id: string | null; applies_to: string | null; doc_id: string; page: number; doc_sha256: string; locator: string; quote: string; role: string; controlling_document: boolean;
  registry: 'match' | 'unknown_document'; matches_run_package: boolean | null };
export type ScopeFinding = { item: string; label: string; status: 'UNRESOLVED' | 'SPECIFIED'; value: string | null; basis: string; evidence_excerpt_ids: string[] };
export type ProposedClarification = { clarification_id: string; topic: string; derived_from_issue: string; status: 'PROPOSED_NOT_APPROVED'; approved: false; sent: false; evolus_generated: false; requires_named_human_review: true;
  authorship_kind: string; authorship: string; question: string; unresolved_requirements: string[]; excluded_because_specified: string[]; evidence_excerpt_ids: string[] };
export type PinInfo = { manifest_schema: string; release: string; audit_sha256: string; report_file: string; report_sha256: string; report_verified: true; superseded: { audit_id: string; file: string; sha256: string }[]; supersedes: string | null };
/** The release-pinned trust anchor. Compiled into the release; never read from the audit directory and never recomputed at load time. */
export type ManifestRun = { run_id: string; run_sha256: string; trace_id: string; trace_sha256: string; execution_id: string;
  cases: Record<string, { case_id: string; case_sha256: string }>; loom_report: { file: string; sha256: string };
  audits: { audit_id: string; file: string; sha256: string; status: 'ACTIVE' | 'SUPERSEDED' }[];
  policy: { issues: Record<string, { draft_id: string | null; disposition: Disposition }>; cases: Record<string, Disposition>; scope_findings: Record<string, 'UNRESOLVED' | 'SPECIFIED'>; proposed_clarifications: string[] } };
export type AuditManifest = { schema: 'gatehouse-audit-release-manifest.v1'; release: string; runs: ManifestRun[] };
export type Assessment = { state: AuditState; actionable: boolean; label: string; summary: string | null; verification_note: string | null; evidence: AuditEvidence[] };
export type AuditInfo = { audit_id: string; auditor: string; auditor_role: string; reported_verdict: string | null; source_kind: string; source_description: string; created_utc: string; file: string; sha256: string;
  is_human_decision: false; human_authorization_status: 'NONE_RECORDED'; pinned: PinInfo; scope_findings: ScopeFinding[]; proposed_clarifications: ProposedClarification[]; drops: { count: number; explanation: string; original_reason_code: string; entries: string[]; verified_against_run_record: boolean } | null };

const UNVERIFIABLE: Assessment = { state: 'AUDIT_UNVERIFIABLE', actionable: false, label: 'AUDIT RECORD COULD NOT BE VERIFIED', summary: 'An independent audit record exists for this run but did not verify against the stored evidence, so this item is not cleared for use.', verification_note: null, evidence: [] };

/** Strict structural validation of an audit record (schema v2). Returns reasons; empty = well-formed. */
export function checkAuditShape(a: any, stem: string): string[] {
  const e: string[] = [];
  const TOP = ['schema', 'audit_id', 'supersedes', 'created_utc', 'additive', 'is_human_decision', 'auditor', 'source', 'human_authorization', 'subject', 'dispositions', 'scope_findings', 'proposed_clarifications', 'drops_correction', 'verification'];
  if (!a || typeof a !== 'object' || Array.isArray(a)) return ['not a JSON object'];
  const extra = Object.keys(a).filter(k => !TOP.includes(k)); if (extra.length) e.push(`unexpected field(s): ${extra.slice(0, 5).join(', ')}`);
  if (a.schema !== 'gatehouse-independent-audit.v2') e.push('schema must be gatehouse-independent-audit.v2');
  if (a.audit_id !== stem || !/^AUDIT-GH-RUN-[0-9a-f]{12}-\d{1,3}$/.test(String(a.audit_id))) e.push('audit_id does not match the file name');
  if (a.supersedes != null && !/^AUDIT-GH-RUN-[0-9a-f]{12}-\d{1,3}$/.test(String(a.supersedes))) e.push('supersedes is not an audit id');
  if (!isStr(a.created_utc, 40) || Number.isNaN(Date.parse(a.created_utc))) e.push('created_utc is not a timestamp');
  if (a.additive !== true) e.push('additive must be true');
  if (a.is_human_decision !== false) e.push('is_human_decision must be false: an audit is never a human decision');
  if (!keysEq(a.human_authorization, ['status', 'note']) || a.human_authorization.status !== 'NONE_RECORDED') e.push('human_authorization must be exactly NONE_RECORDED');
  if (!a.auditor || !isStr(a.auditor.name, 80) || !isStr(a.auditor.role, 120) || (a.auditor.reported_verdict != null && !isStr(a.auditor.reported_verdict, 160))) e.push('auditor {name, role} missing');
  if (!a.source || !isStr(a.source.kind, 40) || !isStr(a.source.description, 1500) || !isStr(a.source.report_file, 200) || !HEX64.test(String(a.source.report_sha256)) || Object.keys(a.source).length !== 4) e.push('an explicit source {kind, description, report_file, report_sha256} is required');
  const s = a.subject;
  if (!s || !isStr(s.gatehouse_trace_id, 120) || !/^GH-RUN-[0-9a-f]{12}$/.test(String(s.run_id)) || !HEX64.test(String(s.run_sha256)) || !HEX64.test(String(s.trace_sha256)) || !isStr(s.original_validator_status, 80) || s.original_validator_status_preserved !== true) e.push('subject must bind trace id, run id, run sha256, trace sha256 and the original validator status');
  const evIds = new Set<string>();
  if (!Array.isArray(a.dispositions) || !a.dispositions.length || a.dispositions.length > 30) e.push('dispositions missing');
  else for (const d of a.dispositions) {
    if (!d || !/^[A-Za-z0-9_-]{1,20}$/.test(String(d.issue_id)) || !(DISPOSITIONS as readonly string[]).includes(d.disposition) || !(SCOPES as readonly string[]).includes(d.subject_scope) || !isStr(d.summary, 2500) || (d.verification_note != null && !isStr(d.verification_note, 3000))) { e.push(`disposition ${String(d?.issue_id).slice(0, 20)} is malformed`); continue; }
    if ((d.case_id == null) !== (d.case_sha256 == null) || (d.case_id != null && (!/^GH-CASE-[0-9a-f]{12}$/.test(String(d.case_id)) || !HEX64.test(String(d.case_sha256))))) e.push(`disposition ${d.issue_id}: bad case binding`);
    if (!Array.isArray(d.evidence) || !d.evidence.length || d.evidence.length > 12) { e.push(`disposition ${d.issue_id}: evidence missing`); continue; }
    for (const x of d.evidence) {
      if (!x || !isStr(x.quote, 1500) || !isStr(x.doc_id, 120) || !HEX64.test(String(x.doc_sha256)) || !Number.isInteger(x.page) || x.page < 1 || !isStr(x.locator, 240) || !(ROLES as readonly string[]).includes(x.role) || !(SCOPES as readonly string[]).includes(x.applies_to) || typeof x.controlling_document !== 'boolean' || (x.excerpt_id != null && !/^X-[0-9a-f]{12}$/.test(String(x.excerpt_id)))) { e.push(`disposition ${d.issue_id}: malformed evidence entry`); continue; }
      if (x.excerpt_id) evIds.add(x.excerpt_id);
      // scope guard: a G2-only passage may be context, but cannot be the support or the contradiction for a G3 conclusion (and vice versa) without a general rule
      if ((x.role === 'supports' || x.role === 'controlling_contradicts') && x.applies_to !== 'general' && x.applies_to !== d.subject_scope) e.push(`disposition ${d.issue_id}: evidence for ${x.applies_to} cannot be ${x.role === 'supports' ? 'support' : 'a contradiction'} for a ${d.subject_scope} conclusion`);
    }
    if (d.disposition === 'FLAGGED_UNSUPPORTED_BY_CONTROLLING_EVIDENCE' && !d.evidence.some((x: any) => x?.role === 'controlling_contradicts')) e.push(`disposition ${d.issue_id}: a flag must cite controlling evidence`);
  }
  const inEv = (ids: unknown) => Array.isArray(ids) && ids.length > 0 && ids.length <= 12 && ids.every(i => typeof i === 'string' && evIds.has(i));
  if (!Array.isArray(a.scope_findings) || !a.scope_findings.length || a.scope_findings.length > 10) e.push('scope_findings missing');
  else for (const f of a.scope_findings) if (!keysEq(f, ['item', 'label', 'status', 'value', 'basis', 'evidence_excerpt_ids']) || !/^[A-Z0-9_]{3,40}$/.test(String(f.item)) || !isStr(f.label, 120) || !(SCOPE_STATUS as readonly string[]).includes(f.status)
    || (f.status === 'SPECIFIED') !== isStr(f.value, 300) || (f.status === 'UNRESOLVED' && f.value !== null) || !isStr(f.basis, 1500) || !inEv(f.evidence_excerpt_ids)) e.push(`scope finding ${String(f?.item).slice(0, 40)} is malformed`);
  if (!Array.isArray(a.proposed_clarifications) || a.proposed_clarifications.length > 5) e.push('proposed_clarifications must be a list');
  else for (const c of a.proposed_clarifications) if (!keysEq(c, ['clarification_id', 'topic', 'derived_from_issue', 'status', 'approved', 'sent', 'evolus_generated', 'requires_named_human_review', 'authorship', 'question', 'unresolved_requirements', 'excluded_because_specified', 'evidence_excerpt_ids'])
    || !/^PC-GH-RUN-[0-9a-f]{12}-[A-Z0-9-]{3,40}$/.test(String(c.clarification_id)) || !isStr(c.topic, 160) || !/^[A-Za-z0-9_-]{1,20}$/.test(String(c.derived_from_issue)) || c.status !== 'PROPOSED_NOT_APPROVED' || c.approved !== false || c.sent !== false || c.evolus_generated !== false || c.requires_named_human_review !== true
    || !keysEq(c.authorship, ['kind', 'description']) || c.authorship.kind !== 'DRAFTED_BY_ANVIL_1_FROM_LOOM_RECOMMENDATION' || !isStr(c.authorship.description, 800) || !isStr(c.question, 2000)
    || !Array.isArray(c.unresolved_requirements) || !c.unresolved_requirements.length || !c.unresolved_requirements.every((r: unknown) => isStr(r, 300)) || !Array.isArray(c.excluded_because_specified) || !c.excluded_because_specified.every((r: unknown) => isStr(r, 400)) || !inEv(c.evidence_excerpt_ids)) e.push(`proposed clarification ${String(c?.clarification_id).slice(0, 60)} is malformed or claims approval, sending or Evolus authorship`);
  const dc = a.drops_correction; if (dc != null && (!Number.isInteger(dc.count) || !isStr(dc.explanation, 1500) || !isStr(dc.original_reason_code, 100) || !Array.isArray(dc.entries) || dc.entries.length > 30)) e.push('drops_correction is malformed');
  return e.slice(0, 15);
}

/** Structural validation of the release manifest. It is compiled into the release, but a malformed one fails closed all the same. */
export function checkManifestShape(m: any): string[] {
  const e: string[] = []; const H = (v: unknown) => HEX64.test(String(v)); const D = (v: unknown) => v === 'SUPPORTED' || v === 'FLAGGED_UNSUPPORTED_BY_CONTROLLING_EVIDENCE';
  if (!m || typeof m !== 'object' || m.schema !== 'gatehouse-audit-release-manifest.v1' || !isStr(m.release, 80) || !Array.isArray(m.runs) || m.runs.length > 20 || Object.keys(m).length !== 3) return ['manifest schema, release or runs missing'];
  const seen = new Set<string>();
  for (const r of m.runs) {
    const w = String(r?.run_id); if (!r || !/^GH-RUN-[0-9a-f]{12}$/.test(w) || !H(r.run_sha256) || !isStr(r.trace_id, 120) || !H(r.trace_sha256) || !isStr(r.execution_id, 120) || !r.loom_report || !isStr(r.loom_report.file, 200) || !H(r.loom_report.sha256)) { e.push(`${w}: run binding malformed`); continue; }
    if (seen.has(w)) e.push(`${w}: duplicate run entry`); seen.add(w);
    if (!r.cases || typeof r.cases !== 'object' || !Object.keys(r.cases).length || !Object.values(r.cases).every((c: any) => /^GH-CASE-[0-9a-f]{12}$/.test(String(c?.case_id)) && H(c?.case_sha256))) e.push(`${w}: case bindings malformed`);
    const p = r.policy; if (!p || !p.issues || !p.cases || !p.scope_findings || !Array.isArray(p.proposed_clarifications)) { e.push(`${w}: policy missing`); continue; }
    for (const [iid, v] of Object.entries<any>(p.issues)) { if (!D(v?.disposition) || !(v.draft_id === null || typeof v.draft_id === 'string')) e.push(`${w}: policy for ${iid} malformed`); else if (v.draft_id && p.cases[v.draft_id] !== v.disposition) e.push(`${w}: policy for ${iid} and ${v.draft_id} disagree`); }
    for (const [did, v] of Object.entries<any>(p.cases)) if (!D(v) || !r.cases[did]) e.push(`${w}: case policy for ${did} malformed or unbound`);
    if (!Object.values<any>(p.scope_findings).every(v => v === 'UNRESOLVED' || v === 'SPECIFIED')) e.push(`${w}: scope policy malformed`);
    if (!Array.isArray(r.audits) || !r.audits.length) { e.push(`${w}: no audit entries`); continue; }
    if (r.audits.filter((a: any) => a?.status === 'ACTIVE').length !== 1) e.push(`${w}: exactly one ACTIVE audit is required`);
    for (const a of r.audits) if (!a || !new RegExp(`^AUDIT-${w}-\\d{1,3}$`).test(String(a.audit_id)) || a.file !== `${a.audit_id}.json` || !H(a.sha256) || (a.status !== 'ACTIVE' && a.status !== 'SUPERSEDED')) e.push(`${w}: audit entry malformed`);
  }
  const files = m.runs.flatMap((r: any) => (r?.audits ?? []).map((a: any) => a?.file)), shas = m.runs.flatMap((r: any) => (r?.audits ?? []).map((a: any) => a?.sha256));
  if (new Set(files).size !== files.length || new Set(shas).size !== shas.length) e.push('duplicate audit file or digest in the manifest');
  return e.slice(0, 12);
}

/** The package the model was given (excerpt id -> doc, page, text), read from the run record's own stored input. */
export function packageExcerpts(runDoc: any): Map<string, { doc_id: string; page: number; text: string }> {
  const m = new Map<string, { doc_id: string; page: number; text: string }>();
  try { const inp = typeof runDoc?.evolus_execution?.input === 'string' ? JSON.parse(runDoc.evolus_execution.input) : runDoc?.evolus_execution?.input;
    for (const x of (Array.isArray(inp?.excerpts) ? inp.excerpts : []).slice(0, 400)) if (isStr(x?.excerpt_id, 40) && isStr(x?.text, 5000)) m.set(x.excerpt_id, { doc_id: x.doc_id, page: x.page, text: x.text }); } catch { /* none */ }
  return m;
}

/** Adds audit assessments to the reviews. Only an audit whose exact bytes are pinned by the release manifest, and whose dispositions equal the manifest's policy, can clear anything.
 *  Anything else (no manifest entry, substituted bytes, duplicate, wrong run/case/trace bytes, policy mismatch, altered LOOM report) leaves its run's cases NOT CLEARED. */
export async function attachAudits(reviews: Map<string, Review>, executions: Execution[], runs: Map<string, { doc: any; sha: string }>,
  registryDocs: { doc_id: string; sha256: string; pages: number }[] | null, sources: SourceReport[], manifest: AuditManifest, releaseDirArg?: string): Promise<void> {
  const dir = process.env.GATEHOUSE_AUDIT_DIR || (process.env.DP001_DIR ? path.join(process.env.DP001_DIR, 'independent_audits') : '');
  const releaseDir = releaseDirArg ?? process.env.GATEHOUSE_RELEASE_DIR ?? path.join(process.cwd(), 'release');
  let names: string[] = []; if (dir) { try { names = (await readdir(dir)).sort(); } catch { names = []; } }
  const byTrace = new Map(executions.map(x => [x.trace_id, x]));
  const traceByRun = new Map<string, string>(); for (const [tid, rv] of reviews) if (rv.run) traceByRun.set(rv.run.run_id, tid);
  const mErr = checkManifestShape(manifest);
  const mRuns = new Map<string, ManifestRun>(mErr.length ? [] : manifest.runs.map(r => [r.run_id, r]));
  const unverifiable = new Set<string>(); const superseded = new Map<string, { audit_id: string; file: string; sha256: string }[]>(); const accepted = new Map<string, SourceReport>();
  const files = names.filter(n => /^AUDIT-GH-RUN-[0-9a-f]{12}-\d{1,3}\.json$/.test(n)).slice(0, 40);
  const bytes = new Map<string, { buf: Buffer; sha: string } | null>();
  for (const n of files) { try { const f = path.join(dir, n); if ((await stat(f)).size > 400_000) { bytes.set(n, null); continue; } const buf = await readFile(f); bytes.set(n, { buf, sha: createHash('sha256').update(buf).digest('hex') }); } catch { bytes.set(n, null); } }
  const shaCount = new Map<string, number>(); for (const b of bytes.values()) if (b) shaCount.set(b.sha, (shaCount.get(b.sha) ?? 0) + 1);
  for (const n of files) {
    const b = bytes.get(n) ?? null; const sha = b?.sha; const rep = (accepted: boolean, errors?: string[]): SourceReport => ({ name: n, role: 'audit', accepted, errors, sha256: sha });
    const runId = n.slice('AUDIT-'.length, 'AUDIT-GH-RUN-e5bbcecef551'.length); // attribution comes from the FILE NAME, never from the untrusted content
    const mr = mRuns.get(runId); const entry = mr?.audits.find(a => a.file === n); const tid = mr?.trace_id ?? traceByRun.get(runId); const x = tid ? byTrace.get(tid) : undefined; const rv = tid && x ? reviews.get(tid) : undefined;
    const fail = (errs: string[]) => { sources.push(rep(false, errs)); if (rv) unverifiable.add(tid!); };
    if (mErr.length) { fail([`the release audit manifest is invalid, so no audit can be trusted (${mErr[0]})`]); continue; }
    if (!mr || !entry) { fail(['not pinned in the release audit manifest (unregistered or substituted audit record); it cannot clear anything']); continue; }
    if (!x) continue; // a pinned audit applies only to an execution that is present; it ships with the repository, so its absence is not an error
    if (!b) { fail(['unreadable or too large']); continue; }
    if ((shaCount.get(b.sha) ?? 0) > 1) { fail(['duplicate audit record: identical bytes appear in more than one audit file']); continue; }
    if (b.sha !== entry.sha256) { fail([`audit bytes differ from the digest pinned in the release manifest (pinned ${entry.sha256.slice(0, 12)}…, found ${b.sha.slice(0, 12)}…)`]); continue; }
    if (entry.status === 'SUPERSEDED') { sources.push({ ...rep(true), trace_id: entry.audit_id }); (superseded.get(tid!) ?? superseded.set(tid!, []).get(tid!)!).push({ audit_id: entry.audit_id, file: n, sha256: b.sha }); continue; }
    let doc: any; try { doc = JSON.parse(b.buf.toString('utf8')); } catch { fail(['not JSON']); continue; }
    const errs = checkAuditShape(doc, n.replace(/\.json$/, '')); if (errs.length) { fail(errs); continue; }
    if (!rv || !rv.run) { fail(['the run record for this execution is not available, so the audit cannot be verified against it']); continue; }
    const run = runs.get(rv.run.run_id)!; const s = doc.subject; const bad: string[] = [];
    // 1) the audit must name exactly what the PINNED manifest names, and the evidence on disk must be what the manifest pins
    if (doc.audit_id !== entry.audit_id) bad.push('audit id differs from the manifest');
    if (s.run_id !== mr.run_id || s.gatehouse_trace_id !== mr.trace_id || s.execution_id !== mr.execution_id) bad.push('audit names a different run, trace or execution than the manifest pins');
    if (s.run_sha256 !== mr.run_sha256 || s.trace_sha256 !== mr.trace_sha256) bad.push('audit run/trace digest differs from the manifest');
    if (run.sha !== mr.run_sha256 || x.sha256 !== mr.trace_sha256) bad.push('the stored run record or trace file differs from the bytes the release manifest pins');
    if (s.run_id !== rv.run.run_id) bad.push('audit names a different run'); if (s.run_sha256 !== run.sha) bad.push('audit is bound to a different run record (sha256 mismatch)');
    if (s.trace_sha256 !== x.sha256) bad.push('audit is bound to a different trace file (sha256 mismatch)'); if (s.original_validator_status !== rv.run.status) bad.push('audit records a different original validator status than the run record');
    const prior = mr.audits.filter(a => a.status === 'SUPERSEDED').map(a => a.audit_id); if ((doc.supersedes ?? null) !== (prior.length ? prior[prior.length - 1] : null)) bad.push('audit supersedes a record the manifest does not name');
    // 2) the LOOM report the audit cites must be the pinned one, and the bundled copy must still match it
    if (doc.source.report_sha256 !== mr.loom_report.sha256 || doc.source.report_file !== mr.loom_report.file) bad.push('the audit cites a LOOM report other than the one the release pins');
    try { const rb = await readFile(path.join(releaseDir, mr.loom_report.file)); if (createHash('sha256').update(rb).digest('hex') !== mr.loom_report.sha256) bad.push('the bundled LOOM re-check report differs from the digest the release pins'); }
    catch { bad.push('the bundled LOOM re-check report is missing, so it cannot be verified'); }
    // 3) the dispositions must equal the pinned release policy exactly (no more, no fewer, no different)
    const pol = mr.policy; const got = new Map<string, any>(doc.dispositions.map((d: any) => [d.issue_id, d]));
    if (got.size !== doc.dispositions.length) bad.push('duplicate issue disposition');
    if ([...got.keys()].sort().join() !== Object.keys(pol.issues).sort().join()) bad.push('the audit covers different issues than the release policy');
    for (const [iid, p] of Object.entries(pol.issues)) { const d = got.get(iid); if (!d) continue;
      if (d.disposition !== p.disposition) bad.push(`${iid}: disposition ${d.disposition} is inconsistent with the pinned release policy (${p.disposition})`);
      if ((d.draft_id ?? null) !== p.draft_id) bad.push(`${iid}: bound to a different draft than the release policy`);
      if (p.draft_id) { const pc = mr.cases[p.draft_id]; if (!pc || d.case_id !== pc.case_id || d.case_sha256 !== pc.case_sha256) bad.push(`${iid}: case binding differs from the manifest`); if (pol.cases[p.draft_id] !== d.disposition) bad.push(`${p.draft_id}: case disposition inconsistent with the pinned release policy`); } }
    const sf = Object.fromEntries(doc.scope_findings.map((f: any) => [f.item, f.status])); if (JSON.stringify(Object.entries(sf).sort()) !== JSON.stringify(Object.entries(pol.scope_findings).sort())) bad.push('scope findings differ from the pinned release policy');
    if (doc.proposed_clarifications.map((c: any) => c.clarification_id).sort().join() !== [...pol.proposed_clarifications].sort().join()) bad.push('proposed clarifications differ from the pinned release policy');
    // 4) the original bindings (run package, case bytes, registry)
    const pk = packageExcerpts(run.doc); const issues = new Map(rv.run.issues.map(i => [i.issue_id, i])); const byDraft = new Map(rv.cases.map(c => [c.draft_id, c]));
    const out: { issue_id: string; draft_id: string | null; a: Assessment }[] = [];
    for (const d of doc.dispositions) {
      if (!issues.has(d.issue_id)) { bad.push(`${d.issue_id} is not an issue in the run record`); continue; }
      const c = d.draft_id ? byDraft.get(d.draft_id) : null;
      if (d.draft_id != null) { if (!c) { bad.push(`${d.draft_id}: no such case under this execution`); continue; } if (c.case_id !== d.case_id || c.sha256 !== d.case_sha256) { bad.push(`${d.draft_id}: audit is bound to different case bytes`); continue; } }
      const ev: AuditEvidence[] = [];
      for (const q of d.evidence) {
        const reg = registryDocs?.find(r => r.doc_id === q.doc_id) ?? null;
        if (reg && reg.sha256 !== q.doc_sha256) { bad.push(`${q.doc_id}: document hash differs from Gatehouse's registry`); continue; }
        if (reg && q.page > reg.pages) { bad.push(`${q.doc_id}: page ${q.page} is beyond the document`); continue; }
        let mp: boolean | null = null;
        if (q.excerpt_id) { const p = pk.get(q.excerpt_id); mp = !!p && p.doc_id === q.doc_id && p.page === q.page && norm(p.text).includes(norm(q.quote)); if (!mp) bad.push(`${q.excerpt_id}: the quoted text is not in the package recorded in the run record`); }
        ev.push({ excerpt_id: q.excerpt_id ?? null, applies_to: q.applies_to ?? null, doc_id: q.doc_id, page: q.page, doc_sha256: q.doc_sha256, locator: q.locator, quote: q.quote, role: q.role, controlling_document: q.controlling_document, registry: reg ? 'match' : 'unknown_document', matches_run_package: mp });
      }
      const flagged = d.disposition !== 'SUPPORTED';
      out.push({ issue_id: d.issue_id, draft_id: d.draft_id ?? null, a: { state: flagged ? 'FLAGGED' : 'SUPPORTED', actionable: !flagged, label: flagged ? 'FLAGGED — UNSUPPORTED BY CONTROLLING EVIDENCE' : 'SUPPORTED', summary: d.summary, verification_note: d.verification_note ?? null, evidence: ev } });
    }
    const dropped: any[] = Array.isArray(run.doc.dropped_unverifiable_excerpts) ? run.doc.dropped_unverifiable_excerpts : [];
    const regIds = new Set((registryDocs ?? []).map(r => r.doc_id));
    const allUnregistered = !!registryDocs && dropped.length > 0 && dropped.every(q => typeof q?.doc_id === 'string' && !regIds.has(q.doc_id));
    let drops: AuditInfo['drops'] = null; const dc = doc.drops_correction;
    if (dc) { if (dc.count !== dropped.length) bad.push('drops_correction count differs from the run record'); else if (!allUnregistered) bad.push('drops_correction: the dropped entries in the run record are not all unregistered documents');
      else drops = { count: dc.count, explanation: dc.explanation, original_reason_code: dc.original_reason_code, entries: dc.entries.map((q: any) => String(q?.text ?? '').slice(0, 200)), verified_against_run_record: true }; }
    if (bad.length) { fail(bad.slice(0, 12)); continue; }
    const okSrc: SourceReport = { ...rep(true), trace_id: doc.audit_id }; sources.push(okSrc); accepted.set(tid!, okSrc);
    rv.audit = { audit_id: doc.audit_id, auditor: doc.auditor.name, auditor_role: doc.auditor.role, reported_verdict: doc.auditor.reported_verdict ?? null, source_kind: doc.source.kind, source_description: doc.source.description, created_utc: doc.created_utc, file: n, sha256: b.sha,
      is_human_decision: false, human_authorization_status: 'NONE_RECORDED',
      pinned: { manifest_schema: manifest.schema, release: manifest.release, audit_sha256: b.sha, report_file: mr.loom_report.file, report_sha256: mr.loom_report.sha256, report_verified: true, superseded: [], supersedes: doc.supersedes ?? null },
      scope_findings: doc.scope_findings.map((f: any) => ({ ...f })),
      proposed_clarifications: doc.proposed_clarifications.map((c: any) => ({ ...c, authorship_kind: c.authorship.kind, authorship: c.authorship.description })), drops };
    for (const o of out) { const i = issues.get(o.issue_id); if (i) i.assessment = o.a; if (o.draft_id) { const c = byDraft.get(o.draft_id); if (c) c.assessment = o.a; } }
  }
  // a pinned audit that is absent from the audit directory is tampering or a deployment error: the run is NOT CLEARED, with the reason shown
  for (const mr of mErr.length ? [] : manifest.runs) { const x = byTrace.get(mr.trace_id), rv = x ? reviews.get(mr.trace_id) : undefined; if (!x || !rv || !rv.run) continue;
    for (const a of mr.audits) if (!files.includes(a.file)) { sources.push({ name: a.file, role: 'audit', accepted: false, errors: ['a pinned audit record is missing from the audit directory'] }); unverifiable.add(mr.trace_id); } }
  for (const [tid, list] of superseded) { const rv = reviews.get(tid); if (rv?.audit) rv.audit.pinned.superseded = list; }
  // any failure for a run revokes everything for that run, including a verified record: with an unpinned or altered sibling present, nothing clears
  for (const tid of unverifiable) { const rv = reviews.get(tid); if (!rv) continue; const ok = accepted.get(tid); if (ok) { ok.accepted = false; ok.errors = ['verified on its own, but revoked: another audit file for this run failed verification, so nothing is cleared']; } rv.audit = undefined; for (const c of rv.cases) c.assessment = UNVERIFIABLE; for (const i of rv.run?.issues ?? []) i.assessment = UNVERIFIABLE; rv.audit_unverifiable = true; }
}

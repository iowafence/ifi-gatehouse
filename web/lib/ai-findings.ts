// Server-only AI Findings service. The ledger (dp001/ai_findings.json) is built OFFLINE from stored AMD outputs by amd_bridge/ledger.py with the experiment's own
// strict parser, PDF quotation verifier and spatial oracle. This module only (1) shows candidates beside the engine's real scope state, (2) records a human's
// accept / reject / defer, and (3) for an accepted, verified, SUPPORTED finding forwards ONE existing engine scope decision (scope/resolve, approve_inferred).
// An AI finding never authorizes Scope by itself, never supplies a value, and never touches pricing, crews or release digests. This module makes no AMD call.
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { canonical, sha } from './takeoff-service';
import { contradictionKind, RETRO_CONTRADICTION } from './contradiction';

/* eslint-disable @typescript-eslint/no-explicit-any */
type Raw = Record<string, any>;
export type Decision = { finding_id: string; decision: 'accept' | 'reject' | 'defer'; by: string; note: string; at: string; idempotency_key: string; outcome: 'scope_decision_recorded' | 'no_scope_change' | 'recorded_only'; scope_version_before: number | null; scope_version_after: number | null; engine_exception_id?: string };
type Store = { decisions: Map<string, Decision>; ledger: Map<string, { hash: string; response: any; status: number }> };
const g = globalThis as unknown as { __aiStore?: Map<string, Store>; __aiLedger?: { sha: string; data: Raw } };
const STORE = (g.__aiStore ||= new Map<string, Store>());
export const aiStoreFor = (sid: string, pid: string): Store => { const k = `${sid}:${pid}`; let s = STORE.get(k); if (!s) { s = { decisions: new Map(), ledger: new Map() }; STORE.set(k, s); if (STORE.size > 2000) STORE.delete(STORE.keys().next().value as string); } return s; };

export async function loadLedger(): Promise<{ sha: string; data: Raw } | null> {
  if (g.__aiLedger) return g.__aiLedger;
  try {
    const buf = await readFile(path.join(process.env.DP001_DIR || '', 'ai_findings.json'));
    const data = JSON.parse(buf.toString('utf8'));
    if (data?.schema !== 'gatehouse-ai-findings.v1') return null;
    return (g.__aiLedger = { sha: createHash('sha256').update(buf).digest('hex'), data });
  } catch { return null; }
}

function selectedBid(project: Raw): 'base' | 'alt' | null {
  const a = [...(project.audit || [])].reverse().find((x: Raw) => String(x.exception_id || '').includes('BID_SELECTION'));
  return !a ? null : a.option_id === 'base' ? 'base' : 'alt';
}

/** What accepting a finding would do, computed from the LIVE engine project. Nothing here mutates anything. */
export function previewFor(f: Raw, project: Raw): Raw {
  const sv = Number(project.scope_version ?? 0);
  const block = (reason: string, code: string) => ({ kind: 'blocked', code, reason, scope_changes: false, steps: [], scope_version_now: sv, scope_version_after: sv });
  if (f.provenance === 'SIMULATED_TEST_DATA') return block('SIMULATED TEST DATA is for interface and guard tests only; it cannot be accepted into scope.', f.conflict ? 'CONFLICT_WITH_CONTROLLING_DOCUMENT' : 'SIMULATED_NOT_ACCEPTABLE');
  if (f.conflict) return block(`Conflicts with a controlling document: ${f.conflict.rule}`, 'CONFLICT_WITH_CONTROLLING_DOCUMENT');
  const cls = f.classification;
  if (cls === 'CONTRADICTED_BY_DRAWING_EVIDENCE') return block(`AI CLAIM CONTRADICTED BY DRAWING EVIDENCE: ${contradictionKind(f) === 'retrospective' ? RETRO_CONTRADICTION : (f.verification?.why || 'the drawing\'s own vector geometry disagrees with the claim')} The model said "${f.uncertainty?.model_stated}". It cannot be accepted into scope.`, 'CONTRADICTED_BY_DRAWING_EVIDENCE');
  if (cls === 'FALSE_CANDIDATE') return block('Not a fence type tag (it is a keynote bubble). A false candidate is recorded for transparency and cannot be accepted.', 'NOT_A_FENCE_TYPE_TAG');
  if (cls === 'NOT_VERIFIED_VISUAL_ONLY') return block(`Gate-symbol relationships are NOT verified: a correct label position is not symbol comprehension, and a single/double-leaf prediction is never promoted to a gate fact. ${f.crop_clipped ? 'The crop also clips the gate symbol, so the prediction lacks visual support. ' : ''}Gate sizes and leaf counts come from Addendum 01 and the schedules.`, 'SYMBOL_NOT_VERIFIED');
  if (cls === 'VECTOR_CONFIRMED') return { kind: 'no_scope_change', reason: 'Confirmed against the drawing\'s vector geometry by the frozen pre-registered oracle. No scope fact depends on which element tag A points to, so accepting records supporting evidence only.', scope_changes: false, steps: [], scope_version_now: sv, scope_version_after: sv };
  if (cls === 'GATE_LABEL_POSITION_CONFIRMED' && !f.scope_link) return { kind: 'no_scope_change', reason: 'Label localization only (a repeat observation of a relationship already seen in Test 002), not symbol comprehension and not an independent new fact. Accepting records supporting evidence only; no scope fact changes.', scope_changes: false, steps: [], scope_version_now: sv, scope_version_after: sv };
  if (f.type === 'ai_unresolved') return block('The model reported it could not establish this; it stays an open question for a human.', 'AI_UNRESOLVED');
  if (f.type === 'spatial_association' && !f.scope_link) {
    const ph = f.post_hoc_reading;
    return block(ph?.disagrees_with_claim ? 'The PDF text layer cannot verify which fence element a type tag points to, and a post-hoc vector reading DISAGREES with the model\'s claim. Review required; it cannot be accepted.' : 'The PDF text layer cannot verify which fence element a type tag points to (spatial verification incomplete).', 'SPATIAL_NOT_VERIFIABLE');
  }
  if (f.type === 'text_fact') {
    const c = f.corroboration_on_dp001_ansi_b;
    if (f.verification.result !== 'VERIFIED_EXACT') return block('The quotation was not found in the PDF text layer (unverified). It cannot be accepted.', 'UNVERIFIED');
    if (c?.result !== 'EXACT') return block('Captured against a DIFFERENT source document (34×22 Rev 0); the same quotation does not appear on the registered ANSI B drawing, so it is not evidence for DP-001.', 'DIFFERENT_SOURCE_DOCUMENT');
    return { kind: 'no_scope_change', reason: 'Verified on the originating capture AND found verbatim on the ANSI B drawing. Accepting records it as supporting evidence only; no scope fact changes.', scope_changes: false, steps: [], scope_version_now: sv, scope_version_after: sv };
  }
  // spatial gate-tag side -> supports a human-prepared inferred gate station
  const link = f.scope_link;
  if (f.verification.verdict !== 'SIDE_CONFIRMED_BY_PDF_POSITION') return block('The side claim was not confirmed against the PDF label position.', 'UNVERIFIED');
  const sel = selectedBid(project);
  if (sel === 'alt') return block('This analysis covers the BASE BID plan view only; Alternate A-1 (view 2) has not been analyzed. Base and Alternate stay separate.', 'ANALYSIS_COVERS_BASE_ONLY');
  const exId = `EX-INFERRED_FACT_UNAPPROVED-${link.exception_path}`;
  const ex = (project.exceptions || []).find((e: Raw) => e.exception_id === exId && e.severity === 'blocking');
  if (!ex) return { kind: 'no_scope_change', reason: `The related scope fact (${link.exception_path}) has no open inferred-value exception in this project (already decided or not an open decision). Accepting records the evidence only; scope is unchanged.`, scope_changes: false, steps: [], scope_version_now: sv, scope_version_after: sv };
  const opt = (ex.candidate_resolutions || []).find((o: Raw) => o.option_id === 'approve_inferred');
  if (!opt) return block('The engine offers no approve-inferred option for this fact.', 'NO_ENGINE_ROUTE');
  const patch = (opt.patch || [])[0]; const val = patch?.value?.value;
  const down = project.status === 'needs_scope_review' ? [] : ['Labor decision', 'crew plan', 'estimate and proposal digest', 'takeoff review'];
  return { kind: 'engine_resolve', reason: 'Accepting asks the engine to record YOUR approval of the human-prepared value below, citing this finding. The AI supplied a plan side only, never the value.', scope_changes: true,
    steps: [{ route: 'POST scope/resolve', exception_id: exId, option_id: 'approve_inferred', fact_path: link.exception_path, value: val, unit: patch?.value?.unit ?? 'ft', plan_side: link.plan_side, gate: link.gate, value_source: 'HUMAN-PREPARED derivation (not from AI)' }],
    scope_version_now: sv, scope_version_after: sv + 1, voids: down, voids_note: down.length ? 'The engine voids these when scope changes.' : 'No Labor, crew-plan, estimate or release approval exists yet; the engine requires Scope to be clear before Labor, so nothing downstream can be affected.' };
}

export async function buildFindingsView(project: Raw, sid: string, pid: string) {
  const led = await loadLedger();
  if (!led) return { available: false, reason: 'AI findings ledger not installed' };
  const st = aiStoreFor(sid, pid); const d = led.data; const sv = Number(project.scope_version ?? 0);
  const findings = d.findings.map((f: Raw) => {
    const dec = st.decisions.get(f.finding_id) || null; const pv = previewFor(f, project);
    const accepted = dec?.decision === 'accept';
    const origin = accepted ? 'Human-approved' : f.origin_label;
    return { ...f, decision: dec, preview: { ...pv, digest: sha(canonical({ id: f.finding_id, k: pv.kind, s: pv.steps, v: sv })) }, display_origin: origin,
      can_accept: !dec || dec.decision === 'defer' ? pv.kind !== 'blocked' : false, final: !!dec && dec.decision !== 'defer' };
  });
  return { available: true, ledger_sha256: led.sha, schema: d.schema, live_calls: d.live_calls, doctrine: d.doctrine, target_document: d.target_document, states: d.states, attempts: d.attempts, accounting: d.accounting, execution_control_deviations: d.execution_control_deviations, test003_manifest: d.test003_manifest, scope_version: sv, selected: selectedBid(project), findings };
}

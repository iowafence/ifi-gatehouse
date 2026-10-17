// Attribution and provenance: every AGENT-FOUND label names a real run id and the model the provider returned, or reads NOT_REPORTED. Simulated fixtures are never in the
// product path. Run: npm run test:flight
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { buildScopeGates, attribution, NOT_REPORTED } from '../lib/scope-gates.ts';

const ROOT = new URL('../../', import.meta.url).pathname;
const ledger = JSON.parse(readFileSync(path.join(ROOT, 'dp001/ai_findings.json'), 'utf8'));
const draft = JSON.parse(readFileSync(path.join(ROOT, 'dp001/scope_draft.json'), 'utf8'));
const ex = (id: string, code: string): any => ({ exception_id: id, code, severity: 'blocking', blocking: true, question: `${code} ${id}`, status: 'open', evidence: [] });
const project = (): any => ({ status: 'needs_scope_review', scope_version: 1, audit: [], addenda: [], rfi_drafts: [], exceptions: [ex('EX-MISSING_VALUE-/gates/2/clear_width_ft', 'MISSING_VALUE'), ex('EX-INFERRED_FACT_UNAPPROVED-/fence_runs/0/length_lf', 'INFERRED_FACT_UNAPPROVED')] });
const agentFindings = (ai: any) => buildScopeGates(project(), draft, ai).flatMap(g => g.findings.filter(f => f.prov === 'AGENT-FOUND'));
const realRuns = new Set<string>(ledger.findings.filter((f: any) => f.provenance === 'REAL_AMD_OUTPUT' && f.run && typeof f.run === 'object').map((f: any) => f.run.run_id));
const realModels = new Set<string>(ledger.findings.filter((f: any) => f.provenance === 'REAL_AMD_OUTPUT').map((f: any) => f.model?.returned).filter(Boolean));

test('the shipped ledger contains no simulated finding', () => {
  assert.equal(ledger.findings.filter((f: any) => f.provenance !== 'REAL_AMD_OUTPUT').length, 0); assert.equal(ledger.accounting.simulated_findings, 0);
  assert.ok(!JSON.stringify(ledger).includes('SIM-g'));
});
test('every AGENT-FOUND label in the Scope Gate is built from real records: a real run id and a returned model, or NOT_REPORTED', () => {
  const fs = agentFindings(ledger); assert.ok(fs.length >= 3, 'G2, G3 and the inferred gate each carry a real-record finding');
  for (const f of fs) {
    assert.ok(typeof f.model === 'string');
    if (f.model === NOT_REPORTED) continue;
    if (/^configured .+, not reported by the run$/.test(f.model!)) continue;      // an Evolus run record names a configured model only
    for (const part of f.model!.split('; ')) { const m = /^(.+) · run (.+)$/.exec(part); assert.ok(m, `bad attribution: ${part}`); assert.ok(realModels.has(m![1]), `model ${m![1]} is not a returned model in the ledger`); assert.ok(realRuns.has(m![2]), `run ${m![2]} is not a run id in the ledger`); }
  }
});
test('a finding without a returned model or run id reads NOT_REPORTED, with no extra wording; Gemma is never assumed', () => {
  assert.equal(attribution([{ provenance: 'REAL_AMD_OUTPUT', model: { returned: 'DeepSeek-V4.1-Flash' } }]), NOT_REPORTED);      // no run id
  assert.equal(attribution([{ provenance: 'REAL_AMD_OUTPUT', run: { run_id: 'r1' }, model: {} }]), NOT_REPORTED);                  // no returned model
  assert.equal(attribution([]), NOT_REPORTED);
  assert.equal(attribution([{ provenance: 'SIMULATED_TEST_DATA', run: { run_id: 'r' }, model: { returned: 'Gemma-4-31B-IT' } }]), NOT_REPORTED);   // a simulated item never gets a model label
  assert.ok(agentFindings(ledger).every(f => !/Gemma/i.test(f.model || '')), 'the stored scope findings come from DeepSeek and Qwen records, not Gemma');
  assert.equal(attribution([{ provenance: 'REAL_AMD_OUTPUT', run: { run_id: 'r1' }, model: { returned: 'Qwen3.8-27B' } }]), 'Qwen3.8-27B · run r1');
});
test('a simulated fixture handed to the product code never appears in any gate', () => {
  const sim = { finding_id: 'FIXTURE-g3', provenance: 'SIMULATED_TEST_DATA', claim: { category: 'gate_symbol', key: 'G3', text: "G3 clear opening 12'-0\"" }, model: { returned: 'X' }, run: { run_id: 'SIMULATED' } };
  const out = JSON.stringify(buildScopeGates(project(), draft, { findings: [...ledger.findings, sim] }));
  assert.ok(!out.includes('FIXTURE-g3') && !out.includes('SIMULATED') && !out.includes("G3 clear opening 12'-0"));
});
test('the vector-geometry wording is accurate: label positions are checked against printed text positions, only fence-type leaders against vector geometry', () => {
  const inf = buildScopeGates(project(), draft, ledger).find(g => g.id === 'inferred')!.findings.find(f => f.prov === 'AGENT-FOUND')!;
  assert.match(inf.text, /8 gate-label positions confirmed against the PDF's printed text positions/);
  assert.match(inf.text, /1 fence-type leader confirmed against the drawing's vector geometry/); assert.match(inf.text, /2 contradicted/);
  assert.doesNotMatch(inf.text, /confirmed by the drawing's own vector geometry/);
});
test('no product source says "attribution pending" or names a simulated G2/G3 fixture', () => {
  const walk = (d: string): string[] => readdirSync(d).flatMap(n => { const p = path.join(d, n); return n === 'node_modules' || n === '.next' ? [] : statSync(p).isDirectory() ? walk(p) : /\.(ts|tsx)$/.test(n) ? [p] : []; });
  for (const f of [...walk(path.join(ROOT, 'web/app')), ...walk(path.join(ROOT, 'web/lib'))]) {
    const t = readFileSync(f, 'utf8'); assert.ok(!/attribution pending/i.test(t), `${f}: attribution pending`); assert.ok(!/SIM-g[23]/.test(t), `${f}: simulated G2/G3 fixture`);
  }
});

const drafts = [
  { case_id: 'GH-CASE-5131630cf9d1', run_id: 'GH-RUN-e5bbcecef551', subject: 'Gate G3 Clear Opening Width', question: 'What is the clear opening width for Gate G3?', status: 'PENDING_HUMAN_REVIEW', sent: false, gate: 'G3', model: 'configured Gemma-4-31B-IT, not reported by the run', assessment: 'SUPPORTED' },
  { case_id: 'GH-CASE-b661ad38637b', run_id: 'GH-RUN-e5bbcecef551', subject: 'Gate G3 Post and Footing Specifications', question: 'Please provide the post size and footing for Gate G3.', status: 'PENDING_HUMAN_REVIEW', sent: false, gate: 'G3', model: 'configured Gemma-4-31B-IT, not reported by the run', assessment: 'FLAGGED — UNSUPPORTED BY CONTROLLING EVIDENCE' }];
test('the two stored Evolus RFI drafts appear on G3 as AGENT-FOUND with run id, never sent, and the model exactly as the run record names it', () => {
  const g3 = buildScopeGates(project(), draft, { ...ledger, evolus_drafts: drafts }).find(g => g.id === 'g3')!;
  const ev = g3.findings.filter(f => f.prov === 'AGENT-FOUND' && /^Evolus RFI draft:/.test(f.text)); assert.equal(ev.length, 2);
  for (const f of ev) { assert.equal(f.model, 'configured Gemma-4-31B-IT, not reported by the run'); assert.match(f.note!, /GH-RUN-e5bbcecef551/); assert.match(f.note!, /Pending human review, never sent\./); }
  assert.match(ev[1].note!, /FLAGGED — UNSUPPORTED BY CONTROLLING EVIDENCE/);      // the audit's flag on the second draft is shown, not hidden
  const none = buildScopeGates(project(), draft, ledger).find(g => g.id === 'g3')!; assert.ok(!none.findings.some(f => /^Evolus RFI draft/.test(f.text)));
  // once the addendum resolves G3 the drafts stay as history and no longer claim to be pending
  const done = project(); done.exceptions = []; done.addenda = [{ status: 'APPLIED', filename: 'ADDENDUM_02.pdf', accepted_by: 'P' }];
  const after = buildScopeGates(done, draft, { ...ledger, evolus_drafts: drafts }, null).find(g => g.id === 'g3')!.findings.filter(f => /^Evolus RFI draft/.test(f.text));
  assert.ok(after.every(f => /answered by the accepted addendum/.test(f.note!) && !/Pending human review, never sent\./.test(f.note!)));
});
test('the Addendum 01 G2 correction stays on the Scope Gate: 12\'-0" double leaf, tagged ADDENDUM, with its citation', () => {
  const g2 = buildScopeGates(project(), draft, ledger).find(g => g.id === 'g2')!;
  const f = g2.findings.find(x => x.prov === 'ADDENDUM')!; assert.ok(f); assert.match(f.text, /12'-0" clear opening, double leaf/); assert.match(f.note!, /12'-0" double leaf/);
  assert.ok(f.src!.some(s => s.doc_id === 'dp001_addendum_01_ansi_b_pkg' && s.page === 1 && /Revise Gate G2/.test(String(s.excerpt))));
  assert.equal(g2.state, 'corrected'); assert.equal(g2.blocking, false);
});

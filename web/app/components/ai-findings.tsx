'use client';
// AI Findings: candidates from STORED (offline) AMD outputs, shown beside the human-prepared Scope draft. A finding is a claim plus a verification
// result computed by code against the PDF; it never authorizes Scope. A human accepts, rejects or defers; an accepted, verified, supported finding becomes
// ONE existing engine scope decision made by that human. Nothing here calls AMD, calculates money, or changes a price.
import {scopeStatus} from '@/lib/gate-status';
import {aiFindingsCallNote,type ConfiguredMode} from '@/lib/parse-mode';
import {useCallback, useEffect, useRef, useState} from 'react';
import {Bot, CircleAlert, LoaderCircle, RefreshCw, Search} from 'lucide-react';
import type {Project} from '@/lib/types';
import type {DocEntry, Target} from './dp001';
import {SelfDeclared} from './pricing';

/* eslint-disable @typescript-eslint/no-explicit-any */
const ANSI_B='dp001_ansi_b_v2_drawings';
const STATE_TEXT:Record<string,string>={NOT_ANALYZED:'Not analyzed',PROCESSING:'Processing',CANDIDATES_AVAILABLE:'Candidates available',PARTIALLY_VERIFIED:'Partially verified',REVIEW_REQUIRED:'Review required',FAILED:'Failed',TIMED_OUT:'Timed out'};
const short=(h?:string|null)=>h?`${h.slice(0,12)}…${h.slice(-6)}`:'—';

function verifyText(f:any):string{
  const v=f.verification;
  if(v.verdict==='CONFIRMED_BY_VECTOR_GEOMETRY')return 'VERIFIED · leader end confirmed against the PDF vector geometry';
  if(v.verdict==='CONTRADICTED_BY_VECTOR_GEOMETRY')return 'CONTRADICTED · the PDF vector geometry disagrees with the claim';
  if(v.verdict==='TAG_PRESENT_AND_ORDER_CONFIRMED_BY_PDF_POSITION')return 'VERIFIED · label position only (not symbol comprehension)';
  if(v.verdict==='NOT_VERIFIED_VISUAL_ONLY')return 'NOT VERIFIED · visual claim, no oracle can check it';
  if(v.verdict==='NOT_A_FENCE_TYPE_TAG')return 'FALSE CANDIDATE · not a fence type tag';
  if(f.type==='ai_unresolved')return 'NO CLAIM · the model reported it could not establish this';
  if(f.type==='spatial_association')return v.verdict==='SIDE_CONFIRMED_BY_PDF_POSITION'?'VERIFIED · tag label position confirmed against the PDF':v.verdict==='NOT_VERIFIABLE_FROM_PDF'?'NOT VERIFIABLE from the PDF text layer':v.verdict==='NOT_APPLICABLE'?'No claim to verify':v.verdict;
  return v.result==='VERIFIED_EXACT'?'VERIFIED · quotation found verbatim in the PDF text layer':'UNVERIFIED · quotation not found';
}
function jumpTarget(f:any):Target|null{
  const va=f.evidence?.vector_anchor;
  if(va&&f.origin_document.doc_id===ANSI_B){const r=va.rects;return {doc_id:ANSI_B,page:f.origin_document.page,rects:[r.tag_diamond,r.leader_end,r.target_element],rectKey:f.finding_id,cite:`AI finding ${f.finding_id}: outlined = (1) the tag diamond, (2) where its leader line ENDS, (3) ${va.terminal_description} (PDF vector geometry, not a model box). AI claim: ${f.claim.text}. Model confidence: ${f.uncertainty.model_stated}. Independent verification: ${f.verification.verdict}.`};}
  if(f.type==='spatial_association'||f.type==='ai_unresolved'){
    const rects=f.evidence?.pdf_text_rects_norm_page||[];
    return f.origin_document.doc_id===ANSI_B&&rects.length?{doc_id:ANSI_B,page:f.origin_document.page,rects,rectKey:f.finding_id,cite:`AI finding ${f.finding_id}: outlined = where the PDF text layer places the ${f.claim.key} label (PDF-derived, not a model box). AI claim: ${f.claim.text}`}:null;
  }
  if(f.provenance==='SIMULATED_TEST_DATA'){const r=f.evidence?.pdf_text_rects_norm_page||[];return r.length?{doc_id:ANSI_B,page:f.origin_document.page,excerpt:f.evidence.quotation,rects:r,rectKey:f.finding_id}:null;}
  const c=f.corroboration_on_dp001_ansi_b;
  return c?.result==='EXACT'?{doc_id:ANSI_B,page:c.page,excerpt:f.evidence.quotation,rects:c.rects_norm_page,rectKey:f.finding_id}:null;
}

export function AiFindings({project,review,docs,view,onRefresh,mode='RECORDED'}:{mode?:ConfiguredMode;project:Project;review?:unknown;docs:Record<string,DocEntry>;view:(t:Target)=>void;onRefresh:()=>void}){
  // A finding labelled "Unresolved / RFI required" was about G3; once the accepted addendum resolves G3 it is history, not a pending item.
  const g3Done=scopeStatus(project,review as never).g3.state==='resolved';
  const origin=(o:string)=>g3Done&&/RFI required/i.test(o)?'Was unresolved (history): resolved by the accepted addendum':o;
  const [data,setData]=useState<any>(null);const [err,setErr]=useState('');const [sel,setSel]=useState<string|null>(null);
  const [by,setBy]=useState('');const [note,setNote]=useState('');const [busy,setBusy]=useState(false);const [msg,setMsg]=useState<{id:string;t:string}|null>(null);
  const pending=useRef<{fp:string;key:string}|null>(null);
  const load=useCallback(async()=>{
    try{const r=await fetch('/api/demo/ai-findings',{cache:'no-store'});const b=await r.json();if(!r.ok)throw new Error(b.error||`HTTP ${r.status}`);setData(b);setErr('');}
    catch(e){setErr(e instanceof Error?e.message:'AI findings unavailable');}
  },[]);
  useEffect(()=>{void load();},[load,project.scope_version,project.audit?.length]);
  async function decide(f:any,decision:'accept'|'reject'|'defer'){
    setBusy(true);setMsg(null);
    const body:any={finding_id:f.finding_id,decision,by:by.trim(),note:note.trim()};if(decision==='accept')body.preview_digest=f.preview.digest;
    const fp=JSON.stringify(body);if(!pending.current||pending.current.fp!==fp)pending.current={fp,key:`ifs-${crypto.randomUUID()}`};
    try{
      const r=await fetch('/api/demo/ai-findings/decision',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':pending.current.key},body:JSON.stringify(body)});
      const b=await r.json().catch(()=>({error:`HTTP ${r.status}`}));
      if(!r.ok){if(r.status>=400&&r.status<500&&r.status!==429)pending.current=null;throw new Error(`${b.error||`HTTP ${r.status}`}${b.code?` [${b.code}]`:''}`);}
      pending.current=null;setMsg({id:f.finding_id,t:`${r.headers.get('idempotent-replay')==='true'?'(historical replay) ':''}${b.status}${b.scope_changed?` Scope version ${f.preview.scope_version_now} → ${b.scope_version}.`:' Scope version unchanged.'}`});
      setNote('');await load();onRefresh();
    }catch(e){setMsg({id:f.finding_id,t:e instanceof Error?e.message:'Could not record the decision'});}finally{setBusy(false);}
  }
  if(err)return <section className="card ai-findings" data-testid="ai-findings"><div className="notice error" role="alert"><CircleAlert size={16}/><span>{err}</span></div></section>;
  if(!data)return <section className="card ai-findings" role="status"><LoaderCircle className="spin" size={16}/> Loading AI findings…</section>;
  if(!data.available)return <section className="card ai-findings" data-testid="ai-findings"><p className="section-label">AI FINDINGS</p><p className="muted">{data.reason}</p></section>;
  const fs:any[]=data.findings;const native=fs.filter(f=>f.provenance==='REAL_AMD_OUTPUT'&&f.origin_document.doc_id===ANSI_B);const t002=native.filter(f=>f.run.run_id==='spatial_c101_live_002'),t003=native.filter(f=>String(f.run.run_id).startsWith('spatial_003_'));
  const other=fs.filter(f=>f.provenance==='REAL_AMD_OUTPUT'&&f.origin_document.doc_id!==ANSI_B);const simu=fs.filter(f=>f.provenance==='SIMULATED_TEST_DATA');
  const c101=data.states.C101;const acct=data.accounting;const cur=fs.find(f=>f.finding_id===sel)||null;
  const row=(f:any)=>{
    const jt=jumpTarget(f);const dec=f.decision;
    return <li key={f.finding_id} className={`ai-row${sel===f.finding_id?' on':''}`} data-testid={`finding-${f.finding_id}`} data-decision={dec?.decision||''} data-provenance={f.provenance}>
      <button className="ai-main" onClick={()=>setSel(sel===f.finding_id?null:f.finding_id)} aria-expanded={sel===f.finding_id}><strong>{f.claim.text.length>110?f.claim.text.slice(0,108)+'…':f.claim.text}</strong>
        <span className="ai-badges"><span className={`mini-tag ${f.classification==='CONTRADICTED_BY_DRAWING_EVIDENCE'?'bad':f.display_origin.startsWith('AI-suggested, evidence')||f.display_origin.includes('vector-confirmed')||f.display_origin==='Human-approved'?'ok':'warn'}`} data-testid="f-origin">{origin(f.display_origin)}</span>
        {f.uncertainty?.model_stated&&<span className="mini-tag" data-testid="f-model-conf" title="the model's own stated confidence; not evidence">model: {f.uncertainty.model_stated}</span>}
        <span className={`mini-tag ${f.verification.result==='VERIFIED_EXACT'||/CONFIRMED/.test(f.verification.verdict||'')&&!/CONTRADICTED/.test(f.verification.verdict||'')?'ok':/CONTRADICTED/.test(f.verification.verdict||'')?'bad':'warn'}`} data-testid="f-verify">{verifyText(f).split(' · ')[0]}</span>
        {dec&&<span className="mini-tag" data-testid="f-decision">{dec.decision==='accept'?'ACCEPTED by a human':dec.decision==='reject'?'REJECTED':'DEFERRED'}</span>}</span></button>
      <button className="chip-btn" disabled={!jt} onClick={()=>jt&&view(jt)} data-testid="f-jump" title={jt?'Show this evidence in the PDF viewer':'No viewable evidence in this project'}><Search size={12}/> {jt?'Show evidence':'Not viewable here'}</button>
    </li>;
  };
  return <section className="card ai-findings" aria-label="AI findings" data-testid="ai-findings" data-ledger={data.ledger_sha256}>
    <div className="card-heading"><div><p className="section-label">AI FINDINGS · AMD · STORED OUTPUTS (OFFLINE)</p><h2><Bot size={18}/> AI Findings <span className="h2-count">{fs.length}</span></h2></div><button className="text-button" onClick={()=>{void load();}}><RefreshCw size={14}/> Reload</button></div>
    <div className="guardrail ai-doctrine" role="note"><CircleAlert size={19}/><span><strong>AI interprets. Code calculates. Humans authorize.</strong> These are CANDIDATES with code-computed verification, not construction facts. {aiFindingsCallNote(mode)} Accepting one never authorizes Scope by itself; a rejected, deferred or unverified finding changes nothing.</span></div>
    <p className="tiny" data-testid="ai-state"><span className={`mini-tag ${c101.state==='REVIEW_REQUIRED'?'warn':''}`} data-testid="ai-state-c101">C101 · {STATE_TEXT[c101.state]}</span> {Object.entries(data.states).filter(([k])=>k!=='C101').map(([k,v]:any)=><span key={k} className="mini-tag" title={`${k}: ${STATE_TEXT[v.state]}`}>{k} · {STATE_TEXT[v.state]}</span>)}</p>
    <p className="tiny subdued" data-testid="ai-accounting">Real AMD attempts recorded: {acct.real_amd_attempts_recorded} ({Object.entries(acct.attempts_by_state).map(([k,v])=>`${v} ${k.toLowerCase().replaceAll('_',' ')}`).join(', ')}). Real findings {acct.real_findings} ({acct.real_on_ansi_b_native} on the ANSI B drawing, {acct.real_on_34x22_origin} captured on a different 34×22 Rev 0 file){acct.simulated_findings>0?` · simulated test items ${acct.simulated_findings}`:''}. Spatial: {acct.spatial_observations} observations of {acct.spatial_distinct_relationships} distinct relationships (repeats are not independent facts). Fence-type leader targets verified: {acct.real_fence_type_to_element_associations_verified}; contradicted observations marked “clear”: {acct.confident_and_contradicted_observations}.</p>

    <details open data-testid="group-t003"><summary><strong>Spatial Test 003</strong> · ANSI B C101 · REAL AMD OUTPUT, DeepSeek-V4.1-Flash · {t003.length} observations · predefined success criterion NOT MET</summary>
      <p className="tiny subdued" data-testid="t003-note">Three small crops, frozen plan 784c93c8…. Gate LABEL positions were localized correctly; no gate-symbol relationship is verified; tag A is vector-confirmed; tag B is CONTRADICTED by the drawing (marked "clear"); keynote 6 was a false type-tag candidate.</p>
      <ul className="ai-list">{t003.map(f=>row(f))}</ul></details>
    <details open data-testid="group-t002"><summary><strong>Spatial Test 002</strong> · ANSI B C101 · REAL AMD OUTPUT, DeepSeek-V4.1-Flash · {t002.length} observations (a distinct inference attempt)</summary>
      <ul className="ai-list">{t002.map(f=>row(f))}</ul></details>
    <details data-testid="group-other"><summary>Captured on a DIFFERENT source document (34×22 Rev 0, Qwen3.8-27B) · {other.length}</summary>
      <p className="tiny subdued">Verified against that file&apos;s own text layer. Only the findings whose quotation is also found on the registered ANSI B drawing can show evidence here; none of this is an AMD inference on the ANSI B file.</p>
      <ul className="ai-list">{other.map(f=>row(f))}</ul></details>
    {simu.length>0&&<details data-testid="group-sim"><summary><strong>SIMULATED TEST DATA</strong> — not an AMD result · {simu.length}</summary>
      <p className="tiny warning-text">Interface and guard tests only. These are invented to exercise the conflict and unverified-claim guards; they are excluded from every claim about AMD performance.</p>
      <ul className="ai-list">{simu.map(f=>row(f))}</ul></details>}

    {cur&&<div className="ai-detail" data-testid="ai-detail" data-finding={cur.finding_id}>
      <p className="section-label">WHAT THE AI CLAIMED</p>
      <p data-testid="d-claim"><strong>{cur.claim.text}</strong></p>
      <dl className="ai-dl">
        <div><dt>Origin</dt><dd>{origin(cur.display_origin)}{cur.provenance==='SIMULATED_TEST_DATA'?' — SIMULATED':''}</dd></div>
        <div><dt>Normalized</dt><dd>{JSON.stringify(cur.claim.normalized)}</dd></div>
        <div><dt>Document</dt><dd className="mono" title={cur.origin_document.sha256}>{cur.origin_document.doc_id} · p{cur.origin_document.page} {cur.origin_document.sheet||''} · sha256 {cur.origin_document.sha256}</dd></div>
        <div><dt>Model</dt><dd>{cur.model.provider} · {cur.model.requested}{cur.model.returned?` (returned ${cur.model.returned})`:''}</dd></div>
        <div><dt>Run</dt><dd className="mono">{cur.run.run_id} · input {short(cur.run.input_sha256)} · prompt {short(cur.run.prompt_sha256)}</dd></div>
        <div><dt>Evidence</dt><dd>{cur.evidence.quotation?`“${cur.evidence.quotation}”`:`visual anchor “${cur.evidence.visual_anchor||'—'}” (${cur.evidence.location_description||'no description'})`}</dd></div>
        <div><dt>Uncertainty</dt><dd data-testid="d-uncertainty">model-stated: {String(cur.uncertainty.model_stated??cur.uncertainty.model_stated_confidence??'—')} · {cur.uncertainty.classification.replaceAll('_',' ')} (confidence is not evidence)</dd></div>
      </dl>
      <p className="section-label">VERIFICATION</p>
      <p data-testid="d-verify"><span className={`mini-tag ${verifyText(cur).startsWith('VERIFIED')?'ok':'warn'}`}>{verifyText(cur)}</span> {cur.verification.why||''}</p>
      {cur.corroboration_on_dp001_ansi_b&&<p className="tiny" data-testid="d-corroboration">ANSI B drawing: <strong>{cur.corroboration_on_dp001_ansi_b.result==='EXACT'?'quotation found verbatim':'quotation NOT present'}</strong> — {cur.corroboration_on_dp001_ansi_b.attribution}</p>}
      {cur.post_hoc_reading&&<div className={`notice ${cur.post_hoc_reading.disagrees_with_claim?'error':'info'}`} role="note" data-testid="d-posthoc"><CircleAlert size={15}/><span><strong>{cur.post_hoc_reading.disagrees_with_claim?'REVIEW REQUIRED — a post-hoc PDF-vector reading disagrees with the AI claim.':'Post-hoc reading (not formal verification).'}</strong> {cur.post_hoc_reading.reading} <em>({cur.post_hoc_reading.source})</em></span></div>}
      {cur.retrospective_oracle_v3&&<p className="tiny" data-testid="d-retro"><span className={`mini-tag ${cur.retrospective_oracle_v3.claim_verdict.startsWith('CONFIRMED')?'ok':'warn'}`}>Retrospective vector oracle: {cur.retrospective_oracle_v3.claim_verdict.replaceAll('_',' ')}</span> leader ends on the {String(cur.retrospective_oracle_v3.leader_target.element).replaceAll('_',' ')} ({cur.retrospective_oracle_v3.leader_target.enclosure_side}). {cur.retrospective_oracle_v3.status}.</p>}
      {cur.model_confidence_vs_verification&&<p className="tiny" data-testid="d-confver"><strong>Model confidence vs independent verification:</strong> {cur.model_confidence_vs_verification}</p>}
      {cur.evidence?.vector_anchor&&<p className="tiny" data-testid="d-vector"><strong>Drawing evidence:</strong> the leader line ends on {cur.evidence.vector_anchor.terminal_description} ({cur.evidence.vector_anchor.distance_in} sheet-in from the leader end). Show evidence outlines the tag, the leader end and that element.</p>}
      {cur.evidence?.crop_visibility?.determinable&&<p className="tiny" data-testid="d-clip">Gate symbol visible in this crop: {Math.round((cur.evidence.crop_visibility.symbol_fraction_inside_crop??0)*100)}%{cur.crop_clipped?' — the crop CLIPS the symbol this prediction is about.':''}</p>}
      {cur.free_text_from_same_response?.length>0&&<p className="tiny" data-testid="d-freetext">Model free text in the same response: “{cur.free_text_from_same_response.join(' · ')}” (inconsistent with its structured answer).</p>}
      {cur.also_mentioned_in?.length>0&&<p className="tiny">Also: {cur.also_mentioned_in.map((x:any)=>x.text).join(' · ')}</p>}
      {cur.relationship_key&&<p className="tiny subdued" data-testid="d-relationship">Relationship <span className="mono">{cur.relationship_key}</span> — observed {fs.filter((x:any)=>x.relationship_key===cur.relationship_key).length}× across inference attempts; repeat observations are not independent construction facts.</p>}
      {cur.conflict&&<div className="notice error" role="alert" data-testid="d-conflict"><CircleAlert size={15}/><span><strong>CONFLICT with a controlling document.</strong> {cur.conflict.rule}. The AI may surface this; it cannot resolve it.</span></div>}
      <p className="section-label">RESULTING SCOPE CHANGE (PREVIEW — NOTHING IS COMMITTED UNTIL YOU ACCEPT)</p>
      <div data-testid="d-preview" data-kind={cur.preview.kind}>
        <p><span className={`mini-tag ${cur.preview.kind==='blocked'?'warn':''}`}>{cur.preview.kind==='engine_resolve'?'ENGINE SCOPE DECISION':cur.preview.kind==='no_scope_change'?'NO SCOPE CHANGE':'CANNOT BE ACCEPTED'}</span> {cur.preview.reason}</p>
        {cur.preview.steps.map((s:any,i:number)=><ul key={i} className="blocker-list"><li><span><strong>{s.route}</strong> · {s.exception_id}<br/>option <strong>{s.option_id}</strong> on {s.gate} ({s.plan_side} side): value <strong>{String(s.value)} {s.unit}</strong> — {s.value_source}. Scope version v{cur.preview.scope_version_now} → v{cur.preview.scope_version_after}.</span></li></ul>)}
        {cur.preview.kind==='engine_resolve'&&<p className="tiny" data-testid="d-voids">{cur.preview.voids_note}{cur.preview.voids?.length?` Voided: ${cur.preview.voids.join(', ')}.`:''}</p>}
        <p className="tiny subdued">Calculations, crew plans, pricing and release digests are unaffected by a rejected, deferred or unverified finding.</p>
      </div>
      {cur.final?<p className="tiny" data-testid="d-decided">Decided by {cur.decision.by} (self-declared): {cur.decision.decision.toUpperCase()} — “{cur.decision.note}”. Outcome: {cur.decision.outcome.replaceAll('_',' ')}{cur.decision.scope_version_after!==null?` (scope v${cur.decision.scope_version_before} → v${cur.decision.scope_version_after})`:''}.</p>
      :<div className="input-stack">
        <label>Your name (self-declared, not verified)</label><input aria-label="AI decision name" value={by} onChange={e=>setBy(e.target.value)} placeholder="Name for this AI decision (self-declared)"/>
        <label>Decision note</label><textarea aria-label="AI decision note" rows={2} value={note} onChange={e=>setNote(e.target.value)} placeholder="What did you check in the drawing?"/>
        <SelfDeclared/>
        <div className="ai-actions">
          <button className="btn primary" data-testid="f-accept" disabled={busy||!by.trim()||!note.trim()||!cur.can_accept} onClick={()=>{void decide(cur,'accept');}}>Accept</button>
          <button className="btn outlined" data-testid="f-reject" disabled={busy||!by.trim()||!note.trim()} onClick={()=>{void decide(cur,'reject');}}>Reject</button>
          <button className="btn ghost" data-testid="f-defer" disabled={busy||!by.trim()||!note.trim()} onClick={()=>{void decide(cur,'defer');}}>Defer</button></div>
        {!cur.can_accept&&<p className="tiny warning-text" data-testid="d-cannot">Accept is unavailable: {cur.preview.code||'see above'}.</p>}</div>}
      {msg&&msg.id===cur.finding_id&&<p className="tiny" role="status" data-testid="d-msg">{msg.t}</p>}
    </div>}

    <details><summary>Attempt inventory ({data.attempts.length}) — what AMD actually returned</summary>
      <div className="table-scroll"><table className="data-table"><thead><tr><th>Attempt</th><th>Document</th><th>Outcome</th><th>Accepted output</th></tr></thead><tbody>{data.attempts.map((a:any)=><tr key={a.attempt_id} data-testid={`attempt-${a.attempt_id}`}><td>{a.attempt_id}<br/><small className="subdued">{a.model}</small></td><td><small>{a.document.doc_id}<br/>{short(a.document.sha256)}</small></td><td><span className={`mini-tag ${a.state==='CANDIDATES_AVAILABLE'?'ok':'warn'}`}>{a.state.replaceAll('_',' ')}</span><br/><small>{a.detail}</small></td><td><small>{a.accepted_output}</small></td></tr>)}</tbody></table></div></details>
    <details data-testid="provenance"><summary>Provenance and execution control</summary>
      <p className="tiny">Spatial Test 003 manifest: {Object.keys(data.test003_manifest.files).length} frozen files verified; plan <span className="mono" title={data.test003_manifest.plan_sha256}>{data.test003_manifest.plan_sha256.slice(0,16)}…</span>.</p>
      {data.execution_control_deviations.map((d:any)=><div key={d.id} className="notice warn-note" role="note" data-testid="deviation"><CircleAlert size={15}/><span><strong>{d.id} — {d.kind}.</strong> {d.what_happened} {d.decision}</span></div>)}</details>
    <p className="tiny subdued" data-testid="ai-statement">{acct.statement}</p>
  </section>;
}

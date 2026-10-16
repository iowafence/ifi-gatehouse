'use client';
// AI Flight Recorder: a small, expandable execution trace. Three PRODUCER layers (AMD / Google Gemma / Evolus) are kept visibly separate from the two
// layers Gatehouse computes itself (code validation, human authorization). Every value shows the provenance state of the record it came from;
// a value a record does not contain is shown as NOT REPORTED, never estimated. Read-only: this panel calls no model and changes nothing.
import {useCallback, useEffect, useRef, useState} from 'react';
import {Activity, CircleAlert, LoaderCircle, RefreshCw, X} from 'lucide-react';

/* eslint-disable @typescript-eslint/no-explicit-any */
const STATE_HELP:Record<string,string>={LIVE:'Captured live during this session',RECORDED:'From a stored record (hash shown)',SIMULATED:'Produced by a simulator or test fixture',FAILED:'The step failed; the reason is shown',NOT_REPORTED:'No record contains this'};
const LAYER_TITLE:Record<string,string>={amd:'AMD · inference provider',gemma:'Google Gemma · model',evolus:'Evolus · orchestration',gatehouse_validation:'Gatehouse validation · code',human_authorization:'Human authorization'};
const LAYER_KIND:Record<string,string>={amd:'Producer layer',gemma:'Producer layer',evolus:'Producer layer',gatehouse_validation:'Computed by Gatehouse',human_authorization:'Computed by Gatehouse'};
const KEY_FIELDS=['http_status','ttft_s','t_end_s','prompt_tokens','completion_tokens','tokens_per_s','cost_usd','by','decision','workflow_execution_id','review_state'];
// User-facing text never names the build or review agents; the hashes still identify the exact records.
const noAgents=(t:unknown)=>String(t??'').replace(/\b(ANVIL|LOOM|WITNESS|HERMES|KNOX|BLAKE|RIOT|ATLAS)(?:[ _-]?\d+)?\b/gi,'an independent reviewer');
const short=(h?:string|null)=>h?`${h.slice(0,10)}…${h.slice(-6)}`:'—';

export function StateBadge({state}:{state:string}){
  return <span className={`fr-badge fr-${state.toLowerCase()}`} title={STATE_HELP[state]||state} data-testid={`fr-state-${state}`}>{state.replace('_',' ')}</span>;
}
function fmt(f:any):string{
  if(!f||f.value===null||f.value===undefined)return 'NOT REPORTED';
  if(Array.isArray(f.value))return f.value.length?f.value.join(', '):'(none)';
  if(typeof f.value==='number'&&f.unit==='USD')return `$${f.value}`;
  return `${String(f.value)}${f.unit&&f.unit!=='USD'?' '+f.unit:''}`;
}
function Fields({ev}:{ev:any}){
  const rows=Object.entries(ev.fields||{}) as [string,any][];
  if(!rows.length)return <p className="tiny subdued">No fields. {ev.note||''}</p>;
  return <table className="fr-fields"><tbody>{rows.map(([k,f])=>(
    <tr key={k} className={f.value===null?'fr-null':''}><th scope="row">{k}</th><td data-testid={`fr-field-${k}`}>{fmt(f)}{f.derived&&<span className="fr-derived" title={`derived: ${f.derived.formula}`}> derived · {f.derived.formula}</span>}</td></tr>))}</tbody></table>;
}
function Event({ev}:{ev:any}){
  const f=ev.fields||{};
  const facts=KEY_FIELDS.filter(k=>f[k]&&f[k].value!==null).slice(0,6).map(k=>`${k.replace(/_/g,' ')} ${fmt(f[k])}`);
  return <details className="fr-event" data-testid="fr-event">
    <summary><StateBadge state={ev.state}/> <span className="fr-label">{ev.label}</span>{facts.length>0&&<span className="fr-facts">{facts.join(' · ')}</span>}</summary>
    <div className="fr-body">
      <Fields ev={ev}/>
      {ev.utc&&ev.utc!=='1970-01-01T00:00:00.000Z'&&<p className="tiny subdued">Time: {ev.utc}</p>}
      <p className="tiny subdued" data-testid="fr-source">Source: {ev.source?.kind?.replaceAll('_',' ')}{ev.source?.record_path?` · ${ev.source.record_path}`:''}{ev.source?.record_sha256?` · sha256 ${short(ev.source.record_sha256)}`:''}</p>
      {ev.note&&<p className="tiny fr-note">{ev.note}</p>}
    </div></details>;
}
function LayerBlock({layer,tid,defaultOpen}:{layer:any;tid?:string;defaultOpen:boolean}){
  const [open,setOpen]=useState(defaultOpen);
  return <section className={`fr-layer fr-layer-${layer.layer}`} data-testid={tid||`fr-layer-${layer.layer}`}>
    <button className="fr-layer-head" type="button" aria-expanded={open} onClick={()=>setOpen(v=>!v)}>
      <span className="fr-layer-kind">{LAYER_KIND[layer.layer]}</span><strong>{LAYER_TITLE[layer.layer]||layer.layer}</strong><StateBadge state={layer.state}/><span className="tiny subdued">{layer.events.length} event{layer.events.length===1?'':'s'}</span>
    </button>
    {open&&<div className="fr-layer-body"><p className="tiny">{layer.summary}</p>{layer.events.map((e:any)=><Event key={e.event_id} ev={e}/>)}</div>}
  </section>;
}
const yn=(v:boolean|null|undefined,y:string,n:string,u='not recorded')=>v===true?y:v===false?n:u;
const ASSESS_CLASS:Record<string,string>={SUPPORTED:'fr-pill-supported',FLAGGED:'fr-pill-flagged',NOT_AUDITED:'fr-pill-no',AUDIT_UNVERIFIABLE:'fr-pill-flagged'};
function AssessPill({a,tid}:{a:any;tid?:string}){return <span className={`fr-pill ${ASSESS_CLASS[a?.state]||'fr-pill-no'}`} data-testid={tid||'fr-assess-pill'}>{a?.label||'NOT INDEPENDENTLY AUDITED'}</span>;}
function EvidenceList({a}:{a:any}){
  if(!a?.evidence?.length)return null;
  return <ul className="fr-src-list" data-testid="fr-assess-evidence">{a.evidence.map((e:any,i:number)=>
    <li key={i}><strong>{e.role==='controlling_contradicts'?'Controlling evidence':e.role==='supports'?'Supporting evidence':e.role==='context'?'Context':'Cited by the original'}</strong> <span className="subdued">· {e.locator} · {e.doc_id} · page {e.page}{e.controlling_document?' · controlling document':''}</span>{e.applies_to&&e.applies_to!=='general'&&<span className="fr-scope-tag" data-testid="fr-evidence-scope" data-applies-to={e.applies_to}>applies to Gate {e.applies_to} only{e.applies_to==='G2'&&e.role==='context'?' — not extended to G3':''}</span>}
      <p className="tiny subdued fr-case-label" data-testid="fr-excerpt-label">Adapter-supplied excerpt text (may join separate table cells; not a verified contiguous quotation)</p>
      <div className="fr-quote" data-testid="fr-excerpt-text">{e.quote}</div>
      <div className="tiny subdued">{e.matches_run_package===true?'text is identical to the excerpt in the package recorded in the run record (compared with the adapter’s text, not with the PDF)':e.matches_run_package===false?'TEXT DOES NOT MATCH the excerpt in the run record':'text not compared with the run record'} · {e.registry==='match'?'document hash matches Gatehouse’s registry':'document not in Gatehouse’s registry'} · the Flight Recorder does not read the PDF</div></li>)}</ul>;
}
function Assurance({c,run}:{c:any;run:any}){
  const a=c.assessment; const regOk=c.evidence.every((e:any)=>e.registry==='match');
  return <table className="fr-assure" data-testid="fr-assurance"><tbody>
    <tr><th>Structurally valid AI output</th><td data-testid="fr-assure-structure">{run?`Gatehouse strict validator: ${run.status||'not recorded'} (original result, unchanged)`:'run record not available here'}</td></tr>
    <tr><th>Source match reported by adapter</th><td data-testid="fr-assure-adapter">The adapter reported, when the package was built, that {c.evidence.length} cited excerpt{c.evidence.length===1?'':'s'} matched source text. <strong>Not independently rechecked by the Flight Recorder</strong>, which does not read the PDFs.</td></tr>
    <tr><th>Citation binding checks by the recorder</th><td data-testid="fr-assure-citations">Each citation id resolves to an evidence record; {regOk?'document hash and page agree with Gatehouse’s registry':'a document is not in Gatehouse’s registry'}. These checks tie a citation to a document and page. They do not check the quoted text and say nothing about whether the conclusion follows.</td></tr>
    <tr><th>Independent assessment of semantic support</th><td data-testid="fr-assure-semantic"><AssessPill a={a} tid="fr-assess-pill"/> <span className="tiny subdued">{a.state==='NOT_AUDITED'||a.state==='AUDIT_UNVERIFIABLE'?'':'from the audit record shown in this block; an assessment, not a decision'}</span></td></tr>
    <tr><th>Human authorization</th><td data-testid="fr-assure-human"><strong>NONE RECORDED</strong> — NOT APPROVED, NOT SENT. No person has approved or rejected this draft.</td></tr>
  </tbody></table>;
}
function CaseCard({c,run}:{c:any;run:any}){
  const a=c.authority; const st=c.assessment.state;
  return <article className={`fr-case${st==='FLAGGED'||st==='AUDIT_UNVERIFIABLE'?' fr-case-flagged':''}`} data-testid="fr-case" data-case-id={c.case_id} data-assessment={st}>
    <div className="fr-case-head"><strong data-testid="fr-case-id">{c.case_id}</strong>
      <span className="fr-pill fr-pill-pending" data-testid="fr-case-status">PENDING HUMAN REVIEW</span>
      <span className="fr-pill fr-pill-no" data-testid="fr-case-approval">NOT APPROVED</span>
      <span className="fr-pill fr-pill-no" data-testid="fr-case-sent">NOT SENT</span></div>
    {st==='FLAGGED'&&<div className="fr-flag" role="note" data-testid="fr-flag"><strong>FLAGGED — UNSUPPORTED BY CONTROLLING EVIDENCE.</strong> {c.assessment.summary}</div>}
    {st==='AUDIT_UNVERIFIABLE'&&<div className="fr-flag" role="note" data-testid="fr-flag"><strong>NOT CLEARED.</strong> {c.assessment.summary}</div>}
    <p className="tiny fr-scope" data-testid="fr-case-banner"><strong>Proposed RFI: a stored AI draft.</strong> It has not been approved by a person and has not been sent to anyone. It is not part of the estimate.{st==='SUPPORTED'?' The independent audit supports it, so it is eligible for human review.':''}</p>
    <Assurance c={c} run={run}/>
    <h5 className="fr-case-subject">{c.subject}</h5>
    <p className="fr-case-q" data-testid="fr-case-question">{c.question}</p>
    <p className="tiny subdued fr-case-label">Unresolved requirements (as the AI stated them)</p>
    <ul className="fr-case-list" data-testid="fr-case-missing">{c.missing_requirements.map((m:string,i:number)=><li key={i}>{m}</li>)}</ul>
    <p className="tiny subdued fr-case-label">Sources cited by the draft</p>
    <ul className="fr-src-list" data-testid="fr-case-sources">{c.evidence.map((e:any)=>
      <li key={e.excerpt_id}><strong>{e.excerpt_id}</strong> <span className="subdued">· {e.doc_id} · page {e.page} · document sha256 {short(e.doc_sha256)}</span>
        <div className="tiny subdued">source match reported by adapter — not independently rechecked by Flight Recorder · {e.registry==='match'?'document hash matches Gatehouse’s registry':'document not in Gatehouse’s registry'} · {e.quote_in_source?`adapter-supplied excerpt text: ${e.quote_in_source}`:'excerpt text not stored in the case'}</div></li>)}</ul>
    {c.assessment.evidence.length>0&&<><p className="tiny subdued fr-case-label">Independent audit evidence</p>
      {c.assessment.verification_note&&<p className="tiny" data-testid="fr-assess-note"><strong>Independent verification:</strong> {c.assessment.verification_note}</p>}
      <EvidenceList a={c.assessment}/></>}
    <p className="tiny subdued" data-testid="fr-case-authority">Recorded authority: changes scope {yn(a.changes_scope,'yes','no')} · changes estimate {yn(a.changes_estimate,'yes','no')} · authorizes labor or release {yn(a.authorizes_labor_or_release,'yes','no')} · marks bid ready {yn(a.marks_bid_ready,'yes','no')} · needs a named human {yn(a.requires_named_human,'yes','no')}. Showing this case changes none of them.</p>
    <p className="tiny subdued" data-testid="fr-case-integrity">Integrity: {c.integrity.run_record==='matches_trace_hash'?'run record hash matches the execution trace; draft is identical to the draft in the run record':'run record not available here; draft not cross-checked'} · case file {c.file} · sha256 {short(c.sha256)}</p>
  </article>;
}
function DropsNote({run,audit}:{run:any;audit:any}){
  if(!run||run.dropped_excerpts===null||run.dropped_excerpts===0)return null;
  return <div className="tiny fr-drops" data-testid="fr-drops">
    <strong>{run.dropped_excerpts} package entr{run.dropped_excerpts===1?'y was':'ies were'} omitted before submission.</strong> The run record names document id {run.dropped_doc_ids.map((d:string)=>`“${d}”`).join(', ')||'—'}{run.dropped_unregistered===true?', which is not a registered Gatehouse document':''}. The package builder’s own reason code is {run.dropped_reasons.join(', ')||'not recorded'} (a generic code).
    {audit?.drops?<> <strong data-testid="fr-drops-correction">Audit correction ({audit.audit_id}):</strong> {audit.drops.explanation}</>:<> That code has not been independently explained; do not read it as a failed PDF quotation.</>}
  </div>;
}
const SCOPE_CLASS:Record<string,string>={UNRESOLVED:'fr-pill-flagged',SPECIFIED:'fr-pill-supported'};
function G3Scope({audit}:{audit:any}){
  const f:any[]=audit?.scope_findings||[]; if(!f.length)return null;
  return <section className="fr-g3" data-testid="fr-g3-scope"><h5 className="fr-shortlist-title">Gate G3: what the documents resolve and what they do not</h5>
    <ul className="fr-case-list">{f.map(i=><li key={i.item} data-testid="fr-g3-item" data-item={i.item} data-status={i.status}><strong>{i.label}</strong> <span className={`fr-pill ${SCOPE_CLASS[i.status]||'fr-pill-no'}`}>{i.status}</span>{i.value&&<> <span data-testid="fr-g3-value">{i.value}</span></>}<div className="tiny subdued">{i.basis}</div></li>)}</ul>
    <p className="tiny" data-testid="fr-g3-note">The footing minimums are known because the G3 detail and the general gate rule point to 3/F501. The G3 post size is not, because Specification 2.1.B ties it to the opening width, which no document gives. Addendum 01 item 1.5 (2.875 in OD) belongs to Gate G2 and is not applied to G3. No design-team answer and no human authorization is recorded for either open item.</p></section>;
}
function Clarification({c}:{c:any}){
  return <article className="fr-case fr-clarif" data-testid="fr-clarification" data-clarification-id={c.clarification_id}>
    <div className="fr-case-head"><strong data-testid="fr-clarif-id">{c.clarification_id}</strong><span className="fr-pill fr-pill-pending">PROPOSED</span><span className="fr-pill fr-pill-no">NOT APPROVED</span><span className="fr-pill fr-pill-no">NOT SENT</span><span className="fr-pill fr-pill-no">NOT AN EVOLUS CASE</span></div>
    <h5 className="fr-case-subject">{c.topic}</h5>
    <p className="tiny fr-scope" data-testid="fr-clarif-authorship"><strong>Authorship:</strong> {noAgents(c.authorship)} Drafted from {noAgents(c.derived_from_issue)}. A named person must review it before anything is asked of the design team.</p>
    <p className="fr-case-q" data-testid="fr-clarif-question">{c.question}</p>
    <p className="tiny subdued fr-case-label">Unresolved requirement</p><ul className="fr-case-list">{c.unresolved_requirements.map((m:string,i:number)=><li key={i}>{m}</li>)}</ul>
    {c.excluded_because_specified.length>0&&<><p className="tiny subdued fr-case-label">Not asked, because the documents already specify it</p><ul className="fr-case-list" data-testid="fr-clarif-excluded">{c.excluded_because_specified.map((m:string,i:number)=><li key={i}>{m}</li>)}</ul></>}
  </article>;
}
function ReviewBlock({x}:{x:any}){
  const rv=x.review; const run=rv?.run; const audit=rv?.audit; const cases:any[]=rv?.cases||[];
  const cleared=cases.filter(c=>c.assessment.state==='SUPPORTED'); const flagged=cases.filter(c=>c.assessment.state==='FLAGGED');
  const pending=cases.filter(c=>c.assessment.state==='NOT_AUDITED'||c.assessment.state==='AUDIT_UNVERIFIABLE');
  return <div className="fr-review" data-testid="fr-review">
    <h5 className="fr-review-title">Gatehouse review of this execution</h5>
    {run?<div className="fr-validator" data-testid="fr-validator">
      <p><strong>Gatehouse strict validator (original result, unchanged):</strong> <span data-testid="fr-validator-status">{run.status||'not recorded'}</span> <span className="tiny subdued">(from the run record {run.run_id}, sha256 {short(run.sha256)}{run.matches_trace_hash?', matches the hash in the trace':''}). This means the output had a valid structure and resolvable citations. It does not mean the conclusions are supported.</span></p>
      <p className="tiny" data-testid="fr-validator-counts">{run.issues.length} issue{run.issues.length===1?'':'s'} accepted · {yn(run.rfi_drafts!==null,String(run.rfi_drafts),'')} RFI draft{run.rfi_drafts===1?'':'s'} · {run.dropped_excerpts===null?'dropped entries not recorded':`${run.dropped_excerpts} package entr${run.dropped_excerpts===1?'y':'ies'} omitted before submission`} · Gatehouse project state {yn(run.gatehouse_state_unchanged,'unchanged during the run (as recorded)','CHANGED during the run','change not recorded')}</p>
      <DropsNote run={run} audit={audit}/>
      {run.issues.length>0&&<ul className="fr-case-list tiny" data-testid="fr-issues">{run.issues.map((i:any)=><li key={i.issue_id} data-assessment={i.assessment?.state||'NOT_AUDITED'}>{i.issue_id} · {i.title} <span className="subdued">({i.category}{i.severity?`; AI-suggested severity ${i.severity}`:''})</span> <AssessPill a={i.assessment} tid="fr-issue-assess"/></li>)}</ul>}
      <p className="tiny subdued">Everything above is an AI suggestion for human review. None of it is a Scope revision.</p>
    </div>:<p className="tiny subdued" data-testid="fr-validator-none">{rv?'The run record for this execution is not available in this deployment, so the validator outcome is not shown.':'No stored review cases for this execution.'}</p>}
    {audit&&<div className="fr-audit" data-testid="fr-audit"><p><strong>Independent audit:</strong> {audit.auditor} ({audit.auditor_role}){audit.reported_verdict?` · reported verdict “${audit.reported_verdict}”`:''}</p>
      <p className="tiny subdued" data-testid="fr-audit-source">Source ({audit.source_kind.replaceAll('_',' ')}): {audit.source_description}</p>
      <p className="tiny subdued">Additive record {audit.audit_id} · created {audit.created_utc} · sha256 {short(audit.sha256)} · bound to the run record and case bytes above, which it does not modify. <strong data-testid="fr-audit-nothuman">This is an automated assessment, not a human approval, rejection or decision. Human authorization: none recorded.</strong></p>
      <p className="tiny" data-testid="fr-audit-pinned"><strong>Pinned by this release:</strong> these exact audit bytes (sha256 {short(audit.pinned.audit_sha256)}) and the independent review report (sha256 {short(audit.pinned.report_sha256)}, bundled copy re-hashed) match the release manifest, and every disposition matches the manifest’s pinned policy. That proves the record is the one this release shipped. It does not prove who wrote it, and the digest the app computes from a file is never treated as proof.</p>
      {audit.pinned.superseded.length>0&&<p className="tiny subdued" data-testid="fr-audit-superseded">Supersedes {audit.pinned.superseded.map((s:any)=>`${s.audit_id} (sha256 ${short(s.sha256)}, retained unchanged)`).join(', ')}: that record applied Addendum 01 item 1.5 to G3, which the correction withdraws.</p>}</div>}
    {audit&&<G3Scope audit={audit}/>}
    {rv?.audit_unverifiable&&<div className="fr-flag" role="note" data-testid="fr-audit-unverifiable"><strong>Independent audit evidence for this run could not be authenticated</strong> (altered, missing, unpinned or duplicate; reasons are in the trace-file list). No case is cleared and nothing here can be treated as audited.</div>}
    {cases.length>0&&<p className="tiny subdued fr-case-label" data-testid="fr-case-count">{cases.length} pending-review RFI case{cases.length===1?'':'s'}</p>}
    {cleared.length>0&&<section data-testid="fr-shortlist"><h5 className="fr-shortlist-title">Active RFI shortlist — eligible for human review</h5>{cleared.map(c=><CaseCard key={c.case_id} c={c} run={run}/>)}</section>}
    {audit?.proposed_clarifications?.length>0&&<section data-testid="fr-clarifications"><h5 className="fr-shortlist-title">Proposed clarification — not an Evolus case, awaiting human review</h5>{audit.proposed_clarifications.map((c:any)=><Clarification key={c.clarification_id} c={c}/>)}</section>}
    {pending.length>0&&<section data-testid="fr-unaudited"><h5 className="fr-shortlist-title">Not cleared — no verified independent audit</h5>{pending.map(c=><CaseCard key={c.case_id} c={c} run={run}/>)}</section>}
    {flagged.length>0&&<section data-testid="fr-flagged-section"><h5 className="fr-shortlist-title fr-shortlist-flagged">Historical AI output — flagged, not on the active shortlist</h5>
      {flagged.map(c=><details key={c.case_id} className="fr-flagged-case" data-testid="fr-flagged-case"><summary><strong>{c.case_id}</strong> <AssessPill a={c.assessment} tid="fr-flagged-pill"/> <span className="subdued">{c.subject}</span></summary><CaseCard c={c} run={run}/></details>)}</section>}
  </div>;
}
function ExecutionView({x}:{x:any}){
  return <div className="fr-exec" data-testid="fr-selected" data-trace-id={x.trace_id}>
    <div className="fr-exec-head"><strong data-testid="fr-exec-id">{x.trace_id}</strong><StateBadge state={x.outcome}/></div>
    <p className="tiny subdued" data-testid="fr-exec-meta">Producer: {x.producer}{x.generated_utc?` · generated ${x.generated_utc}`:''} · file {x.file} · sha256 {short(x.sha256)}</p>
    <p className="tiny fr-scope">Everything in this block comes from this one execution. A layer that reports nothing says NOT REPORTED; earlier runs are kept in the section below.</p>
    {x.layers.map((l:any)=><LayerBlock key={`${x.trace_id}:${l.layer}`} layer={l} defaultOpen/>)}
    <ReviewBlock x={x}/>
  </div>;
}

export function FlightRecorder({open,onClose}:{open:boolean;onClose:()=>void}){
  const [data,setData]=useState<any>(null);
  const [err,setErr]=useState<string|null>(null);
  const [busy,setBusy]=useState(false);
  const [sel,setSel]=useState(0);
  const closeRef=useRef<HTMLButtonElement>(null);
  const load=useCallback(async()=>{
    setBusy(true);setErr(null);
    try{
      const r=await fetch('/api/demo/flight-recorder',{cache:'no-store'});
      const b=await r.json();
      if(!r.ok)setErr(b?.error||`HTTP ${r.status}`);else{setData(b);setSel(0);}
    }catch{setErr('The Flight Recorder could not be loaded.');}
    setBusy(false);
  },[]);
  useEffect(()=>{if(open){void load();window.setTimeout(()=>closeRef.current?.focus(),0);}},[open,load]);
  // Capture phase + stopPropagation: Escape closes only the topmost layer (this panel), not the gate dialog behind it.
  useEffect(()=>{if(!open)return;const h=(e:KeyboardEvent)=>{if(e.key==='Escape'){e.stopPropagation();onClose();}};window.addEventListener('keydown',h,true);return()=>window.removeEventListener('keydown',h,true);},[open,onClose]);
  if(!open)return null;
  const rejected=(data?.sources||[]).filter((s:any)=>!s.accepted);
  const execs:any[]=data?.executions||[]; const hist=data?.historical;
  return <>
    <div className="fr-backdrop" onClick={onClose}/>
    <aside className="fr-drawer" role="dialog" aria-modal="false" aria-label="AI Flight Recorder" data-testid="flight-recorder">
      <div className="fr-bar"><div><p className="section-label">AI FLIGHT RECORDER</p><h3><Activity size={17}/> Execution trace</h3></div>
        <div className="fr-bar-actions"><button className="icon-button" type="button" onClick={()=>void load()} aria-label="Refresh trace" disabled={busy}>{busy?<LoaderCircle size={16} className="spin"/>:<RefreshCw size={16}/>}</button>
        <button ref={closeRef} className="icon-button" type="button" onClick={onClose} aria-label="Close Flight Recorder"><X size={17}/></button></div></div>
      <div className="fr-legend" aria-label="Trace states">{Object.keys(STATE_HELP).map(s=><span key={s} className="fr-legend-item"><StateBadge state={s}/><span className="tiny subdued">{STATE_HELP[s]}</span></span>)}</div>
      {err&&<div className="guardrail" role="alert"><CircleAlert size={18}/><span>{err}</span></div>}
      {!data&&!err&&<p className="muted">Loading…</p>}
      {data&&<>
        <p className="tiny subdued" data-testid="fr-notice">{data.notice}</p>
        <h4 className="fr-group">Selected execution <span className="tiny subdued">one run, exactly as its producer reported it</span></h4>
        {execs.length===0&&<div className="fr-none" data-testid="fr-no-execution"><StateBadge state="NOT_REPORTED"/> <span>No execution trace has been recorded. Nothing below the next heading belongs to a current run.</span></div>}
        {execs.length>1&&<div className="fr-picker" role="tablist" aria-label="Recorded executions" data-testid="fr-picker">{execs.map((e:any,i:number)=><button key={e.trace_id} type="button" role="tab" aria-selected={i===sel} className={`fr-pick${i===sel?' on':''}`} onClick={()=>setSel(i)} data-testid="fr-pick"><StateBadge state={e.outcome}/> <span className="tiny">{e.trace_id}</span></button>)}</div>}
        {execs.length>0&&<ExecutionView key={execs[Math.min(sel,execs.length-1)].trace_id} x={execs[Math.min(sel,execs.length-1)]}/>}
        <h4 className="fr-group">Historical recorded evidence <span className="tiny subdued">earlier runs, NOT part of the selected execution</span></h4>
        <div className="fr-hist" data-testid="fr-historical">
          <p className="tiny fr-scope" data-testid="fr-hist-meta">Stored with the repository{hist.source?.accepted?<> · file {hist.source.name} · sha256 {short(hist.source.sha256)} · {hist.source.producer}</>:<> · record not available</>}. These requests were made earlier; they are not what happened in the execution above.</p>
          {hist.layers.map((l:any)=><LayerBlock key={l.layer} layer={l} tid={`fr-hist-layer-${l.layer}`} defaultOpen={false}/>)}
          <LayerBlock layer={hist.validation} defaultOpen={false}/>
        </div>
        <h4 className="fr-group">This session <span className="tiny subdued">computed by Gatehouse from this project</span></h4>
        <LayerBlock layer={data.session.human_authorization} defaultOpen={false}/>
        <h4 className="fr-group">Trace files <span className="tiny subdued">strictly validated; a violation is rejected, never repaired</span></h4>
        <ul className="fr-sources" data-testid="fr-sources">{(data.sources||[]).map((s:any)=><li key={s.name}><strong>{s.name}</strong> <span className="tiny subdued">({s.role==='historical'?'historical record':s.role==='case'?'review case':s.role==='audit'?'independent audit record':'execution trace'})</span> — {s.accepted?<span className="fr-ok">accepted</span>:<span className="fr-bad" data-testid="fr-rejected">REJECTED</span>}{s.sha256&&<span className="tiny subdued"> · sha256 {short(s.sha256)}</span>}{s.producer&&<span className="tiny subdued"> · {s.producer}</span>}{s.errors&&<ul>{s.errors.map((e:string,i:number)=><li key={i} className="tiny">{e}</li>)}</ul>}</li>)}{!(data.sources||[]).length&&<li className="tiny subdued">No trace files found.</li>}</ul>
        {rejected.length>0&&<p className="tiny warning-text">{rejected.length} trace file(s) were rejected and none of their content is displayed.</p>}
      </>}
    </aside></>;
}

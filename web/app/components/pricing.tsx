'use client';
// Display and input components for the real pricing integration. NOTHING here calculates money, hours or digests:
// every figure shown is returned by the Python engine (preview or approved state); this file only formats and selects.
import {useEffect, useMemo, useRef, useState} from 'react';
import {CircleAlert, Info, LockKeyhole, ArrowRight} from 'lucide-react';
import type {Comparison, Economics, EstimateView, Exception, PlanBody, Preview, Project} from '@/lib/types';

const usd=(n:unknown)=>typeof n==='number'&&Number.isFinite(n)?new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(n):'—';
const num=(n:unknown,d=1)=>typeof n==='number'&&Number.isFinite(n)?n.toFixed(d):'—';
const pctf=(n:unknown)=>typeof n==='number'?`${n.toFixed(1)}%`:'n/a';
async function postJSON<T>(url:string,body:object):Promise<T>{
  const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const j=await r.json().catch(()=>({error:`Unexpected HTTP ${r.status}`}));
  if(!r.ok){const e=j as {error?:string;code?:string;retry_after_seconds?:number};const ra=Number(e.retry_after_seconds??r.headers.get('retry-after')??0);
    throw Object.assign(new Error(e.error||`HTTP ${r.status}`),{status:r.status,code:e.code,retryAfter:Number.isFinite(ra)&&ra>0?Math.ceil(ra):undefined});}
  return j as T;
}
/** Shown beside every human decision button: the actor name is typed, not authenticated. */
export function SelfDeclared(){return <p className="tiny self-declared" data-testid="self-declared"><strong>Self-declared demo approval — identity not authenticated.</strong></p>;}
const LEVELS=['easy','standard','hard'] as const;
const BLOCKER_TEXT:Record<string,string>={
  WAGE_DETERMINATION_REQUIRED:'Prevailing wage applies: a named person must record the wage determination before labor can be priced.',
  CREW_PLAN_REQUIRED:'A named person must approve the crew plan (crews per task and job difficulty).',
  MISSING_VALUE:'A required scope value is still unresolved.',
};

export function ProvisionalBox({p,wageCleared}:{p:import('@/lib/types').Provisional|null;wageCleared:boolean}){
  return <div className="guardrail provisional" aria-label="Provisional labor (informational)"><CircleAlert size={19}/><div><strong>Provisional and informational: not a crew plan, never releasable.</strong>
    {p&&typeof p.provisional_labor_cost==='number'
      ?<p className="prov-line">Provisional labor: <strong data-testid="prov-total">{usd(p.provisional_labor_cost)}</strong>, the mean cost of the fleet crews eligible for each task (wage bases cleared). Drilling uses only the eligible crews.</p>
      :<p className="prov-line" data-testid="prov-none">No provisional dollar figure: {wageCleared?'at least one task has no eligible fleet crew, so the estimate is incomplete.':'the wage determination is not recorded, so no compliant cost can be shown. Hours are shown for each crew.'}</p>}
    {p&&<details><summary>Per-task provisional cost</summary><ul className="prov-list">{p.lines.map(l=><li key={l.task_id} data-task={l.task_id}><span>{l.task}</span><span>{typeof l.provisional_cost==='number'?usd(l.provisional_cost):'no cost'}</span><small>{l.eligible_crews.length?`mean of ${l.eligible_crews.map(c=>c.name).join(', ')}`:'no eligible fleet crew'}</small></li>)}</ul></details>}
  </div></div>;
}

export function PlanHistory({h}:{h:import('@/lib/types').PlanHistoryItem[]}){
  if(!h.length)return null;
  return <details className="plan-history"><summary>Crew-plan versions ({h.length})</summary><ul className="prov-list">{h.map(x=><li key={x.plan_version} data-version={x.plan_version}><span>v{x.plan_version} · {x.approved_by}</span><span>{x.retired_reason?'retired':'current'}</span><small>{x.retired_reason||`difficulty ${x.difficulty_default}`}</small></li>)}</ul><p className="tiny subdued">Versions only increase and are never reused; retired plans cannot authorize a release.</p></details>;
}

export function ContractorNotice({rs}:{rs?:import('@/lib/types').Pricing['ruleset']}){
  if(!rs||rs.contractor_approved)return null;
  return <div className="notice info" role="note"><Info size={16}/><span><strong>Quantity rules not contractor-approved.</strong> {rs.contractor_note}</span></div>;
}

export function BlockerList({exceptions,codes}:{exceptions:Exception[];codes?:string[]}){
  const open=exceptions.filter(e=>(e.blocking||e.severity==='blocking')&&(!codes||codes.includes(e.code||'')));
  if(!open.length)return null;
  return <ul className="blocker-list" aria-label="Pricing blockers">{open.map(e=><li key={e.exception_id}><CircleAlert size={15}/><span><strong>{e.code}</strong> {BLOCKER_TEXT[e.code||'']||e.question}</span></li>)}</ul>;
}

export function RulesetForm({ex,project,busy,onSubmit}:{ex:Exception;project:Project;busy:boolean;onSubmit:(b:{by:string;note:string;ruleset_sha256:string})=>void}){
  const [by,setBy]=useState('');const [note,setNote]=useState('');
  const rs=project.pricing?.ruleset;
  const sha=ex.required_decision?.sha256||'';
  return <section className="card mini-card form-card" aria-label="Quantity ruleset approval">
    <p className="section-label">TYPED DECISION / QUANTITY RULESET</p><h3>Approve the quantity rules</h3>
    <p className="muted">{ex.question}</p>
    <dl className="ro-dl"><dt>Ruleset</dt><dd>{rs?.ruleset_id} v{rs?.version}</dd><dt>Status</dt><dd>{rs?.status?.replaceAll('_',' ')||'draft'}</dd><dt>Digest</dt><dd className="mono">{sha.slice(0,16)}…</dd></dl>
    <div className="input-stack"><label>Your name (self-declared, not verified)</label><input value={by} onChange={e=>setBy(e.target.value)} placeholder="Any name; recorded as self-declared"/>
      <label>Decision note</label><textarea rows={3} value={note} onChange={e=>setNote(e.target.value)} placeholder="What did you review?"/></div>
    <SelfDeclared/>
    <button className="btn primary full" disabled={busy||!by.trim()||!note.trim()||!sha} onClick={()=>onSubmit({by:by.trim(),note:note.trim(),ruleset_sha256:sha})}>{busy?'Recording…':'Approve this exact ruleset'} <ArrowRight size={16}/></button>
    {rs&&!rs.contractor_approved&&<div className="guardrail"><CircleAlert size={19}/><span><strong>Contractor approval outstanding.</strong> {rs.contractor_note}</span></div>}
    <p className="tiny subdued">The approval is bound to the digest shown. Any edit to the rules voids it.</p>
  </section>;
}

type SchedRow={classification:string;base_rate:string;fringe_rate:string};
type RoleRow={classification:string;base_rate:string;fringe_rate:string;status:string;conf:string;src:string};
const blankRole:RoleRow={classification:'',base_rate:'',fringe_rate:'',status:'',conf:'',src:''};
// FICTIONAL demonstration decision FDB-DP001, offered so a judge need not type a schedule. Still submitted by a named person.
const FICTIONAL={det:{decision_id:'FDB-DP001',modification:'0',date:'2026-10-05',valid_through:'2026-12-31',source_ref:'Fictional wage decision, Attachment A'},
  sched:[{classification:'Laborer, common or general',base_rate:'24.50',fringe_rate:'9.10'},{classification:'Power equipment operator, skid steer',base_rate:'29.80',fringe_rate:'11.25'},{classification:'Cement mason, concrete finisher',base_rate:'28.40',fringe_rate:'10.70'}],
  adm:{basis:'per_week',unit_cost:'85',weeks:'4',reason:'',source_ref:'Fictional payroll administrator quote'}};

export function WageForm({project,busy,onSubmit}:{project:Project;busy:boolean;onSubmit:(b:Record<string,unknown>)=>void}){
  const w=project.pricing!.wage;
  const roles=w.roles||[];
  const [det,setDet]=useState({decision_id:'',modification:'',date:'',valid_through:'',source_ref:''});
  const [sched,setSched]=useState<SchedRow[]>([{classification:'',base_rate:'',fringe_rate:''}]);
  const [rows,setRows]=useState<Record<string,RoleRow>>({});
  const [burden,setBurden]=useState({pct:'',source_ref:''});
  const [prodOk,setProdOk]=useState(false);
  const [adm,setAdm]=useState({basis:'per_week',unit_cost:'',weeks:'',reason:'',source_ref:''});
  const [by,setBy]=useState('');const [note,setNote]=useState('');
  const role=(k:string)=>rows[k]||blankRole;
  const setRole=(k:string,p:Partial<RoleRow>)=>setRows(r=>({...r,[k]:{...(r[k]||blankRole),...p}}));
  function pick(k:string,cls:string){setRole(k,{classification:cls});} // the person selects the classification and types the rate and fringe; nothing is copied or preselected
  function fill(){ // loads ONLY the transcribed decision header and schedule. No role is assigned a classification, rate or fringe, and nothing is affirmed.
    setDet(FICTIONAL.det);setSched(FICTIONAL.sched);setAdm(FICTIONAL.adm); // employer burden is NOT preloaded: that rule is pending the owner
  }
  const n=(s:string)=>s.trim()===''?undefined:Number(s);
  function submit(){
    const body:Record<string,unknown>={by:by.trim(),note:note.trim(),
      determination:{decision_id:det.decision_id.trim(),modification:det.modification.trim(),date:det.date.trim(),...(det.valid_through.trim()?{valid_through:det.valid_through.trim()}:{}),source_ref:det.source_ref.trim()},
      schedule:sched.filter(s=>s.classification.trim()).map(s=>({classification:s.classification.trim(),base_rate:n(s.base_rate),fringe_rate:n(s.fringe_rate)})),
      rows:roles.map(k=>{const r=role(k);return {role_key:k,classification:r.classification.trim(),classification_status:r.status,base_rate:n(r.base_rate),fringe_rate:n(r.fringe_rate),source_ref:r.src.trim(),...(r.conf.trim()?{conformance_ref:r.conf.trim()}:{})};}),
      employer_burden:{pct:n(burden.pct),source_ref:burden.source_ref.trim()},production_rates_approved:prodOk,
      certified_payroll_admin:{basis:adm.basis,...(n(adm.unit_cost)!==undefined?{unit_cost:n(adm.unit_cost)}:{}),...(n(adm.weeks)!==undefined?{weeks:n(adm.weeks)}:{}),...(adm.reason.trim()?{reason:adm.reason.trim()}:{}),source_ref:adm.source_ref.trim()}};
    onSubmit(body);
  }
  const burdenDone=burden.pct.trim()!==''&&burden.source_ref.trim()!=='';
  const rolesDone=roles.length>0&&roles.every(k=>{const r=role(k);return !!r.classification.trim()&&r.base_rate.trim()!==''&&r.fringe_rate.trim()!==''&&!!r.status&&!!r.src.trim();});
  const ready=!!by.trim()&&!!note.trim()&&!!det.decision_id.trim()&&rolesDone&&burdenDone&&prodOk;
  return <section className="card mini-card form-card wage-form" aria-label="Davis-Bacon wage determination">
    <p className="section-label">TYPED DECISION / PREVAILING WAGE</p><h3>Record the wage determination</h3>
    <p className="muted">Davis-Bacon applies to this fictional project. Labor stays unpriced until a named person transcribes the wage decision, assigns each crew role a classification, and states the burden and payroll-administration basis.</p>
    <button type="button" className="btn outlined full" onClick={fill}>Load the fictional decision header and schedule (FDB-DP001)</button>
    <p className="tiny subdued">Fictional decision data for the demo only. This fills the decision header and its schedule, nothing else. You choose each crew role's classification and type its base rate and fringe, type the employer burden and its source, affirm the production rates, name yourself and submit. The decision has no fence-erector classification: that assignment is yours.</p>
    <div className="input-stack">
      <label>Wage decision id</label><input value={det.decision_id} onChange={e=>setDet({...det,decision_id:e.target.value})}/>
      <div className="wage-grid"><div><label>Modification</label><input value={det.modification} onChange={e=>setDet({...det,modification:e.target.value})} placeholder="0"/></div><div><label>Decision date</label><input value={det.date} onChange={e=>setDet({...det,date:e.target.value})} placeholder="YYYY-MM-DD"/></div><div><label>Valid through</label><input value={det.valid_through} onChange={e=>setDet({...det,valid_through:e.target.value})} placeholder="YYYY-MM-DD"/></div></div>
      <label>Decision source reference</label><input value={det.source_ref} onChange={e=>setDet({...det,source_ref:e.target.value})}/>
      <p className="section-label">DECISION SCHEDULE (as transcribed)</p>
      {sched.map((s,i)=><div className="wage-grid sched" key={i}><input aria-label={`Schedule classification ${i+1}`} list="wage-classes" value={s.classification} onChange={e=>setSched(sched.map((x,j)=>j===i?{...x,classification:e.target.value}:x))} placeholder="Classification"/><input aria-label={`Schedule base rate ${i+1}`} value={s.base_rate} onChange={e=>setSched(sched.map((x,j)=>j===i?{...x,base_rate:e.target.value}:x))} placeholder="Base $/h"/><input aria-label={`Schedule fringe rate ${i+1}`} value={s.fringe_rate} onChange={e=>setSched(sched.map((x,j)=>j===i?{...x,fringe_rate:e.target.value}:x))} placeholder="Fringe $/h"/></div>)}
      <button type="button" className="btn ghost" onClick={()=>setSched([...sched,{classification:'',base_rate:'',fringe_rate:''}])} disabled={sched.length>=8}>Add schedule row</button>
      <datalist id="wage-classes">{sched.filter(s=>s.classification).map(s=><option key={s.classification} value={s.classification}/>)}</datalist>
      <p className="section-label">CLASSIFICATION BY CREW ROLE</p>
      {roles.map(k=>{const r=role(k);return <div className="role-card" key={k}><strong>{w.role_names?.[k]||k}</strong>
        <input aria-label={`${w.role_names?.[k]||k} classification`} list="wage-classes" value={r.classification} onChange={e=>pick(k,e.target.value)} placeholder="Classification"/>
        <div className="wage-grid"><input aria-label={`${w.role_names?.[k]||k} base rate`} value={r.base_rate} onChange={e=>setRole(k,{base_rate:e.target.value})} placeholder="Base $/h"/><input aria-label={`${w.role_names?.[k]||k} fringe rate`} value={r.fringe_rate} onChange={e=>setRole(k,{fringe_rate:e.target.value})} placeholder="Fringe $/h"/>
          <select aria-label={`${w.role_names?.[k]||k} classification status`} value={r.status} onChange={e=>setRole(k,{status:e.target.value})}><option value="">Select status…</option><option value="listed">Listed in the decision</option><option value="proposed_for_conformance">Not listed · conformance proposed</option><option value="approved_conformance">Not listed · conformance approved</option></select></div>
        {r.status==='approved_conformance'&&<input aria-label={`${w.role_names?.[k]||k} conformance reference`} value={r.conf} onChange={e=>setRole(k,{conf:e.target.value})} placeholder="Conformance approval reference"/>}
        <input aria-label={`${w.role_names?.[k]||k} source reference`} value={r.src} onChange={e=>setRole(k,{src:e.target.value})} placeholder="Source reference"/></div>;})}
      <p className="section-label">EMPLOYER COSTS AND PAYROLL</p>
      <div className="wage-grid"><div><label>Employer burden (fraction of wages)</label><input value={burden.pct} onChange={e=>setBurden({...burden,pct:e.target.value})} placeholder="e.g. 0.20"/></div><div><label>Burden source</label><input value={burden.source_ref} onChange={e=>setBurden({...burden,source_ref:e.target.value})}/></div></div>
      <label className="check"><input type="checkbox" checked={prodOk} onChange={e=>setProdOk(e.target.checked)}/> I affirm the rate book&apos;s production rates for this wage basis</label>
      <div className="wage-grid"><div><label>Certified payroll admin</label><select value={adm.basis} onChange={e=>setAdm({...adm,basis:e.target.value})}><option value="per_week">Per week</option><option value="lump_sum">Lump sum</option><option value="per_crew_hour">Per crew hour</option><option value="not_charged">Not charged</option></select></div><div><label>Unit cost $</label><input value={adm.unit_cost} onChange={e=>setAdm({...adm,unit_cost:e.target.value})}/></div><div><label>Weeks</label><input value={adm.weeks} onChange={e=>setAdm({...adm,weeks:e.target.value})}/></div></div>
      <input aria-label="Payroll admin source reference" value={adm.source_ref} onChange={e=>setAdm({...adm,source_ref:e.target.value})} placeholder="Payroll administration source"/>
      <label>Your name (self-declared, not verified)</label><input value={by} onChange={e=>setBy(e.target.value)} placeholder="Any name; recorded as self-declared"/>
      <label>Decision note</label><textarea rows={2} value={note} onChange={e=>setNote(e.target.value)} placeholder="What did you review?"/>
    </div>
    <SelfDeclared/>
    <button className="btn primary full" disabled={busy||!ready} onClick={submit}>{busy?'Recording…':w.recorded?'Replace wage determination':'Record wage determination'} <ArrowRight size={16}/></button>
    <p className="tiny subdued">The engine checks every row against your transcribed schedule. An incomplete record is kept, but pricing stays blocked and each defect is named.</p>
  </section>;
}

export function CrewPlanner({project,busy,onApprove}:{project:Project;busy:boolean;onApprove:(b:PlanBody&{by:string;note:string})=>void}){
  const pr=project.pricing!;
  const plan=pr.crew_plan;
  const [pref,setPref]=useState(plan?.preferred_crew||'');
  const [assign,setAssign]=useState<Record<string,string>>(plan?.assignments||{});
  const [useDef,setUseDef]=useState(false); // legacy default crews are never selected implicitly; only fleet crews appear here
  const [diff,setDiff]=useState(plan?.difficulty.default||'standard');
  const [over,setOver]=useState<Record<string,string>>(plan?.difficulty.overrides||{});
  const [by,setBy]=useState('');const [note,setNote]=useState('');
  const [pv,setPv]=useState<Preview|null>(null);const [err,setErr]=useState('');const [pending,setPending]=useState(false);
  const seq=useRef(0);
  const planKey=`${project.project_id}:${plan?.plan_version??0}`;
  const lastKey=useRef(planKey);
  useEffect(()=>{ // adopt a newly approved plan as the starting draft
    if(lastKey.current===planKey)return;lastKey.current=planKey;
    setPref(plan?.preferred_crew||'');setAssign(plan?.assignments||{});setUseDef(false);setDiff(plan?.difficulty.default||'standard');setOver(plan?.difficulty.overrides||{});
  },[planKey,plan]);
  const draft=useMemo(()=>({...(pref?{preferred_crew:pref}:{}),assignments:assign,use_default_for_unassigned:useDef,difficulty:{default:diff,overrides:Object.fromEntries(Object.entries(over).filter(([,v])=>v))}}) as PlanBody,[pref,assign,useDef,diff,over]);
  const dep=`${JSON.stringify(draft)}|${project.scope_version}|${pr.wage.cleared}|${project.proposal_digest}`;
  useEffect(()=>{
    const id=++seq.current;setPending(true);
    const t=window.setTimeout(async()=>{
      try{const r=await postJSON<Preview>('/api/demo/crew-plan/preview',draft);if(id===seq.current){setPv(r);setErr('');}}
      catch(e){if(id===seq.current){const x=e as {code?:string;status?:number;retryAfter?:number};
        setErr(x.status===429?`Recalculation paused: too many recalculations${x.retryAfter?`; try again in about ${x.retryAfter}s`:''}. Your draft is kept; change a field to retry.`:e instanceof Error?e.message:'Recalculation failed');setPv(null);}}
      finally{if(id===seq.current)setPending(false);}
    },120);
    return()=>window.clearTimeout(t);
  },[dep]);// eslint-disable-line react-hooks/exhaustive-deps
  // The engine keys the comparison by scenario. With the Base Bid selected both BASE and the (unselected) alternate are present and BASE applies;
  // once Alternate A-1 is selected the alternate is the only scenario. Never fall back to a scenario that is not the selected one.
  const cmpSet:Record<string,Comparison>=pv?.comparison||pr.crew_comparison||{};
  const cmpKeys=Object.keys(cmpSet);
  const cmp:Comparison|undefined=cmpSet['BASE']||(cmpKeys.length===1?cmpSet[cmpKeys[0]]:undefined);
  const crewNames=pr.crews.crews||[];
  const fleetIds=new Set(crewNames.map(c=>c.crew_id));
  const offFleet=[...new Set([...(pref?[pref]:[]),...Object.values(assign)].filter(c=>c&&!fleetIds.has(c)))];
  const e=pv?.economics,est=pv?.estimate;
  const setCrew=(task:string,crew:string)=>setAssign(a=>({...a,[task]:crew}));
  return <section className="card plan-card" aria-label="Crew selection by task">
    <p className="section-label">CREW SELECTION / BY TASK</p><h2>Crew plan</h2>
    {!plan&&<ProvisionalBox p={pr.provisional} wageCleared={!!pr.wage.cleared}/>}
    {pr.plan_history.length>0&&<PlanHistory h={pr.plan_history}/>}
    {plan&&<p className="tiny subdued">Approved plan v{plan.plan_version} by {plan.approved_by}. Changing a crew or difficulty below is a draft until you approve it again, and re-approving gives a new release digest.</p>}
    <div className="plan-controls">
      <label>Preferred crew (applies to tasks you do not set)<select value={pref} onChange={e=>setPref(e.target.value)} aria-label="Preferred crew"><option value="">None</option>{crewNames.map(c=><option key={c.crew_id} value={c.crew_id}>{c.name} · {c.efficiency_pct}%</option>)}</select></label>
      <label>Job difficulty<select value={diff} onChange={e=>setDiff(e.target.value)} aria-label="Job difficulty">{LEVELS.map(l=><option key={l} value={l}>{l[0].toUpperCase()+l.slice(1)}</option>)}</select></label>
    </div>
    <div className="plan-matrix" role="group" aria-label="Crew choice per task">
      {cmp?.tasks.map(t=><div className="plan-row" key={t.task_id} data-task={t.task_id}>
        <div className="plan-task"><strong>{t.task}</strong><small>{typeof t.quantity==='number'?`${num(t.quantity,t.quantity%1?1:0)} ${t.uom}`:'quantity unresolved'} · {t.task_id}</small>
          <label className="plan-diff">Difficulty<select aria-label={`Difficulty for ${t.task}`} value={over[t.driver_key]||''} onChange={e=>setOver(o=>({...o,[t.driver_key]:e.target.value}))}><option value="">Job default</option>{LEVELS.map(l=><option key={l} value={l}>{l[0].toUpperCase()+l.slice(1)}</option>)}</select></label></div>
        <div className="plan-cells" role="radiogroup" aria-label={`Crew for ${t.task}`}>
          {[...t.candidates].sort((a,b)=>a.crew_id.localeCompare(b.crew_id)).map(c=>{
            const nm=c.name||c.description||c.crew_id;
            return <button type="button" role="radio" key={c.crew_id} data-crew={c.crew_id} data-task={t.task_id} data-eligible={c.eligible} aria-checked={c.selected} disabled={!c.eligible} aria-disabled={!c.eligible}
              className={`plan-cell${c.selected?' sel':''}${c.eligible?'':' inelig'}`} onClick={()=>setCrew(t.task_id,c.crew_id)}>
              <span className="pc-head"><strong>{nm}</strong><i>{c.efficiency_pct??'—'}%</i></span>
              {c.eligible?(typeof c.crew_hours==='number'?<span className="pc-body"><span>{num(c.crew_hours)} crew-h · {num(c.worker_hours)} worker-h</span><span>{num(c.duration_days,2)} crew-d{c.hours_only?'':` · ${usd(c.labor_cost)}`}</span>{c.hours_only&&<em>cost withheld: wages not cleared</em>}</span>:<span className="pc-body"><em>not calculable</em></span>)
                :<span className="pc-why">Not eligible: {(c.reasons_display?.length?c.reasons_display:c.reasons).join('; ')}</span>}
            </button>;})}
        </div>
      </div>)}
    </div>
    <div className={`plan-totals${pending?' pending':''}`} aria-live="polite" aria-label="Recalculated totals">
      <div className="plan-totals-head"><strong>{plan&&pv?.valid?'Draft recalculation':'Provisional recalculation'}</strong><span className="mini-tag">{pending?'RECALCULATING…':'ENGINE RESULT · DRAFT'}</span></div>
      {err&&<p className="tiny warning-text" role="alert">{err}</p>}
      {pv&&!pv.valid&&<ul className="blocker-list">{(()=>{const ns=pv.problems.filter(p=>p.code==='CREW_NOT_SELECTED');const rest=pv.problems.filter(p=>p.code!=='CREW_NOT_SELECTED');return [...(ns.length?[<li key="ns"><CircleAlert size={15}/><span><strong>CREW_NOT_SELECTED</strong> {ns.length} task{ns.length===1?'':'s'} still need a crew: choose a preferred crew or select a crew per task. Nothing is assumed.</span></li>]:[]),...rest.map((p,i)=><li key={i}><CircleAlert size={15}/><span><strong>{p.code}</strong> {p.message_display}</span></li>)];})()}</ul>}
      {pv&&pv.valid&&!est&&<div className="blocked-note"><LockKeyhole size={16}/><span><strong>Pricing blocked.</strong> Hours and durations above are provisional productivity only; no labor cost or total exists yet.{pv.pricing_blocked_by.length>0&&<> Open: {pv.pricing_blocked_by.map(c=>BLOCKER_TEXT[c]||c).join(' ')}</>}</span></div>}
      {est&&e&&<dl className="totals-grid">
        <div><dt>Total estimate</dt><dd data-testid="draft-total">{usd(est.price_total)}</dd></div>
        <div><dt>Labor cost</dt><dd data-testid="draft-labor">{usd(est.labor_subtotal)}</dd></div>
        <div><dt>Crew hours</dt><dd data-testid="draft-crew-hours">{num(est.crew_hours)}</dd></div>
        <div><dt>Worker-hours</dt><dd data-testid="draft-worker-hours">{num(est.worker_hours)}</dd></div>
        <div><dt>Crew-days (effort)</dt><dd data-testid="draft-days">{num(est.crew_days,2)}</dd></div>
        <div><dt>Estimated gross profit (at bid)</dt><dd data-testid="draft-gp">{usd(e.gross_profit)} · {pctf(e.gross_margin_pct)}</dd></div>
        <div><dt>Estimated net profit (at bid)</dt><dd data-testid="draft-np">{usd(e.net_profit)} · {pctf(e.net_margin_pct)}</dd></div>
      </dl>}
      {est&&e&&<p className="tiny subdued">Crew-days are effort (crew-hours ÷ workday), not calendar duration; scheduling is not modeled. Gross and net profit are estimated at bid from the engine&apos;s markup lines; not realized profit. {e.basis}.</p>}
    </div>
    <div className="input-stack plan-approve">
      <label>Your name (self-declared, not verified)</label><input aria-label="Crew plan approver name" value={by} onChange={e=>setBy(e.target.value)} placeholder="Any name; recorded as self-declared"/>
      <label>Decision note</label><textarea aria-label="Crew plan note" rows={2} value={note} onChange={e=>setNote(e.target.value)} placeholder="Why these crews and this difficulty?"/>
    </div>
    {offFleet.length>0&&<p className="tiny warning-text" role="alert" data-testid="off-fleet">Not an active fleet crew: {offFleet.join(', ')}. Choose one of the four fleet crews before approving.</p>}
    <SelfDeclared/>
    <button className="btn primary full" disabled={busy||pending||!pv?.valid||!by.trim()||!note.trim()||offFleet.length>0} onClick={()=>onApprove({...draft,by:by.trim(),note:note.trim()})}>{busy?'Recording…':plan?'Approve revised crew plan':'Approve crew plan'} <ArrowRight size={16}/></button>
    <p className="tiny subdued">Approval is checked again by the engine; a crew without the required operator is refused there even if this screen is bypassed.</p>
  </section>;
}

export function EstimateDetail({view,econ}:{view:EstimateView;econ:Economics|null}){
  return <>
    <div className="table-scroll"><table className="data-table" aria-label="Estimate breakdown"><thead><tr><th>Component</th><th>Amount</th></tr></thead><tbody>
      {view.breakdown.map(b=><tr key={b.key} className={['direct_cost','price_total'].includes(b.key)?'sum':''}><td>{b.label}</td><td data-testid={`est-${b.key}`}>{usd(b.amount)}</td></tr>)}
    </tbody></table></div>
    {econ&&<dl className="totals-grid" aria-label="Estimated profit"><div><dt>Estimated gross profit (at bid)</dt><dd data-testid="rel-gp">{usd(econ.gross_profit)} · {pctf(econ.gross_margin_pct)}</dd></div><div><dt>Estimated net profit (at bid)</dt><dd data-testid="rel-np">{usd(econ.net_profit)} · {pctf(econ.net_margin_pct)}</dd></div></dl>}
    {econ&&<p className="tiny subdued" data-testid="econ-note">Estimated at bid; not realized profit and not approved accounting. {econ.basis}.</p>}
    <p className="section-label">LABOR BY TASK</p>
    <div className="table-scroll"><table className="data-table" aria-label="Labor lines"><thead><tr><th>Task</th><th>Crew</th><th>Crew-h</th><th>Worker-h</th><th>Crew-days</th><th>Labor</th></tr></thead><tbody>
      {view.labor_lines.map(l=><tr key={l.task_id} data-task={l.task_id}><td>{l.task}</td><td>{l.crew_name} · {l.efficiency_pct}% · {l.difficulty_level}</td><td>{num(l.crew_hours)}</td><td>{num(l.worker_hours)}</td><td>{num(l.duration_days,2)}</td><td>{usd(l.extended)}</td></tr>)}
      <tr className="sum"><td colSpan={2}>All tasks</td><td>{num(view.labor_totals.crew_hours)}</td><td>{num(view.labor_totals.worker_hours)}</td><td>{num(view.labor_totals.crew_days,2)}</td><td/></tr>
    </tbody></table></div>
    {view.alternates.length>0&&<p className="tiny subdued">Alternate pricing from the same engine run: {view.alternates.map(a=>`${a.scope_ref} ${usd(a.price_total)}`).join(' · ')}.</p>}
    {view.advisories.length>0&&<div className="notice info"><Info size={16}/><span>{view.advisories.join(' ')}</span></div>}
  </>;
}

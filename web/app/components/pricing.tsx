'use client';
// Display and input components for the real pricing integration. NOTHING here calculates money, hours or digests:
// every figure shown is returned by the Python engine (preview or approved state); this file only formats and selects.
import {useEffect, useMemo, useRef, useState} from 'react';
import {CircleAlert, Info, LockKeyhole, ArrowRight} from 'lucide-react';
import type {Comparison, Economics, EstimateView, Exception, PlanBody, Preview, Project} from '@/lib/types';
import {crewLook,crewStatus,hasRun} from '@/lib/crew-view';

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
  CREW_PLAN_REQUIRED:'A named person must approve the crew plan (one crew for the job and job difficulty).',
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
  adm:{basis:'not_charged',unit_cost:'',weeks:'',reason:'The pinned workbook carries no certified-payroll administration line; nothing is charged.',source_ref:'Pinned workbook reference_pricing_workbook_v2_3_0 (owner decision)'}};

// PRESET RECORDED BY JORDAN. Loaded into the form for review; never submitted on load. The engine never chooses a classification: the named person
// who submits the form affirms every value. Each value carries its source (workbook Roles sheet v2.3.0, or the fictional wage decision FDB-DP001).
const PRESET_BY='Preset recorded by Jordan';
type PresetRole={cls:string;base:string;fringe:string;baseSrc:string;fringeSrc:string;raised?:string};
const PRESET_ROLES:Record<string,PresetRole>={
  'Foreman':{cls:'Laborer, common or general',base:'32.00',fringe:'9.10',baseSrc:'workbook Roles sheet',fringeSrc:'FDB-DP001'},
  'Installer':{cls:'Laborer, common or general',base:'26.00',fringe:'9.10',baseSrc:'workbook Roles sheet',fringeSrc:'FDB-DP001'},
  'Laborer':{cls:'Laborer, common or general',base:'24.50',fringe:'9.10',baseSrc:'FDB-DP001',fringeSrc:'FDB-DP001',raised:'Laborer base raised from workbook $20.00 to the wage decision $24.50'},
  'Equipment operator':{cls:'Power equipment operator, skid steer',base:'29.80',fringe:'11.25',baseSrc:'FDB-DP001',fringeSrc:'FDB-DP001',raised:'Equipment operator base raised from workbook $28.00 to the wage decision $29.80'},
};
const PRESET_BURDEN={pct:'0.35',source_ref:'Workbook Roles sheet, employer burden 35%'};
const presetRow=(pr:PresetRole):RoleRow=>({classification:pr.cls,base_rate:pr.base,fringe_rate:pr.fringe,status:'listed',conf:'',src:`Base: ${pr.baseSrc}. Fringe: ${pr.fringeSrc}. ${PRESET_BY}.${pr.raised?' '+pr.raised+'.':''}`});
const sameAsPreset=(r:RoleRow,pr?:PresetRole)=>!!pr&&r.classification===pr.cls&&r.base_rate===pr.base&&r.fringe_rate===pr.fringe&&r.status==='listed';

export function WageForm({project,busy,onSubmit}:{project:Project;busy:boolean;onSubmit:(b:Record<string,unknown>)=>void}){
  const w=project.pricing!.wage;
  const roles=w.roles||[];
  const presetRows=()=>Object.fromEntries(roles.filter(k=>PRESET_ROLES[w.role_names?.[k]||'']).map(k=>[k,presetRow(PRESET_ROLES[w.role_names![k]])])) as Record<string,RoleRow>;
  const [det,setDet]=useState(FICTIONAL.det);
  const [sched,setSched]=useState<SchedRow[]>(FICTIONAL.sched);
  const [rows,setRows]=useState<Record<string,RoleRow>>(presetRows);
  const [burden,setBurden]=useState(PRESET_BURDEN);
  const [affirm,setAffirm]=useState(false);
  const [prodOk,setProdOk]=useState(false);
  const [adm,setAdm]=useState(FICTIONAL.adm);
  const [by,setBy]=useState('');const [note,setNote]=useState('');
  const role=(k:string)=>rows[k]||blankRole;
  const setRole=(k:string,p:Partial<RoleRow>)=>setRows(r=>({...r,[k]:{...(r[k]||blankRole),...p}}));
  function pick(k:string,cls:string){setRole(k,{classification:cls});} // the person selects the classification and types the rate and fringe; nothing is copied or preselected
  function fill(){ // reload the recorded preset (nothing is submitted or affirmed)
    setDet(FICTIONAL.det);setSched(FICTIONAL.sched);setAdm(FICTIONAL.adm);setRows(presetRows());setBurden(PRESET_BURDEN);setAffirm(false);
  }
  function clearAll(){setRows({});setBurden({pct:'',source_ref:''});setAffirm(false);}
  const n=(s:string)=>s.trim()===''?undefined:Number(s);
  function submit(){
    const touched=roles.filter(k=>PRESET_ROLES[w.role_names?.[k]||'']);
    const kept=touched.filter(k=>sameAsPreset(role(k),PRESET_ROLES[w.role_names![k]])),edited=touched.filter(k=>!kept.includes(k));
    const prov=[kept.length?`${PRESET_BY}; kept as recorded: ${kept.map(k=>w.role_names?.[k]||k).join(', ')}.`:'',...kept.map(k=>PRESET_ROLES[w.role_names![k]].raised||'').filter(Boolean).map(t=>t+'.'),edited.length?`Edited by the named person after the preset: ${edited.map(k=>w.role_names?.[k]||k).join(', ')}.`:'',burden.pct===PRESET_BURDEN.pct?`Employer burden 35% from the workbook Roles sheet.`:''].filter(Boolean).join(' ');
    const body:Record<string,unknown>={by:by.trim(),note:(note.trim()+(prov?' | '+prov:'')).slice(0,1900),
      determination:{decision_id:det.decision_id.trim(),modification:det.modification.trim(),date:det.date.trim(),...(det.valid_through.trim()?{valid_through:det.valid_through.trim()}:{}),source_ref:det.source_ref.trim()},
      schedule:sched.filter(s=>s.classification.trim()).map(s=>({classification:s.classification.trim(),base_rate:n(s.base_rate),fringe_rate:n(s.fringe_rate)})),
      rows:roles.map(k=>{const r=role(k);return {role_key:k,classification:r.classification.trim(),classification_status:r.status,base_rate:n(r.base_rate),fringe_rate:n(r.fringe_rate),source_ref:r.src.trim(),...(r.conf.trim()?{conformance_ref:r.conf.trim()}:{})};}),
      employer_burden:{pct:n(burden.pct),source_ref:burden.source_ref.trim()},production_rates_approved:prodOk,
      certified_payroll_admin:{basis:adm.basis,...(n(adm.unit_cost)!==undefined?{unit_cost:n(adm.unit_cost)}:{}),...(n(adm.weeks)!==undefined?{weeks:n(adm.weeks)}:{}),...(adm.reason.trim()?{reason:adm.reason.trim()}:{}),source_ref:adm.source_ref.trim()}};
    onSubmit(body);
  }
  // Advisory only: the engine is authoritative. The wage decision is a floor: a listed classification needs base and fringe each at or above the schedule (WAGE_RATE_BELOW_DECISION otherwise).
  const schedFor=(r:RoleRow)=>sched.find(x=>x.classification.trim().toLowerCase()===r.classification.trim().toLowerCase()&&r.classification.trim()!=='');
  const below=roles.filter(k=>{const r=role(k);const sc=schedFor(r);return !!sc&&r.status==='listed'&&r.base_rate.trim()!==''&&(Number(r.base_rate)<Number(sc.base_rate)||Number(r.fringe_rate)<Number(sc.fringe_rate));});
  const above=roles.filter(k=>{const r=role(k);const sc=schedFor(r);return !!sc&&r.status==='listed'&&r.base_rate.trim()!==''&&!below.includes(k)&&(Number(r.base_rate)>Number(sc.base_rate)||Number(r.fringe_rate)>Number(sc.fringe_rate));});
  const burdenDone=burden.pct.trim()!==''&&burden.source_ref.trim()!=='';
  const rolesDone=roles.length>0&&roles.every(k=>{const r=role(k);return !!r.classification.trim()&&r.base_rate.trim()!==''&&r.fringe_rate.trim()!==''&&!!r.status&&!!r.src.trim();});
  const ready=!!by.trim()&&!!note.trim()&&!!det.decision_id.trim()&&rolesDone&&burdenDone&&prodOk&&affirm;
  return <section className="card mini-card form-card wage-form" aria-label="Davis-Bacon wage determination">
    <p className="section-label">TYPED DECISION / PREVAILING WAGE</p><h3>Record the wage determination</h3>
    <p className="muted">Davis-Bacon applies to this fictional project. Labor stays unpriced until a named person transcribes the wage decision, assigns each crew role a classification, and states the burden and payroll-administration basis.</p>
    <p className="section-label" data-testid="wage-preset-label">{PRESET_BY}</p>
    <button type="button" className="btn outlined full" onClick={fill}>Reload the recorded preset</button><button type="button" className="btn ghost" onClick={clearAll}>Clear the preset</button>
    <p className="tiny subdued">The form is filled from the preset recorded by Jordan, with each value's source shown. Nothing is submitted until you review it, affirm it and name yourself. The engine never chooses a classification. Decision FDB-DP001 is fictional demo data and has no fence-erector classification: mapping a crew role to Laborer or Power equipment operator is the recorded preset's choice, not the engine's.</p>
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
        {(()=>{const pr=PRESET_ROLES[w.role_names?.[k]||''];return pr?<p className="tiny subdued" data-testid={`preset-source-${k}`}>{sameAsPreset(r,pr)?`Base ${pr.base}: ${pr.baseSrc}. Fringe ${pr.fringe}: ${pr.fringeSrc}.${pr.raised?' '+pr.raised+'.':''} (${PRESET_BY})`:'Edited from the preset by you.'}</p>:null;})()}<input aria-label={`${w.role_names?.[k]||k} source reference`} value={r.src} onChange={e=>setRole(k,{src:e.target.value})} placeholder="Source reference"/></div>;})}
      <p className="section-label">EMPLOYER COSTS AND PAYROLL</p>
      <div className="wage-grid"><div><label>Employer burden (fraction of wages)</label><input value={burden.pct} onChange={e=>setBurden({...burden,pct:e.target.value})} placeholder="e.g. 0.20"/></div><div><label>Burden source</label><input value={burden.source_ref} onChange={e=>setBurden({...burden,source_ref:e.target.value})}/></div></div>
      <label className="check"><input type="checkbox" checked={prodOk} onChange={e=>setProdOk(e.target.checked)}/> I affirm the rate book&apos;s production rates for this wage basis</label>
      <div className="wage-grid"><div><label>Certified payroll admin</label><select value={adm.basis} onChange={e=>setAdm({...adm,basis:e.target.value})}><option value="per_week">Per week</option><option value="lump_sum">Lump sum</option><option value="per_crew_hour">Per crew hour</option><option value="not_charged">Not charged</option></select></div>{adm.basis!=='not_charged'&&<><div><label>Unit cost $</label><input value={adm.unit_cost} onChange={e=>setAdm({...adm,unit_cost:e.target.value})}/></div><div><label>Weeks</label><input value={adm.weeks} onChange={e=>setAdm({...adm,weeks:e.target.value})}/></div></>}</div>
      {adm.basis==='not_charged'&&<input aria-label="Certified payroll not-charged reason" data-testid="payroll-reason" value={adm.reason} onChange={e=>setAdm({...adm,reason:e.target.value})} placeholder="Why nothing is charged"/>}
      <input aria-label="Payroll admin source reference" value={adm.source_ref} onChange={e=>setAdm({...adm,source_ref:e.target.value})} placeholder="Payroll administration source"/>
      <label className="check"><input type="checkbox" data-testid="wage-affirm" checked={affirm} onChange={e=>setAffirm(e.target.checked)}/> I have reviewed every value above (classification, base, fringe, burden) and affirm this wage record</label>
      <label>Your name (self-declared, not verified)</label><input value={by} onChange={e=>setBy(e.target.value)} placeholder="Any name; recorded as self-declared"/>
      <label>Decision note</label><textarea rows={2} value={note} onChange={e=>setNote(e.target.value)} placeholder="What did you review?"/>
    </div>
    <SelfDeclared/>
    {below.length>0&&<p className="tiny warning-text" data-testid="wage-below" role="status">For {below.map(k=>w.role_names?.[k]||k).join(', ')} the base or fringe is BELOW the wage decision for the chosen classification. The engine will keep labor blocked (WAGE_RATE_BELOW_DECISION).</p>}{above.length>0&&<p className="tiny subdued" data-testid="wage-above">For {above.map(k=>w.role_names?.[k]||k).join(', ')} the recorded rate is above the wage decision. That is allowed: the recorded rate prices and the export flags it as above the decision.</p>}<button className="btn primary full" disabled={busy||!ready} onClick={submit}>{busy?'Recording…':w.recorded?'Replace wage determination':'Record wage determination'} <ArrowRight size={16}/></button>
    <p className="tiny subdued">The engine checks every row against your transcribed schedule. An incomplete record is kept, but pricing stays blocked and each defect is named.</p>
  </section>;
}

export function CrewPlanner({project,busy,onApprove}:{project:Project;busy:boolean;onApprove:(b:PlanBody&{by:string;note:string})=>void}){
  // ONE crew for the whole job. Every figure on a card comes from the engine: a draft preview per crew (never calculated here).
  const pr=project.pricing!;
  const plan=pr.crew_plan;
  const crewList=pr.crews.crews||[];
  const adopted=plan&&plan.preferred_crew&&Object.keys(plan.assignments||{}).length===0?plan.preferred_crew:'';
  const [sel,setSel]=useState(adopted);        // nothing is preselected unless the approved plan was already a one-crew plan
  const [diff,setDiff]=useState(plan?.difficulty.default||'standard');
  const [over,setOver]=useState<Record<string,string>>(plan?.difficulty.overrides||{});
  const [by,setBy]=useState('');const [note,setNote]=useState('');const [avail,setAvail]=useState(false);
  const [pv,setPv]=useState<Record<string,Preview>>({});const [base,setBase]=useState<Preview|null>(null);
  const [err,setErr]=useState('');const [pending,setPending]=useState(false);
  const seq=useRef(0);
  const planKey=`${project.project_id}:${plan?.plan_version??0}`;
  const lastKey=useRef(planKey);
  useEffect(()=>{if(lastKey.current===planKey)return;lastKey.current=planKey;setSel(adopted);setDiff(plan?.difficulty.default||'standard');setOver(plan?.difficulty.overrides||{});setAvail(false);},[planKey,plan,adopted]);
  const difficulty=useMemo(()=>({default:diff,overrides:Object.fromEntries(Object.entries(over).filter(([,v])=>v))}),[diff,over]);
  const fleetIds=useMemo(()=>crewList.map(c=>c.crew_id),[crewList]);
  const dep=`${JSON.stringify(difficulty)}|${fleetIds.join(',')}|${project.scope_version}|${pr.wage.cleared}|${project.proposal_digest}`;
  useEffect(()=>{
    const id=++seq.current;setPending(true);
    const t=window.setTimeout(async()=>{
      try{
        const b=await postJSON<Preview>('/api/demo/crew-plan/preview',{assignments:{},use_default_for_unassigned:false,difficulty});
        const out:Record<string,Preview>={};
        for(const cid of fleetIds){out[cid]=await postJSON<Preview>('/api/demo/crew-plan/preview',{preferred_crew:cid,assignments:{},use_default_for_unassigned:false,difficulty});}
        if(id===seq.current){setBase(b);setPv(out);setErr('');}
      }catch(e){if(id===seq.current){const x=e as {status?:number;retryAfter?:number};
        setErr(x.status===429?`Recalculation paused: too many recalculations${x.retryAfter?`; try again in about ${x.retryAfter}s`:''}. Change a field to retry.`:e instanceof Error?e.message:'Recalculation failed');}}
      finally{if(id===seq.current)setPending(false);}
    },150);
    return()=>window.clearTimeout(t);
  },[dep]);// eslint-disable-line react-hooks/exhaustive-deps
  const cmpOf=(p?:Preview|null):Comparison|undefined=>{const s=p?.comparison||undefined;if(!s)return undefined;const k=Object.keys(s);return s['BASE']||(k.length===1?s[k[0]]:undefined);};
  const cmp=cmpOf(base)||cmpOf(pr.crew_comparison?{comparison:pr.crew_comparison} as unknown as Preview:null);
  // Why a crew cannot be chosen for the whole job: the engine's own reasons for every task it is ineligible for, de-duplicated.
  const status=(cid:string)=>crewStatus(cmp,cid);
  const ran=hasRun(cmp);
  const crewRow=(cid:string)=>(cmp as unknown as {crews?:{crew_id:string;crew_days?:number;crew_hours?:number;labor_cost?:number;complete?:boolean}[]}|undefined)?.crews?.find(r=>r.crew_id===cid);
  // Labels are only ever "lowest bid" and "fastest" (least crew-days), among crews the engine lets you choose. There is no profit ranking.
  const okIds=crewList.filter(c=>status(c.crew_id).ok&&(!pv[c.crew_id]||pv[c.crew_id].valid)).map(c=>c.crew_id);
  const minBy=(f:(id:string)=>number|undefined)=>{const v=okIds.map(i=>[i,f(i)] as const).filter((x):x is readonly [string,number]=>typeof x[1]==='number');return v.length>1?v.reduce((a,b)=>b[1]<a[1]?b:a)[0]:null;};
  const lowestId=minBy(i=>pv[i]?.estimate?.price_total),fastestId=minBy(i=>crewRow(i)?.crew_days);
  const mine=sel?pv[sel]:undefined;
  const e=mine?.economics,est=mine?.estimate;
  return <section className="card plan-card" aria-label="Crew selection for the job">
    <p className="section-label">CREW SELECTION / ONE CREW FOR THE JOB</p><h2>Crew for this job</h2>
    {!plan&&<ProvisionalBox p={pr.provisional} wageCleared={!!pr.wage.cleared}/>}
    {pr.plan_history.length>0&&<PlanHistory h={pr.plan_history}/>}
    {plan&&<p className="tiny subdued">Approved plan v{plan.plan_version} by {plan.approved_by}.{adopted?'':' That plan assigned crews task by task; choose one crew for the whole job to replace it.'} Changing the crew below is a draft until you approve it again, and re-approving gives a new release digest.</p>}
    <div className="plan-controls">
      <label>Job difficulty<select value={diff} onChange={x=>setDiff(x.target.value)} aria-label="Job difficulty">{LEVELS.map(l=><option key={l} value={l}>{l[0].toUpperCase()+l.slice(1)}</option>)}</select></label>
    </div>
    <div className="crew-cards" role="radiogroup" aria-label="Crew for the job">
      {crewList.map(c=>{
        const st=status(c.crew_id),row=crewRow(c.crew_id),p=pv[c.crew_id],pe=p?.estimate;
        const on=sel===c.crew_id,can=st.ok&&(!p||p.valid);
        const why=!st.ok?st.reasons:(p&&!p.valid?p.problems.map(x=>x.message_display||x.message):[]);
        return <button type="button" role="radio" key={c.crew_id} data-crew={c.crew_id} data-eligible={can} aria-checked={on} disabled={!can} aria-disabled={!can} className={`crew-card${on?' sel':''}${crewLook(ran,can)==='ineligible'?' inelig':''}`} onClick={()=>setSel(c.crew_id)}>
          <span className="pc-head"><strong>{c.name} <small>({c.crew_id})</small></strong><i>{c.efficiency_pct}% production</i></span>{(lowestId===c.crew_id||fastestId===c.crew_id)&&<span className="pc-badges">{lowestId===c.crew_id&&<em className="mini-tag ok" data-testid="badge-lowest">lowest bid</em>}{fastestId===c.crew_id&&<em className="mini-tag ok" data-testid="badge-fastest">fastest</em>}</span>}
          <span className="tiny subdued" data-testid="crew-comp">{c.composition.map(m=>m.role).join(' · ')}</span>
          {can?<span className="pc-body">
            <span data-testid="card-labor">Job labor cost: <strong>{typeof row?.labor_cost==='number'?usd(row.labor_cost):'withheld: wages not cleared'}</strong></span>
            <span data-testid="card-bid">Total bid: <strong>{pe?usd(pe.price_total):'not available yet'}</strong></span>
            <span data-testid="card-days">Effort: <strong>{num(row?.crew_days,2)} crew-days</strong></span>
          </span>:!ran?<span className="pc-why" data-testid="crew-available"><strong>Available</strong> — eligibility is calculated once the scope is resolved.</span>:<span className="pc-why" data-testid="crew-ineligible"><strong>{c.composition.some(m=>/operator/i.test(m.role))?'Ineligible':'Ineligible (no operator)'}</strong>{why.length?` — ${why.join('; ')}`:' — eligibility is calculated once the scope is resolved.'}</span>}
        </button>;})}
    </div>
    <p className="tiny subdued" data-testid="contract-time">Contract time: not stated in the Project Manual, so none is shown. Crew-days are effort (crew-hours ÷ workday), not calendar duration; scheduling is not modeled and the engine has no crew availability data. Availability is your confirmation below.</p>
    <details><summary className="tiny">Difficulty by task (optional)</summary><div className="plan-controls">{cmp?.tasks.map(t=><label key={t.task_id}>{t.task}<select aria-label={`Difficulty for ${t.task}`} value={over[t.driver_key]||''} onChange={x=>setOver(o=>({...o,[t.driver_key]:x.target.value}))}><option value="">Job default</option>{LEVELS.map(l=><option key={l} value={l}>{l[0].toUpperCase()+l.slice(1)}</option>)}</select></label>)}</div></details>
    <div className={`plan-totals${pending?' pending':''}`} aria-live="polite" aria-label="Recalculated totals">
      <div className="plan-totals-head"><strong>{sel?'Selected crew':'No crew selected'}</strong><span className="mini-tag">{pending?'RECALCULATING…':'ENGINE RESULT · DRAFT'}</span></div>
      {err&&<p className="tiny warning-text" role="alert">{err}</p>}
      {!sel&&<p className="tiny subdued">Choose one crew above. Nothing is assumed.</p>}
      {sel&&mine&&!mine.valid&&<ul className="blocker-list">{mine.problems.map((x,i)=><li key={i}><CircleAlert size={15}/><span><strong>{x.code}</strong> {x.message_display||x.message}</span></li>)}</ul>}
      {sel&&mine&&mine.valid&&!est&&<div className="blocked-note"><LockKeyhole size={16}/><span><strong>Pricing blocked.</strong> No labor cost or total exists yet.{mine.pricing_blocked_by.length>0&&<> Open: {mine.pricing_blocked_by.map(c=>BLOCKER_TEXT[c]||c).join(' ')}</>}</span></div>}
      {est&&e&&<dl className="totals-grid">
        <div><dt>Total estimate</dt><dd data-testid="draft-total">{usd(est.price_total)}</dd></div>
        <div><dt>Labor cost</dt><dd data-testid="draft-labor">{usd(est.labor_subtotal)}</dd></div>
        <div><dt>Crew hours</dt><dd data-testid="draft-crew-hours">{num(est.crew_hours)}</dd></div>
        <div><dt>Worker-hours</dt><dd data-testid="draft-worker-hours">{num(est.worker_hours)}</dd></div>
        <div><dt>Crew-days (effort)</dt><dd data-testid="draft-days">{num(est.crew_days,2)}</dd></div>
      </dl>}
    </div>
    <div className="input-stack plan-approve">
      <label>Your name (self-declared, not verified)</label><input aria-label="Crew plan approver name" value={by} onChange={x=>setBy(x.target.value)} placeholder="Any name; recorded as self-declared"/>
      <label>Decision note</label><textarea aria-label="Crew plan note" rows={2} value={note} onChange={x=>setNote(x.target.value)} placeholder="Why this crew and this difficulty?"/>
      <label className="check-row"><input type="checkbox" data-testid="crew-available" checked={avail} onChange={x=>setAvail(x.target.checked)}/> I confirm this crew is available.</label>
    </div>
    <SelfDeclared/>
    <button className="btn primary full" disabled={busy||pending||!sel||!mine?.valid||!by.trim()||!note.trim()||!avail} onClick={()=>onApprove({preferred_crew:sel,assignments:{},use_default_for_unassigned:false,difficulty,by:by.trim(),note:`${note.trim()} [Attestation by ${by.trim()}: I confirm this crew is available.]`})}>{busy?'Recording…':plan?'Approve revised crew plan':'Approve crew plan'} <ArrowRight size={16}/></button>
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

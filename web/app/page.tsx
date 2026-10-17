'use client';

import { useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, ArrowDownRight, ArrowRight, ArrowUpRight, ArrowLeft, BookOpenText, Check,
  CheckCheck, CheckCircle2, ChevronDown, ChevronRight, CircleAlert, ClipboardCheck,
  Clock3, Download, FileArchive, FileCheck2, FileSearch2, FileText, FolderOpen,
  HardHat, Hash, Info, Layers, LoaderCircle, LockKeyhole, LogOut, PackageOpen,
  RefreshCw, Scale, ShieldCheck, ShieldOff, UploadCloud, X, MessageSquare, Maximize2, Minimize2, SlidersHorizontal, Cpu
} from 'lucide-react';
import {fromEngine} from '@/lib/adapt';
import {crewRows} from '@/lib/crew-view';
import {DocViewer, DocumentPackage, ScopeDraft, ViewCtx, useDp001, useNarrow} from './components/dp001';
import type {Target} from './components/dp001';
import {TakeoffReview,ReadinessBanner} from './components/takeoff';
import {AiFindings} from './components/ai-findings';
import {AddendumPanel} from './components/addendum';
import {headerModeClause,type ConfiguredMode} from '@/lib/parse-mode';
import {notesFor,valueFieldLabel} from '@/lib/exception-notes';
import {ScopeDiscovery} from './components/scope-discovery';
import {BidDesk} from './components/bid-desk';
import {LandingDashboard,bidStatusLabel} from './components/dashboard';
import {FlightRecorder} from './components/flight-recorder';
import {AiActivity} from './components/ai-activity';
import {BlockerList, ContractorNotice, CrewPlanner, EstimateDetail, PlanHistory, RulesetForm, SelfDeclared, WageForm} from './components/pricing';
import type {AuditEvent, CrewData, Portfolio, PortfolioProject, Document, Exception, Fact, Project, ProjectStatus, SourceRef} from '@/lib/types';

type View = 'overview'|'scope'|'labor'|'release'|'takeoff';
const statusTitles:Record<ProjectStatus,string> = {
  uploaded:'Package received',processing:'Analyzing documents',needs_scope_review:'Scope review required',
  needs_labor_review:'Labor review required',ready_for_final_review:'Final approval required',
  released:'Proposal released',held:'Project on hold',failed:'Processing failed'
};
const classifications:Record<string,string> = {
  site_plan:'Site plan',details:'Detail sheet',detail_sheet:'Detail sheet',specification:'Specification',
  addendum:'Addendum',bid_schedule:'Bid schedule',labor_document:'Labor document',drawing:'Drawing'
};
const PREVIEW_UPLOAD_DISABLED=true;
/** The engine's own notes for this exception's gate/class (served with the scope draft from the file the engine loads); empty when there are none, so today's text stays. */
function exceptionNotes(draft:unknown,ex:{affects?:string[];affected_paths?:string[]}|undefined){
  return notesFor((draft as {exception_notes?:Record<string,string>}|null)?.exception_notes,ex?.affects||ex?.affected_paths);
}
function gateFor(status?:ProjectStatus):View|null{
  return status==='needs_scope_review'?'scope':status==='needs_labor_review'?'labor':status==='ready_for_final_review'?'release':null;
}
function friendlyClass(raw?:string){return raw?classifications[raw]||raw.replaceAll('_',' '):'Unclassified'}
function formatValue(value:unknown):string {
  if(value === null || value === undefined) return 'UNRESOLVED';
  if(typeof value==='number') return Number.isInteger(value)?String(value):String(Number(value.toFixed(3)));
  if(typeof value==='string') return value;
  if(typeof value==='boolean') return value?'Yes':'No';
  return 'Structured value';
}
function dollars(n:unknown, currency='USD') {
  return typeof n==='number' && Number.isFinite(n) ? new Intl.NumberFormat('en-US',{style:'currency',currency}).format(n):'—';
}
class ApiError extends Error{
  status:number;code?:string;details?:{code?:string;key?:string}[];engineCodes?:string[];retryAfter?:number;
  constructor(message:string,status:number,extra:{code?:string;details?:{code?:string;key?:string}[];engineCodes?:string[];retryAfter?:number}={}){super(message);this.status=status;Object.assign(this,extra);}
}
// Stable adapter codes (gatehouse-http-adapter.v1-proposed). The engine's own wording is kept as a fallback; these make the cause actionable.
const CODE_TEXT:Record<string,string>=({
  WAGE_ROW_DUPLICATE_ROLE:'Two wage rows use the same role. Each role may appear once. Nothing was recorded; your entries are kept below.',
  WAGE_SCHEDULE_DUPLICATE_CLASSIFICATION:'The wage schedule lists the same classification twice. Nothing was recorded; your entries are kept below.',
  WAGE_HISTORY_UNAVAILABLE:'The wage-decision history for this project cannot be verified, so a new wage decision is refused.',
  DECISION_UNCHANGED:'This decision is identical to the one already in force. Nothing new was recorded.',
  WAGE_MODIFICATION_NOT_HIGHER:'A changed wage determination must carry a higher modification number than the one on record.',
  WAGE_SUPERSESSION_REQUIRED:'This change must formally supersede the wage determination on record (new decision id or higher modification).',
  WAGE_HISTORICALLY_CLEARED:'This wage determination was already cleared earlier in the project history and cannot be re-opened this way.',
  WAGE_MODIFICATION_STALE:'This wage modification is older than the one on record.',
  CREW_NOT_IN_FLEET:'That crew is not one of the four active fleet crews, so it cannot be assigned.',
  RULESET_ALREADY_APPROVED:'This quantity ruleset has already been approved.',
  IDEMPOTENCY_KEY_REUSED:'This decision key was already used for a different decision. Review the form and submit again to create a new decision.',
  IDEMPOTENCY_KEY_REQUIRED:'The decision could not be submitted without a decision key. Reload and try again.',
  TOO_MANY_ASSIGNMENTS:'Too many crew assignments in one request.',
  BODY_TOO_LARGE:'The request was too large.',PREVIEW_BODY_TOO_LARGE:'The preview request was too large.',
  PREVIEW_RATE_LIMITED:'Too many recalculations. The live preview pauses briefly.',
  RATE_LIMITED:'This demo project has reached its decision limit for now.',
  NOT_IMPLEMENTED:'This action is not implemented in this build.',UNAVAILABLE:'The pricing engine is temporarily unavailable.'
} as Record<string,string>);
const ENGINE_TEXT:Record<string,string>={CREW_PLAN_STALE:'The crew plan changed after this estimate was issued; the release digest is no longer current.'};
function explain(e:ApiError):string{
  const base=(e.code&&CODE_TEXT[e.code])||e.message;
  const extra=[...new Set((e.details||[]).map(d=>d.key).filter(Boolean))].slice(0,6);
  const eng=(e.engineCodes||[]).map(c=>ENGINE_TEXT[c]).filter(Boolean)[0];
  const wait=e.status===429&&e.retryAfter?` Try again in about ${e.retryAfter}s.`:'';
  return `${base}${extra.length?` (${extra.join(', ')})`:''}${eng?` ${eng}`:''}${wait}${e.code?` [${e.code}]`:''}`;
}
type Sent={ok:true;replay:boolean;auditId?:string}|{ok:false};
async function readJSON<T>(r:Response):Promise<T>{
  const body=await r.json().catch(()=>({error:`Unexpected HTTP ${r.status}`})) as {error?:string;detail?:string;code?:string;details?:{code?:string;key?:string}[];engine_codes?:string[];retry_after_seconds?:number};
  if(!r.ok){
    const ra=Number(body.retry_after_seconds??r.headers.get('retry-after')??0);
    throw new ApiError(body.error||body.detail||`HTTP ${r.status}`,r.status,{code:body.code,details:body.details,engineCodes:body.engine_codes,retryAfter:Number.isFinite(ra)&&ra>0?Math.ceil(ra):undefined});
  }
  return body as T;
}
function Source({source}:{source:SourceRef}) {
  const ctx=useContext(ViewCtx);
  const known=!!(ctx&&source.doc_id&&ctx.docs[source.doc_id]);
  const body=<><FileText size={13}/><span>{source.sheet||source.filename||source.doc_id||'Unlabeled source'}{source.page?` · p${source.page}`:''}</span>{source.excerpt&&<small>“{source.excerpt}”</small>}</>;
  return known?<button type="button" className="source-chip clickable" title="Show this evidence in the viewer" onClick={()=>ctx!.view({doc_id:source.doc_id!,page:source.page||1,excerpt:(source.excerpt||'').split(' — states ')[0]||undefined})}>{body}</button>:<div className="source-chip">{body}</div>;
}
function SourceList({sources}:{sources?:SourceRef[]}){
  if(!sources?.length)return <p className="tiny subdued">No source region recorded yet.</p>;
  return <div className="source-list">{sources.map((s,i)=><Source source={s} key={`${s.doc_id||s.filename||'doc'}-${i}`}/>)}</div>;
}
function StatusPill({status,demo}:{status:ProjectStatus;demo?:boolean}){
 if(demo)return <span className="status-pill attention" data-testid="status-demo"><span className="status-dot"/>Demonstration release · NOT a bid</span>;
 const color=['released'].includes(status)?'complete':['held','failed','needs_scope_review','needs_labor_review'].includes(status)?'attention':'neutral';
 return <span className={`status-pill ${color}`}><span className="status-dot"/>{statusTitles[status]}</span>;
}

const STATUS_LABEL={bidding:'Bidding',won:'Won',lost:'Lost'} as const;
const money=(n:number|null|undefined)=>typeof n==='number'?`${n<0?'-':''}$${Math.abs(n).toLocaleString('en-US')}`:'n/a';
const pct=(n:number|null|undefined)=>typeof n==='number'?`${n.toFixed(1)}%`:'n/a';

function ProjectNav({portfolio,active,activeSelected,viewPid,open,setOpen,filter,setFilter,onSelect}:{portfolio:Portfolio|null;active?:{name:string;status:string};activeSelected:boolean;viewPid:string|null;open:boolean;setOpen:(b:boolean)=>void;filter:'all'|'bidding'|'won'|'lost';setFilter:(f:'all'|'bidding'|'won'|'lost')=>void;onSelect:(p:PortfolioProject)=>void}){
  const all=portfolio?.projects||[];
  const shown=all.filter(p=>filter==='all'||p.status===filter);
  return <div className="proj-nav">
    <button type="button" className="side-link" aria-expanded={open} onClick={()=>setOpen(!open)}><Layers size={18}/> Projects <span className="proj-count">{all.length}</span><ChevronRight size={15} className={open?'chev open':'chev'}/></button>
    {open&&<div className="proj-body">
      <div className="proj-filters" role="group" aria-label="Filter projects by status">{(['all','bidding','won','lost'] as const).map(f=><button type="button" key={f} aria-pressed={filter===f} className={`chip${filter===f?' on':''}`} onClick={()=>setFilter(f)}>{f==='all'?'All':STATUS_LABEL[f]}</button>)}</div>
      {!all.length?<p className="crew-note">Portfolio unavailable.</p>:<ul className="proj-list" aria-label="Projects (synthetic demonstration data)">{shown.map(p=>{const sel=p.kind==='active_estimating'?activeSelected:viewPid===p.project_id;
        return <li key={p.project_id}><button type="button" className={`proj-row ${p.status}${sel?' selected':''}`} aria-current={sel?'true':undefined} onClick={()=>onSelect(p)}
          title={`${p.name} · ${STATUS_LABEL[p.status]} · ${money(p.bid_amount)}${p.kind==='active_estimating'?' · opens the live demo workspace':' · read-only fictional example'}`}>
          <span className="proj-line"><span className="proj-name">{p.kind==='active_estimating'&&active?active.name:p.name}</span><span className="proj-amt">{p.kind==='active_estimating'&&active?'':money(p.bid_amount)}</span></span>
          <span className="proj-line sub"><span className="proj-status"><i className="proj-dot" aria-hidden="true"/>{p.kind==='active_estimating'&&active?active.status:STATUS_LABEL[p.status]}</span>{p.kind==='active_estimating'&&<span className="proj-tag">Active workspace</span>}</span>
        </button></li>;})}</ul>}
    </div>}
  </div>;
}

function PortfolioSummary({p,crews,onBack}:{p:PortfolioProject;crews?:CrewData;onBack:()=>void}){
  const roles=(name:string)=>crews?.crews?.find(c=>c.name===name)?.composition.map(m=>m.role).join(' · ')||'';
  const rows:[string,string][]=[['Materials',money(p.materials_cost)],['Labor',money(p.labor_cost)],['Equipment / subcontract / other',money(p.other_direct_cost)],['Total direct cost',money(p.direct_cost)]];
  return <section className="ro-summary" aria-label={`Read-only project summary: ${p.name}`}>
    <button type="button" className="btn ghost back-btn" onClick={onBack}><ArrowLeft size={16}/> Back to active estimating workspace</button>
    <div className="notice info" role="note"><Info size={17}/><span><strong>Fictional portfolio example (read-only).</strong> Synthetic demonstration data. No documents, gate decisions or audit history exist for this project, and it is not connected to document ingestion or model analysis.</span></div>
    <div className="ro-head"><div><p className="eyebrow green">{p.project_type.toUpperCase()} · {p.project_id}</p><h1>{p.name}</h1><p className="lead">{p.owner}</p></div><span className={`ro-status ${p.status}`}>{STATUS_LABEL[p.status]}</span></div>
    <div className="ro-grid">
      <section className="card"><p className="section-label">QUOTED BID</p><div className="ro-big">{money(p.bid_amount)}</div>
        <dl className="ro-dl"><dt>Bid date</dt><dd>{p.bid_date||'n/a'}</dd><dt>{p.status==='bidding'?'Decision':'Decision date'}</dt><dd>{p.status==='bidding'?'Pending':p.decision_date||'n/a'}</dd>
        {p.status==='bidding'&&<><dt>Win probability (stored)</dt><dd>{typeof p.win_probability==='number'?`${Math.round(p.win_probability*100)}%`:'Not set'}</dd></>}</dl>
        {p.status==='lost'&&<div className="ro-outcome lost"><strong>Bid lost</strong><p>{p.loss_reason||'No reason recorded.'}</p></div>}
        {p.status==='won'&&<div className="ro-outcome won"><strong>Bid won</strong><p>Awarded {p.decision_date||'n/a'}.</p></div>}
        {p.status==='bidding'&&<div className="ro-outcome open"><strong>Bid open</strong><p>Outcome not yet decided.</p></div>}
      </section>
      <section className="card"><p className="section-label">ESTIMATED AT BID · NOT REALIZED PROFIT</p>
        {p.missing_inputs.length?<p className="muted">Financial inputs missing or unusable: {p.missing_inputs.join(', ')}. No margins are shown.</p>:
        <table className="ro-table"><tbody>{rows.map(([a,b])=><tr key={a}><th scope="row">{a}</th><td>{b}</td></tr>)}
          <tr className="sum"><th scope="row">Estimated gross profit</th><td>{money(p.gross_profit)} · {pct(p.gross_margin_pct)}</td></tr>
          <tr><th scope="row">Allocated overhead</th><td>{money(p.allocated_overhead)}</td></tr>
          <tr className="sum"><th scope="row">Expected net profit</th><td>{money(p.net_profit)} · {pct(p.net_margin_pct)}</td></tr></tbody></table>}
        <p className="tiny subdued">Gross profit = bid − direct cost. Net profit = gross profit − allocated overhead. Percentages are of the bid. Derived by the engine from the seeded cost inputs.</p>
      </section>
      <section className="card"><p className="section-label">CREW PLAN</p>
        {p.crew_plan.length?<ul className="ro-crews">{p.crew_plan.map(c=><li key={c.crew_id}><div><strong>{c.name}</strong><small>{roles(c.name)}</small></div><span>{c.efficiency_pct}%</span></li>)}</ul>:<p className="muted">No crew plan seeded for this example.</p>}
      </section>
    </div>
  </section>;
}

function CrewPanel({crews, pricing, compact}:{crews?:CrewData; pricing?:unknown; compact?:boolean}){
  // View only. The crew is chosen, once, for the whole job in the Labor Gate, with the availability attestation.
  const ok=!!crews&&!crews.error&&Array.isArray(crews.crews)&&typeof crews.fleet_average_pct==='number';
  const rows=ok?crewRows(crews,pricing):[];
  return <section className={`crew-panel${compact?' crew-compact':''}`} aria-label="Crew efficiency (view only)">
    <div className="side-section-title">CREW EFFICIENCY</div>
    {!ok?<p className="crew-note">Crew data unavailable.</p>:<>
      <div className="crew-fleet"><span>Fleet average · all {crews!.crews!.length} crews</span><strong>{crews!.fleet_average_pct!.toFixed(1)}%</strong></div>
      {rows.map(r=><div className={`crew-row${r.eligibility.ineligible?' inelig':''}`} key={r.id} data-testid={`side-crew-${r.id}`}><div><strong>{r.name} <small className="crew-id">{r.id}</small></strong><small>{r.mix}</small>
        <div className="crew-bar" role="img" aria-label={`${r.name} efficiency ${r.efficiency}%`}><span style={{width:`${Math.max(0,Math.min(r.efficiency,120))/120*100}%`}}/></div>
        <small className={`crew-elig${r.eligibility.ineligible?' no':''}`} data-testid="side-crew-elig">{r.eligibility.label}</small>
        <small data-testid="side-crew-cost">{r.cost!==null?`Job labor cost ${dollars(r.cost)}`:'Cost: shown once priced'}</small></div><span>{r.efficiency}%</span></div>)}
      <p className="crew-note">View only. Not a selection and not an approval: choose one crew for the whole job in the Labor Gate. Fictional example data.</p></>}
  </section>;
}

const isG3Fact=(id:string)=>/\/gates\/2\/clear_width_ft|GATE_G3/.test(id);
function ExportRow({state}:{state:'released'|'priced'|'unpriced'}){
  return <div className="export-row" data-testid="export-row"><a className="btn outlined" data-testid="export-csv" href="/api/demo/export?format=csv" download>Download CSV <Download size={15}/></a><small className="muted">{state==='released'?'Includes the release record and every disclosed qualification.':state==='priced'?'Not released: the export is stamped DRAFT — NOT AUTHORIZED.':'Nothing is priced yet: the export lists the open holds and G3 as RFI PENDING, with no totals.'}</small></div>;
}
export default function Gatehouse(){
  const [project,setProject]=useState<Project|null>(null);
  const [portfolio,setPortfolio]=useState<Portfolio|null>(null);
  const [viewPid,setViewPid]=useState<string|null>(null);
  const [projOpen,setProjOpen]=useState(true);
  const [projFilter,setProjFilter]=useState<'all'|'bidding'|'won'|'lost'>('all');
  const [view,setView]=useState<View>('overview');
  const [recorderOpen,setRecorderOpen]=useState(false);
  const [activityOpen,setActivityOpen]=useState(false);
  const [wide,setWide]=useState(false);          // layout: expand the whole page (hides the sidebar)
  const [home,setHome]=useState(true);   // the landing dashboard until the project is opened
  const [wageEdit,setWageEdit]=useState(false);  // wage form stays collapsed to a summary once recorded, until Edit
  const [deskOpen,setDeskOpen]=useState(false);  // layout: the Bid Desk panel
  useEffect(()=>{try{setWide(localStorage.getItem('gh.wide')==='1');}catch{/* storage unavailable: defaults */}},[]);
  function setWideP(v:boolean){setWide(v);try{localStorage.setItem('gh.wide',v?'1':'0');}catch{/* storage unavailable */}}
  const [selectedFile,setSelectedFile]=useState<File|null>(null);
  const [uploading,setUploading]=useState(false);
  const [uploadPct,setUploadPct]=useState<number|null>(null);
  const [error,setError]=useState('');
  const [info,setInfo]=useState('');
  const [busy,setBusy]=useState(false);
  const [health,setHealth]=useState<'checking'|'connected'|'unavailable'>('checking');
  const [loading,setLoading]=useState(true);
  const [expiresAt,setExpiresAt]=useState<number|null>(null);
  const [docs,setDocs]=useState<Document[]|null>(null);
  const [selectedFact,setSelectedFact]=useState<string|null>(null);
  const [selectedException,setSelectedException]=useState<string>('');
  const [scopeChoice,setScopeChoice]=useState('');
  const [assumption,setAssumption]=useState('');
  const [resolver,setResolver]=useState('');
  const [scopeNote,setScopeNote]=useState('');
  const [laborBy,setLaborBy]=useState('');
  const [laborDecision,setLaborDecision]=useState('');
  const [laborRate,setLaborRate]=useState('');
  const [laborSource,setLaborSource]=useState('');
  const [laborReview,setLaborReview]=useState('');
  const [laborClass,setLaborClass]=useState('');
  const [payroll,setPayroll]=useState('unknown');
  const [qualification,setQualification]=useState('');
  const [laborNote,setLaborNote]=useState('');
  const [approver,setApprover]=useState('');
  const [releaseNote,setReleaseNote]=useState('');
  const [tg,setTg]=useState<any>(null);const [ackQual,setAckQual]=useState(false); // eslint-disable-line @typescript-eslint/no-explicit-any
  const {registry,draft}=useDp001();
  const narrow=useNarrow();
  const [target,setTarget]=useState<Target|null>(null);
  const docMap=useMemo(()=>Object.fromEntries((registry?.documents||[]).map(d=>[d.doc_id,d])),[registry]);
  function viewDoc(t:Target){setTarget(t);window.setTimeout(()=>document.querySelector('[data-testid="doc-viewer"]')?.scrollIntoView({block:'start',behavior:'auto'}),60);}
  useEffect(()=>{ // takeoff conditions for release (DP-001 only): refreshed whenever the project changes while the Release Gate is open
    if(!project||!(project.pricing as any)?.footing)return;let alive=true;
    fetch('/api/demo/takeoff',{cache:'no-store'}).then(r=>r.ok?r.json():null).then(b=>{if(alive){setTg(b&&b.applies?b:null);setAckQual(false);}}).catch(()=>{if(alive)setTg(null);});
    return()=>{alive=false;};
  },[view,project?.scope_version,project?.proposal_digest,project?.status,project?.audit?.length]);// eslint-disable-line react-hooks/exhaustive-deps
  const [parseMode,setParseMode]=useState<ConfiguredMode>('RECORDED');  // the mode the stack is configured for, from the server; RECORDED (today's wording) until it says otherwise
  const inputRef=useRef<HTMLInputElement>(null);
  const dialogRef=useRef<HTMLDivElement>(null);
  const reviewBtnRef=useRef<HTMLButtonElement>(null);
  const dismissedRef=useRef<Set<string>>(new Set());
  const currentId=useRef<string|null>(null);

  const applyState=useCallback((body:{project:unknown;expires_at?:number;parse_mode?:ConfiguredMode})=>{
    setProject(fromEngine(body.project));setExpiresAt(body.expires_at??null);if(body.parse_mode)setParseMode(body.parse_mode);
  },[]);
  // The visitor's project comes from a signed, HttpOnly session cookie. There is no project id in any URL or request.
  const loadProject = useCallback(async(_id?:string,showErrors=false)=>{
    try{
      const body=await readJSON<{project:unknown;fresh?:boolean;expired?:boolean;expires_at?:number}>(await fetch('/api/demo/state',{cache:'no-store'}));
      applyState(body);
      if(body.expired)setInfo('Your previous demo session expired, so a fresh fictional project was started.');
      if(showErrors)setError('');
    }catch(e){if(showErrors)setError(e instanceof Error?e.message:'Cannot start the demo');}
    finally{setLoading(false);}
  },[applyState]);
  const loadDocs=useCallback(async(_id?:string)=>{/* Documents are not available for fixture projects; see the Source inventory panel. */},[]);
  const loadPortfolio=useCallback(async()=>{
    try{setPortfolio(await readJSON<Portfolio>(await fetch('/api/demo/portfolio',{cache:'no-store'})));}
    catch{setPortfolio({error:'Portfolio unavailable'});}
  },[]);
  async function resetDemo(){
    setBusy(true);setError('');setInfo('');
    try{
      const body=await readJSON<{project:unknown;expires_at?:number}>(await fetch('/api/demo/reset',{method:'POST'}));
      applyState(body);setHome(true);setViewPid(null);setProjFilter('all');void loadPortfolio();setView('overview');setSelectedFact(null);setSelectedException('');setScopeChoice('');setAssumption('');setScopeNote('');
      setLaborDecision('');setLaborReview('');setLaborNote('');setLaborSource('');setLaborClass('');setQualification('');setLaborRate('');setApprover('');setReleaseNote('');
      setInfo('Demo reset. This is a new fictional project at the unresolved Scope Gate.');
    }catch(e){setError(e instanceof Error?e.message:'Reset failed');}finally{setBusy(false);}
  }
  useEffect(()=>{
    void loadProject(undefined,true);void loadPortfolio();
    fetch('/api/demo/health',{cache:'no-store'}).then(r=>r.ok?r.json():Promise.reject()).then(h=>setHealth(h.engine==='responsive'?'connected':'unavailable')).catch(()=>setHealth('unavailable'));
  },[loadProject,loadPortfolio]);
  useEffect(()=>{
    if(!project)return;
    if(project.status==='processing'||project.status==='uploaded'){
      const t=window.setInterval(()=>{void loadProject(project.project_id);},3500);return()=>window.clearInterval(t);
    }
  },[project?.project_id,project?.status,loadProject]);
  // A gate dialog opens by itself when the engine first requires a human decision in that state. Dismissing it
  // (button, Escape, backdrop) is remembered for that state, so it never re-opens on its own. Review Required reopens it.
  useEffect(()=>{
    if(!project)return;
    const gate=gateFor(project.status);
    const key=`${project.project_id}:${project.status}`;
    if(!gate||viewPid||home){setView('overview');return;} // read-only fixtures and the landing dashboard never open a gate
    if(!dismissedRef.current.has(key))setView(gate);
  },[project?.project_id,project?.status,viewPid,home]);// eslint-disable-line react-hooks/exhaustive-deps
  function dismiss(){
    if(project)dismissedRef.current.add(`${project.project_id}:${project.status}`);
    setView('overview');
    window.setTimeout(()=>reviewBtnRef.current?.focus(),0);
  }
  function openGate(){if(requiredGate)setView(requiredGate);}
  function openTakeoff(){setView('takeoff');}
  function closeTakeoff(){setView('overview');window.setTimeout(()=>document.querySelector<HTMLButtonElement>('[data-testid="open-takeoff"]')?.focus(),0);}
  useEffect(()=>{
    if(view==='overview')return;
    dialogRef.current?.focus();
    const onKey=(e:KeyboardEvent)=>{if(e.key==='Escape')dismiss();};
    window.addEventListener('keydown',onKey);return()=>window.removeEventListener('keydown',onKey);
  },[view]);// eslint-disable-line react-hooks/exhaustive-deps
  const exceptions=project?.exceptions||[];
  const activeException=exceptions.find(x=>x.exception_id===selectedException)||exceptions.find(x=>x.blocking||x.severity==='blocking')||exceptions[0];
  const sourceDocs=docs||project?.documents||[];
  const facts=project?.facts||[];
  const shownFact=facts.find(f=>f.fact_id===selectedFact)||facts[0];
  const currentStatus=project?.status;
  const requiredGate=gateFor(project?.status);
  const blockingCount=exceptions.filter(x=>x.blocking||x.severity==='blocking').length;
  const outstanding=requiredGate==='scope'?blockingCount:requiredGate?1:0;
  const citations=(()=>{const seen=new Set<string>();const out:{src:SourceRef;code?:string}[]=[];
    for(const ex of exceptions)for(const e of ex.evidence||[]){const k=`${e.sheet||e.doc_id}|${e.page}|${e.excerpt}`;if(!seen.has(k)){seen.add(k);out.push({src:e,code:ex.code});}}
    return out;})();
  const demoRel=String(currentStatus)==='released'&&!!tg&&tg.readiness?.selected?.bid_ready!==true;
  const releaseReady=currentStatus==='ready_for_final_review' && !!project?.proposal_digest;
  const hasScopeIssues=exceptions.some(x=>(x.blocking||x.severity==='blocking')&&x.status!=='resolved');

  function fileChanged(file:File|undefined){setError('');setInfo('');
    if(!file)return;
    if(!file.name.toLowerCase().endsWith('.zip')){setError('Select a ZIP archive containing the bid documents.');return;}
    setSelectedFile(file);
  }
  async function upload(){
    // ZIP analysis stays disabled until the authenticated processing path exists. No upload route is exposed.
    return;
  }
  // One Idempotency-Key per intentional decision. The same key is reused only while the SAME decision (route + exact payload) is unresolved
  // (transport failure, 5xx, 429), so a retry can never double-record. A recorded or definitively refused decision releases its key.
  const pendingKey=useRef<{fp:string;key:string}|null>(null);
  function keyFor(url:string,body:object){
    const fp=`${url}|${JSON.stringify(body)}`;
    if(!pendingKey.current||pendingKey.current.fp!==fp)pendingKey.current={fp,key:`ifs-${crypto.randomUUID()}`};
    return pendingKey.current.key;
  }
  async function send(url:string,body:object,decision=false):Promise<Sent>{
    setBusy(true);setError('');setInfo('');
    const headers:Record<string,string>={'Content-Type':'application/json'};
    if(decision)headers['Idempotency-Key']=keyFor(url,body);
    try{
      const res=await fetch(url,{method:'POST',headers,body:JSON.stringify(body)});
      const replay=res.headers.get('idempotent-replay')==='true'||res.headers.get('x-idempotency-result')==='historical';
      const auditId=res.headers.get('x-original-audit-event-id')||undefined;
      await readJSON<unknown>(res);
      pendingKey.current=null;
      // A historical replay returns the ORIGINAL response. It is shown as history, never as a fresh approval of the current state.
      setInfo(replay?`This exact decision was already recorded${auditId?` (audit event ${auditId})`:''}. This is a historical result; nothing new was recorded. Current state loaded.`:'Recorded by the engine. Updated state loaded.');
      await loadProject(undefined,true);
      return {ok:true,replay,auditId};
    }catch(e){
      if(e instanceof ApiError){
        if(e.status>=400&&e.status<500&&e.status!==429)pendingKey.current=null; // definitively refused: the next attempt is a new decision
        setError(explain(e));
        if(e.status===409&&!decision)void loadProject(undefined,false); // stale version/digest: show current state
      }else setError(e instanceof Error?e.message:'Request failed'); // transport failure: key kept so an identical retry is the same decision
      return {ok:false};
    }finally{setBusy(false);}
  }
  async function approveCrewPlan(body:object){
    const before=project?.proposal_digest||null;
    const r=await send('/api/demo/decision/crew-plan',body,true);
    if(r.ok&&!r.replay){
      setView('release');
      if(before)setInfo('Crew plan changed: the previous release digest is void and a new one was issued. Review the updated estimate before authorizing.');
    }
  }
  async function recordWage(body:object){await send('/api/demo/decision/wage',body,true);}
  async function approveRuleset(body:object){const r=await send('/api/demo/decision/ruleset',body,true);if(r.ok)setSelectedException('');}
  async function resolveScope(){
    if(!project||!activeException||!resolver.trim()||!scopeNote.trim())return;
    // Exactly one of option_id or value, as the engine requires. The server validates; the browser does not pre-approve.
    const body:Record<string,unknown>={exception_id:activeException.exception_id,by:resolver.trim(),note:scopeNote.trim()};
    if(scopeChoice)body.option_id=scopeChoice;
    else{const raw=assumption.trim();if(!raw)return;const n=Number(raw);body.value=Number.isFinite(n)?n:raw;}
    if(body.value!==undefined&&isG3Fact(activeException.exception_id)){if(scopeNote.trim().length<10){setError('A G3 value needs a source note: where it came from (document, page, quote, or who supplied it and when).');return;}body.source_note=scopeNote.trim();body.note='Entered at the Scope Gate.';}
    await send('/api/demo/scope/resolve',body);
  }
  async function resolveLabor(){
    if(!project||!laborBy.trim()||!laborNote.trim()||!laborReview.trim())return;
    if(!laborDecision){setError('Select a determination.');return;}
    if(laborDecision==='human_assumption_with_qualification'&&!qualification.trim()){setError('A pricing assumption requires a visible qualification.');return;}
    if(laborDecision.startsWith('verified_')&&!laborSource.trim()){setError('A verified wage basis requires a source reference.');return;}
    await send('/api/demo/labor/resolve',{
      by:laborBy.trim(),decision:laborDecision,source_refs:laborSource.split(',').map(s=>s.trim()).filter(Boolean),
      applicability_review:laborReview.trim(),classifications:laborClass.split(',').map(s=>s.trim()).filter(Boolean),
      certified_payroll:payroll==='true'?true:payroll==='false'?false:'unknown',
      ...(laborDecision==='human_assumption_with_qualification'?{qualification:qualification.trim()}:{}),
      ...(laborRate.trim()&&['verified_federal','verified_state_local','verified_cba'].includes(laborDecision)?{loaded_hourly_rate:Number(laborRate)}:{}),
      note:laborNote.trim()
    });
  }
  async function release(){
    if(!project||!releaseReady||!approver.trim()||!project.proposal_digest)return;
    await send('/api/demo/release',{
      approver:approver.trim(),expected_scope_version:project.scope_version,
      expected_proposal_digest:project.proposal_digest,note:releaseNote.trim(),
      ...(tg?{takeoff_digest:tg.digest,acknowledged_blockers:ackQual?tg.release_ack_required:[]}:{})
    });
  }
  
  function selectPortfolio(p:PortfolioProject){if(p.kind==='active_estimating')setHome(false);setViewPid(p.kind==='active_estimating'?null:p.project_id);}
  const roProject=viewPid?(portfolio?.projects||[]).find(x=>x.project_id===viewPid)||null:null;
  function newProject(){void resetDemo();}
  const stageReady=(v:View)=>!!project || v==='overview';

  const sideBody=<>
    <div className="side-section-title">NAVIGATION</div>
    <ProjectNav portfolio={portfolio} active={project?{name:draft?`${draft.project_ref} · Municipal Recreation Courts`:'Sample project',status:bidStatusLabel(project)}:undefined} activeSelected={!roProject} viewPid={viewPid} open={projOpen} setOpen={setProjOpen} filter={projFilter} setFilter={setProjFilter} onSelect={selectPortfolio}/>
    <CrewPanel crews={project?.crews} pricing={project?.pricing}/>
    <button className="side-link" type="button" data-testid="open-ai-activity" aria-haspopup="dialog" aria-expanded={activityOpen} onClick={()=>setActivityOpen(true)}><Cpu size={18}/> AI activity <ChevronRight size={15}/></button>
    <button className="side-link" type="button" data-testid="open-flight-recorder" aria-haspopup="dialog" aria-expanded={recorderOpen} onClick={()=>setRecorderOpen(true)}><Activity size={18}/> AI Flight Recorder <ChevronRight size={15}/></button>
    <button className="side-link" type="button" onClick={newProject}><PackageOpen size={18}/> Reset demo <ArrowUpRight size={15}/></button>
  </>;

  // With a gate open the page behind it must not scroll: on desktop the left pane (blueprint first) scrolls on its own, on a phone the full-width gate does.
  useEffect(()=>{
    const on=view!=='overview'&&!roProject; const el=document.documentElement;
    el.classList.toggle('gate-open',on);
    return()=>{el.classList.remove('gate-open');};
  },[view,roProject]);
  const viewDocRef=useRef(viewDoc);viewDocRef.current=viewDoc;
  const ctxValue=useMemo(()=>({view:(t:Target)=>viewDocRef.current(t),docs:docMap}),[docMap]);
  const viewTarget:Target|null=target||(registry?{doc_id:'dp001_ansi_b_v2_drawings',page:2}:null);
  const viewerNode=registry&&viewTarget?<DocViewer registry={registry} target={viewTarget} setTarget={setTarget}/>:null;
  const viewerInDrawer=(view==='scope'||view==='takeoff')&&narrow;
  const viewerTop=(view==='scope'||view==='takeoff')&&!narrow;

  return <ViewCtx.Provider value={ctxValue}><div className={`shell${wide?' wide':''}`}>
    <aside className="sidebar">
      <div className="identity"><div className="brand-icon"><Layers size={23} strokeWidth={2.2}/></div><div><div className="brand-name">IFI <span>GATEHOUSE</span></div><div className="brand-note">ESTIMATING CONTROL SYSTEM</div></div></div>
      <div className="side-scroll">{sideBody}</div>
      <div className="sidebar-bottom"><div className="side-signal"><span className={`signal ${health==='connected'?'green':health==='unavailable'?'amber':'gray'}`}/><div><strong>{health==='connected'?'Engine responsive':health==='checking'?'Checking engine':'Engine unavailable'}</strong><small>Actual backend connection</small></div></div></div>
    </aside>

    <main className={`main-view${view!=='overview'&&!roProject?' has-dialog':''}`}>
      <details className="crew-mobile"><summary>Projects · crews</summary><div className="side-scroll">{sideBody}</div></details>
      <header className="topbar"><div className="breadcrumbs">IFI LABS <ChevronRight size={14}/> GATEHOUSE <ChevronRight size={14}/><strong>{project?(home&&!roProject?'PROJECT DASHBOARD':'PROJECT WORKSPACE'):'NEW PROJECT'}</strong></div><div className="topbar-right"><span className="top-capsule"><LockKeyhole size={14}/> Human-controlled release</span><div className="profile">IFI</div></div></header>
      <nav className="header-tabs" aria-label="Project views">
        <button className={`header-tab${home&&!roProject?' selected':''}`} type="button" data-testid="nav-dashboard" aria-current={home&&!roProject?'page':undefined} onClick={()=>{setHome(true);setViewPid(null);}}><Layers size={16}/> Projects dashboard</button>
        <button className={`header-tab${!home&&!roProject?' selected':''}`} type="button" data-testid="nav-workspace" aria-current={!home&&!roProject?'page':undefined} onClick={()=>{setHome(false);setViewPid(null);}}><FolderOpen size={16}/> Project workspace</button>
      </nav>
      {roProject&&<div className="main-inner"><PortfolioSummary p={roProject} crews={project?.crews} onBack={()=>setViewPid(null)}/></div>}
      <div className={`main-inner${roProject?' is-hidden':''}`}>
        {registry&&draft&&!(home&&project&&!roProject)?<div className="notice info" role="note" data-testid="demo-notice"><Info size={17}/><span><strong>DP-001 synthetic bid package (fictional owner and site, not for construction).</strong> The scope is a <strong>human-prepared draft</strong> attached to the registered documents below. AI Findings are stored AMD model outputs, {headerModeClause(parseMode)}; they never author or change this draft. Pricing uses the example rate book. Names you type are self-declared, not verified identities.</span></div>:<div className="notice info" role="note"><Info size={17}/><span><strong>Interactive demonstration using fictional project data and example pricing.</strong> Prices come from the deterministic engine and the example rate book. Addendum parsing and AI findings are labelled by source (LIVE, RECORDED, or stored). Names you type are self-declared, not verified identities.</span></div>}
        {!(home&&project&&!roProject)&&<div className="page-top"><div><p className="eyebrow green">COMMERCIAL FENCE ESTIMATING / IFI LABS</p><h1>{project?'Project workspace':'Plans in. Verified bids out.'}</h1><p className="lead">AI interprets the documents. Deterministic code calculates. <strong>Humans authorize.</strong></p></div><div className="page-top-action">{project&&<>{requiredGate&&<button ref={reviewBtnRef} className="btn primary review-required" onClick={openGate}>Review required · {outstanding}</button>}{registry&&<button className="btn outlined" data-testid="open-takeoff" onClick={openTakeoff}>Takeoff Review</button>}<details className="layout-menu" data-testid="layout-menu"><summary className="btn ghost small" aria-label="Layout options"><SlidersHorizontal size={14}/> Layout</summary><div className="layout-pop" role="menu" onClick={e=>{(e.currentTarget.closest('details') as HTMLDetailsElement|null)?.removeAttribute('open');}}>
            <button type="button" role="menuitem" data-testid="layout-expand" onClick={()=>setWideP(!wide)}>{wide?<Minimize2 size={14}/>:<Maximize2 size={14}/>} {wide?'Restore sidebar':'Expand whole page'}</button>
            <button type="button" role="menuitem" data-testid="layout-scope" disabled={!requiredGate} onClick={()=>{if(requiredGate==='scope')setView(view==='scope'?'overview':'scope');else openGate();}}><Scale size={14}/> {view==='scope'?'Hide Scope Gate':'Show Scope Gate'}</button>
            <button type="button" role="menuitem" data-testid="layout-desk" onClick={()=>setDeskOpen(!deskOpen)}><MessageSquare size={14}/> {deskOpen?'Hide Bid Desk':'Show Bid Desk'}</button>
            <button type="button" role="menuitem" onClick={()=>{void loadProject(undefined,true);}}><RefreshCw size={14}/> Refresh state</button>
            <button type="button" role="menuitem" disabled={busy} onClick={()=>void resetDemo()}><PackageOpen size={14}/> Reset demo</button>
          </div></details></>}</div></div>}
        {error&&<div role="alert" className="notice error"><CircleAlert size={17}/><span>{error}</span><button aria-label="Dismiss error" onClick={()=>setError('')}><X size={15}/></button></div>}
        {info&&<div role="status" className="notice info"><CheckCircle2 size={17}/><span>{info}</span><button aria-label="Dismiss notice" onClick={()=>setInfo('')}><X size={15}/></button></div>}
        {!project&&loading ? <div className="notice info" role="status"><LoaderCircle className="spin" size={17}/><span>Preparing your fictional demo project…</span></div> : !project ? <>
          <div className="intro-grid"><section className="card upload-card"><div className="card-overline"><span className="number-pill">01</span> START A NEW ESTIMATE</div><h2>Drop your bid package.</h2><p className="muted">One ZIP containing the complete drawing set, specifications, schedules and addenda.</p>
            <input ref={inputRef} type="file" accept=".zip,application/zip,application/x-zip-compressed" className="visually-hidden" id="zipinput" onChange={e=>fileChanged(e.target.files?.[0])}/>
            <div className={`drop-area ${selectedFile?'file-selected':''}`} role="button" tabIndex={0} onClick={()=>inputRef.current?.click()} onKeyDown={e=>{if(e.key==='Enter'||e.key===' ')inputRef.current?.click();}} onDrop={e=>{e.preventDefault();fileChanged(e.dataTransfer.files[0]);}} onDragOver={e=>e.preventDefault()}>
              <div className="upload-glyph"><UploadCloud size={28}/></div><strong>{selectedFile?selectedFile.name:'Drag and drop a ZIP file here'}</strong><p>{selectedFile?`${(selectedFile.size/1024/1024).toFixed(2)} MB selected`:'or browse files from your computer'}</p><span className="soft-button">{selectedFile?'Change package':'Browse files'} <ArrowUpRight size={14}/></span>
            </div>
            {uploadPct!==null&&<div className="progress-wrap"><div className="progress-track"><span style={{width:`${uploadPct}%`}}/></div><small>Transferring ZIP to engine · {uploadPct}%</small></div>}
            <button className="btn primary full upload-submit" type="button" disabled={PREVIEW_UPLOAD_DISABLED||!selectedFile||uploading} onClick={()=>{void upload();}}>{uploading?<LoaderCircle className="spin" size={17}/>:<LockKeyhole size={17}/>} {PREVIEW_UPLOAD_DISABLED?'ZIP analysis not available yet':uploading?'Uploading package…':'Begin document analysis'}</button>{PREVIEW_UPLOAD_DISABLED&&<p className="tiny warning-text">The engine&apos;s upload route is not implemented (HTTP 501). To inspect the real gates, open a fixture project with <code>/?project=PROJECT_ID</code>.</p>}
            <p className="fineprint"><LockKeyhole size={12}/> Server validates the archive. Upload cleared synthetic materials only.</p>
          </section><div className="intro-right"><section className="dark-panel"><div className="panel-cap"><Activity size={16}/> THREE AUTHORITY BOUNDARIES</div><div className="big-number">03<span> gates</span></div><p>Automation handles discovery and calculation. Every commercially significant exception stays under human control.</p><div className="dark-divider"/>{['Scope Gate','Labor Gate','Release Gate'].map((name,i)=><div className="dark-step" key={name}><span>0{i+1}</span><strong>{name}</strong><Check size={15}/></div>)}</section><section className="small-outline"><ShieldCheck size={20}/><div><strong>Fail-closed by design</strong><p>Unknown dimensions never become zero. Unverified wage obligations never become exemptions.</p></div></section></div></div>
          <div className="bottom-explainer"><div><span className="section-label">FROM DOCUMENTS TO DECISIONS</span><h3>Built for the messy middle of commercial bids.</h3></div><div className="process-strip"><div><FileArchive/><span>ZIP Intake</span></div><ArrowRight/><div><FileSearch2/><span>Evidence</span></div><ArrowRight/><div><Scale/><span>Takeoff</span></div><ArrowRight/><div><ClipboardCheck/><span>Approval</span></div></div></div>
        </> : home&&!roProject ? <LandingDashboard project={project} draft={draft} portfolio={portfolio} onOpen={()=>{setHome(false);}} onOpenExample={p=>{setHome(false);selectPortfolio(p);}}/> : <>
          
          <div className="project-banner"><div className="project-summary"><div className="project-monogram"><FileArchive size={24}/></div><div><div className="project-mini">{draft?'ACTIVE BID PACKAGE · FOUR-COURT BASE BID, THREE-COURT ALTERNATE A-1':'ACTIVE BID PACKAGE'}</div><strong>{draft?`${draft.project_ref} · Municipal Recreation Courts`:project.label||`Project ${project.project_id.slice(0,8)}`}</strong><span>ID {project.project_id}</span></div></div><div className="project-meta"><StatusPill status={project.status} demo={demoRel}/><span className="outstanding">{outstanding>0?`${outstanding} action${outstanding===1?'':'s'} outstanding`:project.status==='released'?'No actions outstanding':''}</span><div className="vline"/><div><small>SCOPE REVISION</small><strong>v{project.scope_version??'—'}</strong></div><div className="vline"/><div><small>DOCUMENTS</small><strong>{registry?registry.documents.length:sourceDocs.length}</strong></div></div></div>
          {!viewerInDrawer&&viewerNode&&<div className={`viewer-slot${viewerTop?' viewer-top':''}`}>{viewerNode}</div>}
          {registry&&<DocumentPackage registry={registry} onOpen={viewDoc}/>}
          <div className="workspace-grid"><div className="primary-column">
            <section className="card progress-card"><div className="card-heading"><div><p className="section-label">PROCESSING STATUS</p><h2>{(demoRel?'Demonstration release recorded — NOT a bid':statusTitles[project.status])}</h2></div><span className="utility-icon"><Activity size={20}/></span></div><p className="muted">{['processing','uploaded'].includes(project.status)?'The server is indexing documents and analyzing evidence. Status updates are polled from the engine.':'Review the actual evidence and resolve any required human decisions.'}</p>{project.progress&&<div className="running-progress"><div className="progress-track"><span style={{width:project.progress.total?`${Math.round(100*(project.progress.processed??0)/project.progress.total)}%`:'7%'}}/></div><div><span>PHASE: {project.progress.phase||'pending'}</span><span>{project.progress.processed??0} / {project.progress.total??'—'} processed</span></div></div>}<div className="progress-legend"><span><CheckCircle2 size={15}/> Package accepted</span><span><Clock3 size={15}/> Extraction reported by engine</span><span><LockKeyhole size={15}/> Approval restricted</span></div></section>
            {registry?null:<section className="card"><div className="card-heading"><div><p className="section-label">DOCUMENT STACK</p><h2>Documents <span className="h2-count">{sourceDocs.length}</span></h2></div><button className="text-button" onClick={()=>void loadDocs()}><RefreshCw size={14}/> Reload</button></div>{sourceDocs.length?<div className="document-table">{sourceDocs.map((doc,i)=><div className="doc-row" key={doc.doc_id||i}><div className="doc-icon"><FileText size={19}/></div><div className="doc-main"><strong>{doc.name}</strong><small>{friendlyClass(doc.classification)}</small></div><div className="doc-info"><span>{typeof doc.pages==='number'?`${doc.pages} ${doc.pages===1?'page':'pages'}`:'Pages pending'}</span><span className="doc-tag">{doc.revision||'SOURCE'}</span></div></div>)}</div>:<div className="empty-inline"><FolderOpen size={23}/><strong>Document files unavailable</strong><p>This fixture has no document files and the engine&apos;s documents route is not implemented (HTTP 501). Below are only the source citations the engine attached to its exceptions.</p></div>}{citations.length>0&&<div className="citation-stack"><span className="section-label">CITATIONS FROM ENGINE EXCEPTIONS</span><div className="source-list">{citations.map((c,i)=><div key={i}><Source source={c.src}/><small className="tiny subdued">{c.code}</small></div>)}</div></div>}</section>}
            <section className="card"><div className="card-heading"><div><p className="section-label">MODEL OUTPUT / SOURCED FACTS</p><h2>Evidence register <span className="h2-count">{facts.length}</span></h2></div></div>{facts.length?<div className="fact-grid"><div className="fact-list">{facts.map((f,i)=><button key={f.fact_id||i} className={`fact-row ${shownFact===f?'active':''}`} onClick={()=>setSelectedFact(f.fact_id||null)}><span><strong>{f.path||f.fact_id||`Fact ${i+1}`}</strong><small>{f.status||'unclassified'}</small></span><b>{formatValue(f.value)}</b></button>)}</div><div className="fact-detail"><span className="section-label">EVIDENCE FOR SELECTED FACT</span><h3>{shownFact?.path||shownFact?.fact_id||'Fact'}</h3><SourceList sources={shownFact?.evidence}/></div></div>:<div className="empty-inline"><FileSearch2 size={24}/><strong>Facts register unavailable</strong><p>This engine build does not return a facts list. Evidence appears per exception in the Scope Gate. Nothing is invented here.</p></div>}</section>
          </div><aside className="secondary-column"><section className="card mini-card"><p className="section-label">NEXT ACTION</p><h3>{project.status==='needs_scope_review'?'Resolve scope exceptions':project.status==='needs_labor_review'?'Review the labor basis':project.status==='ready_for_final_review'?'Authorize the proposal':project.status==='released'?'Review the release record':'Await engine status'}</h3><p className="muted">Each decision is recorded against the current project revision.</p>{requiredGate?<button className="btn outlined full" onClick={openGate}>Open review <ArrowRight size={15}/></button>:project.status==='released'?<><button className="btn outlined full" onClick={()=>setView('release')}>View release record <ArrowRight size={15}/></button></>:null}{project.pricing?.crew_plan?<ExportRow state={project.status==='released'?'released':project.pricing?.estimate_view?'priced':'unpriced'}/>:<p className="tiny subdued" data-testid="export-locked">No total or export until one crew is approved for the whole job (Labor Gate).</p>}</section>
          <section className="card mini-card"><p className="section-label">REVISION MANAGEMENT</p><div className="revision-card"><div className="revision-symbol"><Layers size={19}/></div><div><strong>Addendum 02</strong><p>Attach it at the Scope Gate. It enters as a separate revision and waits there for a named person.</p></div></div><button className="btn outlined full" type="button" data-testid="open-addendum" onClick={()=>setView('scope')}>Attach addendum at the Scope Gate <ArrowRight size={15}/></button></section>
          <section className="card mini-card"><p className="section-label">AUDIT ACTIVITY</p>{project.audit?.length?<div className="audit-list">{project.audit.slice(-6).reverse().map((a,i)=><div className="audit-line" key={a.event_id||i}><span className="audit-dot"/><div><strong>{a.event_type||a.decision||'Recorded event'}</strong><small>{a.actor||'System'} · {a.timestamp||'Time pending'}</small></div></div>)}</div>:<p className="muted">No engine audit events returned yet.</p>}</section></aside></div>
          {view!=='overview'&&<div className="gate-backdrop" onClick={dismiss} aria-hidden="true"/>}
          {view!=='overview'&&<div className="gate-dialog" role="dialog" aria-modal="false" aria-label={view==='scope'?'Scope Gate':view==='labor'?'Labor Gate':view==='takeoff'?'Takeoff Review':'Release Gate'} tabIndex={-1} ref={dialogRef}>
            <div className="gate-dialog-bar"><strong>{view==='takeoff'?'Takeoff Review · contractor reconciliation (provisional)':view==='scope'?`Scope Gate · ${blockingCount} blocking exception${blockingCount===1?'':'s'}`:view==='labor'?(project.pricing?(project.pricing.wage.required&&!project.pricing.wage.cleared?'Labor Gate · wage determination required':project.pricing.crew_plan?'Labor Gate · crew plan approved (revisable)':'Labor Gate · crew plan required'):'Labor Gate · wage basis not yet decided'):currentStatus==='released'?'Release record':'Release Gate · final authorization'}</strong><button className="btn ghost" type="button" onClick={view==='takeoff'?closeTakeoff:dismiss}>{currentStatus==='released'||view==='takeoff'?'Close':'Dismiss to inspect documents'} <X size={14}/></button></div>
          {view==='takeoff'&&<div className="workspace-grid"><div className="primary-column">{viewerInDrawer&&viewerNode}{project&&registry&&<TakeoffReview project={project} docs={docMap} view={viewDoc} onRefresh={()=>{void loadProject(undefined,false);}}/>}</div></div>}
          {view==='scope'&&<div className="workspace-grid"><div className="primary-column">{project&&<ScopeDiscovery project={project} draft={draft} review={tg} onFocus={id=>{setSelectedException(id);setScopeChoice('');setAssumption('');setError('');}} addendumSlot={<div data-testid="scope-gate-addendum"><AddendumPanel mode={parseMode} project={project} onRefresh={()=>{void loadProject(undefined,false);}}/></div>}/>}{viewerInDrawer&&viewerNode}
          <section className="card"><div className="card-heading"><div><p className="section-label">QUANTITY RECONCILIATION</p><h2>Plan vs. schedule</h2></div></div>{project.reconciliation?.length?<div className="table-scroll"><table className="data-table"><thead><tr><th>Quantity</th><th>Plan-derived</th><th>Scheduled</th><th>Status</th></tr></thead><tbody>{project.reconciliation.map((r,i)=><tr key={i}><td>{r.label||r.item||`Item ${i+1}`}</td><td>{formatValue(r.derived)}</td><td>{formatValue(r.scheduled)}</td><td><span className={`mini-tag ${r.status==='match'||r.status==='within_tolerance'?'ok':''}`}>{r.status||'review'}</span></td></tr>)}</tbody></table></div>:<div className="empty-inline"><Scale size={23}/><strong>No reconciliation delivered</strong><p>Post counts and LF will appear only when the backend supplies them.</p></div>}</section>
          <details className="card exc-details" data-testid="exception-register"><summary><strong>All exceptions ({exceptions.length})</strong> <span className="tiny subdued">advanced: every item the engine returned</span></summary>{exceptions.length?<div className="exception-list">{exceptions.map((ex,i)=><button onClick={()=>{setSelectedException(ex.exception_id);setScopeChoice('');setAssumption('');setError('');}} key={ex.exception_id||i} className={`exception-row ${activeException?.exception_id===ex.exception_id?'chosen':''}`}><div className={`exception-icon ${ex.blocking||ex.severity==='blocking'?'blocking':'advisory'}`}><CircleAlert size={17}/></div><div><strong>{ex.question||ex.message||ex.code||ex.exception_id}</strong><p>{ex.affected_paths?.join(' · ')||ex.exception_id}</p></div><span className={`mini-tag ${!(ex.blocking||ex.severity==='blocking')?'ok':''}`}>{ex.blocking||ex.severity==='blocking'?'BLOCKING':'ADVISORY'}</span></button>)}</div>:<div className="empty-inline"><CheckCheck size={24}/><strong>No exceptions returned</strong><p>Only the engine can establish whether Scope Gate is complete.</p></div>}</details></div>
          <aside className="secondary-column">{activeException?.required_decision?.type==='approve_ruleset'&&project.pricing?<RulesetForm ex={activeException} project={project} busy={busy} onSubmit={approveRuleset}/>:<section className="card mini-card form-card" data-testid="scope-decision-form"><p className="section-label">HUMAN DECISION / SCOPE GATE</p><h3>Resolve selected exception</h3>{activeException?<><p className="muted">{activeException.question||activeException.message||activeException.exception_id}</p><SourceList sources={activeException.evidence}/><div className="input-stack"><label>Resolution action</label><select value={scopeChoice} onChange={e=>setScopeChoice(e.target.value)}><option value="">{activeException.allows_free_text?'No document-derived option. Enter a value as your own assumption, or request information.':'Select approved option…'}</option>{(activeException.options||[]).map(opt=><option key={opt.option_id} value={opt.option_id}>{opt.label||opt.option_id.replaceAll('_',' ')}</option>)}</select>{!activeException.options?.length&&!activeException.allows_free_text&&<p className="tiny warning-text">The engine offers no option and does not accept a typed value for this exception. It cannot be resolved here.</p>}{activeException.code==='MISSING_VALUE'&&<div className="guardrail" role="note" data-testid="missing-value-warning"><CircleAlert size={19}/><span><strong>{exceptionNotes(draft,activeException).own??'The documents do not state this value.'}</strong> Do not assume it: submit a request for information. A value typed here is recorded only as your self-declared qualified assumption and appears in the estimate qualifications; it does not answer the RFI.{exceptionNotes(draft,activeException).related.length>0&&<span className="related-notes" data-testid="related-notes"><strong>Related notes for this gate</strong>{exceptionNotes(draft,activeException).related.map(r=><span className="related-note" key={r.path} data-field={r.field}><code>{r.field}</code> {r.note}</span>)}</span>}</span></div>}{!scopeChoice&&activeException.allows_free_text&&<><label data-testid="value-field-label">{valueFieldLabel(activeException)}</label><input value={assumption} onChange={e=>setAssumption(e.target.value)} placeholder="Value the engine will validate"/><p className="tiny subdued">Recorded as a human decision, never as a plan dimension.</p></>}<label>Your name (self-declared, not verified)</label><input value={resolver} onChange={e=>setResolver(e.target.value)} placeholder="Any name; recorded as self-declared"/><label>Decision note / qualification</label><textarea rows={4} value={scopeNote} onChange={e=>setScopeNote(e.target.value)} placeholder="What evidence or authority supports this decision?"/></div><SelfDeclared/><button className="btn primary full" disabled={busy||(!scopeChoice&&!(activeException.allows_free_text&&assumption.trim()))||!resolver.trim()||!scopeNote.trim()||(!!assumption.trim()&&isG3Fact(activeException.exception_id)&&scopeNote.trim().length<10)||currentStatus==='processing'} onClick={()=>void resolveScope()}>{busy?'Recording…':'Record scope decision'} <ArrowRight size={16}/></button><p className="tiny subdued">RFI/hold does not authorize pricing. Server validates options and quantities.</p></>:<p className="muted">No selectable exception in the engine response.</p>}</section>}<section className="card mini-card"><p className="section-label">RELEASE BOUNDARY</p><div className="guardrail"><LockKeyhole size={19}/><span>Labor and final release remain separate approvals, even after scope is resolved.</span></div></section></aside>{registry&&<AiFindings mode={parseMode} project={project} review={tg} docs={docMap} view={viewDoc} onRefresh={()=>{void loadProject(undefined,false);}}/>}{draft&&registry&&<ScopeDraft draft={draft} project={project} review={tg} docs={docMap} view={viewDoc}/>}</div>}
          {view==='labor'&&<div className="workspace-grid"><div className="primary-column"><section className="card"><div className="card-heading"><div><p className="section-label">GATE 02 / PRICING BASIS</p><h2>Labor Gate</h2></div><span className="utility-icon warn"><HardHat size={20}/></span></div><p className="muted">Review wage applicability, classifications, fringe and payroll obligations. Missing contract language is not proof of exemption.</p>{tg&&<ReadinessBanner r={tg.readiness}/>}<div className="labor-current"><span className="section-label">ENGINE LABOR STATUS</span><strong>{project.labor_review?.status?.replaceAll('_',' ')||'Unknown / not returned'}</strong>{project.labor_review?.qualification&&<p>{project.labor_review.qualification}</p>}</div><div className="guardrail"><CircleAlert size={19}/><span>A qualified estimating assumption is not a legal compliance certification. Company-controlled rate availability is enforced by the engine.</span></div>{project.pricing&&<>{project.pricing.wage.required&&<p className="tiny subdued">Prevailing wage (Davis-Bacon) applies to this project. Company-rate and qualified-assumption determinations are refused by the engine here; only a recorded wage determination can clear pricing.</p>}<BlockerList exceptions={exceptions} codes={['WAGE_DETERMINATION_REQUIRED','CREW_PLAN_REQUIRED','CREW_NOT_SELECTED','CREW_UNSUITABLE','CREW_PLAN_STALE']}/>{(project.pricing.wage.blockers||[]).filter(c=>c!=='WAGE_DETERMINATION_REQUIRED').length>0&&<BlockerList exceptions={exceptions} codes={project.pricing.wage.blockers}/>}</>}</section>{project.pricing?.crew_comparison&&<CrewPlanner project={project} busy={busy} onApprove={approveCrewPlan}/>}<section className="card"><p className="section-label">SUPPORTING DOCUMENTS</p><h2>Labor evidence</h2>{sourceDocs.filter(d=>/labor|wage|spec|addendum|contract/i.test(`${d.classification||''} ${d.name}`)).length?<div className="document-table">{sourceDocs.filter(d=>/labor|wage|spec|addendum|contract/i.test(`${d.classification||''} ${d.name}`)).map((d,i)=><div className="doc-row" key={d.doc_id||i}><div className="doc-icon"><FileText size={18}/></div><div className="doc-main"><strong>{d.name}</strong><small>{friendlyClass(d.classification)}</small></div></div>)}</div>:<div className="empty-inline"><BookOpenText size={23}/><strong>No labor-related sources classified yet</strong><p>Review applicability before making a pricing decision.</p></div>}</section></div><aside className="secondary-column">{project.pricing?.wage.required?(project.pricing.wage.recorded&&project.pricing.wage.decision&&!wageEdit
          ?<section className="card mini-card wage-summary" data-testid="wage-summary"><p className="section-label">WAGE DETERMINATION · RECORDED</p><p className="wage-line"><strong>{project.pricing.wage.decision.decision_id}</strong> mod {project.pricing.wage.decision.modification} · by {project.pricing.wage.decision.recorded_by} (self-declared) · {project.pricing.wage.cleared?'cleared':'not cleared'} <button type="button" className="link-button" data-testid="wage-edit" onClick={()=>setWageEdit(true)}>Edit</button></p></section>
          :<WageForm project={project} busy={busy} onSubmit={async b=>{await recordWage(b);setWageEdit(false);}}/>):<section className="card mini-card form-card"><p className="section-label">NAMED HUMAN DETERMINATION</p><h3>Record labor basis</h3><div className="input-stack"><label>Your name (self-declared, not verified)</label><input value={laborBy} onChange={e=>setLaborBy(e.target.value)} placeholder="Required"/><label>Determination</label><select value={laborDecision} onChange={e=>setLaborDecision(e.target.value)}><option value="">Select determination…</option><option value="verified_standard">Verified standard</option><option value="verified_federal">Verified federal</option><option value="verified_state_local">Verified state/local</option><option value="verified_cba">Verified CBA / union</option><option value="human_assumption_with_qualification">Qualified estimating assumption</option></select><p className="tiny subdued">The server derives the rate basis from the determination. A hold/RFI action is not exposed by this engine build.</p>{['verified_federal','verified_state_local','verified_cba'].includes(laborDecision)&&<><label>Loaded hourly rate from the cited schedule</label><input type="number" step="any" value={laborRate} onChange={e=>setLaborRate(e.target.value)} placeholder="Taken from the cited wage schedule"/></>}<label>Applicable source reference(s)</label><input value={laborSource} onChange={e=>setLaborSource(e.target.value)} placeholder="Document IDs, comma separated"/><label>Applicability review</label><textarea rows={3} value={laborReview} onChange={e=>setLaborReview(e.target.value)} placeholder="Jurisdiction, project funding, trade and evidence reviewed"/><label>Classifications</label><input value={laborClass} onChange={e=>setLaborClass(e.target.value)} placeholder="Classification labels, comma separated"/><label>Certified payroll</label><select value={payroll} onChange={e=>setPayroll(e.target.value)}><option value="unknown">Unknown</option><option value="true">Required</option><option value="false">Not required · verified</option></select><label>Qualification (when applicable)</label><textarea rows={2} value={qualification} onChange={e=>setQualification(e.target.value)} placeholder="Must appear in proposal if using qualified assumption"/><label>Decision note</label><textarea rows={2} value={laborNote} onChange={e=>setLaborNote(e.target.value)} placeholder="Required rationale"/></div><SelfDeclared/><button className="btn primary full" disabled={busy||!laborDecision||!laborBy.trim()||!laborReview.trim()||!laborNote.trim()||hasScopeIssues||currentStatus==='processing'} onClick={()=>void resolveLabor()}>{busy?'Recording…':'Submit labor review'}<ArrowRight size={16}/></button><p className="tiny subdued">Engine must refuse unsupported determinations or missing approved rates.</p></section>}</aside></div>}
          {view==='release'&&<div className="workspace-grid"><div className="primary-column"><section className="card"><div className="card-heading"><div><p className="section-label">GATE 03 / COMMERCIAL AUTHORIZATION</p><h2>Release Gate</h2></div><span className="utility-icon"><ShieldCheck size={20}/></span></div><p className="muted">Review the engine's exact proposed commercial output. Every release is bound to a scope version and a proposal digest.</p>{tg&&<ReadinessBanner r={tg.readiness}/>}{tg&&<div className="export-row" data-testid="release-takeoff-row"><button type="button" className="btn outlined" data-testid="release-open-takeoff" onClick={openTakeoff}>Open the Takeoff Review</button><small className="muted">{tg.attestation?.current?'Takeoff reviewed for this scope version.':'A current Takeoff Review is required before release.'}</small></div>}{project.pricing?.estimate_view&&<ExportRow state={currentStatus==='released'?'released':'priced'}/>}<div className="release-overview"><div><span className="section-label">{tg&&tg.readiness.selected?.bid_ready!==true?'ENGINE TOTAL · DEMONSTRATION ONLY · NOT A BID':'ENGINE-PRICED TOTAL'}</span><div className="release-amount">{dollars(project.estimate?.total,project.estimate?.currency||'USD')}</div><small>{project.estimate?'Returned by deterministic pricing engine':'Estimate unavailable until earlier gates permit pricing'}</small></div><div className="digest"><span className="section-label">PROPOSAL DIGEST</span><strong>{project.proposal_digest||'Not available'}</strong><small>Scope version {project.scope_version??'—'}</small></div></div>{project.pricing?.estimate_view?<><ContractorNotice rs={project.pricing.ruleset}/><EstimateDetail view={project.pricing.estimate_view} econ={project.pricing.economics}/><PlanHistory h={project.pricing.plan_history}/></>:project.estimate?.items?.length?<div className="table-scroll"><table className="data-table"><thead><tr><th>Line item</th><th>Quantity</th><th>Rate</th><th>Total</th></tr></thead><tbody>{project.estimate.items.map((item,i)=><tr key={i}><td>{item.description||'Unnamed item'}</td><td>{formatValue(item.qty)} {item.unit||''}</td><td>{dollars(item.unit_price,project.estimate?.currency)}</td><td>{dollars(item.total,project.estimate?.currency)}</td></tr>)}</tbody></table></div>:<div className="empty-inline"><Scale size={22}/><strong>No priced line items available</strong><p>The browser cannot calculate or manufacture commercial values.</p></div>}</section><section className="card"><p className="section-label">CONTRACT QUALIFICATIONS</p><h2>Review before signing</h2><div className="qualification-columns"><div><h4>Qualifications</h4>{project.estimate?.qualifications?.length?project.estimate.qualifications.map((q,i)=><p key={i} className="bullet-line">{q}</p>):<p className="muted">None reported.</p>}</div><div><h4>Exclusions</h4>{project.estimate?.exclusions?.length?project.estimate.exclusions.map((q,i)=><p key={i} className="bullet-line">{q}</p>):<p className="muted">None reported.</p>}</div></div></section></div><aside className="secondary-column"><section className="card mini-card form-card"><p className="section-label">RELEASE AUTHORIZATION</p><h3>Named approval required</h3><div className={`approval-banner ${releaseReady?'ready':''}`}>{releaseReady?<CheckCircle2 size={19}/>:<LockKeyhole size={19}/>}<div><strong>{currentStatus==='released'?(demoRel?'Qualified demonstration release recorded (not a bid)':'Proposal already released'):releaseReady?(tg&&tg.readiness.selected?.bid_ready!==true?'Ready for a QUALIFIED DEMONSTRATION release only (not a bid)':'Ready for final authorization'):'Release currently blocked'}</strong><p>{currentStatus==='released'?'The engine has recorded its release decision.':'Scope, labor, pricing and digest must be accepted by engine first.'}</p></div></div><div className="input-stack"><label>Your name (self-declared, not verified)</label><input value={approver} onChange={e=>setApprover(e.target.value)} placeholder="Any name; recorded as self-declared"/><label>Approval note</label><textarea rows={3} value={releaseNote} onChange={e=>setReleaseNote(e.target.value)} placeholder="Reviewed scope, pricing and qualifications"/></div>{tg&&String(currentStatus)!=='released'&&<div className="takeoff-release" data-testid="takeoff-release"><p className="section-label">TAKEOFF CONDITIONS FOR RELEASE</p><p className="tiny" data-testid="tr-review">{tg.attestation?(tg.attestation.current?`Takeoff review CURRENT (by ${tg.attestation.by}, scope v${tg.attestation.scope_version}).`:'Takeoff review is STALE: the takeoff changed. Review it again.'):'No takeoff review recorded for this scope version.'} <button type="button" className="text-button" onClick={openTakeoff}>Open Takeoff Review</button></p><ul className="blocker-list">{tg.blockers.map((b:any)=><li key={b.code}><CircleAlert size={13}/><span><strong>{b.code}</strong>{b.hard?' (hard block)':''}</span></li>)}</ul><label className="check"><input type="checkbox" data-testid="ack-qualified" checked={ackQual} disabled={!!tg.release_hard_blockers.length} onChange={e=>setAckQual(e.target.checked)}/> I acknowledge these qualifications and request a QUALIFIED FICTIONAL DEMONSTRATION release. It is NOT BID READY and is not a submittable bid; post counts are provisional and any G3 values are self-declared assumptions.</label></div>}<SelfDeclared/><button className="btn primary full" disabled={!releaseReady||!approver.trim()||busy||(!!tg&&String(currentStatus)!=='released'&&!ackQual)} onClick={()=>void release()}>{busy?'Recording…':tg&&tg.readiness.selected?.bid_ready!==true?'Record QUALIFIED demonstration release (not a bid)':'Authorize final proposal'} <LockKeyhole size={16}/></button>{currentStatus==='released'&&<button className="btn outlined full" type="button" disabled title="The engine's proposal route is not implemented (HTTP 501)">Proposal PDF not available yet <LockKeyhole size={14}/></button>}{project.pricing&&currentStatus!=='released'&&<button className="btn outlined full" type="button" onClick={()=>setView('labor')}>Revise crew plan · voids this digest <ArrowRight size={14}/></button>}<p className="tiny subdued">Approval cannot be reused after changes. No automatic email delivery.</p></section></aside></div>}
          </div>}
        </>}
        <footer className="footer"><span>IFI GATEHOUSE <span className="dot-sep">·</span> A PROJECT OF IFI LABS</span><span><ShieldCheck size={14}/> Source evidence before commercial decisions</span></footer>
      </div>
      <FlightRecorder open={recorderOpen} onClose={()=>setRecorderOpen(false)}/>
      <AiActivity open={activityOpen} onClose={()=>setActivityOpen(false)}/>
      <BidDesk open={deskOpen} onClose={()=>setDeskOpen(false)} refreshKey={`${project?.scope_version}:${project?.status}:${project?.audit?.length}`}/>
      {!deskOpen&&<button type="button" className="bd-launch" data-testid="bd-launch" onClick={()=>setDeskOpen(true)} aria-label="Open the Gatehouse Bid Desk (simulated)"><MessageSquare size={16}/> Bid Desk <small className="bd-sim" data-testid="bd-launch-sim">SIMULATED</small></button>}
    </main>
  </div></ViewCtx.Provider>;
}

'use client';
// Takeoff Review: gross → opening deductions → net, then the ENGINE's per-class footing schedule (footing-calc.v1), the engine's own
// readiness fields, the two G3 workflows and a named (self-declared) review. Nothing is calculated or approved in the browser: every
// quantity, hash, price and readiness value below was returned by the engine through the proxy.
import {useCallback, useEffect, useRef, useState} from 'react';
import {CircleAlert, LoaderCircle, RefreshCw, ShieldCheck} from 'lucide-react';
import type {Project} from '@/lib/types';
import {EvidenceChip} from './dp001';
import type {DocEntry, Evidence, Target} from './dp001';
import {SelfDeclared} from './pricing';

/* eslint-disable @typescript-eslint/no-explicit-any */
const fmt=(n:unknown,d=0)=>typeof n==='number'&&Number.isFinite(n)?n.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d}):'—';
const usd=(n:unknown)=>typeof n==='number'&&Number.isFinite(n)?new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(n):'—';
const unknown=<span className="mini-tag warn" data-testid="unknown">UNKNOWN</span>;
const CLASS_LABEL:Record<string,string>={A_LINE:'Type A line post',A_CORNER_TERMINAL:'Type A corner / terminal post',GATE_G1:'G1 gate posts',GATE_G2:'G2 gate posts (Addendum 01)',GATE_G3:'G3 gate posts — specification UNRESOLVED',B_LINE:'Type B line post',B_TERMINAL:'Type B terminal post'};
const ORDER=['A_LINE','A_CORNER_TERMINAL','GATE_G1','GATE_G2','GATE_G3','B_LINE','B_TERMINAL'];
const EV_KEYS:Record<string,string>={A_LINE:'a_line',A_CORNER_TERMINAL:'a_terminal',GATE_G1:'g12_gate',GATE_G2:'g12_gate',GATE_G3:'g3_gate',B_LINE:'b_line',B_TERMINAL:'b_terminal'};

function Ev({keys,evidence,docs,view}:{keys:string[];evidence:Record<string,Evidence[]>;docs:Record<string,DocEntry>;view:(t:Target)=>void}){
  const seen=new Set<string>();const rows:Evidence[]=[];
  for(const k of keys)for(const e of evidence[k]||[]){const id=`${e.doc_id}|${e.page}|${e.excerpt}`;if(!seen.has(id)){seen.add(id);rows.push(e);}}
  return <div className="ev-list">{rows.map((e,i)=><EvidenceChip key={i} e={e} docs={docs} view={view}/>)}</div>;
}

/** The engine's authoritative readiness fields. Shown in the Takeoff, Estimate (Labor) and Release views; values are the engine's, never the client's. */
export function ReadinessBanner({r}:{r:any}){
  if(!r)return null;
  const sel=r.selected;const rel=r.release;
  const v=(x:unknown)=>x===null||x===undefined?'—':String(x);
  return <div className={`readiness ${r.tone}`} role="status" data-testid="readiness-banner" data-tone={r.tone}>
    <p className="readiness-head" data-testid="rd-headline">{r.headline}</p>
    <dl className="readiness-grid">
      <div><dt>bid_ready</dt><dd data-testid="rd-bid_ready">{sel?String(sel.bid_ready):rel?String(rel.bid_ready):'false (no priced scenario)'}</dd></div>
      <div><dt>release_class</dt><dd data-testid="rd-release_class">{rel?.release_class?v(rel.release_class):v(sel?.release_class)}</dd></div>
      <div><dt>artifact_kind</dt><dd data-testid="rd-artifact_kind">{rel?.artifact_kind?v(rel.artifact_kind):<em>{r.artifact_kind_note}</em>}</dd></div>
      <div><dt>footing_release_class</dt><dd data-testid="rd-footing_release_class">{Object.entries((rel?.footing_release_class)||r.footing_release_class||{}).map(([k,x])=><span key={k} className="rd-kv"><b>{k}</b> {v(x)}</span>)}</dd></div>
    </dl>
    {sel&&<p className="tiny" data-testid="rd-pricing_go">engine pricing_go = {String(sel.pricing_go)} · weakest input basis: {v(sel.weakest_input_basis)}{rel?` · released ${v(rel.released_at)} (audit event ${v(rel.audit_id)})`:''}</p>}
    {r.qualification_texts?.length>0&&<ul className="blocker-list" data-testid="rd-qualification-text">{r.qualification_texts.map((q:string,i:number)=><li key={i}><CircleAlert size={13}/><span>{q}</span></li>)}</ul>}
    <p className="tiny subdued">Source: {r.source}. A successful HTTP response is not bid readiness; this panel shows the engine's classification.</p>
  </div>;
}

export function TakeoffReview({project,docs,view,onRefresh}:{project:Project;docs:Record<string,DocEntry>;view:(t:Target)=>void;onRefresh:()=>void}){
  const [rev,setRev]=useState<any>(null);const [err,setErr]=useState('');const [loading,setLoading]=useState(true);
  const [tab,setTab]=useState<'base'|'alt'|null>(null);
  const [by,setBy]=useState('');const [note,setNote]=useState('');const [busy,setBusy]=useState(false);const [msg,setMsg]=useState('');
  const [wBy,setWBy]=useState('');const [wNote,setWNote]=useState('FICTIONAL WHAT-IF ONLY: self-declared G3 values, not stated in any document; RFI remains open and unsent.');const [wBusy,setWBusy]=useState(false);const [wMsg,setWMsg]=useState('');
  const pending=useRef<{fp:string;key:string}|null>(null);
  const load=useCallback(async()=>{
    try{const r=await fetch('/api/demo/takeoff',{cache:'no-store'});const b=await r.json();if(!r.ok)throw new Error(b.error||`HTTP ${r.status}`);setRev(b);setErr('');}
    catch(e){setErr(e instanceof Error?e.message:'Takeoff unavailable');}finally{setLoading(false);}
  },[]);
  useEffect(()=>{void load();},[load,project.scope_version,project.status,project.proposal_digest,project.audit?.length]);
  async function applyWhatIf(){
    if(!rev)return;setWBusy(true);setWMsg('');
    try{
      for(const f of rev.g3.facts as any[]){
        if(f.status!=='unresolved')continue;
        const r=await fetch('/api/demo/scope/resolve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({exception_id:f.exception_id,value:f.whatif_value,by:wBy.trim(),note:wNote.trim()})});
        const b=await r.json().catch(()=>({error:`HTTP ${r.status}`}));
        if(!r.ok)throw new Error(`${f.label}: ${b.error||`HTTP ${r.status}`}${b.code?` [${b.code}]`:''}`);
      }
      setWMsg('Fictional what-if recorded through the engine as four self-declared assumptions. Pricing below is the engine\'s.');
      await load();onRefresh();
    }catch(e){setWMsg(e instanceof Error?e.message:'Could not record the what-if');await load();onRefresh();}finally{setWBusy(false);}
  }
  async function attest(){
    if(!rev)return;setBusy(true);setMsg('');
    const body={by:by.trim(),note:note.trim(),takeoff_digest:rev.digest};const fp=JSON.stringify(body);
    if(!pending.current||pending.current.fp!==fp)pending.current={fp,key:`ifs-${crypto.randomUUID()}`};
    try{
      const r=await fetch('/api/demo/takeoff/review',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':pending.current.key},body:JSON.stringify(body)});
      const b=await r.json().catch(()=>({error:`HTTP ${r.status}`}));
      if(!r.ok){if(r.status>=400&&r.status<500&&r.status!==429)pending.current=null;throw new Error(`${b.error||`HTTP ${r.status}`}${b.code?` [${b.code}]`:''}`);}
      pending.current=null;
      setMsg(r.headers.get('idempotent-replay')==='true'?'This exact review was already recorded (historical result); nothing new was recorded.':'Takeoff review recorded for this scope version.');
      await load();onRefresh();
    }catch(e){setMsg(e instanceof Error?e.message:'Could not record the review');}finally{setBusy(false);}
  }
  if(loading)return <section className="card" role="status"><LoaderCircle className="spin" size={16}/> Loading takeoff…</section>;
  if(err||!rev)return <section className="card"><div className="notice error" role="alert"><CircleAlert size={16}/><span>{err||'Takeoff unavailable'}</span></div></section>;
  const sel:'base'|'alt'|null=rev.selected;const active:'base'|'alt'=tab||sel||'base';
  const S=rev.scenarios[active];const L=S.ledger;const F=S.footing;const ev=rev.evidence as Record<string,Evidence[]>;
  const isSel=active===sel;const noG3=rev.g3.facts[0].status==='unresolved';const att=rev.attestation;
  const rows:any[]=F?[...F.rows].sort((a:any,b:any)=>ORDER.indexOf(a.post_class)-ORDER.indexOf(b.post_class)):[];
  const g12=rows.filter(r=>r.post_class==='GATE_G1'||r.post_class==='GATE_G2');
  const pc=F?.partial_cost;const hard=rev.release_hard_blockers.length>0;
  const holeTag=(r:any)=>r.quantity===null||r.quantity===undefined?<>{unknown} <small>≥ {r.known_minimum}</small></>:r.quantity;
  return <section className="card takeoff" aria-label="Takeoff review" data-testid="takeoff-review" data-digest={rev.digest} data-selected={sel||''} data-scope-version={rev.scope_version}>
    <div className="card-heading"><div><p className="section-label">TAKEOFF REVIEW · CONTRACTOR RECONCILIATION</p><h2>Takeoff <span className="h2-count">DP-001</span></h2></div>
      <button className="text-button" onClick={()=>{void load();}}><RefreshCw size={14}/> Reload</button></div>
    <ReadinessBanner r={rev.readiness}/>
    <div className="guardrail" role="note"><CircleAlert size={19}/><span><strong>Post counts are PROVISIONAL.</strong> Quantities come from the engine's per-run footing calculation ({rev.contract.input} → {rev.contract.calc} / {rev.contract.schedule}) over a human reading of C101; they are not verified design quantities and not an approved takeoff. 716 / 576 LF are GROSS composite lengths, not billable net.</span></div>

    <div className="viewer-tabs" role="tablist" aria-label="Bid option">{(['base','alt'] as const).map(k=><button key={k} role="tab" aria-selected={active===k} data-testid={`tab-${k}`} className={`viewer-tab${active===k?' on':''}`} onClick={()=>setTab(k)}>{rev.scenario_defs[k].label}{sel===k?' · selected':''}</button>)}</div>
    {!isSel&&<p className="tiny subdued" data-testid="not-selected">{sel?`Not selected: ${rev.scenario_defs[active].label} is bid in lieu of ${rev.scenario_defs[sel].label}. Shown independently for comparison; never added.`:'No bid option selected yet. Both options are shown separately.'}</p>}

    {L&&<div data-testid={`ledger-${active}`} data-status={L.status}>
      <p className="section-label">QUANTITY LEDGER · {L.label.toUpperCase()} · {L.status.replaceAll('_',' ')}</p>
      <div className="table-scroll"><table className="data-table" aria-label="Quantity ledger"><thead><tr><th>Item</th><th>Quantity</th><th>Formula / basis</th><th>Status</th></tr></thead><tbody>
        <tr data-testid="row-gross-a"><td>Gross Type A perimeter</td><td>{fmt(L.gross.type_a)} LF</td><td>{L.gross.formula_a} (C101, post centerline)</td><td><span className="mini-tag">HUMAN-DERIVED · GROSS</span></td></tr>
        <tr data-testid="row-gross-b"><td>Gross Type B dividers</td><td>{fmt(L.gross.type_b)} LF</td><td>{L.gross.formula_b} (C101)</td><td><span className="mini-tag">HUMAN-DERIVED · GROSS</span></td></tr>
        <tr className="sum" data-testid="row-gross-total"><td>Gross combined fence</td><td>{fmt(L.gross.total)} LF</td><td>not billable net</td><td><span className="mini-tag warn">GROSS</span></td></tr>
        {L.openings.map((o:any)=><tr key={o.tag} data-testid={`row-open-${o.tag}`}><td>Deduct {o.tag} opening{o.count>1?`s (${o.count} × ${o.each} ft)`:''}</td><td>{o.total===null?unknown:<>− {fmt(o.total)} LF</>}</td><td>{o.basis}</td><td><span className={`mini-tag ${o.status==='documented'?'ok':'warn'}`}>{o.status==='documented'?'DOCUMENTED':o.status==='unresolved'?'UNRESOLVED · RFI':'HUMAN_ASSUMPTION — NOT DOCUMENTED'}</span></td></tr>)}
        <tr className="sum" data-testid="row-net-a"><td>Net Type A fence</td><td>{L.net.type_a===null?<>{unknown} <small>{L.net.formula_a}</small></>:<>{fmt(L.net.type_a)} LF</>}</td><td>{L.net.formula_a}; gate openings deducted (32 31 13 1.5.A)</td><td><span className="mini-tag warn">{L.net.type_a===null?'BLOCKED':'PROVISIONAL'}</span></td></tr>
        <tr className="sum" data-testid="row-net-b"><td>Net Type B fence</td><td>{fmt(L.net.type_b)} LF</td><td>no gates on Type B</td><td><span className="mini-tag warn">PROVISIONAL</span></td></tr>
        <tr className="sum" data-testid="row-net-total"><td>Net billable fence, combined</td><td>{L.net.total===null?<>{unknown} <small>{L.net.formula_total}</small></>:<>{fmt(L.net.total)} LF</>}</td><td>{L.net.formula_total}</td><td><span className="mini-tag warn">{L.net.total===null?'NO FINAL NUMBER':'NOT A FINAL PAY QUANTITY'}</span></td></tr>
        <tr data-testid="row-windscreen"><td>Windscreen (south Type A)</td><td>{fmt(L.accessories.windscreen_lf)} LF</td><td>full length between corner posts; field measure before ordering</td><td><span className="mini-tag">HUMAN-DERIVED</span></td></tr>
        <tr data-testid="row-guard"><td>Fence guard (Type B top rail)</td><td>{fmt(L.accessories.fence_guard_lf)} LF</td><td>equals Type B divider length</td><td><span className="mini-tag">HUMAN-DERIVED</span></td></tr>
        <tr data-testid="row-gates"><td>Gates, per each by tag</td><td>G1 × {L.gates.G1} · G2 × {L.gates.G2} · G3 × {L.gates.G3}</td><td>gates include posts, footings, frame, fabric and hardware (32 31 13 1.5.B)</td><td><span className="mini-tag ok">DOCUMENTED</span></td></tr>
      </tbody></table></div>
      <Ev keys={['gross_a','gross_b','measure','g1','g2','g3','windscreen','guard','gates']} evidence={ev} docs={docs} view={view}/>
    </div>}

    {!F&&<div className="notice info" role="note" data-testid="no-engine-schedule"><CircleAlert size={15}/><span><strong>No engine footing schedule for {S.label} in this project.</strong> {sel&&!isSel?`${rev.scenario_defs[sel].label} is selected and replaces the Base scope, so the engine computes the footing schedule only for the selected option. The quantity ledger above is the independent reference, shown conditionally.`:'The engine has not produced a footing schedule for this option.'} Nothing is estimated for it here.</span></div>}
    {F&&<div data-testid={`footings-${active}`} data-schedule-sha={F.schedule_sha256}>
      <p className="section-label">FOOTING SCHEDULE · {S.label.toUpperCase()} · ENGINE {F.calc_version} · PROVISIONAL GEOMETRY</p>
      <div className="table-scroll"><table className="data-table footing-table" aria-label="Footing schedule"><thead><tr><th>Class</th><th>Count</th><th>Footing Ø × depth</th><th>Concrete (CY)</th><th>Core holes</th><th>Cost basis (engine unit rates)</th><th>Basis · review</th></tr></thead><tbody>
        {rows.map((r:any)=><tr key={r.post_class} data-testid={`class-${r.post_class}`} data-quantity={r.quantity??''}>
          <td>{CLASS_LABEL[r.post_class]||r.post_class}<br/><small className="subdued">{r.run_id} · owner {r.owner}{r.owner.startsWith('GATE')?' · gate EACH, not billed again in fence LF':''}</small></td>
          <td data-testid="count">{holeTag(r)}</td>
          <td>{r.diameter_in===null?unknown:<>{r.diameter_in}″ × {r.depth_in}″</>}{r.post_od_in?<><br/><small className="subdued">post OD {r.post_od_in}″</small></>:null}</td>
          <td data-testid="concrete">{r.concrete_cy===null||r.concrete_cy===undefined?unknown:fmt(r.concrete_cy,4)}</td>
          <td data-testid="holes">{r.holes===null||r.holes===undefined?unknown:r.holes}</td>
          <td><small>{r.cost_basis?`${r.cost_basis.post_item} ${usd(r.cost_basis.post_material)} · concrete ${usd(r.cost_basis.concrete_before_rounding)} · S01 ${usd(r.cost_basis.core_drilling)}`:'unknown — not zero'}</small></td>
          <td><span className={`mini-tag ${r.value_basis==='documented'||r.value_basis==='calculated'?'ok':'warn'}`}>{String(r.value_basis).toUpperCase()}</span><br/><small className="subdued" data-testid="review-state">{r.review?.state}</small></td>
        </tr>)}
        {g12.length>0&&<tr className="sum" data-testid="class-G12"><td>G1 / G2 gate posts (subtotal)</td><td data-testid="count">{g12.reduce((a:number,r:any)=>a+(r.quantity||0),0)}</td><td colSpan={5}>F501 terminal / gate footing, Addendum 01 item 1.5</td></tr>}
        <tr className="sum" data-testid="class-total"><td>Total (engine totals)</td>
          <td><strong data-testid="posts-total">{F.totals.posts===null?<>{unknown} <small>≥ {F.totals.posts_counted + F.totals.posts_uncounted_known_minimum}</small></>:F.totals.posts}</strong></td><td>—</td>
          <td><strong data-testid="concrete-total">{F.totals.concrete_cy===null?<>{unknown}</>:fmt(F.totals.concrete_cy,4)}</strong></td>
          <td><strong data-testid="holes-total">{F.totals.core_drill_holes===null?<>{unknown}</>:F.totals.core_drill_holes}</strong></td><td colSpan={2}>every hole core drilled through pavement and base (3.2.E)</td></tr>
        <tr data-testid="concrete-known"><td colSpan={3}>Known-class concrete, G3 posts excluded</td><td data-testid="concrete-known-cy"><strong>{fmt(F.totals.known_concrete_cy,4)}</strong></td><td colSpan={3}>{F.totals.unknown_concrete?.cy===null&&F.totals.unknown_concrete?.classes?.length?`UNKNOWN (not zero): ${F.totals.unknown_concrete.classes.join(', ')}`:'complete'}</td></tr>
      </tbody></table></div>
      <p className="tiny subdued">Each post belongs to one footing class and one owner; shared posts are counted once. Gate posts belong to the gate EACH item. Core drilling is one flat S01 rate per hole (the rate book has no diameter-specific rate); concrete is one M40 rate.</p>
      <Ev keys={['a_line','a_terminal','g12_gate','g3_gate','b_line','b_terminal','spacing','core']} evidence={ev} docs={docs} view={view}/>
      <details><summary>Source references per class (engine)</summary><ul className="blocker-list">{rows.map((r:any)=><li key={r.post_class}><span><strong>{r.post_class}</strong>: {(r.source_refs||[]).map((s:any)=>`${s.sheet_label} (p${s.page})`).filter((x:string,i:number,a:string[])=>a.indexOf(x)===i).join(' · ')||'—'}{r.unresolved_inputs?.length?` · unresolved: ${r.unresolved_inputs.join(', ')}`:''}</span></li>)}</ul></details>
      <details data-testid="segments"><summary>Segments and line posts (engine, per run)</summary>{F.runs.map((run:any)=><div key={run.run_id}><p className="tiny"><strong>{run.run_id}</strong> · Type {run.fence_type} · {run.layout_kind}{run.repeat>1?` · repeated ${run.repeat}×`:''}</p><div className="table-scroll"><table className="data-table"><thead><tr><th>Segment</th><th>Length (LF)</th><th>Intervals</th><th>Line posts</th></tr></thead><tbody>{run.segments.map((s:any)=><tr key={s.segment_id}><td>{s.segment_id}<br/><small className="subdued">{s.from_post} → {s.to_post}</small></td><td>{s.length_lf===null?unknown:fmt(s.length_lf,1)}</td><td>{s.intervals===null?unknown:s.intervals}</td><td>{s.line_posts===null?unknown:s.line_posts}{s.unresolved?.length?<><br/><small className="warning-text">{s.unresolved.join('; ')}</small></>:null}</td></tr>)}</tbody></table></div></div>)}</details>
      {F.reconciliation&&<details data-testid="legacy-recon"><summary>Reconciliation with the Pass 6 aggregate method (engine)</summary>
        <p className="tiny">Pass 6 holes {F.reconciliation.legacy_holes} → per-class schedule {F.reconciliation.schedule_holes} (Δ {F.reconciliation.holes_delta>0?'+':''}{F.reconciliation.holes_delta}; explained {F.reconciliation.explained_delta}, unexplained {F.reconciliation.unexplained_delta}).</p>
        <ul className="blocker-list">{F.reconciliation.runs.map((r:any)=><li key={r.run_id}><span><strong>{r.run_id}</strong>: terminals {r.legacy_terminals} → {r.schedule_terminals}; line posts {r.legacy_line_posts} → {r.schedule_line_posts}. {r.explanation.reason}</span></li>)}</ul></details>}
      <p className="tiny subdued" data-testid="hashes">schedule_sha256 <span className="mono" title={F.schedule_sha256}>{F.schedule_sha256.slice(0,16)}…</span> · calc_inputs_sha256 <span className="mono" title={F.calc_inputs_sha256}>{F.calc_inputs_sha256.slice(0,16)}…</span> · convention {F.measurement_convention}</p>
    </div>}

    {pc&&<div data-testid={`partial-${active}`}><p className="section-label">KNOWN PARTIAL COST VS UNKNOWN EXPOSURE · {S.label.toUpperCase()}</p>
      <p><strong data-testid="partial-subtotal">{usd(pc.known_subtotal)}</strong> <span className="mini-tag warn" data-testid="partial-label">{pc.label}</span> <span className="mini-tag">NOT A PRICE · is_estimate = {String(pc.is_estimate)}</span></p>
      <p className="tiny subdued">{pc.scope}</p>
      <div data-testid="unknown-exposure">{pc.unknown_exposure?.length?<><p className="tiny"><strong>Unknown exposure (not zero, in no total):</strong></p><ul className="blocker-list">{pc.unknown_exposure.map((u:any,i:number)=><li key={i}><CircleAlert size={13}/><span><strong>{u.post_class}</strong> ({u.run_id}): {u.posts===null||u.posts===undefined?`≥ ${u.posts_known_minimum} posts, count unknown`:`${u.posts} posts`} — unknown: {u.unknown.join(', ')}. Why: {u.why.join('; ')}</span></li>)}</ul></>:<p className="tiny subdued">No unknown classes remain in this scenario's footing schedule (under the recorded assumptions).</p>}</div>
      {!F.posture.pricing_go&&<p className="notice warn-note" role="note" data-testid="no-complete-price"><CircleAlert size={15}/><span><strong>Complete bid price: NONE.</strong> The engine withholds a complete estimate while required inputs are unresolved (pricing_go = false). Unknown cost is not represented as zero.</span></p>}
    </div>}

    {rev.pricing&&isSel&&<div data-testid="pricing-status"><p className="section-label">ENGINE PRICING · {rev.pricing.scope_ref}</p>
      <p><strong>Engine total: <span data-testid="engine-total">{usd(rev.pricing.engine_total)}</span></strong> <span className="mini-tag warn" data-testid="pricing-qualifier">{rev.pricing.status}</span></p>
      <p className="tiny subdued">{rev.pricing.reason}{rev.pricing.ratebook?` Rate book ${rev.pricing.ratebook.id} v${rev.pricing.ratebook.version} (sha256 ${String(rev.pricing.ratebook.content_sha256).slice(0,12)}…).`:''}</p>
      <details open><summary>Engine cost lines</summary><div className="table-scroll"><table className="data-table"><tbody>{rev.pricing.breakdown.map((b:any)=><tr key={b.key} data-testid={`cost-${b.key}`}><td>{b.label}</td><td>{usd(b.amount)}</td></tr>)}</tbody></table></div></details>
      <p className="section-label">HOW THE ENGINE'S CREW LABOR USES THESE QUANTITIES</p>
      <div className="table-scroll"><table className="data-table" aria-label="Crew labor drivers"><thead><tr><th>Task</th><th>Engine qty</th><th>Schedule / reference</th><th>Crew · cost</th></tr></thead><tbody>
        {rev.labor.map((l:any)=><tr key={l.task_id} data-testid={`labor-${l.task_id}`} className={l.differs?'diff':''}><td>{l.task_id} {l.task}<br/><small className="subdued">{l.basis}</small></td><td>{fmt(l.engine_quantity)} {l.uom}</td><td>{l.reconciled_quantity===null?'—':fmt(l.reconciled_quantity)}</td><td>{l.crew}<br/>{usd(l.labor_cost)}</td></tr>)}
      </tbody></table></div>
      <p className="tiny subdued">Change crews in the Labor Gate crew planner; cost lines follow the engine's per-crew productivity and rates.</p>
    </div>}

    <div data-testid="crosscheck"><p className="section-label">INDEPENDENT CROSS-CHECK · {S.label.toUpperCase()}</p>
      <p className="tiny" data-testid="crosscheck-state"><span className={`mini-tag ${S.cross.ok?'ok':'warn'}`}>{S.cross.checked?(S.cross.ok?'AGREES':'DISAGREES'):'NOT AVAILABLE'}</span> The engine's schedule versus the separately written deterministic reference (reference pack sha256 {rev.reference.package_sha256.slice(0,12)}…). The reference prices nothing.</p>
      {S.cross.rows.length>0&&<details><summary>Row-by-row ({S.cross.rows.filter((r:any)=>r.ok).length}/{S.cross.rows.length} agree)</summary><div className="table-scroll"><table className="data-table"><thead><tr><th>Quantity</th><th>Engine</th><th>Reference</th><th></th></tr></thead><tbody>{S.cross.rows.map((r:any)=><tr key={r.key} data-testid={`xc-${r.key}`} className={r.ok?'':'diff'}><td>{r.label}</td><td>{r.engine===null?unknown:fmt(r.engine,r.key==='concrete_known'?4:0)}</td><td>{r.reference===null?unknown:fmt(r.reference,r.key==='concrete_known'?4:0)}</td><td>{r.ok?'✓':'✗'}</td></tr>)}</tbody></table></div></details>}
    </div>

    <div data-testid="blockers"><p className="section-label">QUALIFICATIONS AND RELEASE BLOCKERS</p>
      <ul className="blocker-list">{rev.blockers.map((b:any)=><li key={b.code} data-testid={`blocker-${b.code}`}><CircleAlert size={14}/><span><strong>{b.code}</strong>{b.hard?' (hard block)':''}: {b.message}</span></li>)}</ul>
      <p className="tiny subdued">Release needs a current takeoff review and an explicit acknowledgement of every non-hard qualification. It can only ever record a labelled demonstration while the engine says bid_ready = false.</p>
    </div>

    <div data-testid="g3-state" data-state={rev.g3.state}><p className="section-label">GATE G3 · TWO WORKFLOWS</p>
      <p><strong>{rev.g3.state==='unresolved'?'A. Unresolved.':rev.g3.state==='partially_assumed'?'Partly assumed.':'B. Explicit fictional what-if recorded.'}</strong> {rev.g3.state==='unresolved'?'No opening, post size or footing is assumed; nothing is defaulted to zero.':'Values below are self-declared assumptions, NOT document facts.'} RFI {rev.g3.rfi.id} is <strong>{rev.g3.rfi.status.toUpperCase()}</strong> and <strong>{rev.g3.rfi.sent?'sent':'NOT SENT'}</strong>.</p>
      <div className="table-scroll"><table className="data-table" aria-label="G3 requirements"><thead><tr><th>Requirement</th><th>Status</th><th>Value</th></tr></thead><tbody>
        {rev.g3.facts.map((f:any)=><tr key={f.id} data-testid={`g3-${f.id}`}><td>{f.label}<br/><small className="subdued">{f.path}</small></td><td><span className={`mini-tag ${f.status==='unresolved'?'warn':''}`}>{f.status==='unresolved'?'UNRESOLVED · RFI':'HUMAN_ASSUMPTION — NOT DOCUMENTED'}</span></td><td>{f.value===null?unknown:<>{f.value} {f.unit}<br/><small className="subdued">by {f.by} (self-declared)</small></>}</td></tr>)}
      </tbody></table></div>
      {rev.g3.state!=='assumed'?<div className="input-stack" data-testid="whatif-form">
        <p className="tiny"><strong>{rev.g3.whatif.label}.</strong> Applies exactly: opening {rev.g3.whatif.values.opening} ft · post OD {rev.g3.whatif.values.post_od} in · footing {rev.g3.whatif.values.diameter} in × {rev.g3.whatif.values.depth} in. Recorded through the Scope gate as {rev.g3.open_count} self-declared decision{rev.g3.open_count===1?'':'s'}; priced only by the engine; permanent for this project (reset the demo to start over).</p>
        <label>Your name (self-declared, not verified)</label><input aria-label="What-if name" value={wBy} onChange={e=>setWBy(e.target.value)} placeholder="Any name; recorded as self-declared"/>
        <label>Assumption note</label><textarea aria-label="What-if note" rows={2} value={wNote} onChange={e=>setWNote(e.target.value)}/>
        <button className="btn outlined full" data-testid="apply-whatif" disabled={wBusy||!wBy.trim()||!wNote.trim()||!sel} onClick={()=>{void applyWhatIf();}}>{wBusy?'Recording…':'Apply fictional G3 what-if (not a document fact)'}</button>
        {!sel&&<p className="tiny warning-text">Select a bid option at the Scope gate first.</p>}
        {wMsg&&<p className="tiny" role="status" data-testid="whatif-msg">{wMsg}</p>}
      </div>:<p className="tiny subdued" data-testid="whatif-applied">The what-if is recorded. A recorded value cannot be revised over the HTTP adapter (no persistent scope-revision route); reset the demo to explore the unresolved state again.</p>}
    </div>

    <div data-testid="attestation"><p className="section-label">TAKEOFF REVIEW · SCOPE VERSION v{rev.scope_version}</p>
      {att?<p data-testid="att-state" data-current={att.current?'1':'0'}><span className={`mini-tag ${att.current?'ok':'warn'}`}>{att.current?'CURRENT':'STALE: the takeoff changed after this review'}</span> Reviewed by {att.by} (self-declared) at scope v{att.scope_version}, digest {att.digest.slice(0,12)}… “{att.note}”</p>:<p className="tiny subdued" data-testid="att-state" data-current="0">No takeoff review recorded for this scope version.</p>}
      {hard?<p className="tiny warning-text" data-testid="att-blocked">The takeoff cannot be reviewed while {rev.release_hard_blockers.join(' / ')} {rev.release_hard_blockers.length>1?'are':'is'} open.</p>:<div className="input-stack">
        <label>Your name (self-declared, not verified)</label><input aria-label="Takeoff reviewer name" value={by} onChange={e=>setBy(e.target.value)} placeholder="Any name; recorded as self-declared"/>
        <label>Review note</label><textarea aria-label="Takeoff review note" rows={2} value={note} onChange={e=>setNote(e.target.value)} placeholder="What did you check against the drawings?"/>
        <SelfDeclared/>
        <button className="btn primary full" disabled={busy||!by.trim()||!note.trim()} onClick={()=>{void attest();}}>{busy?'Recording…':'Record takeoff review'}</button>
        <p className="tiny subdued">Records that a named person reviewed THIS takeoff (digest {rev.digest.slice(0,12)}…, bound to both scenarios' schedule hashes). Counts stay PROVISIONAL; this is not a contractor approval.</p>
        {msg&&<p className="tiny" role="status" data-testid="att-msg">{msg}</p>}</div>}
    </div>
    <p className="tiny subdued"><ShieldCheck size={12}/> Digest <span data-testid="takeoff-digest">{rev.digest.slice(0,16)}</span>… binds scenario, scope version and the engine schedule/calculation hashes above.</p>
  </section>;
}

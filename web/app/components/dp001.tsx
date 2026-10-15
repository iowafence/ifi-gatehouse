'use client';
// DP-001 document package, embedded PDF viewer and the evidence-linked, HUMAN-PREPARED scope draft.
// Nothing here calculates money or approves anything: statuses are derived from the engine's own exceptions and audit trail.
import {createContext, memo, useCallback, useContext, useEffect, useRef, useState} from 'react';
import {BookOpenText, CheckCircle2, CircleAlert, ExternalLink, FileText, Hash, LoaderCircle, Minus, Plus, ShieldCheck} from 'lucide-react';
import type {Project} from '@/lib/types';

export type DocEntry={doc_id:string;filename:string;sha256:string;bytes:number;pages:number;name:string;group:string;revision:string;controlling:boolean;hash_verified:boolean;sheet_size?:string|null};
export type Sheet={sheet:string;page:number;title:string;doc_id:string};
export type Registry={source_manifest:string;note:string;documents:DocEntry[];sheets:Sheet[]};
export type Evidence={doc_id:string;page:number;sheet_label?:string;excerpt:string;superseded_by?:{doc_id:string;item:string};note?:string};
export type DraftItem={id:string;section:string;title:string;text:string;figure:string;option:'base'|'alt'|'both';kind:string;fact_paths:string[];evidence:Evidence[];note?:string};
export type Rfi={id:string;title:string;question:string;blocks_release:boolean;status:string;needed_by:string;evidence:Evidence[]};
export type Draft={project_ref:string;title:string;provenance:string;items:DraftItem[];rfis:Rfi[];limitations:string[]};
export type Target={doc_id:string;page:number;excerpt?:string;rects?:number[][];rectKey?:string;cite?:string};

type Diag={mounts:number;unmounts:number;renderStarts:number;renderDone:number;cancelled:number;loadingFlashes:number;resizes:number;sizes:number[];docLoads:number;events:{t:number;e:string}[]};
function diag():Diag|null{
  if(typeof window==='undefined')return null;
  try{if(localStorage.getItem('pdfDiag')!=='1')return null;}catch{return null;}
  const w=window as unknown as {__pdfDiag?:Diag};
  return w.__pdfDiag||(w.__pdfDiag={mounts:0,unmounts:0,renderStarts:0,renderDone:0,cancelled:0,loadingFlashes:0,resizes:0,sizes:[],docLoads:0,events:[]});
}
const note=(k:keyof Diag|null,e:string)=>{const d=diag();if(!d)return;if(k&&typeof d[k]==='number')(d[k] as number)++;if(d.events.length<400)d.events.push({t:Math.round(performance.now()),e});};
export const ViewCtx=createContext<{view:(t:Target)=>void;docs:Record<string,DocEntry>}|null>(null);
const shortSha=(h:string)=>`${h.slice(0,12)}…${h.slice(-6)}`;

export function Identity({d}:{d:DocEntry}){
  return <div className="doc-identity" data-testid={`identity-${d.doc_id}`}>
    <span className="mono" title={d.sha256}><Hash size={12}/> SHA-256 {shortSha(d.sha256)}</span>
    <span className={`mini-tag ${d.hash_verified?'ok':''}`}>{d.hash_verified?'IDENTITY VERIFIED':'IDENTITY NOT VERIFIED'}</span>
  </div>;
}

// ------------------------------------------------------------------ PDF viewer (pdf.js, same-origin worker, no external requests)
// Stability rules (root cause of the reported flashing: the render width was read from the SCROLLING stage, so the vertical scrollbar
// appearing/disappearing changed the width, which changed the canvas height, which toggled the scrollbar again: an endless render loop that
// also raised the loading overlay and cleared the resized canvas on every pass):
//  * the width is measured on a NON-scrolling frame, with a reserved scrollbar allowance and a hysteresis, so scrollbars cannot feed back;
//  * a page is rendered to an off-screen canvas and swapped in synchronously, so the visible drawing is never cleared while re-rendering;
//  * the loading overlay is only for the very first paint or an error; later renders keep the current drawing visible;
//  * loaded PDF documents are cached at module level, so a remount never refetches or re-verifies the same document;
//  * the component is memoized on its primitive inputs so unrelated project/scope/pricing updates do not re-render it.
type PdfDoc={numPages:number;getPage:(n:number)=>Promise<any>}; // eslint-disable-line @typescript-eslint/no-explicit-any
const docCache=new Map<string,Promise<PdfDoc>>();
const SCROLLBAR_ALLOWANCE=20, WIDTH_HYSTERESIS=24;
function loadPdf(id:string):Promise<PdfDoc>{
  // The promise is stored synchronously, so concurrent callers (two effect passes before the first await resolves) share ONE fetch.
  let hit=docCache.get(id);
  if(!hit){
    note('docLoads','getDocument '+id);
    hit=import('pdfjs-dist/build/pdf.mjs').then(pdfjs=>{
      pdfjs.GlobalWorkerOptions.workerSrc='/pdf.worker.min.mjs';
      return pdfjs.getDocument({url:`/api/demo/documents/${id}`}).promise as unknown as Promise<PdfDoc>;
    });
    hit.catch(()=>docCache.delete(id)); // a failed load may be retried; a good one is never reloaded
    docCache.set(id,hit);
  }
  return hit;
}
function DocViewerImpl({registry,target,setTarget}:{registry:Registry;target:Target;setTarget:(t:Target)=>void}){
  const d=registry.documents.find(x=>x.doc_id===target.doc_id);
  const frame=useRef<HTMLDivElement>(null);const canvas=useRef<HTMLCanvasElement>(null);
  const shown=useRef(false);                       // the canvas already holds a drawing
  const [zoom,setZoom]=useState(1);const [width,setWidth]=useState(0);
  const [state,setState]=useState<'loading'|'ready'|'error'>('loading');const [err,setErr]=useState('');
  const [busy,setBusy]=useState(false);
  const [rendered,setRendered]=useState<{doc:string;page:number}|null>(null);
  const [marks,setMarks]=useState<{l:number;t:number;w:number;h:number}[]>([]);const [found,setFound]=useState<boolean|null>(null);
  const [size,setSize]=useState<{w:number;h:number}>({w:0,h:0});
  useEffect(()=>{note('mounts','mount');return()=>note('unmounts','unmount');},[]);
  useEffect(()=>{
    const el=frame.current;if(!el)return;
    const measure=()=>{
      const w=Math.floor(el.clientWidth)-SCROLLBAR_ALLOWANCE;
      setWidth(cur=>(cur===0||Math.abs(w-cur)>=WIDTH_HYSTERESIS)?w:cur);   // ignore changes smaller than a scrollbar
    };
    const ro=new ResizeObserver(()=>{note('resizes','resize '+el.clientWidth);measure();});ro.observe(el);measure();
    return()=>ro.disconnect();
  },[]);
  const docId=d?.doc_id,page=target.page,excerpt=target.excerpt,rectKey=target.rectKey;const rectsRef=useRef(target.rects);rectsRef.current=target.rects;
  useEffect(()=>{
    let cancelled=false;let task:{cancel:()=>void}|null=null;
    if(!docId||width<=0)return;
    if(!shown.current)setState('loading');else setBusy(true);   // never blank an already visible drawing
    note('renderStarts',`render start p${page} w${width} z${zoom}`);
    (async()=>{
      try{
        const pdf=await loadPdf(docId);
        const pg=await pdf.getPage(Math.min(Math.max(1,page),pdf.numPages));
        const base=pg.getViewport({scale:1});
        const vp=pg.getViewport({scale:width/base.width*zoom});
        const dpr=Math.min(window.devicePixelRatio||1,2);
        const off=document.createElement('canvas');off.width=Math.floor(vp.width*dpr);off.height=Math.floor(vp.height*dpr);
        const rt=pg.render({canvasContext:off.getContext('2d')!,viewport:vp,transform:dpr!==1?[dpr,0,0,dpr,0,0]:undefined});
        task=rt;
        await rt.promise;
        if(cancelled)return;
        // Locate the cited excerpt in the PDF's own text layer and outline it. Best effort: no match means no outline, never a guess.
        const m:{l:number;t:number;w:number;h:number}[]=[];let hit:boolean|null=null;
        if(excerpt){
          const tc=await pg.getTextContent();const norm=(x:string)=>x.replace(/[\u2019]/g,"'").replace(/[\u201c\u201d]/g,'"').replace(/\s+/g,' ').toLowerCase();
          let full='';const spans:{s:number;e:number;it:any}[]=[]; // eslint-disable-line @typescript-eslint/no-explicit-any
          for(const it of tc.items as any[]){ // eslint-disable-line @typescript-eslint/no-explicit-any
            if(!('str' in it)||!it.str.trim())continue;const st=full.length;full+=norm(it.str)+' ';spans.push({s:st,e:full.length,it});
          }
          const ex=norm(excerpt).trim();const idx=full.indexOf(ex);
          if(idx>=0){
            hit=true;
            for(const sp of spans)if(sp.e>idx&&sp.s<idx+ex.length){
              const tr=sp.it.transform as number[];
              const r=vp.convertToViewportRectangle([tr[4],tr[5],tr[4]+sp.it.width,tr[5]+(sp.it.height||Math.abs(tr[3]))]);
              m.push({l:Math.min(r[0],r[2]),t:Math.min(r[1],r[3]),w:Math.abs(r[2]-r[0]),h:Math.abs(r[3]-r[1])});
            }
          }else hit=false;
        }
        if(rectsRef.current?.length){ // PDF-derived label positions (normalized to the page, origin top-left): outline them; never a model-supplied box
          for(const r of rectsRef.current){const pad=3;m.push({l:r[0]*vp.width-pad,t:r[1]*vp.height-pad,w:(r[2]-r[0])*vp.width+2*pad,h:(r[3]-r[1])*vp.height+2*pad});}
          hit=true;
        }
        if(cancelled)return;
        const cv=canvas.current;if(!cv)return;
        // swap in one synchronous step: resizing a canvas clears it, so the finished off-screen bitmap is drawn immediately afterwards
        cv.width=off.width;cv.height=off.height;cv.style.width=`${Math.floor(vp.width)}px`;cv.style.height=`${Math.floor(vp.height)}px`;
        cv.getContext('2d')!.drawImage(off,0,0);
        shown.current=true;
        note('renderDone','render done');
        setSize({w:vp.width,h:vp.height});setMarks(m);setFound(hit);setRendered({doc:docId,page});setBusy(false);setState('ready');
      }catch(e){
        if(cancelled||(e as {name?:string})?.name==='RenderingCancelledException')return;
        setErr(e instanceof Error?e.message:'Could not open the document');setBusy(false);setState(shown.current?'ready':'error');
      }
    })();
    return()=>{if(!cancelled)note('cancelled','effect cleanup (render superseded)');cancelled=true;try{task?.cancel();}catch{/* already finished */}};
  },[docId,page,excerpt,rectKey,width,zoom]);
  if(!d)return <div className="notice error"><CircleAlert size={16}/><span>Unknown document.</span></div>;
  const sheets=registry.sheets.filter(s=>s.doc_id===d.doc_id);
  const sheet=sheets.find(s=>s.page===target.page);
  return <section className="card viewer-card" aria-label="Document viewer" data-testid="doc-viewer" data-doc={d.doc_id} data-page={target.page}
      data-rendered-doc={rendered?.doc||''} data-rendered-page={rendered?.page||''} data-busy={busy?'1':'0'}>
    <div className="card-heading"><div><p className="section-label">DOCUMENT VIEWER</p><h2>{d.name}{sheet?` · ${sheet.sheet}`:''}</h2></div>
      <a className="text-button" href={`/api/demo/documents/${d.doc_id}${'#page='+target.page}`} target="_blank" rel="noreferrer"><ExternalLink size={14}/> Open original PDF</a></div>
    <div className="viewer-tabs" role="tablist" aria-label="Bid documents">{registry.documents.map(x=><button key={x.doc_id} role="tab" aria-selected={x.doc_id===d.doc_id} className={`viewer-tab${x.doc_id===d.doc_id?' on':''}`} onClick={()=>setTarget({doc_id:x.doc_id,page:1})}>{x.group==='drawings'?'Drawings':x.group==='specifications'?'Project Manual':x.group==='bidding'?'Instructions to Bidders':'Addendum 01'}{x.controlling?' ★':''}</button>)}</div>
    {sheets.length>0&&<div className="viewer-tabs sheets" role="tablist" aria-label="Drawing sheets">{sheets.map(sh=><button key={sh.sheet} role="tab" aria-selected={sh.page===target.page} className={`viewer-tab${sh.page===target.page?' on':''}`} title={sh.title} onClick={()=>setTarget({doc_id:d.doc_id,page:sh.page})}>{sh.sheet}</button>)}</div>}
    <div className="viewer-meta"><span><FileText size={12}/> {d.filename}</span><span>{d.revision}</span><span>p{target.page} of {d.pages}</span><Identity d={d}/>{busy&&<span className="tiny subdued" role="status">Updating…</span>}</div>
    {d.controlling&&<div className="notice info" role="note"><ShieldCheck size={15}/><span><strong>Controlling document.</strong> Addendum 01 governs over the Drawings, Specifications and Special Conditions.</span></div>}
    <div className="viewer-bar">
      {sheets.length===0&&<><button className="btn ghost" disabled={target.page<=1} onClick={()=>setTarget({doc_id:d.doc_id,page:target.page-1})}>Prev page</button><button className="btn ghost" disabled={target.page>=d.pages} onClick={()=>setTarget({doc_id:d.doc_id,page:target.page+1})}>Next page</button></>}
      <span className="viewer-zoom"><button className="btn ghost" aria-label="Zoom out" onClick={()=>setZoom(z=>Math.max(1,+(z-0.5).toFixed(1)))}><Minus size={14}/></button><span>{Math.round(zoom*100)}%</span><button className="btn ghost" aria-label="Zoom in" onClick={()=>setZoom(z=>Math.min(4,+(z+0.5).toFixed(1)))}><Plus size={14}/></button></span>
    </div>
    <div className="viewer-frame" ref={frame}>
      <div className="viewer-stage">
        <div className="viewer-canvas-wrap" style={{width:size.w||undefined,height:size.h||undefined}}>
          <canvas ref={canvas} aria-label={`${d.name} page ${target.page}`}/>
          {state==='ready'&&marks.map((m,i)=><span key={i} className="viewer-mark" style={{left:m.l,top:m.t,width:m.w,height:m.h}} data-testid="viewer-mark"/>)}
        </div>
        {state==='loading'&&<div className="viewer-overlay" role="status"><LoaderCircle className="spin" size={18}/> Opening document…</div>}
        {state==='error'&&<div className="viewer-overlay error" role="alert"><CircleAlert size={16}/> {err}</div>}
      </div>
    </div>
    {target.cite&&<p className="tiny subdued viewer-cite" data-testid="viewer-cite">{target.cite}</p>}
    {target.excerpt&&<p className="tiny subdued viewer-cite" data-testid="viewer-cite">Cited text: “{target.excerpt}”{state==='ready'&&found===false?' (not outlined on the page; the text layer breaks it across columns)':''}</p>}
  </section>;
}
// Re-render only when the document, page, highlight or registry identity changes; project, scope and pricing updates never reach the viewer.
export const DocViewer=memo(DocViewerImpl,(a,b)=>a.registry===b.registry&&a.setTarget===b.setTarget&&a.target.doc_id===b.target.doc_id&&a.target.page===b.target.page&&a.target.excerpt===b.target.excerpt&&a.target.rectKey===b.target.rectKey&&a.target.cite===b.target.cite);

// ------------------------------------------------------------------ document package list
export function DocumentPackage({registry,onOpen}:{registry:Registry;onOpen:(t:Target)=>void}){
  const add=registry.documents.find(x=>x.group==='addendum');
  const rest=registry.documents.filter(x=>x.group!=='addendum');
  return <section className="card" aria-label="Bid documents" data-testid="doc-package">
    <div className="card-heading"><div><p className="section-label">DP-001 · BID PACKAGE · ANSI B DRAWING SET</p><h2>Bid documents <span className="h2-count">{registry.documents.length}</span></h2></div></div>
    <p className="tiny subdued">Identities come from the existing document manifest ({registry.source_manifest}). Each file is hash-checked before it is shown. The coordinated ANSI D parent and the superseded earlier ANSI B copy are separate identities and are not part of this project.</p>
    {add&&<div className="doc-row addendum-row" data-testid="doc-addendum"><div className="doc-icon"><BookOpenText size={18}/></div><div className="doc-main"><strong>{add.name} <span className="mini-tag ok">CONTROLLING DOCUMENT</span></strong><small>{add.filename} · {add.revision} · {add.pages} page</small><Identity d={add}/><small>Governs over the Drawings, Specifications and Special Conditions (00 0200 §3.4.1; SC-1.2.1).</small></div><button className="btn ghost" onClick={()=>onOpen({doc_id:add.doc_id,page:1})}>Open</button></div>}
    <div className="document-table">{rest.map(x=><div className="doc-row" key={x.doc_id} data-testid={`doc-${x.doc_id}`}><div className="doc-icon"><FileText size={18}/></div><div className="doc-main"><strong>{x.name}</strong><small>{x.filename} · {x.revision} · {x.pages} page{x.pages===1?'':'s'}{x.sheet_size?` · ${x.sheet_size}`:''}</small><Identity d={x}/>
      {x.group==='drawings'&&<div className="sheet-links">{registry.sheets.map(s=><button key={s.sheet} className="chip-btn" title={s.title} onClick={()=>onOpen({doc_id:x.doc_id,page:s.page})}>{s.sheet}</button>)}</div>}</div>
      <button className="btn ghost" onClick={()=>onOpen({doc_id:x.doc_id,page:1})}>Open</button></div>)}</div>
  </section>;
}

// ------------------------------------------------------------------ evidence-linked scope draft
function selectedBid(p:Project):'base'|'alt'|null{
  const e=[...(p.audit||[])].reverse().find(a=>a.exception_id?.includes('BID_SELECTION'));
  return !e?null:e.option_id==='base'?'base':'alt';
}
function status(it:DraftItem,p:Project):{label:string;tone:'ok'|'warn'|'info'}{
  const sel=selectedBid(p);
  const open=(p.exceptions||[]).filter(e=>(e.affected_paths||[]).some(x=>it.fact_paths.includes(x)));
  if(it.kind==='decision'){
    if(!sel)return {label:'Awaiting your decision at the Scope gate',tone:'warn'};
    const mine=(it.option==='base')===(sel==='base');
    return mine?{label:'Selected by you (self-declared)',tone:'ok'}:{label:'Not selected: bid in lieu',tone:'info'};
  }
  if(it.kind==='stated')return {label:'Stated in the documents',tone:'ok'};
  if(it.kind==='controlled')return {label:'Controlled by Addendum 01',tone:'ok'};
  if(it.kind==='other_trades')return {label:'Not fence scope: reference only',tone:'info'};
  if(it.kind==='footing')return open.length?{label:'Per-class footings · G3 size unresolved (RFI)',tone:'warn'}:{label:'Per-class footings · G3 recorded as qualified assumption',tone:'ok'};
  if(it.kind==='limited')return {label:'Stated · engine modeling limit',tone:'warn'};
  if(it.kind==='owner_selection')return open.length?{label:'Owner selection pending: no price effect',tone:'info'}:{label:'Resolved',tone:'ok'};
  if(it.kind==='unresolved')return open.length?{label:'Unresolved: RFI required',tone:'warn'}:{label:'Value recorded by your decision (qualified assumption)',tone:'ok'};
  if(it.kind==='derived')return open.length?{label:'Human-prepared derivation: awaiting your approval',tone:'warn'}:{label:'Approved by your decision',tone:'ok'};
  return {label:'Awaiting review',tone:'info'};
}
const optLabel={base:'BASE BID',alt:'ALTERNATE A-1',both:'BOTH OPTIONS'} as const;

export function EvidenceChip({e,docs,view}:{e:Evidence;docs:Record<string,DocEntry>;view:(t:Target)=>void}){
  const d=docs[e.doc_id];
  return <div className={`ev-row${e.superseded_by?' superseded':''}`} data-testid="ev-row">
    <button className="chip-btn" onClick={()=>view({doc_id:e.doc_id,page:e.page,excerpt:e.superseded_by?undefined:e.excerpt})} title="Show this evidence in the viewer">
      <FileText size={12}/> {e.sheet_label||d?.name||e.doc_id} · p{e.page}</button>
    <span className="ev-text">“{e.excerpt}”{e.superseded_by&&<em> — SUPERSEDED by Addendum 01; traceability only</em>}</span>
  </div>;
}

export function ScopeDraft({draft,project,docs,view}:{draft:Draft;project:Project;docs:Record<string,DocEntry>;view:(t:Target)=>void}){
  const sel=selectedBid(project);
  const sections=[...new Set(draft.items.map(i=>i.section))];
  return <section className="card scope-draft" aria-label="Scope draft" data-testid="scope-draft">
    <div className="card-heading"><div><p className="section-label">{draft.provenance}</p><h2>Scope draft <span className="h2-count">{draft.items.length}</span></h2></div></div>
    <div className="guardrail" role="note"><CircleAlert size={19}/><span><strong>Human-prepared, not AI inference.</strong> Prepared by a person from the document text and attached to the exact document identities above. AMD-derived findings (stored outputs, offline) are listed separately under AI Findings and never author or change this draft. Nothing here is approved until you decide at the Scope gate.</span></div>
    <p className="tiny subdued" data-testid="bid-state">Bid option: <strong>{sel==='base'?'Base Bid (four courts)':sel==='alt'?'Alternate A-1 (three courts, in lieu of the Base Bid)':'not selected yet'}</strong></p>
    {sections.map(sec=><div key={sec} className="draft-section"><p className="section-label">{sec.toUpperCase()}</p>
      {draft.items.filter(i=>i.section===sec).map(it=>{const st=status(it,project);return <article key={it.id} className="draft-item" data-testid={`item-${it.id}`} data-status={st.tone}>
        <div className="draft-head"><strong>{it.title}</strong><span className="mini-tag">{optLabel[it.option]}</span></div>
        <p className="draft-figure">{it.figure}</p><p className="muted">{it.text}</p>
        <div className="draft-badges"><span className="mini-tag human">HUMAN-PREPARED</span><span className={`mini-tag ${st.tone==='ok'?'ok':st.tone==='warn'?'warn':''}`} data-testid="item-status">{st.label}</span></div>
        {it.note&&<p className="tiny warning-text">{it.note}</p>}
        {it.evidence.length>0&&<div className="ev-list">{it.evidence.map((e,i)=><EvidenceChip key={i} e={e} docs={docs} view={view}/>)}</div>}
      </article>;})}</div>)}
    <div className="draft-section" data-testid="rfi-list"><p className="section-label">REQUESTS FOR INFORMATION (DRAFTS, NOT SENT)</p>
      {draft.rfis.map(r=><article key={r.id} className="draft-item rfi" data-testid={`rfi-${r.id}`}><div className="draft-head"><strong>{r.title}</strong><span className={`mini-tag ${r.blocks_release?'warn':''}`}>{r.blocks_release?'BLOCKS RELEASE UNTIL DECIDED':'CLARIFICATION'}</span></div>
        <p className="muted">{r.question}</p><p className="tiny subdued">{r.needed_by}. This build does not send RFIs.</p>
        <div className="ev-list">{r.evidence.map((e,i)=><EvidenceChip key={i} e={e} docs={docs} view={view}/>)}</div></article>)}</div>
    <div className="draft-section"><p className="section-label">LIMITATIONS</p><ul className="blocker-list">{draft.limitations.map((l,i)=><li key={i}><CircleAlert size={14}/><span>{l}</span></li>)}</ul></div>
  </section>;
}

export function useDp001(){
  const [registry,setRegistry]=useState<Registry|null>(null);const [draft,setDraft]=useState<Draft|null>(null);const [unavailable,setUnavailable]=useState(false);
  const load=useCallback(async()=>{
    try{
      const [a,b]=await Promise.all([fetch('/api/demo/documents',{cache:'no-store'}),fetch('/api/demo/scope-draft',{cache:'no-store'})]);
      if(!a.ok||!b.ok){setUnavailable(true);return;}
      setRegistry(await a.json());setDraft(await b.json());
    }catch{setUnavailable(true);}
  },[]);
  useEffect(()=>{void load();},[load]);
  return {registry,draft,unavailable};
}
export function useNarrow(){
  const [n,setN]=useState(false);
  useEffect(()=>{const m=window.matchMedia('(max-width:1100px)');const f=()=>setN(m.matches);f();m.addEventListener('change',f);return()=>m.removeEventListener('change',f);},[]);
  return n;
}
export {CheckCircle2};

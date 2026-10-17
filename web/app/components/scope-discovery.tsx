'use client';
// Scope Gate, discovery-first: shows what was found, one gate at a time, each finding with the provenance of its source. It decides nothing; the
// decision forms below it are the existing ones and the engine still validates every decision.
import { useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { CheckCircle2, CircleAlert, FileText, Info, ShieldAlert } from 'lucide-react';
import { ViewCtx } from './dp001';
import { buildScopeGates, currentGate, type Finding, type Gate, type Prov, type Src } from '@/lib/scope-gates';

/* eslint-disable @typescript-eslint/no-explicit-any */
const PROV_HELP: Record<Prov, string> = {
  'AGENT-FOUND': 'A model proposed this from the documents. A candidate only; code verifies it and a named person decides.',
  'ADDENDUM': 'Stated by an addendum document, with its page and quote.',
  'ENGINE-FLAGGED': 'The deterministic engine flagged this from the documents and rules.',
  'ENGINE-CALCULATED': 'The deterministic engine derived this from written dimensions.',
  'HUMAN': 'A named person entered or decided this (self-declared, not verified).',
};
export function ProvChip({ prov }: { prov: Prov }) {
  return <span className={`prov-chip prov-${prov.toLowerCase()}`} title={PROV_HELP[prov]} data-testid={`prov-${prov}`}>{prov}</span>;
}
function SrcBtn({ s }: { s: Src }) {
  const ctx = useContext(ViewCtx);
  const known = !!(ctx && s.doc_id && ctx.docs[s.doc_id]);
  const body = <><FileText size={13} /><span>{s.sheet || s.doc_id || 'Source'}{s.page ? ` · p${s.page}` : ''}</span>{s.excerpt && <small>“{s.excerpt}”</small>}</>;
  return known
    ? <button type="button" className="source-chip clickable" title="Show this evidence in the viewer" onClick={() => ctx!.view({ doc_id: s.doc_id!, page: s.page || 1, excerpt: (s.excerpt || '').split(' — states ')[0] || undefined })}>{body}</button>
    : <div className="source-chip">{body}</div>;
}
function FindingRow({ f }: { f: Finding }) {
  return <li className="finding-row"><ProvChip prov={f.prov} /><div><p>{f.text}</p>{f.note && <p className="tiny subdued">{f.note}</p>}{f.src && f.src.length > 0 && <div className="source-list">{f.src.slice(0, 4).map((s, i) => <SrcBtn s={s} key={i} />)}</div>}</div></li>;
}
const chip = (g: Gate) => g.state === 'corrected' ? <span className="gate-chip ok"><CheckCircle2 size={13} /> CORRECTED</span>
  : g.state === 'resolved' ? <span className="gate-chip ok"><CheckCircle2 size={13} /> RESOLVED</span>
  : g.state === 'info' ? <span className="gate-chip"><Info size={13} /> FOR AWARENESS</span>
  : <span className="gate-chip block"><ShieldAlert size={13} /> BLOCKING</span>;

export function ScopeDiscovery({ project, draft, review, onFocus, addendumSlot }: { project: any; draft: any | null; review: any | null; onFocus: (exceptionId: string) => void; addendumSlot: ReactNode }) {
  const [ai, setAi] = useState<any | null>(null);
  useEffect(() => { let alive = true; fetch('/api/demo/ai-findings', { cache: 'no-store' }).then(r => r.ok ? r.json() : null).then(b => { if (alive) setAi(b && b.available !== false ? b : null); }).catch(() => { if (alive) setAi(null); }); return () => { alive = false; }; }, [project?.scope_version]);
  const gates = useMemo(() => buildScopeGates(project, draft, ai, review), [project, draft, ai, review]);
  const cur = currentGate(gates);
  // No exceptions, no audit and no addenda means no findings have landed yet. That is not the same as every gate being cleared.
  const noFindings = !(project?.exceptions || []).length && !(project?.audit || []).length && !(project?.addenda || []).length;
  const numbered = gates.filter(g => g.id !== 'other' && g.id !== 'assumed');
  const n = cur ? numbered.findIndex(g => g.id === cur.id) + 1 : numbered.length;
  const [openId, setOpenId] = useState<string | null>(null);
  // With nothing blocking, G3's detail stays open by default: its resolution and the original exception (kept as history) are what a reviewer checks first.
  const shown = gates.find(g => g.id === openId) || cur || gates.find(g => g.id === 'g3') || null;
  const showAddendum = (shown?.id === 'g3') || (project?.addenda || []).length > 0;
  if (noFindings) return <section className="card discovery" data-testid="scope-discovery" aria-label="Scope discovery" data-empty="true"><p className="section-label">SCOPE DISCOVERY · WHAT WAS FOUND</p><h2>No findings yet</h2><p className="muted" data-testid="discovery-empty">Findings appear here as the documents are read. Nothing is cleared, and nothing is pending, until they land.</p></section>;
  return <section className="card discovery" data-testid="scope-discovery" aria-label="Scope discovery">
    <p className="section-label">SCOPE DISCOVERY · WHAT WAS FOUND</p>
    <h2 data-testid="discovery-heading">{cur ? `Now: ${cur.title}` : 'All scope gates cleared'}{cur && <small className="gate-count"> · gate {n} of {numbered.length}</small>}</h2>
    <p className="muted">{cur ? 'Work on one gate at a time. Everything found is listed with where it came from.' : 'Nothing blocks the scope now. Continue to the Labor Gate.'}</p>
    <div className="prov-legend" aria-label="Where a finding came from">{(Object.keys(PROV_HELP) as Prov[]).map(p => <ProvChip key={p} prov={p} />)}</div>
    <ol className="found-list" aria-label="Found so far">
      {gates.map(g => <li key={g.id} className={`found-row${shown?.id === g.id ? ' on' : ''}`} data-testid={`gate-${g.id}`} data-state={g.state}>
        <button type="button" className="found-btn" aria-expanded={shown?.id === g.id} onClick={() => setOpenId(shown?.id === g.id && !cur ? null : g.id)}>
          <span className="found-title">{g.title}</span>{chip(g)}{g.tag && <span className="mini-tag warn" data-testid={`tag-${g.tag}`}>{g.tag}</span>}
          <span className="found-sum">{g.summary}</span>
        </button>
      </li>)}
    </ol>
    {shown && <div className="gate-detail" data-testid="gate-detail" data-gate={shown.id}>
      <h3>{shown.title}{shown.blocking && <span className="gate-chip block"><CircleAlert size={13} /> BLOCKING</span>}{shown.tag && <span className="mini-tag warn">{shown.tag}</span>}</h3>
      <ul className="finding-list">{shown.findings.map((f, i) => <FindingRow f={f} key={i} />)}</ul>
      {shown.exceptionIds.length > 0 && <button type="button" className="btn outlined" data-testid="focus-gate" onClick={() => { onFocus(shown.exceptionIds[0]); window.setTimeout(() => document.querySelector('[data-testid="scope-decision-form"]')?.scrollIntoView({ block: 'start' }), 60); }}>Decide this gate ({shown.exceptionIds.length}) </button>}
      {shown.id === 'g3' && shown.blocking && <p className="tiny subdued">To clear G3: upload Addendum 02 below (it shows Before → After and waits for a named person), or have a named person enter a value with its source as an assumption.</p>}
    </div>}
    {showAddendum && <div className="discovery-addendum">{addendumSlot}</div>}
  </section>;
}

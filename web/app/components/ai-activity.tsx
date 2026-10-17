'use client';
// AI activity: one separate row per AI step, read only from stored records. Absent values print NOT_REPORTED. Nothing is summed or estimated here.
import { useCallback, useEffect, useRef, useState } from 'react';
import { Cpu, LoaderCircle, RefreshCw, X, CircleAlert } from 'lucide-react';
import { StateBadge } from './flight-recorder';

/* eslint-disable @typescript-eslint/no-explicit-any */
export function AiActivity({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [data, setData] = useState<any>(null); const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);
  const load = useCallback(async () => {
    setBusy(true); setErr(null);
    try { const r = await fetch('/api/demo/ai-activity', { cache: 'no-store' }); const b = await r.json(); if (!r.ok) setErr(b?.error || `HTTP ${r.status}`); else setData(b); }
    catch { setErr('The AI activity could not be loaded.'); }
    setBusy(false);
  }, []);
  useEffect(() => { if (open) { void load(); window.setTimeout(() => closeRef.current?.focus(), 0); } }, [open, load]);
  useEffect(() => { if (!open) return; const h = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); onClose(); } }; window.addEventListener('keydown', h, true); return () => window.removeEventListener('keydown', h, true); }, [open, onClose]);
  if (!open) return null;
  const tok = (r: any) => (r.tokens_in === 'no AI call' ? 'no AI call' : r.tokens_in === 'NOT_REPORTED' && r.tokens_out === 'NOT_REPORTED' ? 'NOT_REPORTED' : /^reported on/.test(r.tokens_in) ? r.tokens_in : `${r.tokens_in} in${r.tokens_cached !== 'NOT_REPORTED' ? ` (${r.tokens_cached} cached)` : ''} / ${r.tokens_out} out`);
  return <>
    <div className="fr-backdrop" onClick={onClose} />
    <aside className="fr-drawer" role="dialog" aria-modal="false" aria-label="AI activity" data-testid="ai-activity">
      <div className="fr-bar"><div><p className="section-label">AI ACTIVITY</p><h3><Cpu size={17} /> What the AI did</h3></div>
        <div className="fr-bar-actions"><button className="icon-button" type="button" onClick={() => void load()} aria-label="Refresh AI activity" disabled={busy}>{busy ? <LoaderCircle size={16} className="spin" /> : <RefreshCw size={16} />}</button>
          <button ref={closeRef} className="icon-button" type="button" onClick={onClose} aria-label="Close AI activity"><X size={17} /></button></div></div>
      {err && <div className="guardrail" role="alert"><CircleAlert size={18} /><span>{err}</span></div>}
      {!data && !err && <p className="muted">Loading…</p>}
      {data && <>
        <p className="tiny subdued" data-testid="aa-notice">{data.notice}</p>
        {data.rows.map((r: any) => <section key={r.id} className="aa-row" data-testid={`aa-${r.id}`}>
          <div className="aa-head"><strong>{r.step}</strong><StateBadge state={r.mode} /></div>
          <p className="tiny subdued">{r.mode_note}</p>
          <dl className="aa-dl">
            <dt>Model</dt><dd data-testid="aa-model">{r.model}</dd>
            <dt>Serving path</dt><dd>{r.path}</dd>
            <dt>Time</dt><dd>{r.time}</dd>
            <dt>Tokens</dt><dd data-testid="aa-tokens">{tok(r)}</dd>
            <dt>Latency</dt><dd data-testid="aa-latency">{r.latency}</dd>
            <dt>Cost</dt><dd>{r.cost}</dd>
          </dl>
          {r.measurements.length > 0 && <ul className="aa-meas">{r.measurements.map((m: any, i: number) => <li key={i}><span>{m.label}</span><strong>{m.value}</strong></li>)}</ul>}
          {r.notes.map((n: string, i: number) => <p key={i} className="tiny subdued">{n}</p>)}
          {r.attempts && <details data-testid="aa-attempts"><summary className="tiny">All {r.attempts.length} stored attempts, with outcome</summary>
            <div className="table-scroll"><table className="data-table aa-table"><thead><tr><th>Attempt</th><th>Model</th><th>Outcome</th><th>Tokens in/out (cached)</th><th>Call time</th><th>Cost</th></tr></thead><tbody>
              {r.attempts.map((a: any) => <tr key={a.attempt_id}><td>{a.attempt_id}</td><td>{a.model}</td><td><span className={`mini-tag ${a.state === 'CANDIDATES_AVAILABLE' ? 'ok' : 'warn'}`}>{a.state.replace(/_/g, ' ')}</span></td>
                <td>{a.tokens_in === 'NOT_REPORTED' && a.tokens_out === 'NOT_REPORTED' ? 'NOT_REPORTED' : `${a.tokens_in} / ${a.tokens_out}${a.tokens_cached !== 'NOT_REPORTED' ? ` (${a.tokens_cached})` : ''}`}</td><td>{a.latency}<small className="tiny subdued"> {a.latency_basis !== 'NOT_REPORTED' ? a.latency_basis : ''}</small></td><td>{a.cost}</td></tr>)}
            </tbody></table></div></details>}
        </section>)}
        <p className="aa-footer" data-testid="aa-footer">{data.footer}</p>
      </>}
    </aside>
  </>;
}

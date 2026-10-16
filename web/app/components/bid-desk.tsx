'use client';
// Gatehouse Bid Desk: an advisory chat. It shows the current GATE STATE and a mode label. It is not an audit record and it never approves anything.
// "Open source" buttons appear only for evidence the engine or the registered scope draft supplied with the answer.
import { useContext, useEffect, useRef, useState } from 'react';
import { MessageSquare, Send, X } from 'lucide-react';
import { ViewCtx } from './dp001';

/* eslint-disable @typescript-eslint/no-explicit-any */
type Msg = { who: 'you' | 'desk'; text: string; sources?: any[] };
const SUGGEST = ['What blocks me?', 'What about G3?', 'Why is G2 corrected?', 'Which crew can I pick?'];

export function BidDesk({ open, onClose, refreshKey }: { open: boolean; onClose: () => void; refreshKey: string }) {
  const ctx = useContext(ViewCtx);
  const [gs, setGs] = useState<any>(null);
  const [mode, setMode] = useState<{ mode: string; live: { enabled: boolean; reason: string } } | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { if (!open) return; let alive = true;
    fetch('/api/demo/bid-desk', { cache: 'no-store' }).then(r => r.ok ? r.json() : Promise.reject()).then(b => { if (alive) { setGs(b.gate_state); setMode({ mode: b.mode, live: b.live }); } }).catch(() => { if (alive) setGs(null); });
    return () => { alive = false; }; }, [open, refreshKey]);
  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest' }); }, [msgs]);
  async function ask(q: string) {
    const t = q.trim(); if (!t || busy) return;
    setBusy(true); setErr(''); setMsgs(m => [...m, { who: 'you', text: t }]); setText('');
    try {
      const r = await fetch('/api/demo/bid-desk', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: t }) });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) { setErr(b.error || `The Bid Desk is unavailable (HTTP ${r.status}).`); return; }
      setGs(b.gate_state); setMode({ mode: b.mode, live: b.live });
      setMsgs(m => [...m, { who: 'desk', text: b.answer, sources: b.sources }]);
    } catch { setErr('The Bid Desk could not be reached.'); } finally { setBusy(false); }
  }
  if (!open) return null;
  return <aside className="bid-desk" role="complementary" aria-label="Gatehouse Bid Desk" data-testid="bid-desk">
    <div className="bd-head"><strong><MessageSquare size={15} /> Gatehouse Bid Desk</strong><button type="button" className="btn ghost" aria-label="Close Bid Desk" onClick={onClose}><X size={14} /></button></div>
    <div className="bd-state" data-testid="bd-state" aria-live="polite">
      <small>GATE STATE</small>
      {gs ? <ul>
        <li><b>{gs.stage}</b> · scope v{gs.scope_version ?? '—'} · {gs.blocking} blocking</li>
        <li>G3: {gs.g3}</li><li>Addendum: {gs.addendum}</li><li>Crew: {gs.crew}</li><li>Total: {gs.total}</li>
      </ul> : <p className="tiny subdued">Gate state unavailable.</p>}
    </div>
    <p className="bd-mode" data-testid="bd-mode"><span className="mini-tag warn">{mode?.mode ?? 'MODE UNKNOWN'}</span> Answers come from the engine's current state. {mode ? mode.live.reason : ''}</p>
    <p className="tiny subdued bd-note" data-testid="bd-note">Advisory only. This chat is not an audit record and it never approves, accepts or releases anything.</p>
    <div className="bd-log" role="log" aria-live="polite">
      {!msgs.length && <p className="tiny subdued">Ask about the current gate.</p>}
      {msgs.map((m, i) => <div key={i} className={`bd-msg ${m.who}`}><p>{m.text}</p>
        {m.sources && m.sources.length > 0 && <div className="bd-sources">{m.sources.map((s: any, j: number) => ctx && s.doc_id && ctx.docs[s.doc_id]
          ? <button key={j} type="button" className="btn outlined bd-open" data-testid="bd-open-source" onClick={() => ctx.view({ doc_id: s.doc_id, page: s.page || 1, excerpt: (s.excerpt || '').split(' — states ')[0] || undefined })}>Open source · {s.sheet || s.doc_id}{s.page ? ` p${s.page}` : ''}</button> : null)}</div>}
      </div>)}
      <div ref={end} />
    </div>
    {err && <p className="tiny warning-text" role="alert">{err}</p>}
    <div className="bd-suggest">{SUGGEST.map(s => <button key={s} type="button" className="chip" disabled={busy} onClick={() => void ask(s)}>{s}</button>)}</div>
    <form className="bd-form" onSubmit={e => { e.preventDefault(); void ask(text); }}>
      <input aria-label="Ask the Bid Desk" maxLength={400} value={text} onChange={e => setText(e.target.value)} placeholder="Ask about this gate…" />
      <button className="btn primary" type="submit" disabled={busy || !text.trim()} aria-label="Send"><Send size={14} /></button>
    </form>
  </aside>;
}

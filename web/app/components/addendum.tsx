'use client';
import { useEffect, useRef, useState } from 'react';
import { ArrowRight, FileUp, LockKeyhole } from 'lucide-react';

// Binds to the ANVIL 2 contract (BID_CONTRACT.md): the engine's `addenda` records. Nothing here decides anything about a document.
type Inherited = { gate?: string; inherited_from?: string; source_status?: string; source_value?: unknown; source_evidence?: { doc_id?: string; page?: number; excerpt?: string }[] | { doc_id?: string; page?: number; excerpt?: string } };
type Change = { path: string; before: unknown; before_status: string | null; after: unknown; supersedes_established_fact?: boolean; cited_page: number; cited_excerpt: string; inherited_from?: Inherited | null };
type Intake = { intake_id: string; status: string; filename: string; size: number; page_count: number; source: { sha256: string; doc_revision: number }; ingested_by: string; received_utc: string;
  parse: { parser: string; model: string; elapsed_ms: unknown; result: string; mode?: string; recorded_from?: string; usage?: unknown } | null; rejected: { path: string; page: number; reason: string; code?: string }[]; blocked?: { path?: string; reason?: string; field?: string }[] | null; before_after: Change[] | null; message: string | null; accepted_by?: string; applied_scope_version?: number; declined_by?: string };

const STATUS: Record<string, string> = {
  PROCESSING: 'The engine is reading the document…', PROPOSED: 'Verified by the engine. Waiting for a named person to accept.', APPLIED: 'Accepted. The scope was revised.',
  HELD_UNVERIFIED_EVIDENCE: 'Held. A cited line is not on the cited page. Nothing changed.', HELD_NO_CHANGE: 'Held. It changes nothing in the scope.',
  HELD_CONTRADICTORY: 'Held. The document contradicts itself or the record. Nothing changed.', HELD_PARSE_UNAVAILABLE: 'Held: parse unavailable. This hosted demo has no recorded parse for this file, so nothing was proposed and the scope is unchanged.',
  DECLINED: 'Declined. Nothing changed.', HELD_REFUSED: 'Held. The engine refused it. Nothing changed.', HELD_NO_FACTS: 'Held. No facts were found. Nothing changed.',
};
const REFUSAL: Record<string, string> = {
  ACTOR_REQUIRED: 'Enter your name first.', TOO_LARGE: 'That PDF is too large (limit 5 MB).', INVALID_PDF: 'That file is not a readable PDF.', EMPTY: 'The file is empty.',
};
const LABEL: Record<string, string> = {
  '/gates/2/clear_width_ft': 'G3 clear opening width', '/footing_scope/classes/GATE_G3/post_od_in': 'G3 gate-post outside diameter',
  '/footing_scope/classes/GATE_G3/diameter_in': 'G3 footing diameter', '/footing_scope/classes/GATE_G3/depth_in': 'G3 footing depth',
};
const show = (v: unknown) => (v === null || v === undefined ? 'unresolved' : String(v));

export function AddendumPanel({ project, onRefresh }: { project: any; onRefresh: () => void }) { // eslint-disable-line @typescript-eslint/no-explicit-any
  const items: Intake[] = (project?.addenda || []).slice().reverse();
  const [file, setFile] = useState<File | null>(null);
  const [by, setBy] = useState('');
  const [label, setLabel] = useState('');
  const [itemRef, setItemRef] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [notes, setNotes] = useState<Record<string, string>>({});
  const input = useRef<HTMLInputElement>(null);
  // The engine reads the document in the background (202 PROCESSING). Poll the project state until no record is still processing.
  const working = items.some(i => i.status === 'PROCESSING');
  useEffect(() => { if (!working) return; const t = window.setInterval(onRefresh, 2000); return () => window.clearInterval(t); }, [working, onRefresh]);

  async function upload() {
    if (!file || !by.trim()) return;
    setBusy(true); setMsg('Uploading…');
    const f = new FormData(); f.append('file', file); f.append('by', by.trim());
    try {
      const r = await fetch('/api/demo/addendum/upload', { method: 'POST', body: f });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) setMsg(REFUSAL[b.code] || b.error || `Upload refused (HTTP ${r.status}). Nothing was recorded.`);
      else setMsg(`Recorded. SHA-256 ${String(b.intake?.source?.sha256 || '').slice(0, 12)}…. ${b.intake?.status === 'PROCESSING' ? 'The engine is reading it; this page updates when it finishes.' : 'Result: ' + String(b.intake?.status || 'unknown').replace(/_/g, ' ') + '.'} An identical file uploaded again shows this same record.`);
      setFile(null); if (input.current) input.current.value = '';
    } catch { setMsg('The upload could not be completed. Check the list below; nothing is accepted without a person.'); }
    finally { setBusy(false); onRefresh(); }
  }

  async function accept(it: Intake) {
    const note = (notes[it.intake_id] || '').trim();
    if (!by.trim() || !note) return;
    setBusy(true); setMsg('');
    try {
      const r = await fetch('/api/demo/addendum/accept', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ intake_id: it.intake_id, by: by.trim(), note, scope_version: project.scope_version, proposal_digest: project.proposal_digest ?? null, ...(label.trim() ? { addendum_label: label.trim() } : {}), ...(itemRef.trim() ? { addendum_item_reference: itemRef.trim() } : {}) }) });
      const b = await r.json().catch(() => ({}));
      setMsg(r.ok ? 'Recorded by the engine. The scope is revised; labor and release must be redone.' : (b.error || `Refused (HTTP ${r.status}).`));
    } catch { setMsg('The decision could not be sent. Nothing was recorded.'); }
    finally { setBusy(false); onRefresh(); }
  }

  async function decline(it: Intake) {
    const note = (notes[it.intake_id] || '').trim();
    if (!by.trim() || !note) return;
    setBusy(true); setMsg('');
    try {
      const r = await fetch('/api/demo/addendum/decline', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ intake_id: it.intake_id, by: by.trim(), note }) });
      const b = await r.json().catch(() => ({}));
      setMsg(r.ok ? 'Declined. Nothing changed in the scope.' : (b.error || `Refused (HTTP ${r.status}).`));
    } catch { setMsg('The decision could not be sent. Nothing was recorded.'); }
    finally { setBusy(false); onRefresh(); }
  }

  return <div className="addendum-panel" data-testid="addendum-panel">
    <p className="section-label">ATTACH ADDENDUM</p>
    <p className="tiny subdued">Upload a later addendum PDF. The engine records it as its own revision with its SHA-256, reads it, and checks that every cited line is really on the cited page. Nothing changes until a named person accepts the Before → After.</p>
    <div className="input-stack">
      <label>Your name (self-declared, not verified)</label>
      <input aria-label="Addendum uploader name" value={by} onChange={e => setBy(e.target.value)} placeholder="Your name" />
      <p className="tiny subdued" data-testid="addendum-demo-note">Hosted demo replays a recorded capture of a live AMD parse; other files are held as parse unavailable. <a href="/api/demo/sample-addendum" download="ADDENDUM_02.pdf" data-testid="addendum-sample">Download the sample Addendum 02 (PDF)</a>.</p>
      <label>Addendum PDF (up to 5 MB)</label>
      <input ref={input} type="file" accept="application/pdf,.pdf" data-testid="addendum-file" onChange={e => setFile(e.target.files?.[0] || null)} />
      <button className="btn outlined full" type="button" data-testid="addendum-upload" disabled={busy || !file || !by.trim()} onClick={() => { void upload(); }}>{busy ? 'Working…' : 'Upload addendum'} <FileUp size={15} /></button>
    </div>
    {msg && <p className="tiny" role="status" data-testid="addendum-msg">{msg}</p>}
    {items.map(it => <div key={it.intake_id} className="card mini-card" data-testid={`addendum-${it.status}`} style={{ marginTop: 10 }}>
      <strong>{it.filename}</strong>
      <p className="tiny subdued">SHA-256 {it.source.sha256.slice(0, 12)}… · revision {it.source.doc_revision} · {it.page_count} page{it.page_count === 1 ? '' : 's'} · uploaded by {it.ingested_by}</p>
      <p><span className={`mini-tag ${it.status === 'PROPOSED' || it.status === 'APPLIED' || it.status === 'PROCESSING' ? '' : 'warn'}`}>{it.status.replace(/_/g, ' ')}</span> {STATUS[it.status] || ''}</p>
      {it.message && <p className="tiny warning-text" data-testid="addendum-error">{it.message}</p>}
      {it.status === 'HELD_PARSE_UNAVAILABLE' && <p className="tiny" data-testid="addendum-held-note">Nothing proposed. Scope unchanged. Fallback: type the value at the Takeoff Review with the source “Addendum 02, page N”. It is recorded as entered by your name, citing Addendum 02.</p>}
      {it.parse && <p className="tiny subdued" data-testid="addendum-parse-mode"><strong>{it.parse.mode === 'RECORDED' ? 'RECORDED replay (no new model call)' : it.parse.mode === 'LIVE' ? 'LIVE model call' : 'Parse mode not reported'}</strong>{it.parse.recorded_from ? ` of ${it.parse.recorded_from}` : ''}. Parser: {it.parse.parser}; model {it.parse.model === 'NOT_REPORTED' ? 'not reported' : it.parse.model}; time {it.parse.elapsed_ms === 'NOT_REPORTED' || it.parse.elapsed_ms == null ? 'not reported' : `${it.parse.elapsed_ms} ms`}; result {it.parse.result}. The parser only proposes; the engine verified the quotes below.</p>}
      {it.before_after && it.before_after.length > 0 && <div aria-label="Addendum before and after" role="list" data-testid="addendum-beforeafter">
        {it.before_after.map(c => <div key={c.path} role="listitem" data-testid="addendum-row" style={{ borderTop: '1px solid #e2e8e9', padding: '10px 0' }}>
          <strong>{LABEL[c.path] || c.path}</strong><br /><small className="subdued">{c.path}</small>
          <p style={{ margin: '6px 0 2px' }}>Before: <strong>{show(c.before)}</strong> <small className="subdued">({c.before_status || 'no status'}{c.supersedes_established_fact ? '; this replaces an established value' : ''})</small></p>
          <p style={{ margin: '2px 0' }}>After: <strong>{show(c.after)}</strong>{c.inherited_from && <small data-testid="addendum-inherited"> · inherited from {c.inherited_from.gate || 'Gate G1'}{c.inherited_from.inherited_from ? ` (${c.inherited_from.inherited_from})` : ''}, {c.inherited_from.source_status || 'confirmed'}</small>}</p>
          <p className="tiny" style={{ margin: '2px 0' }}>Cited: {it.filename}, page {c.cited_page} — “{c.cited_excerpt}”</p>
        </div>)}
      </div>}
      {it.rejected?.length > 0 && <details><summary className="tiny">{it.rejected.length} proposed fact{it.rejected.length === 1 ? '' : 's'} refused by the engine</summary>{it.rejected.map((x, i) => <p key={i} className="tiny"><strong>{x.code ? x.code + ' ' : ''}{x.path}</strong> page {x.page}: {x.reason}</p>)}</details>}
      {Array.isArray(it.blocked) && it.blocked.length > 0 && <p className="tiny warning-text" data-testid="addendum-blocked">Still blocked (not document-confirmed): {it.blocked.map(b => b.path || b.field || JSON.stringify(b)).join('; ')}</p>}
      {it.status === 'APPLIED' && <p className="tiny subdued">Accepted by {it.accepted_by} (self-declared); scope version {it.applied_scope_version}.</p>}
      {it.status === 'PROPOSED' && <div className="input-stack">
        <label>Addendum label (optional; type it exactly as you want it printed, e.g. the number on the document)</label>
        <input aria-label="Addendum label" data-testid="addendum-label" maxLength={60} value={label} onChange={e => setLabel(e.target.value)} placeholder="Not inferred from the file name" />
        <label>Addendum item (optional; type the item or paragraph number you checked, e.g. Item 2.1)</label>
        <input aria-label="Addendum item" data-testid="addendum-item" maxLength={60} value={itemRef} onChange={e => setItemRef(e.target.value)} placeholder="Blank prints: not stated; cited by page and quote" />
        <label>Decision note (what did you check?)</label>
        <textarea aria-label="Addendum decision note" data-testid="addendum-note" rows={2} value={notes[it.intake_id] || ''} onChange={e => setNotes({ ...notes, [it.intake_id]: e.target.value })} />
        <p className="tiny subdued"><LockKeyhole size={12} /> Accepting revises the scope, voids the labor decision and any release eligibility, and keeps the old version in history. It uses the name entered above.</p>
        <button className="btn primary full" type="button" data-testid="addendum-accept" disabled={busy || !by.trim() || !(notes[it.intake_id] || '').trim()} onClick={() => { void accept(it); }}>Accept this change <ArrowRight size={15} /></button>
        <button className="btn outlined full" type="button" data-testid="addendum-decline" disabled={busy || !by.trim() || !(notes[it.intake_id] || '').trim()} onClick={() => { void decline(it); }}>Decline</button>
      </div>}
    </div>)}
  </div>;
}

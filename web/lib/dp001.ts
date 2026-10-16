// Server-only access to the DP-001 document registry, the PDFs and the human-prepared scope draft.
// Identities come from the existing experiment manifest (projected into document_registry.json by dp001/build.py); every file is
// hash-checked against that identity before it is listed as verified or served.
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

const dir = () => process.env.DP001_DIR || '';
// PDFs are reviewed public synthetic assets under samples/public-demo/dp001 (sibling of the DP001_DIR parent), unless overridden.
const docsDir = () => process.env.DP001_DOCUMENTS_DIR || path.join(dir(), '..', 'samples', 'public-demo', 'dp001');
type Doc = { doc_id: string; filename: string; sha256: string; [k: string]: unknown };
type Registry = { documents: Doc[]; sheets: unknown[]; [k: string]: unknown };
const verified = new Map<string, boolean>();

async function registry(): Promise<Registry | null> {
  if (!dir()) return null;
  try { return JSON.parse(await readFile(path.join(dir(), 'document_registry.json'), 'utf8')); } catch { return null; }
}

async function check(d: Doc): Promise<{ ok: boolean; bytes?: Buffer }> {
  try {
    const bytes = await readFile(path.join(docsDir(), path.basename(d.filename)));
    const ok = createHash('sha256').update(bytes).digest('hex') === d.sha256;
    verified.set(d.doc_id, ok);
    return { ok, bytes };
  } catch { verified.set(d.doc_id, false); return { ok: false }; }
}

export async function listDocuments() {
  const r = await registry();
  if (!r) return null;
  const docs = await Promise.all(r.documents.map(async d => ({ ...d, hash_verified: verified.get(d.doc_id) ?? (await check(d)).ok })));
  return { ...r, documents: docs };
}

export async function documentBytes(id: string) {
  const r = await registry();
  const d = r?.documents.find(x => x.doc_id === id);
  if (!d) return null;
  const c = await check(d);
  return c.ok && c.bytes ? { bytes: c.bytes, doc: d } : { bytes: null, doc: d };
}

export async function scopeDraft() {
  if (!dir()) return null;
  try { return JSON.parse(await readFile(path.join(dir(), 'scope_draft.json'), 'utf8')); } catch { return null; }
}

// The downloadable sample Addendum 02: served only when its bytes match this pinned SHA-256 (the hosted demo's recorded capture is for exactly this file).
const SAMPLE_ADDENDUM_SHA256 = 'f0b0571c9696517676320d5b7dcf02cbff214149b0db9f6147913ff15ed00aef';
export async function sampleAddendum(): Promise<Buffer | null> {
  try {
    const bytes = await readFile(path.join(docsDir(), 'ADDENDUM_02.pdf'));
    return createHash('sha256').update(bytes).digest('hex') === SAMPLE_ADDENDUM_SHA256 ? bytes : null;
  } catch { return null; }
}

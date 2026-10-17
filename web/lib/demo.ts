// Session-bound demo operations. The ONLY project a request can touch is the one in the visitor's signed cookie;
// URLs and bodies never carry a project id.
import { NextRequest, NextResponse } from 'next/server';
import { COOKIE, SESSION_SECONDS, Session, cookieOptions, decode, encode, newSid, ownerFor } from './session';
import { engine } from './engine';
import { allow, clientIp, ipRequestsPerMinute, ipMutationsPer10Min, newDemosGlobalPerHour, logIpShape } from './limits';
import { buildReview, isDp001, storeFor, canonical, sha, type Attestation } from './takeoff-service';
import { buildFindingsView, previewFor, loadLedger, aiStoreFor, type Decision } from './ai-findings';
import { loadCases, loadRegistryDocs } from './evolus-cases';
import { attachAudits } from './evolus-audit';
import { RELEASE_AUDIT_MANIFEST } from './audit-manifest';
import { loadEvidence, validationLayer, humanLayer } from './flight-recorder';
import { buildExport, toCsv, ExportRefused } from './export';
import { answer as deskAnswer, gateStateOf, DESK_MAX_CHARS, liveReason } from './bid-desk';
import { scopeDraft } from './dp001';
import { buildAiActivity, evolusStatement } from './ai-activity.ts';
import { fromEngine } from './adapt';

const json = (body: unknown, status = 200) => NextResponse.json(body, { status, headers: { 'Cache-Control': 'no-store' } });

/** Replay/throttle headers the adapter contract defines; forwarded to the browser so a historical replay is never shown as a new decision. */
const hdrs = (h?: Record<string, string>) => ({ 'Cache-Control': 'no-store', ...(h || {}) });
const reply = (r: { status: number; body: any; headers?: Record<string, string> }) => NextResponse.json(clean_adapter(r.body), { status: r.status, headers: hdrs(r.headers) }); // eslint-disable-line @typescript-eslint/no-explicit-any

/** The adapter block carries wage-history content hashes and authorization markers. They stay in the engine; the browser gets counts and status only. */
export function clean_adapter(body: any): any { // eslint-disable-line @typescript-eslint/no-explicit-any
  if (!body || typeof body !== 'object') return body;
  const strip = (o: any) => { // eslint-disable-line @typescript-eslint/no-explicit-any
    if (!o || typeof o !== 'object' || !o.adapter) return o;
    const a = o.adapter, wh = a.wage_history;
    return { ...o, adapter: { contract: a.contract, actor_identity: a.actor_identity, decision_count: Array.isArray(a.decisions) ? a.decisions.length : 0,
      wage_history: wh ? { history_complete: !!wh.history_complete, incomplete_reason: wh.incomplete_reason ?? null, record_count: Array.isArray(wh.records) ? wh.records.length : 0 } : null } };
  };
  return body.project ? { ...body, project: strip(body.project) } : strip(body);
}

function originOk(req: NextRequest): boolean {
  const o = req.headers.get('origin');
  if (!o) return true; // same-origin navigations and non-browser clients send none; SameSite=Lax covers the rest
  try { return new URL(o).host === req.headers.get('host'); } catch { return false; }
}

function gate(req: NextRequest, sess: Session | null, mutating: boolean): NextResponse | null {
  const ip = clientIp(req.headers);
  if (!allow(`ip:${ip}`, ipRequestsPerMinute(), 60_000)) return json({ error: 'Too many requests. Slow down.' }, 429);
  if (mutating) {
    if (!originOk(req)) return json({ error: 'Cross-origin request refused' }, 403);
    if (!allow(`ipm:${ip}`, ipMutationsPer10Min(), 10 * 60_000)) return json({ error: 'Too many actions from this network. Try again later.' }, 429);
    if (sess && !allow(`sess:${sess.sid}`, 60, 10 * 60_000)) return json({ error: 'Too many actions in this demo session.' }, 429);
  }
  return null;
}

async function createProject(req: NextRequest, prior: Session | null): Promise<{ sess: Session; summary: any } | NextResponse> { // eslint-disable-line @typescript-eslint/no-explicit-any
  const ip = clientIp(req.headers);
  // NEW_DEMOS_PER_HOUR (default 12, clamped 1..500) lets an owner raise the per-network limit for a venue where many judges share one public IP.
  const perHour = Math.min(500, Math.max(1, Number.parseInt(process.env.NEW_DEMOS_PER_HOUR || '12', 10) || 12));
  if (!allow(`new:${ip}`, perHour, 60 * 60_000)) return json({ error: 'Too many new demos from this network. Try again later.' }, 429);
  logIpShape(req.headers);
  // Global ceiling, independent of attribution: if client-IP buckets ever fail to share state, new sessions are still bounded so the engine's project cap cannot be exhausted by one source.
  if (!allow('new:global', newDemosGlobalPerHour(), 60 * 60_000)) return json({ error: 'The demo is receiving many new visitors. Please try again in a few minutes.' }, 429);
  const sid = newSid();
  const r = await engine('POST', 'demo/projects', ownerFor(sid), {});
  if (r.status !== 201) return json({ error: r.body?.error || 'Could not start a demo project' }, r.status === 429 ? 429 : 503);
  if (prior) void engine('DELETE', `demo/projects/${prior.pid}`, ownerFor(prior.sid)); // best effort; the engine also expires idle projects
  return { sess: { sid, pid: r.body.project_id, exp: Math.floor(Date.now() / 1000) + SESSION_SECONDS }, summary: r.body };
}

function withCookie(res: NextResponse, sess: Session): NextResponse {
  res.cookies.set(COOKIE, encode(sess), cookieOptions(sess.exp));
  return res;
}

/** GET: return the visitor's project, creating one on first visit or after expiry. */
export async function state(req: NextRequest) {
  const sess = decode(req.cookies.get(COOKIE)?.value);
  const blocked = gate(req, sess, false);
  if (blocked) return blocked;
  if (sess) {
    const r = await engine('GET', `projects/${sess.pid}`, ownerFor(sess.sid));
    if (r.status === 200) return json({ fresh: false, expires_at: sess.exp, project: clean_adapter(r.body) });
    if (r.status !== 404) return json({ error: r.body?.error || 'Engine unavailable' }, 503);
  }
  const made = await createProject(req, null);
  if (made instanceof NextResponse) return made;
  return withCookie(json({ fresh: true, expired: !!sess, expires_at: made.sess.exp, project: clean_adapter(made.summary) }), made.sess);
}

/** POST: discard the visitor's project and start a fresh fictional one. */
export async function reset(req: NextRequest) {
  const sess = decode(req.cookies.get(COOKIE)?.value);
  const blocked = gate(req, sess, true);
  if (blocked) return blocked;
  const made = await createProject(req, sess);
  if (made instanceof NextResponse) return made;
  return withCookie(json({ fresh: true, expires_at: made.sess.exp, project: clean_adapter(made.summary) }), made.sess);
}

type Field = 'string' | 'number' | 'boolean' | 'strlist' | 'stringOrNumber' | 'payroll' | 'stringOrBool' | 'strmap' | 'json';
const SCHEMAS: Record<string, { path: string; fields: Record<string, Field>; required: string[] }> = {
  scope: { path: 'scope/resolve', required: ['exception_id', 'by', 'note'],
    fields: { exception_id: 'string', option_id: 'string', value: 'stringOrNumber', by: 'string', note: 'string', source_note: 'string' } },
  labor: { path: 'labor/resolve', required: ['by', 'decision', 'applicability_review', 'note', 'certified_payroll'],
    fields: { by: 'string', decision: 'string', certified_payroll: 'payroll', applicability_review: 'string', note: 'string',
              loaded_hourly_rate: 'number', source_refs: 'strlist', classifications: 'strlist', qualification: 'string' } },
  release: { path: 'release', required: ['approver', 'expected_scope_version', 'expected_proposal_digest'],
    fields: { approver: 'string', expected_scope_version: 'number', expected_proposal_digest: 'string', note: 'string', takeoff_digest: 'string', acknowledged_blockers: 'strlist' } },
  ruleset: { path: 'decisions/ruleset-approval', required: ['by', 'note', 'ruleset_sha256'],
    fields: { by: 'string', note: 'string', ruleset_sha256: 'string' } },
  crewplan: { path: 'decisions/crew-plan', required: ['by', 'note', 'use_default_for_unassigned', 'difficulty'],
    fields: { by: 'string', note: 'string', preferred_crew: 'string', assignments: 'strmap', use_default_for_unassigned: 'boolean', difficulty: 'json' } },
  wage: { path: 'decisions/wage-determination', required: ['by', 'note', 'determination', 'schedule', 'rows', 'employer_burden', 'production_rates_approved', 'certified_payroll_admin'],
    fields: { by: 'string', note: 'string', determination: 'json', schedule: 'json', rows: 'json', employer_burden: 'json', production_rates_approved: 'boolean', certified_payroll_admin: 'json' } },
  preview: { path: 'crew-plan/preview', required: ['use_default_for_unassigned', 'difficulty'],
    fields: { preferred_crew: 'string', assignments: 'strmap', use_default_for_unassigned: 'boolean', difficulty: 'json' } },
};

/** Plain JSON only: bounded depth, size and string length. The engine is still the authority on meaning. */
function plainJson(v: unknown, depth = 0): boolean {
  if (depth > 4) return false;
  if (v === null || typeof v === 'boolean') return true;
  if (typeof v === 'number') return Number.isFinite(v);
  if (typeof v === 'string') return v.length <= 500;
  if (Array.isArray(v)) return v.length <= 20 && v.every(x => plainJson(x, depth + 1));
  if (typeof v === 'object') { const e = Object.entries(v as object); return e.length <= 20 && e.every(([k, x]) => k.length <= 60 && plainJson(x, depth + 1)); }
  return false;
}

function clean(kind: string, raw: unknown): Record<string, unknown> | string {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return 'Body must be a JSON object';
  const spec = SCHEMAS[kind], b = raw as Record<string, unknown>, out: Record<string, unknown> = {};
  for (const k of Object.keys(b)) if (!(k in spec.fields)) return `Unknown field: ${k.slice(0, 40)}`;
  for (const [k, t] of Object.entries(spec.fields)) {
    if (!(k in b) || b[k] === undefined) continue;
    const v = b[k];
    const ok = t === 'string' ? typeof v === 'string' && v.length <= 2000
      : t === 'number' ? typeof v === 'number' && Number.isFinite(v)
      : t === 'stringOrNumber' ? (typeof v === 'string' && v.length <= 2000) || (typeof v === 'number' && Number.isFinite(v))
      : t === 'payroll' ? v === true || v === false || v === 'unknown'
      : t === 'boolean' ? typeof v === 'boolean'
      : t === 'json' ? !!v && typeof v === 'object' && plainJson(v)
      : t === 'strmap' ? !!v && typeof v === 'object' && !Array.isArray(v) && Object.entries(v as object).length <= 20 && Object.entries(v as object).every(([k, x]) => k.length <= 60 && typeof x === 'string' && x.length <= 60)
      : t === 'strlist' ? Array.isArray(v) && v.length <= 20 && v.every(x => typeof x === 'string' && x.length <= 500)
      : false;
    if (!ok) return `Invalid value for ${k}`;
    out[k] = v;
  }
  for (const k of spec.required) if (!(k in out)) return `Missing field: ${k}`;
  return out;
}

const DECISION_KINDS = new Set(['ruleset', 'crewplan', 'wage']);
const IDEM_RE = /^[A-Za-z0-9_.:-]{8,128}$/;

/** POST a human decision against the visitor's own project. The engine remains the only authority on whether it is accepted. */
export async function mutate(req: NextRequest, kind: 'scope' | 'labor' | 'release' | 'ruleset' | 'crewplan' | 'wage') {
  const sess = decode(req.cookies.get(COOKIE)?.value);
  const blocked = gate(req, sess, true);
  if (blocked) return blocked;
  if (!sess) return json({ error: 'No demo session. Reload the page to start one.' }, 401);
  const len = Number(req.headers.get('content-length') || 0);
  if (len > 16_384) return json({ error: 'Request too large' }, 413);
  let body: unknown;
  try { body = JSON.parse(await req.text()); } catch { return json({ error: 'Invalid JSON' }, 400); }
  const payload = clean(kind, body);
  if (typeof payload === 'string') return json({ error: payload }, 400);
  if (kind === 'scope') {
    // A typed value for an unresolved Gate G3 fact must say where it came from. The engine records the combined note against the named person; nothing is defaulted or suggested.
    const g3 = /\/gates\/2\/clear_width_ft|GATE_G3/.test(String(payload.exception_id || ''));
    const src = typeof payload.source_note === 'string' ? payload.source_note.trim() : '';
    if (g3 && payload.value !== undefined) {
      if (src.length < 10) return json({ error: 'A G3 value needs a source note (at least 10 characters): where this value came from, such as a document, page and quote, or who supplied it and when.', code: 'G3_SOURCE_NOTE_REQUIRED' }, 400);
      payload.note = `ASSUMED, RFI PENDING. SOURCE: ${src} | ${String(payload.note || '')}`.slice(0, 1990);
    }
    delete payload.source_note;
  }
  if (kind === 'release') {
    // The engine is authoritative for scope/labor/digest AND for bid readiness. For a footing-scope project (DP-001) the proxy additionally
    // requires a CURRENT Takeoff Review (bound to the engine's schedule hashes) and an explicit acknowledgement of every open qualification.
    // A client can never assert readiness: unknown body fields (e.g. bid_ready) are rejected above, and nothing here sets it.
    const pr = await engine('GET', `projects/${sess.pid}`, ownerFor(sess.sid));
    if (pr.status === 200 && isDp001(pr.body)) {
      const rev = await buildReview(pr.body, sess.sid, sess.pid);
      const reject = (code: string, error: string, details?: unknown) => json({ error, code, details }, 409);
      if (rev.release_hard_blockers.length) return reject(rev.release_hard_blockers[0], 'Release is blocked: ' + rev.blockers.filter((b: any) => b.hard).map((b: any) => b.message).join(' ')); // eslint-disable-line @typescript-eslint/no-explicit-any
      const att = rev.attestation;
      if (!att) return reject('TAKEOFF_REVIEW_REQUIRED', 'Record a Takeoff Review for this scope version before release.');
      if (!att.current || payload.takeoff_digest !== rev.digest) return reject('TAKEOFF_REVIEW_STALE', 'The takeoff changed after it was reviewed (or the request names an older takeoff digest). Review the current takeoff again.', { current_digest: rev.digest });
      const ack = new Set((payload.acknowledged_blockers as string[] | undefined) || []);
      const missing = rev.release_ack_required.filter((c: string) => !ack.has(c));
      if (missing.length) return reject('NOT_BID_READY_ACKNOWLEDGEMENT_REQUIRED', 'Acknowledge every open qualification to record a QUALIFIED FICTIONAL DEMONSTRATION release (never a bid): ' + missing.join(', '), { unacknowledged: missing, required: rev.release_ack_required });
      const rc = rev.readiness.selected?.release_class;
      const qual = `QUALIFIED DEMONSTRATION RELEASE — NOT BID READY — FICTIONAL DEMONSTRATION ONLY (self-declared, unauthenticated). Engine release_class ${String(rc)}. Takeoff digest ${rev.digest.slice(0, 16)}. Acknowledged: ${rev.release_ack_required.join(', ')}. Footing counts are provisional; G3 values, if any, are self-declared assumptions.`;
      payload.note = `${String(payload.note || '')}${payload.note ? ' | ' : ''}${qual}`.slice(0, 1990);
    }
    delete payload.takeoff_digest; delete payload.acknowledged_blockers;
  }
  // Decision routes require a client-supplied Idempotency-Key, forwarded unchanged. The proxy never invents or reuses one.
  let extra: Record<string, string> | undefined;
  if (DECISION_KINDS.has(kind)) {
    const key = req.headers.get('idempotency-key') || '';
    if (!IDEM_RE.test(key)) return json({ error: 'A decision needs an Idempotency-Key header (8-128 characters).', code: 'IDEMPOTENCY_KEY_REQUIRED' }, 400);
    extra = { 'Idempotency-Key': key };
  }
  const r = await engine('POST', `projects/${sess.pid}/${SCHEMAS[kind].path}`, ownerFor(sess.sid), payload, extra);
  if (r.status === 404) return json({ error: 'Your demo session expired. Reload the page to start a fresh one.' }, 410);
  if (kind === 'release' && r.status === 200 && r.body && typeof r.body === 'object') { // keep the engine's own readiness fields so they survive a reload
    const b = r.body; storeFor(sess.sid, sess.pid).release = { bid_ready: b.bid_ready, release_class: b.release_class, artifact_kind: b.artifact_kind, footing_release_class: b.footing_release_class, proposal_digest: b.proposal_digest, scope_version: b.scope_version, released_at: b.released_at, audit_id: b.audit_id };
  }
  // Engine rejections (400/409/429) pass through verbatim, with their stable codes and replay headers, so a refused decision is shown as refused.
  return reply(r);
}

export async function health(req: NextRequest) {
  const blocked = gate(req, null, false);
  if (blocked) return blocked;
  const r = await engine('GET', 'health', 'a'.repeat(64));
  return json({ engine: r.status === 200 ? 'responsive' : 'unavailable' });
}

/** GET the static, read-only synthetic portfolio. Same for every visitor; derived entirely by the engine. */
export async function portfolio(req: NextRequest) {
  const sess = decode(req.cookies.get(COOKIE)?.value);
  const blocked = gate(req, sess, false);
  if (blocked) return blocked;
  const r = await engine('GET', 'demo/portfolio', 'a'.repeat(64));
  if (r.status !== 200) return json({ error: 'Portfolio unavailable' }, 503);
  return json(r.body);
}

/** POST a DRAFT crew plan for a what-if recalculation by the engine. Changes nothing, records nothing, approves nothing. */
export async function preview(req: NextRequest) {
  const sess = decode(req.cookies.get(COOKIE)?.value);
  const ip = clientIp(req.headers);
  if (!allow(`ip:${ip}`, 300, 60_000)) return json({ error: 'Too many requests. Slow down.' }, 429);
  if (!originOk(req)) return json({ error: 'Cross-origin request refused' }, 403);
  if (!sess) return json({ error: 'No demo session. Reload the page to start one.' }, 401);
  if (!allow(`prev:${sess.sid}`, 600, 10 * 60_000)) return json({ error: 'Too many recalculations in this demo session.' }, 429);
  const len = Number(req.headers.get('content-length') || 0);
  if (len > 16_384) return json({ error: 'Request too large' }, 413);
  let body: unknown;
  try { body = JSON.parse(await req.text()); } catch { return json({ error: 'Invalid JSON' }, 400); }
  const payload = clean('preview', body);
  if (typeof payload === 'string') return json({ error: payload }, 400);
  const r = await engine('POST', `projects/${sess.pid}/crew-plan/preview`, ownerFor(sess.sid), payload);
  if (r.status === 404) return json({ error: 'Your demo session expired. Reload the page to start a fresh one.' }, 410);
  return reply(r);
}


/** GET: the Takeoff Review for the visitor's own project (engine footing schedule + independent cross-check). */
export async function takeoff(req: NextRequest) {
  const sess = decode(req.cookies.get(COOKIE)?.value);
  const blocked = gate(req, sess, false);
  if (blocked) return blocked;
  if (!sess) return json({ error: 'No demo session. Reload the page to start one.' }, 401);
  const r = await engine('GET', `projects/${sess.pid}`, ownerFor(sess.sid));
  if (r.status === 404) return json({ error: 'Your demo session expired. Reload the page to start a fresh one.' }, 410);
  if (r.status !== 200) return json({ error: r.body?.error || 'Engine unavailable' }, 503);
  try { return json(await buildReview(r.body, sess.sid, sess.pid)); }
  catch (e) { return json({ error: e instanceof Error ? e.message : 'Takeoff could not be computed', code: 'TAKEOFF_REFUSED' }, 400); }
}

/** POST (Idempotency-Key required): a named, self-declared review of the CURRENT takeoff, bound to scope version + takeoff digest. */
export async function takeoffReview(req: NextRequest) {
  const sess = decode(req.cookies.get(COOKIE)?.value);
  const blocked = gate(req, sess, true);
  if (blocked) return blocked;
  if (!sess) return json({ error: 'No demo session. Reload the page to start one.' }, 401);
  const key = req.headers.get('idempotency-key') || '';
  if (!IDEM_RE.test(key)) return json({ error: 'A decision needs an Idempotency-Key header (8-128 characters).', code: 'IDEMPOTENCY_KEY_REQUIRED' }, 400);
  const len = Number(req.headers.get('content-length') || 0);
  if (len > 4096) return json({ error: 'Request too large' }, 413);
  let body: any; try { body = JSON.parse(await req.text()); } catch { return json({ error: 'Invalid JSON' }, 400); } // eslint-disable-line @typescript-eslint/no-explicit-any
  if (!body || typeof body !== 'object' || Array.isArray(body) || Object.keys(body).some(k => !['by', 'note', 'takeoff_digest'].includes(k))) return json({ error: 'Body must be {by, note, takeoff_digest}' }, 400);
  for (const k of ['by', 'note', 'takeoff_digest']) if (typeof body[k] !== 'string' || !body[k].trim() || body[k].length > 500) return json({ error: `Missing or invalid field: ${k}` }, 400);
  const st = storeFor(sess.sid, sess.pid);
  const hash = sha(canonical({ by: body.by.trim(), note: body.note.trim(), d: body.takeoff_digest }));
  const prior = st.ledger.get(key);
  if (prior) {
    if (prior.hash !== hash) return json({ error: 'This Idempotency-Key was already used for a different decision or payload', code: 'IDEMPOTENCY_KEY_REUSED' }, 409);
    return NextResponse.json(prior.response, { status: prior.status, headers: { 'Cache-Control': 'no-store', 'Idempotent-Replay': 'true', 'X-Idempotency-Result': 'historical' } });
  }
  const r = await engine('GET', `projects/${sess.pid}`, ownerFor(sess.sid));
  if (r.status === 404) return json({ error: 'Your demo session expired. Reload the page to start a fresh one.' }, 410);
  if (r.status !== 200 || !isDp001(r.body)) return json({ error: 'There is no DP-001 takeoff to review yet. Resolve the Scope gate first.', code: 'TAKEOFF_NOT_AVAILABLE' }, 409);
  const rev = await buildReview(r.body, sess.sid, sess.pid);
  if (rev.release_hard_blockers.length) return json({ error: 'The takeoff cannot be reviewed while G3 is unresolved.', code: rev.release_hard_blockers[0] }, 409);
  if (body.takeoff_digest !== rev.digest) return json({ error: 'The takeoff changed since you opened it. Review the current takeoff.', code: 'TAKEOFF_REVIEW_STALE', details: { current_digest: rev.digest } }, 409);
  const rec: Attestation = { by: body.by.trim(), note: body.note.trim(), at: new Date().toISOString(), scope_version: rev.scope_version, digest: rev.digest, idempotency_key: key, scenario: rev.selected };
  st.attestation = rec;
  const response = { recorded: true, actor_identity: 'SELF_DECLARED_DEMO_ACTOR_NOT_AUTHENTICATED', attestation: rec, status: 'Takeoff reviewed for this scope version; geometry remains PROVISIONAL. Not a contractor approval.' };
  st.ledger.set(key, { hash, response, status: 200 });
  return json(response);
}


/** GET: AI Findings (offline-captured AMD candidates) beside the visitor's own engine project. Read-only; makes no AMD call. */
export async function aiFindings(req: NextRequest) {
  const sess = decode(req.cookies.get(COOKIE)?.value);
  const blocked = gate(req, sess, false);
  if (blocked) return blocked;
  if (!sess) return json({ error: 'No demo session. Reload the page to start one.' }, 401);
  const r = await engine('GET', `projects/${sess.pid}`, ownerFor(sess.sid));
  if (r.status === 404) return json({ error: 'Your demo session expired. Reload the page to start a fresh one.' }, 410);
  if (r.status !== 200) return json({ error: r.body?.error || 'Engine unavailable' }, 503);
  return json(await buildFindingsView(r.body, sess.sid, sess.pid));
}

/** POST (Idempotency-Key required): a named, self-declared human decision on ONE AI finding. reject/defer record only and never call the engine.
 *  accept requires the finding to be verified and SUPPORTED, the client to have seen the current preview (preview_digest), and then forwards exactly one
 *  existing engine scope decision. If the engine refuses, nothing is recorded as accepted. */
export async function aiFindingDecision(req: NextRequest) {
  const sess = decode(req.cookies.get(COOKIE)?.value);
  const blocked = gate(req, sess, true);
  if (blocked) return blocked;
  if (!sess) return json({ error: 'No demo session. Reload the page to start one.' }, 401);
  const key = req.headers.get('idempotency-key') || '';
  if (!IDEM_RE.test(key)) return json({ error: 'A decision needs an Idempotency-Key header (8-128 characters).', code: 'IDEMPOTENCY_KEY_REQUIRED' }, 400);
  if (Number(req.headers.get('content-length') || 0) > 4096) return json({ error: 'Request too large' }, 413);
  let body: any; try { body = JSON.parse(await req.text()); } catch { return json({ error: 'Invalid JSON' }, 400); } // eslint-disable-line @typescript-eslint/no-explicit-any
  const allowed = ['finding_id', 'decision', 'by', 'note', 'preview_digest'];
  if (!body || typeof body !== 'object' || Array.isArray(body) || Object.keys(body).some(k => !allowed.includes(k))) return json({ error: 'Unknown or malformed field (allowed: ' + allowed.join(', ') + ')' }, 400);
  for (const k of ['finding_id', 'decision', 'by', 'note']) if (typeof body[k] !== 'string' || !body[k].trim() || body[k].length > 600) return json({ error: `Missing or invalid field: ${k}` }, 400);
  if (!['accept', 'reject', 'defer'].includes(body.decision)) return json({ error: 'decision must be accept, reject or defer' }, 400);
  if (body.preview_digest !== undefined && (typeof body.preview_digest !== 'string' || body.preview_digest.length > 100)) return json({ error: 'Invalid preview_digest' }, 400);
  const st = aiStoreFor(sess.sid, sess.pid);
  const hash = sha(canonical({ f: body.finding_id, d: body.decision, by: body.by.trim(), n: body.note.trim(), p: body.preview_digest ?? null }));
  const prior = st.ledger.get(key);
  if (prior) {
    if (prior.hash !== hash) return json({ error: 'This Idempotency-Key was already used for a different decision or payload', code: 'IDEMPOTENCY_KEY_REUSED' }, 409);
    return NextResponse.json(prior.response, { status: prior.status, headers: { 'Cache-Control': 'no-store', 'Idempotent-Replay': 'true', 'X-Idempotency-Result': 'historical' } });
  }
  const led = await loadLedger();
  const f = led?.data.findings.find((x: any) => x.finding_id === body.finding_id); // eslint-disable-line @typescript-eslint/no-explicit-any
  if (!f) return json({ error: 'Unknown AI finding', code: 'UNKNOWN_FINDING' }, 404);
  const cur = st.decisions.get(f.finding_id);
  if (cur && cur.decision !== 'defer') return json({ error: `This finding was already ${cur.decision}ed by ${cur.by}; a final decision is not revisited here.`, code: 'FINDING_ALREADY_DECIDED' }, 409);
  const pr = await engine('GET', `projects/${sess.pid}`, ownerFor(sess.sid));
  if (pr.status === 404) return json({ error: 'Your demo session expired. Reload the page to start a fresh one.' }, 410);
  if (pr.status !== 200) return json({ error: pr.body?.error || 'Engine unavailable' }, 503);
  const sv0 = Number(pr.body.scope_version ?? 0);
  const record = (outcome: Decision['outcome'], after: number | null, exId?: string): Decision => ({ finding_id: f.finding_id, decision: body.decision, by: body.by.trim(), note: body.note.trim(), at: new Date().toISOString(), idempotency_key: key, outcome, scope_version_before: sv0, scope_version_after: after, engine_exception_id: exId });
  const done = (status: number, response: any, rec?: Decision) => { if (rec) st.decisions.set(f.finding_id, rec); st.ledger.set(key, { hash, response, status }); return NextResponse.json(response, { status, headers: { 'Cache-Control': 'no-store' } }); }; // eslint-disable-line @typescript-eslint/no-explicit-any
  const ident = 'SELF_DECLARED_DEMO_ACTOR_NOT_AUTHENTICATED';
  if (body.decision !== 'accept') {
    const rec = record('recorded_only', sv0);
    return done(200, { recorded: true, actor_identity: ident, decision: rec, scope_changed: false, scope_version: sv0, status: `AI finding ${body.decision}ed. Authoritative scope, calculations, crew plans, pricing and release digests were not touched.` }, rec);
  }
  const pv = previewFor(f, pr.body);
  if (pv.kind === 'blocked') return json({ error: pv.reason, code: pv.code }, 409);
  const digest = sha(canonical({ id: f.finding_id, k: pv.kind, s: pv.steps, v: sv0 }));
  if (body.preview_digest !== digest) return json({ error: 'The scope change preview is stale or was not shown to you. Reload the findings and review the current preview.', code: 'AI_PREVIEW_STALE', details: { current_preview_digest: digest } }, 409);
  if (pv.kind === 'no_scope_change') {
    const rec = record('no_scope_change', sv0);
    return done(200, { recorded: true, actor_identity: ident, decision: rec, scope_changed: false, scope_version: sv0, status: 'Accepted as supporting evidence only. Scope was not changed.' }, rec);
  }
  const step = pv.steps[0];
  const note = `AI-assisted human decision: finding ${f.finding_id} (${f.model.requested}, run ${f.run.run_id}, verification ${f.verification.verdict}) accepted by ${body.by.trim()}. The AI supplied a plan side only; the value ${step.value} ${step.unit} is the human-prepared derivation. ${body.note.trim()}`.slice(0, 1990);
  const r = await engine('POST', `projects/${sess.pid}/scope/resolve`, ownerFor(sess.sid), { exception_id: step.exception_id, option_id: step.option_id, by: body.by.trim(), note }, { 'Idempotency-Key': key });
  if (r.status !== 200) return NextResponse.json({ ...(typeof r.body === 'object' ? r.body : {}), accepted: false, status: 'The engine refused the scope decision; nothing was recorded as accepted.' }, { status: r.status === 404 ? 410 : r.status, headers: { 'Cache-Control': 'no-store' } });
  const after = await engine('GET', `projects/${sess.pid}`, ownerFor(sess.sid));
  const sv1 = after.status === 200 ? Number(after.body.scope_version ?? sv0 + 1) : sv0 + 1;
  const rec = record('scope_decision_recorded', sv1, step.exception_id);
  return done(200, { recorded: true, actor_identity: ident, decision: rec, scope_changed: true, scope_version: sv1, engine_exception_id: step.exception_id, status: 'Your approval was recorded through the existing Scope gate (engine scope decision). The AI finding did not authorize it.' }, rec);
}

/** GET: the AI Flight Recorder. Producer layers (AMD / Gemma / Evolus) come from validated trace files; Gatehouse validation and human authorization are computed here
 *  from the ledger and THIS visitor's live project. Read-only; no model, AMD or Evolus call; nothing here can change scope, pricing or release. */
export async function flightRecorder(req: NextRequest) {
  const sess = decode(req.cookies.get(COOKIE)?.value);
  const blocked = gate(req, sess, false);
  if (blocked) return blocked;
  if (!sess) return json({ error: 'No demo session. Reload the page to start one.' }, 401);
  const [prod, ledger] = await Promise.all([loadEvidence(), loadLedger()]);
  const r = await engine('GET', `projects/${sess.pid}`, ownerFor(sess.sid));
  const project = r.status === 200 ? r.body : null;
  const decisions = [...aiStoreFor(sess.sid, sess.pid).decisions.values()];
  const reg = await loadRegistryDocs();
  const cs = await loadCases(prod.executions, reg);
  await attachAudits(cs.reviews, prod.executions, cs.runs, reg, cs.sources, RELEASE_AUDIT_MANIFEST);
  const executions = prod.executions.map(x => ({ ...x, review: cs.reviews.get(x.trace_id) ?? null }));
  return json({ schema: 'gatehouse-flight-recorder-view.v3', contract: 'gatehouse-flight-trace.v1',
    executions,                       // each external trace, newest first; NEVER merged with each other or with `historical`
    historical: { layers: await withRunStatement(prod.historical.layers, prod.executions), source: prod.historical.source, validation: validationLayer(ledger) },
    session: { human_authorization: humanLayer(project, decisions) },
    sources: [...prod.sources, ...cs.sources],
    notice: 'Every value is shown from a stored or live record with its provenance state. Nothing is estimated. "Not reported" means the record does not contain it. Executions and historical evidence come from different runs and are never combined.' });
}

/** The stored history's Evolus layer carries a fixed sentence written before any run existed. Replace it with a statement built from the run records and traces. */
async function withRunStatement(layers: any[], execs: any[]) {
  const summary = await evolusStatement(execs);
  return layers.map(l => (l.layer === 'evolus' ? { ...l, summary } : l));
}

/** GET: the AI activity rows, read only from stored records. No model is called and nothing is written. */
export async function aiActivity(req: NextRequest) {
  const sess = decode(req.cookies.get(COOKIE)?.value);
  const blocked = gate(req, sess, false);
  if (blocked) return blocked;
  if (!sess) return json({ error: 'No demo session. Reload the page to start one.' }, 401);
  return json(await buildAiActivity());
}

/** GET ?format=csv: read-only bid export of what the engine priced and authorized. Draft state is stamped DRAFT; the readiness class is never dropped. */
export async function bidExport(req: NextRequest) {
  const sess = decode(req.cookies.get(COOKIE)?.value);
  const blocked = gate(req, sess, false);
  if (blocked) return blocked;
  if (!sess) return json({ error: 'No demo session. Reload the page to start one.' }, 401);
  const format = req.nextUrl.searchParams.get('format') || 'csv';
  if (format !== 'csv') return json({ error: 'format must be csv', code: 'BAD_FORMAT' }, 400);
  const r = await engine('GET', `projects/${sess.pid}`, ownerFor(sess.sid));
  if (r.status === 404) return json({ error: 'Your demo session expired. Reload the page to start a fresh one.' }, 410);
  if (r.status !== 200) return json({ error: r.body?.error || 'Engine unavailable' }, 503);
  if (!r.body?.pricing?.crew_plan) return json({ error: 'Select and approve one crew for the whole job before exporting.', code: 'CREW_REQUIRED' }, 409);
  let review: any = null; // eslint-disable-line @typescript-eslint/no-explicit-any
  try { review = await buildReview(r.body, sess.sid, sess.pid); } catch { review = null; }
  try {
    const x = buildExport(r.body, review);
    const body = toCsv(x);
    return new NextResponse(body, { status: 200, headers: {
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': `attachment; filename="${x.filename}.csv"`,
      'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' } });
  } catch (e) {
    if (e instanceof ExportRefused) return json({ error: e.message, code: e.code }, 409);
    return json({ error: 'Export failed', code: 'EXPORT_FAILED' }, 500);
  }
}

/** Bid Desk: advisory, session-bound, rate-limited. GET returns the current gate state; POST answers one short question from engine data only. Nothing is recorded. */
export async function bidDesk(req: NextRequest) {
  const sess = decode(req.cookies.get(COOKIE)?.value);
  const post = req.method === 'POST';
  const blocked = gate(req, sess, post);
  if (blocked) return blocked;
  if (!sess) return json({ error: 'No demo session. Reload the page to start one.' }, 401);
  let message = '';
  if (post) {
    if (!allow(`desk:${sess.sid}`, 20, 10 * 60_000) || !allow(`deskip:${clientIp(req.headers)}`, 60, 10 * 60_000)) return json({ error: 'The Bid Desk is rate-limited. Try again in a few minutes.', code: 'RATE_LIMITED' }, 429);
    let b: any; try { b = JSON.parse(await req.text()); } catch { return json({ error: 'Invalid JSON' }, 400); } // eslint-disable-line @typescript-eslint/no-explicit-any
    if (!b || typeof b !== 'object' || typeof b.message !== 'string') return json({ error: 'message must be text', code: 'BAD_REQUEST' }, 400);
    if (b.message.length > DESK_MAX_CHARS) return json({ error: `Keep it under ${DESK_MAX_CHARS} characters.`, code: 'TOO_LONG' }, 400);
    message = b.message;
  }
  const r = await engine('GET', `projects/${sess.pid}`, ownerFor(sess.sid));
  if (r.status === 404) return json({ error: 'Your demo session expired. Reload the page to start a fresh one.' }, 410);
  if (r.status !== 200) return json({ error: r.body?.error || 'Engine unavailable' }, 503);
  const draft = await scopeDraft();
  if (!post) return json({ advisory: true, audit_record: false, mode: 'SIMULATED', live: { enabled: false, reason: liveReason() }, gate_state: gateStateOf(fromEngine(r.body), draft) });
  return json(deskAnswer(fromEngine(r.body), message, draft));
}

const ADDENDUM_MAX = 5_000_000;
const INTAKE_RE = /^[0-9a-f]{16}$/;

/** POST multipart (file + by). Binds to the ANVIL 2 contract: POST /projects/{id}/addenda {filename, content_base64, by}. The engine hashes, validates, parses
 *  and verifies; the browser decides nothing about the document. */
export async function addendumUpload(req: NextRequest) {
  const sess = decode(req.cookies.get(COOKIE)?.value);
  const blocked = gate(req, sess, true);
  if (blocked) return blocked;
  if (!sess) return json({ error: 'No demo session. Reload the page to start one.' }, 401);
  if (Number(req.headers.get('content-length') || 0) > ADDENDUM_MAX + 65_536) return json({ error: 'The PDF is too large (limit 5 MB).', code: 'TOO_LARGE' }, 413);
  let form: FormData;
  try { form = await req.formData(); } catch { return json({ error: 'Send the PDF as a form upload.', code: 'BAD_REQUEST' }, 400); }
  const file = form.get('file'), by = String(form.get('by') || '').trim();
  if (!(file instanceof File)) return json({ error: 'Choose a PDF file.', code: 'BAD_REQUEST' }, 400);
  if (!by || by.length > 80) return json({ error: 'Enter your name: an upload is recorded under a named person.', code: 'ACTOR_REQUIRED' }, 400);
  if (file.size > ADDENDUM_MAX) return json({ error: 'The PDF is too large (limit 5 MB).', code: 'TOO_LARGE' }, 413);
  const bytes = Buffer.from(await file.arrayBuffer());
  if (!bytes.length) return json({ error: 'The file is empty.', code: 'EMPTY' }, 400);
  const safeName = (file.name || 'addendum.pdf').replace(/^.*[\\/]/, '').replace(/[^A-Za-z0-9._ -]/g, '_').slice(0, 100) || 'addendum.pdf';
  const r = await engine('POST', `projects/${sess.pid}/addenda`, ownerFor(sess.sid), { filename: safeName, content_base64: bytes.toString('base64'), by }, undefined, 120_000);
  if (r.status === 404) return json({ error: 'Your demo session expired. Reload the page to start a fresh one.' }, 410);
  if (r.status !== 200 && r.status !== 202) return reply(r); // 202: the engine is reading the document; the client polls the project state
  return json({ intake: r.body?.intake ?? null }, 202);
}

/** POST JSON: a named person accepts the engine-verified Before/After. The engine re-checks that nothing changed since it was shown. */
export async function addendumAccept(req: NextRequest) {
  const sess = decode(req.cookies.get(COOKIE)?.value);
  const blocked = gate(req, sess, true);
  if (blocked) return blocked;
  if (!sess) return json({ error: 'No demo session. Reload the page to start one.' }, 401);
  let b: any; // eslint-disable-line @typescript-eslint/no-explicit-any
  try { b = JSON.parse(await req.text()); } catch { return json({ error: 'Invalid JSON' }, 400); }
  if (!b || typeof b !== 'object' || !INTAKE_RE.test(String(b.intake_id))) return json({ error: 'Unknown addendum.', code: 'BAD_REQUEST' }, 400);
  const payload = { by: String(b.by ?? ''), note: String(b.note ?? ''), scope_version: b.scope_version, proposal_digest: b.proposal_digest ?? null, ...(typeof b.addendum_label === 'string' && b.addendum_label.trim() ? { addendum_label: b.addendum_label.trim().slice(0, 60) } : {}),
    ...(typeof b.addendum_item_reference === 'string' && b.addendum_item_reference.trim() ? { addendum_item_reference: b.addendum_item_reference.trim().slice(0, 60) } : {}) };
  const r = await engine('POST', `projects/${sess.pid}/addenda/${b.intake_id}/accept`, ownerFor(sess.sid), payload);
  if (r.status === 404) return json({ error: 'Your demo session expired or the addendum is gone. Reload the page.' }, 410);
  return reply(r);
}

/** POST JSON: a named person declines the proposed addendum. Nothing changes in the scope. */
export async function addendumDecline(req: NextRequest) {
  const sess = decode(req.cookies.get(COOKIE)?.value);
  const blocked = gate(req, sess, true);
  if (blocked) return blocked;
  if (!sess) return json({ error: 'No demo session. Reload the page to start one.' }, 401);
  let b: any; // eslint-disable-line @typescript-eslint/no-explicit-any
  try { b = JSON.parse(await req.text()); } catch { return json({ error: 'Invalid JSON' }, 400); }
  if (!b || typeof b !== 'object' || !INTAKE_RE.test(String(b.intake_id))) return json({ error: 'Unknown addendum.', code: 'BAD_REQUEST' }, 400);
  const r = await engine('POST', `projects/${sess.pid}/addenda/${b.intake_id}/decline`, ownerFor(sess.sid), { by: String(b.by ?? ''), note: String(b.note ?? '') });
  if (r.status === 404) return json({ error: 'Your demo session expired or the addendum is gone. Reload the page.' }, 410);
  return reply(r);
}

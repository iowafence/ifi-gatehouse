// Evolus Bid Desk: a READ-ONLY conversational guide. Server-side only. It holds the Evolus credentials, so nothing here is imported by a client component.
// It builds a bounded CONTEXT from the engine state the Bid Desk already reads, asks the Evolus agent one question, filters the reply, and labels it.
// It has no way to change anything: there is no engine call, no write and no mutation in this module. Replies are explanatory text, not audit records.
import { allow } from './limits.ts';
import { getConversation, setConversation } from './session.ts';
import { buildScopeGates, type Gate } from './scope-gates.ts';
import { gateStateOf } from './bid-desk.ts';

/* eslint-disable @typescript-eslint/no-explicit-any */

// ---------------------------------------------------------------- configuration (read at request time)
/** Exact hosts the integration may ever call. The base URL comes from the environment only, never from a request. */
export const ALLOWED_HOSTS: readonly string[] = ['api.evolus.ai'];
export type DeskCfg = {
  enabled: boolean; baseUrl: string | null; apiKey: string | null; appId: string | null; agentId: string | null;
  timeoutMs: number; globalPerDay: number; ipPerDay: number; maxChars: number; problem: string | null;
};
const intEnv = (v: string | undefined, dflt: number, lo: number, hi: number) => { const n = Number.parseInt(v || '', 10); return Number.isFinite(n) ? Math.min(hi, Math.max(lo, n)) : dflt; };
const GUID = /^[A-Za-z0-9-]{8,64}$/;

export function readCfg(env: Record<string, string | undefined> = process.env): DeskCfg {
  const enabled = env.EVOLUS_DESK_ENABLED === '1';
  const cfg: DeskCfg = {
    enabled, baseUrl: null, apiKey: null, appId: null, agentId: null,
    timeoutMs: intEnv(env.EVOLUS_DESK_TIMEOUT_MS, 25_000, 1_000, 60_000),
    globalPerDay: intEnv(env.EVOLUS_DESK_GLOBAL_PER_DAY, 600, 1, 100_000),
    ipPerDay: intEnv(env.EVOLUS_DESK_IP_PER_DAY, 100, 1, 10_000),
    maxChars: intEnv(env.EVOLUS_DESK_MAX_CHARS, 1000, 200, 4000), problem: null,
  };
  if (!enabled) return cfg;
  let u: URL | null = null;
  try { u = new URL(String(env.EVOLUS_BASE_URL || '')); } catch { u = null; }
  if (!u || u.protocol !== 'https:' || !ALLOWED_HOSTS.includes(u.hostname) || u.username || u.password || (u.port && u.port !== '443')) cfg.problem = 'The Evolus address is not allowed.';
  else cfg.baseUrl = `https://${u.hostname}`;
  const key = (env.EVOLUS_API_KEY || '').trim(), app = (env.EVOLUS_APPLICATION_ID || '').trim(), agent = (env.EVOLUS_AGENT_ID || '').trim();
  if (!key || !GUID.test(app) || !GUID.test(agent)) cfg.problem = cfg.problem || 'The live desk is not fully configured.';
  else { cfg.apiKey = key; cfg.appId = app; cfg.agentId = agent; }
  return cfg;
}

export type IntegrationStatus = 'OFF' | 'ENABLED' | 'DEGRADED';
let lastFailureAt = 0;
const DEGRADED_FOR_MS = 5 * 60_000;
export const noteFailure = () => { lastFailureAt = Date.now(); };
export const noteSuccess = () => { lastFailureAt = 0; };
export function deskStatus(cfg: DeskCfg): IntegrationStatus {
  if (!cfg.enabled) return 'OFF';
  if (cfg.problem || !cfg.baseUrl) return 'DEGRADED';
  return lastFailureAt && Date.now() - lastFailureAt < DEGRADED_FOR_MS ? 'DEGRADED' : 'ENABLED';
}

// ---------------------------------------------------------------- transport (replaceable; tests use a mock)
export type DeskErrorCode = 'TIMEOUT' | 'AUTH' | 'RATE_LIMIT' | 'HTTP' | 'BAD_RESPONSE' | 'NETWORK' | 'CONFIG';
export class DeskError extends Error { code: DeskErrorCode; constructor(code: DeskErrorCode, msg = code) { super(msg); this.code = code; } }
export type AgentInfo = { agentId: string; name?: string; modelDisplayName?: string };
export interface Transport {
  ask(a: { content: string; conversationId: string | null }, cfg: DeskCfg): Promise<{ answer: string; conversationId: string | null }>;
  agents(cfg: DeskCfg): Promise<AgentInfo[]>;
}
const MAX_BODY = 200_000;

async function call(cfg: DeskCfg, method: 'GET' | 'POST', path: string, body?: unknown): Promise<any> {
  if (!cfg.baseUrl || !cfg.apiKey || !cfg.appId) throw new DeskError('CONFIG');
  const url = new URL(path, cfg.baseUrl + '/');
  if (url.protocol !== 'https:' || !ALLOWED_HOSTS.includes(url.hostname)) throw new DeskError('CONFIG');
  let res: Response;
  try {
    res = await fetch(url, { method, cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(cfg.timeoutMs),
      headers: { 'X-ApiKey': cfg.apiKey, 'X-Application-Id': cfg.appId, 'Content-Type': 'application/json', Accept: 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body) });
  } catch (e: any) { throw new DeskError(e && (e.name === 'TimeoutError' || e.name === 'AbortError') ? 'TIMEOUT' : 'NETWORK'); }
  if (res.status === 401 || res.status === 403 || res.status === 402) throw new DeskError('AUTH');
  if (res.status === 429) throw new DeskError('RATE_LIMIT');
  if (!res.ok) throw new DeskError('HTTP');
  const text = (await res.text().catch(() => '')).slice(0, MAX_BODY);
  try { return JSON.parse(text); } catch { throw new DeskError('BAD_RESPONSE'); }
}

export const evolusTransport: Transport = {
  async ask(a, cfg) {
    const out = await call(cfg, 'POST', `api/v1/agents/${encodeURIComponent(cfg.agentId || '')}/ask`, { content: a.content, conversationId: a.conversationId });
    if (!out || typeof out.answer !== 'string' || !out.answer.trim()) throw new DeskError('BAD_RESPONSE');
    return { answer: out.answer, conversationId: typeof out.conversationId === 'string' ? out.conversationId : null };
  },
  async agents(cfg) {
    const out = await call(cfg, 'GET', 'api/v1/agents');
    const list = Array.isArray(out) ? out : Array.isArray(out?.agents) ? out.agents : null;
    if (!list) throw new DeskError('BAD_RESPONSE');
    return list.filter((x: any) => x && typeof x === 'object').map((x: any) => ({ agentId: String(x.agentId ?? x.id ?? ''), name: typeof x.name === 'string' ? x.name : undefined, modelDisplayName: typeof x.modelDisplayName === 'string' ? x.modelDisplayName : undefined }));
  },
};

// ---------------------------------------------------------------- configured model (cached, single-flight; failure = not reported)
const MODEL_TTL_MS = 10 * 60_000;
let modelCache: { at: number; value: string | null; key: string } | null = null;
let modelFlight: Promise<string | null> | null = null;
export const resetModelCache = () => { modelCache = null; modelFlight = null; };
/** The model the Evolus agent is CONFIGURED with. Evolus replies do not report which model answered, so this is a configuration label only. */
export async function configuredModel(cfg: DeskCfg, transport: Transport = evolusTransport): Promise<string | null> {
  if (!cfg.enabled || cfg.problem || !cfg.agentId) return null;
  const key = `${cfg.baseUrl}|${cfg.agentId}`;
  if (modelCache && modelCache.key === key && Date.now() - modelCache.at < MODEL_TTL_MS) return modelCache.value;
  if (modelFlight) return modelFlight;
  modelFlight = (async () => {
    let value: string | null = null;
    try {
      const me = (await transport.agents(cfg)).find(x => x.agentId.toLowerCase() === (cfg.agentId || '').toLowerCase());
      const m = me?.modelDisplayName?.trim();
      value = m && m.length <= 80 && /^[\w .:/+()-]+$/.test(m) ? m : null;
    } catch { value = null; }
    modelCache = { at: Date.now(), value, key }; modelFlight = null; return value;
  })();
  return modelFlight;
}

// ---------------------------------------------------------------- limits
/** Daily caps on live calls. Called immediately before an Evolus request; the existing per-session and per-IP desk limits stay in bidDesk(). */
export function checkDeskCaps(ip: string, cfg: DeskCfg): 'global' | 'ip' | null {
  if (!allow('evolus-desk:global', cfg.globalPerDay, 86_400_000)) return 'global';
  if (!allow(`evolus-desk:ip:${ip}`, cfg.ipPerDay, 86_400_000)) return 'ip';
  return null;
}

// ---------------------------------------------------------------- context
const r2 = (n: number) => Math.round(n * 100) / 100;
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v)) ? Number(v) : null);
const clip = (s: unknown, n: number) => String(s ?? '').replace(/\s+/g, ' ').trim().slice(0, n);
export const CONTEXT_CAP = 6000;

/** Which of the five guided steps the current state shows. Computed from engine state only. */
export function currentStep(p: any, takeoff: any | null): { n: 1 | 2 | 3 | 4 | 5 | 6; name: string } {
  if (p?.status === 'released') return { n: 6, name: 'released for proposal preparation' };
  if (p?.status === 'needs_scope_review') return { n: 1, name: 'scope review' };
  const wage = p?.pricing?.wage;
  if (wage && wage.required && !wage.cleared) return { n: 2, name: 'prevailing-wage verification' };
  if (!p?.pricing?.crew_plan) return { n: 3, name: 'crew review' };
  if (!takeoff?.attestation) return { n: 4, name: 'quantity verification' };
  return { n: 5, name: 'release authorization' };
}

/** The bounded, read-only facts sent with every turn. No reviewer names, notes, session ids or raw document text. Figures are never trimmed. */
export function buildContext(p: any, draft: any | null, takeoff: any | null): { text: string; step: { n: number; name: string } } {
  const gates: Gate[] = (() => { try { return buildScopeGates(p, draft, null); } catch { return []; } })();
  const step = currentStep(p, takeoff);
  const gs = gateStateOf(p, draft);
  const pr = p?.pricing || {};
  const ev = pr.estimate_view || {};
  const alt = Array.isArray(ev.alternates) ? ev.alternates : [];
  const crewsRaw: any[] = Array.isArray(pr.crew_comparison?.BASE?.crews) ? pr.crew_comparison.BASE.crews : [];
  const tasks: any[] = Array.isArray(pr.crew_comparison?.BASE?.tasks) ? pr.crew_comparison.BASE.tasks : [];
  const crews = crewsRaw.map(c => {
    const id = String(c.crew_id);
    let why = '';
    for (const t of tasks) { const cand = (t.candidates || []).find((x: any) => x.crew_id === id && x.eligible === false); if (cand) { why = clip((cand.reasons_display?.[0] ?? cand.reasons?.[0] ?? 'not eligible for a task'), 90); break; } }
    const complete = c.complete === true;
    return { crew_id: id, name: clip(c.description, 60), eligible_for_whole_job: complete, ...(complete ? { labor_cost_usd: num(c.labor_cost) } : { disqualified_for: why || 'not eligible for every task', partial_labor_cost_usd: num(c.labor_cost) }) };
  });
  const complete = crews.filter(c => c.eligible_for_whole_job && typeof (c as any).labor_cost_usd === 'number');
  const crewDiffs: string[] = [];
  for (let i = 0; i < complete.length; i++) for (let j = i + 1; j < complete.length; j++) {
    const a = complete[i] as any, b = complete[j] as any; crewDiffs.push(`${b.crew_id} labor minus ${a.crew_id} labor = ${r2(b.labor_cost_usd - a.labor_cost_usd)}`);
  }
  const basePrice = pr.crew_plan ? num(ev.price_total) : null;
  const altPrice = pr.crew_plan && alt[0] ? num(alt[0].price_total) : null;
  const wage = pr.wage || {};
  const wageRows = (Array.isArray(wage.role_classifications) ? wage.role_classifications : []).slice(0, 8).map((r: any) => ({
    role: clip(r.role, 30), classification: clip(r.classification, 48), schedule_base_usd_hr: num(r.decision_base_rate), schedule_fringe_usd_hr: num(r.decision_fringe_rate), rate_used_usd_hr: num(r.base_rate) }));
  const g3 = (takeoff?.g3?.facts || []).filter((f: any) => f && (f.id === 'opening' || /post|footing|diam|depth|od/i.test(String(f.id)))).slice(0, 6)
    .map((f: any) => ({ fact: clip(f.label, 40), value: num(f.value) ?? clip(f.value, 20), unit: clip(f.unit, 8), status: clip(f.status, 30) }));
  const scen: any = {};
  for (const k of ['base', 'alt']) {
    const s = takeoff?.scenarios?.[k]; if (!s) continue;
    const t = s.footing?.totals || {};
    scen[k] = { label: clip(s.label, 24), gross_fence_lf: num(s.ledger?.gross?.total), openings: (s.ledger?.openings || []).slice(0, 6).map((o: any) => ({ tag: clip(o.tag, 6), count: num(o.count), each_ft: num(o.each), status: clip(o.status, 20) })),
      posts: num(t.posts), holes: num(t.holes ?? t.holes_total) };
  }
  const base: any = {
    project: 'DP-001 (fictional demonstration)', current_step: `${step.n} of 5 - ${step.name}`.replace('6 of 5', 'after step 5'),
    gate: { stage: gs.stage, status: gs.status, scope_version: gs.scope_version, blocking_items: gs.blocking, g3: gs.g3, addendum: gs.addendum, crew: gs.crew, release: gs.release },
    bid_options: { base: 'Base Bid', alternate: 'Alternate A-1 (in lieu of the Base Bid; never added to it)', ...(basePrice !== null ? { base_total_usd: basePrice } : {}), ...(altPrice !== null ? { alternate_total_usd: altPrice, base_minus_alternate_usd: basePrice !== null ? r2(basePrice - altPrice) : undefined } : {}) },
    precedence: 'Addendum 01 controls over earlier inconsistent descriptions: G2 is a 12 ft clear opening, double leaf.',
    scope_gates: gates.filter(g => g.id !== 'other').map(g => ({ id: g.id, title: clip(g.title, 60), state: g.state, blocking: g.blocking })),
    g3_facts: g3,
    wage: { required: wage.required === true, recorded: wage.recorded === true, cleared: wage.cleared === true, schedule: clip(wage.decision?.decision_id, 24), rows: wageRows },
    crews, crew_differences: crewDiffs,
    takeoff: { scenarios: scen, reviewed: !!takeoff?.attestation },
    release: { status: clip(p?.status, 24), released: p?.status === 'released' },
  };
  const drop: ((o: any) => void)[] = [
    o => { o.scope_gates = (o.scope_gates || []).map((g: any) => ({ id: g.id, state: g.state, blocking: g.blocking })); },
    o => { for (const r of o.wage.rows) { r.classification = clip(r.classification, 24); } },
    o => { for (const c of o.crews) { c.name = ''; if (c.disqualified_for) c.disqualified_for = clip(c.disqualified_for, 40); } },
    o => { o.g3_facts = (o.g3_facts || []).slice(0, 3); },
    o => { delete o.precedence; },
  ];
  let text = JSON.stringify(base);
  for (const d of drop) { if (text.length <= CONTEXT_CAP) break; d(base); text = JSON.stringify(base); }
  return { text, step };
}

export const PREAMBLE = [
  'You are the Gatehouse Bid Desk guide. You are a READ-ONLY guide for a fictional demonstration.',
  'You cannot accept, approve, select, resolve, record or release anything. The estimator does those with the on-screen buttons. Never say or imply that you did.',
  'Use only figures that appear in CONTEXT. Do not calculate, estimate or recommend a crew. If CONTEXT lacks a figure, say it is not available.',
  'Guide the estimator through five steps in order: (1) scope review: Base Bid vs Alternate A-1, addendum precedence, resolving G3 with Addendum 02; (2) verify the prevailing-wage rates extracted from the specifications; (3) review the eligible and disqualified crews with the Gatehouse-calculated totals; (4) quantity verification: ask whether the estimated quantities have been verified and mention the Takeoff Review; (5) the estimator explicitly authorizes release for proposal preparation.',
  'State which step the current state shows (CONTEXT current_step), say what the estimator should do next on screen, and ask at most one question. Plain text only, short.',
].join('\n');

// ---------------------------------------------------------------- output filters
const numberOf = (s: string) => Number(s.replace(/,/g, ''));
const decimalsOf = (s: string) => { const m = /\.(\d+)/.exec(s); return m ? m[1].length : 0; };
const SCALE: Record<string, number> = { k: 1e3, thousand: 1e3, m: 1e6, million: 1e6 };

/** Every number in the CONTEXT text (commas removed). A reply figure is supported when it equals one of these, or is a plain rounding of one. */
export function contextFigures(ctx: string): number[] {
  const out: number[] = [];
  for (const m of ctx.matchAll(/-?\d[\d,]*(?:\.\d+)?/g)) { const n = numberOf(m[0]); if (Number.isFinite(n)) out.push(Math.abs(n)); }
  return out;
}
const supported = (v: number, decimals: number, scale: number, figs: number[]) => {
  const tol = 0.5 * Math.pow(10, -decimals) * scale + 1e-9;
  return figs.some(c => Math.abs(v - c) <= tol);
};
const MONEY = /\$\s?(\d[\d,]*(?:\.\d+)?)\s*(k|m|thousand|million)?\b/gi;
const UNIT = /(?<![A-Za-z0-9.])(\d[\d,]*(?:\.\d+)?)\s?-?\s?(%|percent\b|LF\b|linear feet\b|linear foot\b|SF\b|sq\.? ?ft\b|square feet\b|EA\b|ft\b|feet\b|foot\b|inch(?:es)?\b|gates?\b|posts?\b|panels?\b|holes?\b|hours?\b|hrs?\b|\/hr\b|per hour\b)/gi;
const WORDNUM = /\b(?:total|labor|rate|price|cost|bid|subtotal)\b[^.\d$]{0,24}?(?<![A-Za-z0-9.])(\d[\d,]*(?:\.\d+)?)/gi;
const NUMWORD = /(?<![A-Za-z0-9.])(\d[\d,]*(?:\.\d+)?)\s+(?:total|labor|rate|price|cost)\b/gi;
const big = (s: string) => /[,.]/.test(s) || s.replace(/\D/g, '').length >= 3;

/** Unsupported financial amounts / unit-or-estimating-word numbers in one sentence (empty = fine). Section numbers, dates, ids and versions are not examined. */
export function unsupportedFigures(sentence: string, figs: number[]): string[] {
  const bad: string[] = [];
  const s = sentence.replace(/https?:\/\/\S+/g, ' ');
  for (const m of s.matchAll(MONEY)) {
    const sc = SCALE[(m[2] || '').toLowerCase()] || 1; const v = numberOf(m[1]) * sc;
    if (!supported(v, decimalsOf(m[1]), sc, figs)) bad.push(m[0]);
  }
  const money = s.replace(MONEY, ' ');
  for (const m of money.matchAll(UNIT)) { if (!supported(numberOf(m[1]), decimalsOf(m[1]), 1, figs)) bad.push(m[0]); }
  for (const re of [WORDNUM, NUMWORD]) for (const m of money.matchAll(re)) { if (big(m[1]) && !supported(numberOf(m[1]), decimalsOf(m[1]), 1, figs)) bad.push(m[0]); }
  return bad;
}
const ACTION_CLAIM = /\b(?:i|we)(?:'ve|’ve| have| had)?\s+(?:just\s+|already\s+|now\s+|successfully\s+)?(?:accept(?:ed)?|approv(?:e|ed)|releas(?:e|ed)|record(?:ed)?|select(?:ed)?|resolv(?:e|ed)|submit(?:ted)?|confirm(?:ed)?|sign(?:ed)?|saved?|chose|chosen|decid(?:e|ed)|appl(?:y|ied)|upload(?:ed)?)\b/i;
export const hasActionClaim = (t: string) => ACTION_CLAIM.test(t);
export const FIGURES_NOTE = 'Some figures were withheld: not in the engine state.';

export type FilterResult = { ok: true; text: string; withheldSome: boolean } | { ok: false; reason: 'ACTION_CLAIM' | 'TOO_LONG' | 'FIGURES' | 'EMPTY' };
export function filterReply(raw: string, ctx: string, maxChars: number): FilterResult {
  // plain text only: control characters and any markup brackets are removed; the UI renders it as text, never as HTML
  const text = String(raw ?? '').replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '').replace(/[<>]/g, '').trim();
  if (!text) return { ok: false, reason: 'EMPTY' };
  if (text.length > maxChars) return { ok: false, reason: 'TOO_LONG' };
  if (hasActionClaim(text)) return { ok: false, reason: 'ACTION_CLAIM' };
  const figs = contextFigures(ctx);
  const sentences = text.split(/(?<=[.!?])\s+|\n+/).map(x => x.trim()).filter(Boolean);
  const kept = sentences.filter(s => unsupportedFigures(s, figs).length === 0);
  if (!kept.length) return { ok: false, reason: 'FIGURES' };
  const withheldSome = kept.length < sentences.length;
  return { ok: true, text: kept.join(' ') + (withheldSome ? `\n${FIGURES_NOTE}` : ''), withheldSome };
}

// ---------------------------------------------------------------- one live turn
export const REASON: Record<string, string> = {
  TIMEOUT: 'Evolus did not answer in time.', AUTH: 'Evolus refused the request (credentials).', RATE_LIMIT: 'Evolus is limiting requests right now.',
  HTTP: 'Evolus returned an error.', BAD_RESPONSE: 'Evolus returned an unreadable reply.', NETWORK: 'Evolus could not be reached.', CONFIG: 'The live desk is not configured.',
  CAP_GLOBAL: 'The live desk reached its daily limit.', CAP_IP: 'This network reached its daily limit for the live desk.',
  ACTION_CLAIM: 'The reply was withheld: it claimed an action.', TOO_LONG: 'The reply was withheld: it was too long.', FIGURES: 'The reply was withheld: its figures are not in the engine state.', EMPTY: 'Evolus returned an empty reply.',
};
export type LiveOutcome = { mode: 'LIVE'; answer: string; withheld_note: boolean } | { mode: 'UNAVAILABLE'; reason: string };

export async function liveTurn(a: { cfg: DeskCfg; transport?: Transport; sid: string; sessionExp: number; capped?: 'global' | 'ip' | null; project: any; draft: any | null; takeoff: any | null; message: string }): Promise<LiveOutcome> {
  const { cfg, project, draft, takeoff, message } = a; const transport = a.transport || evolusTransport;
  if (!cfg.enabled || cfg.problem) return { mode: 'UNAVAILABLE', reason: REASON.CONFIG };
  const capped = a.capped ?? null;   // the daily caps are checked by the caller (bidDesk) immediately before this request
  if (capped) return { mode: 'UNAVAILABLE', reason: capped === 'global' ? REASON.CAP_GLOBAL : REASON.CAP_IP };
  const ctx = buildContext(project, draft, takeoff);
  const conv = getConversation(a.sid);
  const content = `${PREAMBLE}\n\nCONTEXT (the only source of figures):\n${ctx.text}\n\nESTIMATOR QUESTION:\n${clip(message, 400)}`;
  let got: { answer: string; conversationId: string | null };
  try { got = await transport.ask({ content, conversationId: conv ? conv.id : null }, cfg); }
  catch (e: any) { noteFailure(); return { mode: 'UNAVAILABLE', reason: REASON[e instanceof DeskError ? e.code : 'NETWORK'] || REASON.NETWORK }; }
  if (got.conversationId) setConversation(a.sid, got.conversationId, a.sessionExp);
  const f = filterReply(got.answer, ctx.text, cfg.maxChars);
  if (!f.ok) { return { mode: 'UNAVAILABLE', reason: REASON[f.reason] }; }
  noteSuccess();
  return { mode: 'LIVE', answer: f.text, withheld_note: f.withheldSome };
}

/** The POST body the Bid Desk returns. Flag off: the deterministic SIMULATED answer and no outbound call. Flag on: LIVE only for a reply that passed the filters,
 *  otherwise UNAVAILABLE with a one-line reason and the deterministic answer (labelled SIMULATED) after it. Credentials are never part of the result. */
export async function answerDesk(a: { cfg: DeskCfg; transport?: Transport; sid: string; sessionExp: number; capped: 'global' | 'ip' | null; project: any; draft: any | null;
  getTakeoff: () => Promise<any>; message: string; det: Record<string, any> }): Promise<Record<string, any>> {
  const { cfg, det } = a;
  if (!cfg.enabled) return det;
  let takeoff: any = null;
  if (!a.capped && !cfg.problem) { try { takeoff = await a.getTakeoff(); } catch { takeoff = null; } }
  const out = await liveTurn({ cfg, transport: a.transport, sid: a.sid, sessionExp: a.sessionExp, capped: a.capped, project: a.project, draft: a.draft, takeoff, message: a.message });
  const model = await configuredModel(cfg, a.transport);
  if (out.mode === 'LIVE') return { ...det, mode: 'LIVE', live: { enabled: true, reason: 'Answered by the Evolus Bid Desk agent.' }, configured_model: model, intent: 'live', answer: out.answer, sources: [], withheld_note: out.withheld_note };
  return { ...det, mode: 'UNAVAILABLE', live: { enabled: true, reason: out.reason }, configured_model: model, fallback_label: 'SIMULATED' };
}

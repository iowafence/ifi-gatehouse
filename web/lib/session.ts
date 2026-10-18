// Anonymous demo session: a signed, HttpOnly cookie that binds one visitor to exactly one engine project.
// Server-side only (Node runtime). The cookie holds no engine credential; SESSION_SIGNING_SECRET never leaves the server.
import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto';

export const COOKIE = 'gatehouse_demo';
export const SESSION_SECONDS = 12 * 60 * 60; // absolute lifetime; not extended by activity
export type Session = { sid: string; pid: string; exp: number };

function secret(): string {
  const s = process.env.SESSION_SIGNING_SECRET;
  if (!s || s.length < 32) throw new Error('SESSION_SIGNING_SECRET not configured securely');
  return s;
}
const sign = (payload: string) => createHmac('sha256', secret()).update(payload).digest('hex');

export function newSid(): string { return randomBytes(24).toString('hex'); }

/** Opaque owner id sent to the engine. Derived, so the engine never sees the cookie's sid. */
export function ownerFor(sid: string): string { return createHmac('sha256', secret()).update('owner:' + sid).digest('hex'); }

export function encode(s: Session): string {
  const payload = `v2.${s.sid}.${s.pid}.${s.exp}`;
  return `${payload}.${sign(payload)}`;
}

export function decode(raw: string | undefined | null): Session | null {
  if (!raw) return null;
  const m = /^v2\.([a-f0-9]{48})\.([a-f0-9]{32})\.(\d{10})\.([a-f0-9]{64})$/.exec(raw);
  if (!m) return null;
  const payload = `v2.${m[1]}.${m[2]}.${m[3]}`;
  const a = Buffer.from(sign(payload)), b = Buffer.from(m[4]);
  if (a.length !== b.length || !timingSafeEqual(a, b)) return null;
  if (Number(m[3]) <= Date.now() / 1000) return null;
  return { sid: m[1], pid: m[2], exp: Number(m[3]) };
}

export function cookieOptions(exp: number) {
  return { httpOnly: true, secure: process.env.NODE_ENV === 'production', sameSite: 'lax' as const, path: '/',
           maxAge: Math.max(1, exp - Math.floor(Date.now() / 1000)) };
}

// Evolus Bid Desk conversation id, bound to the session id. Kept ONLY in this server process's memory (like the limiter and the takeoff attestations):
// it is never put in the cookie, never sent to the browser and never accepted from a request. If it is lost (restart, another instance, expiry, the
// turn cap) the next turn simply starts a new conversation. It is cleared when the visitor resets the demo.
const CONV_MAX_ENTRIES = 5000, CONV_MAX_TURNS = 30, CONV_ID_RE = /^[A-Za-z0-9-]{8,64}$/;
const convs = new Map<string, { id: string; exp: number; turns: number }>();
export function getConversation(sid: string): { id: string; turns: number } | null {
  const c = convs.get(sid);
  if (!c) return null;
  if (c.exp <= Date.now() / 1000 || c.turns >= CONV_MAX_TURNS) { convs.delete(sid); return null; }
  return { id: c.id, turns: c.turns };
}
export function setConversation(sid: string, id: string, exp: number): void {
  if (!CONV_ID_RE.test(id)) return;
  const prev = convs.get(sid);
  if (!prev && convs.size >= CONV_MAX_ENTRIES) { const oldest = convs.keys().next().value; if (oldest !== undefined) convs.delete(oldest); }
  convs.set(sid, { id, exp, turns: prev && prev.id === id ? prev.turns + 1 : 1 });
}
export function clearConversation(sid: string | undefined | null): void { if (sid) convs.delete(sid); }

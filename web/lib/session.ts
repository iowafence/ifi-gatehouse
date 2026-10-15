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

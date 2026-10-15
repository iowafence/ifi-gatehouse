// Small fixed-window rate limiter, in memory. Per server instance: on a multi-instance host (e.g. serverless)
// the effective limit is per instance, so pair it with a shared store for a hard global limit. The engine
// additionally caps total projects and actions per project.
const buckets = new Map<string, { n: number; reset: number }>();
let lastSweep = 0;

export function allow(key: string, limit: number, windowMs: number): boolean {
  const now = Date.now();
  if (now - lastSweep > 60_000) {
    lastSweep = now;
    for (const [k, v] of buckets) if (v.reset <= now) buckets.delete(k);
    if (buckets.size > 50_000) buckets.clear(); // memory guard under flood
  }
  const b = buckets.get(key);
  if (!b || b.reset <= now) { buckets.set(key, { n: 1, reset: now + windowMs }); return true; }
  if (b.n >= limit) return false;
  b.n += 1;
  return true;
}

export function clientIp(h: Headers): string {
  // CLIENT_IP_HEADER names the ONE header your platform sets itself (e.g. fly-client-ip, cf-connecting-ip, x-vercel-forwarded-for). Use it on any public host:
  // x-forwarded-for can be forged by the client when the platform only appends to it, which would defeat the per-IP limits.
  if (process.env.CLIENT_IP_HEADER) {
    const named = h.get(process.env.CLIENT_IP_HEADER);
    if (!named) return 'unidentified'; // fail closed: one shared bucket
    const parts = named.split(',').map(x => x.trim()).filter(Boolean);
    // CLIENT_IP_FROM_RIGHT=N (1..9): take the Nth entry from the RIGHT. 1 = the last entry (a proxy that appends the address it saw writes it, so a client can prepend junk but cannot control it).
    // With several appending proxies in front of the app (e.g. a CDN then the platform router) the last entry is the NEAREST proxy, not the visitor: use the entry just left of the proxy hops you trust.
    // If there are fewer entries than N, or the value is not a digit 1..9, this FAILS CLOSED into one shared bucket. It never falls back to the client-controlled first entry.
    const fr = process.env.CLIENT_IP_FROM_RIGHT;
    if (fr !== undefined && fr !== '') { const n = /^[1-9]$/.test(fr) ? Number(fr) : 0; return (n && parts[parts.length - n] ? parts[parts.length - n] : 'unidentified').slice(0, 64); }
    return (parts[0] || 'unidentified').slice(0, 64);
  }
  // Without it: behind a trusted proxy (e.g. Vercel) the first hop is the client. Locally there is no header.
  const xff = h.get('x-forwarded-for');
  return (xff ? xff.split(',')[0].trim() : h.get('x-real-ip') || 'local').slice(0, 64);
}

/** Per-network limits, tunable for an event where many judges share one public IP. Defaults are the previous constants. Clamped; rate limiting is never disabled. */
const envInt = (name: string, dflt: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, Number.parseInt(process.env[name] || '', 10) || dflt));
export const ipRequestsPerMinute = () => envInt('IP_REQUESTS_PER_MIN', 300, 60, 6000);
/** Global ceiling on NEW demo sessions per hour, independent of any client-IP attribution (protects the engine's project cap if attribution fails). */
export const newDemosGlobalPerHour = () => envInt('NEW_DEMOS_GLOBAL_PER_HOUR', 300, 10, 5000);
export const ipMutationsPer10Min = () => envInt('IP_MUTATIONS_PER_10MIN', 120, 30, 3000);

// Opt-in diagnostic (CLIENT_IP_LOG_SHAPE=1): logs the SHAPE of the forwarding headers for the first 30 new-session requests, with each of the right-most 3 entries reduced to an 8-hex salted hash
// (salt is per process and never logged), so two requests from the same visitor can be compared to see which position is stable. No raw address is ever logged.
import { createHash, randomBytes } from 'node:crypto';
const SALT = randomBytes(8); let shapeLogged = 0;
export function logIpShape(h: Headers): void {
  if (process.env.CLIENT_IP_LOG_SHAPE !== '1' || shapeLogged >= 30) return; shapeLogged++;
  const hh = (v: string) => createHash('sha256').update(SALT).update(v).digest('hex').slice(0, 8);
  const xff = (h.get('x-forwarded-for') || '').split(',').map(x => x.trim()).filter(Boolean);
  console.log('[client-ip-shape]', JSON.stringify({ n: shapeLogged, xff_entries: xff.length, tail_hashes_right_to_left: xff.slice(-3).reverse().map(hh), cf_connecting_ip_present: h.has('cf-connecting-ip'), cf_hash: h.get('cf-connecting-ip') ? hh(h.get('cf-connecting-ip')!) : null, true_client_ip_present: h.has('true-client-ip'), x_real_ip_present: h.has('x-real-ip') }));
}

// Server-only engine client. The engine key stays here; nothing in this file is imported by client components.
export type EngineResult = { status: number; body: any; headers?: Record<string, string> }; // eslint-disable-line @typescript-eslint/no-explicit-any

// Response headers the adapter contract defines for historical replays and throttling; everything else is dropped.
const PASS_HEADERS = ['idempotent-replay', 'x-idempotency-result', 'x-original-audit-event-id', 'retry-after'];

// Deny by default: the ONLY engine paths this web tier may call. Anything else is a 404 and never reaches the engine
// (no /dev/projects, no crew-matrix, no addendum decide, no GET addenda/{id}). Paths are relative, as passed by callers.
const PID = '[0-9a-f]{32}', IID = '[0-9a-f]{16}';
const ALLOWED: [string, RegExp][] = [
  ['GET', /^health$/], ['GET', /^demo\/portfolio$/], ['POST', /^demo\/projects$/], ['DELETE', new RegExp(`^demo/projects/${PID}$`)],
  ['GET', new RegExp(`^projects/${PID}$`)],
  ['POST', new RegExp(`^projects/${PID}/(scope/resolve|labor/resolve|release|decisions/ruleset-approval|decisions/crew-plan|decisions/wage-determination|crew-plan/preview|addenda)$`)],
  ['POST', new RegExp(`^projects/${PID}/addenda/${IID}/(accept|decline)$`)],
];
export const engineAllowed = (method: string, path: string) => ALLOWED.some(([m, re]) => m === method && re.test(path));

export async function engine(method: string, path: string, owner: string, body?: unknown, extra?: Record<string, string>, timeoutMs = 20_000): Promise<EngineResult> {
  if (!engineAllowed(method, path)) return { status: 404, body: { error: 'Not found' } };
  const base = process.env.ENGINE_BASE_URL, key = process.env.ENGINE_API_KEY;
  if (!base || !key) return { status: 503, body: { error: 'Engine not connected' } };
  try {
    const res = await fetch(new URL(path, base.replace(/\/?$/, '/')), {
      method, cache: 'no-store', signal: AbortSignal.timeout(timeoutMs),
      headers: { 'X-Engine-Key': key, 'X-Demo-Owner': owner, 'Content-Type': 'application/json', Accept: 'application/json', ...extra },
      body: body === undefined ? undefined : body instanceof Uint8Array ? (body as unknown as BodyInit) : JSON.stringify(body),
    });
    if (!(res.headers.get('content-type') || '').includes('application/json')) return { status: 502, body: { error: 'Unexpected engine response' } };
    const json = await res.json().catch(() => null);
    if (res.status >= 500 || json === null) return { status: res.status === 503 ? 503 : 502, body: { error: res.status === 503 ? (json?.error || 'Demo capacity reached') : 'Engine operation failed' } };
    const headers: Record<string, string> = {};
    for (const h of PASS_HEADERS) { const v = res.headers.get(h); if (v) headers[h] = v.slice(0, 200); }
    return { status: res.status, body: json, headers };
  } catch { return { status: 503, body: { error: 'Engine unavailable or request timed out' } }; }
}

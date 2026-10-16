import test from 'node:test';
import assert from 'node:assert/strict';
import { engine, engineAllowed } from '../lib/engine.ts';
const P = 'a'.repeat(32), I = 'b'.repeat(16);
test('every engine path the web tier needs is allowed', () => {
  for (const [m, p] of [['GET', 'health'], ['GET', 'demo/portfolio'], ['POST', 'demo/projects'], ['DELETE', `demo/projects/${P}`], ['GET', `projects/${P}`],
    ...['scope/resolve', 'labor/resolve', 'release', 'decisions/ruleset-approval', 'decisions/crew-plan', 'decisions/wage-determination', 'crew-plan/preview', 'addenda'].map(x => ['POST', `projects/${P}/${x}`]),
    ['POST', `projects/${P}/addenda/${I}/accept`], ['POST', `projects/${P}/addenda/${I}/decline`]]) assert.ok(engineAllowed(m, p), `${m} ${p}`);
});
test('everything else is refused, including the paths that must stay closed', () => {
  for (const [m, p] of [['POST', 'dev/projects'], ['GET', 'dev/projects'], ['GET', `projects/${P}/crew-matrix`], ['POST', `projects/${P}/addenda/${I}/decide`], ['GET', `projects/${P}/addenda/${I}`],
    ['GET', `projects/${P}/addenda`], ['DELETE', `projects/${P}`], ['PUT', `projects/${P}`], ['GET', 'projects'], ['POST', `projects/${P}/../x`], ['POST', `projects/${P}/release/x`],
    ['GET', 'health/x'], ['GET', `projects/${'A'.repeat(32)}`], ['GET', `projects/${P}?x=1`], ['POST', `projects/${P}/addenda/${I}/accept/x`], ['GET', '//evil.example/x'], ['GET', 'admin']]) assert.ok(!engineAllowed(m, p), `${m} ${p}`);
});
test('a refused path returns 404 without calling the engine', async () => {
  process.env.ENGINE_BASE_URL = 'http://127.0.0.1:1'; process.env.ENGINE_API_KEY = 'k';
  const r = await engine('GET', 'dev/projects', 'o'.repeat(64));
  assert.equal(r.status, 404);
});
import { readdirSync, statSync, existsSync } from 'node:fs';
import { join } from 'node:path';
test('the public web routes are exactly this list; a new route must be added here on purpose', () => {
  const walk = (d: string, base = ''): string[] => readdirSync(d).flatMap(n => { const p = join(d, n), rel = base ? `${base}/${n}` : n; return statSync(p).isDirectory() ? walk(p, rel) : n === 'route.ts' ? [base] : []; });
  const found = walk('app/api').sort();
  const expected = ['demo/addendum/accept', 'demo/addendum/decline', 'demo/addendum/upload', 'demo/ai-findings', 'demo/ai-findings/decision', 'demo/bid-desk', 'demo/crew-plan/preview', 'demo/decision/crew-plan', 'demo/decision/ruleset', 'demo/decision/wage',
    'demo/documents', 'demo/documents/[id]', 'demo/export', 'demo/flight-recorder', 'demo/health', 'demo/labor/resolve', 'demo/portfolio', 'demo/release', 'demo/reset', 'demo/sample-addendum', 'demo/scope-draft', 'demo/scope/resolve', 'demo/state', 'demo/takeoff', 'demo/takeoff/review'].sort();
  assert.deepEqual(found, expected);
  assert.ok(existsSync('app/api/demo/bid-desk/route.ts'));
});
test('the UI pass adds no engine path: the Bid Desk and the export read GET projects/{id}, which was already allowed', () => {
  assert.ok(engineAllowed('GET', `projects/${P}`));
  assert.ok(!engineAllowed('POST', `projects/${P}/bid-desk`) && !engineAllowed('GET', `projects/${P}/export`));
});

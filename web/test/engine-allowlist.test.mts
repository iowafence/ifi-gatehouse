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

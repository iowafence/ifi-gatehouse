import test from 'node:test';
import assert from 'node:assert/strict';
import { clientIp, allow } from '../lib/limits.ts';
test('without CLIENT_IP_HEADER the first x-forwarded-for hop is used (previous behavior)', () => {
  delete process.env.CLIENT_IP_HEADER;
  assert.equal(clientIp(new Headers({ 'x-forwarded-for': '1.2.3.4, 10.0.0.1' })), '1.2.3.4');
  assert.equal(clientIp(new Headers()), 'local');
});
test('with CLIENT_IP_HEADER a forged x-forwarded-for is ignored', () => {
  process.env.CLIENT_IP_HEADER = 'fly-client-ip';
  assert.equal(clientIp(new Headers({ 'x-forwarded-for': '6.6.6.6', 'fly-client-ip': '203.0.113.9' })), '203.0.113.9');
  assert.equal(clientIp(new Headers({ 'x-forwarded-for': '6.6.6.6' })), 'unidentified', 'fails closed into one shared bucket, never trusts the forgeable header');
  delete process.env.CLIENT_IP_HEADER;
});
test('the fixed-window limiter refuses after the limit', () => {
  const k = 'k' + Math.random(); for (let i = 0; i < 3; i++) assert.equal(allow(k, 3, 1000), true); assert.equal(allow(k, 3, 1000), false);
});

test('CLIENT_IP_FROM_RIGHT takes the last x-forwarded-for entry, so a client-prepended value is ignored', () => {
  process.env.CLIENT_IP_HEADER = 'x-forwarded-for'; process.env.CLIENT_IP_FROM_RIGHT = '1';
  assert.equal(clientIp(new Headers({ 'x-forwarded-for': '6.6.6.6, 203.0.113.9' })), '203.0.113.9');
  assert.equal(clientIp(new Headers({ 'x-forwarded-for': '203.0.113.9' })), '203.0.113.9');
  assert.equal(clientIp(new Headers()), 'unidentified');
  delete process.env.CLIENT_IP_FROM_RIGHT; assert.equal(clientIp(new Headers({ 'x-forwarded-for': '6.6.6.6, 203.0.113.9' })), '6.6.6.6', 'default stays first-hop');
  delete process.env.CLIENT_IP_HEADER;
});
test('per-network limits default to the previous constants and are clamped, never disabled', async () => {
  const m = await import('../lib/limits.ts');
  delete process.env.IP_REQUESTS_PER_MIN; delete process.env.IP_MUTATIONS_PER_10MIN;
  assert.equal(m.ipRequestsPerMinute(), 300); assert.equal(m.ipMutationsPer10Min(), 120);
  process.env.IP_REQUESTS_PER_MIN = '0'; process.env.IP_MUTATIONS_PER_10MIN = '99999999';
  assert.equal(m.ipRequestsPerMinute(), 300, 'zero/garbage falls back to the default'); assert.equal(m.ipMutationsPer10Min(), 3000, 'upper clamp');
  process.env.IP_REQUESTS_PER_MIN = '1'; assert.equal(m.ipRequestsPerMinute(), 60, 'lower clamp: cannot be set below 60');
  delete process.env.IP_REQUESTS_PER_MIN; delete process.env.IP_MUTATIONS_PER_10MIN;
});

// ---- limiter regression (2026-10-14 production finding): behind a CDN + platform router the LAST X-Forwarded-For entry is a rotating proxy hop, not the visitor
const stream = (n: number, rotate: boolean) => Array.from({ length: n }, (_, i) => new Headers({ 'x-forwarded-for': `6.6.6.${i % 250}, 203.0.113.9, 198.51.100.${rotate ? (i * 37) % 250 + 1 : 7}` }));
const admitted = (hs: Headers[], limit: number, key = 'new') => { const bucket = 'b' + Math.random(); let ok = 0; for (const h of hs) if (allow(`${bucket}:${key}:${clientIp(h)}`, limit, 60_000)) ok++; return ok; };
test('REPRODUCTION: FROM_RIGHT=1 with a rotating proxy hop as the last entry lets every request into a fresh bucket (limit never reached)', () => {
  process.env.CLIENT_IP_HEADER = 'x-forwarded-for'; process.env.CLIENT_IP_FROM_RIGHT = '1';
  assert.equal(admitted(stream(150, true), 120), 150, 'observed in production: 150 of 150 admitted against a limit of 120');
  assert.equal(admitted(stream(150, false), 120), 120, 'with a stable last entry the limit holds (what local tests had shown)');
  delete process.env.CLIENT_IP_HEADER; delete process.env.CLIENT_IP_FROM_RIGHT;
});
test('FROM_RIGHT=2 keys on the visitor entry: the limit holds despite a rotating proxy hop and a forged client-prepended prefix', () => {
  process.env.CLIENT_IP_HEADER = 'x-forwarded-for'; process.env.CLIENT_IP_FROM_RIGHT = '2';
  assert.equal(clientIp(new Headers({ 'x-forwarded-for': '6.6.6.6, 203.0.113.9, 198.51.100.77' })), '203.0.113.9');
  assert.equal(admitted(stream(150, true), 120), 120); assert.equal(admitted(stream(150, false), 120), 120);
  delete process.env.CLIENT_IP_HEADER; delete process.env.CLIENT_IP_FROM_RIGHT;
});
test('CLIENT_IP_FROM_RIGHT fails CLOSED: too few entries or an invalid value never falls back to the client-controlled first entry', () => {
  process.env.CLIENT_IP_HEADER = 'x-forwarded-for'; const h = new Headers({ 'x-forwarded-for': '6.6.6.6, 203.0.113.9' });
  for (const v of ['3', '0', '10', 'abc', '-1', '1.5']) { process.env.CLIENT_IP_FROM_RIGHT = v; assert.equal(clientIp(h), 'unidentified', `value ${v}`); }
  process.env.CLIENT_IP_FROM_RIGHT = '2'; assert.equal(clientIp(h), '6.6.6.6'); assert.equal(clientIp(new Headers({ 'x-forwarded-for': '203.0.113.9' })), 'unidentified', 'one entry cannot satisfy N=2');
  delete process.env.CLIENT_IP_HEADER; delete process.env.CLIENT_IP_FROM_RIGHT;
});
test('the GLOBAL new-session guard bounds new sessions even when per-IP attribution fails completely', async () => {
  const m = await import('../lib/limits.ts'); delete process.env.NEW_DEMOS_GLOBAL_PER_HOUR; assert.equal(m.newDemosGlobalPerHour(), 300);
  process.env.NEW_DEMOS_GLOBAL_PER_HOUR = '1'; assert.equal(m.newDemosGlobalPerHour(), 10, 'lower clamp'); process.env.NEW_DEMOS_GLOBAL_PER_HOUR = '999999'; assert.equal(m.newDemosGlobalPerHour(), 5000, 'upper clamp'); process.env.NEW_DEMOS_GLOBAL_PER_HOUR = 'x'; assert.equal(m.newDemosGlobalPerHour(), 300);
  process.env.CLIENT_IP_HEADER = 'x-forwarded-for'; process.env.CLIENT_IP_FROM_RIGHT = '1'; const g = 'g' + Math.random(); let ok = 0;
  for (const h of stream(500, true)) if (allow(`b${g}:new:${clientIp(h)}`, 120, 60_000) && allow(`${g}:global`, 300, 60_000)) ok++;
  assert.equal(ok, 300, 'per-IP buckets all pass (attribution failed) but the global guard stops at 300, below the 500-project cap');
  delete process.env.NEW_DEMOS_GLOBAL_PER_HOUR; delete process.env.CLIENT_IP_HEADER; delete process.env.CLIENT_IP_FROM_RIGHT;
});
test('the opt-in shape log is off by default, bounded to 30 lines, and never prints a raw address', async () => {
  const m = await import('../lib/limits.ts'); const lines: string[] = []; const orig = console.log; console.log = (...a: unknown[]) => { lines.push(a.join(' ')); };
  const h = new Headers({ 'x-forwarded-for': '6.6.6.6, 203.0.113.9, 198.51.100.77', 'cf-connecting-ip': '203.0.113.9' });
  try { delete process.env.CLIENT_IP_LOG_SHAPE; m.logIpShape(h); assert.equal(lines.length, 0, 'off by default'); process.env.CLIENT_IP_LOG_SHAPE = '1'; for (let i = 0; i < 50; i++) m.logIpShape(h); }
  finally { console.log = orig; delete process.env.CLIENT_IP_LOG_SHAPE; }
  assert.equal(lines.length, 30, 'bounded'); const all = lines.join('\n'); assert.ok(!/203\.0\.113\.9|198\.51\.100\.77|6\.6\.6\.6/.test(all), 'no raw address in the log');
  const j = JSON.parse(lines[0].replace('[client-ip-shape] ', '')); assert.equal(j.xff_entries, 3); assert.equal(j.cf_connecting_ip_present, true); assert.equal(j.tail_hashes_right_to_left.length, 3);
  assert.equal(j.cf_hash, j.tail_hashes_right_to_left[1], 'cf-connecting-ip equals the 2nd-from-right entry, detectable by hash without exposing it');
});

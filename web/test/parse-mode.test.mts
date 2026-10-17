// Mode-aware copy: keyed on the parse mode the stack is configured for and the mode the engine recorded per upload, never on an invented flag. Run: npm run test:flight
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { configuredParseMode, headerModeClause, aiFindingsCallNote, uploadPanelNote, heldParseLine, heldReasonIsOwn, parseModeLabel, UPLOAD_RECEIVED } from '../lib/parse-mode.ts';

test('the configured mode is the engine\'s own ENGINE_ADDENDUM_MODE mapping: recorded, reconstructed, else (unset) live', () => {
  assert.equal(configuredParseMode('recorded'), 'RECORDED'); assert.equal(configuredParseMode('reconstructed'), 'RECONSTRUCTED');
  assert.equal(configuredParseMode(undefined), 'LIVE'); assert.equal(configuredParseMode('live'), 'LIVE');
  const api = readFileSync(new URL('../../api/server.py', import.meta.url), 'utf8'); assert.match(api, /"recorded": ai\.recorded_parser, "reconstructed": ai\.reconstructed_parser\}\.get\(os\.environ\.get\("ENGINE_ADDENDUM_MODE"\), ai\.live_parser\)/);
});
test('recorded mode keeps today\'s wording exactly', () => {
  assert.equal(headerModeClause('RECORDED'), 'replayed offline (no live inference)');
  assert.equal(aiFindingsCallNote('RECORDED'), 'No AMD call is made by this build (live calls are on hold).');
  assert.equal(uploadPanelNote('RECORDED', null), 'Hosted demo replays a recorded capture of a live AMD parse; other files are held as parse unavailable.');
  assert.equal(uploadPanelNote('RECORDED', { filename: 'x.pdf', status: 'HELD_PARSE_UNAVAILABLE', parse: { mode: 'LIVE' } }), uploadPanelNote('RECORDED', null));      // an upload does not rewrite the hosted note
  assert.equal(heldParseLine('no verified capture exists for this document, so there is nothing to replay (RECORDED mode never substitutes a reconstruction)'), 'Held: parse unavailable. This hosted demo has no recorded parse for this file, so nothing was proposed and the scope is unchanged.');
});
test('live-enabled mode never says live is off: a live parse runs for an authorized hash and is labelled LIVE', () => {
  for (const t of [headerModeClause('LIVE'), aiFindingsCallNote('LIVE'), uploadPanelNote('LIVE', null)]) { assert.match(t, /live AMD parse runs/); assert.match(t, /SHA-256 is authorized|whose SHA-256 is authorized/); assert.match(t, /labelled LIVE/); assert.doesNotMatch(t, /no live inference|live calls are on hold|No AMD call is made by this build|hosted demo replays/i); }
});
test('after an upload the panel states exactly what that upload did', () => {
  assert.match(uploadPanelNote('LIVE', { filename: 'ADDENDUM_02.pdf', status: 'PROPOSED', parse: { mode: 'LIVE' } }), /^Last upload \(ADDENDUM_02\.pdf\): LIVE model call\./);
  assert.match(uploadPanelNote('LIVE', { filename: 'a.pdf', status: 'PROPOSED', parse: { mode: 'RECORDED' } }), /^Last upload \(a\.pdf\): RECORDED replay \(no new model call\)\./);
  assert.match(uploadPanelNote('LIVE', { filename: 'b.pdf', status: 'HELD_PARSE_UNAVAILABLE', message: 'live parse is authorized for Addendum 02 only: this document\'s SHA-256 is not on the authorized list', parse: { mode: 'NOT_REPORTED' } }), /^Last upload \(b\.pdf\): no parse ran \(live parse is authorized for Addendum 02 only/);
  assert.match(uploadPanelNote('LIVE', { filename: 'c.pdf', status: 'PROCESSING', parse: null }), /still being read/);
  for (const m of ['LIVE', 'RECORDED', 'RECONSTRUCTED', 'SIMULATED']) assert.ok(parseModeLabel(m) !== 'Parse mode not reported');
});
test('held status line: the engine\'s own reason comes first; "no recorded parse for this file" only when that is the reason', () => {
  const live = heldParseLine('live parse is authorized for Addendum 02 only: this document\'s SHA-256 is not on the authorized list');
  assert.match(live, /^Held: live parse is authorized for Addendum 02 only/); assert.doesNotMatch(live, /no recorded parse/);
  for (const m of ['the live-call budget (3) is used up; no further live call is authorized', 'the model call failed (HTTP 503); no retry was made', 'live parse is not authorized: there is no ledger/authorization file (ledger.json in the live-captures directory)']) { const l = heldParseLine(m); assert.ok(l.startsWith(`Held: ${m}`)); assert.doesNotMatch(l, /no recorded parse/); assert.ok(heldReasonIsOwn(m)); }
  assert.ok(!heldReasonIsOwn('no verified capture exists for this document, so there is nothing to replay'));
});
test('upload message says "Upload received." and no longer "Recorded."', () => {
  assert.equal(UPLOAD_RECEIVED, 'Upload received.');
  const src = readFileSync(new URL('../app/components/addendum.tsx', import.meta.url), 'utf8');
  assert.ok(src.includes('setMsg(`${UPLOAD_RECEIVED} SHA-256')); assert.ok(!src.includes('`Recorded. SHA-256'));
});

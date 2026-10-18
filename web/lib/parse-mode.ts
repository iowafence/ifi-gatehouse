// Mode-aware copy. The mode is never a flag of our own: before an upload it is the parse mode the stack is configured for (the same ENGINE_ADDENDUM_MODE the engine reads;
// unset means the engine's default, the live parser), and after an upload it is the parse mode the engine recorded on that upload (LIVE / RECORDED / RECONSTRUCTED / SIMULATED).
// Pure: no I/O, so the server and the browser share it and tests can exercise every mode.
export type ConfiguredMode = 'RECORDED' | 'RECONSTRUCTED' | 'LIVE';

/** Same mapping as api/server.py: recorded and reconstructed are named; anything else (including unset) is the live parser. */
export function configuredParseMode(env: string | undefined = process.env.ENGINE_ADDENDUM_MODE): ConfiguredMode {
  return env === 'recorded' ? 'RECORDED' : env === 'reconstructed' ? 'RECONSTRUCTED' : 'LIVE';
}

/** What the engine recorded for one upload's parse, in words. Unchanged wording from the original panel. */
export function parseModeLabel(mode: string | undefined): string {
  return mode === 'RECORDED' ? 'RECORDED replay (no new model call)' : mode === 'LIVE' ? 'LIVE model call'
    : mode === 'RECONSTRUCTED' ? 'RECONSTRUCTED from the logged record (not a recording, not a live call)' : mode === 'SIMULATED' ? 'SIMULATED (test fixture, no model call)' : 'Parse mode not reported';
}

export const UPLOAD_RECEIVED = 'Upload received.';

type Upload = { filename?: string; status?: string; message?: string | null; parse?: { mode?: string } | null };

/** The static note under the addendum uploader. Recorded keeps its wording; live-enabled says what a live run does until an upload exists, then states exactly what the last upload did. */
export function uploadPanelNote(mode: ConfiguredMode, last: Upload | null): string {
  if (mode === 'RECORDED') return 'Hosted demo replays a recorded capture of a live AMD parse; other files are held as parse unavailable.';
  if (mode === 'RECONSTRUCTED') return 'This build replays a reconstruction rebuilt from the logged record (not a recording, not a live call); other files are held as parse unavailable.';
  if (!last) return 'A live AMD parse runs for a file whose SHA-256 is authorized, and the result is labelled LIVE. Any other file is held as parse unavailable.';
  const did = last.parse?.mode && last.parse.mode !== 'NOT_REPORTED' ? parseModeLabel(last.parse.mode) : last.status === 'PROCESSING' ? 'still being read' : `no parse ran${last.message ? ` (${last.message})` : ''}`;
  return `Last upload (${last.filename ?? 'file'}): ${did}. A live AMD parse runs only for a file whose SHA-256 is authorized, and the result is labelled LIVE.`;
}

/** The AI findings sentence about model calls. */
export function aiFindingsCallNote(mode: ConfiguredMode): string {
  return mode === 'LIVE'
    ? 'These findings are stored outputs; viewing them makes no AMD call. A live AMD parse runs only when an addendum file whose SHA-256 is authorized is uploaded, and its result is labelled LIVE.'
    : mode === 'RECORDED' ? 'No AMD call is made by this build to parse an addendum. A live AMD parse runs on the local stack for an authorized addendum file; this hosted build replays a recording of one.'
    : 'No AMD call is made by this build to parse an addendum (live calls are on hold).';
}

/** The sentence in the page header about where AI Findings come from. */
export function headerModeClause(mode: ConfiguredMode): string {
  return mode === 'LIVE'
    ? 'replayed offline; a live AMD parse runs only for an addendum file whose SHA-256 is authorized, and its result is labelled LIVE'
    : 'replayed offline (no live Addendum parse)';
}

const NO_CAPTURE = /^no verified capture exists/;
/** The held-parse status line: the engine's actual reason first; "no recorded parse for this file" only when that is the reason. */
export function heldParseLine(message: string | null | undefined): string {
  if (!message || NO_CAPTURE.test(message)) return 'Held: parse unavailable. This hosted demo has no recorded parse for this file, so nothing was proposed and the scope is unchanged.';
  return `Held: ${message.replace(/[.\s]+$/, '')}. Nothing was proposed and the scope is unchanged.`;
}
export const heldReasonIsOwn = (message: string | null | undefined): boolean => !!message && !NO_CAPTURE.test(message);

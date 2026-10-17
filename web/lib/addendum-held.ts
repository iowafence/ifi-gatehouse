// Why a HELD addendum was held, said accurately. The engine holds the whole parse with a fixed "cited excerpt(s) are not on the cited page" text whenever ANY row is rejected,
// but a row rejected as PATH_NOT_OPEN_SLOT means a person already answered that fact. Display only: the engine's message, the stored result and every hash input are untouched.
export type Rejected = { path: string; page?: number; reason?: string; code?: string };
const FIELD: Record<string, string> = { post_od_in: 'post OD', diameter_in: 'diameter', depth_in: 'depth' };

/** A short fact name for a path, e.g. "G3 width", "post OD", "diameter", "depth". Unknown paths fall back to the path itself. */
export function factName(path: string): string {
  let m = /^\/gates\/(\d+)\/clear_width_ft$/.exec(path); if (m) return `G${Number(m[1]) + 1} width`;
  m = /^\/footing_scope\/classes\/GATE_(G\d+)\/(post_od_in|diameter_in|depth_in)$/.exec(path); if (m) return m[1] === 'G3' ? FIELD[m[2]] : `${m[1]} ${FIELD[m[2]]}`;
  return path;
}
export type HeldView = { kind: 'answered'; headline: string; facts: string[] } | { kind: 'engine' };

/** `answered` only when there are rejected rows and EVERY one is PATH_NOT_OPEN_SLOT. A mix, or any QUOTE_NOT_ON_PAGE (or any other code), keeps the engine's text. */
export function heldView(status: string, rejected: Rejected[] | null | undefined): HeldView {
  const rows = rejected || [];
  if (status !== 'HELD_UNVERIFIED_EVIDENCE' || !rows.length || !rows.every(r => r?.code === 'PATH_NOT_OPEN_SLOT')) return { kind: 'engine' };
  const facts = [...new Set(rows.map(r => factName(String(r.path))))];
  return { kind: 'answered', facts, headline: `This addendum was held because a person already answered facts it covers (${facts.join(', ')}). The addendum cannot overwrite a human answer. Use Reset demo, then upload the addendum before typing values.` };
}

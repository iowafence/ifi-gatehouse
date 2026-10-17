// The engine's own notes on open facts (served with the scope draft), arranged for the exception panel: the selected exception's note, and the notes carried by the
// other exceptions of the same gate/class. Pure. Nothing is composed or matched on wording: relatedness is the shared parent path, order is the field order below.
export type NoteLine = { field: string; path: string; note: string };
const ORDER = ['post_od_in', 'diameter_in', 'depth_in', 'clear_width_ft'];
const parent = (p: string) => p.slice(0, p.lastIndexOf('/'));
const field = (p: string) => p.slice(p.lastIndexOf('/') + 1);

export function notesFor(notes: Record<string, string> | undefined | null, paths: string[] | undefined): { own: string | undefined; related: NoteLine[] } {
  const all = notes || {}; const sel = (paths || []).find(p => all[p]) ?? (paths || [])[0];
  const own = sel ? all[sel] : undefined;
  const scope = (paths || []).map(parent);
  const related = Object.entries(all).filter(([p, n]) => n && p !== sel && scope.includes(parent(p)))
    .map(([path, note]) => ({ field: field(path), path, note }))
    .sort((a, b) => (ORDER.indexOf(a.field) === -1 ? 99 : ORDER.indexOf(a.field)) - (ORDER.indexOf(b.field) === -1 ? 99 : ORDER.indexOf(b.field)) || a.path.localeCompare(b.path));
  return { own, related };
}

/** The label over the typed-value box. A missing value with no document-derived option is the estimator's own assumption; an inferred value keeps the original wording, where it is accurate. */
export function valueFieldLabel(ex: { code?: string; options?: unknown[] } | undefined): string {
  return ex?.code === 'MISSING_VALUE' && !(ex.options || []).length ? 'Your value (self-declared assumption)' : 'Documented value (human-entered)';
}

/** A geometry-invalid exception is a dead end for typing: a typed run length is what made the layout disagree, and the engine cannot re-take it here. Keyed on the exception kind (code). */
export const isDeadEndException = (ex: { code?: string } | undefined): boolean => ex?.code === 'GEOMETRY_INVALID';
export const DEAD_END_TEXT = 'The run length and the layout sides must describe the same fence. A typed run length made them disagree and this cannot be re-entered here. Use Reset demo to start over.';

/** The engine refused a scope decision because the path is not a resolvable fact, or no exception is open for it. Keyed on the 409 and its own words, never on a kind list. */
export const isNonResolvable409 = (status: number, message: string | undefined): boolean => status === 409 && /not a resolvable fact|no open exception/i.test(String(message || ''));

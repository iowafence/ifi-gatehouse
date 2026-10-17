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

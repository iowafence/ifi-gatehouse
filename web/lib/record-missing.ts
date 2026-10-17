// What is missing before a record button can be used. ONE computation per button: it sets the button's disabled state and says why beside it, so the two cannot diverge. Display only.
export function attestMissing(i: { by: string; note: string; busy: boolean }): { missing: ('name' | 'note')[]; disabled: boolean; text: string } {
  const missing: ('name' | 'note')[] = []; if (!i.by.trim()) missing.push('name'); if (!i.note.trim()) missing.push('note');
  const text = missing.length === 2 ? 'Enter your name and a review note to record.' : missing[0] === 'name' ? 'Enter your name to record.' : missing[0] === 'note' ? 'Enter a review note to record.' : '';
  return { missing, disabled: i.busy || missing.length > 0, text };
}

export type G3Missing = 'name' | 'source' | 'bid' | 'value';
export function g3RecordMissing(i: { by: string; source: string; hasBid: boolean; vals: Record<string, string>; busy: boolean }): { missing: G3Missing[]; disabled: boolean; text: string } {
  const missing: G3Missing[] = [];
  if (!i.by.trim()) missing.push('name');
  if (i.source.trim().length < 10) missing.push('source');
  if (!i.hasBid) missing.push('bid');
  if (!Object.values(i.vals).some(x => x.trim())) missing.push('value');
  const label: Record<G3Missing, string> = { name: 'your name', source: 'a source note (at least 10 characters)', bid: 'a bid option (choose it at the Scope gate)', value: 'at least one value' };
  return { missing, disabled: i.busy || missing.length > 0, text: missing.length ? `To record, still needed: ${missing.map(m => label[m]).join('; ')}.` : '' };
}

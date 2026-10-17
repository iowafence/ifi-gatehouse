// Why release is waiting. ONE computation, used both to disable the Release button and to list what is open beside it, so the two cannot diverge.
// Display only: the engine (and the web release route) stay the source of truth. The takeoff item does not disable the button (the route refuses a release without a
// current Takeoff Review and says so in an error elsewhere on the page); it is listed here so the reason sits next to the button.
export type WaitAction = 'open-takeoff' | 'focus-ack' | 'focus-name';
export type WaitItem = { id: 'engine' | 'takeoff' | 'ack' | 'name'; text: string; action?: WaitAction; actionLabel?: string; disables: boolean };
export type WaitInput = { status: string; hasDigest: boolean; tg: { attestation?: { current?: boolean } | null; release_hard_blockers?: unknown[] } | null; ackQual: boolean; approver: string; busy: boolean };

export function releaseWaiting(i: WaitInput): { items: WaitItem[]; disabled: boolean; released: boolean } {
  const released = i.status === 'released';
  const releaseReady = i.status === 'ready_for_final_review' && i.hasDigest;
  const items: WaitItem[] = [];
  if (!releaseReady) items.push({ id: 'engine', disables: true, text: i.status === 'ready_for_final_review' ? 'The engine has not issued a proposal digest yet.' : `The engine has not reached final review (status: ${i.status.replace(/_/g, ' ')}). Finish the earlier gates first.` });
  if (i.tg && !released) {
    const a = i.tg.attestation;
    if (!a) items.push({ id: 'takeoff', disables: false, action: 'open-takeoff', actionLabel: 'Open Takeoff Review', text: 'A Takeoff Review has not been recorded for this scope version.' });
    else if (!a.current) items.push({ id: 'takeoff', disables: false, action: 'open-takeoff', actionLabel: 'Open Takeoff Review', text: 'The Takeoff Review is stale: the takeoff changed after it was reviewed. Record it again.' });
    if (!i.ackQual) {
      const hard = (i.tg.release_hard_blockers || []).length > 0;
      items.push(hard ? { id: 'ack', disables: true, text: 'A hard block prevents the acknowledgement, so this release cannot be recorded.' }
        : { id: 'ack', disables: true, action: 'focus-ack', actionLabel: 'Go to the acknowledgement', text: 'Tick the acknowledgement of the qualifications (qualified demonstration release, not a bid).' });
    }
  }
  if (!i.approver.trim()) items.push({ id: 'name', disables: true, action: 'focus-name', actionLabel: 'Go to the name field', text: 'Enter your name (self-declared).' });
  return { items, released, disabled: i.busy || items.some(x => x.disables) };
}

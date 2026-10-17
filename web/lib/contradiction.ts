// How an AI finding that is classed CONTRADICTED_BY_DRAWING_EVIDENCE was contradicted, from its stored verification verdict (never hardcoded per finding): by the frozen
// vector-geometry oracle at the time ("formal"), or only by a later reading of the PDF's vector objects that was not pre-registered ("retrospective"). Pure; shared by the server and the browser.
/* eslint-disable @typescript-eslint/no-explicit-any */
export type ContradictionKind = 'formal' | 'retrospective' | 'other';
export const RETRO_CONTRADICTION = 'Contradicted by a retrospective vector-geometry reading; not formally verified at the time.';

export function contradictionKind(f: any): ContradictionKind | null {
  if (f?.classification !== 'CONTRADICTED_BY_DRAWING_EVIDENCE') return null;
  const v = f.verification?.verdict;
  return v === 'CONTRADICTED_BY_VECTOR_GEOMETRY' ? 'formal' : v === 'NOT_VERIFIABLE_FROM_PDF' ? 'retrospective' : 'other';
}
/** The sentence for the headline count, split by kind. Kinds with a zero count are omitted. */
export function contradictionCountText(findings: any[]): string[] {
  const n = (k: ContradictionKind) => findings.filter(f => contradictionKind(f) === k).length; const out: string[] = [];
  if (n('formal')) out.push(`${n('formal')} contradicted by vector geometry (formal check)`);
  if (n('retrospective')) out.push(`${n('retrospective')} contradicted by a retrospective reading (not formally verified)`);
  if (n('other')) out.push(`${n('other')} contradicted by the drawing`);
  return out;
}

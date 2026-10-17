// What the engine issued at release, for the "Release recorded" block. Display only. Null unless a release is recorded, so the block can never show before one.
/* eslint-disable @typescript-eslint/no-explicit-any */
export type ReleaseRecordView = { releaseClass: string; scopeVersion: string; digestShort: string; digestFull: string; crew: string; by: string; at: string };
const nr = (x: unknown) => x === null || x === undefined || x === '' ? 'not reported by the engine' : String(x);

export function releaseRecordView(project: any, tg: any | null): ReleaseRecordView | null {
  if (!project || String(project.status) !== 'released') return null;
  const rel = tg?.readiness?.release ?? null;
  const cls = rel?.release_class ?? tg?.readiness?.selected?.release_class ?? null;
  const digest = String(project.proposal_digest ?? rel?.proposal_digest ?? '');
  const pid = project.pricing?.crew_plan?.preferred_crew ?? null;
  const cname = pid ? (project.pricing?.crews?.crews || []).find((c: any) => c.crew_id === pid)?.name : null;
  return { releaseClass: nr(cls), scopeVersion: nr(project.scope_version ?? rel?.scope_version), digestShort: digest ? `${digest.slice(0, 12)}…${digest.slice(-6)}` : 'not reported by the engine', digestFull: digest,
    crew: pid ? `${cname ? cname + ' ' : ''}(${pid}) for the whole job` : 'not reported by the engine', by: nr(project.approved_by), at: nr(project.released_at ?? rel?.released_at) };
}

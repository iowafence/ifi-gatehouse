// RELEASE-PINNED audit manifest: the trust anchor for independent-audit records. It is compiled into the application release, lives OUTSIDE the mutable audit-data directory
// (GATEHOUSE_AUDIT_DIR / dp001/independent_audits) and is NEVER generated or updated when audits are loaded. Changing a pinned value is a code change to the release that a reviewer can see.
// What it authenticates: WHICH BYTES this release accepts as the audit of GH-RUN-e5bbcecef551, and WHICH dispositions that audit may carry.
// What it does not do: it is not a digital signature and does not prove who wrote the audit; whoever can alter the release can alter this file (see docs/HOSTING.md, "Independent audit records").
import type { AuditManifest } from './evolus-audit';

export const RELEASE_AUDIT_MANIFEST: AuditManifest = {
  schema: 'gatehouse-audit-release-manifest.v1',
  release: 'gatehouse-judge-demo / hosting-candidate 2026-10-14 (audit correction 2)',
  runs: [{
    run_id: 'GH-RUN-e5bbcecef551',
    run_sha256: '7a4cc958f821f18ce4679a6fee428148c91c39de6ce9eaa3e27c50725fef70c4',
    trace_id: 'GH-TRACE-06b4b6d525133f8a',
    trace_sha256: '5aa339ec1bf7022ba98b505ba4ae6776c47aa9605870df24286ed21c0fe9bef8',
    execution_id: 'a161a9f6-0bc8-f111-bf5b-000d3aae6dc8',
    cases: {
      D1: { case_id: 'GH-CASE-5131630cf9d1', case_sha256: '6e4319bc30b9f45092515492b6a4c99996856dc750e49236c73da45021984701' },
      D2: { case_id: 'GH-CASE-b661ad38637b', case_sha256: '7f7f5001a90639eb4b2cb210462384bf146cfa60b8a444eb2ca98168f341ed7b' },
    },
    loom_report: { file: 'LOOM-GH-RUN-e5bbcecef551-remediation-recheck.md', sha256: 'd6040e169d374b03f3b8336f4d255d31fd892ee08bcb7b201d3273b26aeabf05' },
    audits: [
      { audit_id: 'AUDIT-GH-RUN-e5bbcecef551-1', file: 'AUDIT-GH-RUN-e5bbcecef551-1.json', sha256: '1e4f1c196cdaa91659d76eb8529e2a7bda489f5d8161247d8361d7f76387371b', status: 'SUPERSEDED' },
      { audit_id: 'AUDIT-GH-RUN-e5bbcecef551-2', file: 'AUDIT-GH-RUN-e5bbcecef551-2.json', sha256: 'b68748fecf9e9986ecceead9b428c5330471c59857ab88a7cedbd8b6f9f734b8', status: 'ACTIVE' },
    ],
    policy: {
      issues: {
        I1: { draft_id: 'D1', disposition: 'SUPPORTED' },
        I2: { draft_id: 'D2', disposition: 'FLAGGED_UNSUPPORTED_BY_CONTROLLING_EVIDENCE' },
        I3: { draft_id: null, disposition: 'SUPPORTED' },
      },
      cases: { D1: 'SUPPORTED', D2: 'FLAGGED_UNSUPPORTED_BY_CONTROLLING_EVIDENCE' },
      scope_findings: { G3_CLEAR_OPENING_WIDTH: 'UNRESOLVED', G3_POST_OD: 'UNRESOLVED', G3_FOOTING: 'SPECIFIED' },
      proposed_clarifications: ['PC-GH-RUN-e5bbcecef551-G3-POST-OD'],
    },
  }],
};

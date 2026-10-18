# Cleanup

Files removed from the public tree, by group, and why.

## G1 (7 files): internal release-readiness and hosting notes

Internal notes written during the build; superseded by docs/STATUS.md and the verification record. Several contained statements that are no longer true.

- `docs/hosting/FINAL_READINESS_2026-10-14.md`
- `docs/hosting/LIMITER_DIAGNOSIS_2026-10-14.md`
- `docs/hosting/LIVE_VERIFICATION_2026-10-14.md`
- `docs/hosting/RELEASE_CHECKLIST.md`
- `docs/hosting/RELEASE_READINESS.md`
- `docs/hosting/VERIFICATION.md`
- `docs/hosting/REPLIT_FEASIBILITY.md`

## G2 (4 files): demo-lock milestone reports

Internal milestone reports from Oct 13-14; superseded.

- `docs/milestones/GATEHOUSE_2026-10-13_DEMO_LOCK_REPORT.md`
- `docs/milestones/GATEHOUSE_2026-10-14_ARTIFACT_MANIFEST.md`
- `docs/milestones/GATEHOUSE_2026-10-14_DEMO_LOCK.md`
- `docs/milestones/GATEHOUSE_2026-10-14_STAGED_FILES.sha256`

## G3 (5 files): one-off verification and end-to-end probe scripts

Used during the build; not part of the product or CI. Their results are recorded in the verification record.

- `dp001/engine_vs_reference.py`
- `dp001/evidence_dump.py`
- `scripts/dp001_verification_run.py`
- `e2e/walk_to_release.py`
- `e2e/flicker_probe.py`

## G7 (4 files): local developer helpers

They need private environment files; the README quick start does not use them.

- `run/run_browser_suites.sh`
- `run/start_engine.sh`
- `run/start_engine_dp001.sh`
- `run/start_web.sh`

## G8 (1 file): plan for an AMD call

The call it planned has since been made, so its "no AMD request has been made" status is no longer true.

- `spatial_plan/LIVE_CALL_PLAN_003.md`

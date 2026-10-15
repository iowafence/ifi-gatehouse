# Status

Updated 2026-10-14. Everything runs on **fictional data**; nothing here is a bid or a price to rely on.

| Area | State |
|---|---|
| Repository layout, guardrails, CI | Secret and private-document scan, commit policy, link check, policy tests, engine and API tests, web typecheck and build, Docker build |
| Engine and API | Implemented: scope validation, guards, exception rules, takeoff, three-gate workflow, portfolio KPIs; HTTP service with isolated anonymous demo sessions |
| Pricing | Implemented: quantity rules (unapproved draft), footing schedule by class (`footing-scope.v1` / `footing-calc.v1` / `footing-schedule.v1`), crew plans, wage records, rate-book import with a fictional reference workbook. Reference totals are conditional (see README); `bid_ready` is false in every priced state |
| Web app | Implemented as a demonstration: project workspace, PDF evidence viewer, Takeoff Review, Scope / Labor / Release gates, AI Findings |
| AMD evidence | Implemented offline: stored model outputs are verified against the drawing and classified; a contradicted finding cannot be accepted. One authorized live spatial test (3 requests) is stored with hashes. No live inference in the demo. Real spatial understanding is **not** demonstrated |
| AI Flight Recorder | Implemented: expandable trace of AMD / Gemma / Evolus producer layers (from validated `gatehouse-flight-trace.v1` files) beside Gatehouse validation and human authorization; states LIVE / RECORDED / SIMULATED / FAILED / NOT_REPORTED; nothing estimated. Contract confirmed with the Evolus adapter side; no real Evolus run exists yet |
| Evolus | Agent instructions and a REST client with a mock mode (`evolus/`). Separately, an adapter ran two real Evolus workflow executions on 2026-10-14 (one failed HTTP 400, one completed); their traces, two pending-review RFI cases, the run record and independent LOOM audits are in `release_evidence/` and shown read-only in the AI Flight Recorder. The Evolus workspace was configured to use the AMD Token Factory (owner-stated, not confirmed by the execution record); the completed run's model is recorded only as configured Gemma-4-31B-IT, unverified, and per-execution model and AMD telemetry were not provided. Eligibility for the Evolus track's own-vLLM requirement is unresolved and not claimed |
| Gemma / other models | Not implemented |
| Intake | ZIP inventory and optional PDF page index; not wired into the demo |
| Persistence | None: state is in memory |
| Authentication | None: names at the gates are self-declared |
| Hosted deployment | Public synthetic demo on Render (one Standard instance, no disk) from a private container image; see `docs/HOSTING.md` and `docs/hosting/` |
| License | MIT |

Automated checks: backend suite through `harness/run_safe_suite.py`, repository policy tests, AMD bridge and spatial-plan tests, browser suites (Playwright), web typecheck and build. They do not test live model behavior.

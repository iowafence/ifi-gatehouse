# Gatehouse judge demo: release checklist (2026-10-14)

**Nothing here has been executed against a hosting provider. Do not deploy, push or publish until the owner separately authorizes each step.** Provider UI labels and behaviors below are from the provider documents read earlier (`REPLIT_FEASIBILITY.md`) and are **unverified**; confirm them on screen. Each step is marked LOCAL (run here, safe), OWNER (needs the owner's account, money or approval) or POST (after authorization).

## A. Decisions and credentials (minimum to publish)
| # | Need | Who | Why |
|---|---|---|---|
| A1 | Organizer confirmation that Render (not on their suggested list) is acceptable; otherwise choose Replit | OWNER | event rules |
| A2 | Hosting account (Render), payment method, Standard plan (~$25/month; recheck price) | OWNER | I should not hold these credentials |
| A3 | Repository access for the host: either the public GitHub repo (after A6) or a private repo connected by the owner, or an image uploaded by the owner | OWNER | the host builds `hosting/Dockerfile` |
| A4 | Access mode: open, or platform password during judging | OWNER | public mutation routes are anonymous (readiness report S5) |
| A5 | Event limits approval: `NEW_DEMOS_PER_HOUR=120`, `IP_REQUESTS_PER_MIN=900`, `IP_MUTATIONS_PER_10MIN=400` | OWNER | defaults throttle a venue IP |
| A6 | Public GitHub: push `hosting/judge-demo` and/or merge to `main`; approval to publish the authentic Evolus evidence and LOOM reports | OWNER | not authorized now |
| A7 | URL / domain choice and DNS control if custom | OWNER | |
| A8 | Approval of the known-limitations wording (A9) | OWNER | honesty in the entry |
| A9 | Disclosures to include: names are self-declared; state is in memory and lost on restart; npm advisories (Next 15, PostCSS build-time) not fixed; no load test; Google Fonts CDN; synthetic data only; the AI results are stored authentic Evolus runs, not live calls | OWNER | |
No Evolus, AMD or other API credential is needed or should be provided: the release makes no outbound call.

## B. Pre-deployment gates (LOCAL, repeatable)
1. `git status` clean on `hosting/judge-demo`; note the commit id to deploy. The authentic evidence staged in `release_evidence/` must be committed (the host builds from the repository, so untracked files are not deployed).
2. `hosting/stage_release_evidence.py` (idempotent; refuses on any hash mismatch) then `(cd release_evidence && sha256sum -c SHA256SUMS)`.
3. `docker build -f hosting/Dockerfile -t gatehouse-judge-demo .`
4. `hosting/verify_release.sh 18250`: no-mount run; baked evidence hashes, audit/manifest inputs, read-only evidence, 0 mounts, non-root. Must print `RELEASE CONFIG VERIFIED`.
5. `cd web && npx tsc --noEmit && npm run test:flight` (48 expected), then the browser suites listed in section H against that container.
6. Confirm the frozen demo (5071) and accepted build (5051) still answer 200 and were not edited.
7. Re-scan for secrets and local paths in the diff to be published (commands in the readiness report S1–S4).

## C. Deployment sequence (Render; POST, owner-authorized)
1. OWNER creates the Render account and a **Web Service** from the repository, **Runtime: Docker**, Dockerfile path `hosting/Dockerfile`, build context repository root.
2. Plan **Standard**; **instances exactly 1**; autoscaling off; no scale-to-zero. **Auto-deploy off** so a stray push cannot restart the demo mid-judging.
3. Health check path `/api/demo/health`.
4. Environment: `CLIENT_IP_HEADER` and `CLIENT_IP_FROM_RIGHT` per Render's documented proxy header (**confirm**; the readiness report proposes `x-forwarded-for` with from-right, unverified on Render), the three event limits (A5). Optional secrets `SESSION_SIGNING_SECRET`, `ENGINE_API_KEY` (random per start otherwise). **Do not set** `GATEHOUSE_AUDIT_DIR`, `GATEHOUSE_RELEASE_DIR`, `FLIGHT_TRACE_DIR`, `GATEHOUSE_CASES_DIR`, or add a disk or mount over `/app/traces` or `/app/cases`.
5. Deploy to the platform URL first (staging use). Do not announce it.
6. Post-deploy verification against the HTTPS URL (all read-only, no Evolus or AMD call): `curl <url>/api/demo/health` returns `{"engine":"responsive"}`; response headers (HSTS present? if not, record it); probes `/.env`, `/traces`, `/cases`, `/dp001/...` return 404; `DEMO_URL=<url> e2e_evolus_cases.py` passes (6 groups); `e2e_dp001.py` passes; open the recorder in a real browser once (D1 shortlist, D2 flagged, G3 panel, four-part labels).
7. Time the first load after a cold start; record it.
8. A small scripted load test with owner approval (e.g. 20 concurrent judge walk-throughs); record memory and error rate. Not yet run.
9. Freeze: record the deployed commit id and image digest in `docs/hosting/RELEASE_RECORD.md` (new file, local). Tag only with owner approval.

## D. HTTPS, judge access, health and recovery
- HTTPS and certificate: provided by the platform. Cookies are `Secure; HttpOnly; SameSite=lax` and need the HTTPS URL.
- Judge access: the URL, optionally a platform password; a one-page "how to try it" (the DEMO_ROUTE_V2 flow, not rehearsed) and the known-limitations notes.
- Health: `/api/demo/health` (no session needed); the container exits if either process dies, so the platform restarts it.
- Recovery: a restart drops every in-progress judge project by design (judges can reset; state is not persisted). Evidence is baked into the image and cannot be damaged at runtime. After any restart re-run the post-deploy checks in C6. Keep the platform logs open during judging; the app prints no secrets.
- Monitoring: an external uptime check on the health URL (owner choice; free tools exist; not set up).
- Do not redeploy during judging: it resets everyone.

## E. Public GitHub release timing
Recommended order (all OWNER-authorized): (1) staging deploy passes C6–C8; (2) scrub optional items S2/S3 if desired; (3) push `hosting/judge-demo` and open a PR or merge to `main`; (4) rebuild from the public commit and redeploy once (so the URL and repository match) and rerun C6; (5) only then put the URL and repository link in the submission. Nothing is pushed now; `main` is `5bf7dec`, the branch is ~10 commits ahead, and `release_evidence/` plus the LOOM reports would become public (A6).

## F. Submission assets (OWNER; none made here)
| Asset | Status |
|---|---|
| Video | the 150-second MP4 and script exist (original walkthrough); **a version covering the Flight Recorder route has not been recorded**; `demo/DEMO_ROUTE_V2.md` proposes it, timing **not rehearsed** |
| Slides | not made |
| Cover image | not made (screenshots exist in `evidence/screenshots/` and the session scratchpad) |
| Written entry | not written; use the limitations in A9 and the provenance wording ("stored authentic Evolus execution; audit by LOOM; human authorization none recorded") |
Do not claim: that the AI ran live during judging, that an RFI was approved or sent, that names are authenticated, that the pin proves LOOM wrote the audit, that Gemma or AMD telemetry exists for the Evolus runs, or that the app is load-tested.

## G. Rollback
- **Before public announcement:** in Render, redeploy the previous successful deploy, or suspend the service. State is not persisted, so there is nothing to restore.
- **After announcement:** redeploy the last verified commit (record it in RELEASE_RECORD). Judges lose in-progress projects. Keep the previous image digest.
- **Evidence problem suspected:** do not edit files in place. Rebuild from the tagged commit and rerun B4 and C6; compare `RELEASE_SHA256SUMS` and the manifest pins.
- **Emergency fallback (requires explicit owner approval, not recommended):** run the same image from this machine behind a tunnel. It exposes a personal machine, so it is a last resort.
- **Take-down:** suspend the Render service; the frozen local demo is unaffected.

## H. Test results (filled at the time of the run; see the readiness report for the final summary)
Results table is appended below by the verification run.

| Check (local, release image with NO host mounts, `hosting/verify_release.sh` and `NEW_DEMOS_PER_HOUR=120`) | Result |
|---|---|
| `hosting/verify_release.sh` | PASS: 8 baked files match `RELEASE_SHA256SUMS`; audits and pinned LOOM report match manifest; evidence read-only for uid 10001; 0 mounts |
| Web typecheck; Flight Recorder node tests (`npm run test:flight`) | clean; 48 of 48 pass |
| Image build (includes `next build`) | pass |
| Browser: `e2e_evolus_cases` (authentic executions, audit, cases) | PASS 6 step groups |
| Browser: `e2e_dp001` (DP-001 package to scope) | PASS 8 steps |
| Browser: `e2e_viewer_stability` (real PDFs) | PASS 11 checks |
| Browser: `e2e_footing` (frozen calculation), `e2e_takeoff`, `e2e_ai_bridge` | PASS 18, 7 and 14 groups on the same image (first batch; footing re-run on the event-limit container was still in progress at writing) |
| Backend safe suite (run from a `git archive` snapshot) | 565 run, 560 passed, 0 failed, 3 skipped (PyMuPDF), 2 errors that are artifacts of the snapshot having no `.git` |
| Repo policy tests in the real repo | 16 OK |
| Note | the default new-session limit (12/hour per IP) returned HTTP 429 after many test sessions: the limiter works and the venue value must be raised (A5) |
| Not run | load test; real HTTPS; HSTS and proxy-header behavior; `e2e_pass6` (needs the generic engine) |

# Gatehouse judge demo: release readiness report (2026-10-14)

Local documentation only. **Nothing is deployed, pushed, published or provisioned.** "Verified" means run locally on this machine in Docker; anything about a hosting provider's behavior is **not verified** (no account, no deployment).

Frozen on LOOM's final PASS (`LOOM-GH-RUN-e5bbcecef551-9b0a22f-spotcheck.md`, sha256 `c18af41e…79aaa`): the Flight Recorder evidence, audit machinery, presentation behavior and original execution records. This work changed none of them (see section 7).

## 1. Assessment
**READY for an owner-authorized deployment, with the decisions in section 10 outstanding. Not deployed. Not a publication approval.**
The packaging gap found here (the image carried no execution evidence, because traces and cases only arrived through host mounts, which a hosting platform does not provide) is closed: the evidence is now baked in read-only and verified.

## 2. Inventory (what runs)
One container, one instance, two processes:
| Component | Role | Listens | Exposed? |
|---|---|---|---|
| Python engine (`run/start_engine_dp001.py`, stdlib HTTP, in-memory state) | all projects, decisions, audit trail, deterministic pricing | `127.0.0.1:8099` inside the container | **No** (loopback only; verified) |
| Next.js 15 web tier (`next start`) | UI, session cookies, proxy to the engine, read-only Flight Recorder reader | `0.0.0.0:$PORT` (default 8080) | **Yes, the only port** |
Runtime: Node 22 and Python 3.12 (`node:22-slim` builder, `python:3.12-slim` runtime), non-root uid 10001, read-only root filesystem, all capabilities dropped. Image 1.34 GB (full `node_modules` because `next.config.ts` needs TypeScript at runtime; slimming is optional and untested). Measured earlier: about 136 MiB idle for the whole stack.
No database, no queue, no object store, no outbound network call, no AMD or Evolus client or credential anywhere in the image.

### Environment variables
| Variable | Needed? | Notes |
|---|---|---|
| `PORT` | platform sets it | web port; default 8080 |
| `SESSION_SIGNING_SECRET`, `ENGINE_API_KEY` | optional | random per start if absent (sessions end on restart anyway); set as platform secrets only if stable sessions are wanted |
| `CLIENT_IP_HEADER`, `CLIENT_IP_FROM_RIGHT` | **set on a public host** | without them the limiter trusts a forgeable first `X-Forwarded-For` hop. Render value must be confirmed from Render's documentation (unverified here) |
| `NEW_DEMOS_PER_HOUR`, `IP_REQUESTS_PER_MIN`, `IP_MUTATIONS_PER_10MIN` | recommended for judging | defaults 12 / 300 / 120 per shared IP are too low for a venue; event values proposed in `REPLIT_FEASIBILITY.md` section 5 (reasoned, not load-tested) |
| `DEMO_MAX_PROJECTS`, `DEMO_TTL_SECONDS` | optional | engine caps, defaults 1000 / 21600 |
| `FLIGHT_TRACE_DIR`, `GATEHOUSE_CASES_DIR`, `DP001_DIR` | already set in the image | `/app/traces`, `/app/cases`, `/app/dp001`; do not override in production |
| `GATEHOUSE_AUDIT_DIR`, `GATEHOUSE_RELEASE_DIR` | **do not set** | default to the baked, read-only locations; the audit manifest is compiled into the release regardless |
`ENGINE_API_KEY` and `SESSION_SIGNING_SECRET` are the only secrets, and both are generated at start, never printed or baked in (image environment inspected: no secret; the `GPG_KEY` entry is the public Python release fingerprint from the base image).

## 3. Recommended hosting approach
**Render, one Web Service (Standard, 2 GB / 1 CPU, about $25/month), "Deploy from a Dockerfile" (`hosting/Dockerfile`), exactly 1 instance, no autoscaling, health check path `/api/demo/health`, HTTPS and `*.onrender.com` URL provided by the platform.** Reasons: it runs the image we tested unchanged; evidence is baked in so no disk or mount is needed; the in-memory design requires exactly one always-on instance. Prior analysis and the Replit alternative (conditional, would need a non-container start script) are in `REPLIT_FEASIBILITY.md`.
Two cautions carried from that report: Render is not a platform the organizers name, so **confirm acceptance with them first** (Replit is the fallback); and any restart or redeploy drops every judge's in-progress project (state is in memory by design).
Not recommended: Vercel (in-memory authority state on a serverless host; see `HOSTING.md`).

## 4. What the release contains (checked against the built image)
| Required content | Where | Verified |
|---|---|---|
| DP-001 synthetic bid package (5 PDFs) | `/app/samples/public-demo/dp001` (via `dp001/documents` link) | PDFs present; document hashes match `dp001/document_registry.json` (checked by the recorder's registry bindings) |
| Frozen calculation and estimate behavior | engine and `pricing/` unchanged since the accepted build | the existing suites below pass against the release container |
| PDF/document presentation | web viewer + `/api/demo/documents/[id]` | viewer suites pass against the release container |
| Authentic Evolus successful and failed traces | `/app/traces` (2 files, baked, read-only) | sha256 equal to LOOM's reports |
| Two original pending RFI cases + the run record | `/app/cases` (3 files, baked, read-only) | sha256 equal to LOOM's reports |
| Corrective audits | `/app/dp001/independent_audits` (-1 superseded, -2 active) | sha256 equal to the manifest pins |
| LOOM reports | `/app/loom_reports` (3) and `/app/web/release` (the pinned one) | sha256 equal to LOOM's reports |
| Release-pinned evidence manifest | compiled into the web build (`web/lib/audit-manifest.ts`) | audit still authenticates in the release container (browser suite) |
| Provenance and human-authorization labels | Flight Recorder UI | browser suite asserts the wording; LOOM's final spot-check PASS |
Staging: `hosting/stage_release_evidence.py` makes byte-exact copies into `release_evidence/` and refuses to write unless each source file equals the hash recorded by LOOM; it never modifies a source. `hosting/verify_release.sh` runs the image with **no mounts** (what a host does), re-hashes the baked files inside the container, and checks they are read-only to the app user.
Adding a **new** trace later requires a rebuild and redeploy on a host (no writable drop). Locally, a read-only mount at `/app/traces` still overrides the baked copy.

## 5. Security findings
| # | Finding | Severity | Status / action |
|---|---|---|---|
| S1 | No credential, key, token or private key in tracked files, evidence, image layers or image environment (patterns scanned) | pass | none |
| S2 | Local machine paths: only in local-run helper scripts and `docs/HOSTING.md` (home-directory defaults, since changed to `$HOME`); none in application code, evidence, or API responses (recorder API output scanned for paths, URLs, IPs) | low | acceptable; scrub the two docs/scripts before the public repo if you prefer |
| S3 | Personal identifiers: the author address `iowafence@users.noreply.github.com` (GitHub noreply, also enforced by the repo hook); no other email or name in tracked files | low | none; confirm you want the commit author shown publicly |
| S4 | Internal addresses / private repos / private hostnames | pass | none found in tracked files; only loopback appears in docs |
| S5 | Public mutation endpoints (10 POST routes) are anonymous: anyone can create a session and a fictional project up to the limits. They act only on that visitor's own in-memory project; no external call; release needs the human gates | medium | per-IP and per-session limits, engine caps, signed 12-hour cookie. **Set `CLIENT_IP_HEADER`**. Decide on an access gate (owner decision) |
| S6 | Self-declared decision names: "approvals" in the demo are typed names, labeled "Self-declared demo approval — identity not authenticated." on screen | info | accurate labeling already shown; do not describe as authenticated |
| S7 | CSP has no `script-src`; no HSTS from the app | medium | known; platform HTTPS should add HSTS (verify after deploy); a nonce CSP is a follow-up needing owner approval |
| S8 | Google Fonts loaded from Google's CDN (visitor IPs reach Google) | low | remove the `@import` for a closed venue; acceptable for a public demo, say so in privacy notes |
| S9 | `npm audit`: `next` (moderate) and build-time `postcss` (high, needs attacker-controlled CSS, which this app never processes); fix requires Next 16 | medium | not fixed (major upgrade changes a frozen build); disclose, do not claim "no known vulnerabilities" |
| S10 | Probes on the release container: `/.env`, traversal into `documents`, unknown document ids, `/traces`, `/cases`, `/dp001/...`, `/app/web/release/...` all 404; engine port not published; only 8080 mapped | pass | repeat once against the real HTTPS URL after deploy |
| S11 | Evidence in the public repo/image: traces, cases, run record (61 KB) and LOOM reports contain no secrets, URLs or paths; they name the Evolus workflow execution id, which is a record identifier, not a credential | low | owner to confirm publishing these authentic records |
| S12 | Rate limiting is per instance and in memory; no load test with many simultaneous judges has been run | medium | event values proposed, **not load-tested** |

## 6. Public-demo safeguards (section 7 of the brief)
- **Authentication:** none exists or is claimed. Optional platform password for the public window (owner decision).
- **Read-only protection:** the Flight Recorder is GET-only and read-only (browser suites assert no non-GET request and an identical project record before and after). Evidence directories are read-only to the app user. The recorder has no approve, send or edit control, and nothing a judge does can alter evidence, audits or cases.
- **Rate limiting:** present; must be configured for shared venue IPs (S5, S12).
- **Abuse:** judges can burn memory by creating projects; capped at 1000 projects with a 6-hour idle expiry.
- **Reset:** the reset route affects only the caller's own session.

## 7. Verification (local; frozen demo untouched)
See section 9 for the per-suite results. Unchanged by this work, verified by hash: ANVIL 2's five original files; both audits; the manifest; the pinned LOOM report; and the three UI sources LOOM spot-checked (only `hosting/Dockerfile` and new `hosting/` scripts, `release_evidence/`, and docs changed). The frozen demo (5071) and the accepted build (5051) answered 200 before and after; no frozen file was edited.

## 8. Missing requirements (blockers to publication, not to local readiness)
1. Owner decision on hosting platform and organizer acceptance (section 10).
2. A real HTTPS deployment: HSTS, client-IP header behavior, cold-start time, and health-check behavior are **not verified** until then.
3. Concurrency: no load test. Run one with a modest scripted judge count after deploying to staging (owner-approved).
4. Submission assets not produced here: video, slides, cover image, written entry. (The 150-second script and shot list exist in `demo/`; the recording has not been re-made for the Flight Recorder route, which is documented in `DEMO_ROUTE_V2.md` and **not rehearsed**.)
5. Public repository timing and contents (section 10).
6. `main` is at `5bf7dec`; the release branch `hosting/judge-demo` is local only (about 10 commits ahead).

## 9. Tests run for this report
See `RELEASE_CHECKLIST.md` section H for the result table.

## 10. Decisions required from the owner (minimum)
1. **Platform:** approve Render Standard (and contact the organizers to confirm it is acceptable), or choose Replit Reserved VM (needs a separate, untested start path).
2. **Account and payment:** the owner creates and funds the hosting account and connects the repository (or uploads the image). I need no credential; none should be shared with me.
3. **Public URL / domain:** the default `*.onrender.com` name, or a custom domain (DNS control is the owner's).
4. **Access mode:** open anonymous access, or a platform password during judging.
5. **Event limits:** approve the proposed `NEW_DEMOS_PER_HOUR` 120 / `IP_REQUESTS_PER_MIN` 900 / `IP_MUTATIONS_PER_10MIN` 400.
6. **Public GitHub:** whether and when to push the branch or merge to `main` (recommended: after the staging deploy passes, before submission, so the submitted URL and the repository match), and approval to publish the authentic Evolus evidence files and LOOM reports in it.
7. **Disclosures:** approve the wording of the known-limitations notes (self-declared names, in-memory restart loss, npm advisories, no load test).

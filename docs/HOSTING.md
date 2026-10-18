# Hosting the judge demo

Status 2026-10-17. A public synthetic demo runs on Render from a private container image, pulled by digest (see [RENDER_DEPLOY_RUNBOOK.md](hosting/RENDER_DEPLOY_RUNBOOK.md)). This file is the hosting plan and security review. Everything below marked "verified" was run locally in Docker; anything about Vercel, Fly.io, Cloud Run or any other platform is **not verified**.

## Decision

**Recommended: one container, one running instance** (engine on loopback + web tier), behind the platform's HTTPS. Image: `hosting/Dockerfile`.
**Not recommended for the October 18 demo: Vercel for the web tier**, because the web tier keeps authority-related state in server memory (below). A frontend-only Vercel deployment would not give judges a working backend, and a Vercel + remote-engine split is blocked by that state until it is moved, which needs the owner's decision.

## Why a single instance (facts from the code)
| Where | State | Consequence on a multi-instance / serverless host |
|---|---|---|
| Engine (Python) | all projects, decisions, audit, in memory; idle expiry 6 h; cap `DEMO_MAX_PROJECTS` (1000) | one engine process only; a restart drops every project |
| Web tier `lib/takeoff-service.ts` | takeoff-review attestations (`globalThis` Map) | Release would be disabled at random: the review recorded on one instance is unknown to the next |
| Web tier `lib/ai-findings.ts` | AI finding accept/reject/defer marks | marks vanish between requests |
| Web tier `lib/demo.ts` | the release response's `artifact_kind` | the released banner loses `artifact_kind` (documented limitation) |
| Web tier `lib/limits.ts` | rate limiter | the limit is per instance, not global |
So the engine and the web tier must each run as **exactly one process that is never scaled to zero or restarted mid-session**. Serverless platforms (Vercel functions) cannot guarantee that.

## Option A (recommended): single container
```bash
docker build -f hosting/Dockerfile -t gatehouse-judge-demo .
docker run -d --read-only --tmpfs /tmp --tmpfs /app/web/.next/cache:uid=10001 --cap-drop ALL --security-opt no-new-privileges \
  -p 127.0.0.1:8080:8080 gatehouse-judge-demo          # verified; on a real host publish the port through the platform's HTTPS proxy only
```
* The engine listens on `127.0.0.1:8099` **inside** the container (`ENGINE_HOST`); only the web port is exposed. Verified: from the container network `8099` refuses connections.
* `ENGINE_API_KEY` and `SESSION_SIGNING_SECRET` are generated at every start unless supplied as platform secrets; they are never printed, written or baked into the image (verified by image inspection).
* The image contains **no AMD or Evolus client, endpoint or credential**; replay is offline (verified by a search of the image; only text labels such as the provider name occur in the stored-evidence data files).
* Platform requirements: one instance, always on (`min=max=1`, no scale-to-zero), HTTPS, ~1 GB memory. Image size is 747 MB (full `node_modules` because `next.config.ts` needs TypeScript at runtime; a slimmer image is possible later). *Platform settings are untested.*

| Variable | Purpose |
|---|---|
| `PORT` | web port (default 8080) |
| `ENGINE_API_KEY`, `SESSION_SIGNING_SECRET` | optional; random per start if absent (sessions end on restart anyway) |
| `CLIENT_IP_HEADER` | **set this on any public host** to the one header your platform sets itself (e.g. `fly-client-ip`, `cf-connecting-ip`). Without it the limiter trusts the first `X-Forwarded-For` hop, which a client can forge. If set and the header is missing, all such requests share one bucket (verified: 330 requests with 330 forged IPs were throttled together) |
| `NEW_DEMOS_PER_HOUR` | per-network limit on new sessions (default 12, max 500). Judges sharing one venue IP will hit 12 quickly: raise it (the judge image sets 120) |
| `FLIGHT_TRACE_DIR` | directory of external Flight Recorder traces (default `/app/traces`); mount read-only |

### Pending-review RFI cases (read-only, verified locally)
ANVIL 2's persisted cases (`GH-CASE-*.json`, mode 0600, so unreadable to the container) reach the recorder through a byte-exact export: `hosting/export_evolus_cases.py` copies the cases and the run records they reference into `~/gatehouse-evolus-cases` (mode 0644, sha256-verified; it never writes to the source and refuses to overwrite a file that differs). `hosting/run-local.sh` mounts that directory read-only at `/app/cases` (`GATEHOUSE_CASES_DIR`). A case is shown only under the execution whose `trace_id` equals the case's `gatehouse_trace_id`, and only if it passes strict checks (exact PENDING_HUMAN_REVIEW / NOT_APPROVED / not sent / all authority flags false, every citation backed by an evidence record, run record sha256 equal to the one in the execution trace, draft identical to the run record, cited document hash and page consistent with Gatehouse's own `dp001/document_registry.json`). Anything else is listed REJECTED and not displayed. The reader has no write, approve, send, engine or network call. Cases do not store the cited excerpt text; the panel says so and shows document, page and hash instead. A hosted copy needs the same files in `GATEHOUSE_CASES_DIR` at publish time.

### Independent audit records (additive, read-only, release-pinned)
`dp001/independent_audits/AUDIT-<run>-<n>.json` records an independent auditor's assessment of an Evolus run. Two exist for `GH-RUN-e5bbcecef551`: **-1** (first remediation; relayed report; it extended Addendum 01 item 1.5 to G3, which LOOM's re-check found wrong) is kept byte-identical and pinned as SUPERSEDED, and **-2** (schema `gatehouse-independent-audit.v2`) is the corrected record, built by `tools/build_corrective_audit.py` from LOOM's own re-check report (sha256 `d6040e16…abf05`, bundled at `web/release/`). -2 treats item 1.5 as G2-only; records G3 clear opening width UNRESOLVED, G3 post OD UNRESOLVED and G3 terminal/gate footing SPECIFIED (3/F501, 1'-4" dia. x 4'-0" deep minimum); keeps D2 FLAGGED and off the shortlist; and carries one separate **proposed clarification** for the G3 post outside diameter only, authored by ANVIL 1 from LOOM's recommendation (not an Evolus case, not approved, not sent). It is never a human decision.

**Trust boundary.** An audit file is never trusted for what it says about itself, including a sha256 computed from it. `web/lib/audit-manifest.ts` is the release manifest: it is compiled into the application release, sits outside the mutable audit directory (`GATEHOUSE_AUDIT_DIR`), and is never generated or updated at load time. For each run it pins the run, trace and case digests and ids, the LOOM report digest, the exact digest of every audit file (one ACTIVE, others SUPERSEDED) and the **policy**: the exact disposition of every issue and of D1 and D2, the G3 scope-finding statuses and the proposed-clarification ids. The loader rejects (and then treats the whole run as NOT CLEARED): bytes that differ from the pinned digest; a file not in the manifest (unregistered or substituted, including a stray replacement, which also revokes a verified sibling); duplicate bytes; a missing pinned file; an altered or missing bundled LOOM report; a disposition, case binding, scope status or clarification outside the pinned policy; a different run, trace or execution; and an invalid manifest. It still re-checks run/trace/case bytes, document hashes against `document_registry.json`, and that every quote is in the package recorded in the run record. Only a verified SUPPORTED disposition puts a case on the shortlist; an audit can never approve anything, and the recorder shows it beside the original validator result and cases, never in place of them.

**Limitations (be exact).** The manifest authenticates *which bytes this release accepts*; it is not a digital signature and does not prove LOOM wrote them. Whoever can change the application release (source, build or image) can change the manifest, so the protection is against changes to the audit-data directory and the run's evidence files, not against a compromised build. The pinned digests were entered by ANVIL 1 and need LOOM's independent confirmation. The bundled LOOM report is authenticated by hash only. Operator-controlled environment (`GATEHOUSE_AUDIT_DIR`, `GATEHOUSE_RELEASE_DIR`) can point at other directories, but whatever is found there must still match the compiled-in digests. A hosted copy must ship the audit files and the bundled report with the same release.

### Flight Recorder trace drop (local run, verified)
`hosting/run-local.sh [port]` runs the image with `$HOME/gatehouse-flight-traces` mounted **read-only** at `/app/traces` (`FLIGHT_TRACE_DIR=/app/traces`); override with `FLIGHT_TRACE_HOST_DIR`. The reader lists the directory on every panel open, so a new file appears with no restart and no code change. Producer rules: write each trace **atomically** (write to a name not ending in `.json`, or a dotfile, then rename to `*.json`); a half-written `*.json` is listed as REJECTED until complete. Files must be world-readable (the container runs as uid 10001). At most 39 trace files are read (sorted by name); the rest are ignored. The recorder never writes to the directory.
| `DEMO_MAX_PROJECTS`, `DEMO_TTL_SECONDS` | engine caps (defaults 1000 / 21600) |

## Option B: Vercel for the web tier + a container for the engine
Blocked until, at least: (1) the three web-memory stores above move into the engine or a shared store (this changes how release gating and the authority banner are computed, so it needs owner approval and re-verification of all suites); (2) the engine is reachable from Vercel over the public internet, which means exposing it with its key; (3) PDF/ledger files are bundled into the function (`outputFileTracingIncludes`) or served elsewhere. Not attempted.

## What a judge can do (verified in the container)
Load the C101 drawing viewer with evidence chips; inspect AI findings (verified / confirmed / contradicted, each against what it was checked against); select Base or Alternate; review the footing schedule and four-crew comparison; reach the qualified fictional release; open the AI Flight Recorder.

## Deployment security review (local black-box checks)
| Check | Result |
|---|---|
| AMD / Evolus keys in browser, build output, image layers, image env | none (client bundle and image searched; no key names in `.next/static`) |
| Public proxy to AMD or Evolus | none: no route calls either; the Flight Recorder reads local files only |
| Session cookie | `Secure; HttpOnly; SameSite=lax`, 12 h absolute |
| Response headers | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, `Permissions-Policy` (camera/mic/geolocation off), CSP limited to `frame-ancestors 'none'; base-uri 'self'; form-action 'self'` |
| Weak point: CSP has no `script-src` | open; a nonce-based CSP is a follow-up (Next inline scripts) |
| HSTS | not set by the app; the platform's HTTPS layer must add it |
| Path traversal, unknown document ids, `/.env` | 404 |
| Engine reachable from outside the container | no |
| Rate limits | per-IP and per-session in the web tier; engine caps projects and mutations; per instance only |
| Forged `X-Forwarded-For` | defeats the per-IP limit **unless** `CLIENT_IP_HEADER` is set (fixed here, tested) |
| XSS via human-entered names and notes (HTML and script in a note) | rendered as inert text in the recorder and workspace; no injected element, no script executed |
| Container | non-root (uid 10001), read-only root filesystem, all capabilities dropped, no-new-privileges |
| Build hygiene | `.dockerignore` now excludes nested `.env*`, keys and test files (the classic builder only applies root-anchored patterns; a canary `.env.local` was proven absent from the image) |
| Dependencies | `npm audit`: `next` (moderate) and bundled `postcss` (high, build-time); fix needs Next 16 |
| Abuse | anonymous and public: anyone can create sessions up to the limits. Consider an access gate (platform password, shared code) for the public window |
| Google Fonts | the page loads DM Sans / IBM Plex Mono from Google's CDN (visitor IPs reach Google); remove the `@import` for a closed venue |

## Not verified
Any real platform deployment; HTTPS/HSTS; behavior under load or with many simultaneous judges; the proxy's behavior behind each platform's header conventions; image slimming.

## Owner approvals needed (nothing happens without them)
1. Hosting platform and account; whether to deploy at all; public vs access-gated.
2. Domain / URL to give judges.
3. Setting `CLIENT_IP_HEADER` for the chosen platform (needs the platform's documented header).
4. Raising `NEW_DEMOS_PER_HOUR` for the venue.
5. Whether Option B (Vercel) is worth moving authority-related state; if yes, a separate, owner-approved change with full re-verification.
6. Pushing this branch / merging it to `main` (currently local only).
7. Publishing the recording or screenshots.

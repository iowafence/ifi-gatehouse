# Render deployment runbook: IFI Gatehouse judge demo (prepared 2026-10-14; NOT executed)

Status: **Phases 1 and 2 done locally; Phase 3 is waiting on the owner** (a private container registry and the Render login). Nothing has been pushed, published or deployed. Provider screens below are from Render's documentation and are unverified until clicked.

## 1. The verified artifact (Phase 1)
| Item | Value |
|---|---|
| Source commit | `9fee8c7` (branch `hosting/judge-demo`, local only; `main` is `5bf7dec`) |
| Built from | a clean `git archive 9fee8c7` (not the working tree) as `gatehouse-judge-demo:9fee8c7` |
| Local image ID (config digest) | `sha256:f641393c048c0facadfddebe392e44aaff282510a34e10d5d4a2de81331478be` |
| Registry image (private GHCR) | `ghcr.io/iowafence/ifi-gatehouse@sha256:f641393c048c0facadfddebe392e44aaff282510a34e10d5d4a2de81331478be` (pushed 2026-10-14; manifest digest equals the local image ID; anonymous access refused, i.e. private). Pulled back by digest after deleting the local copy: image ID matched, `verify_release.sh` PASS on the pulled copy. Write credential removed (`docker logout ghcr.io`). |
| LOOM final PASS report | `LOOM-GH-RUN-e5bbcecef551-9b0a22f-spotcheck.md`, sha256 `c18af41ecc38d0eadc3d7388062558af977682702eec36ca64f7cc226f379aaa` (matched) |
| `hosting/verify_release.sh` on this exact image | PASS: 8 baked evidence files equal `RELEASE_SHA256SUMS`; audits -1/-2 and pinned LOOM report equal the manifest pins; evidence read-only to uid 10001; 0 mounts; non-root |
| PDFs | 4 registry documents in the image, sha256 equal `document_registry.json` |
Why a registry image and not a Git build: Render would otherwise rebuild from a repository checkout, which needs a GitHub push (not authorized) and would not be byte-identical. Render deploys prebuilt images from a registry by digest, so the verified bytes are what runs. Prebuilt-image services have no auto-deploy (Render documentation), which is the desired setting.

## 2. Security and capacity results (Phase 2)
- **Dependencies:** `npm audit`: 0 critical, 1 high, 1 moderate, all from PostCSS inside Next 15 (fix needs Next 16). Exposure: PostCSS runs only at build time on this repository's own stylesheet; the running server never parses visitor-supplied CSS or source maps, the app has no upload or CSS route, so the file-read and path-traversal advisories (which need attacker-controlled CSS) are not reachable. Not fixed (a major upgrade of a frozen build); disclosed. Python engine uses the standard library only.
- **Public mutation endpoints:** 10 POST routes, all act on the caller's own signed-session project; session isolation verified (A's reset leaves B unchanged); a tampered cookie yields no one else's project; engine caps per project and in total; no outbound network call exists.
- **Secrets and paths:** none in tracked files, evidence, image environment or image filesystem (one false positive: a base64 blob inside the minified pdf.js worker matched an AWS-key pattern). Recorder API output contains no paths, internal addresses or credentials (asserted by `hosting/verify_live.py`).
- **Listening:** web tier on `0.0.0.0:$PORT` (tested with `PORT=10000`, Render's default); engine on `127.0.0.1:8099` only, unaffected by `PORT`.
- **Client IP:** Render's pages I could read do not document the client-IP header or whether `X-Forwarded-For` is appended or replaced, so no header is trusted blindly. Configuration: `CLIENT_IP_HEADER=x-forwarded-for` with `CLIENT_IP_FROM_RIGHT=1` (the **last** entry, which the platform proxy writes; a client can prepend values but not control it; with extra proxy hops it over-shares a bucket and never accepts a forged value). Tested locally with a proxy-style last entry: 400 sessions with forged prefixes got 120 allowed and 280 refused (429). A missing header fails closed into one shared bucket. **Must be confirmed on the real service** (section 5, step 6).
- **Load (bounded, local container, event limits, 2 GB class):** 60 judges x 3 walks (2,340 requests): all 200, 379 req/s, p50 64 ms, p95 460 ms, max 2.3 s. 30 judges behind one shared IP (390 requests): all 200, p95 278 ms. Three repeated 40-judge runs: p95 310 to 388 ms, memory plateaued near 490 MiB (idle 137 MiB; about 0.64 MiB per session). Not a test of Render's network or of hundreds of simultaneous judges.
- **Limits chosen from these results:** `NEW_DEMOS_PER_HOUR=120`, `IP_REQUESTS_PER_MIN=900`, `IP_MUTATIONS_PER_10MIN=400`, plus `DEMO_MAX_PROJECTS=500` (extra memory headroom; default is 1000). A walk is about 14 requests, so 900 per minute per IP supports roughly 60 judges walking at once from one venue address.

## 3. Owner steps to get the exact image to a private registry
The image contains the application source and must be **private**. Do not paste passwords or tokens into chat; type them in your own terminal. Run each command yourself in your own terminal.
1. Create a **private** repository on a registry you control, for example Docker Hub (`<you>/gatehouse-judge-demo`) or GitHub Container Registry (private package). Create an access token with write permission for pushing, and a second read-only token for Render.
2. In your terminal: `! docker login` (or `docker login ghcr.io`), entering the credentials there.
3. `! docker tag gatehouse-judge-demo:9fee8c7 <registry>/<you>/gatehouse-judge-demo:9fee8c7`
4. `! docker push <registry>/<you>/gatehouse-judge-demo:9fee8c7`
5. Tell me the image path. I will pull it **by digest** on this machine, confirm its image ID is `sha256:f641393c…478be`, and re-run `hosting/verify_release.sh` on the pulled copy before anything goes live. Record `docker inspect --format '{{index .RepoDigests 0}}' <image>` as the deployed digest.

## 4. Render configuration (Phase 3; owner clicks, exact values)
1. Render dashboard > **New +** > **Web Service** > **Existing Image**. Image URL: `<registry>/<you>/gatehouse-judge-demo@sha256:<digest from step 3>` (pin by digest, not by tag). Add the **read-only** registry credential when prompted (the owner enters it on Render's page).
2. Name `gatehouse-judge-demo`; any region. **Instance type: Standard** (1 CPU, 2 GB; plan id `1c-2g`). **Confirm the dollar price on the screen before creating;** I could not read it from Render's pages (earlier documentation said about $25/month; a workspace plan fee may apply on top).
3. **Instances: 1.** Do not enable autoscaling. **Do not add a disk.** No auto-deploy exists for prebuilt images.
4. Advanced > **Health Check Path:** `/api/demo/health`.
5. Environment variables (none are secrets): `CLIENT_IP_HEADER=x-forwarded-for`, `CLIENT_IP_FROM_RIGHT=1`, `NEW_DEMOS_PER_HOUR=120`, `IP_REQUESTS_PER_MIN=900`, `IP_MUTATIONS_PER_10MIN=400`, `DEMO_MAX_PROJECTS=500`. Leave `PORT` alone (Render sets it). Optional: `SESSION_SIGNING_SECRET` and `ENGINE_API_KEY` (random per start if absent). **Do not set** `GATEHOUSE_AUDIT_DIR`, `GATEHOUSE_RELEASE_DIR`, `FLIGHT_TRACE_DIR`, `GATEHOUSE_CASES_DIR`, `DP001_DIR`.
6. Create the service. If Render asks for billing or login, you complete it; I do not need those details. Keep the `*.onrender.com` URL private until verification passes.

## 5. Live verification (Phase 4; I run these once the URL exists)
1. `hosting/verify_live.py https://<service>.onrender.com` (about 70 checks: health, redirect, headers, probes, every PDF hash, Flight Recorder content, audit pin, evidence not writable, isolation).
2. Browser: `DEMO_URL=https://<service>.onrender.com/ e2e_evolus_cases.py`, `e2e_dp001.py`, `e2e_viewer_stability.py`, `e2e_footing.py` (screenshots).
3. `hosting/capacity_probe.py https://<service>.onrender.com --judges 20 --walks 2 --spoof --xff none` (bounded; own sessions only).
4. Record HSTS presence, response headers and cold-start time.
5. Restart behavior: Render dashboard > Manual Deploy / Restart; confirm health returns, judge projects reset, evidence unchanged (`verify_live.py` again).
6. **Client-IP confirmation:** from this machine exhaust the new-session limit (the spoof test does it); then from a second network (the owner's phone on cellular) open the URL. If the phone still gets a session, per-IP separation works. If it is refused, Render is not supplying a per-client last entry: stop, set the three limits higher or add a platform password, and re-test.

## 6. Rollback
- Not yet announced: Render > service > **Suspend** (or deploy the previous digest). State is in memory, so there is nothing to restore.
- After announcement: Manual Deploy of the last verified digest (keep it recorded here). Judges lose in-progress projects.
- Evidence concern: never edit in place. Pull the recorded digest locally, re-run `hosting/verify_release.sh`, compare to `RELEASE_SHA256SUMS`.
- Take-down: Suspend the service. The frozen local demo is unaffected throughout.

## 7. Limiter-repair image (2026-10-14; supersedes the image in section 1 for the one authorized redeploy)
| Item | Value |
|---|---|
| Source | commit `20e0d6b` (tip of `hosting/limiter-fix` is `c2730c3`, which only adds `hosting/limiter_matrix.py`); clean `git archive` build |
| Registry image (private GHCR, unique tag `limiter-20e0d6b`) | `ghcr.io/iowafence/ifi-gatehouse@sha256:e6d41ac19afb297c50e6729ff9148f9947ce60658b70d03d966fece71334947b` (OCI manifest, 4,938 bytes, linux/amd64; image ID equals manifest digest under the containerd image store) |
| Verification | anonymous manifest fetch refused (HTTP 403, private); local copy deleted, pulled back by digest; `hosting/verify_release.sh` PASS (8 evidence files, audits -1/-2, read-only, 0 mounts, uid 10001); registry PDFs match; write token removed from Docker |
| Rollback image (still in GHCR, untouched) | `ghcr.io/iowafence/ifi-gatehouse@sha256:f641393c048c0facadfddebe392e44aaff282510a34e10d5d4a2de81331478be` |
| Local test results | matrix 11 of 11; node 53 of 53; backend 563 passed; six browser suites and audit-tamper PASS; 53 live checks PASS |

# IFI Gatehouse judge demo: final readiness and freeze record (2026-10-14)

**JUDGE-READY: PASS, with the documented limitations below.** Public URL: https://ifi-gatehouse.onrender.com (Render Web Service, Docker image from a private GHCR package). No further deployment, restart, environment change, load test, source publication or Evolus/AMD call is authorized until the owner says so.

## Frozen deployment
| Item | Value |
|---|---|
| Deployed image (owner-reported live; behavior corroborated, see below) | `ghcr.io/iowafence/ifi-gatehouse@sha256:e6d41ac19afb297c50e6729ff9148f9947ce60658b70d03d966fece71334947b` (OCI manifest, linux/amd64) |
| Source commit of the image | `20e0d6bfaf8ff2f634fb73722f82ab5fe3aea94c` on branch `hosting/limiter-fix` (later commits on that branch add only tests, tools and documentation; none is in the image) |
| Rollback image (kept in GHCR, unchanged) | `ghcr.io/iowafence/ifi-gatehouse@sha256:f641393c048c0facadfddebe392e44aaff282510a34e10d5d4a2de81331478be` (from `9fee8c7`; has the per-network limiter bypass, so use only if the current image fails) |
| Render | Web Service, Standard 1 CPU / 2 GB (plan `1c-2g`), 1 instance, no autoscaling, no disk, health check `/api/demo/health`. Render redeploys when environment settings are saved. |
| Environment | `CLIENT_IP_HEADER=x-forwarded-for`, `CLIENT_IP_FROM_RIGHT=2`, `CLIENT_IP_LOG_SHAPE=0`, `NEW_DEMOS_PER_HOUR=120`, `NEW_DEMOS_GLOBAL_PER_HOUR=300`, `IP_REQUESTS_PER_MIN=900`, `IP_MUTATIONS_PER_10MIN=400`, `DEMO_MAX_PROJECTS=500` (owner-confirmed; nothing here is a secret) |
| Pinned evidence (unchanged) | traces `5aa339ec…bef8`, `8cd25c97…d6bd`; cases `6e4319bc…4701`, `7f7f5001…ed7b`; run record `7a4cc958…0c4`; audits -1 `1e4f1c19…7371b` (superseded) and -2 `b68748fe…4b8` (active); pinned LOOM report `d6040e16…abf05`; LOOM final PASS report `c18af41e…79aaa` |

## Evidence of readiness
| Check | Result | Source |
|---|---|---|
| 54 live checks on the production URL | PASS (53 through a local counting proxy plus the direct HTTP to HTTPS 301 check) | measured |
| Browser suites on production: evidence/audit/cases 6, DP-001 scope 8, PDF viewer 11, footing/pricing 18, takeoff 7, AI bridge 14 | all PASS | measured |
| Evidence, audits, RFI statuses | hashes unchanged; D1 pending, unapproved, unsent; D2 flagged, non-actionable; G3 clarification unapproved; executions separated; AMD/Gemma NOT_REPORTED | measured by `verify_live.py` |
| Per-network new-session limit | from one network with no forged headers: 120 admitted (27 Phase 1 sessions counted by proxy, 3 existing, 90 more), **first HTTP 429 on request 121**, 5 further requests refused, 3 of 3 existing sessions still usable | measured |
| Second network | **owner-reported**: three separate Chrome Incognito visits over cellular with Wi-Fi off all loaded, while the primary network was already receiving 429 for new sessions. I did not observe these visits myself. | owner-reported |
| Trusted client-IP position | second entry from the right of `X-Forwarded-For`; matched the Cloudflare `CF-Connecting-IP` hash on all 12 owner-reported diagnostic observations, stable per network, different across networks, unchanged by forged prefixes; Cloudflare returned 403 for a forged `CF-Connecting-IP`. The raw log lines were summarized by the owner; I did not see them. | owner-reported plus one measured test |
| Local adversarial matrix on the exact image source | 11 of 11 scenarios (bypass reproduced, stable and rotating entries, forged prefixes, missing/malformed/too few entries fail closed, global guard 301 and 11, capacity 503 without eviction, never-used flood frees slots) | measured |
| Release image | `verify_release.sh` PASS on the pulled-by-digest image: 8 evidence files, audits, read-only evidence, 0 mounts, non-root, PDFs match the registry; no secrets or private paths in the image | measured |
| Tests | node 53 of 53; backend 563 passed, 0 failed (2 snapshot-only policy errors; repo policy 16 of 16); demo routes 14 of 14; audit-tamper rejection browser check PASS (local) | measured |
| Capacity | engine returns 503 "demo capacity reached" at the cap and never evicts an active project; never-used sessions free their slot after 15 minutes; memory plateaued near 490 MiB under a 60-judge local load and about 15 to 17 percent of 2 GB on Render | measured / owner-reported |
| Global 300 per hour guard | configured (owner-confirmed); enforced behavior proven only locally. It was deliberately not exhausted on production. | partly unverified in production |

## Documented limitations (do not overstate in the submission)
1. The cellular result, the Render dashboard facts (image digest live, environment values, metrics, price) and the raw proxy log lines are owner-reported. I could confirm them only through behavior.
2. The trust boundary assumes every request reaches the service through Cloudflare and that Render appends exactly one proxy hop after it. Both published addresses answer as Cloudflare, but the origin address is not published, so a direct path cannot be ruled out. If Render changes its hop count the limiter could silently weaken; the global guard bounds new sessions, and the 121-request threshold test should be repeated after any platform change.
3. Per-network means per client IP address: judges sharing one venue or carrier address share one 120 per hour budget; a client rotating IPv6 addresses gets a fresh bucket each time (bounded only by the global guard).
4. The global guard of 300 per hour protects the 500-project cap and memory, not availability: a determined flooder could exhaust it and delay new judges for the rest of the hour.
5. Participant state is in memory: any restart or redeploy drops every in-progress judge project. Judges' names are self-declared, not authenticated.
6. HSTS is not set by the app or observed from the platform; there is no `script-src` Content-Security-Policy; Google Fonts loads from Google's CDN.
7. `npm audit` still lists Next 15 and build-time PostCSS advisories (fix needs Next 16); not reachable at runtime (no visitor-supplied CSS is processed).
8. Capacity was tested up to 60 concurrent judges locally and 20 on production; large-scale load is unverified.
9. The actual Render monthly price was not provided to me.
10. The AI results shown are stored authentic Evolus runs audited by LOOM, not live inference during judging. Human authorization for every RFI is NONE RECORDED.

## Freeze
Infrastructure and deployment are frozen as above. Any change (environment save, redeploy, image change, restart) needs explicit owner authorization and a re-run of `hosting/verify_live.py` plus the 121-request threshold check from a quiet network.

## Next phase (not started)
Submission assets (video covering the Flight Recorder route, slides, cover image, written entry) and controlled GitHub publication. Publication needs the owner's decision on which branch and commit to publish (`20e0d6b` is the deployed source) and approval to include the authentic Evolus evidence and LOOM reports.

# New-session rate limiter: production diagnosis (2026-10-14)

No production request, restart or deployment was made for this diagnosis. Evidence is the deployed release source (commit `9fee8c7`, image `sha256:f641393c…478be`), the owner-verified Render configuration, the earlier live-test observations, and a local reproduction using the SAME pulled image.

## Root cause (confidence: high for the mechanism, moderate for Render's exact header layout)
The limiter keys every counter on `clientIp(req.headers)`. Production ran `CLIENT_IP_HEADER=x-forwarded-for`, `CLIENT_IP_FROM_RIGHT=1`, so the key is the **last** `X-Forwarded-For` entry. Behind Cloudflare and Render's router that entry is a proxy hop (Render appends to, and does not clear, `X-Forwarded-For`; third-party reports, unverified by Render's own pages), and it differs between requests. Each request therefore lands in a fresh bucket and the 120-per-hour limit is never reached.

Evidence:
1. Code: all three limiter keys (`ip:`, `ipm:`, `new:`) come from one `clientIp()` call; counters live in a single in-process `Map` (`lib/limits.ts`); `NEW_DEMOS_PER_HOUR` is read at request time and reaches `createProject` unchanged (`lib/demo.ts`); 429 is produced there. No other code path creates a session without passing it.
2. The same image and environment, locally, behind a proxy appending a CONSTANT last entry: 120 allowed, first 429 at request 121. Behind a proxy appending a ROTATING last entry: 150 of 150 admitted, no 429. This reproduces every production observation (forged header, no header, one keep-alive connection: about 400 sessions, no 429).
3. The owner confirmed the six variables are exactly as intended, and Render shows one instance, no restarts, so the setting reaches the code and counter state is not being lost.
Ruled out: default 12/hour applying (it would have refused far earlier); a shared "unidentified" bucket (it would have refused at 120); process restarts or multiple instances; forged-header acceptance (a forged prefix is to the left of the trusted entry and is ignored). Not ruled out: an unusual Render layout I cannot see from outside; only a header-shape observation settles the exact entry to trust.

## Latent hazard found
`CLIENT_IP_FROM_RIGHT` values other than exactly `1` silently fell back to the FIRST entry, which the client controls. A mistaken value would have been spoofable, not merely ineffective.

## Minimal fix (branch `hosting/limiter-fix`, commit `df9e9ef`; the deployed branch `hosting/judge-demo` is untouched)
1. `CLIENT_IP_FROM_RIGHT=N` (digit 1 to 9): key on the Nth entry from the right. 1 behaves as before. Fewer than N entries, or any invalid value, fails closed into one shared bucket and never falls back to the first entry.
2. Global guard `NEW_DEMOS_GLOBAL_PER_HOUR` (default 300, clamp 10 to 5000), checked after the per-network limit, independent of attribution, set below the 500-project cap so one source cannot exhaust it when attribution fails.
3. Opt-in `CLIENT_IP_LOG_SHAPE=1`: logs the forwarding-header shape for the first 30 new-session requests, with the right-most three entries reduced to 8-hex salted hashes (salt per process, never logged; no raw address). Comparing two requests from one visitor shows which position is stable.

## Tests (all in `web/test/limits.test.mts`; 53 of 53 node tests pass)
Reproduction (rotating last entry admits 150 of 150 at limit 120; stable last entry holds at 120); `FROM_RIGHT=2` holds at 120 despite rotation and a forged prefix; fail-closed matrix (3, 0, 10, abc, -1, 1.5, too few entries); global guard defaults, clamps and a 500-request rotating stream stopping at 300; shape log off by default, bounded to 30, no raw address. Four of these fail against the deployed `limits.ts`. Rebuilt test image (local only) behind the rotating-hop proxy: `FROM_RIGHT=2` gives 120 allowed then 429 at 121; global guard at 10 stops at 10.

## Do we need a new deployment and a controlled restart? Yes.
All three changes are code, so a new image is needed; environment changes also restart the service. No configuration-only fix exists. Recommended two stages, each needing separate owner authorization:
- **Stage 1:** new image, `CLIENT_IP_FROM_RIGHT=1` unchanged, add `CLIENT_IP_LOG_SHAPE=1` and `NEW_DEMOS_GLOBAL_PER_HOUR=300`. Safe immediately (global ceiling holds even though per-IP is still ineffective). Two requests from one device give the stable position in Render's logs. A restart also clears about 400 test sessions.
- **Stage 2:** set `CLIENT_IP_FROM_RIGHT` to the observed stable position (expected 2), remove the shape flag, verify one cap-crossing test (about 125 sessions) against a quiet service before announcing.
Pushing the new image needs the owner to log in to GHCR with a write token again (the earlier token was removed); only changed layers upload.

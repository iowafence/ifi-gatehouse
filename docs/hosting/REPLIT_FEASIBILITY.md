# Hosting feasibility: Replit Reserved VM (decision report, 2026-10-14)

Nothing was deployed, provisioned, imported or pushed. Provider facts come from the linked pages read on 2026-10-14; "measured" means run locally on this machine; "unverified" means no way to check without an account or a deployment.

## 1. Verdict
**REPLIT: CONDITIONAL.** It can run the same architecture, but not the container we tested, and several details can only be proven after deployment.
**Recommended platform: Render, one paid web service (Standard) deploying `hosting/Dockerfile` unchanged**, because it needs the fewest changes to the tested application. Use Replit if the organizers require one of the platforms they name. *Render is not among the platforms lablab suggests, so event acceptance must be confirmed with the organizers before choosing it.*

## 2. Replit: exact technical constraints
| Question | Answer | Basis |
|---|---|---|
| Deploy the existing Dockerfile? | **No.** Deployments are driven by `.replit` `build` and `run` commands plus Nix; the official configuration page documents no Dockerfile, and Replit's own writing says it avoids making users write Dockerfiles. (The docs do not say "unsupported" in so many words.) | [configuration](https://docs.replit.com/features/project-setup/configuration), [Replit blog](https://blog.replit.com/nix-vs-docker) |
| Reproduce Python + Next.js in one app? | Expected yes (`modules` for Node and Python, one run script). Module names and versions (`nodejs-22`, `python-3.12`) are **unverified**. | Replit docs describe modules; I could not confirm the current list |
| One external port | **Yes, exactly one**, mapped to external port 80; the exposed server must listen on `0.0.0.0`. | [troubleshooting](https://docs.replit.com/cloud-services/deployments/troubleshooting) |
| Engine unreachable from the internet | Our engine binds `127.0.0.1` on an unmapped port; since only one external port exists this should hold. **Unverified on Replit.** Proven locally: `hosting/replit/start.sh` listens on `0.0.0.0:<web>` and `127.0.0.1:<engine>` only. | measured |
| Single persistent instance | Reserved VM is the always-on, fixed-cost type, not autoscale. | [deployment pricing](https://docs.replit.com/billing/deployment-pricing.md) and [deployment types](https://docs.replit.com/features/publishing/deployment-types.md) |
| In-memory projects across restart / redeploy | **Lost on every publish** ("the file system in published apps is not persistent and resets every time you publish"); lost on any process restart. Platform recycling behavior is not documented in what I read. | troubleshooting page |
| Server-side secrets, `FLIGHT_TRACE_DIR` | How environment variables and Replit "Secrets" are set for a deployment: **not confirmed** in the pages I could fetch (the template's `[env]` block is a guess to verify). A trace file must be **in the repository at publish time**; there is no documented way to drop a file into a running deployment, so adding a trace means republishing, which restarts the app and drops live sessions. | unverified |
| Image size 747 MB | Irrelevant: Replit builds from source (`npm ci` + `next build`). The source tree is 116 MB plus 654 MB `node_modules` and 92 MB build output (measured), against an 8 GB limit for Reserved VM apps. | measured; troubleshooting page |
| Resources | Measured: 136 MiB for the whole stack idle; first healthy response 1.5 s after launch; 0.5 MiB per additional empty project; 25 requests for a scripted judge visit. Peak load under many judges is **not measured**. | measured |
| Health check | Replit requests the homepage and fails publishing if it takes more than 5 s. Ours answers in about 3 ms once started. | troubleshooting page; measured |
| Public HTTPS URL without login | Yes: `https://<subdomain>.replit.app`, public by default with no visitor login; password-protected deployments exist on all plans; private deployments need Pro. | [docs](https://docs.replit.com/references/publishing/private-deployments) |

## 3. Pricing (from provider pages)
Reserved VM per month: **$15** shared 0.5 vCPU / 2 GB; **$35** dedicated 1 vCPU / 4 GB; $50 for 2 vCPU / 8 GB; $130 for 4 vCPU / 16 GB. "All publishing costs are deducted from your monthly credits." Source: [Replit deployment pricing](https://docs.replit.com/billing/deployment-pricing.md). Plans (Starter free with one published app; Core about $25/month monthly or $20 annual with $20 of credits; Pro $100) are from third-party summaries and **must be confirmed on [replit.com/pricing](https://replit.com/pricing)**; I could not establish whether the free plan can publish a Reserved VM.
Expected cost for a two-week event on the $35 VM: about $16 if billed pro rata by the hour (my arithmetic from the monthly price, not a quoted rate), plus the plan the account needs. Budget roughly **$35 to $60** to be safe.
Render fallback: Starter $7/month (512 MB, 0.5 CPU), **Standard $25/month (2 GB, 1 CPU)**; the free tier spins down after 15 minutes idle and is unusable (cold start, state loss). Sources: [Render compute plans](https://render.com/docs/compute-plans.md), [Render free tier](https://render.com/docs/free); live prices must be rechecked on [render.com/pricing](https://render.com/pricing) (the page could not be read automatically).

## 4. Security configuration
| Topic | Configuration |
|---|---|
| HTTPS | provided by the platform (`*.replit.app`, Render's domain). **HSTS: not stated by either provider**; the app does not set it. Check the response headers after deploying; add it in `next.config.ts` only with owner approval. |
| Client IP | Replit documents `X-Forwarded-For` support ([blog](https://replit.com/blog/deployments-updates)) but not whether it appends or replaces. Use `CLIENT_IP_HEADER=x-forwarded-for` with `CLIENT_IP_FROM_RIGHT=1` (new): the last entry is written by the platform proxy, so a client-prepended value is ignored; with more proxies than expected it over-shares one bucket rather than being forgeable. Measured locally: forged prefixes did not escape the per-IP limit. Verify once deployed (checklist below). |
| Cookies | already `Secure; HttpOnly; SameSite=lax`; needs the HTTPS URL. |
| Rate limiting | stays on. Never set the tunables to "off": they are clamped (requests/min 60..6000, mutations/10 min 30..3000, new demos/hour 1..500). |
| CSP | currently `frame-ancestors 'none'; base-uri 'self'; form-action 'self'` only. A stronger policy needs nonces for Next's inline scripts; not done, so say so. |
| Health check | Render: path `/api/demo/health` (no session needed). Replit checks `/`. |
| Public frontend, private engine | one exposed port; engine on loopback (measured). |
| Secrets | `ENGINE_API_KEY` and `SESSION_SIGNING_SECRET` are optional platform secrets, otherwise random per start; AMD and Evolus credentials are never needed and are not in the image, bundle or any route. |
| Logs | the start script prints no secret; I did not audit every log line of the application, so check the platform log view once after deploying. |
| Next.js / PostCSS advisories | `npm audit` lists four PostCSS advisories (XSS in CSS stringify output; three `sourceMappingURL` file-read/path-traversal issues). Each needs **attacker-controlled CSS** fed to PostCSS. In this app PostCSS runs only at build time on this repository's own stylesheet; `next start` does not process visitor input as CSS (stated from the app's design and its routes; I did not audit Next's internals). The `next` "moderate" finding is the same bundled PostCSS. **Not exploitable in the intended deployment; still open and fixed only by a Next 16 upgrade**, which is out of scope. |

## 5. Judge accessibility and concurrency plan
Measured here: judges are isolated (judge A's decision left judge B's project at the same version and audit length); a tampered session cookie produced a new project, never someone else's; a premature release attempt was refused (HTTP 409); memory grows about 0.5 MiB per empty project (priced projects were not measured).
Existing protections kept: per-session 60 mutations/10 min, engine cap of 100 mutations per project and 1000 projects, signed 12-hour sessions, release needs the gates.
**Event configuration (shared venue or office IP), all via environment, no code edit beyond the three tunables already added:**
| Variable | Value | Reason |
|---|---|---|
| `NEW_DEMOS_PER_HOUR` | 120 | many judges and resets behind one IP; default is 12 |
| `IP_REQUESTS_PER_MIN` | 900 | a scripted visit costs 25 requests; default 300 shared per IP |
| `IP_MUTATIONS_PER_10MIN` | 400 | a full walkthrough makes dozens of decisions; default 120 shared per IP |
| `CLIENT_IP_HEADER` / `CLIENT_IP_FROM_RIGHT` | `x-forwarded-for` / `1` | see above |
These are reasoned from the measurements above, **not from a load test**. Realistic limits: one Python engine process and one Node process, no benchmark of simultaneous judges, all state lost on restart. Optional: a platform password for the public window (Replit offers it on all plans) if you do not want open anonymous access.

## 6. Evolus / Flight Recorder readiness
The reader re-reads `FLIGHT_TRACE_DIR` on every open, so a file appears without a restart **if it can be placed there**. On Replit and Render's container the filesystem is not writable by us at runtime, so ANVIL 2's trace must be committed (Replit: in `traces/`; Render: baked or on a persistent disk, which I have not evaluated) and published, restarting the app. Plan the drop before judging opens. Simulated traces are labelled SIMULATED by the panel; nothing claims live Gemma or Evolus execution until a real run is recorded.

## 7. Gatehouse source changes
None are required to run on Replit or Render beyond configuration. Added in the candidate (defaults unchanged, no authority logic touched): `CLIENT_IP_FROM_RIGHT`, `IP_REQUESTS_PER_MIN`, `IP_MUTATIONS_PER_10MIN`, `ENGINE_PORT` in the Docker-free start script. New files: `hosting/replit/start.sh`, `hosting/replit/replit.toml.example` (a template, **untested on Replit**).

## 8. Fallback
Render Standard, single instance: builds `hosting/Dockerfile` directly ([Render Docker docs](https://render.com/docs/docker)), HTTPS included, always on for paid instances, zero-downtime deploys are supported (the mechanism is not described; sessions are lost on every deploy either way, and a brief overlap of two instances is possible, so do not rely on instance uniqueness during a deploy). Starter (512 MB) is too tight for Node + Python; use Standard.

## 9. Deployment procedure (after approval)
**Render:** (1) owner creates the account and a Web Service of type Docker from the repository (private repo needs GitHub authorization; after the repo is public no authorization is needed), Dockerfile `hosting/Dockerfile`, plan Standard, instances 1, health check `/api/demo/health`. (2) Set the four event variables and `CLIENT_IP_HEADER` as above. (3) Deploy once, then run the verification below. (4) Never redeploy during judging.
**Replit:** (1) owner creates the account and plan, creates an App from the public repository (or an uploaded archive), (2) copies `hosting/replit/replit.toml.example` to `.replit`, confirming each key in the current docs, (3) sets secrets and event variables, (4) publishes as Reserved VM 1 vCPU / 4 GB, (5) verifies.
**Verification (either):** `curl -sI <url>/` for headers and HTTPS; `/api/demo/health`; open the Flight Recorder; run `DEMO_URL=<url>/ python3 e2e/e2e_flight_recorder.py` and the other suites from a separate machine (they create demo sessions, so raise `NEW_DEMOS_PER_HOUR` first); send 400 requests with forged `X-Forwarded-For` prefixes from one machine and confirm some return 429 (proves the limiter keys on the platform-written address), then confirm a second real network is not throttled by the first (proves it is not over-sharing).

## 10. Owner approvals required
1. Choice of platform, accepting that Render is not on lablab's list (confirm with the organizers) or that Replit needs the untested non-Docker setup.
2. Creating the account and the paid plan and VM/instance; the budget ($35 to $60 for Replit; $25/month for Render Standard).
3. Giving the host access to the code: make the repository public first (preferred), or authorize GitHub access, or upload an archive.
4. Merging or pushing `hosting/judge-demo` (currently local, branch only) so the host can build it.
5. Going public with the URL, and whether to add a platform password.
6. Approving the event limit values above.
7. Approving any HSTS or CSP change.
8. Scheduling the ANVIL 2 trace drop (needs a republish).
Not done and not approved: no deployment, no provisioning, no GitHub connection, no push.

## Sources
[Replit deployment pricing](https://docs.replit.com/billing/deployment-pricing.md) · [Replit configuration](https://docs.replit.com/features/project-setup/configuration) · [Replit deployment troubleshooting](https://docs.replit.com/cloud-services/deployments/troubleshooting) · [Replit deployment types](https://docs.replit.com/features/publishing/deployment-types.md) · [Replit private deployments](https://docs.replit.com/references/publishing/private-deployments) · [Replit: Deployments updates (X-Forwarded-For)](https://replit.com/blog/deployments-updates) · [Replit: Nix vs Docker](https://blog.replit.com/nix-vs-docker) · [Render Docker](https://render.com/docs/docker) · [Render free tier](https://render.com/docs/free) · [Render compute plans](https://render.com/docs/compute-plans.md) · [lablab: delivering your hackathon solution](https://lablab.ai/delivering-your-hackathon-solution)

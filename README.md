# IFI Gatehouse

Evidence-gated commercial fence estimating, by [Iowa Fence Inc.](https://github.com/iowafence). Open source under the [MIT License](LICENSE).

> **AI interprets. Code calculates. Humans authorize.**

**Everything in this repository is fictional.** The project, owner, site, drawings, rates and prices are invented. Nothing here is a bid, a price to rely on, or a construction document. Current state, exactly: [docs/STATUS.md](docs/STATUS.md).

## Live demo

A public synthetic demo runs at **https://ifi-gatehouse.onrender.com** (one container, in-memory state, isolated anonymous sessions, rate-limited; names at the gates are self-declared). Open **AI Flight Recorder** to see two real Evolus workflow executions exactly as recorded: one failed (HTTP 400) and one completed. The completed run produced three exception findings and two draft RFIs. Gatehouse's strict validator accepted its structure (`COMPLETED_VALID`), and an independent audit (LOOM, an AI auditor, not a person) then found one draft supported (D1, pending human review) and one flagged as unsupported by controlling evidence (D2, kept as historical output). The audit was corrected after its own independent re-check (`release_evidence/loom/`). **No RFI was approved or sent; human authorization is none recorded.** The Evolus workspace was configured to use the AMD Token Factory (stated by the owner; the execution record does not confirm it), and the run record lists its configured model as Gemma-4-31B-IT, unverified. Per-execution model and AMD telemetry were not provided, so this repository makes no claim about which model served the run. The Evolus track's own-vLLM requirement is **not claimed as met**; that eligibility question is unresolved with the organizers. Nothing in the demo calls an AI service live.

## What it demonstrates

A model reads a construction drawing and proposes findings. Gatehouse treats every model claim as untrusted input:

* **AI evidence ledger.** Stored outputs of an AMD-hosted model are replayed **offline** and checked against the PDF itself (text positions and vector geometry). Each finding is verified, vector-confirmed, unverifiable, or **contradicted by drawing evidence**. In the one authorized live test the model said "clear" about a fence-type leader that the drawing's vector geometry shows ending on an interior divider end post. Gatehouse refuses to accept it: HTTP 409 `CONTRADICTED_BY_DRAWING_EVIDENCE`.
* **Deterministic engine.** Takeoff, footing schedule (`footing-scope.v1` → `footing-calc.v1` / `footing-schedule.v1`) and pricing are plain code; model confidence is never an input to arithmetic.
* **Human gates.** A named person resolves each Scope exception, decides the Labor basis and authorizes the Release. A scope change voids the downstream decisions. Names are self-declared in this demo.
* **Honest release.** The only release is a qualified fictional demonstration: `bid_ready: false`, banner **NOT BID READY — FICTIONAL DEMONSTRATION ONLY**.

Reference result (conditional, reproducible): with a self-declared G3 what-if (12 ft opening, 2.875 in OD post, 16 × 48 in footing) and the reference crew plan, the engine prices the fictional DP-001 Base Bid at **$54,284.69** and Alternate A-1 at **$45,771.50**. Other crew choices price differently. The tests compare these values with the engine's output; they are never injected.

## What it does not demonstrate

No live AMD inference in the demo. **Real spatial understanding is not demonstrated**: in the stored live test, gate-label localization scored 7/7, gate-symbol relationships verified 0, and one claim was contradicted. DP-001 is not bid-ready. Evolus workflow integration and Gemma are **not implemented** (see [docs/STATUS.md](docs/STATUS.md)). No persistence, no real authentication.

## Quick start

Requirements: Python 3.12, Node 22. Browser tests also need Playwright (`pip install playwright && playwright install chromium`).

```sh
# 1. Engine (standard library only), serving the DP-001 scope
export ENGINE_API_KEY="$(python3 -c 'import secrets;print(secrets.token_hex(24))')"
export ENGINE_DEMO_ROUTES=1 PORT=8099
python3 run/start_engine_dp001.py                       # 127.0.0.1:8099

# 2. Web (other terminal)
cd web
cp .env.example .env.local
#   ENGINE_BASE_URL=http://127.0.0.1:8099
#   ENGINE_API_KEY=<the same value>
#   SESSION_SIGNING_SECRET=<at least 32 random characters>
#   DP001_DIR=<absolute path of this repository's dp001/ directory>
npm ci && npm run build
npx next start -p 5071 -H 127.0.0.1                     # open http://127.0.0.1:5071/
```

Use new random values; never commit `.env.local`. The generic demo scope instead of DP-001: `python3 -m api.server`.

### Configuration

| Variable | Used by | Purpose |
|---|---|---|
| `ENGINE_API_KEY` | engine, web | shared key between the proxy and the engine |
| `ENGINE_DEMO_ROUTES` | engine | `1` enables the anonymous demo routes the web app uses |
| `PORT` | engine | engine port (default 8080) |
| `ENGINE_BASE_URL` | web | where the proxy reaches the engine |
| `SESSION_SIGNING_SECRET` | web | signs the anonymous demo cookie (≥ 32 characters) |
| `DP001_DIR` | web | the `dp001/` directory (registry, scope draft, AI findings ledger) |
| `DP001_DOCUMENTS_DIR` | web | optional; PDFs default to `samples/public-demo/dp001/` |
| `GATEHOUSE_RATEBOOK_DIR` | engine | optional private rate-book store (never committed) |
| `AMD_TOKEN_FACTORY_API_KEY` | optional live tool only | read from the environment or `~/.config/ifi-amd/token_factory.env`; not needed for anything above |

## Tests

```sh
python3 harness/run_safe_suite.py .                      # backend suite (3 PDF tests skip without PyMuPDF)
python3 -m unittest tests.test_repo_policy               # repository guardrails

pip install -r requirements-amd.txt                      # pypdfium2, pillow
export PYTHONPATH=amd_experiment
python3 -m unittest amd_bridge.test_bridge spatial_plan.test_plan spatial_plan.test_executor
python3 -m unittest discover -s amd_experiment/tests
python3 demo/snapshot.py --verify                        # frozen AMD evidence + key asset hashes

# browser suites: engine + web running on non-demo ports, a fresh web server per suite
DEMO_URL=http://127.0.0.1:5081/ python3 e2e/e2e_footing.py     # also ai_bridge, takeoff, dp001, viewer_stability
```

`e2e/e2e_pass6.py` needs the generic engine (`python3 -m api.server`) instead of the DP-001 engine. The proxy allows 12 new demo projects per hour per IP, in memory, so restart the web server between suites.

The AMD ledger `dp001/ai_findings.json` can be rebuilt offline (no network, no AMD client): `python3 -m amd_bridge.ledger`. Its output is hash-pinned.

## Hosting and the AI Flight Recorder

[`docs/HOSTING.md`](docs/HOSTING.md) is the hosting plan and deployment security review (one container, one instance; `hosting/Dockerfile`). The in-app **AI Flight Recorder** and its trace contract: [`docs/FLIGHT_RECORDER_CONTRACT.md`](docs/FLIGHT_RECORDER_CONTRACT.md); rebuild the recorded trace offline with `python3 -m amd_bridge.flight_trace`; web contract tests: `cd web && npm run test:flight`; browser test: `e2e/e2e_flight_recorder.py`. Demo route: [`demo/DEMO_ROUTE_V2.md`](demo/DEMO_ROUTE_V2.md).

## The 150-second walkthrough

[`demo/DEMO_SCRIPT_150_SECONDS.md`](demo/DEMO_SCRIPT_150_SECONDS.md), [`demo/DEMO_SHOT_LIST.md`](demo/DEMO_SHOT_LIST.md) and [`demo/DEMO_PREFLIGHT.md`](demo/DEMO_PREFLIGHT.md) describe the six scenes. `python3 demo/stage.py A B C` pre-stages three sessions through the real UI; `python3 demo/present.py` opens them. Known limits: [`demo/DEMO_LIMITATIONS.md`](demo/DEMO_LIMITATIONS.md).

## Repository layout

| Path | Purpose |
|---|---|
| `engine/`, `api/` | deterministic estimating engine and HTTP service |
| `pricing/` | quantity rules, footing calculation, crews, wage records, rate-book import, pricing engine, schemas |
| `intake/` | hardened ZIP inventory and optional PDF page index |
| `web/` | Next.js workspace: PDF evidence viewer, Takeoff Review, gates, AI Findings |
| `amd_bridge/`, `spatial_plan/`, `amd_experiment/` | offline AMD evidence ledger, Spatial Test 003 plan, oracle and stored records, curated harness |
| `dp001/` | the DP-001 scope drafts, document registry, AI findings ledger, independent takeoff reference |
| `samples/` | fictional scopes, the synthetic DP-001 package and the reference workbook (`samples/public-demo/`, with hashes and provenance) |
| `tests/`, `e2e/`, `harness/` | unit tests, browser suites, safe test runner |
| `run/`, `demo/` | start scripts; walkthrough tooling and documents |
| `docs/` | architecture, workflow, status, contracts, [milestone notes](docs/milestones/), [about the history](docs/HISTORY.md), [third-party notices](docs/THIRD_PARTY.md) |
| `evolus/` | Evolus agent instructions and client (mock mode). A separate adapter ran two real Evolus executions whose records are shown in the AI Flight Recorder (`release_evidence/`) |

## History, licenses and security

This repository is a single-commit public release of the project; the development history is kept in a private repository: [docs/HISTORY.md](docs/HISTORY.md). Third-party licenses and the optional AGPL PDF dependency: [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md). Security model and reporting: [SECURITY.md](SECURITY.md). Contribution and repository rules: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

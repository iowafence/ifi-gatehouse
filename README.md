# IFI Gatehouse

Evidence-gated commercial fence estimating, by Iowa Fence Inc. Open source under the MIT License.

**AI interprets. Code calculates. Humans authorize.**

Everything in this repository is fictional. The project, owner, site, drawings, rates and prices are invented. Nothing here is a bid, a price to rely on, or a construction document. Current state, exactly: [docs/STATUS.md](docs/STATUS.md).

**Live demo:** https://ifi-gatehouse.onrender.com (replays a recorded AMD parse and says so on screen; no live AI calls happen on the hosted site).

To walk the addendum step: after the upload, scroll down inside the dialog to 'Decision note', enter your name and a note (both are required before 'Accept this change' enables), then click Accept.

## The problem

A commercial fence bid lives in a drawing set, a spec section and a stack of addenda. The costly mistakes are quiet ones: a gate width nobody stated, a spec that contradicts a drawing, an addendum that changes a quantity. An estimator who guesses can lose the job, or win it at a loss. AI makes this worse if it fills the gaps with confident numbers.

## What Gatehouse does

It reads a bid package, finds what the documents do not say, and holds the estimate until a named person decides. Three gates, in order:

1. **Scope Gate.** An AI model reads the documents and proposes findings. Every finding shows where it came from (sheet, page and the quoted words). Nothing enters the scope until a named person accepts it. A model's claim is treated as untrusted input and checked against the PDF itself (text positions and vector geometry).
2. **Labor Gate.** A deterministic engine prices every line from a pinned rate workbook. A named person records the wage decision and picks the crew. Ineligible crews cannot be selected.
3. **Release Gate.** A named person authorizes the release. A scope change invalidates the labor and release decisions that depend on it. Every export is labelled QUALIFIED DEMONSTRATION, NOT BID READY, FICTIONAL.

The demo case, DP-001, is a fictional four-court pickleball complex with a three-court alternate. It contains deliberate traps: a gate (G3) whose width no document states, a spec that conflicts with a drawing, and a prevailing-wage gap. Gatehouse holds at G3, drafts a request for information, then takes Addendum 02 when it arrives, checks that every quoted line really sits on the cited page, shows Before and After, and waits for a named human to accept.

## Where AMD and open models are used

- The Addendum 02 parse ran on **Qwen3.8-27B through the AMD Token Factory** (a real call, HTTP 200; the capture is in the repository). The hosted demo replays that capture; a local stack can perform one authorized live parse.
- Scope reading was evaluated on the AMD Token Factory across three open models (Gemma-4-31B-IT, Qwen3.8-27B, DeepSeek-V4.1-Flash): 10 stored attempts, 32 real findings.
- Where a model is wrong, the product shows it. A model marked the same fence-type tag "clear" in two tests. The drawing's vector geometry contradicted it in the formal check of the second test, and a later retrospective reading contradicted the first. Both are labelled as contradicted, with how each was established.

## What was verified

- Four whole-job plans (two crews, each as Base and Alternate A-1) match an independently built answer key to the cent: CR13 Base $63,257.38 and Alternate A-1 $54,398.76; CR14 Base $66,879.97 and Alternate A-1 $57,405.40. 224 priced lines and 28 allocation comparisons were checked. The key was built by a separate verifier from the pinned workbook and is not published; that verifier saw some engine figures earlier, so this was **not blind verification**.
- Engine suite: 773 passed, 0 failed, 3 skipped (PDF-indexing tests that need PyMuPDF). Web suite: 144 of 144 on the build workstation; 141 passed and 3 skipped on a clean checkout (three Evolus audit tests need local evidence folders that are not in this repository).
- Exports are checked by a separate verifier before they are called ready. Verification record and every finding with its disposition: [docs/VERIFICATION.md](docs/VERIFICATION.md).

## Claims and limits

| Claim | Evidence | Status |
|---|---|---|
| Totals are deterministic and match an independent key to the cent | Totals reproduce from the demo's CSV export. A separate verifier compared them with its own private answer key; the key is not published. Record: [docs/VERIFICATION.md](docs/VERIFICATION.md) | Verified by a separate verifier (key not published) |
| Addendum 02 was parsed by an AMD-hosted open model | Real Qwen3.8-27B call via the AMD Token Factory, capture on file | Verified |
| The hosted demo makes live AMD calls | It does not. It replays a recording, labelled RECORDED | Disclosed |
| A model caught the missing G3 width | No. The engine's missing-value check did. The AI drafted the RFI | Not claimed |
| Model readings of gate symbols are verified | No. Gate label positions were confirmed (8 observations); 0 symbol readings were verified; 2 claims were contradicted | Disclosed |
| Blueprint highlights show where findings are | No. Outlines on the plan come from PDF vector geometry, not from a model | Not claimed |
| The export is a bid | No. NOT BID READY, FICTIONAL, with named qualified assumptions | Disclosed |
| Bid Desk answers come from an Evolus agent | No. The Bid Desk chat is simulated and labelled SIMULATED. Two real Evolus workflow executions (2026-10-14) are recorded in `release_evidence/`: one completed, one failed (see [docs/STATUS.md](docs/STATUS.md); the failed run has a trace only) | Disclosed |
| Accessibility conformance | Not claimed. The gate dialogs are not fully modal for keyboard users | Disclosed |

## Built with AI, checked by a separate AI

Built with AI coding assistants under human direction and review. A separate AI verifier checked the pricing against a private answer key it built independently. Commits are authored as Iowa Fence Inc.

## History

The history was rewritten once to remove a personal surname; see [docs/HISTORY.md](docs/HISTORY.md).

## Quick start

Requirements: Python 3.12, Node 22, and `pdftotext` (poppler-utils).

**First, install the PDF text extractor** the addendum upload uses: `sudo apt-get install -y poppler-utils` (Debian/Ubuntu) or `brew install poppler` (macOS). Without it, uploads are refused with `PDF_TEXT_UNAVAILABLE`.

```sh
# 1. Engine (standard library only), serving the DP-001 scope
export ENGINE_API_KEY="$(python3 -c 'import secrets;print(secrets.token_hex(24))')"
export ENGINE_DEMO_ROUTES=1 ENGINE_HOST=127.0.0.1 PORT=8099
export ENGINE_ADDENDUM_MODE=recorded GATEHOUSE_CAPTURE_DIR="$PWD/hosting/captures"   # replay the stored AMD capture; no AMD call, no credentials
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

With those two engine variables set, uploading `samples/public-demo/dp001/ADDENDUM_02.pdf` at the Scope Gate reaches **PROPOSED**: the Before and After rows appear and the addendum waits for a named person to accept. The parse is a replay of the stored capture, so **no AMD call is made** and no AMD credential is needed. Without `ENGINE_ADDENDUM_MODE=recorded` the engine uses its live parser, which needs an AMD credential.

Use new random values; never commit `.env.local`. The generic demo scope instead of DP-001: `python3 -m api.server`.

### Configuration

| Variable | Used by | Purpose |
|---|---|---|
| `ENGINE_API_KEY` | engine, web | shared key between the proxy and the engine |
| `ENGINE_DEMO_ROUTES` | engine | `1` enables the anonymous demo routes the web app uses |
| `ENGINE_HOST` | engine | bind address; set `127.0.0.1` so only the local web tier can reach the engine (the default is all interfaces) |
| `PORT` | engine | engine port (default 8080) |
| `ENGINE_ADDENDUM_MODE` | engine | `recorded` replays the stored Addendum 02 capture (no AMD call); unset uses the live parser |
| `GATEHOUSE_CAPTURE_DIR` | engine | directory of stored captures; for the replay use `hosting/captures` in this repository |
| `ENGINE_BASE_URL` | web | where the proxy reaches the engine |
| `SESSION_SIGNING_SECRET` | web | signs the anonymous demo cookie (≥ 32 characters) |
| `DP001_DIR` | web | the `dp001/` directory (registry, scope draft, AI findings ledger) |
| `DP001_DOCUMENTS_DIR` | web | optional; PDFs default to `samples/public-demo/dp001/` |
| `GATEHOUSE_RATEBOOK_DIR` | engine | optional private rate-book store (never committed) |
| `AMD_TOKEN_FACTORY_API_KEY` | optional live tool only | read from the environment or `~/.config/ifi-amd/token_factory.env`; not needed for anything above |

## Tests

Current results: engine suite 773 passed, 0 failed, 3 skipped (the PDF-indexing tests that need PyMuPDF); web suite 144 of 144 on the build workstation; 141 passed and 3 skipped on a clean checkout (three Evolus audit tests need local evidence folders that are not in this repository); TypeScript clean; repository policy 16.

```sh
python3 harness/run_safe_suite.py .                      # backend suite (3 PDF tests skip without PyMuPDF)
python3 -m unittest tests.test_repo_policy               # repository guardrails

pip install -r requirements-amd.txt                      # pypdfium2, pillow
export PYTHONPATH=amd_experiment
python3 -m unittest amd_bridge.test_bridge amd_bridge.test_flight_trace spatial_plan.test_plan spatial_plan.test_executor
python3 -m unittest discover -s amd_experiment/tests
python3 -m amd_bridge.flight_trace --check               # recorded trace equals an offline rebuild
python3 demo/snapshot.py --verify                        # source, frozen AMD evidence and key asset hashes (exit 0)

cd web && npm run typecheck && npm run test:flight       # web suite
```

The AMD ledger `dp001/ai_findings.json` can be rebuilt offline (no network, no AMD client): `python3 -m amd_bridge.ledger`. Its output is hash-pinned.

## Development tools

The scripts under e2e/ and the walkthrough scripts under demo/ were written against earlier versions of the UI. They are kept for reference and are not maintained for the shipped build; some selectors are stale and they may fail. The hosted demo and the Quick start above are the supported ways to run Gatehouse.

## Hosting and the AI Flight Recorder

[`docs/HOSTING.md`](docs/HOSTING.md) is the hosting plan and deployment security review (one container, one instance; `hosting/Dockerfile`). The in-app **AI Flight Recorder** and its trace contract: [`docs/FLIGHT_RECORDER_CONTRACT.md`](docs/FLIGHT_RECORDER_CONTRACT.md); rebuild the recorded trace offline with `python3 -m amd_bridge.flight_trace`; web contract tests: `cd web && npm run test:flight`. Demo route: [`demo/DEMO_ROUTE_V2.md`](demo/DEMO_ROUTE_V2.md).

The hosted demo replays a stored capture of a real Qwen3.8-27B call on the AMD Token Factory; a local stack can perform one authorized live parse. Gemma is not implemented. Two real Evolus workflow executions (2026-10-14) are recorded in `release_evidence/`: one completed, one failed (see [docs/STATUS.md](docs/STATUS.md); the failed run has a trace only). They are shown read-only in the AI Flight Recorder; `tools/evolus_client.py` is mock-mode and not wired into the demo. The image defaults to 12 new demos per hour per visitor; the hosted demo sets 120 through an environment variable (`NEW_DEMOS_PER_HOUR`). The hosted image is built from `hosting/Dockerfile`. The root `Dockerfile` builds the engine only and is what CI builds.

## The 150-second walkthrough

[`demo/DEMO_SCRIPT_150_SECONDS.md`](demo/DEMO_SCRIPT_150_SECONDS.md), [`demo/DEMO_SHOT_LIST.md`](demo/DEMO_SHOT_LIST.md) and [`demo/DEMO_PREFLIGHT.md`](demo/DEMO_PREFLIGHT.md) describe the six scenes. Known limits: [`demo/DEMO_LIMITATIONS.md`](demo/DEMO_LIMITATIONS.md).

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
| `tests/`, `e2e/`, `harness/` | unit tests, e2e scripts (see Development tools), safe test runner |
| `run/`, `demo/` | start scripts; walkthrough tooling and documents |
| `docs/` | architecture, workflow, status, contracts, [about the history](docs/HISTORY.md), [third-party notices](docs/THIRD_PARTY.md) |
| `evolus/`, `tools/evolus_client.py` | Evolus agent instructions; the REST client in `tools/` is mock-mode and not wired into the demo. Two real Evolus workflow executions (2026-10-14) are recorded in `release_evidence/`: one completed, one failed (see [docs/STATUS.md](docs/STATUS.md); the failed run has a trace only), and shown in the AI Flight Recorder |

## Licenses and security

Third-party licenses and the optional AGPL PDF dependency: [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md). Security model and reporting: [SECURITY.md](SECURITY.md). Contribution and repository rules: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

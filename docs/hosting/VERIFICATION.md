# Hosting candidate verification (2026-10-14)

Candidate branch `hosting/judge-demo`, based on canonical `main` `5bf7dec5316344504e1ffa06b7f6bdf8763c47f8`. Local only; not pushed, not deployed. The frozen demo (`~/ifi-gatehouse-demo-lock`, 5071/8099) and the accepted build (5051/8098) were not touched; they answered 200 throughout.

## Runs (all local, Docker image `hosting/Dockerfile`, ports 18200-18203; nothing on the frozen ports)
| Check | Result |
|---|---|
| Flight Recorder browser test, plain image | 10 step groups PASS |
| Flight Recorder browser test, with fixture traces mounted (one valid SIMULATED Evolus trace, one invalid trace) | 10 step groups PASS: valid trace shown as SIMULATED, invalid trace REJECTED and not displayed |
| Existing suites against the container: API ai-findings, API footing, ai_bridge 14, footing 18, takeoff 7, dp001 8, viewer stability 11 | all PASS (same step counts as the October 13 acceptance); run twice, the second time on the final image |
| `e2e_pass6` (needs the generic engine, so run natively on separate ports) | 15 steps PASS |
| Backend safe suite (`harness/run_safe_suite.py`) | 565 run, 562 passed, 0 failed, 3 skipped (PyMuPDF) |
| Repository policy tests | 16 OK |
| AMD bridge + flight-trace + spatial plan + executor (clean venv) | 36 OK |
| Flight Recorder contract tests (`npm run test:flight`, Node, no network) | 18 pass |
| `python3 -m amd_bridge.flight_trace --check` | recorded trace equals a fresh offline rebuild |
| Web typecheck and production build | pass |
| Security probes | see docs/HOSTING.md |

## Defects found and fixed during this work
1. The human-authorization layer first read audit fields that do not exist and showed the system `start` entry as a human decision with a fabricated 1970 timestamp. Now only named-actor entries are shown and a missing timestamp stays null. Tests added.
2. A merged Evolus layer kept the sentence "No Evolus workflow execution has been recorded" beside real events. Fixed, tested.
3. Escape closed both the recorder and the Scope Gate behind it. The recorder now handles Escape in the capture phase.
4. The classic Docker builder ignores per-Dockerfile ignore files and applies root-anchored patterns, so a nested `web/.env.local` would have entered the image. Root `.dockerignore` is now recursive for env files, keys and test files; proven with a canary file.
5. The proxy trusted a forgeable `X-Forwarded-For`. `CLIENT_IP_HEADER` (fail-closed) added and tested.
6. Two of my own tests were too broad (matching explanatory sentences) and two image builds were stale when first tested; both corrected.

## Small non-authority changes to existing code
`api/server.py`: optional `ENGINE_HOST` (default unchanged, all interfaces). `web/lib/limits.ts`: optional `CLIENT_IP_HEADER`. `web/lib/demo.ts`: `NEW_DEMOS_PER_HOUR` (default 12) and the `flightRecorder` read-only handler. `web/app/page.tsx`: one sidebar entry and one component mount. No pricing, quantity, scope, release or evidence-classification code was changed.

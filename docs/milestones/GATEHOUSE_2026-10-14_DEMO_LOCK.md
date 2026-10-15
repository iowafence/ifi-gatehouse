# Gatehouse milestone: evidence-gated demo lock (2026-10-13 work, checkpointed 2026-10-14)

**Status: PRIVATE CHECKPOINT. Not a release.** Fictional demonstration data only. `bid_ready` is `false` in every priced state.
Branch `milestone/2026-10-14-demo-lock`, based on `main` at `f001c0999d956d6fc360a501660fe6cde852a5f5`. The repository was confirmed PRIVATE before this commit.
The source tree lives under `gatehouse-demo-lock/` (a packaging prefix: the workspace has its own `engine/`, `web/`, `dp001/` directories that would collide with the repository root). Nothing outside `gatehouse-demo-lock/` and `docs/milestones/` was changed.

## 1. October 13: start of day versus end of day

| | Start of day | End of day |
|---|---|---|
| Pricing / workflow | Accepted "Pass 6" Scope → Labor → Release workflow with deterministic pricing | Same workflow plus the accepted footing amendment (`footing-scope.v1`, `footing-calc.v1`, `footing-schedule.v1`) |
| DP-001 in the browser | Synthetic bid package opened beside the Scope Gate; takeoff reconciliation could not produce a final footing number (gate G3 unresolved, Base net quantity UNKNOWN) | Provisional footing schedule by class, two explicit G3 workflows, takeoff review gated before release |
| AI evidence | None in the product | Offline AMD-findings ledger with per-finding verification, human accept/reject/defer and a scope-impact preview |
| Spatial claims | None | One authorized live test (Spatial Test 003) ingested offline; a contradicted claim is blocked by the product |
| Demo | None | Six-scene 150-second walkthrough, three rehearsals, recording and screenshots (kept local) |

The start-of-day column is reconstructed from the working record and the browser test suites. The partner EOD/morning handoff document has **not** been transferred to this machine and is not included (see section 12).

## 2. Accepted Pass 6 and the footing amendment

* The footing engine takes `footing-scope.v1` and returns `footing-calc.v1` / `footing-schedule.v1`, with per-run footing classes. Base / Alternate A-1 counts: A line 43 / 35, A corner 4 / 4, G1 and G2 gate posts 6 / 6, G3 posts 2 / 2 (unresolved), B line 18 / 12, B terminal 6 / 4; auger holes 79 / 63. Known-class concrete 7.9566 CY (Base) and 6.7308 CY (Alternate), with G3 excluded as UNKNOWN, never zero.
* Engine posture fields shown in the Takeoff, Estimate and Release views: `bid_ready`, `release_class`, `footing_release_class`, and `artifact_kind` (present in the release response only).
* The takeoff review digest binds the engine's schedule hashes. Release requires a current takeoff review and acknowledgement of non-hard blockers. A stale scope version, proposal digest or takeoff digest is rejected.

## 3. DP-001 real-document browser integration

The four synthetic DP-001 PDFs (drawings, project manual, instructions to bidders, Addendum 01) are rendered in a stable C101 viewer beside the Scope Gate. Evidence chips jump to the page and highlight. The viewer does not re-render on project, scope or pricing updates (11 viewer-stability checks, including 375 px).

## 4. Provisional footing schedule and conditional pricing

Reference totals are **conditional** and reproduce only under the self-declared G3 what-if (12 ft opening, 2.875 in OD post, 16 × 48 in footing) **and** the reference crew plan (CR13 preferred, CR13 drilling):

| | Total |
|---|---|
| Base Bid | $54,284.69 |
| Alternate A-1 | $45,771.50 |

Other crew choices price Base differently: CR11 $51,554.05, CR12 $55,513.85, CR14 $56,363.69. Values come from the engine; the tests compare them with the accepted reference and never inject them. Without the G3 what-if the product shows a partial known cost, listed unknown exposure and NOT BID READY.

## 5. AMD evidence ledger and the contradicted Type B finding

* `dp001/ai_findings.json` (sha256 `1faf2c2f…baa76`) is built offline from stored model outputs. No AMD client is imported by the bridge; sockets are blocked in the build, and `LIVE_CALLS_DISABLED` stays in force.
* 10 real AMD attempts are recorded; 32 real findings plus 2 labelled simulated items that exercise guards. 14 findings come from a different 34 × 22 drawing file and cannot be accepted into DP-001.
* **Spatial Test 003** (DeepSeek-V4.1-Flash, 3 sequential crops at 200 dpi, plan hash `784c93c8…b96d`): gate-label localization scored 7/7; gate-symbol relationships verified 0; fence-type tag A leader confirmed by vector geometry; **tag B**: the model said "clear" that the leader ends on the perimeter fence, but the drawing's vector evidence shows it ends on an interior divider end post. The finding is classified `AI CLAIM CONTRADICTED BY DRAWING EVIDENCE`, acceptance is refused in the UI, and the API returns **409 `CONTRADICTED_BY_DRAWING_EVIDENCE`**. A keynote was reported as a type tag (false candidate); two crops clipped or omitted the gate symbol they were asked about. The predefined success criterion was **not met**.
* Preview rules are classification-driven. The only mutation route is `scope/resolve` with `approve_inferred` on an open inferred gate-station exception; gate positions and vector-confirmed Type A are evidence-only (`no_scope_change`).

## 6. Qualified, non-bid-ready release semantics

A release is possible only as a qualified fictional demonstration: banner **NOT BID READY — FICTIONAL DEMONSTRATION ONLY**, `bid_ready: false`, `artifact_kind: QUALIFIED_FICTIONAL_DEMONSTRATION`. No bid wording, no PDF, no authorize button, a second release is refused, and a client-supplied `bid_ready` is rejected. Names are self-declared and unauthenticated; nothing here is a durable production approval.

## 7. Demo-lock workspace

The candidate (web 5071, engine 8099) is the accepted build (web 5051, engine 8098) plus one presentation sentence on the top banner (it used to say no AI document inference is connected, contradicting the AI Findings panel) and a `DEMO_URL` switch in the test tooling. Both are enumerated in `demo/snapshot.py` (`PRESENTATION_CHANGES`). `python3 demo/snapshot.py --verify` compares the tree with the accepted workspace after port/path normalization.

## 8. Local startup procedure (fresh checkout)

The run scripts address the workspace as `~/ifi-gatehouse-demo-lock`.

1. `git checkout milestone/2026-10-14-demo-lock`, then `ln -s "$PWD/gatehouse-demo-lock" ~/ifi-gatehouse-demo-lock`.
2. Restore the local-only assets listed in `GATEHOUSE_2026-10-14_ARTIFACT_MANIFEST.md` and verify their hashes.
3. Create `run/engine.env` (`ENGINE_API_KEY`, `ENGINE_DEMO_ROUTES=1`, `PORT=8099`) and `web/.env.local` from `web/.env.example` (`ENGINE_BASE_URL=http://127.0.0.1:8099`, `ENGINE_API_KEY` equal to the engine's, `SESSION_SIGNING_SECRET` at least 32 random characters, `DP001_DIR` set to the `dp001` directory). Use new random values; never commit them.
4. `cd web && npm ci && cp node_modules/pdfjs-dist/build/pdf.worker.min.mjs public/ && npx next build`.
5. `bash run/start_engine_dp001.sh` (engine serving the DP-001 scope) and `bash run/start_web.sh` (web on 127.0.0.1:5071).
6. Demo tooling: `python3 demo/stage.py A B C` then `python3 demo/present.py`; checklist in `demo/DEMO_PREFLIGHT.md`, narration in `demo/DEMO_SCRIPT_150_SECONDS.md`, scene list in `demo/DEMO_SHOT_LIST.md`. Playwright and Chromium are needed for the browser tooling.
7. `e2e/e2e_pass6.py` needs the generic Pass 6 engine (`bash run/start_engine.sh`) instead of the DP-001 engine. `e2e/e2e_takeoff.py` needs the external independent takeoff reference (see the manifest). Restart the web server between suites (the proxy allows 12 new demo projects per hour per IP, in memory).

The engine was exercised on Python 3.12; `requirements-pdf.txt` lists the optional PDF dependency (3 PDF-indexing tests skip without PyMuPDF). The AMD bridge tests and `demo/snapshot.py` need the experiment interpreter and directory named in the manifest.

## 9. Rehearsal results (October 13, demo lock)

| Rehearsal | Result |
|---|---|
| Fresh-session functional, 1800 × 732 | 26/26 checks; scene action times 4.6 / 0.9 / 3.8 / 1.9 / 6.7 / 4.1 s; 0 external requests |
| Timed 150 s, recorded at 1920 × 1080 | 26/26 checks; 150.0 s; 507 viewer samples, 0 blank or overlay frames; Base and Alternate matched the references |
| Recovery after Reset demo | 26/26 checks |

Automation runs at machine speed; a person following the shot list needs roughly 1.5 × the action time. Narration is about 334 words (about 134 wpm).

## 10. Test counts

| Check | Demo lock, Oct 13 | This checkpoint, re-run Oct 14 on a separate scratch copy (separate ports) |
|---|---|---|
| Backend, safe filtered runner | 628 discovered, 1 excluded by name, 627 run: 624 passed, 3 skipped, 0 failed | 549 discovered and run: 546 passed, 3 skipped, 0 failed. The 79 fewer tests are those in the two unshipped test files (63 + 16) |
| Browser: ai_bridge / footing / takeoff / dp001 / viewer stability / pass6 | 14 / 18 / 7 / 8 / 11 / 15 | 14 / 18 / 7 / 8 / 11 / 15 |
| HTTP API suites (AI findings, footing) | pass | pass |
| Spatial plan + executor | 12 OK | 12 OK (executor restored in the scratch copy only) |
| AMD bridge unit | recorded as "17 OK" | 17 OK **only when the evidence copy is present**; see the correction below |

**Correction to the October 13 report.** The demo-lock workspace's own saved bridge-test output shows `FAILED (errors=1)`: `test_manifest_and_plan_hashes` needs `evidence/spatial_test_003_runs/`, which exists in the accepted AMD-bridge workspace (17 OK there) but was never copied into the demo-lock workspace. It is a missing-evidence-directory condition, not a code defect, and it passes once the directory is present (verified here). The October 13 summary that listed it as 17 OK for the candidate was inaccurate.

Test-runner note: the safe runner (`harness/run_safe_suite.py`) names no excluded test and refuses to run if any shipped test references a private location. This is the only source change from the demo lock.

## 11. Known operational limitations

Full list in `demo/DEMO_LIMITATIONS.md`. Summary: no live AMD inference in the replay; real spatial understanding is **not** demonstrated; not all findings are verified; DP-001 is not bid-ready (G3 unresolved, draft quantity ruleset, flat rates); reference totals are conditional; identity is self-declared; web-session state (takeoff-review attestations, AI decision marks, `artifact_kind`) lives in web-server memory and engine projects live in engine memory (6 h idle expiry); a web restart removes `artifact_kind` display for a released project and the takeoff-review attestation for an unreleased one (re-stage instead); an engine restart removes all projects. These restart behaviours were documented, not changed, because they concern authority display.

## 12. Pending and not integrated

* **Evolus / Gemma:** pending, not integrated. The repository contains only the Evolus REST client with a mock mode and the agent instruction text; no Evolus or Gemma output feeds the demo, the ledger or any price.
* **Partner EOD/morning handoff:** not transferred to this machine; not included, and no substitute has been written.
* **Public submission and partner-track eligibility:** pending and **not authorized**. This checkpoint is private-branch history only. It contains proprietary engine source (reviewed path by path for the private checkpoint only) and must not be used for a public submission without separate approval and a public-release review.

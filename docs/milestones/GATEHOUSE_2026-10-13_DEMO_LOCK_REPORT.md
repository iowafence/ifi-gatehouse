> **Historical record.** Written on 2026-10-13/14 inside the original demo-lock workspace; the paths, ports and the "accepted build" fallback it mentions refer to that workstation and are not part of this repository. Run instructions: README quick start. Corrections made later are in `GATEHOUSE_2026-10-14_DEMO_LOCK.md` (see its section 10: the bridge-test count).

# Hackathon demo lock — final report (October 18 build)

**Demo URL: `http://127.0.0.1:5071/`** (demo-lock candidate; engine `127.0.0.1:8099`) · workspace `~/ifi-gatehouse-demo-lock` · fallback `http://127.0.0.1:5051/` (accepted build, untouched, sessions staged in `demo/staged_5051/`).
Candidate = accepted build + ONE presentation sentence + a `DEMO_URL` switch in test tooling (verified by `demo/snapshot.py --verify`: all other 191 source files identical after port/path normalization; 24 frozen AMD evidence files and the ledger/workbook/PDF hashes unchanged). No AMD request, Git write, deployment or private access occurred; `LIVE_CALLS_DISABLED` is in force; the accepted workspace, the footing workspace and the AMD experiment directory have no files modified.

## Verdicts
* **JUDGE DEMO: GO**
* **COLD START: GO** (staging 3 sessions takes ≈45 s; documented restart limits and recovery routes below)
* **EVIDENCE INTEGRITY: GO**
* **150-SECOND PRESENTATION: GO** (scripted sequence fits 150.0 s; narration is 334 words ≈ 134 wpm; cut-list provided)

## Rehearsal results (all runs: 26/26 checks, 0 external requests, 0 console errors, 0 blank/overlay viewer frames)
| Rehearsal | Setup | Scene action time (s) 1·2·3·4·5·6 | Total |
|---|---|---|---|
| 1 Fresh-session functional | no stored state, nothing pre-selected, everything built through the UI, 1800×732 visible scrollbars | 4.6 · 0.9 · 3.8 · 1.9 · 6.7 · 4.1 | 22.0 s of actions (43.8 s incl. building the priced session) |
| 2 Timed 150 s (recorded) | pre-staged sessions, 1920×1080, paced to the scene budgets | active 7.8 · 5.9 · 10.1 · 5.5 · 13.3 · 11.5; scenes held to 20 · 25 · 30 · 25 · 30 · 20 | **150.0 s** (157 s of video incl. intro/outro) |
| 3 Recovery after reset | used session → **Reset demo** → scenes 1–4 → re-stage B → scenes 5–6, 1800×732 | 4.6 · 0.9 · 3.8 · 1.9 · 6.8 · 4.1 | 22.1 s of actions (47.1 s wall) |
Automation action time is machine speed; a human clicking the shot list takes roughly 1.5×. The timed run proves the full story (including the real API 409, the human accept, four-crew comparison, release) fits the 150-s frame with narration windows; the cut-list in the shot list covers a slow presenter.
Measured values come from the app/engine and are *compared* with the accepted conditional references, never injected: Base **$54,284.69**, Alternate A-1 **$45,771.50** (identical to the references) under the self-declared G3 what-if and CR13 reference plan; the four-crew sweep shows CR11 $51,554.05 · CR12 $55,513.85 · CR13 $54,284.69 · CR14 $56,363.69 (a different crew choice prices differently — explained on stage). Holes 79 vs 63; release classification NOT BID READY — FICTIONAL DEMONSTRATION ONLY, `bid_ready: false`, `artifact_kind` QUALIFIED_FICTIONAL_DEMONSTRATION after the release click.

## Artifacts (`~/ifi-gatehouse-demo-lock/demo/`)
`DEMO_SCRIPT_150_SECONDS.md` · `DEMO_SHOT_LIST.md` · `DEMO_PREFLIGHT.md` · `DEMO_EVIDENCE_MANIFEST.md` (generated) · `DEMO_LIMITATIONS.md` · `DEMO_SNAPSHOT_MANIFEST.json` (191 source files + key/frozen hashes) · **recording `recording/GATEHOUSE_DEMO_150s_1080p.mp4`** (1920×1080, 25 fps, silent; `.webm` original beside it; frames `frame_*s.png`) · `screenshots/` (13 PNGs: Type B contradiction in the PDF, blocked acceptance in the UI, real API 409, human review preview, scope-version change with G3 unresolved, takeoff Type A vs B, Alternate 63 holes, four-crew comparison, Alternate total, NOT BID READY release gate, release record with `artifact_kind`, project/provenance scenes) · rehearsal folders with `result.json` per run · tooling `stage.py`, `present.py`, `run_demo.py`, `snapshot.py`, `make_evidence_manifest.py`.
The recording and screenshots carry two harness-only overlays (scene caption, red “actual API response” box); the app has no such elements.

## Integrity verification
Source drawing `62ab61d7…c525` ✓ · workbook `3d431204…8dde8f1` ✓ · ledger `1faf2c2f…baa76` identical to the accepted workspace ✓ · frozen AMD evidence (Test 001/002 manifests in the experiment, Test 003 manifest in the bridge): 24 files ✓ · frozen plan `784c93c8…` ✓ · hold file present ✓. Regression on the candidate: bridge unit 17 OK · spatial plan/executor 12 OK · browser: ai_bridge 14, footing 18, takeoff 7, dp001 8, viewer stability 11, pass6 15 — all PASS · safe backend runner 627 run / 624 passed / 3 skipped / 0 failed (private-workbook test excluded) · harness v6 14/14.

## Bugs / issues found and what was done
1. **Contradictory banner (fixed, presentation-only):** the top notice said “no AMD or other AI document inference is connected” beside an AI Findings panel. Candidate text now says AI Findings are stored AMD outputs replayed offline and never author the draft. Accepted build 5051 keeps the old wording (documented fallback).
2. **Viewer centring (harness-only):** the first recording left the Type B marks off-screen; the harness now centres them (scroll container is `.viewer-stage`).
3. **Staging rate limit (operational):** repeated rehearsals hit the 12-new-demos/hour proxy limit on the candidate; restarting the *candidate* web server resets it. On the live demo: stage once, don't loop.
4. **Restart limits (documented, NOT changed — authority display):** after a web restart a released project no longer shows `artifact_kind` (banner reads “issued … only when a release is recorded”; `bid_ready`/`release_class` remain engine-derived); an unreleased staged project loses its takeoff-review attestation so Release is disabled until the review is re-recorded (tested, ≈20 s); an engine restart drops all projects. Workaround: never restart between staging and presenting; re-stage instead. No value is fabricated.
5. Stale-scene noise: nothing else material; no flashing viewer frames in any rehearsal (507 samples in the timed run).

## What still needs manual interaction
Starting/confirming services (already running), `stage.py` + `present.py` before the session, typing a name/note in scenes 4 and 6 (self-declared), the console one-liner for the live 409 (or point at the disabled Accept and the recording), and re-staging between judges (≈30 s). Headed windows were smoke-tested under a virtual display only.

## Fallback if something fails live
Switch to the other staged window/URL (5051); re-stage (`python3 demo/stage.py A B C`); or play the 1080p recording with live narration; or walk `screenshots/` in script order. Never restart the accepted services mid-demo.

## Claims the demo does NOT make
Real spatial understanding demonstrated · gate symbols reliably classified · all 32 real findings verified · DP-001 bid-ready · authenticated/durable approvals · live AMD inference during the replay.

## Housekeeping note
Files are never deleted, so superseded intermediate rehearsal folders (`rehearsal_timed`, `_final`, `_final2`, `_final3`, `rehearsal_functional`, `rehearsal_recovery`, `shots/`, `video/`) and older frames in `recording/` (`frame_14s`, `_38s`, `_52s`, `_61s`, `_62s`, `_130s`, `_135s`, `_152s`) remain on disk. The authoritative set is: `rehearsal_timed_FINAL/`, `rehearsal_functional_final/`, `rehearsal_recovery_final/`, `screenshots/`, `recording/GATEHOUSE_DEMO_150s_1080p.*` and `recording/frame_{12,35,62,100,120,140}s.png`.

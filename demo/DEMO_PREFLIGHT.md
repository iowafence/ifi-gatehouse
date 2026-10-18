# DEMO_PREFLIGHT — five-minute setup and recovery

> **Note:** The scripts under e2e/ and the walkthrough scripts under demo/ were written against earlier versions of the UI. They are kept for reference and are not maintained for the shipped build; some selectors are stale and they may fail. The hosted demo and the README Quick start are the supported ways to run Gatehouse.

**Demo URL: `http://127.0.0.1:5071/`** (web 5071, engine 8099 serving the DP-001 scope; start both as described in the README quick start).
**Fallback:** the recorded walkthrough or the screenshots (published separately, not in this repository); or prepare the three windows again by hand.
Tooling lives in `demo/`. Run everything from the repository root.

## T-5 min — checks (30 s)
```bash
curl -s http://127.0.0.1:5071/api/demo/health            # {"engine":"responsive"}
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5071/   # 200
python3 demo/snapshot.py --verify                        # source, frozen AMD evidence and key asset hashes (exit 0)
ls amd_experiment/LIVE_CALLS_DISABLED                     # the hold must exist: no live AMD call is possible
```
## T-4 min — prepare the three windows by hand
The staging and presenter scripts (`stage.py`, `present.py`) do not work on the shipped build, so set the windows up through the UI: A = Scope gate, Base selected · B = Base priced, takeoff reviewed, waiting at Release · C = Alternate A-1 priced, waiting at Release. Use the real UI; the engine produces the prices. Use a fresh browser profile for any extra window: cookies are shared across ports on 127.0.0.1.

Page zoom 100%, window ≥1800×732, classic scrollbars visible.

## T-2 min — verify what judges will see
* Window A: Scope Gate drawer, **AI Findings** present (“Real AMD attempts recorded: 10”), banner **SCOPE REVISION v2**.
* Window B: Release gate for Base (total shown by the engine; readiness banner **NOT BID READY — FICTIONAL DEMONSTRATION ONLY**).
* Window C: Release gate for Alternate A-1.

## During the demo
Follow `DEMO_SHOT_LIST.md`. If you run late, cut the items marked “Cut if late”.

## Resetting for the next judge (≈25 s)
* Scenes 1–4: in window A click **Reset demo** (fresh project) then select the Base Bid in the Scope gate (“Which bid should be priced” → Base) and reopen window A.
* Scenes 5–6: window B/C are consumed by the release click → prepare windows B and C again by hand.

## Recovery table
| Symptom | Cause | Fix |
|---|---|---|
| “Too many new demos from this network” | proxy limit 12/hour/IP (memory) | wait, or restart the *web* server only when no live window is in use, then prepare the windows again |
| Release button disabled, “No takeoff review recorded” | web server was restarted (attestations are in memory) | Takeoff Review → name + note → **Record takeoff review** (≈20 s); tested |
| Released project’s banner says `artifact_kind` “issued … only when a release is recorded” | web restart after release; the engine’s release response is not retained | cosmetic and documented; `bid_ready`/`release_class` remain engine-derived. Prepare B again instead of presenting that session; never invent a value |
| “Your demo session expired” / fresh project | engine restarted (all projects lost) | prepare windows A, B and C again |
| Viewer shows “Opening document…” longer than 2 s | cold PDF load | wait; reload the window once (cookies persist) |
| Anything unrecoverable | — | play `demo/recording/GATEHOUSE_DEMO_150s_1080p.mp4` (narrate over it) or walk the screenshots in `demo/rehearsal_timed_FINAL/shots/` |

**Never** restart the services mid-demo; staging and reset need neither a restart nor any change to the engine.

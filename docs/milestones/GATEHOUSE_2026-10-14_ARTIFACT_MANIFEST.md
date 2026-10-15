# Gatehouse 2026-10-14 demo lock: local artifact manifest

This checkpoint deliberately does not contain every file the demonstration needs. This manifest lists what is left out, why, and how to restore it.
Hashes are recorded only for permitted synthetic or public assets. Paths are relative to the demo workspace root (`gatehouse-demo-lock/` in this checkout).

## A. Synthetic assets that must be restored locally (hashes recorded)

| Path | Why it is not in Git | SHA-256 |
|---|---|---|
| `dp001/documents/DP001_Drawings_IFB_Rev0_ANSI_B.pdf` | Repository policy ignores `*.pdf` (documents live under `samples/public-demo/` only after review). Marked "FICTIONAL SYNTHETIC DEMONSTRATION". | `62ab61d7f2558245f4a6f1708d9320a49e66fd28bf829a2329be5b79db9ac525` |
| `dp001/documents/DP001_Addendum_01.pdf` | same | `390ffe093029fb89a9e498da4ba4e46f5600690bc05ecc7717c91607fc185deb` |
| `dp001/documents/DP001_00_0200_Instructions_to_Bidders.pdf` | same | `c2fe76dd3cf57cf7c01115d53ffcfc88cbe9aa899c3986b4c8032a7c9f631c19` |
| `dp001/documents/DP001_Project_Manual.pdf` | same | `9fe8c8942c453ac911abeda54d5e9be64b1bd8186d1eeba08b527e8270d0377a` |
| `engine/config/ratebook_reference_2.3.0.fictional.xlsx` | Fictional pricing workbook; `.xlsx` is blocked in Git | `3d43120473c8db3840557d62397e5f4fc5669b7f2b3cf5a0c86005fc88dde8f1` |
| `engine/samples/ratebook/IFI_Gatehouse_Rate_Book_REFERENCE_FICTIONAL_v2.xlsx` | same file, second location | `3d43120473c8db3840557d62397e5f4fc5669b7f2b3cf5a0c86005fc88dde8f1` |
| `engine/legacy_fixtures/legacy_3crew_testbook.fictional.xlsx` | Fictional test workbook; `.xlsx` blocked | `2d382bb2c50de4bc000e5659b36a937aa9f78ad66e84fc942881846abd419ed1` |
| `web/public/pdf.worker.min.mjs` | Vendored copy of the `pdfjs-dist` worker (regenerable): `cp node_modules/pdfjs-dist/build/pdf.worker.min.mjs web/public/` | `1baa1844c89c80a5b2797c916e75ab29254be46d8e9cb53cb6364d7aad84be36` |
| `spatial_plan/crops/r1_north_band_gates_and_tag_200dpi.png` | Rendered output (regenerable with `spatial_plan/build_plan.py`) | `d51cf19e0b13f6cbcf3864a11e8c9e7af2e182d226776b82aeaab2f12df4e930` |
| `spatial_plan/crops/r2_east_edge_type_tag_and_gate_200dpi.png` | same | `57e3f3218ae8cd1cb0692c9175837cf0625e2850778beafa2ca3a3ffbbb3d288` |
| `spatial_plan/crops/r3_west_edge_gate_200dpi.png` | same | `a467df4fe5594cd07d3d778e02036bb64638836478def3c2cc6ce66da8a963db` |

Included and pinned instead: `dp001/ai_findings.json` (the offline AI-findings ledger) `1faf2c2f30918ec753d5c036e9618e0fd62492707c9e099e17a25b623fcbaa76`;
`spatial_plan/SPATIAL_PLAN_003.json` plan hash (excluding its own field) `784c93c8d9457cf6c8005070c15280f1e2626588fccb4dc57a32759c7662b96d`.

## B. Stored AMD responses and evidence (not committed, no unrestricted evidence directories)

| Local path | Content | Needed for |
|---|---|---|
| `spatial_plan/runs_v3/` (11 files) | Raw stored responses, scoring and run metadata of Spatial Test 003. The per-file hashes are listed in the committed `spatial_plan/FROZEN_TEST003.json`. | `amd_bridge` test003 replay, `test_bridge.py` hash tests |
| `evidence/` (68 files) | Browser-suite outputs, acceptance reports, screenshots, the copy `evidence/spatial_test_003_runs/`, `evidence/ai_findings.before_test003.json` | 2 bridge tests, reporting |
| `~/ifi-amd-inference-experiment/` (outside this repository) | Experiment harness used offline for replay (`ext.pipeline`, `ext.spatial2`, `ext.validator`), the earlier frozen runs (Tests 001/002), the `LIVE_CALLS_DISABLED` hold and the interpreter with PDF rendering. The bridge never imports its AMD client. | Bridge unit tests, ledger rebuild, `demo/snapshot.py --verify` |

| `~/ifi-gatehouse-takeoff-pack/` (outside this repository) | `dp001_takeoff_review.py`, the independent reference implementation of the takeoff reconciliation that `e2e/e2e_takeoff.py` compares the app against. It is not part of this checkpoint. | Takeoff browser suite only |

## C. Never committed (secrets, session state, large or generated outputs)

* `web/.env.local`, `run/engine.env`: contain the local engine key and session signing secret. Create them from `web/.env.example` and the procedure in the milestone document.
* `demo/staged/`, `demo/staged_5051/`, `run/e2e_state_*.json`: browser storage state (session cookies).
* `demo/recording/`, `demo/screenshots/`, `demo/rehearsal_*`, `demo/shots`, `demo/video`, `*.log`: recordings, screenshots and regenerated output (about 176 MB).
* `web/node_modules/`, `web/.next/`, `web/tsconfig.tsbuildinfo`, `__pycache__/`: dependencies, build output, caches.
* `demo/DEMO_SNAPSHOT_MANIFEST.json`, `dp001/_parity_run.mjs`: generated on the workstation and containing absolute local paths; regenerate with `python3 demo/snapshot.py` and `python3 dp001/parity_check.py`.
* Engine project stores: in memory only; they do not exist on disk.

## D. Deliberately omitted source (review items)

| Path | Reason |
|---|---|
| `engine/tests/test_ratebook_import.py` | A test file that is not part of this checkpoint. Not staged, not executed. `harness/run_safe_suite.py` stays fail-closed without it. |
| `engine/tests/audit_workbook_support.py`, `engine/tests/test_ratebook_containment.py` | Internal test support files that are not part of this checkpoint. Not staged. |
| `spatial_plan/run_live_003.py`, `spatial_plan/test_executor.py` | Live-inference executor and its loopback test; not integration code. The offline replay does not need them. |
| `engine/deploy/` | Droplet serving scripts (unused by the demo). |
| `engine/.github/`, `engine/.githooks/`, `engine/scripts/` | Duplicates of the repository-root tooling, inert under a subdirectory. |

No internal evaluation material was opened, hashed, copied or executed at any point in this checkpoint.

# DP-001 independent takeoff reference

`dp001_takeoff_review.py` is a small, deterministic reference derivation of the DP-001 nominal takeoff (gross fence length, gate-opening deductions, net Type A / Type B) written separately from the application. `e2e/e2e_takeoff.py`, `dp001/parity_check.py` and `dp001/engine_vs_reference.py` compare the app and the engine against it. It is **not** production pricing code and **not** an expected-answer file for any model.

* Inputs are the public synthetic DP-001 documents only.
* With gate G3 unresolved the reference returns formulas ("… − G3 width"), never a number. `DP001_TAKEOFF_REFERENCE_DEMO_ONLY.json` shows its output with G3 unresolved and with the demonstration-only 12 ft assumption.
* Tests: `python3 -m unittest dp001.reference.test_dp001_takeoff_review` (offline).

Imported on 2026-10-14 from an unversioned working directory; no earlier history exists.

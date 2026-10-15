# Engine interface contract `pricing-service.v1` (FROZEN for ANVIL 1)

Module: `engine/pricing_service.py`. Surface pinned by `docs/pricing/engine_interface.v1.json` and `tests/test_pricing_service.py::FrozenSurface`. Changing any name, key or code needs both agents to agree and a new `CONTRACT_VERSION`. `api/server.py` is **not modified** by this work; ANVIL 1 owns routes and the frontend adapter, this module owns every number.

Rules for the caller: never send or compute a price, wage, production rate, hour, total or digest. Pass only named-human decisions. `state` is the workflow project state; every decision call is atomic (a refusal leaves `state` byte-identical) and raises `GateError` with stable codes in the message.

## Functions
| Function | Purpose | Returns / raises |
|---|---|---|
| `import_ratebook(bytes, as_of=None)` | validate + normalize an .xlsx; fails closed | `ImportResult {ratebook (server-side only), ratebook_ref, data_classification, warnings, report}`; `RateBookRejected.problems=[{code,where}]` (no cell values) |
| `fleet_overview(rb)` | sidebar: every fleet crew + average | `{crews[{crew_id,description,profile_version,headcount,efficiency_pct,qualifications}], fleet_average_efficiency_pct, fleet_average_display ("95.3"), crew_count, basis}` |
| `crew_profiles(rb)` | stored profile of every priced crew | list of crew records + `headcount` |
| `task_eligibility(rb, task_id)` / `all_eligibility(rb)` | Labor Gate eligibility | `{task_id, task, required_roles, required_qualifications, crews[{crew_id, eligible, reasons[{code,role_key,role,qualification,message}], production_rate, rate_basis, is_default}]}`; `None` for an unknown task |
| `compare_crews(state)` | per task, per crew: hours, worker-hours, crew-days, cost, cost/unit | `{scope_ref: comparison}`; `{}` until quantities exist; marked provisional Standard until a plan exists |
| `provisional_labor(state)` | indicative labor with no approved plan | per scope: `{provisional:true, releasable:false, complete, lines[], provisional_labor_cost|null}` |
| `adopt_crew_plan(state, by, note, preferred_crew?, assignments?{task_id:crew_id}, use_default_for_unassigned=False, difficulty?{default, overrides?}, use_recommendation=False)` | adopt a (mixed) crew plan; engine recomputes labor, estimate, digest | `LaborResult`; `GateError` |
| `record_wage_decision(state, **record_wage_determination args)` | Davis-Bacon classification/wage/fringe decision | `LaborResult` (an incomplete record is stored and returns its blockers) |
| `recommend_difficulty(state, by, default, overrides?, evidence_refs, rationale?)` | cited recommendation; prices nothing | `LaborResult` |
| `labor_result(state)` | current engine view | `{contract_version, status, blockers[{code,question}], priced, crew_plan, crew_plan_version, scenarios{ref:{labor_subtotal, crew_hours, worker_hours, crew_days, calendar_duration:null, basis, lines, estimate_total}}, proposal_digest, ratebook_ref}` |
| `crew_plan_history(state)` | append-only plans, current last | versions strictly increase, never reused; retired plans carry `retired_reason` |
| `digest_is_current(state, digest)` | has a shown digest been invalidated | `{current, current_digest}` |

## Behaviour that is part of the contract
* **Fleet vs eligibility.** The sidebar lists fleet crews only (crews offered as per-task alternatives; if a book has none, every priced crew). It never drops a crew for a missing qualification; fictional reference book v2.3.0: Crew 1 (CR11) 104, Crew 2 (CR12) 94, Crew 3 (CR13) 88, Crew 4 (CR14) 97, unweighted average 95.75 (display `95.8`). Eligibility is per task: core drilling (`L02`, requires `R4`) returns Crew 1 (`CR11`) and Crew 2 (`CR12`) ineligible with `MISSING_REQUIRED_ROLE` (`R4`, "Equipment operator"); Crew 3 and Crew 4 eligible. **Use `crew_id`, not the label:** `CR1` is a legacy default crew; "Crew 1" is `CR11`.
* **No fabricated assignment.** A task with no selected crew is `CREW_NOT_SELECTED` unless the caller states `use_default_for_unassigned=true`. Unknown task/crew ids, ineligible crews, crews without a rate for the task, invalid difficulty: refused.
* **Provisional average** (display/indicative only): per task, the mean *cost* of the **fleet** crews eligible for that task and with cleared wage bases (drilling = mean of CR13 and CR14; legacy default crews such as `CR1` are never averaged); efficiency percentages are never averaged for cost; ineligible crews are excluded from that task only. Never releasable, never in a digest. A task nobody can do has no provisional cost and the total is `null`.
* **Hours vs money.** Efficiency, difficulty and `historical_calibrated` change hours only; calibrated rates never receive efficiency twice (`efficiency_applied:false`). Wages, fringes, employer costs are independent of both. Exact decimals, cents rounded half-up per line.
* **Crew-hours vs worker-hours** are separate fields. Job/crew totals report `crew_days` (effort) and `calendar_duration: null` (`NOT_MODELED`). Per-task `duration_days` is one task for one crew. **Do not display a sum of task durations as project duration.**
* **Versions and digests.** Any change to the plan, difficulty, a crew's profile version, production rates, wage decision, quantities, rate book or scope changes `proposal_digest`; the old one is refused at release. A changed crew profile voids the plan (moved to `crew_plan_history`).
* **Summary additions** the adapter may expose read-only: `crew_comparison`, `crew_plan`, `crew_plan_history`, `difficulty_recommendation`, `labor_result()`.

## Integration instructions for ANVIL 1
1. Import `engine.pricing_service as svc` in the route layer only. Do not import `pricing.*` from model-facing code (`tools/`, `evolus/`, `intake/`); a test enforces it.
2. Map routes 1:1 to functions (names in the table). Translate `GateError` to 409 with the message, `RateBookRejected` to 422 with `.problems`. Never return `ImportResult.ratebook`.
3. Authentication supplies `by`; the browser supplies `note` and the selections only.
4. Render `labor_result()`; do not recompute totals client-side. After every decision call, replace the whole project summary from `state`.
5. The existing `POST …/decisions/crew-plan`, `…/difficulty-recommendation`, `…/wage-determination` proposals in `API_CONTRACT_PROPOSAL.md` map to `adopt_crew_plan`, `recommend_difficulty`, `record_wage_decision`. Read endpoints for sidebar/eligibility map to `fleet_overview`, `task_eligibility`. These routes are still unimplemented and need APEX + NOVA agreement.

## Additive fields (v1-compatible; not part of the pinned surface)
`compare_crews()` candidates and crew rows gain `in_fleet`; candidates gain `reason_details[{code, role_key, role, message}]` (same shape as `task_eligibility` reasons) so the Labor Gate can grey out ineligible crews with the exact missing-role text; `task_eligibility` crews gain `in_fleet`. No name, key or code in `engine_interface.v1.json` changed.

## Assumptions made (flag for the owner)
1. Fleet membership = crews with `Crew_Production` rows (no explicit flag exists in layout v2). An `in_fleet` workbook column would be cleaner but changes the rate-book layout.
2. Provisional average = mean of eligible crews' per-task cost (unweighted). Weighting by availability is a business decision not made here.
3. Renamed aggregate `duration_days` to `crew_days` (was not yet exposed over HTTP).

## Still pending the owner's contractor approval (untouched)
Fitting and quantity rules (`pricing/data/quantity_rules.v1.json`, draft v1.0.0) remain **unapproved**; nothing here approves them. A release still needs the named ruleset approval.

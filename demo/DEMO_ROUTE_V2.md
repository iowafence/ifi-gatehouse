# Demo route v2: the original walkthrough plus the AI Flight Recorder

**The original 150-second MP4 and scripts are untouched and remain the reference** (`DEMO_SCRIPT_150_SECONDS.md`, `DEMO_SHOT_LIST.md`; the recording is kept outside this repository). This route adds one panel. **Timing below is a proposal and has NOT been rehearsed**; measure it before relying on it.

## What changed in the product
A sidebar entry, **AI Flight Recorder**, opens a drawer in four groups: **Selected execution** (one recorded run, exactly as its producer reported it; shows "no execution recorded" until a trace exists), **Historical recorded evidence** (the earlier AMD / Gemma runs stored with the repository, labelled as not part of the selected execution), **This session** (human decisions) and **Trace files**. The table below describes the layers; the AMD, Gemma and Gatehouse-validation rows are the *historical* group, the Evolus row is the selected execution:

| Layer | Shows | Today |
|---|---|---|
| AMD (provider) | 10 real stored requests: HTTP status, timings, tokens, cost; TTFT and tokens/s only where derivable, labelled *derived* with the formula | RECORDED / FAILED |
| Google Gemma (model) | exact model string, tokens, citations, findings returned | one stored Gemma-4-31B-IT attempt: FAILED (8000-token budget, no parseable JSON) |
| Evolus (orchestration) | agent, workflow execution id, knowledge retrieval, tool calls, run status | NOT REPORTED (nothing recorded); shows the producer's trace when one is dropped into `FLIGHT_TRACE_DIR` |
| Gatehouse validation | code's classification of every model claim; the contradicted Type B finding; SIMULATED guard items | RECORDED (from the ledger) |
| Human authorization | named, self-declared decisions on **this** project | LIVE, empty until someone decides |

States: **LIVE, RECORDED, SIMULATED, FAILED, NOT_REPORTED**. Nothing is estimated: a value a record lacks reads NOT REPORTED. No GPU utilization or reasoning statistics exist in any record, so none is shown.

## Proposed 150-second route (not rehearsed)
| Scene | Budget | Change from the original |
|---|---|---|
| 1 Project | 15 s | unchanged, tightened |
| 2 AMD intelligence (replay) | 20 s | unchanged, tightened |
| 3 Type B money shot | 25 s | after the 409, open **Flight Recorder → Gatehouse validation**: the model said "clear"; code contradicted it; acceptance refused |
| 4 Humans retain authority | 25 s | make the Base bid decision; reopen the recorder: **Human authorization** now shows the named decision as LIVE |
| 5 Deterministic pricing | 30 s | unchanged |
| 6 Responsible release | 20 s | unchanged |
| 7 Flight Recorder overview | 15 s | AMD layer (one Test 003 request: first-token time and tokens/s labelled derived), Gemma layer (FAILED, honestly), Evolus layer (state per the section below) |

## When ANVIL 2's Evolus / Gemma RFI workflow is integrated
1. A real run produces a trace file in `gatehouse-flight-trace.v1` (contract: `docs/FLIGHT_RECORDER_CONTRACT.md`, confirmed with ANVIL 2). Put it in the directory named by `FLIGHT_TRACE_DIR`, mounted read-only (container default `/app/traces`). No restart is needed; the panel re-reads the directory on open.
2. The **Selected execution** group then shows that run (AMD and Gemma NOT REPORTED unless the trace reports them; the historical AMD / Gemma evidence never moves into it). Its Evolus layer shows the workflow execution id on every event, retrieval, tool calls and the run status, as **RECORDED** (source record + sha256). A simulator run shows **SIMULATED**. A trace that breaks the contract is listed as **REJECTED** and none of it is displayed.
3. What stays outside the trace by design: the draft RFI's approval status (it is pending human review), Gatehouse's validation of the model's findings, and the human's authorization. Gatehouse shows those in its own layers. **Not yet built:** validating Evolus/Gemma findings in the Gatehouse validation layer and surfacing the draft RFI case; that waits for ANVIL 2's case data and is not demonstrated today.
4. Do not narrate anything the layer does not show. If the layer says NOT REPORTED, say that.

## Working recorded-evidence fallback (available now)
The Flight Recorder reads stored evidence only and calls no model; the Bid Desk is separate (a live Evolus reply is labelled LIVE, the built-in desk SIMULATED, and a failed live reply UNAVAILABLE). Everything in the AMD, Gemma and Gatehouse layers is already stored evidence and works offline: the 10 recorded requests, the contradicted Type B finding with its 409, the failed Gemma attempt. For a rehearsal of the Evolus layout only, `e2e/fixtures/flight_traces/valid_evolus_simulated.json` shows a clearly labelled SIMULATED trace (its own text says it is not an Evolus run); the panel stamps every event SIMULATED, so it must be presented as a layout preview, never as an Evolus result. `invalid_unbacked_gpu_number.json` demonstrates rejection of an invented number.

## Pre-flight (60 s)
`curl <url>/api/demo/health` → `{"engine":"responsive"}`; open the recorder once and confirm the five layers and "Trace files: flight_recorder.json accepted". If a dropped trace shows REJECTED, read the listed reasons; do not edit the file to force acceptance.

## Live Evolus execution, its independent audit and its pending RFI cases (2026-10-14, corrected)
Under **Selected execution**, the newest recorded run opens first. For the first genuine run the panel shows: Evolus RECORDED with the real workflow execution id; AMD and Gemma NOT REPORTED; the Gatehouse strict validator result exactly as recorded (COMPLETED_VALID: valid structure and resolvable citations, not proof the conclusions are right); and LOOM's independent audit as a separate, attributed, release-pinned record. Say it in four parts, which the panel keeps apart: structurally valid AI output; authentic citations; the independent assessment of whether the conclusion is supported; and human authorization (none recorded).
- **Active shortlist:** D1 (Gate G3 clear opening width), SUPPORTED, eligible for human review, not approved, not sent.
- **Gate G3 panel:** clear opening width UNRESOLVED; post outside diameter UNRESOLVED (Specification 2.1.B ties it to the opening width; F502 note 4 says not specified); footing SPECIFIED (3/F501, 1'-4" dia. x 4'-0" deep minimum). Addendum 01 item 1.5 (2.875 in OD) is under "Gate G2 revised" and is shown as G2-only context, never applied to G3.
- **Flagged, historical:** D2 is FLAGGED, UNSUPPORTED BY CONTROLLING EVIDENCE because its footing requirement is already answered by 3/F501. It stays visible as historical output, is off the shortlist, and the flag does not mean the G3 post size is resolved.
- **Proposed clarification (separate):** G3 post outside diameter only, drafted by ANVIL 1 from LOOM's recommendation. Not an Evolus case, not approved, not sent.
- **Six omitted entries:** human-prepared Alternate A-1 arithmetic notes omitted before submission, not PDF quotations that failed verification.
- **If the audit cannot be authenticated** (altered, missing, unpinned or duplicate), the screen says so and nothing is cleared.
Do not say an RFI or clarification was approved or sent, that LOOM's audit was a human decision, that the pin proves LOOM wrote the record (it proves the release shipped those bytes), that Gemma or AMD ran for this execution, or that a draft changed the estimate (it cannot). The earlier HTTP 400 is a separate execution with no audit and no cases.

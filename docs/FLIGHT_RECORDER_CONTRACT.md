# AI Flight Recorder: trace data contract `gatehouse-flight-trace.v1`

**Status: confirmed 2026-10-14, with the clarifications below. The format is emitted by the adapter and passes an independent port of the ten rules; two real Evolus runs are now recorded.** The reader in `web/lib/flight-recorder.ts` implements exactly this text; a trace that violates it is shown as REJECTED, never repaired.

## What the Flight Recorder shows
**Presentation rule (view v2): runs are never combined.** Each trace file in `FLIGHT_TRACE_DIR` is one *execution* and is shown on its own under "Selected execution" (newest first; a picker lists the others). A layer the trace does not contain reads NOT REPORTED. The repository's stored record `dp001/flight_recorder.json` (earlier AMD / Gemma runs) is shown only under "Historical recorded evidence", with its own file, producer and sha256, and never contributes an event or status to an execution. A second file with an already-seen `trace_id` is rejected. The view API returns `executions[]`, `historical` and `session` (no merged `producer_layers`).

Within one trace: three producer layers, kept visually separate, then Gatehouse's own layers:

| Layer | Meaning | Who may supply it |
|---|---|---|
| `amd` | Inference **provider** measurements for a request (provider, model served, HTTP status, timings, tokens) | stored inference records or live telemetry |
| `gemma` | The **model** layer for Gemma runs only: exact model string, token counts, citations, findings the model returned | ANVIL 2 / stored records |
| `evolus` | **Orchestration**: agent, workflow execution id, knowledge retrieval, tool calls, review state | ANVIL 2 |
| Gatehouse validation | Code verification of model claims (ledger classification, vector oracle) | **Gatehouse only**, computed from the ledger |
| Human authorization | Named, self-declared decisions recorded on the live project | **Gatehouse only**, read from the engine's audit trail |

Gatehouse validation and human authorization are never accepted from a trace file.
A request answered by a non-Gemma model (e.g. DeepSeek on the AMD endpoint) appears in the `amd` layer with its exact model name and **never** in `gemma`.

## Document
```json
{ "schema": "gatehouse-flight-trace.v1", "trace_id": "string", "generated_utc": "ISO-8601", "producer": {"name": "string", "version": "string"},
  "layers": [ { "layer": "amd|gemma|evolus", "state": "STATE", "summary": "string",
      "events": [ { "event_id": "string", "kind": "string", "label": "string", "state": "STATE", "utc": "ISO-8601|null",
          "fields": { "<name>": { "value": "number|string|bool|[string]|null", "unit": "string|null", "reported": true, "derived": null } },
          "source": { "kind": "stored_inference_record|live_telemetry|simulation|none", "record_path": "string|null", "record_sha256": "64 hex|null" },
          "note": "string|null" } ] } ] }
```
`STATE` is one of **LIVE, RECORDED, SIMULATED, FAILED, NOT_REPORTED**.
`derived` is `null` or `{"formula": "string", "inputs": ["field names"]}` and marks a value computed from other measured fields in the same event (shown with a "derived" badge and its formula).

## Rules the reader enforces
1. `fields[x].reported == false` requires `value == null`; a non-null `value` requires `reported == true`. A null value is displayed as NOT_REPORTED. Nothing is estimated or filled in.
2. `LIVE` requires `source.kind == live_telemetry` and a non-null `utc`.
3. `RECORDED` requires `source.kind == stored_inference_record`, `record_path`, and a 64-hex `record_sha256` of the stored record.
4. `SIMULATED` requires `source.kind == simulation` and a `note`.
5. `FAILED` requires a `note` giving the reason (and may carry the fields that were measured).
6. `NOT_REPORTED` requires every field null (or no fields); `source.kind == none`.
7. A derived field must list inputs that exist in the same event, all `reported`.
8. `gemma` events require `fields.model` and its value must contain `gemma` (case-insensitive). `evolus` events in state LIVE or RECORDED require `fields.workflow_execution_id` reported.
9. Layer `state` must equal the worst-case summary of its events: FAILED if any event failed and none succeeded, otherwise the strongest provenance among them; a layer with no events is NOT_REPORTED.
10. Unknown field names are shown as received (under the event) with the same provenance rules; the reader does not rename or interpret them.

Field names Gatehouse knows (labels only; any may be absent): `provider`, `endpoint_host`, `model`, `model_returned`, `http_status`, `finish_reason`, `t_connected_s`, `t_first_byte_s`, `ttft_s`, `total_s`, `chunks`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `tokens_per_s`, `cost_usd`, `citations`, `findings_returned`, `agent`, `workflow_id`, `workflow_execution_id`, `knowledge_sources`, `tool_name`, `review_state`.
GPU utilization, hidden reasoning statistics and similar values are shown only if a record reports them; Gatehouse supplies none.

## Clarifications agreed with ANVIL 2
1. Rule 8 is **per event**: every Evolus event (execution, retrieval, tool call) carries `workflow_execution_id`.
2. Evolus-reported fields (each `reported=false` / null when the execution response lacks it; found by key search, never inferred): `workflow_execution_id`, `workflow_id`, `agent`, `review_state` (= the Evolus **run status**, not a Gatehouse review state), `knowledge_sources`, `tool_name`; Gemma layer: `model` (exact string, emitted only if it contains "gemma"), `prompt_tokens`, `completion_tokens`, `total_tokens` (not summed by the producer), `citations`, `findings_returned`; AMD layer: `provider`/`model_returned` only if Evolus reports a provider. Extra fields shown as received (rule 10): `evolus_trace_id`, `gatehouse_trace_id`, `package_sha256`, `submitted_epoch_s`, `completed_epoch_s`, and `total_s` derived as `completed_epoch_s - submitted_epoch_s` (adapter wall clock, **not** an Evolus measurement). No `ttft_s`, `tokens_per_s`, `cost_usd` or GPU numbers unless Evolus reports them.
3. State mapping: simulator runs are `SIMULATED` (source `simulation` plus a note). Real runs are `RECORDED` with source = the stored run record (`evolus_runs/<run_id>.json`) and its sha256, because the adapter polls after the fact and never claims `LIVE`. Failed / timed-out / start-failed runs are `FAILED` with a note. The `gemma` and `amd` layers stay `NOT_REPORTED` (empty) unless Evolus reports a Gemma model string; a non-Gemma model never appears in `gemma`.
4. Draft-RFI approval status, Gatehouse validation, dispositions and human authorization are **not** in a trace; Gatehouse computes them. The adapter has no approve or send route.
5. Gatehouse reads **files only** (`FLIGHT_TRACE_DIR`). It does not call the adapter's HTTP endpoints.
6. `generated_utc` may be `null` for deterministic offline rebuilds. Gatehouse's own layers use the source kinds `ledger_replay` and `session_audit`, which are rejected if a trace file tries to use them.

## Delivery
External producers drop one JSON document per trace into `FLIGHT_TRACE_DIR` (default `<repo>/traces/`). The proxy reads the directory server-side; nothing is sent to the browser except the validated trace. Gatehouse's own stored-record trace is `dp001/flight_recorder.json`, rebuilt offline by `python3 -m amd_bridge.flight_trace` from the stored inference records (no network, no AMD client).

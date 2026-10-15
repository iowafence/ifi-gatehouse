# engine

**Status: implemented; runs on fictional fixtures.** Deterministic code for scope validation, input guards, exception detection, takeoff, estimate and the three-gate workflow. No model output is used for arithmetic.

* `workflow.py` Scope, Labor and Release gates. A rejected decision leaves state untouched; a scope change invalidates downstream decisions; release needs a named approver, the exact scope version and the digest of the pending proposal.
* `guards.py`, `validate.py`, `exceptions.py` fail closed on zero, negative, non-finite, non-numeric or impossible values and on empty scopes.
* `takeoff.py`, `estimate.py` quantities and an estimate from `config/rates.example.json` (example rates) for the generic demo scope.
* `integration.py`, `pricing_service.py`, `ratebook_mode.py` the priced mode: footing scope, rate-book pricing through `pricing/`, readiness fields (`bid_ready`, `release_class`, `footing_release_class`, `artifact_kind`).
* `portfolio.py` KPIs for the synthetic eight-project portfolio, Decimal arithmetic.
* Priced mode and the HTTP contract are documented in `docs/HTTP_ADAPTER_CONTRACT_v1_PROPOSED.md` and `docs/pricing/`.

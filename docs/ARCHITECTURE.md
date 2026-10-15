# Architecture

**Status: design. Components are published in stages; see [STATUS.md](STATUS.md) for which exist.**

## Principle

AI interprets, code calculates, humans authorize. The boundary between interpretation and arithmetic is a
validated JSON scope; the boundary between arithmetic and release is a human gate.

## Data flow

```
Project documents (plans, specs, addenda)
        |  hardened intake: archive and file validation          (intake/)
        v
Model interpretation on AMD-served open-weight models,
orchestrated through Evolus                                       (evolus/)
        |  proposes a scope: each fact has value, status, evidence
        v
Deterministic engine                                              (engine/)
        |  validate -> guards -> exceptions -> takeoff -> estimate
        |  rates come from company-controlled tables               (pricing/)
        v
Authenticated API                                                 (api/)
        v
Project workspace with gate dialogs                               (web/)
```

## Trust boundaries

- Model output is untrusted. It is validated like hand-typed input. Missing or unusable values become blocking
  exceptions and are never filled in by the model or by the engine.
- The browser never holds the engine key or any model credential. The web tier calls the API server-side.
- Rates are company data, validated before use. Example rates in the repository are not real prices.
- Release is bound to a scope version and a digest of the proposal contents, so a stale approval cannot release
  a changed proposal.

## Facts and statuses

Every fact in a scope carries a value, a status (for example confirmed, inferred, unresolved, human-resolved)
and evidence. Inferred and human-resolved values require a recorded justification or a named person.

## Not decided yet

There is no persistence: all state is in memory. The public demo runs as one container (engine on loopback, web tier on the platform port); see `docs/HOSTING.md`. The repository is MIT-licensed.

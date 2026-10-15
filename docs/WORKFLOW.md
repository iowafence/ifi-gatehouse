# Human approval workflow

**Status: implemented in `engine/workflow.py` and exercised through the demo API and web workspace on a fictional fixture. Names are self-declared, not authenticated.**

| Gate | Opens when | A named person must | Blocks until |
|---|---|---|---|
| Scope | Any blocking exception is open | Resolve each exception with a value or option and a note | No blocking exceptions remain |
| Labor | Scope is clean | Decide the wage basis with sources, or record a qualified assumption | A labor decision exists for the current scope version |
| Release | Scope and labor are decided | Approve the exact proposal digest and scope version | Approval is recorded |

Rules:

- Every decision records who decided and why. Names are self-declared unless identity is added later.
- A rejected decision changes nothing.
- Changing the scope invalidates the labor decision. Changing the proposal invalidates a pending release.
- No price is shown or computed before the labor gate.
- Unknown compliance status is never presented as approved.
- Every state change is written to an audit trail.

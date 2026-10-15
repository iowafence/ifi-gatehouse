# Security

IFI Gatehouse is a hackathon demonstration. It has **no production authentication** (names entered at the gates are self-declared), keeps all state **in memory**, and runs on **fictional data**. A public judge demo instance runs as one container behind the host's HTTPS with per-network and global new-session limits, isolated anonymous sessions and read-only evidence (see `docs/HOSTING.md`). Do not run your own copy on the public internet without equivalent controls, and never enter real project data.

Please report a vulnerability privately through GitHub's "Report a vulnerability" (Security tab) on this repository, not in a public issue. Reports about secrets that should not be in the history are especially welcome.

What the code does defend, and what the tests cover: fail-closed input guards, hash-checked document serving, stale-decision rejection by digest, idempotent decision replay, hardened ZIP and workbook readers, and refusal of model output that the drawing evidence contradicts. See `tests/` and `docs/ARCHITECTURE.md`.

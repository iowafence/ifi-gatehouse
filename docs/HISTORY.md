# About this repository's history

This repository is a **single-commit public release**, created on 2026-10-15 from a private development repository at commit `2bdab4d8ccf11fde326f09d60c043559b75ef174`. That commit is the deployed application source (`20e0d6b`) plus documentation and tooling only; every input of the deployed container image is byte-identical to the deployed commit. The development history (about 40 commits across two independently created lineages, a milestone checkpoint and a re-layout) stays private and is not published here.

Commit ids that appear in the documents (for example `20e0d6b`, `9fee8c7`, `5bf7dec`) refer to that private repository and cannot be resolved in this one. They are kept because the verification records quote them. To check what was deployed, use the hashes inside this repository instead: `hosting/verify_release.sh` and `release_evidence/SHA256SUMS` (the authentic execution traces, review cases and LOOM reports), `dp001/independent_audits/` and `web/lib/audit-manifest.ts` (the release-pinned audit manifest), and `samples/public-assets.sha256` (the synthetic documents).

The earlier development work also included internal evaluation tooling that is not part of this release; nothing from it is in this repository.

Later work lands as ordinary commits and pull requests, dated when it is made.

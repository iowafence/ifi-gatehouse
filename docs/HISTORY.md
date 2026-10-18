# Repository history

This repository's history was rewritten once, on 17 October 2026, before it was made public.

**Why.** Early development used the founder's full name as the demo "owner" in constants, fixtures and tests. To keep a personal detail out of a public repository, the surname was replaced with the first name throughout the history: in file contents and in commit messages.

**What changed.**
- Only that replacement, in every revision.
- The removal of internal working files, in the commit titled "prep for public cleanup". Its message and [CLEANUP.md](CLEANUP.md) list each group of files and the reason.
- Documentation updates made after that.

**What did not change.**
- Commit order, commit dates, parent structure and authorship (Iowa Fence Inc.) are as they were during the build. The first commit is from 14 October 2026 and the last build commit from 17 October 2026.
- The content of every other file is identical. The tree at the tag `gatehouse-ui-final-4` is byte-identical to the verified build (tree hash `00cc3b0ef5fc85dc01a0a8adfcc3d9385c7b4dfa`, image digest `sha256:16bf4a536d23c52f0d8110634a5ad611dd03aaeae0b8f0523804b6a63483d548`).

**What differs from the private history.**
- Commit hashes differ, because rewriting content changes every hash after it. Earlier private verification reports are tied to the build by tree hash, not commit hash.
- Three merge-commit messages mention other commits by short hash; the rewriting tool updated those to the new hashes. Two short hashes in the root commit's message refer to commits that are not on this branch.
- The tag `gatehouse-ui-final-4` was re-created on the rewritten history, so its date is the rewrite date.

**How it was checked.** A separate auditor compared all 99 original commits with the rewritten ones (author, committer, dates, parents), compared 828 file versions against an independent application of the same replacement, and scanned every revision for the surname (0 hits), for AI attribution lines (0) and for stray files (0).

The original private repository is retained and can be shown to judges on request.

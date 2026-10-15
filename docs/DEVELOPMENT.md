# Development policy

## Git

- `main` is the only long-lived branch. Changes land as reviewed commits.
- Commits are authored and committed as `Iowa Fence Inc.` using the project noreply address.
- Commit messages carry no automatic agent attribution footers. CI and the commit-msg hook reject them.
- Install the hooks once per clone: `./scripts/install_hooks.sh`.

## What must never be committed

Credentials and `.env` files, real customer or bid documents, answer keys and evaluation ground truth, private rate books,
internal audit or coordination reports, and real pricing. Documents, archives and spreadsheets are accepted only as reviewed
public synthetic assets: under `samples/public-demo/`, with the exact content hash and a provenance note in
`samples/public-assets.sha256`. `scripts/check_secrets.sh` enforces this in the pre-commit hook and in CI.
Optional local name denylist: put regular expressions, one per line, in an untracked `.private-names` file.

## Local checks

```
./scripts/check_secrets.sh --tree
python3 scripts/check_links.py
python3 -m unittest discover -s tests -v
(cd web && npm ci && npm run typecheck && npm run build)
docker build -t gatehouse-engine .
```

CI runs the same checks: repository policy, engine tests, web typecheck and build, and the Docker image build with a `/health` check.

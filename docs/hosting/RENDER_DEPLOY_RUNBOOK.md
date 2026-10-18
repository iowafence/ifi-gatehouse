# Deploying the judge demo to Render

The public synthetic demo runs as a Render **Image** service. Render pulls a private container image from GitHub Container Registry **by digest**; there is no Git deploy and nothing is built on Render.

## The image

| Item | Value |
|---|---|
| Build | tag `gatehouse-ui-final-4`, tree `00cc3b0ef5fc85dc01a0a8adfcc3d9385c7b4dfa` |
| Registry image (private) | `ghcr.io/iowafence/ifi-gatehouse@sha256:16bf4a536d23c52f0d8110634a5ad611dd03aaeae0b8f0523804b6a63483d548` |
| Source | built from a clean clone of the tag with `hosting/Dockerfile` |
| Registry access | the package is private; Render uses a read-only pull credential |

The digest, not a tag, is what Render runs. A pushed tag cannot change the deployed image, and an earlier digest stays pullable for rollback.

## Push and verify

1. Build from a clean clone: `docker build -f hosting/Dockerfile -t gatehouse-judge-demo:<tag> .`
2. Tag and push to the private package, then read the pushed manifest digest from the registry.
3. Pull back **by digest** and confirm the pulled image ID equals the local one.
4. Confirm an anonymous pull by digest is refused (the package must stay private).
5. Run `IMAGE=<registry image by digest> hosting/verify_release.sh`. It checks that the baked evidence files equal `RELEASE_SHA256SUMS`, that the evidence is read-only to the app user (uid 10001), that there are no host mounts, and that the container runs non-root.
6. Remove the write token from the machine after the push.

## Render settings

Use the image URL above with the registry credential, one instance, no disk. The container needs no secrets for the recorded Addendum 02 replay (`ENGINE_ADDENDUM_MODE=recorded`), and it refuses to start in any other mode. The live Bid Desk is optional and needs the `EVOLUS_*` secrets (see HOSTING.md); without `EVOLUS_DESK_ENABLED=1` it is off. See [HOSTING.md](../HOSTING.md) for the environment variables and the security review.

## Rollback

Set the service's image to the previous digest and redeploy. Digests of earlier images remain in the package.

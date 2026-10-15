# AMD experiment harness (curated import)

Code, tests, experiment definitions and **text** run records of the AMD-hosted model experiments that produced the evidence ledger (`dp001/ai_findings.json`).
Imported on 2026-10-14 from an unversioned working directory; no earlier history exists.

* `ext/` harness: request pipeline, strict parser, validators, PDF text and vector geometry oracles, streaming client.
* `tests/` the harness's own offline unit tests (`test_frozen.py` is not included: it hashes image files that are not published).
* `experiments/`, `manifests/` experiment definitions and the document registry (local file paths were reduced to file names when imported).
* `runs/`, `runs_v2/` stored JSON/JSONL/text records of real attempts, including the two frozen spatial tests (hash manifests `runs_v2/FROZEN_TEST00{1,2}.json`). Rendered images, logs and overlays are not published.
* `LIVE_CALLS_DISABLED` the hold file. While it exists the pipeline refuses to send any request. The offline bridge never imports the AMD client.

The API key, if you ever make a live call, is read from `AMD_TOKEN_FACTORY_API_KEY` or `~/.config/ifi-amd/token_factory.env`. It is not part of this repository.
`documents/dp001_ansi_b_v2_candidate` is a symlink to the published synthetic PDFs in `samples/public-demo/dp001/` so the harness tests find the drawing (the ZIP/FreeCAD originals are not published; the two tests that need them skip).
Run the tests with Python 3.12 and `pip install -r requirements-amd.txt` (`pypdfium2`, `pillow`): `PYTHONPATH=amd_experiment python3 -m unittest discover -s amd_experiment/tests`.

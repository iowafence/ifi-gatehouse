#!/usr/bin/env python3
"""SAFE (deliberately filtered) test runner. It is NOT an unrestricted full-suite run and must never be reported as one.

 * Runs in a SANITIZED environment: HOME is pointed at a fresh empty temporary directory so no test can resolve files under the real home.
 * Does not open, hash, copy or inspect any private file, and refuses to run if any shipped test references a private location.
usage: run_safe_suite.py ENGINE_COPY [--manifest PATH] [-v]   (writes only the manifest, if given)"""
import json, os, sys, tempfile, unittest

EXCLUDED = ()   # no test is excluded
copy_dir = os.path.abspath(sys.argv[1])
MANIFEST_PATH = os.path.abspath(sys.argv[sys.argv.index("--manifest") + 1]) if "--manifest" in sys.argv else None   # resolved BEFORE chdir
sandbox = tempfile.mkdtemp(prefix="sanitized-home-")
os.environ["HOME"] = sandbox
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.chdir(copy_dir)
sys.path.insert(0, copy_dir)
import pathlib
assert str(pathlib.Path.home()) == sandbox, "HOME sanitization failed"


def flatten(s):
    for t in s:
        if isinstance(t, unittest.TestSuite):
            yield from flatten(t)
        else:
            yield t


suite = unittest.defaultTestLoader.discover("tests")
all_tests = list(flatten(suite))
excluded = [t for t in all_tests if any(t.id().endswith(e) for e in EXCLUDED)]
selected = [t for t in all_tests if t not in excluded]
# No test file may reference a private location.
EXPECTED_MATCHES = len(EXCLUDED)
for root, _, names in os.walk("tests"):
    for n in names:
        if n.endswith(".py") and "-private/" in open(os.path.join(root, n), errors="replace").read():
            sys.exit(f"{n} references a private location: refusing to run")
if len(excluded) != EXPECTED_MATCHES:
    sys.exit(f"exclusion matched {len(excluded)} tests, expected {EXPECTED_MATCHES}: refusing to run")
verbose = 2 if "-v" in sys.argv else 1
res = unittest.TextTestRunner(verbosity=verbose, stream=sys.stderr).run(unittest.TestSuite(selected))
passed = res.testsRun - len(res.failures) - len(res.errors) - len(res.skipped)
report = {"run_type": "SAFE FILTERED SELECTION (NOT an unrestricted full-suite run)", "engine_copy": copy_dir, "sanitized_home": "fresh empty temp dir (no private files mounted)",
          "discovered": len(all_tests), "excluded_by_design": [t.id() for t in excluded], "excluded_count": len(excluded), "selected_and_run": res.testsRun,
          "passed": passed, "failed": len(res.failures), "errors": len(res.errors), "skipped": len(res.skipped),
          "skipped_tests": [t.id() for t, _ in res.skipped], "skipped_reasons": sorted({r for _, r in res.skipped}),
          "excluded_reason": "none"}
print(json.dumps(report, indent=1))
if MANIFEST_PATH:
    json.dump(report, open(MANIFEST_PATH, "w"), indent=1)
sys.exit(0 if res.wasSuccessful() else 1)

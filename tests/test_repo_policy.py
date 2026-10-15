"""Tests of the repository guardrails. They exercise the real scripts against throwaway repositories with planted violations,
so a regression in a guard (not just a layout change) fails CI."""
import hashlib
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
KEY_SUFFIXES = (".pem", ".key", ".p12")
DOC_SUFFIXES = (".pdf", ".zip", ".xlsx", ".xls", ".dwg")


def git(cwd, *args, env=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env)


def tracked():
    return subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).split("\n")[:-1]


def scratch_repo(files):
    """A throwaway git repo containing the repo's guard scripts plus `files` ({path: bytes|str}), all staged."""
    d = tempfile.TemporaryDirectory()
    root = pathlib.Path(d.name)
    git(root, "init", "-q")
    (root / "scripts").mkdir()
    for name in ("check_secrets.sh", "check_commit_msgs.sh", "check_links.py"):
        (root / "scripts" / name).write_bytes((ROOT / "scripts" / name).read_bytes())
        (root / "scripts" / name).chmod(0o755)
    for path, data in files.items():
        p = root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())
    git(root, "add", "-A")
    return d, root


def run(root, *cmd):
    return subprocess.run(cmd, cwd=root, capture_output=True, text=True)


class SecretScanner(unittest.TestCase):
    def blocked(self, files):
        d, root = scratch_repo(files)
        with d:
            r = run(root, "./scripts/check_secrets.sh", "--tree")
            return r.returncode != 0, r.stderr

    def test_clean_tree_passes(self):
        self.assertFalse(self.blocked({"README.md": "hello\n", ".env.example": "KEY=\n"})[0])

    def test_credential_shaped_strings_are_blocked_and_never_echoed(self):
        secret = "sk-" + "A1b2C3d4" * 4
        bad, err = self.blocked({"app.py": f"token = '{secret}'\n"})
        self.assertTrue(bad)
        self.assertNotIn(secret, err)

    def test_private_key_headers_env_files_and_documents_are_blocked(self):
        for path, data in ((".env", "A=1"), ("keys/id.pem", "x"), ("bids/plan.pdf", b"%PDF"), ("pricing/book.xlsx", b"PK"), ("a.zip", b"PK"),
                           ("samples/public-demo/unlisted.pdf", b"%PDF"), ("k.txt", "-----BEGIN RSA " + "PRIVATE KEY-----\n")):
            with self.subTest(path=path):
                self.assertTrue(self.blocked({path: data})[0])

    def asset(self, path, data=b"%PDF-1.4 fictional\n", manifest_path=None, provenance="# fictional drawing created for the public demo; reviewed"):
        h = hashlib.sha256(data).hexdigest()
        return {path: data, "samples/public-assets.sha256": f"# header\n{h}  {manifest_path or path}  {provenance}\n"}

    def test_a_reviewed_public_synthetic_asset_is_allowed(self):
        for name in ("plans.pdf", "package.zip", "takeoff.xlsx"):
            with self.subTest(name=name):
                self.assertFalse(self.blocked(self.asset(f"samples/public-demo/{name}"))[0])

    def test_a_listed_asset_must_match_its_hash_and_carry_provenance(self):
        files = self.asset("samples/public-demo/plans.pdf")
        files["samples/public-demo/plans.pdf"] = b"%PDF-1.4 changed after review\n"
        self.assertTrue(self.blocked(files)[0])
        self.assertTrue(self.blocked(self.asset("samples/public-demo/plans.pdf", provenance=""))[0])

    def test_private_looking_names_and_other_locations_are_blocked_even_if_listed(self):
        for path in ("samples/public-demo/answer_key.xlsx", "samples/public-demo/bid_ground_truth.pdf", "samples/public-demo/legacy_rate_book.xlsx",
                     "samples/public-demo/customer_plans.zip", "samples/public-demo/ORIGINAL_WITH_ANSWER.xlsx", "docs/plans.pdf", "pricing/book.xlsx"):
            with self.subTest(path=path):
                self.assertTrue(self.blocked(self.asset(path))[0])

    def test_local_name_denylist_blocks_a_listed_name(self):
        d, root = scratch_repo({"notes.md": "Project Falcon Ridge bid\n"})
        with d:
            (root / ".private-names").write_text("falcon ridge\n")
            self.assertNotEqual(run(root, "./scripts/check_secrets.sh", "--tree").returncode, 0)


class CommitPolicy(unittest.TestCase):
    def make(self, message, name="Iowa Fence Inc."):
        d, root = scratch_repo({"a.txt": "x\n"})
        env = {**os.environ, "GIT_AUTHOR_NAME": name, "GIT_COMMITTER_NAME": name, "GIT_AUTHOR_EMAIL": "ci@example.invalid", "GIT_COMMITTER_EMAIL": "ci@example.invalid"}
        git(root, "commit", "-q", "-m", message, env=env)
        return d, root

    def test_attribution_trailers_are_rejected_and_plain_commits_pass(self):
        for msg, should_fail in (("Add feature", False), ("Add feature\n\nCo-Authored-By: Claude <noreply@anthropic.com>", True)):
            with self.subTest(msg=msg[:20]):
                d, root = self.make(msg)
                with d:
                    self.assertEqual(run(root, "./scripts/check_commit_msgs.sh", "--range", "HEAD").returncode != 0, should_fail)

    def test_wrong_author_is_rejected(self):
        d, root = self.make("Add feature", name="Someone Else")
        with d:
            self.assertNotEqual(run(root, "./scripts/check_commit_msgs.sh", "--range", "HEAD").returncode, 0)


class LinkChecker(unittest.TestCase):
    def test_broken_relative_links_fail_and_valid_ones_pass(self):
        d, root = scratch_repo({"README.md": "[ok](docs/a.md) [web](https://example.com)\n", "docs/a.md": "x\n"})
        with d:
            self.assertEqual(run(root, "python3", "scripts/check_links.py").returncode, 0)
        d, root = scratch_repo({"README.md": "[gone](docs/missing.md)\n"})
        with d:
            self.assertNotEqual(run(root, "python3", "scripts/check_links.py").returncode, 0)


class TrackedFiles(unittest.TestCase):
    def test_no_key_files_or_env_files_are_tracked(self):
        for f in tracked():
            with self.subTest(file=f):
                self.assertFalse(f.lower().endswith(KEY_SUFFIXES))
                name = pathlib.PurePosixPath(f).name
                self.assertFalse(name.startswith(".env") and name != ".env.example")

    def test_every_tracked_document_is_a_listed_public_asset_with_a_matching_hash(self):
        manifest = (ROOT / "samples" / "public-assets.sha256").read_text(encoding="utf-8")
        for f in tracked():
            if f.lower().endswith(DOC_SUFFIXES):
                with self.subTest(file=f):
                    self.assertTrue(f.startswith("samples/public-demo/"))
                    h = hashlib.sha256((ROOT / f).read_bytes()).hexdigest()
                    self.assertRegex(manifest, rf"(?m)^{h}  {f}  # .+")

    def test_env_example_has_names_only(self):
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                self.assertTrue(line.endswith("="), f"value present: {line.split('=')[0]}")

    def test_readme_does_not_claim_more_than_status_says(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        status = (ROOT / "docs" / "STATUS.md").read_text(encoding="utf-8")
        self.assertIn("docs/STATUS.md", readme)
        for component in ("Engine", "API", "Web app"):
            if f"| {component} | Not yet published" in status:
                self.assertNotIn(f"{component} is implemented", readme)

    def test_ci_runs_the_guards_and_the_tests(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        for needle in ("check_secrets.sh --tree", "check_commit_msgs.sh", "check_links.py", "unittest discover"):
            self.assertIn(needle, ci)

    def test_docker_and_git_ignores_exclude_private_material(self):
        for fname in (".gitignore", ".dockerignore"):
            text = (ROOT / fname).read_text(encoding="utf-8")
            for needle in (".env", "*.pdf", "*.xlsx", "*.pem"):
                self.assertIn(needle, text, f"{fname} missing {needle}")


if __name__ == "__main__":
    unittest.main()

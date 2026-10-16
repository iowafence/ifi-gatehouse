"""The hosted image's recorded capture is a tracked file, hash-pinned, alone in its folder, and free of key or ledger content; both dockerignore files keep the judge image deny list."""
import hashlib, json, pathlib, re, subprocess, sys, unittest
ROOT = pathlib.Path(__file__).resolve().parent.parent
NAME = "f0b0571c9696_call3.json"
class HostingCapture(unittest.TestCase):
    def test_guard_script_passes(self):
        r = subprocess.run([sys.executable, str(ROOT / "hosting/stage_capture.py")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
    def test_capture_has_no_key_or_ledger_content(self):
        t = (ROOT / "hosting/captures" / NAME).read_text()
        for pat in (r"bearer\s+\S+", r"authorization", r"sk-[A-Za-z0-9]{10,}", r"hf_[A-Za-z0-9]{10,}", r"ledger", r"authorized_by", r"allowed_sha256", r"max_calls"):
            self.assertIsNone(re.search(pat, t, re.I), pat)
        self.assertEqual(sorted(p.name for p in (ROOT / "hosting/captures").iterdir()), [NAME])
    def test_dockerfile_reads_the_tracked_path_and_guards_the_hash(self):
        d = (ROOT / "hosting/Dockerfile").read_text()
        self.assertIn("COPY hosting/captures ./captures", d); self.assertNotIn("staged", d.split("COPY hosting/captures")[0].splitlines()[-1] + "COPY hosting/captures")
        self.assertIn("ad91cd1e30d8c87350665a5181a7723116bd927aa96bbb3ed5748ab50f5b6fa6", d)
    def test_both_dockerignores_exclude_dp001_scripts_and_reference(self):
        for f in (".dockerignore", "hosting/Dockerfile.dockerignore"):
            t = (ROOT / f).read_text().splitlines()
            self.assertIn("dp001/*.py", t, f); self.assertIn("dp001/reference", t, f)
        self.assertIn("!hosting/captures", (ROOT / "hosting/Dockerfile.dockerignore").read_text().splitlines())
if __name__ == "__main__": unittest.main()

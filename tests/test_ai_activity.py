"""dp001/ai_activity.json is the stored attempt records restated, nothing more: it equals a fresh build from them, names no organization, project or key identifier, and states
only what a record states (null where none does)."""
import json, pathlib, re, subprocess, sys, unittest
ROOT = pathlib.Path(__file__).resolve().parent.parent
class AiActivity(unittest.TestCase):
    def setUp(self): self.doc = json.loads((ROOT / "dp001/ai_activity.json").read_text())
    def test_matches_a_fresh_build_from_the_stored_records(self):
        r = subprocess.run([sys.executable, "-m", "amd_bridge.ai_activity", "--check"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
    def test_counts_and_states_follow_the_ledger(self):
        led = json.loads((ROOT / "dp001/ai_findings.json").read_text())
        self.assertEqual([a["attempt_id"] for a in self.doc["attempts"]], [a["attempt_id"] for a in led["attempts"]])
        self.assertEqual(self.doc["by_state"], {"CANDIDATES_AVAILABLE": 5, "FAILED": 2, "TIMED_OUT": 3})
        self.assertEqual(self.doc["by_model"], {"Gemma-4-31B-IT": 1, "Qwen3.8-27B": 2, "DeepSeek-V4.1-Flash": 7})
        self.assertEqual((self.doc["tokens_reported_on"], self.doc["call_time_reported_on"]), (7, 10))
    def test_no_identifier_and_no_invented_value(self):
        t = (ROOT / "dp001/ai_activity.json").read_text()
        self.assertIsNone(re.search(r"organization|project_id|apiKey|api_key", t, re.I))
        a = {x["attempt_id"]: x for x in self.doc["attempts"]}
        self.assertIsNone(a["spatial_c101_live_001"]["tokens_in"])           # usage is null in its record
        self.assertEqual((a["exp2-qwen-crop"]["tokens_in"], a["exp2-qwen-crop"]["tokens_cached"], a["exp2-qwen-crop"]["tokens_out"]), (1517, 1472, 2947))
        for x in self.doc["attempts"]:
            for s in x["sources"]: self.assertRegex(s["sha256"], r"^[0-9a-f]{64}$")
if __name__ == "__main__": unittest.main()

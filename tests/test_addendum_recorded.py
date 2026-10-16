"""RECORDED replay: labeled, offline, never consumes the live-call ledger, answers only for the recorded document."""
import hashlib
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from engine import addendum_intake as ai, addendum_live as live, addendum_recorded as rec_mod
from tests import footing_helpers as H
from tests.decoy_pdf import G3_LINE, decoy

WHO = "Uploader (self-declared)"


class Recorded(unittest.TestCase):
    def setUp(self):
        self.pdf = decoy(G3_LINE)
        sha = hashlib.sha256(self.pdf).hexdigest()
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"label": "RECORDED", "ledger_call_no": 2, "live_call_utc": "2026-10-16T17:24:37Z", "source_sha256": sha, "model_returned": "self-dploy/Qwen3.8-27B",
                   "elapsed_ms": 10182, "usage": {"total_tokens": 1228},
                   "facts": [{"path": "/gates/2/clear_width_ft", "value": 14, "page": 1, "excerpt": "THE CLEAR OPENING WIDTH IS 14 FEET"}]}, self.tmp)
        self.tmp.close()
        self.p = mock.patch.object(rec_mod, "RECORDING", pathlib.Path(self.tmp.name))
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_replay_is_labeled_recorded_and_goes_through_the_same_verification_and_gate(self):
        st = H.start(H.fixture())
        rec = ai.submit_addendum(st, self.pdf, "r.pdf", parser=ai.recorded_parser, by=WHO)
        self.assertEqual(rec["status"], ai.PROPOSED)
        p = rec["parse"]
        self.assertEqual((p["mode"], p["model"], p["elapsed_ms"], p["result"]), ("RECORDED", "self-dploy/Qwen3.8-27B", 10182, "RETURNED"))
        self.assertIn("RECORDED", p["label"])
        self.assertIn("not a live call", p["label"])
        self.assertIn("live call 2", p["recorded_from"])
        self.assertEqual(st["scope"]["gates"][2]["clear_width_ft"]["status"], "unresolved")          # still a proposal until a named human accepts
        self.assertEqual(rec["before_after"][0]["after"], 14.0)

    def test_replay_of_a_different_document_is_refused(self):
        st = H.start(H.fixture())
        rec = ai.submit_addendum(st, decoy(G3_LINE, "A DIFFERENT DOCUMENT"), "x.pdf", parser=ai.recorded_parser, by=WHO)
        self.assertEqual((rec["status"], rec["parse"]["mode"]), ("HELD_PARSE_UNAVAILABLE", "RECORDED"))
        self.assertIn("no recording", rec["message"])

    def test_replay_never_touches_the_ledger_the_network_or_credentials(self):
        before = open(live.AUTH_FILE).read()
        with mock.patch("socket.socket", side_effect=AssertionError("network used")), mock.patch.object(live, "_reserve", side_effect=AssertionError("ledger used")):
            rec = ai.submit_addendum(H.start(H.fixture()), self.pdf, "r.pdf", parser=ai.recorded_parser, by=WHO)
        self.assertEqual(rec["status"], ai.PROPOSED)
        self.assertEqual(open(live.AUTH_FILE).read(), before)

    def test_the_shipped_recording_matches_the_ledger_entry_it_replays(self):
        r = json.load(open(live.ROOT / "amd_experiment" / "recorded" / "addendum_02_call2.json"))
        d = json.load(open(live.AUTH_FILE))
        call = d["calls"][r["ledger_call_no"] - 1]
        self.assertEqual((r["label"], r["source_sha256"], r["elapsed_ms"], r["usage"], r["model_returned"], len(r["facts"])),
                         ("RECORDED", call["sha256"], call["elapsed_ms"], call["usage"], call["model_returned"], call["facts_returned"]))
        self.assertIn("raw model reply was not retained", r["note"])


if __name__ == "__main__":
    unittest.main()

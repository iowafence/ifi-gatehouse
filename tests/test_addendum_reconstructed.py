"""RECORDED replay: labeled, offline, never consumes the live-call ledger, answers only for the recorded document."""
import hashlib
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from engine import addendum_intake as ai, addendum_live as live, addendum_reconstructed as rec_mod
from tests import footing_helpers as H
from tests.decoy_pdf import G3_LINE, decoy

WHO = "Uploader (self-declared)"


class Reconstructed(unittest.TestCase):
    def setUp(self):
        self.pdf = decoy(G3_LINE)
        sha = hashlib.sha256(self.pdf).hexdigest()
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"label": "RECONSTRUCTED", "ledger_call_no": 2, "live_call_utc": "2026-10-16T17:24:37Z", "source_sha256": sha, "model_returned": "self-dploy/Qwen3.8-27B",
                   "elapsed_ms": 10182, "usage": {"total_tokens": 1228},
                   "facts": [{"path": "/gates/2/clear_width_ft", "value": 14, "page": 1, "excerpt": "THE CLEAR OPENING WIDTH IS 14 FEET"}]}, self.tmp)
        self.tmp.close()
        self.p = mock.patch.object(rec_mod, "RECORDING", pathlib.Path(self.tmp.name))
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_replay_is_labeled_recorded_and_goes_through_the_same_verification_and_gate(self):
        st = H.start(H.fixture())
        rec = ai.submit_addendum(st, self.pdf, "r.pdf", parser=ai.reconstructed_parser, by=WHO)
        self.assertEqual(rec["status"], ai.PROPOSED)
        p = rec["parse"]
        self.assertEqual((p["mode"], p["model"], p["elapsed_ms"], p["result"]), ("RECONSTRUCTED", "self-dploy/Qwen3.8-27B", 10182, "RETURNED"))
        self.assertIn("RECONSTRUCTED", p["label"])
        self.assertNotIn("RECORDED", p["label"])
        self.assertIn("raw reply not retained", p["label"])
        self.assertIn("not a live call", p["label"])
        self.assertIn("live call 2", p["recorded_from"])
        self.assertEqual(st["scope"]["gates"][2]["clear_width_ft"]["status"], "unresolved")          # still a proposal until a named human accepts
        self.assertEqual(rec["before_after"][0]["after"], 14.0)

    def test_replay_of_a_different_document_is_refused(self):
        st = H.start(H.fixture())
        rec = ai.submit_addendum(st, decoy(G3_LINE, "A DIFFERENT DOCUMENT"), "x.pdf", parser=ai.reconstructed_parser, by=WHO)
        self.assertEqual((rec["status"], rec["parse"]["mode"]), ("HELD_PARSE_UNAVAILABLE", "RECONSTRUCTED"))
        self.assertIn("has none", rec["message"])

    def test_replay_never_touches_the_ledger_the_network_or_credentials(self):
        self.led = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        self.led.write('{"calls": []}')
        self.led.close()
        lp = mock.patch.object(live, "LEDGER_FILE", pathlib.Path(self.led.name))
        lp.start()
        self.addCleanup(lp.stop)
        before = open(live.ledger_path()).read()
        with mock.patch("socket.socket", side_effect=AssertionError("network used")), mock.patch.object(live, "_reserve", side_effect=AssertionError("ledger used")):
            rec = ai.submit_addendum(H.start(H.fixture()), self.pdf, "r.pdf", parser=ai.reconstructed_parser, by=WHO)
        self.assertEqual(rec["status"], ai.PROPOSED)
        self.assertEqual(open(live.ledger_path()).read(), before)

    def test_the_shipped_reconstruction_is_labeled_and_consistent(self):
        r = json.load(open(live.ROOT / "amd_experiment" / "reconstructed" / "addendum_02_call2_reconstructed.json"))
        self.assertEqual((r["label"], r["ledger_call_no"], r["model_returned"], len(r["facts"])), ("RECONSTRUCTED", 2, "self-dploy/Qwen3.8-27B", 4))
        self.assertIn("raw reply not retained", r["note"])
        self.assertNotIn("RECORDED", json.dumps(r))
        ledger = pathlib.Path.home() / "ifi-gatehouse-live-captures" / "ledger.json"
        if ledger.exists():                                                   # on the machine that made the call: it must match the ledger entry
            call = next(c for c in json.load(open(ledger))["calls"] if c["call_no"] == r["ledger_call_no"])
            self.assertEqual((r["source_sha256"], r["elapsed_ms"], r["usage"]), (call["sha256"], call["elapsed_ms"], call["usage"]))

if __name__ == "__main__":
    unittest.main()

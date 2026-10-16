"""RECORDED replay of a CAPTURED live reply: exact, offline, verified, per-document, and never a reconstruction."""
import base64
import hashlib
import json
import os
import pathlib
import tempfile
import threading
import unittest
from unittest import mock

from engine import addendum_intake as ai, addendum_live as live
from tests import footing_helpers as H
from tests.decoy_pdf import G3_LINE, decoy
from tests.test_addendum_live import Fake, WHO
from http.server import ThreadingHTTPServer


class Recorded(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        cls.url = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        Fake.mode, Fake.hits = "ok", 0
        self.pdf = decoy(G3_LINE)
        self.sha = hashlib.sha256(self.pdf).hexdigest()
        self.auth = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"purpose": "ADDENDUM_02_PARSE_ONLY", "authorized_by": "test", "model": "Qwen3.8-27B", "max_calls": 5, "timeout_s": 5.0, "allowed_sha256": [self.sha], "calls": []}, self.auth)
        self.auth.close()
        self.capdir = tempfile.mkdtemp()
        self.ps = [mock.patch.object(live, "AUTH_FILE", pathlib.Path(self.auth.name)),
                   mock.patch.dict(os.environ, {"AMD_TOKEN_FACTORY_API_KEY": "test-key-not-real", "AMD_TOKEN_FACTORY_BASE_URL": self.url, "GATEHOUSE_CAPTURE_DIR": self.capdir})]
        for p in self.ps:
            p.start()

    def tearDown(self):
        for p in self.ps:
            p.stop()
        os.unlink(self.auth.name)

    def live(self):
        st = H.start(H.fixture())
        return ai.submit_addendum(st, self.pdf, "d.pdf", parser=ai.live_parser, by=WHO)

    def test_replay_returns_exactly_what_the_live_call_returned_and_is_labeled_recorded(self):
        lv = self.live()
        self.assertEqual((lv["status"], lv["parse"]["mode"]), (ai.PROPOSED, "LIVE"))
        hits, ledger = Fake.hits, open(live.AUTH_FILE).read()
        with mock.patch("socket.socket", side_effect=AssertionError("network used")), mock.patch.object(live, "_reserve", side_effect=AssertionError("ledger used")):
            rp = ai.submit_addendum(H.start(H.fixture()), self.pdf, "d.pdf", parser=ai.recorded_parser, by=WHO)
        self.assertEqual((rp["status"], rp["parse"]["mode"]), (ai.PROPOSED, "RECORDED"))
        self.assertEqual(rp["updates"], lv["updates"])                                      # the same proposed facts, bit for bit
        self.assertEqual(rp["before_after"], lv["before_after"])
        self.assertEqual((rp["parse"]["model"], rp["parse"]["usage"], rp["parse"]["elapsed_ms"]), (lv["parse"]["model"], lv["parse"]["usage"], json.load(open(next(pathlib.Path(self.capdir).glob("*.json"))))["elapsed_ms"]))
        self.assertIn("captured live call 1", rp["parse"]["recorded_from"])
        self.assertIn("RECORDED replay of a captured live reply", rp["parse"]["label"])
        self.assertNotIn("RECONSTRUCTED", rp["parse"]["label"])
        self.assertEqual((Fake.hits, open(live.AUTH_FILE).read()), (hits, ledger))        # no new call, ledger untouched

    def test_no_capture_means_nothing_to_replay_never_a_reconstruction(self):
        rp = ai.submit_addendum(H.start(H.fixture()), self.pdf, "d.pdf", parser=ai.recorded_parser, by=WHO)
        self.assertEqual((rp["status"], rp["parse"]["mode"]), ("HELD_PARSE_UNAVAILABLE", "RECORDED"))
        self.assertIn("never substitutes a reconstruction", rp["message"])

    def test_only_the_exact_document_replays(self):
        self.live()
        other = ai.submit_addendum(H.start(H.fixture()), decoy(G3_LINE, "ANOTHER DOCUMENT"), "x.pdf", parser=ai.recorded_parser, by=WHO)
        self.assertEqual(other["status"], "HELD_PARSE_UNAVAILABLE")

    def test_a_tampered_capture_is_not_replayed(self):
        self.live()
        path = next(pathlib.Path(self.capdir).glob("*_call1.json"))
        cap = json.load(open(path))
        raw = base64.b64decode(cap["response_raw_b64"]).replace(b"14", b"99")
        cap["response_raw_b64"], cap["response_raw_text"] = base64.b64encode(raw).decode(), raw.decode()
        json.dump(cap, open(path, "w"))
        rp = ai.submit_addendum(H.start(H.fixture()), self.pdf, "d.pdf", parser=ai.recorded_parser, by=WHO)
        self.assertEqual(rp["status"], "HELD_PARSE_UNAVAILABLE")

    def test_failed_calls_are_not_replayed_and_the_latest_good_capture_wins(self):
        Fake.mode = "500"
        self.live()
        rp = ai.submit_addendum(H.start(H.fixture()), self.pdf, "d.pdf", parser=ai.recorded_parser, by=WHO)
        self.assertEqual(rp["status"], "HELD_PARSE_UNAVAILABLE")                           # a 500 capture is evidence, not a reply
        Fake.mode = "ok"
        self.live()
        rp = ai.submit_addendum(H.start(H.fixture()), self.pdf, "d.pdf", parser=ai.recorded_parser, by=WHO)
        self.assertEqual((rp["status"], rp["parse"]["capture_file"]), (ai.PROPOSED, f"{self.sha[:12]}_call2.json"))


if __name__ == "__main__":
    unittest.main()

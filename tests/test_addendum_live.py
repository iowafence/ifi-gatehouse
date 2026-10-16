"""The live parser against a LOOPBACK fake of the AMD endpoint. No real network call is ever made by these tests."""
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from engine import addendum_intake as ai, addendum_live as live
from tests import footing_helpers as H
from tests.decoy_pdf import G3_LINE, decoy

WHO = "Uploader (self-declared)"


class Fake(BaseHTTPRequestHandler):
    mode, hits, last = "ok", 0, None

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        type(self).last = json.loads(self.rfile.read(n))
        type(self).hits += 1
        if self.mode == "slow":
            time.sleep(3)
        code, out = 200, {"model": "self-dploy/Qwen3.8-27B", "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                          "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"facts": [{
                              "path": "/gates/2/clear_width_ft", "value": 14, "page": 1, "excerpt": "THE CLEAR OPENING WIDTH IS 14 FEET"}]})}}]}
        if self.mode == "500":
            code, out = 500, {"error": {"message": "boom"}}
        if self.mode == "junk":
            out["choices"][0]["message"]["content"] = "Sure! The width is 14 feet."
        if self.mode == "wrongtext":
            out["choices"][0]["message"]["content"] = json.dumps({"facts": [{"path": "/gates/2/clear_width_ft", "value": 14, "page": 1, "excerpt": "THE CLEAR OPENING WIDTH IS 20 FEET"}]})
        if self.mode == "badslot":
            out["choices"][0]["message"]["content"] = json.dumps({"facts": [{"path": "/gates/1/clear_width_ft", "value": 14, "page": 1, "excerpt": "THE CLEAR OPENING WIDTH IS 14 FEET"}]})
        if self.mode == "nonnumber":
            out["choices"][0]["message"]["content"] = json.dumps({"facts": [{"path": "/gates/2/clear_width_ft", "value": "fourteen", "page": 1, "excerpt": "THE CLEAR OPENING WIDTH IS 14 FEET"}]})
        b = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


class Live(unittest.TestCase):
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
        Fake.mode, Fake.hits, Fake.last = "ok", 0, None
        self.pdf = decoy(G3_LINE)
        import hashlib
        self.sha = hashlib.sha256(self.pdf).hexdigest()
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"purpose": "ADDENDUM_02_PARSE_ONLY", "authorized_by": "test", "model": "Qwen3.8-27B", "max_calls": 3, "timeout_s": 1.0,
                   "allowed_sha256": [self.sha], "calls": []}, self.tmp)
        self.tmp.close()
        self.patches = [mock.patch.object(live, "AUTH_FILE", __import__("pathlib").Path(self.tmp.name)),
                        mock.patch.dict(os.environ, {"AMD_TOKEN_FACTORY_API_KEY": "test-key-not-real", "AMD_TOKEN_FACTORY_BASE_URL": self.url})]
        for p in self.patches:
            p.start()
        self.st = H.start(H.fixture())

    def tearDown(self):
        for p in self.patches:
            p.stop()
        os.unlink(self.tmp.name)

    def calls(self):
        return json.load(open(self.tmp.name))["calls"]

    def up(self, pdf=None):
        return ai.submit_addendum(self.st, pdf or self.pdf, "d.pdf", parser=ai.live_parser, by=WHO)

    def test_authorized_call_logs_model_result_timing_and_proposes(self):
        rec = self.up()
        self.assertEqual(rec["status"], ai.PROPOSED)
        p = rec["parse"]
        self.assertEqual((p["model"], p["result"]), ("self-dploy/Qwen3.8-27B", "RETURNED"))
        self.assertIsInstance(p["elapsed_ms"], int)
        self.assertEqual(p["usage"]["total_tokens"], 120)
        c = self.calls()
        self.assertEqual((len(c), c[0]["result"], c[0]["sha256"]), (1, "RETURNED", self.sha))
        self.assertEqual((Fake.last["model"], Fake.last["temperature"], Fake.hits), ("Qwen3.8-27B", 0.0, 1))
        self.assertNotIn("test-key-not-real", json.dumps(self.st) + open(self.tmp.name).read())
        self.assertIn("/gates/2/clear_width_ft", Fake.last["messages"][1]["content"])
        self.assertEqual(self.st["scope"]["gates"][2]["clear_width_ft"]["status"], "unresolved")     # proposal only

    def test_unlisted_document_is_never_sent(self):
        other = decoy(G3_LINE, "A DIFFERENT DOCUMENT")
        rec = self.up(other)
        self.assertEqual((rec["status"], Fake.hits, self.calls()), ("HELD_PARSE_UNAVAILABLE", 0, []))
        self.assertEqual(rec["parse"]["model"], "NOT_REPORTED")

    def test_http_error_is_one_attempt_no_retry_and_counts(self):
        Fake.mode = "500"
        rec = self.up()
        self.assertEqual((rec["status"], Fake.hits), ("HELD_PARSE_UNAVAILABLE", 1))
        self.assertEqual(rec["parse"]["result"], "UNAVAILABLE")
        self.assertEqual(self.calls()[0]["result"], "HTTP_ERROR")

    def test_timeout_is_one_attempt_and_held(self):
        Fake.mode = "slow"
        t0 = time.monotonic()
        rec = self.up()
        self.assertLess(time.monotonic() - t0, 2.9)
        self.assertEqual(rec["status"], "HELD_PARSE_UNAVAILABLE")
        self.assertEqual(self.calls()[0]["result"], "HTTP_ERROR")
        self.assertEqual(self.calls()[0]["http_status"], 0)

    def test_budget_of_three_total(self):
        Fake.mode = "junk"
        for i in range(3):
            self.st = H.start(H.fixture())                                            # a fresh project each time, the same document
            self.assertEqual(self.up()["status"], "HELD_PARSE_UNAVAILABLE")
        self.assertEqual((Fake.hits, len(self.calls())), (3, 3))
        self.st = H.start(H.fixture())
        rec = self.up()
        self.assertIn("budget", rec["message"])
        self.assertEqual(Fake.hits, 3)                                                # the fourth was never sent

    def test_reply_not_json_is_held(self):
        Fake.mode = "junk"
        rec = self.up()
        self.assertEqual((rec["status"], Fake.hits, self.calls()[0]["result"]), ("HELD_PARSE_UNAVAILABLE", 1, "UNPARSEABLE"))

    def test_model_citing_text_not_on_the_page_is_held(self):
        Fake.mode = "wrongtext"
        self.assertEqual(self.up()["status"], "HELD_UNVERIFIED_EVIDENCE")

    def test_model_answering_outside_the_open_slots_is_held(self):
        Fake.mode = "badslot"
        rec = self.up()
        self.assertEqual(rec["status"], "HELD_UNVERIFIED_EVIDENCE")
        self.assertEqual(self.st["scope"]["gates"][1]["clear_width_ft"]["value"], 12.0)

    def test_non_numeric_value_is_refused_not_coerced(self):
        Fake.mode = "nonnumber"
        rec = self.up()
        self.assertEqual(rec["status"], "HELD_UNVERIFIED_EVIDENCE")
        self.assertEqual(self.st["scope"]["gates"][2]["clear_width_ft"]["status"], "unresolved")

    def test_shipped_authorization_file_lists_no_document_and_uses_no_budget(self):
        d = json.load(open(live.ROOT / "amd_experiment" / "LIVE_AUTH_ADDENDUM_02.json"))
        self.assertEqual((d["allowed_sha256"], d["calls"], d["max_calls"], d["model"]), ([], [], 3, "Qwen3.8-27B"))
        self.assertTrue((live.ROOT / "amd_experiment" / "LIVE_CALLS_DISABLED").exists())   # the harness-wide hold stays in force


if __name__ == "__main__":
    unittest.main()

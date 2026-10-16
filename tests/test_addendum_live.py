"""The live parser against a LOOPBACK fake of the AMD endpoint. No real network call is ever made by these tests."""
import base64
import hashlib
import json
import os
import pathlib
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
    mode, hits, last, last_raw = "ok", 0, None, b""

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw_in = self.rfile.read(n)
        type(self).last = json.loads(raw_in)
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
        type(self).last_raw = b
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
                   "allowed_sha256": [self.sha], "live_caller": "ANVIL 2", "calls": []}, self.tmp)
        self.tmp.close()
        self.capdir = tempfile.mkdtemp()
        self.patches = [mock.patch.object(live, "LEDGER_FILE", __import__("pathlib").Path(self.tmp.name)),
                        mock.patch.dict(os.environ, {"AMD_TOKEN_FACTORY_API_KEY": "test-key-not-real", "AMD_TOKEN_FACTORY_BASE_URL": self.url, "GATEHOUSE_CAPTURE_DIR": self.capdir, "GATEHOUSE_LIVE_CALLER": "ANVIL 2"})]
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
        self.assertEqual(Fake.last["chat_template_kwargs"], {"enable_thinking": False})      # without this the model spends its whole token budget thinking
        self.assertNotIn("test-key-not-real", json.dumps(self.st) + open(self.tmp.name).read())
        self.assertIn("/gates/2/clear_width_ft", Fake.last["messages"][1]["content"])
        self.assertEqual(self.st["scope"]["gates"][2]["clear_width_ft"]["status"], "unresolved")     # proposal only

    def test_every_live_call_stores_the_verbatim_response_and_the_request_without_credentials(self):
        rec = self.up()
        c = self.calls()[0]
        self.assertTrue(c["capture_file"].endswith("_call1.json"))
        path = __import__("pathlib").Path(self.capdir) / c["capture_file"]
        cap = json.load(open(path))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), c["capture_sha256"])
        self.assertEqual(cap["response_raw_text"], Fake.last_raw.decode())                          # byte-for-byte what the endpoint sent
        self.assertEqual(base64.b64decode(cap["response_raw_b64"]), Fake.last_raw)
        self.assertEqual(cap["response_raw_sha256"], hashlib.sha256(Fake.last_raw).hexdigest())
        self.assertEqual(cap["request_body"], Fake.last)                                            # the exact body that was sent
        self.assertEqual((cap["http_status"], cap["source_sha256"], cap["call_no"]), (200, self.sha, 1))
        text = open(path).read()
        self.assertNotIn("test-key-not-real", text)
        self.assertNotIn("Authorization", text)
        self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")
        self.assertEqual(rec["status"], ai.PROPOSED)

    def test_failed_and_unparseable_calls_are_captured_too_and_never_overwritten(self):
        Fake.mode = "junk"
        self.up()
        Fake.mode = "500"
        self.st = H.start(H.fixture())
        self.up()
        names = sorted(c["capture_file"] for c in self.calls())
        self.assertEqual(names, [f"{self.sha[:12]}_call1.json", f"{self.sha[:12]}_call2.json"])
        self.assertEqual(json.load(open(__import__("pathlib").Path(self.capdir) / names[1]))["http_status"], 500)
        with self.assertRaises(FileExistsError):
            live._write_capture(self.sha, 1, "k", {"a": 1}, 200, b"x", 1, None)

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

    def test_budget_total_is_enforced(self):
        Fake.mode = "junk"
        d = json.load(open(self.tmp.name))
        d["max_calls"] = 3
        json.dump(d, open(self.tmp.name, "w"))
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

    def test_only_the_designated_caller_may_make_a_live_call(self):
        for env in ({"GATEHOUSE_LIVE_CALLER": "ANVIL 1"}, {"GATEHOUSE_LIVE_CALLER": ""}):
            with mock.patch.dict(os.environ, env):
                rec = self.up()
            self.assertEqual(rec["status"], "HELD_PARSE_UNAVAILABLE")
            self.assertIn("only ANVIL 2 may make live calls", rec["message"])
            self.st = H.start(H.fixture())
        with mock.patch.dict(os.environ):
            os.environ.pop("GATEHOUSE_LIVE_CALLER", None)
            self.assertEqual(self.up()["status"], "HELD_PARSE_UNAVAILABLE")
        self.assertEqual((Fake.hits, self.calls()), (0, []))                                   # nothing sent, nothing reserved
        self.assertEqual(self.up()["status"], ai.PROPOSED)
        self.assertEqual(self.calls()[0]["caller"], "ANVIL 2")

    def test_the_ledger_lives_outside_the_repository_and_the_hold_stays(self):
        with mock.patch.object(live, "LEDGER_FILE", None):
            self.assertEqual(live.ledger_path(), pathlib.Path(self.capdir) / "ledger.json")
        self.assertNotIn(str(live.ROOT), str(pathlib.Path.home() / "ifi-gatehouse-live-captures"))
        self.assertFalse((live.ROOT / "amd_experiment" / "LIVE_AUTH_ADDENDUM_02.json").exists())   # no authorization/ledger file ships in a branch
        self.assertTrue((live.ROOT / "amd_experiment" / "LIVE_CALLS_DISABLED").exists())            # the harness-wide hold stays in force

    def test_no_ledger_means_no_live_call(self):
        with mock.patch.object(live, "LEDGER_FILE", pathlib.Path(self.capdir) / "absent.json"):
            rec = self.up()
        self.assertEqual((rec["status"], Fake.hits), ("HELD_PARSE_UNAVAILABLE", 0))
        self.assertIn("no ledger", rec["message"])

if __name__ == "__main__":
    unittest.main()

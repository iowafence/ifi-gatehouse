"""Streaming runner tests against a real local HTTP server (loopback only; no AMD traffic)."""
import json, pathlib, sys, threading, time, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ext import streaming  # noqa: E402

KEY = "rc-0123456789abcdef0123456789abcdef0123456789abcdef"
SCENARIO = {"mode": "normal", "requests": 0, "seen_auth": None, "body": None}


def chunk(text=None, finish=None, usage=None, extra=None):
    ev = {"choices": [{"delta": ({"content": text} if text is not None else {}), "finish_reason": finish}], **({"usage": usage} if usage else {}), **(extra or {})}
    return ("data: " + json.dumps(ev) + "\n\n").encode()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        SCENARIO["requests"] += 1
        SCENARIO["seen_auth"] = self.headers.get("Authorization")
        SCENARIO["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        m = SCENARIO["mode"]
        if m == "http429":
            self.send_response(429); self.send_header("Retry-After", "1"); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(b'{"error": {"type": "rate_limit"}}'); return
        if m == "no_headers":
            time.sleep(3); return
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        w = self.wfile
        try:
            if m == "normal":
                time.sleep(0.2)
                for t in ("{\"a\":", " 1", "}"):
                    w.write(chunk(t, extra={"metadata": {"routing": [{"apiKeyHash": "abc123"}]}})); w.flush(); time.sleep(0.05)
                w.write(chunk(None, finish="stop", usage={"prompt_tokens": 5, "completion_tokens": 3})); w.write(b"data: [DONE]\n\n"); w.flush()
            elif m == "stall_after_first":
                w.write(chunk("partial ")); w.flush(); time.sleep(4)
            elif m == "drip":
                for _ in range(100):
                    w.write(chunk("x")); w.flush(); time.sleep(0.2)
            elif m == "close_early":
                w.write(chunk("cut off")); w.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


class Streaming(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}/v1"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def run_mode(self, mode, **kw):
        SCENARIO.update(mode=mode, requests=0)
        return streaming.stream_chat(self.base, KEY, {"model": "m", "messages": []}, **kw)

    def test_normal_stream_telemetry(self):
        r = self.run_mode("normal", no_progress_s=5, wall_s=10)
        t = r["telemetry"]
        self.assertEqual((t["outcome"], t["http_status"], t["partial"], t["finish_reason"], t["cancelled_by_client"]), ("normal", 200, False, "stop", False))
        self.assertEqual(r["content"], '{"a": 1}')
        self.assertEqual(r["usage"], {"prompt_tokens": 5, "completion_tokens": 3})
        for k in ("t_connected_s", "t_request_sent_s", "t_first_byte_s", "t_first_content_token_s", "t_done_s", "t_end_s"):
            self.assertIsNotNone(t.get(k), k)
        self.assertLessEqual(t["t_connected_s"], t["t_request_sent_s"])
        self.assertLessEqual(t["t_first_byte_s"], t["t_first_content_token_s"])
        self.assertGreater(t["inter_chunk_gap_s"]["n"], 0)
        self.assertIn("max", t["inter_chunk_gap_s"])
        self.assertEqual(t["chunks"], 4)
        self.assertTrue(t["usage_supplied"])

    def test_the_key_goes_only_in_the_header_and_never_into_telemetry_or_scrubbed_events(self):
        r = self.run_mode("normal", no_progress_s=5, wall_s=10)
        self.assertEqual(SCENARIO["seen_auth"], f"Bearer {KEY}")
        blob = json.dumps(r)
        self.assertNotIn(KEY, blob)
        self.assertNotIn("abc123", blob)                      # provider key-hash metadata is scrubbed
        self.assertTrue(SCENARIO["body"]["stream"])

    def test_no_progress_after_first_chunk_aborts_keeps_partial_output_and_is_a_client_cancel(self):
        r = self.run_mode("stall_after_first", no_progress_s=0.6, wall_s=10)
        t = r["telemetry"]
        self.assertEqual((t["outcome"], t["cancelled_by_client"], t["partial"], t["http_status"]), ("client_abort_no_progress", True, True, 200))
        self.assertEqual(r["content"], "partial ")
        self.assertLess(t["t_end_s"], 3)
        self.assertEqual(SCENARIO["requests"], 1)             # no retry

    def test_wall_time_limit_aborts_a_stream_that_keeps_making_progress(self):
        r = self.run_mode("drip", no_progress_s=5, wall_s=1.0)
        t = r["telemetry"]
        self.assertEqual(t["outcome"], "client_abort_wall_time")
        self.assertTrue(t["cancelled_by_client"] and t["partial"])
        self.assertGreater(len(r["content"]), 0)
        self.assertLess(t["t_end_s"], 2.5)

    def test_no_response_headers_within_the_no_progress_window_is_reported_as_no_response(self):
        r = self.run_mode("no_headers", no_progress_s=0.6, wall_s=10)
        t = r["telemetry"]
        self.assertEqual((t["outcome"], t["http_status"], t["cancelled_by_client"]), ("client_abort_no_progress", None, True))
        self.assertEqual(SCENARIO["requests"], 1)

    def test_http_error_is_distinguished_from_client_cancellation_and_headers_are_recorded(self):
        r = self.run_mode("http429", no_progress_s=5, wall_s=10)
        t = r["telemetry"]
        self.assertEqual((t["outcome"], t["http_status"], t["cancelled_by_client"]), ("http_error", 429, False))
        self.assertEqual(t["rate_limit_headers"].get("retry-after"), "1")
        self.assertEqual(SCENARIO["requests"], 1)

    def test_stream_closed_without_done_is_partial_and_not_normal(self):
        r = self.run_mode("close_early", no_progress_s=5, wall_s=10)
        self.assertEqual((r["telemetry"]["outcome"], r["telemetry"]["partial"], r["content"]), ("stream_closed_without_done", True, "cut off"))

    def test_connection_refused_is_a_connect_error(self):
        r = streaming.stream_chat("http://127.0.0.1:1/v1", KEY, {"model": "m"}, no_progress_s=1, wall_s=2)
        self.assertEqual(r["telemetry"]["outcome"], "connect_error")
        self.assertNotIn(KEY, json.dumps(r))


if __name__ == "__main__":
    unittest.main()

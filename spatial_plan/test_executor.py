"""Offline mechanics test of run_live_003.py against a LOOPBACK stub (no AMD, no credential). Verifies hold restoration on success, HTTP error, malformed JSON, and SIGTERM mid-request,
and that the executor stops at the first bad outcome. Run from the workspace root with the experiment interpreter."""
import http.server, json, os, pathlib, signal, subprocess, sys, tempfile, threading, time, unittest
HERE = pathlib.Path(__file__).resolve().parent; PY = pathlib.Path(sys.executable)
GOOD = {"1": {"gate_tags": [{"tag": "G3", "adjacent_symbol": "single_leaf_swing", "uncertainty": "clear"}, {"tag": "G1", "adjacent_symbol": "single_leaf_swing", "uncertainty": "clear"}], "type_tags": [{"tag": "B", "leader_ends_on": "interior_divider", "uncertainty": "clear"}], "ambiguous": []},
        "2": {"gate_tags": [{"tag": "G2", "adjacent_symbol": "double_leaf_swing", "uncertainty": "clear"}], "type_tags": [{"tag": "A", "leader_ends_on": "perimeter_fence", "uncertainty": "clear"}], "ambiguous": []},
        "3": {"gate_tags": [{"tag": "G2", "adjacent_symbol": "double_leaf_swing", "uncertainty": "clear"}], "type_tags": [], "ambiguous": []}}
def serve(mode):
    n = {"i": 0}
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0))); n["i"] += 1
            if mode == "500": self.send_response(500); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"{}"); return
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
            if mode == "hang": time.sleep(30); return
            txt = "{\"gate_tags\":[BROKEN" if mode == "malformed" else json.dumps(GOOD[str(n["i"])], separators=(",", ":"))
            self.wfile.write(("data: " + json.dumps({"choices": [{"delta": {"content": txt}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}) + "\n\ndata: [DONE]\n\n").encode()); self.wfile.flush()
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=s.serve_forever, daemon=True).start(); return s, n

def run(mode, sig=None):
    s, n = serve(mode); d = pathlib.Path(tempfile.mkdtemp()); (d / "LIVE_CALLS_DISABLED").write_text("HOLD TEXT\n"); ev = d / "ev"
    p = subprocess.Popen([str(PY), str(HERE / "run_live_003.py"), "--loopback-port", str(s.server_address[1]), "--hold-dir", str(d), "--evidence-dir", str(ev)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(HERE.parent), env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    if sig:
        for _ in range(100):
            if (d / "LIVE_CALLS_DISABLED.suspended_for_one_request").exists(): break
            time.sleep(0.1)
        assert (d / "LIVE_CALLS_DISABLED.suspended_for_one_request").exists(), "hold should be suspended during the request"; p.send_signal(sig)
    out, err = p.communicate(timeout=60); s.shutdown()
    return d, ev, out, err, n["i"]

class Exec(unittest.TestCase):
    def test_success_three_requests_hold_restored(self):
        d, ev, out, err, n = run("ok"); self.assertEqual(n, 3, err); self.assertEqual((d / "LIVE_CALLS_DISABLED").read_text(), "HOLD TEXT\n"); self.assertFalse((d / "LIVE_CALLS_DISABLED.suspended_for_one_request").exists())
        self.assertTrue(all((ev / c / "scoring.json").exists() for c in ("r1_north_band_gates_and_tag", "r2_east_edge_type_tag_and_gate", "r3_west_edge_gate"))); self.assertIn('"requests_made": 3', out)
    def test_http_error_stops_after_first(self):
        d, ev, out, err, n = run("500"); self.assertEqual(n, 1); self.assertIn("STOP after r1", out); self.assertEqual((d / "LIVE_CALLS_DISABLED").read_text(), "HOLD TEXT\n")
    def test_malformed_json_stops_after_first(self):
        d, ev, out, err, n = run("malformed"); self.assertEqual(n, 1); self.assertIn("STOP after r1", out); self.assertEqual((d / "LIVE_CALLS_DISABLED").read_text(), "HOLD TEXT\n")
    def test_sigterm_mid_request_restores_hold(self):
        d, ev, out, err, n = run("hang", signal.SIGTERM); self.assertEqual(n, 1); self.assertEqual((d / "LIVE_CALLS_DISABLED").read_text(), "HOLD TEXT\n"); self.assertFalse((d / "LIVE_CALLS_DISABLED.suspended_for_one_request").exists())
    def test_refuses_wrong_authorized_hash_and_missing_hold(self):
        r = subprocess.run([str(PY), str(HERE / "run_live_003.py"), "--authorized-plan-sha256", "0" * 64, "--preflight-only"], capture_output=True, text=True, cwd=str(HERE.parent)); self.assertNotEqual(r.returncode, 0); self.assertIn("authorized hash differs", r.stderr)
if __name__ == "__main__": unittest.main()

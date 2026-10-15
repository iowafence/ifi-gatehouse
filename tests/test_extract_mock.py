"""Exercises the extraction client against a local mock OpenAI-compatible server (no model needed)."""
import json, pathlib, sys, threading, unittest, copy, subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import extract_scope as ex  # noqa: E402
from engine.validate import validate_scope  # noqa: E402

SAMPLE = json.load(open(ROOT / "samples/scope_synthetic.json"))
PDF = "/tmp/_mock_plan.pdf"


def make_pdf():
    # one-page PDF via LibreOffice-free route: use a tiny hand-written PDF
    open(PDF, "wb").write(b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
                          b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R/Size 4>>\n%%EOF")


def serve(payloads):
    calls = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers["Content-Length"]); calls.append(json.loads(self.rfile.read(n)))
            body = json.dumps({"choices": [{"message": {"content": payloads[min(len(calls) - 1, len(payloads) - 1)]}}]}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, calls


@unittest.skipUnless(subprocess.run(["which", "pdftoppm"], capture_output=True).returncode == 0, "poppler not installed")
class Extract(unittest.TestCase):
    def setUp(self):
        make_pdf()

    def run_extract(self, payloads):
        srv, calls = serve(payloads)
        try:
            return ex.extract([("PLANS", PDF, [1])], f"http://127.0.0.1:{srv.server_port}/v1", "mock", "k", dpi=40, retries=1), calls
        finally:
            srv.shutdown()

    def test_clean_output_accepted_first_try(self):
        res, calls = self.run_extract(["```json\n" + json.dumps(SAMPLE) + "\n```"])
        self.assertEqual(res["problems"], [])
        self.assertEqual(len(calls), 1)
        msg = calls[0]["messages"][1]["content"]
        self.assertTrue(any(c["type"] == "image_url" for c in msg))   # page image was sent

    def test_model_emitted_money_is_rejected_then_repaired(self):
        bad = copy.deepcopy(SAMPLE); bad["fence_runs"][0]["unit_price"] = 55.0
        res, calls = self.run_extract([json.dumps(bad), json.dumps(SAMPLE)])
        self.assertEqual(res["problems"], [])
        self.assertEqual(res["attempt"], 2)
        self.assertIn("money-like key", calls[1]["messages"][-1]["content"])

    def test_guessing_on_unresolved_is_caught(self):
        bad = copy.deepcopy(SAMPLE); bad["fence_runs"][1]["height_ft"]["value"] = 3.5   # status still 'unresolved'
        self.assertTrue(any("model guessed" in p for p in validate_scope(bad)))

    def test_unparseable_then_repaired(self):
        res, calls = self.run_extract(["sorry, here you go: not json", json.dumps(SAMPLE)])
        self.assertEqual(res["problems"], [])


class Validate(unittest.TestCase):
    def test_sample_scope_is_valid(self):
        self.assertEqual(validate_scope(SAMPLE), [])

    def test_inferred_without_note_flagged(self):
        bad = copy.deepcopy(SAMPLE); del bad["fence_runs"][0]["length_lf"]["inference_note"]
        self.assertTrue(any("inference_note" in p for p in validate_scope(bad)))


if __name__ == "__main__":
    unittest.main()

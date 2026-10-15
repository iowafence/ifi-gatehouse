"""HTTP-level tests against the real server on an ephemeral local port. No network beyond loopback."""
import copy, json, os, pathlib, subprocess, sys, threading, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

from api import server

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCOPE = json.load(open(ROOT / "samples/scope_synthetic.json"))
KEY = "test-key-not-a-real-secret"


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["ENGINE_API_KEY"], os.environ["ENGINE_DEV_ROUTES"] = KEY, "1"
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        os.environ.pop("ENGINE_API_KEY", None)
        os.environ.pop("ENGINE_DEV_ROUTES", None)

    def call(self, method, path, body=None, key=KEY, raw=None):
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if key is not None:
            req.add_header("X-Engine-Key", key)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def new_project(self, scope=SCOPE):
        code, out = self.call("POST", "/dev/projects", {"scope": scope})
        self.assertEqual(code, 201, out)
        return out["project_id"], out

    def test_auth_required_and_constant_key(self):
        for key in (None, "", "wrong", KEY + "x"):
            self.assertEqual(self.call("GET", "/health", key=key)[0], 401)
        self.assertEqual(self.call("GET", "/health")[0], 200)

    def test_server_refuses_to_start_without_key_or_explicit_noauth(self):
        env = {k: v for k, v in os.environ.items() if k not in ("ENGINE_API_KEY", "ENGINE_ALLOW_NOAUTH")}
        r = subprocess.run([sys.executable, "-m", "api.server"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ENGINE_API_KEY", r.stderr)

    def test_health_does_not_claim_unprobed_components_are_connected(self):
        os.environ["EVOLUS_WORKFLOW_ID"] = "set-but-never-probed"
        try:
            h = self.call("GET", "/health")[1]
        finally:
            os.environ.pop("EVOLUS_WORKFLOW_ID")
        self.assertEqual(h["evolus"]["status"], "not_probed")
        self.assertEqual(h["amd_inference"]["status"], "not_probed")
        self.assertNotIn("connected", json.dumps(h))

    def test_unimplemented_routes_say_so(self):
        for m, p in (("POST", "/projects/upload"), ("GET", "/projects/abc/documents"), ("GET", "/projects/abc/proposal")):
            self.assertEqual(self.call(m, p, {} if m == "POST" else None)[0], 501)

    def test_dev_route_off_by_default(self):
        os.environ.pop("ENGINE_DEV_ROUTES")
        try:
            self.assertEqual(self.call("POST", "/dev/projects", {"scope": SCOPE})[0], 404)
        finally:
            os.environ["ENGINE_DEV_ROUTES"] = "1"

    def test_oversized_and_malformed_bodies(self):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=10)
        conn.putrequest("POST", "/dev/projects")  # declares a huge body; the server must refuse before reading it
        conn.putheader("X-Engine-Key", KEY)
        conn.putheader("Content-Length", str(server.MAX_BODY + 1))
        conn.endheaders()
        self.assertEqual(conn.getresponse().status, 413)
        conn.close()
        self.assertEqual(self.call("POST", "/dev/projects", raw=b"[1,2]")[0], 400)
        self.assertEqual(self.call("POST", "/dev/projects", raw=b"{not json")[0], 400)

    def test_empty_scope_over_http_has_no_price_and_cannot_release(self):
        pid, out = self.new_project({})
        self.assertEqual(out["status"], "needs_scope_review")
        self.assertIsNone(out["estimate"])
        code, err = self.call("POST", f"/projects/{pid}/release",
                              {"approver": "Test Approver", "expected_scope_version": 1, "expected_proposal_digest": "0" * 64})
        self.assertEqual(code, 409, err)

    def test_full_three_gate_flow_and_stale_digest(self):
        pid, out = self.new_project()
        self.assertEqual(out["status"], "needs_scope_review")
        self.assertIsNone(out["estimate"])
        who = {"by": "Test Reviewer", "note": "test decision"}
        for eid, opt in (("EX-BID_SELECTION_REQUIRED-/bid_structure/selected_bid", "base"),
                         ("EX-PLAN_SPEC_CONFLICT-/fence_runs/1/height_ft", "v:3.5"),
                         ("EX-PLAN_SPEC_CONFLICT-/accessories/1/applies_to_gates", "v:no")):
            code, out = self.call("POST", f"/projects/{pid}/scope/resolve", {"exception_id": eid, "option_id": opt, **who})
            self.assertEqual(code, 200, out)
        self.assertEqual(out["status"], "needs_labor_review")
        self.assertIsNone(out["estimate"])
        self.assertTrue(out["provisional_quantities"])
        code, _ = self.call("POST", f"/projects/{pid}/labor/resolve", {"decision": "verified_standard"})
        self.assertEqual(code, 400)
        labor = {"by": "Test Reviewer", "decision": "verified_standard", "certified_payroll": False,
                 "applicability_review": "fictional test applicability check", "source_refs": ["fictional-1"], "note": "test"}
        self.assertEqual(self.call("POST", f"/projects/{pid}/labor/resolve", {**labor, "by": ""})[0], 409)
        self.assertEqual(self.call("POST", f"/projects/{pid}/labor/resolve", {**labor, "surprise": 1})[0], 400)
        code, out = self.call("POST", f"/projects/{pid}/labor/resolve", labor)
        self.assertEqual((code, out["status"]), (200, "ready_for_final_review"))
        digest, version = out["proposal_digest"], out["scope_version"]
        self.assertEqual(len(digest), 64)
        rel = {"approver": "Test Approver", "expected_scope_version": version, "note": "reviewed"}
        self.assertEqual(self.call("POST", f"/projects/{pid}/release", {**rel, "expected_proposal_digest": "0" * 64})[0], 409)
        self.assertEqual(self.call("POST", f"/projects/{pid}/release", {**rel, "approver": " ", "expected_proposal_digest": digest})[0], 409)
        self.assertEqual(self.call("POST", f"/projects/{pid}/release", {**rel, "expected_scope_version": version - 1, "expected_proposal_digest": digest})[0], 409)
        code, out = self.call("POST", f"/projects/{pid}/release", {**rel, "expected_proposal_digest": digest})
        self.assertEqual((code, out["status"], out["proposal_digest"]), (200, "released", digest))
        self.assertEqual(self.call("POST", f"/projects/{pid}/release", {**rel, "expected_proposal_digest": digest})[0], 409)
        self.assertNotIn(KEY, json.dumps(self.call("GET", f"/projects/{pid}")[1]))

    def test_zero_width_resolution_rejected_over_http(self):
        sc = copy.deepcopy(SCOPE)
        sc["gates"][0]["clear_width_ft"] = {"value": None, "status": "unresolved", "unit": "ft", "evidence": []}
        pid, out = self.new_project(sc)
        eid = "EX-MISSING_VALUE-/gates/0/clear_width_ft"
        self.assertIn(eid, [e["exception_id"] for e in out["exceptions"]])
        for bad in (0, -1, "4", True):
            code, _ = self.call("POST", f"/projects/{pid}/scope/resolve", {"exception_id": eid, "value": bad, "by": "Test Reviewer", "note": "n"})
            self.assertEqual(code, 409, bad)


if __name__ == "__main__":
    unittest.main()

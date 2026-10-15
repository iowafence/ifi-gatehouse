"""Demo mode: server-side-only creation of isolated fictional projects, owner scoping, caps and expiry."""
import json, os, uuid, threading, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

from api import server

KEY = "demo-test-key-not-real"
A, B = "a" * 64, "b" * 64
BID = "EX-BID_SELECTION_REQUIRED-/bid_structure/selected_bid"
G3 = "EX-MISSING_VALUE-/gates/2/clear_width_ft"


class DemoRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"ENGINE_API_KEY": KEY, "ENGINE_DEMO_ROUTES": "1"})
        self.env.start()
        os.environ.pop("ENGINE_DEV_ROUTES", None)
        server.PROJECTS.clear()
        server.META.clear()

    def tearDown(self):
        self.env.stop()

    def call(self, method, path, body=None, owner=A, key=KEY, idem=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=None if body is None else json.dumps(body).encode())
        req.add_header("Content-Type", "application/json")
        if key:
            req.add_header("X-Engine-Key", key)
        if "/decisions/" in path and idem is not False:
            req.add_header("Idempotency-Key", idem or ("t-" + uuid.uuid4().hex))      # one fresh key per intentional decision
        if owner:
            req.add_header("X-Demo-Owner", owner)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def create(self, owner=A):
        code, out = self.call("POST", "/demo/projects", {}, owner=owner)
        self.assertEqual(code, 201, out)
        return out["project_id"], out

    def test_disabled_unless_flag_set(self):
        os.environ.pop("ENGINE_DEMO_ROUTES")
        self.assertEqual(self.call("POST", "/demo/projects", {})[0], 404)

    def test_key_and_owner_header_required(self):
        self.assertEqual(self.call("POST", "/demo/projects", {}, key=None)[0], 401)
        for bad in (None, "", "short", "G" * 64, "A" * 64, "a" * 63):
            self.assertEqual(self.call("POST", "/demo/projects", {}, owner=bad)[0], 400, bad)

    def test_dev_route_stays_off_in_demo_mode(self):
        self.assertEqual(self.call("POST", "/dev/projects", {"scope": {}})[0], 404)

    def test_creates_the_builtin_fixture_and_ignores_caller_scope(self):
        code, out = self.call("POST", "/demo/projects", {"scope": {"fence_runs": []}, "rates": {"x": 1}})
        self.assertEqual(code, 201)
        self.assertEqual(out["status"], "needs_scope_review")
        self.assertEqual([e["code"] for e in out["exceptions"] if e["severity"] == "blocking"], ["MISSING_VALUE"])  # gate G3 width
        self.assertEqual(out["pricing"]["mode"], "ratebook")
        self.assertIsNone(out["estimate"])

    def test_other_owner_cannot_read_or_mutate(self):
        pid, _ = self.create(A)
        for owner in (B, None):
            self.assertEqual(self.call("GET", f"/projects/{pid}", owner=owner)[0], 404)
            self.assertEqual(self.call("POST", f"/projects/{pid}/scope/resolve",
                                       {"exception_id": BID, "option_id": "base", "by": "X", "note": "n"}, owner=owner)[0], 404)
        self.assertEqual(self.call("GET", f"/projects/{pid}")[1]["scope_version"], 1)
        self.assertEqual(self.call("GET", "/projects/" + "0" * 32)[0], 404)  # unknown id answers the same way

    def test_one_owners_release_does_not_touch_another(self):
        from tests.test_ratebook_workflow import wage_args
        pa, _ = self.create(A)
        pb, _ = self.create(B)
        who = {"by": "Visitor A", "note": "demo"}
        self.assertEqual(self.call("POST", f"/projects/{pa}/scope/resolve", {"exception_id": G3, "value": 10.0, **who})[0], 200)
        sha = self.call("GET", f"/projects/{pa}")[1]
        sha = next(e["required_decision"]["sha256"] for e in sha["exceptions"] if e["code"] == "QUANTITY_RULESET_UNAPPROVED")
        self.assertEqual(self.call("POST", f"/projects/{pa}/decisions/ruleset-approval", {**who, "ruleset_sha256": sha})[0], 200)
        self.assertEqual(self.call("POST", f"/projects/{pa}/decisions/wage-determination", wage_args(by="Visitor A"))[0], 200)
        code, out = self.call("POST", f"/projects/{pa}/decisions/crew-plan", {
            **who, "preferred_crew": "CR13", "assignments": {"L02": "CR13"}, "use_default_for_unassigned": False, "difficulty": {"default": "standard"}})
        self.assertEqual((code, out["status"]), (200, "ready_for_final_review"))
        rel = {"approver": "Visitor A", "expected_scope_version": out["scope_version"], "expected_proposal_digest": out["proposal_digest"]}
        self.assertEqual(self.call("POST", f"/projects/{pb}/release", rel, owner=B)[0], 409)   # B cannot release with A's digest
        self.assertEqual(self.call("POST", f"/projects/{pa}/release", rel)[1]["status"], "released")
        b = self.call("GET", f"/projects/{pb}", owner=B)[1]
        self.assertEqual((b["status"], b["scope_version"], len(b["audit"])), ("needs_scope_review", 1, 1))
        self.assertIsNone(b["estimate"])
        self.assertIsNone(b["pricing"]["crew_plan"])

    def test_delete_is_owner_checked(self):
        pid, _ = self.create(A)
        self.assertEqual(self.call("DELETE", f"/demo/projects/{pid}", owner=B)[0], 404)
        self.assertEqual(self.call("GET", f"/projects/{pid}")[0], 200)
        self.assertEqual(self.call("DELETE", f"/demo/projects/{pid}")[0], 200)
        self.assertEqual(self.call("GET", f"/projects/{pid}")[0], 404)

    def test_idle_projects_expire_and_are_evicted(self):
        pid, _ = self.create(A)
        server.META[pid]["touched"] -= 7 * 3600
        self.assertEqual(self.call("GET", f"/projects/{pid}")[0], 404)
        server.META[pid]["touched"] -= 0
        self.create(B)  # creation sweeps expired projects
        self.assertNotIn(pid, server.PROJECTS)

    def test_project_cap(self):
        os.environ["DEMO_MAX_PROJECTS"] = "2"
        self.create(A); self.create(B)
        self.assertEqual(self.call("POST", "/demo/projects", {}, owner="c" * 64)[0], 503)

    def test_capacity_rejects_predictably_and_never_evicts_active_projects(self):
        os.environ["DEMO_MAX_PROJECTS"] = "3"
        pids = [self.create(o)[0] for o in (A, B, "c" * 64)]
        for pid, o in zip(pids, (A, B, "c" * 64)): self.assertEqual(self.call("GET", f"/projects/{pid}", owner=o)[0], 200)   # all three are in use
        before = {pid: server.META[pid]["touched"] for pid in pids}
        for _ in range(5):
            code, out = self.call("POST", "/demo/projects", {}, owner="d" * 64)
            self.assertEqual(code, 503); self.assertIn("capacity", out["error"])                 # controlled, identical rejection each time
        self.assertEqual(set(server.PROJECTS), set(pids), "no active project was evicted or overwritten by arriving requests")
        for pid, o in zip(pids, (A, B, "c" * 64)): self.assertEqual(self.call("GET", f"/projects/{pid}", owner=o)[0], 200)
        self.assertEqual(len(server.PROJECTS), 3, "memory is bounded by the cap")

    def test_untouched_projects_free_their_slot_quickly_but_used_ones_do_not(self):
        os.environ["DEMO_MAX_PROJECTS"] = "3"; os.environ["DEMO_UNTOUCHED_TTL_SECONDS"] = "60"
        used, _ = self.create(A); idle1, _ = self.create(B); idle2, _ = self.create("c" * 64)
        self.assertEqual(self.call("GET", f"/projects/{used}", owner=A)[0], 200)                 # real activity
        self.assertEqual(self.call("POST", "/demo/projects", {}, owner="d" * 64)[0], 503)         # full: flood-created idle projects hold the slots
        for pid in (used, idle1, idle2): server.META[pid]["created"] -= 120; server.META[pid]["touched"] -= 120
        code, _ = self.call("POST", "/demo/projects", {}, owner="d" * 64)
        self.assertEqual(code, 201, "capacity recovers after the short untouched window")
        self.assertIn(used, server.PROJECTS, "a project with activity is kept (full idle TTL)"); self.assertNotIn(idle1, server.PROJECTS); self.assertNotIn(idle2, server.PROJECTS)
        self.assertEqual(self.call("GET", f"/projects/{used}", owner=A)[0], 200)

    def test_a_reclaimed_untouched_project_is_indistinguishable_from_missing(self):
        os.environ["DEMO_UNTOUCHED_TTL_SECONDS"] = "60"; pid, _ = self.create(A)
        server.META[pid]["created"] -= 120; server.META[pid]["touched"] -= 120; self.create(B)       # creation sweeps
        self.assertEqual(self.call("GET", f"/projects/{pid}", owner=A)[0], 404)

    def test_mutation_cap_per_project(self):
        os.environ["DEMO_MAX_MUTATIONS"] = "3"
        pid, _ = self.create(A)
        bad = {"exception_id": "EX-NOPE", "option_id": "x", "by": "A", "note": "n"}
        codes = [self.call("POST", f"/projects/{pid}/scope/resolve", bad)[0] for _ in range(4)]
        self.assertEqual(codes, [409, 409, 409, 429])

    def test_oversized_fields_are_refused(self):
        pid, _ = self.create(A)
        code, _ = self.call("POST", f"/projects/{pid}/scope/resolve",
                            {"exception_id": BID, "option_id": "base", "by": "A", "note": "x" * 5000})
        self.assertEqual(code, 400)
        self.assertEqual(self.call("GET", f"/projects/{pid}")[1]["scope_version"], 1)


if __name__ == "__main__":
    unittest.main()

"""Independent review v6 (pass-6 backend): independent HTTP-layer checks against the ISOLATED PASS-6 COPY (never a running service).
Binds 127.0.0.1 on an ephemeral port in-process. All data fictional. Run:
  cd ~/loom-remediation-package/p2 && ENGINE_COPY=<copy of ~/ifi-verification/demo-build/engine> PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_http_independent
Observations that are findings (not asserted as pass/fail) are written to p6_observations.json next to this file."""
import copy, json, os, pathlib, sys, threading, unittest, urllib.error, urllib.request, uuid
from http.server import ThreadingHTTPServer
from unittest import mock

COPY = pathlib.Path(os.environ["ENGINE_COPY"]).resolve()
sys.path.insert(0, str(COPY))
from api import server                       # noqa: E402
from engine import integration                # noqa: E402
from tests.test_ratebook_workflow import wage_args   # noqa: E402

KEY, A, B = "p2-test-key-not-real", "a" * 64, "b" * 64
G3 = "EX-MISSING_VALUE-/gates/2/clear_width_ft"
WHO = {"by": "Pat Estimator", "note": "reviewed"}
OBS = {}


def plan(pref="CR13", assign=None, diff="standard", **extra):
    return {**({"preferred_crew": pref} if pref else {}), "assignments": {"L02": "CR13", **(assign or {})}, "use_default_for_unassigned": False,
            "difficulty": {"default": diff, "overrides": {}}, **extra}


class H(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close()
        pathlib.Path(__file__).with_name("p6_observations.json").write_text(json.dumps(OBS, indent=2, sort_keys=True) + "\n")

    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"ENGINE_API_KEY": KEY, "ENGINE_DEMO_ROUTES": "1"}); self.env.start()
        server.PROJECTS.clear(); server.META.clear()
        c, out = self.call("POST", "/demo/projects", {}); self.assertEqual(c, 201, out); self.pid = out["project_id"]

    def tearDown(self):
        self.env.stop()

    def call(self, method, path, body=None, owner=A, key=KEY, raw=None, idem=None):
        req = urllib.request.Request(self.base + path, method=method, data=raw if raw is not None else (None if body is None else json.dumps(body).encode()))
        req.add_header("Content-Type", "application/json")
        if key is not None: req.add_header("X-Engine-Key", key)
        if owner: req.add_header("X-Demo-Owner", owner)
        if "/decisions/" in path and idem is not False: req.add_header("Idempotency-Key", idem or ("v2-" + uuid.uuid4().hex))
        try:
            with urllib.request.urlopen(req, timeout=15) as r: return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            try: return e.code, json.load(e)
            except Exception: return e.code, {}

    def post(self, suffix, body, expect=200, **kw):
        c, out = self.call("POST", f"/projects/{self.pid}/{suffix}", body, **kw); self.assertEqual(c, expect, out); return out

    def get(self, **kw): return self.call("GET", f"/projects/{self.pid}", **kw)

    def wage_cleared(self):
        self.post("scope/resolve", {"exception_id": G3, "value": 10.0, **WHO})
        sha = next(e["required_decision"]["sha256"] for e in self.get()[1]["exceptions"] if e["code"] == "QUANTITY_RULESET_UNAPPROVED")
        self.post("decisions/ruleset-approval", {**WHO, "ruleset_sha256": sha})
        return self.post("decisions/wage-determination", wage_args())

    def stable(self):
        """Everything a read-only call must not change: the summary (minus nothing) and the per-project mutation counter."""
        s = self.get()[1]
        return json.dumps(s, sort_keys=True), server.META[self.pid]["mutations"], len(server.PROJECTS[self.pid]["audit"])


class Isolation(H):
    def test_other_owner_missing_owner_and_missing_key(self):
        self.wage_cleared()
        for method, path, body in (("GET", f"/projects/{self.pid}", None), ("POST", f"/projects/{self.pid}/crew-plan/preview", plan()),
                                   ("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan()}),
                                   ("POST", f"/projects/{self.pid}/release", {"approver": "x", "expected_scope_version": 1, "expected_proposal_digest": "0" * 64})):
            self.assertEqual(self.call(method, path, body, owner=B)[0], 404, (method, path))
            self.assertEqual(self.call(method, path, body, owner=None)[0], 404, (method, path))
            self.assertEqual(self.call(method, path, body, key=None)[0], 401)
            self.assertEqual(self.call(method, path, body, key="wrong")[0], 401)
        self.assertEqual(self.call("DELETE", f"/demo/projects/{self.pid}", owner=B)[0], 404)
        self.assertEqual(self.get()[0], 200)                                   # still there for the owner
        self.assertEqual(self.call("POST", "/demo/projects", {}, owner="not-hex")[0], 400)

    def test_two_owners_get_independent_projects(self):
        c, o2 = self.call("POST", "/demo/projects", {}, owner=B)
        self.assertEqual(c, 201); pid2 = o2["project_id"]
        self.assertNotEqual(pid2, self.pid)
        self.wage_cleared()
        self.post("decisions/crew-plan", {**WHO, **plan()})
        s2 = self.call("GET", f"/projects/{pid2}", owner=B)[1]
        self.assertIsNone(s2["pricing"]["crew_plan"]); self.assertIsNone(s2["estimate"])
        self.assertEqual(self.call("GET", f"/projects/{self.pid}", owner=B)[0], 404)


class Preview(H):
    def test_preview_never_mutates_state_audit_or_mutation_counter(self):
        self.wage_cleared()
        before = self.stable()
        for body in (plan(), plan(assign={"L02": "CR11"}), plan(assign={"L02": "CR14"}, diff="hard"), plan(pref="CR12", assign={"L03": "CR14"})):
            c, out = self.call("POST", f"/projects/{self.pid}/crew-plan/preview", body)
            self.assertEqual(c, 200, out); self.assertTrue(out["draft"])
            self.assertEqual(self.stable(), before)
        v = self.call("POST", f"/projects/{self.pid}/crew-plan/preview", plan())[1]
        self.assertTrue(v["valid"]); self.assertIsNotNone(v["estimate"])
        self.assertIsNone(self.get()[1]["estimate"])                            # a valid preview prices nothing in the project
        self.assertIsNone(self.get()[1]["proposal_digest"])
        for bad in ({"x": 1}, {"assignments": [1]}, {"difficulty": {"default": "extreme"}}, {}):
            c, _ = self.call("POST", f"/projects/{self.pid}/crew-plan/preview", {**plan(), **bad} if "x" in bad or "assignments" in bad else bad)
            self.assertIn(c, (200, 400)); self.assertEqual(self.stable(), before)

    def test_preview_reports_the_exact_missing_role_for_a_forged_drilling_assignment(self):
        self.wage_cleared()
        out = self.call("POST", f"/projects/{self.pid}/crew-plan/preview", plan(assign={"L02": "CR11"}))[1]
        self.assertFalse(out["valid"]); self.assertIsNone(out["estimate"])
        self.assertTrue(any(p["code"] == "CREW_UNSUITABLE" for p in out["problems"]))
        msg = [p["message_display"] for p in out["problems"] if p["code"] == "CREW_UNSUITABLE"]
        OBS["preview_missing_role_wording"] = msg
        self.assertTrue(any("Equipment operator" in m and "Crew 1" in m for m in msg), msg)

    def test_preview_is_bounded_per_project_by_a_process_local_limiter(self):
        self.wage_cleared()
        codes = [self.call("POST", f"/projects/{self.pid}/crew-plan/preview", plan())[0] for _ in range(30)]
        OBS["preview_30_calls_status_codes"] = codes
        self.assertEqual(codes[:20], [200] * 20)                      # default 20/min per project
        self.assertEqual(set(codes[20:]), {429})                      # FIXED in pass 2 (process-local limiter)


class ForgedAssignments(H):
    def test_ineligible_unknown_and_malformed_assignments_are_refused_and_leave_state_untouched(self):
        self.wage_cleared()
        before = self.stable()
        cases = [({"L02": "CR11"}, 409), ({"L02": "CR12"}, 409), ({"L99": "CR13"}, 409), ({"L02": "CR99"}, 409), ({"L02": ["CR13"]}, 400), ({"L02": None}, 409)]
        for asg, want in cases:
            c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan(assign=asg)})
            self.assertEqual(c, want, (asg, out)); self.assertNotIn("estimate_view", out)
            after = self.stable()
            # a refused call must not change the project; the mutation counter DOES count the attempt (documented)
            self.assertEqual((after[0], after[2]), (before[0], before[2]), asg)
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan(), "approved_by": "me", "plan_version": 99})
        self.assertEqual(c, 400)                                                  # client cannot set engine-owned fields
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, "preferred_crew": "CR11", "use_default_for_unassigned": False,
                                                                                 "difficulty": {"default": "standard"}})
        self.assertEqual(c, 409)                                                  # drilling task unassigned and preferred crew can't drill: nothing guessed
        self.assertIsNone(self.get()[1]["estimate"])

    def test_assignment_of_a_non_fleet_legacy_crew_is_now_rejected_by_the_adapter(self):
        self.wage_cleared()
        before = json.dumps(self.get()[1], sort_keys=True)
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan(pref="CR13", assign={"L02": "CR1"})})
        OBS["assign_legacy_default_crew_CR1_status"] = [c, out.get("code")]
        self.assertEqual((c, out["code"]), (409, "CREW_NOT_IN_FLEET"))      # FIXED in pass 2: CR1 is engine-eligible for L02 but not an active fleet crew
        self.assertEqual(json.dumps(self.get()[1], sort_keys=True), before)

    def test_blank_actor_or_note_is_refused(self):
        self.wage_cleared()
        for who in ({"by": "", "note": "n"}, {"by": "Pat", "note": " "}, {"note": "n"}):
            self.assertEqual(self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**who, **plan()})[0] in (400, 409), True)
        self.assertIsNone(self.get()[1]["estimate"])


class DigestsAndReplay(H):
    def adopt(self, **kw):
        return self.post("decisions/crew-plan", {**WHO, **plan(**kw)})

    def test_stale_digest_is_refused_at_release_and_current_one_releases_exactly_once(self):
        self.wage_cleared()
        d1 = self.adopt()["proposal_digest"]
        d2 = self.adopt(pref="CR14", assign={"L02": "CR14"})["proposal_digest"]
        self.assertNotEqual(d1, d2)
        sv = self.get()[1]["scope_version"]
        rel = lambda d, sv_=sv: self.call("POST", f"/projects/{self.pid}/release", {"approver": "Test Approver", "expected_scope_version": sv_, "expected_proposal_digest": d})
        self.assertEqual(rel(d1)[0], 409)                                         # stale digest
        self.assertEqual(rel("0" * 64)[0], 409)
        self.assertEqual(rel(d2, sv + 1)[0], 409)                                 # stale scope version
        self.assertEqual(rel(d2, "1")[0] in (400, 409), True)
        c, out = rel(d2); self.assertEqual(c, 200, out)
        c2, _ = rel(d2); self.assertEqual(c2, 409)                                # release replay refused
        self.assertEqual(self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan()})[0], 409)   # no decisions after release

    def test_replay_of_an_identical_crew_plan_decision(self):
        self.wage_cleared()
        body = {**WHO, **plan()}
        c, a = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", body, idem="v2-replay-key-0001"); self.assertEqual(c, 200)
        before = json.dumps(self.get()[1], sort_keys=True)
        c, b = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", body, idem="v2-replay-key-0001")       # exact replay
        OBS["replay_same_key_same_payload"] = {"status": c, "same_body": a == b, "plan_version": b["pricing"]["crew_plan"]["plan_version"]}
        self.assertEqual((c, a == b), (200, True))
        self.assertEqual(json.dumps(self.get()[1], sort_keys=True), before)                                           # no new event/version/digest
        c, o = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", body, idem="v2-replay-key-0002")       # new key, identical plan
        OBS["new_key_identical_plan"] = [c, o.get("code")]
        self.assertEqual((c, o["code"]), (409, "DECISION_UNCHANGED"))
        c, o = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**body, "note": "other"}, idem="v2-replay-key-0001")
        self.assertEqual((c, o["code"]), (409, "IDEMPOTENCY_KEY_REUSED"))

    def test_replay_of_ruleset_and_wage_decisions(self):
        self.post("scope/resolve", {"exception_id": G3, "value": 10.0, **WHO})
        sha = next(e["required_decision"]["sha256"] for e in self.get()[1]["exceptions"] if e["code"] == "QUANTITY_RULESET_UNAPPROVED")
        self.post("decisions/ruleset-approval", {**WHO, "ruleset_sha256": sha}, idem="v2-ruleset-orig-01")
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/ruleset-approval", {"by": "Someone Else", "note": "overwrite", "ruleset_sha256": sha})
        OBS["replay_ruleset_approval_new_key_status"] = [c, out.get("code")]
        self.assertEqual((c, out["code"]), (409, "RULESET_ALREADY_APPROVED"))
        self.assertEqual(self.get()[1]["pricing"]["ruleset"]["approved_by"], WHO["by"])
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/ruleset-approval", {**WHO, "ruleset_sha256": sha}, idem="v2-ruleset-orig-01")
        self.assertEqual(c, 200)
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/ruleset-approval", {**WHO, "ruleset_sha256": "0" * 64})
        self.assertIn(c, (400, 409))                                              # wrong digest cannot approve
        self.post("decisions/wage-determination", wage_args())
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/wage-determination", wage_args())
        OBS["wage_determination_same_modification_new_key_status"] = c      # engine semantics unchanged: recorded again under a NEW key (identifiable in the ledger)
        old = wage_args(); old["determination"] = {**old["determination"], "modification": "-1"}
        self.assertIn(self.call("POST", f"/projects/{self.pid}/decisions/wage-determination", old)[0], (400, 409))

    def test_changed_wage_decision_after_a_plan_voids_the_plan_or_digest(self):
        self.wage_cleared()
        d1 = self.adopt()["proposal_digest"]
        w = wage_args(); w["determination"] = {**w["determination"], "modification": "1"}
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/wage-determination", w)
        s = self.get()[1]
        OBS["after_wage_modification_1"] = {"status": c, "plan_kept": s["pricing"]["crew_plan"] is not None, "digest_same": s["proposal_digest"] == d1}
        self.assertNotEqual(s["proposal_digest"], d1) if s["proposal_digest"] else None


class Bounds(H):
    def test_malformed_bodies_never_crash_or_half_apply(self):
        self.wage_cleared(); before = self.stable()
        for raw in (b"{", b"[]", b"null", b'{"by": 1}', b'"x"'):
            c, _ = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", raw=raw); self.assertIn(c, (400, 409))
        c, _ = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan(), "note": "x" * 5000}); self.assertIn(c, (400, 413))
        c, _ = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan(), "assignments": {f"L{i}": "CR13" for i in range(50)}})
        OBS["decision_route_50_assignment_status"] = c; self.assertIn(c, (400, 409, 413))   # finding: only preview caps assignments (20); the engine still rejects unknown tasks
        self.assertEqual(self.stable()[0], before[0])
        self.assertEqual(self.get()[0], 200)

    def test_mutation_cap_counts_refused_attempts(self):
        self.wage_cleared()
        with mock.patch.dict(os.environ, {"DEMO_MAX_MUTATIONS": str(server.META[self.pid]["mutations"] + 3)}):
            codes = [self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan(assign={"L02": "CR11"})})[0] for _ in range(5)]
        OBS["mutation_cap_codes_after_3_refused_attempts"] = codes
        self.assertEqual(codes[-1], 429)


if __name__ == "__main__":
    unittest.main()

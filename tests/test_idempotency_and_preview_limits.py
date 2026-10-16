"""Approval replay semantics (idempotency at the HTTP decision boundary) and bounded previews. Local single-process demo guarantees only: the
in-memory limiter and ledger are NOT shared/global guarantees (see docs/HTTP_ADAPTER_CONTRACT_v1_PROPOSED.md)."""
import json
import unittest
from unittest import mock

from api import server
from tests.http_harness import HttpBase, OWNER_A, OWNER_B, WHO, plan
from tests.test_ratebook_workflow import wage_args


class Idempotency(HttpBase):
    def setUp(self):
        super().setUp()
        self.to_wage_cleared()

    def decide(self, idem, body=None, expect=200, hdr=None):
        h = {} if hdr is None else hdr
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", body or {**WHO, **plan()}, idem=idem, headers_out=h)
        self.assertEqual(c, expect, out)
        return out, h

    def test_key_is_required_and_validated(self):
        for idem, want in ((False, "IDEMPOTENCY_KEY_REQUIRED"), ("short", "IDEMPOTENCY_KEY_REQUIRED"), ("bad key with spaces!", "IDEMPOTENCY_KEY_REQUIRED")):
            c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan()}, idem=idem)
            self.assertEqual((c, out["code"]), (400, want))
        self.assertIsNone(self.get()["pricing"]["crew_plan"])

    def test_same_key_and_identical_payload_returns_the_original_result_with_no_new_event_or_version(self):
        first, h1 = self.decide("key-crew-plan-0001")
        before, muts = self.frozen(), self.mutations()
        again, h2 = self.decide("key-crew-plan-0001")
        self.assertEqual(h2.get("idempotent-replay"), "true")
        self.assertNotIn("idempotent-replay", h1)
        self.assertEqual(again, first)                                                    # the original response, byte for byte
        self.assertEqual((self.frozen(), self.mutations()), (before, muts))               # no audit event, no version, no mutation count
        s = self.get()
        self.assertEqual(s["pricing"]["crew_plan"]["plan_version"], 1)
        self.assertEqual(len([a for a in s["audit"] if a["event"] == "crew_plan_approved"]), 1)

    def test_canonical_payload_ignores_key_order_but_not_content(self):
        body = {**WHO, **plan()}
        self.decide("key-canonical-001", body)
        reordered = json.loads(json.dumps(body, sort_keys=True)[::1])
        reordered = dict(reversed(list(reordered.items())))
        out, h = self.decide("key-canonical-001", reordered)
        self.assertEqual(h.get("idempotent-replay"), "true")
        changed = {**body, "note": "a different note"}
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", changed, idem="key-canonical-001")
        self.assertEqual((c, out["code"]), (409, "IDEMPOTENCY_KEY_REUSED"))

    def test_reusing_a_key_with_a_different_payload_or_route_is_rejected_and_changes_nothing(self):
        self.decide("key-reuse-000001")
        before, muts = self.frozen(), self.mutations()
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan(diff="hard")}, idem="key-reuse-000001")
        self.assertEqual((c, out["code"]), (409, "IDEMPOTENCY_KEY_REUSED"))
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/wage-determination", wage_args(), idem="key-reuse-000001")
        self.assertEqual((c, out["code"]), (409, "IDEMPOTENCY_KEY_REUSED"))
        self.assertEqual(self.frozen(), before)

    def test_an_intentional_new_decision_is_separately_identified_and_prior_history_is_preserved(self):
        self.decide("key-plan-version-a")
        out, _ = self.decide("key-plan-version-b", {**WHO, **plan(diff="hard")})
        s = self.get()
        self.assertEqual(s["pricing"]["crew_plan"]["plan_version"], 2)
        self.assertEqual([p["plan_version"] for p in s["pricing"]["plan_history"]], [1, 2])
        self.assertEqual(s["pricing"]["plan_history"][0]["retired_reason"], "superseded by plan version 2")
        evs = [a for a in s["audit"] if a["event"] == "crew_plan_approved"]
        self.assertEqual([e["plan_version"] for e in evs], [1, 2])                          # nothing rewritten, nothing reset
        led = {d["idempotency_key"]: d for d in s["adapter"]["decisions"] if d["route"] == "crew-plan"}
        self.assertEqual(set(led), {"key-plan-version-a", "key-plan-version-b"})
        self.assertNotEqual(led["key-plan-version-a"]["audit_event_id"], led["key-plan-version-b"]["audit_event_id"])
        self.assertEqual({d["actor_identity"] for d in led.values()}, {"SELF_DECLARED_DEMO_ACTOR_NOT_AUTHENTICATED"})
        self.assertEqual(s["adapter"]["actor_identity"], "SELF_DECLARED_DEMO_ACTOR_NOT_AUTHENTICATED")

    def test_a_new_key_cannot_re_approve_an_identical_plan_to_churn_the_version_or_digest(self):
        self.decide("key-first-approval")
        d1 = self.get()["proposal_digest"]
        before = self.frozen()
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan()}, idem="key-second-approval")
        self.assertEqual((c, out["code"]), (409, "DECISION_UNCHANGED"))
        self.assertEqual(self.frozen(), before)
        self.assertEqual(self.get()["proposal_digest"], d1)

    def test_an_old_digest_never_authorizes_a_changed_plan(self):
        d1 = self.decide("key-digest-plan-1")[0]["proposal_digest"]
        d2 = self.decide("key-digest-plan-2", {**WHO, **plan(pref="CR14")})[0]["proposal_digest"]
        self.assertNotEqual(d1, d2)
        sv = self.get()["scope_version"]
        rel = lambda d: self.call("POST", f"/projects/{self.pid}/release", {"approver": "Test Approver", "expected_scope_version": sv, "expected_proposal_digest": d})
        self.assertEqual(rel(d1)[0], 409)
        c, out = rel(d2)
        self.assertEqual(c, 200, out)
        c, _ = rel(d2)
        self.assertEqual(c, 409)                                                           # release replay refused
        self.assertEqual(self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan(diff="hard")})[0], 409)   # nothing after release

    def test_a_refused_attempt_does_not_burn_the_key(self):
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan(assign={"L02": "CR11"})}, idem="key-retry-000001")
        self.assertEqual(c, 409)
        plans = lambda: [d for d in self.get()["adapter"]["decisions"] if d["route"] == "crew-plan"]
        self.assertEqual(plans(), [])
        self.decide("key-retry-000001")                                                    # same key, corrected payload: allowed, it was never recorded
        self.assertEqual(len(plans()), 1)

    def test_ruleset_replay_and_reapproval_cannot_overwrite_the_recorded_approver(self):
        s = self.get()
        sha, approver = s["pricing"]["ruleset"]["sha256"], s["pricing"]["ruleset"]["approved_by"]
        self.assertEqual(approver, WHO["by"])
        before = self.frozen()
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/ruleset-approval", {"by": "Someone Else", "note": "overwrite attempt", "ruleset_sha256": sha}, idem="key-ruleset-other")
        self.assertEqual((c, out["code"]), (409, "RULESET_ALREADY_APPROVED"))
        self.assertEqual(self.frozen(), before)
        self.assertEqual(self.get()["pricing"]["ruleset"]["approved_by"], approver)
        # exact replay of the ORIGINAL approval key returns the original result without a new event
        ledger = self.get()["adapter"]["decisions"]
        orig = next(d for d in ledger if d["route"] == "ruleset-approval")
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/ruleset-approval", {**WHO, "ruleset_sha256": sha}, idem=orig["idempotency_key"])
        self.assertEqual(c, 200)
        self.assertEqual(self.frozen(), before)

    def test_wage_determination_replay_with_the_same_key_is_not_re_recorded(self):
        before = self.frozen()
        orig = next(d for d in self.get()["adapter"]["decisions"] if d["route"] == "wage-determination")
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/wage-determination", wage_args(), idem=orig["idempotency_key"])
        self.assertEqual(c, 200)
        self.assertEqual(self.frozen(), before)
        self.assertEqual(len([a for a in self.get()["audit"] if a["event"] == "wage_determination_recorded"]), 1)

    def test_keys_are_scoped_per_project_and_per_owner(self):
        self.decide("key-shared-name-1")
        c, o2 = self.call("POST", "/demo/projects", {}, owner=OWNER_B)
        pid2 = o2["project_id"]
        c, out = self.call("POST", f"/projects/{pid2}/decisions/ruleset-approval", {**WHO, "ruleset_sha256": o2["pricing"]["ruleset"]["sha256"]}, owner=OWNER_B, idem="key-shared-name-1")
        self.assertEqual(c, 200, out)                                                       # same key text, other project: independent
        self.assertEqual(self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan()}, owner=OWNER_B, idem="key-shared-name-1")[0], 404)

    def test_exact_replays_do_not_consume_the_demo_mutation_cap(self):
        self.decide("key-cap-replay-001")
        muts = self.mutations()
        for _ in range(5):
            self.decide("key-cap-replay-001")
        self.assertEqual(self.mutations(), muts)

    def test_ledger_survives_nothing_but_memory_and_is_labelled_so(self):
        text = open(server.__file__).read()
        self.assertIn("in memory", text)


class PreviewLimits(HttpBase):
    ENV = {"PREVIEW_MAX_PER_MINUTE": "5", "PREVIEW_MAX_PER_OWNER_PER_MINUTE": "8"}

    def setUp(self):
        super().setUp()
        self.to_wage_cleared()

    def prev(self, body=None, owner=OWNER_A, pid=None, h=None):
        return self.call("POST", f"/projects/{pid or self.pid}/crew-plan/preview", body or plan(), owner=owner, headers_out=h)

    def test_per_project_limit_returns_429_with_retry_guidance_and_a_consistent_body(self):
        codes = [self.prev()[0] for _ in range(5)]
        self.assertEqual(codes, [200] * 5)
        h = {}
        c, out = self.prev(h=h)
        self.assertEqual(c, 429)
        self.assertEqual(out["code"], "PREVIEW_RATE_LIMITED")
        self.assertGreaterEqual(int(h["retry-after"]), 1)
        self.assertEqual(int(h["retry-after"]), out["retry_after_seconds"])
        self.assertLessEqual(out["retry_after_seconds"], 61)
        self.assertIn("process-local", out["limit_scope"])
        self.assertIn("not a global guarantee", out["limit_scope"])

    def test_per_owner_limit_spans_projects_and_other_owners_are_unaffected(self):
        c, o2 = self.call("POST", "/demo/projects", {}, owner=OWNER_A)
        pid2 = o2["project_id"]
        for _ in range(5):
            self.assertEqual(self.prev()[0], 200)                                           # project 1: 5 of 5
        # project 2 preview needs the scope gate clear; limit accounting happens before the engine, so use the raw status
        statuses = [self.prev(pid=pid2)[0] for _ in range(6)]
        self.assertIn(429, statuses)                                                         # owner window (8) exhausted across both projects
        c, o3 = self.call("POST", "/demo/projects", {}, owner=OWNER_B)
        self.assertNotEqual(self.prev(pid=o3["project_id"], owner=OWNER_B)[0], 429)

    def test_window_expiry_is_computed_from_timestamps(self):
        server.PREVIEW_HITS.clear()
        t = 1000.0
        for i in range(5):
            self.assertIsNone(server._preview_throttle("o", "p", t + i))
        self.assertEqual(server._preview_throttle("o", "p", t + 5), 56)                       # oldest at t -> frees at t+60
        self.assertIsNone(server._preview_throttle("o", "p", t + 60.5))

    def test_preview_never_mutates_creates_no_audit_approval_or_digest_even_when_limited(self):
        before, muts = self.frozen(), self.mutations()
        for _ in range(9):
            self.prev(plan(pref="CR14"))
        self.assertEqual((self.frozen(), self.mutations()), (before, muts))
        s = self.get()
        self.assertIsNone(s["proposal_digest"])
        self.assertIsNone(s["pricing"]["crew_plan"])
        self.assertIsNone(s["estimate"])
        self.assertEqual([a["event"] for a in s["audit"] if "plan" in a["event"] or a["event"] == "released"], [])

    def test_oversized_bodies_and_too_many_assignments_are_bounded(self):
        c, out = self.prev({**plan(), "pad": "x" * 9000})
        self.assertEqual((c, out["code"]), (413, "PREVIEW_BODY_TOO_LARGE"))
        c, out = self.prev({**plan(), "assignments": {f"L{i:02d}": "CR13" for i in range(1, 40)}})
        self.assertEqual(c, 400)
        c, out = self.call("POST", f"/projects/{self.pid}/crew-plan/preview", raw=b"{")
        self.assertEqual(c, 400)

    def test_limiter_state_is_dropped_with_the_project(self):
        self.prev()
        self.assertTrue(any(k[0] == "p" and k[2] == self.pid for k in server.PREVIEW_HITS))
        self.assertEqual(self.call("DELETE", f"/demo/projects/{self.pid}")[0], 200)
        self.assertFalse(any(k[0] == "p" and k[2] == self.pid for k in server.PREVIEW_HITS))
        self.assertNotIn(self.pid, server.LEDGER)


if __name__ == "__main__":
    unittest.main()

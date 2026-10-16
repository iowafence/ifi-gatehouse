"""Pass 3: wage-determination replay policy and idempotency replay ORDERING relative to the mutation cap.
Replay semantics (documented in docs/HTTP_ADAPTER_CONTRACT_v1_PROPOSED.md): a stored replay is the HISTORICAL result of the original decision,
returned byte for byte with `Idempotent-Replay: true` and `X-Idempotency-Result: historical`; it is never current state or current authorization.
Release always checks the live digest."""
import copy
import json
import os
import threading
import unittest
from unittest import mock

from api import server
from tests.http_harness import HttpBase, OWNER_A, OWNER_B, WHO, plan
from tests.test_ratebook_workflow import wage_args, good_rows, row, OPR

WAGE_ROUTE = "decisions/wage-determination"


def mod(n, **kw):
    a = wage_args(**kw)
    a["determination"] = {**a["determination"], "modification": str(n)}
    return a


class WageReplay(HttpBase):
    def setUp(self):
        super().setUp()
        self.to_labor_gate()                                         # ruleset approved; wage not yet recorded

    def wage(self, body, idem, expect=200, **kw):
        h = {}
        c, out = self.call("POST", f"/projects/{self.pid}/{WAGE_ROUTE}", body, idem=idem, headers_out=h, **kw)
        self.assertEqual(c, expect, out)
        return out, h

    def events(self, name="wage_determination_recorded"):
        return [a for a in self.get()["audit"] if a["event"] == name]

    def wage_ledger(self):
        return [d for d in self.get()["adapter"]["decisions"] if d["route"] == "wage-determination"]

    # 1 ---------------------------------------------------------------------------------------------
    def test_1_same_key_exact_replay_returns_the_original_with_no_audit_ledger_or_counter_change(self):
        first, h1 = self.wage(wage_args(), "wage-key-original-1")
        before, muts = self.frozen(), self.mutations()
        again, h2 = self.wage(wage_args(), "wage-key-original-1")
        self.assertEqual(again, first)
        self.assertEqual((h2.get("idempotent-replay"), h2.get("x-idempotency-result")), ("true", "historical"))
        self.assertNotIn("idempotent-replay", h1)
        self.assertEqual((self.frozen(), self.mutations()), (before, muts))
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(len(self.wage_ledger()), 1)

    def test_1b_same_key_with_a_different_request_or_actor_is_rejected_and_changes_nothing(self):
        self.wage(wage_args(), "wage-key-original-2")
        before = self.frozen()
        for body in (wage_args(by="Another Reviewer"), wage_args(note="different note"), mod(1)):
            c, out = self.call("POST", f"/projects/{self.pid}/{WAGE_ROUTE}", body, idem="wage-key-original-2")
            self.assertEqual((c, out["code"]), (409, "IDEMPOTENCY_KEY_REUSED"))
        self.assertEqual(self.frozen(), before)

    # 2 ---------------------------------------------------------------------------------------------
    def test_2_different_key_same_modification_unchanged_is_not_recorded_or_reattributed(self):
        self.wage(wage_args(), "wage-key-a-0001")
        d1 = self.get()["proposal_digest"]
        before = self.frozen()
        for who in ({}, {"by": "Someone Else", "note": "re-attribution attempt"}):
            c, out = self.call("POST", f"/projects/{self.pid}/{WAGE_ROUTE}", wage_args(**who), idem=f"wage-key-b-{len(who)}000")
            self.assertEqual((c, out["code"]), (409, "DECISION_UNCHANGED"))
        self.assertEqual(self.frozen(), before)
        s = self.get()
        self.assertEqual(s["pricing"]["wage"]["decision"]["recorded_by"], wage_args()["by"])
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(s["proposal_digest"], d1)

    # 3 ---------------------------------------------------------------------------------------------
    def test_3_changed_content_at_the_same_modification_is_refused_once_cleared(self):
        self.wage(wage_args(), "wage-key-cleared-1")
        self.assertTrue(self.get()["pricing"]["wage"]["cleared"])
        before = self.frozen()
        changed = wage_args(employer_burden=dict(pct=0.30, source_ref="altered"))
        c, out = self.call("POST", f"/projects/{self.pid}/{WAGE_ROUTE}", changed, idem="wage-key-cleared-2")
        self.assertEqual((c, out["code"]), (409, "WAGE_MODIFICATION_NOT_HIGHER"))
        self.assertEqual(self.frozen(), before)

    def test_3b_a_higher_modification_is_a_new_audited_decision_and_prior_attribution_stays_recoverable(self):
        self.wage(wage_args(), "wage-key-mod0-001")
        self.post("decisions/crew-plan", {**WHO, **plan()})
        d_old = self.get()["proposal_digest"]
        new = mod(1, by="Second Reviewer", note="modification 1 per the decision document")
        self.wage(new, "wage-key-mod1-001")
        s = self.get()
        self.assertEqual(s["pricing"]["wage"]["decision"], {"decision_id": "FDB-DP001", "modification": "1", "recorded_by": "Second Reviewer"})
        evs = self.events()
        self.assertEqual([(e["actor"], e["modification"]) for e in evs], [("Lee Reviewer", "0"), ("Second Reviewer", "1")])    # prior actor preserved
        led = self.wage_ledger()
        self.assertEqual([(d["by"], d["idempotency_key"]) for d in led], [("Lee Reviewer", "wage-key-mod0-001"), ("Second Reviewer", "wage-key-mod1-001")])
        self.assertEqual(len({d["audit_event_id"] for d in led}), 2)
        sv = s["scope_version"]
        rel = lambda d: self.call("POST", f"/projects/{self.pid}/release", {"approver": "Test Approver", "expected_scope_version": sv, "expected_proposal_digest": d})[0]
        self.assertEqual(rel(d_old), 409)                                     # an intentional new wage decision invalidates the old digest
        if s["proposal_digest"]:
            self.assertNotEqual(s["proposal_digest"], d_old)

    def test_3c_lower_modification_different_decision_and_malformed_requests_leave_everything_unchanged(self):
        self.wage(mod(2), "wage-key-mod2-001")
        before, muts = self.frozen(), self.mutations()
        cases = [(mod(1), "wage-key-low-0001", None),                                                              # stale (engine)
                 (wage_args(determination=dict(decision_id="OTHER-DECISION", modification="5", date="2026-10-05", valid_through="2026-12-31", source_ref="x")), "wage-key-other-01", "WAGE_SUPERSESSION_REQUIRED"),
                 (mod(3, schedule=[{"classification": "Laborer", "base_rate": -1, "fringe_rate": 1}]), "wage-key-neg-0001", None),
                 (mod(3, rows="not-a-list"), "wage-key-bad-0001", None)]
        for body, key, code in cases:
            c, out = self.call("POST", f"/projects/{self.pid}/{WAGE_ROUTE}", body, idem=key)
            self.assertIn(c, (400, 409), out)
            if code:
                self.assertEqual(out["code"], code)
        a, b = json.loads(self.frozen()), json.loads(before)
        for k in ("audit", "pricing", "proposal_digest", "estimate"):
            self.assertEqual(a[k], b[k], k)
        self.assertEqual(a["adapter"]["decisions"], b["adapter"]["decisions"])
        self.assertEqual(self.mutations(), muts + len(cases))                  # refused attempts still count; replays do not (see the cap tests)

    def test_3d_an_uncleared_record_may_be_completed_but_not_resubmitted_unchanged(self):
        rows = good_rows()
        rows[3] = row("R4", OPR, status="proposed_for_conformance")
        self.wage(wage_args(rows=rows), "wage-key-draft-001")
        self.assertFalse(self.get()["pricing"]["wage"]["cleared"])
        c, out = self.call("POST", f"/projects/{self.pid}/{WAGE_ROUTE}", wage_args(rows=rows, note="again"), idem="wage-key-draft-002")
        self.assertEqual((c, out["code"]), (409, "DECISION_UNCHANGED"))
        self.wage(wage_args(), "wage-key-draft-003")                          # the completed record
        self.assertTrue(self.get()["pricing"]["wage"]["cleared"])
        self.assertEqual(len(self.events()), 2)                               # both versions remain in the append-only audit log
        self.assertEqual(len(self.wage_ledger()), 2)

    # 8 ---------------------------------------------------------------------------------------------
    def test_8_stale_digest_behavior_after_intentional_new_decisions_and_historical_replays(self):
        self.wage(wage_args(), "wage-key-hist-001")
        _, first = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan()}, idem="plan-key-hist-001")
        d1 = first["proposal_digest"]
        v1_body = first
        _, second = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan(pref="CR14")}, idem="plan-key-hist-002")
        d2 = second["proposal_digest"]
        self.assertNotEqual(d1, d2)
        h = {}
        c, replay = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan()}, idem="plan-key-hist-001", headers_out=h)
        self.assertEqual(c, 200)
        self.assertEqual(replay, v1_body)                                       # the HISTORICAL result, not the current state
        self.assertEqual(replay["pricing"]["crew_plan"]["plan_version"], 1)
        self.assertEqual(self.get()["pricing"]["crew_plan"]["plan_version"], 2)  # current state is different
        self.assertEqual(h["x-idempotency-result"], "historical")
        sv = self.get()["scope_version"]
        rel = lambda d: self.call("POST", f"/projects/{self.pid}/release", {"approver": "Test Approver", "expected_scope_version": sv, "expected_proposal_digest": d})
        self.assertEqual(rel(replay["proposal_digest"])[0], 409)                # a replayed old digest never authorizes release
        self.assertEqual(rel(d2)[0], 200)


class ReplayOrderingAtTheCap(HttpBase):
    CAP_SLACK = 2

    def setUp(self):
        super().setUp()
        self.to_wage_cleared()
        _, self.first = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan()}, idem="cap-key-original-1")
        self.cap = self.mutations() + self.CAP_SLACK
        self.env_cap = mock.patch.dict(os.environ, {"DEMO_MAX_MUTATIONS": str(self.cap)})
        self.env_cap.start()
        self.addCleanup(self.env_cap.stop)

    def fill_cap(self):
        n = 0
        while self.mutations() < self.cap:                                      # genuine new (refused) mutations consume the budget
            self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan(assign={"L02": "CR11"})})
            n += 1
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan(assign={"L02": "CR11"})})
        self.assertEqual((c, out["code"]), (429, "RATE_LIMITED"))               # confirmed: the cap is now reached
        return n

    def test_4_exact_replay_at_and_beyond_the_cap_returns_the_original_without_incrementing(self):
        self.fill_cap()
        before, muts = self.frozen(), self.mutations()
        self.assertEqual(muts, self.cap)
        for _ in range(5):                                                       # at the cap and well beyond it
            h = {}
            c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan()}, idem="cap-key-original-1", headers_out=h)
            self.assertEqual(c, 200)
            self.assertEqual(out, self.first)
            self.assertEqual((h["idempotent-replay"], h["x-idempotency-result"]), ("true", "historical"))
        self.assertEqual((self.frozen(), self.mutations()), (before, muts))

    def test_5_changed_payload_or_actor_replay_at_the_cap_does_not_bypass_it(self):
        self.fill_cap()
        before, muts = self.frozen(), self.mutations()
        for body in ({**WHO, **plan(diff="hard")}, {**WHO, "by": "Other Actor", **{k: v for k, v in plan().items()}}, {"by": WHO["by"], "note": "changed note", **plan()}):
            c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", body, idem="cap-key-original-1")
            self.assertEqual((c, out["code"]), (429, "RATE_LIMITED"))
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/ruleset-approval", {**WHO, "ruleset_sha256": "0" * 64}, idem="cap-key-original-1")   # other route, same key
        self.assertEqual((c, out["code"]), (429, "RATE_LIMITED"))
        self.assertEqual((self.frozen(), self.mutations()), (before, muts))
        self.assertEqual(self.get()["pricing"]["crew_plan"]["plan_version"], 1)

    def test_5b_a_genuinely_new_decision_at_the_cap_is_still_limited_and_below_the_cap_still_works(self):
        for i, d in enumerate(("hard", "easy")):                                  # below the cap: genuinely new decisions still work
            c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan(diff=d)}, idem=f"cap-key-new-000{i}")
            self.assertEqual(c, 200, out)
        self.assertEqual(self.mutations(), self.cap)
        before = self.frozen()
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan(diff="standard", assign={"L02": "CR14"})}, idem="cap-key-new-0009")
        self.assertEqual((c, out["code"]), (429, "RATE_LIMITED"))
        self.assertEqual(self.frozen(), before)

    def test_5c_a_replay_of_an_unknown_key_at_the_cap_is_not_served(self):
        self.fill_cap()
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan()}, idem="cap-key-never-used")
        self.assertEqual(c, 429)

    def test_6_cross_owner_and_cross_project_key_reuse(self):
        self.fill_cap()
        # another owner can neither replay nor probe this project's keys
        h = {}
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan()}, owner=OWNER_B, idem="cap-key-original-1", headers_out=h)
        self.assertEqual((c, out.get("error")), (404, "no such project"))
        self.assertNotIn("idempotent-replay", h)
        self.assertNotIn("proposal_digest", json.dumps(out))
        self.assertEqual(self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan()}, owner=None, idem="cap-key-original-1")[0], 404)
        # the same key text on the other owner's OWN project is independent (no replay, no conflict, own cap)
        c, o2 = self.call("POST", "/demo/projects", {}, owner=OWNER_B)
        pid2 = o2["project_id"]
        h = {}
        sha = o2["pricing"]["ruleset"]["sha256"]
        c, out = self.call("POST", f"/projects/{pid2}/decisions/ruleset-approval", {**WHO, "ruleset_sha256": sha}, owner=OWNER_B, idem="cap-key-original-1", headers_out=h)
        self.assertEqual(c, 200, out)
        self.assertNotIn("idempotent-replay", h)
        # same owner, second project: independent as well
        c, o3 = self.call("POST", "/demo/projects", {}, owner=OWNER_A)
        c, out = self.call("POST", f"/projects/{o3['project_id']}/decisions/ruleset-approval", {**WHO, "ruleset_sha256": o3["pricing"]["ruleset"]["sha256"]}, idem="cap-key-original-1", headers_out=h)
        self.assertEqual(c, 200, out)


class Concurrency(HttpBase):
    def setUp(self):
        super().setUp()
        self.to_wage_cleared()

    def burst(self, bodies, key, n):
        res, lock = [], threading.Lock()
        barrier = threading.Barrier(n)

        def go(i):
            h = {}
            barrier.wait()
            c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", bodies[i % len(bodies)], idem=key, headers_out=h)
            with lock:
                res.append((c, out, h))
        ts = [threading.Thread(target=go, args=(i,)) for i in range(n)]
        [t.start() for t in ts]
        [t.join(30) for t in ts]
        return res

    def test_7_concurrent_identical_retries_apply_exactly_once(self):
        muts = self.mutations()
        res = self.burst([{**WHO, **plan()}], "burst-key-0001", 10)
        self.assertEqual(len(res), 10)
        self.assertEqual({c for c, _, _ in res}, {200})
        originals = [r for r in res if "idempotent-replay" not in r[2]]
        self.assertEqual(len(originals), 1)                                       # exactly one execution
        self.assertTrue(all(out == originals[0][1] for _, out, _ in res))        # everyone gets the same (original) result
        s = self.get()
        self.assertEqual(s["pricing"]["crew_plan"]["plan_version"], 1)
        self.assertEqual(len([a for a in s["audit"] if a["event"] == "crew_plan_approved"]), 1)
        self.assertEqual(self.mutations(), muts + 1)

    def test_7b_concurrent_same_key_different_payloads_have_one_winner(self):
        res = self.burst([{**WHO, **plan()}, {**WHO, **plan(diff="hard")}], "burst-key-0002", 10)
        codes = [c for c, _, _ in res]
        self.assertEqual(codes.count(200) >= 1, True)
        self.assertTrue(set(codes) <= {200, 409})
        s = self.get()
        self.assertEqual(s["pricing"]["crew_plan"]["plan_version"], 1)
        self.assertEqual(len([a for a in s["audit"] if a["event"] == "crew_plan_approved"]), 1)
        self.assertEqual(len([d for d in s["adapter"]["decisions"] if d["idempotency_key"] == "burst-key-0002"]), 1)


if __name__ == "__main__":
    unittest.main()

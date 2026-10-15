"""footing-scope.v1 through the real HTTP adapter (in-process server on 127.0.0.1, fictional DP-001 data): the footing schedule is exposed additively, the Scope/Labor/Release
gates, fleet-only crew rule, Idempotency-Key and stale-digest protections still hold, and a footing revision cannot be released against an old digest."""
import json
import unittest
from unittest import mock

from api import server
from engine import integration
from tests import footing_helpers as H
from tests.http_harness import HttpBase, WHO, plan, OWNER_A
from tests.test_ratebook_workflow import wage_args

FOOT = "EX-MISSING_VALUE-/footing_scope/classes/GATE_G3/"
G3W = "EX-MISSING_VALUE-/gates/2/clear_width_ft"


class FootingHttp(HttpBase):
    def setUp(self):
        self.scope = mock.patch.object(integration, "SCOPE_PATH", H.FIX / "dp001_footing_scope.json")
        self.scope.start()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self.scope.stop()

    def to_scope_cleared(self, footing=True):
        sel = next(e for e in self.get()["exceptions"] if e["code"] == "BID_SELECTION_REQUIRED")
        self.post("scope/resolve", {"exception_id": sel["exception_id"], "option_id": "base", **WHO})
        for _ in range(60):
            inf = [e for e in self.get()["exceptions"] if e["code"] == "INFERRED_FACT_UNAPPROVED"]
            if not inf:
                break
            self.post("scope/resolve", {"exception_id": inf[0]["exception_id"], "option_id": "approve_inferred", **WHO})
        self.post("scope/resolve", {"exception_id": G3W, "value": 12.0, "by": "Pat Estimator", "note": "WHAT-IF ONLY: G3 opening assumed"})
        if footing:
            for k, v in (("diameter_in", 16.0), ("depth_in", 48.0), ("post_od_in", 2.875)):
                self.post("scope/resolve", {"exception_id": FOOT + k, "value": v, "by": "Pat Estimator", "note": "WHAT-IF ONLY: G3 post/footing assumed; RFI open"})
        for _ in range(60):
            inf = [e for e in self.get()["exceptions"] if e["code"] == "INFERRED_FACT_UNAPPROVED"]
            if not inf:
                break
            self.post("scope/resolve", {"exception_id": inf[0]["exception_id"], "option_id": "approve_inferred", **WHO})

    def test_footing_schedule_is_exposed_additively_and_unpriced_while_g3_is_open(self):
        s = self.get()
        f = s["pricing"]["footing"]
        self.assertEqual(set(f), {"BASE", "ALT-A1"})
        self.assertEqual(f["BASE"]["posture"]["release_class"], "NOT_PRICEABLE_PARTIAL_UNRECONCILED")
        self.assertFalse(f["BASE"]["partial_cost"]["is_estimate"])
        self.assertIsNone(s["estimate"])
        self.assertNotIn("posts", f["BASE"])                       # the per-post list stays server-side
        self.assertEqual(f["BASE"]["totals"]["posts"], None)

    def test_g3_footing_facts_are_asked_of_a_named_human_and_a_bad_value_changes_nothing(self):
        before = self.frozen()
        c, out = self.call("POST", f"/projects/{self.pid}/scope/resolve", {"exception_id": FOOT + "diameter_in", "value": -5, **WHO})
        self.assertEqual(c, 409, out)
        self.assertEqual(self.frozen(), before)

    def test_full_flow_to_a_demonstration_release_that_says_it_is_not_bid_ready(self):
        self.to_scope_cleared()
        s = self.get()
        self.assertEqual(s["pricing"]["footing"]["BASE"]["totals"]["posts"], 79)
        sha = next(e["required_decision"]["sha256"] for e in s["exceptions"] if e["code"] == "QUANTITY_RULESET_UNAPPROVED")
        self.post("decisions/ruleset-approval", {**WHO, "ruleset_sha256": sha})
        self.post("decisions/wage-determination", wage_args())
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan(pref="CR1", assign={"L02": "CR13"})})
        self.assertIn(c, (400, 409, 422), out)                       # fleet-only rule still enforced
        self.post("decisions/crew-plan", {**WHO, **plan()})
        s = self.get()
        self.assertEqual(s["status"], "ready_for_final_review")
        est = s["estimate"]["scenarios"]["BASE"]
        self.assertEqual({l["item_id"]: l["quantity"] for l in est["materials"]["lines"] if l["item_id"] in ("M01", "M02", "M03", "M04")},
                         {"M01": 12, "M02": 43, "M03": 6, "M04": 18})
        # stale digest refused; current digest releases with the not-bid-ready qualification in the response
        c, out = self.call("POST", f"/projects/{self.pid}/release", {"approver": "Pat Estimator", "expected_scope_version": s["scope_version"], "expected_proposal_digest": "0" * 64, "note": "x"})
        self.assertEqual(c, 409, out)
        c, out = self.call("POST", f"/projects/{self.pid}/release", {"approver": "Pat Estimator", "expected_scope_version": s["scope_version"],
                                                                      "expected_proposal_digest": s["proposal_digest"], "note": "demonstration release"})
        self.assertEqual(c, 200, out)
        self.assertTrue([q for q in out["qualifications"] if q["type"] == "footing_scope_not_bid_ready"])
        self.assertEqual(self.get()["pricing"]["footing"]["BASE"]["posture"]["bid_ready"], False)

    def release_ready_project(self):
        self.to_scope_cleared()
        s = self.get()
        sha = next(e["required_decision"]["sha256"] for e in s["exceptions"] if e["code"] == "QUANTITY_RULESET_UNAPPROVED")
        self.post("decisions/ruleset-approval", {**WHO, "ruleset_sha256": sha})
        self.post("decisions/wage-determination", wage_args())
        self.post("decisions/crew-plan", {**WHO, **plan()})
        return self.get()

    def test_release_response_states_readiness_from_server_state_not_from_the_request(self):
        s = self.release_ready_project()
        body = {"approver": "Pat Estimator", "expected_scope_version": s["scope_version"], "expected_proposal_digest": s["proposal_digest"], "note": "demonstration release",
                "bid_ready": True, "release_class": "BID_READY", "artifact_kind": "SUBMIT_READY_BID"}      # client-supplied claims must be ignored
        c, out = self.call("POST", f"/projects/{self.pid}/release", body)
        self.assertEqual(c, 200, out)
        self.assertIs(out["bid_ready"], False)
        self.assertEqual(out["release_class"], "QUALIFIED_DEMONSTRATION_ONLY_NOT_BID_READY")
        self.assertEqual(out["artifact_kind"], "QUALIFIED_FICTIONAL_DEMONSTRATION")
        self.assertEqual(out["footing_release_class"], {"BASE": "QUALIFIED_DEMONSTRATION_ONLY_NOT_BID_READY", "ALT-A1": "QUALIFIED_DEMONSTRATION_ONLY_NOT_BID_READY"})
        note = [q for q in out["qualifications"] if q["type"] == "footing_scope_not_bid_ready"]
        self.assertTrue(note and "demonstration result, not a bid-ready price" in note[0]["note"])          # human-readable text preserved
        self.assertEqual(out["proposal_digest"], s["proposal_digest"])
        after = self.get()
        self.assertEqual(after["status"], "released")
        self.assertEqual(after["pricing"]["footing"]["BASE"]["posture"]["bid_ready"], out["bid_ready"])      # consistent with the stored evidence
        self.assertEqual(after["pricing"]["footing"]["BASE"]["posture"]["release_class"], out["footing_release_class"]["BASE"])
        self.assertEqual(after["proposal_digest"], out["proposal_digest"])

    def test_release_replay_and_stale_guards_are_intact(self):
        s = self.release_ready_project()
        good = {"approver": "Pat Estimator", "expected_scope_version": s["scope_version"], "expected_proposal_digest": s["proposal_digest"], "note": "x"}
        c, _ = self.call("POST", f"/projects/{self.pid}/release", {**good, "expected_proposal_digest": "0" * 64})
        self.assertEqual(c, 409)
        self.assertEqual(self.get()["status"], "ready_for_final_review")
        c, first = self.call("POST", f"/projects/{self.pid}/release", good)
        self.assertEqual(c, 200)
        frozen = self.frozen()
        c, again = self.call("POST", f"/projects/{self.pid}/release", good)            # release has no replay route in Pass 6: a second release is refused and changes nothing
        self.assertEqual(c, 409, again)
        self.assertNotIn("bid_ready", again)
        self.assertEqual(self.frozen(), frozen)

    def test_decision_replay_still_returns_the_identical_historical_bytes(self):
        self.to_scope_cleared()
        sha = next(e["required_decision"]["sha256"] for e in self.get()["exceptions"] if e["code"] == "QUANTITY_RULESET_UNAPPROVED")
        raw1, raw2 = [], []
        self.call("POST", f"/projects/{self.pid}/decisions/ruleset-approval", {**WHO, "ruleset_sha256": sha}, idem="idem-rel-1", raw_out=raw1)
        self.call("POST", f"/projects/{self.pid}/decisions/ruleset-approval", {**WHO, "ruleset_sha256": sha}, idem="idem-rel-1", raw_out=raw2)
        self.assertEqual(raw1, raw2)

    def test_legacy_release_response_is_unchanged(self):
        self.scope.stop()
        with mock.patch.object(integration, "SCOPE_PATH", H.FIX / "dp001_legacy_scope.json"):
            c, out = self.call("POST", "/demo/projects", {})
            pid = out["project_id"]
            def post(suffix, body):
                cc, o = self.call("POST", f"/projects/{pid}/{suffix}", body)
                self.assertEqual(cc, 200, o)
                return o
            def get():
                return self.call("GET", f"/projects/{pid}")[1]
            post("scope/resolve", {"exception_id": next(e["exception_id"] for e in get()["exceptions"] if e["code"] == "BID_SELECTION_REQUIRED"), "option_id": "base", **WHO})
            for _ in range(60):
                inf = [e for e in get()["exceptions"] if e["code"] == "INFERRED_FACT_UNAPPROVED"]
                if not inf:
                    break
                post("scope/resolve", {"exception_id": inf[0]["exception_id"], "option_id": "approve_inferred", **WHO})
            post("scope/resolve", {"exception_id": G3W, "value": 12.0, **WHO})
            sha = next(e["required_decision"]["sha256"] for e in get()["exceptions"] if e["code"] == "QUANTITY_RULESET_UNAPPROVED")
            post("decisions/ruleset-approval", {**WHO, "ruleset_sha256": sha})
            post("decisions/wage-determination", wage_args())
            post("decisions/crew-plan", {**WHO, **plan()})
            s = get()
            c, out = self.call("POST", f"/projects/{pid}/release", {"approver": "Pat Estimator", "expected_scope_version": s["scope_version"], "expected_proposal_digest": s["proposal_digest"], "note": "x"})
            self.assertEqual(c, 200, out)
            self.assertEqual(sorted(out), ["approved_by", "audit_id", "proposal_digest", "qualifications", "released_at", "scope_version", "status"])
            self.assertFalse([q for q in out["qualifications"] if q["type"] == "footing_scope_not_bid_ready"])
        self.scope.start()

    def test_idempotent_decision_replay_does_not_change_the_footing_schedule(self):
        self.to_scope_cleared()
        s = self.get()
        sha = next(e["required_decision"]["sha256"] for e in s["exceptions"] if e["code"] == "QUANTITY_RULESET_UNAPPROVED")
        self.post("decisions/ruleset-approval", {**WHO, "ruleset_sha256": sha}, idem="idem-ruleset-1")
        a = self.frozen()
        self.post("decisions/ruleset-approval", {**WHO, "ruleset_sha256": sha}, idem="idem-ruleset-1")
        self.assertEqual(json.loads(self.frozen())["pricing"]["footing"], json.loads(a)["pricing"]["footing"])

    def test_decision_without_idempotency_key_is_refused(self):
        self.to_scope_cleared()
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/ruleset-approval", {**WHO, "ruleset_sha256": "0" * 64}, idem=False)
        self.assertGreaterEqual(c, 400)


if __name__ == "__main__":
    unittest.main()

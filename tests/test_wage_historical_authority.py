"""Pass 4: a wage determination that was EVER cleared (or ever authorized pricing) can never be corrected at the same statutory modification, even if it is
uncleared NOW. Authority is the server-side, append-only, monotonic wage history (integration.wage_history_*), never a client flag, never current status
alone, and never the absence of history (missing/ambiguous history fails closed).

Rejected-attempt quota policy (unchanged, documented, asserted below): a refused or malformed decision attempt that is not an exact replay COUNTS toward the
demo mutation cap; an exact replay never does.

Time/scope changes are SIMULATED by editing the server-side project state directly (policy as_of, scope_version): there is no HTTP route that changes them."""
import json
import threading
import unittest

from api import server
from engine import workflow as wf
from tests.http_harness import HttpBase, OWNER_A, WHO, plan
from tests.test_ratebook_workflow import wage_args, good_rows, row, OPR

W = "decisions/wage-determination"


def mod(n, **kw):
    a = wage_args(**kw)
    a["determination"] = {**a["determination"], "modification": str(n)}
    return a


def uncleared_rows():
    r = good_rows()
    r[3] = row("R4", OPR, status="proposed_for_conformance")
    return r


class Base(HttpBase):
    def setUp(self):
        super().setUp()
        self.to_labor_gate()

    def wage(self, body, idem, expect=200, **kw):
        c, out = self.call("POST", f"/projects/{self.pid}/{W}", body, idem=idem, **kw)
        self.assertEqual(c, expect, out)
        return out

    def refused(self, body, code, idem, status=409):
        before, muts = self.frozen(), self.mutations()
        c, out = self.call("POST", f"/projects/{self.pid}/{W}", body, idem=idem)
        self.assertEqual((c, out.get("code")), (status, code), out)
        self.assertEqual(self.frozen(), before)                                  # wage record, audit, ledger, history, plan version, digest: unchanged
        self.assertEqual(self.mutations(), muts + 1)                             # documented policy: a refused attempt counts toward the cap
        return out

    def hist(self):
        return self.get()["adapter"]["wage_history"]

    def advance(self):
        """Any successful engine call re-evaluates the wage blockers; used after simulating a relevant change."""
        self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan(diff="hard" if self.get()["pricing"]["crew_plan"] is None or
                  self.get()["pricing"]["crew_plan"]["difficulty"]["default"] != "hard" else "easy")})

    def expire(self):
        server.PROJECTS[self.pid]["policy"]["as_of"] = "2027-01-15"            # after valid_through 2026-12-31
        self.advance()

    def void_by_scope_change(self):
        server.PROJECTS[self.pid]["scope"]["scope_version"] += 1                # engine voids a wage record whose scope version is stale
        self.advance()


class Scenarios(Base):
    def test_A_initially_incomplete_never_cleared_correction_is_accepted_with_append_only_attribution(self):
        self.wage(wage_args(rows=uncleared_rows()), "wage-A-draft-0001")
        self.assertFalse(self.get()["pricing"]["wage"]["cleared"])
        self.wage(wage_args(by="Corrector", note="conformance approved", ), "wage-A-fixed-0001")
        s = self.get()
        self.assertTrue(s["pricing"]["wage"]["cleared"])
        evs = [(a["actor"], a["modification"]) for a in s["audit"] if a["event"] == "wage_determination_recorded"]
        self.assertEqual(evs, [("Lee Reviewer", "0"), ("Corrector", "0")])        # both versions and both actors remain in the audit log
        h = s["adapter"]["wage_history"]
        self.assertEqual([(r["by"], r["ever_cleared"]) for r in h["records"]], [("Lee Reviewer", False), ("Corrector", True)])
        self.assertTrue(h["history_complete"])

    def test_B_previously_cleared_and_currently_cleared_same_modification_change_is_refused(self):
        self.wage(wage_args(), "wage-B-orig-0001")
        self.refused(wage_args(employer_burden=dict(pct=0.30, source_ref="altered")), "WAGE_MODIFICATION_NOT_HIGHER", "wage-B-chg-0001")
        self.assertTrue(self.hist()["records"][0]["ever_cleared"])

    def test_C_cleared_then_made_uncleared_by_expiry_is_still_not_correctable_at_the_same_modification(self):
        self.wage(wage_args(), "wage-C1-orig-001")
        self.expire()
        s = self.get()
        self.assertTrue(s["pricing"]["wage"]["recorded"] and not s["pricing"]["wage"]["cleared"])      # now uncleared
        self.assertTrue(s["adapter"]["wage_history"]["records"][0]["ever_cleared"])                    # ... but history is irreversible
        self.refused(wage_args(employer_burden=dict(pct=0.31, source_ref="late change")), "WAGE_HISTORICALLY_CLEARED", "wage-C1-chg-0001")

    def test_C2_cleared_then_voided_by_a_scope_change_survives_invalidation(self):
        self.wage(wage_args(), "wage-C2-orig-001")
        self.void_by_scope_change()
        s = self.get()
        self.assertFalse(s["pricing"]["wage"]["recorded"])                                              # the engine voided the record
        h = s["adapter"]["wage_history"]
        self.assertEqual((len(h["records"]), h["records"][0]["ever_cleared"], h["history_complete"]), (1, True, True))
        self.refused(wage_args(rows=uncleared_rows()), "WAGE_HISTORICALLY_CLEARED", "wage-C2-chg-0001")  # changed content at the same modification: refused
        self.wage(wage_args(), "wage-C2-same-001")                                                       # identical content re-verification is allowed
        self.assertEqual(len(self.get()["adapter"]["wage_history"]["records"]), 2)
        self.assertTrue(all(r["ever_cleared"] for r in self.get()["adapter"]["wage_history"]["records"][:1]))

    def test_D_used_to_authorize_pricing_then_clearance_invalidated_is_still_not_correctable(self):
        self.wage(wage_args(), "wage-D-orig-0001")
        self.post("decisions/crew-plan", {**WHO, **plan()})
        self.assertIsNotNone(self.get()["estimate"])
        self.assertTrue(self.hist()["records"][0]["ever_authorized_pricing"])
        self.expire()
        s = self.get()
        self.assertIsNone(s["estimate"])                                                                 # price clearance invalidated
        self.assertFalse(s["pricing"]["wage"]["cleared"])
        h = s["adapter"]["wage_history"]["records"][0]
        self.assertEqual((h["ever_cleared"], h["ever_authorized_pricing"]), (True, True))
        self.refused(wage_args(employer_burden=dict(pct=0.29, source_ref="x")), "WAGE_HISTORICALLY_CLEARED", "wage-D-chg-0001")

    def test_E_history_unknown_or_unavailable_fails_closed(self):
        self.wage(wage_args(rows=uncleared_rows()), "wage-E-draft-0001")                                 # genuinely never cleared: would normally be correctable
        saved = server.WAGE_HISTORY[self.pid]
        # (1) history missing
        del server.WAGE_HISTORY[self.pid]
        c, out = self.call("POST", f"/projects/{self.pid}/{W}", wage_args(), idem="wage-E-fix-00001")
        self.assertEqual((c, out["code"]), (409, "WAGE_HISTORY_UNAVAILABLE"))
        # (2) history flagged incomplete
        server.WAGE_HISTORY[self.pid] = saved
        saved["complete"] = False
        c, out = self.call("POST", f"/projects/{self.pid}/{W}", wage_args(), idem="wage-E-fix-00002")
        self.assertEqual((c, out["code"]), (409, "WAGE_HISTORY_UNAVAILABLE"))
        # (3) a strictly higher modification does not need the history
        self.wage(mod(1), "wage-E-higher-001")
        self.assertEqual(self.get()["pricing"]["wage"]["decision"]["modification"], "1")

    def test_E2_an_engine_record_that_does_not_match_the_history_makes_it_permanently_incomplete(self):
        self.wage(wage_args(rows=uncleared_rows()), "wage-E2-draft-001")
        server.PROJECTS[self.pid]["wage_determination"]["recorded_by"] = "Out Of Band"                  # simulated out-of-band engine change
        self.get()                                                                                       # any request observes it
        self.assertFalse(server.WAGE_HISTORY[self.pid]["complete"])
        server.PROJECTS[self.pid]["wage_determination"]["recorded_by"] = "Lee Reviewer"                  # restoring it does NOT restore trust (monotonic)
        self.get()
        self.assertFalse(server.WAGE_HISTORY[self.pid]["complete"])
        c, out = self.call("POST", f"/projects/{self.pid}/{W}", wage_args(), idem="wage-E2-fix-0001")
        self.assertEqual((c, out["code"]), (409, "WAGE_HISTORY_UNAVAILABLE"))

    def test_F_higher_modification_is_a_new_decision_and_prior_history_is_retained(self):
        self.wage(wage_args(), "wage-F-mod0-00001")
        self.post("decisions/crew-plan", {**WHO, **plan()})
        self.wage(mod(1, by="Second Reviewer", note="mod 1"), "wage-F-mod1-00001")
        s = self.get()
        self.assertEqual(s["pricing"]["wage"]["decision"], {"decision_id": "FDB-DP001", "modification": "1", "recorded_by": "Second Reviewer"})
        recs = s["adapter"]["wage_history"]["records"]
        self.assertEqual([(r["modification"], r["by"], r["ever_cleared"], r["ever_authorized_pricing"]) for r in recs], [("0", "Lee Reviewer", True, True), ("1", "Second Reviewer", True, True)])   # mod 1 also priced the retained plan, so it too is irreversibly authorized
        self.assertEqual([(a["actor"], a["modification"]) for a in s["audit"] if a["event"] == "wage_determination_recorded"], [("Lee Reviewer", "0"), ("Second Reviewer", "1")])
        self.refused(mod(0, by="Back Door"), "WAGE_MODIFICATION_STALE", "wage-F-back-00001")              # statutory modifications do not go backwards

    def test_G_identical_key_replay_returns_the_original_historical_result_without_mutation(self):
        orig = self.wage(wage_args(), "wage-G-orig-00001")
        before, muts = self.frozen(), self.mutations()
        h = {}
        c, out = self.call("POST", f"/projects/{self.pid}/{W}", wage_args(), idem="wage-G-orig-00001", headers_out=h)
        self.assertEqual((c, out), (200, orig))
        self.assertEqual((h["idempotent-replay"], h["x-idempotency-result"]), ("true", "historical"))
        self.assertEqual((self.frozen(), self.mutations()), (before, muts))

    def test_H_new_key_unchanged_decision_adds_no_audit_event_and_no_attribution_change(self):
        self.wage(wage_args(), "wage-H-orig-00001")
        self.expire()                                                                                    # even when the record is uncleared now
        before = self.frozen()
        for who in ({}, {"by": "Thief", "note": "re-attribute"}):
            self.refused(wage_args(**who), "DECISION_UNCHANGED", f"wage-H-new-{len(who):05d}")
        self.assertEqual(self.get()["pricing"]["wage"]["decision"]["recorded_by"], "Lee Reviewer")
        self.assertEqual(len([a for a in self.get()["audit"] if a["event"] == "wage_determination_recorded"]), 1)

    def test_I_rejected_corrections_change_nothing_except_the_documented_quota_counter(self):
        self.wage(wage_args(), "wage-I-orig-00001")
        self.post("decisions/crew-plan", {**WHO, **plan()})
        before = json.loads(self.frozen())
        bads = [(wage_args(employer_burden=dict(pct=0.33, source_ref="x")), "WAGE_MODIFICATION_NOT_HIGHER"),
                (wage_args(determination=dict(decision_id="OTHER", modification="9", date="2026-10-05", valid_through="2026-12-31", source_ref="x")), "WAGE_SUPERSESSION_REQUIRED")]
        muts = self.mutations()
        for i, (b, code) in enumerate(bads):
            c, out = self.call("POST", f"/projects/{self.pid}/{W}", b, idem=f"wage-I-bad-{i:05d}")
            self.assertEqual((c, out["code"]), (409, code))
        after = json.loads(self.frozen())
        for k in ("audit", "pricing", "estimate", "proposal_digest", "labor_review"):
            self.assertEqual(after[k], before[k], k)
        self.assertEqual(after["adapter"], before["adapter"])
        self.assertEqual(self.mutations(), muts + 2)                                                     # documented: refused attempts consume quota
        muts = self.mutations()
        for _ in range(3):                                                                               # ... while exact replays never do
            self.call("POST", f"/projects/{self.pid}/{W}", wage_args(), idem="wage-I-orig-00001")
        self.assertEqual(self.mutations(), muts)

    def test_client_supplied_history_flags_are_never_trusted(self):
        self.wage(wage_args(), "wage-X-orig-00001")
        self.expire()
        c, out = self.call("POST", f"/projects/{self.pid}/{W}", {**wage_args(rows=uncleared_rows()), "ever_cleared": False}, idem="wage-X-flag-00001")
        self.assertEqual((c, out["code"]), (400, "BAD_REQUEST"))                                         # unknown top-level field
        nested = wage_args(rows=uncleared_rows())
        nested["determination"] = {**nested["determination"], "ever_cleared": False, "never_cleared": True}
        c, out = self.call("POST", f"/projects/{self.pid}/{W}", nested, idem="wage-X-flag-00002")
        self.assertEqual((c, out["code"]), (409, "WAGE_HISTORICALLY_CLEARED"))                           # a flag inside the document is just ignored text

    def test_K_stale_release_digest_remains_invalid_after_a_new_decision(self):
        self.wage(wage_args(), "wage-K-mod0-00001")
        d1 = self.post("decisions/crew-plan", {**WHO, **plan()})["proposal_digest"]
        self.wage(mod(1), "wage-K-mod1-00001")
        s = self.get()
        d2 = s["proposal_digest"]
        sv = s["scope_version"]
        rel = lambda d: self.call("POST", f"/projects/{self.pid}/release", {"approver": "Test Approver", "expected_scope_version": sv, "expected_proposal_digest": d})[0]
        self.assertEqual(rel(d1), 409)
        if d2:
            self.assertNotEqual(d1, d2)
            self.assertEqual(rel(d2), 200)


class Concurrency(Base):
    def test_J_ten_concurrent_identical_wage_retries_execute_once_with_identical_bytes(self):
        res, lock, barrier = [], threading.Lock(), threading.Barrier(10)

        def go():
            raw, h = [], {}
            barrier.wait()
            c, out = self.call("POST", f"/projects/{self.pid}/{W}", wage_args(), idem="wage-J-burst-0001", headers_out=h, raw_out=raw)
            with lock:
                res.append((c, h, raw[0] if raw else b""))
        ts = [threading.Thread(target=go) for _ in range(10)]
        [t.start() for t in ts]
        [t.join(30) for t in ts]
        self.assertEqual(len(res), 10)
        self.assertEqual({c for c, _, _ in res}, {200})
        self.assertEqual(len([1 for _, h, _ in res if "idempotent-replay" not in h]), 1)                 # one authoritative execution
        self.assertEqual(len({raw for _, _, raw in res}), 1)                                             # every response body is byte-identical
        s = self.get()
        self.assertEqual(len([a for a in s["audit"] if a["event"] == "wage_determination_recorded"]), 1)
        self.assertEqual(len(s["adapter"]["wage_history"]["records"]), 1)

    def test_J2_concurrent_changed_corrections_of_a_cleared_record_all_refuse(self):
        self.wage(wage_args(), "wage-J2-orig-0001")
        before = self.frozen()
        codes, lock, barrier = [], threading.Lock(), threading.Barrier(8)

        def go(i):
            barrier.wait()
            c, out = self.call("POST", f"/projects/{self.pid}/{W}", wage_args(employer_burden=dict(pct=0.30 + i / 100, source_ref="x")), idem=f"wage-J2-chg-{i:05d}")
            with lock:
                codes.append((c, out.get("code")))
        ts = [threading.Thread(target=go, args=(i,)) for i in range(8)]
        [t.start() for t in ts]
        [t.join(30) for t in ts]
        self.assertEqual(set(codes), {(409, "WAGE_MODIFICATION_NOT_HIGHER")})
        a, b = json.loads(self.frozen()), json.loads(before)
        for k in ("audit", "pricing", "adapter"):
            self.assertEqual(a[k], b[k], k)


class RawByteIdentity(HttpBase):
    """Parsed-JSON equality is NOT byte identity. These compare the exact bytes received."""
    def setUp(self):
        super().setUp()
        self.to_wage_cleared()

    def test_a_replay_is_byte_identical_to_the_original_response_and_stays_so_after_newer_decisions(self):
        raw1, rawr, rawr2 = [], [], []
        c, o1 = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan()}, idem="raw-bytes-key-01", raw_out=raw1)
        self.assertEqual(c, 200)
        self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan(diff="hard")}, idem="raw-bytes-key-02")   # a newer decision changes the live state
        c, _ = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan()}, idem="raw-bytes-key-01", raw_out=rawr)
        c, _ = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan()}, idem="raw-bytes-key-01", raw_out=rawr2)
        self.assertEqual(rawr[0], raw1[0])                                                                 # BYTE-identical, not merely equal after parsing
        self.assertEqual(rawr2[0], raw1[0])
        live = []
        self.call("GET", f"/projects/{self.pid}", raw_out=live)
        self.assertNotEqual(live[0], raw1[0])                                                              # and it is not the live state


if __name__ == "__main__":
    unittest.main()

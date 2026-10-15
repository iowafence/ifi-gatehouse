"""Pass 5: wage CONTENT integrity. A matching decision id, statutory modification and actor are NOT enough: the engine's live wage record must have exactly the
canonical content committed in the project's append-only history (spec `wage-content-identity-v1`, engine/integration.py). An unexplained mismatch, or a
missing/malformed committed identity, permanently marks that project's wage history untrusted for same-or-lower-modification edits (fail closed).
Tampering with the live record is SIMULATED by editing in-process server state; no HTTP route can do it."""
import copy
import json
import unittest

from api import server
from engine import integration
from tests.http_harness import HttpBase, WHO, plan
from tests.test_ratebook_workflow import wage_args, good_rows, row, OPR

W = "decisions/wage-determination"


def uncleared():
    r = good_rows()
    r[3] = row("R4", OPR, status="proposed_for_conformance")
    return wage_args(rows=r)


def mod(n, **kw):
    a = wage_args(**kw)
    a["determination"] = {**a["determination"], "modification": str(n)}
    return a


class Base(HttpBase):
    def setUp(self):
        super().setUp()
        self.to_labor_gate()

    def wage(self, body, idem, expect=200, **kw):
        c, out = self.call("POST", f"/projects/{self.pid}/{W}", body, idem=idem, **kw)
        self.assertEqual(c, expect, out)
        return out

    def live(self):
        return server.PROJECTS[self.pid]["wage_determination"]

    def hist(self):
        return self.get()["adapter"]["wage_history"]

    def refused(self, body, code, idem, status=409):
        before, muts = self.frozen(), self.mutations()
        c, out = self.call("POST", f"/projects/{self.pid}/{W}", body, idem=idem)
        self.assertEqual((c, out.get("code")), (status, code), out)
        self.assertEqual(self.mutations(), muts + 1)                          # documented quota policy: a refused attempt counts toward the cap
        return before, out


class IdentitySpec(unittest.TestCase):
    """Specification tests for wage-content-identity-v1 (no HTTP)."""
    def ident(self, **over):
        a = wage_args()
        a.update(over)
        return integration.wage_identity_from_request(a)

    def test_stable_hex_and_deterministic(self):
        i = self.ident()
        self.assertRegex(i, r"^[0-9a-f]{64}$")
        self.assertEqual(i, self.ident())
        self.assertEqual(i, integration.wage_identity_from_request(copy.deepcopy(wage_args())))

    def test_included_fields_each_change_the_identity(self):
        base = self.ident()
        a = wage_args()
        muts = {
            "employer_burden.pct": lambda x: x["employer_burden"].update(pct=0.21),
            "employer_burden.source_ref": lambda x: x["employer_burden"].update(source_ref="other"),
            "employer_burden.extra_key": lambda x: x["employer_burden"].update(extra=1),
            "production_rates_approved": lambda x: x.update(production_rates_approved=False),
            "certified_payroll_admin.unit_cost": lambda x: x["certified_payroll_admin"].update(unit_cost=86.0),
            "certified_payroll_admin.weeks": lambda x: x["certified_payroll_admin"].update(weeks=5),
            "row.base_rate": lambda x: x["rows"][0].update(base_rate=1.0),
            "row.fringe_rate": lambda x: x["rows"][0].update(fringe_rate=1.0),
            "row.classification": lambda x: x["rows"][0].update(classification="Other"),
            "row.classification_status": lambda x: x["rows"][3].update(classification_status="proposed_for_conformance"),
            "row.source_ref": lambda x: x["rows"][0].update(source_ref="x"),
            "row.conformance_ref": lambda x: x["rows"][3].update(conformance_ref="CR-1"),
            "schedule.base_rate": lambda x: x["schedule"][0].update(base_rate=1.0),
            "schedule.classification": lambda x: x["schedule"][0].update(classification="Z"),
            "determination.valid_through": lambda x: x["determination"].update(valid_through="2027-01-01"),
            "determination.date": lambda x: x["determination"].update(date="2026-10-06"),
            "determination.modification": lambda x: x["determination"].update(modification="1"),
            "determination.decision_id": lambda x: x["determination"].update(decision_id="X"),
            "determination.source_ref": lambda x: x["determination"].update(source_ref="y"),
            "row removed": lambda x: x["rows"].pop(),
        }
        for name, m in muts.items():
            b = copy.deepcopy(a)
            m(b)
            self.assertNotEqual(integration.wage_identity_from_request(b), base, name)

    def test_excluded_and_normalized_things_do_not_change_it(self):
        base = self.ident()
        a = wage_args(by="Someone Else", note="another note")
        self.assertEqual(integration.wage_identity_from_request(a), base)                                  # actor and note are excluded
        b = wage_args()
        b["rows"] = list(reversed(b["rows"]))
        b["schedule"] = list(reversed(b["schedule"]))
        self.assertEqual(integration.wage_identity_from_request(b), base)                                  # list order is not content
        c = wage_args()
        c["determination"] = {**c["determination"], "modification": 0, "junk": "ignored"}
        c["rows"][0] = {**c["rows"][0], "junk": 1}
        self.assertEqual(integration.wage_identity_from_request(c), base)                                  # int vs text modification; unknown keys dropped as the engine drops them
        d = wage_args()
        d["rows"][0]["base_rate"] = float(d["rows"][0]["base_rate"])                                       # 24.5 as float/decimal-equal forms
        self.assertEqual(integration.wage_identity_from_request(d), base)
        e = wage_args()
        e["employer_burden"]["pct"] = 0.2
        self.assertEqual(integration.wage_identity_from_request(e), base)                                  # 0.20 == 0.2 exactly

    def test_malformed_inputs_raise_instead_of_guessing(self):
        for bad in (dict(rows="x"), dict(schedule=None), dict(determination="x"), dict(employer_burden={"pct": float("nan")}),
                    dict(employer_burden={"pct": object()}), dict(certified_payroll_admin={1: 2})):
            with self.assertRaises(ValueError, msg=str(list(bad))):
                self.ident(**bad)

    def test_duplicate_keys_have_no_identity_in_v2(self):
        a = wage_args()
        a["rows"].append(copy.deepcopy(a["rows"][0]))
        with self.assertRaises(integration.WageAmbiguity):
            integration.wage_identity_from_request(a)

    def test_booleans_are_not_numbers(self):
        self.assertNotEqual(self.ident(production_rates_approved=True), self.ident(production_rates_approved=1))


class TamperDetection(Base):
    def test_A_altered_employer_burden_with_same_id_modification_and_actor_makes_history_untrusted_and_rejects_the_correction(self):
        self.wage(uncleared(), "wage-A-orig-00001")
        d = self.live()["determination"]
        ident_before = (d["decision_id"], d["modification"], self.live()["recorded_by"])
        self.live()["employer_burden"]["pct"] = 0.99                                  # the reviewer's exact alteration
        self.assertEqual((d["decision_id"], d["modification"], self.live()["recorded_by"]), ident_before)
        h = self.hist()                                                               # the request observes the live record first
        self.assertFalse(h["history_complete"])
        self.assertIn("differs from the committed history", h["incomplete_reason"])
        self.assertEqual(len(h["incomplete_events"]), 1)
        before, out = self.refused(wage_args(by="Corrector"), "WAGE_HISTORY_UNAVAILABLE", "wage-A-fix-000001")
        self.assertEqual(self.live()["employer_burden"]["pct"], 0.99)                 # nothing was overwritten by the refused request
        a, b = json.loads(self.frozen()), json.loads(before)
        for k in ("audit", "pricing", "estimate", "proposal_digest", "adapter"):
            self.assertEqual(a[k], b[k], k)
        self.assertFalse(a["adapter"]["wage_history"]["records"][0]["ever_cleared"])  # flags are never reset or invented

    def test_A2_the_guard_itself_verifies_the_old_live_record_before_mutation_even_if_no_observation_ran(self):
        self.wage(uncleared(), "wage-A2-orig-0001")
        self.live()["employer_burden"]["pct"] = 0.99
        s = server.PROJECTS[self.pid]
        hist = server.WAGE_HISTORY[self.pid]
        self.assertTrue(hist["complete"])                                             # observation has not run since the tamper
        with self.assertRaises(integration.AdapterRefusal) as cm:
            integration.wage_decision_guard(s, wage_args(by="Corrector"), "x" * 64, hist)
        self.assertEqual(cm.exception.code, "WAGE_HISTORY_UNAVAILABLE")
        self.assertFalse(hist["complete"])                                            # and it marked the history untrusted

    def test_B_any_pricing_relevant_field_altered_in_the_live_record_is_detected(self):
        tampers = {
            "row base_rate": lambda w: w["rows"][0].__setitem__("base_rate", 1.0),
            "row fringe_rate": lambda w: w["rows"][1].__setitem__("fringe_rate", 99.0),
            "row classification": lambda w: w["rows"][0].__setitem__("classification", "Altered"),
            "row classification_status": lambda w: w["rows"][3].__setitem__("classification_status", "approved_conformance"),
            "schedule rate": lambda w: w["schedule"][0].__setitem__("base_rate", 1.0),
            "schedule class": lambda w: w["schedule"][0].__setitem__("classification", "Altered"),
            "employer_burden source": lambda w: w["employer_burden"].__setitem__("source_ref", "altered"),
            "production_rates_approved": lambda w: w.__setitem__("production_rates_approved", False),
            "certified_payroll_admin": lambda w: w["certified_payroll_admin"].__setitem__("unit_cost", 1.0),
            "determination valid_through": lambda w: w["determination"].__setitem__("valid_through", "2099-01-01"),
            "determination date": lambda w: w["determination"].__setitem__("date", "2020-01-01"),
            "row removed": lambda w: w["rows"].pop(),
        }
        for name, t in tampers.items():
            with self.subTest(name):
                self.setUp()
                self.wage(uncleared(), "wage-B-orig-00001")
                t(self.live())
                self.assertFalse(self.hist()["history_complete"], name)
                self.refused(wage_args(by="Corrector"), "WAGE_HISTORY_UNAVAILABLE", "wage-B-fix-000001")
                self.tearDown()

    def test_C_unchanged_canonical_content_keeps_the_history_trusted(self):
        self.wage(uncleared(), "wage-C-orig-00001")
        for _ in range(3):
            self.assertTrue(self.hist()["history_complete"])                          # repeated observations never distrust an untouched record
        for who in ({}, {"by": "Other", "note": "other"}):
            reordered = uncleared()
            reordered["rows"] = list(reversed(reordered["rows"]))
            reordered["schedule"] = list(reversed(reordered["schedule"]))
            reordered["determination"] = {**reordered["determination"], "modification": 0}
            reordered.update(who)
            self.refused(reordered, "DECISION_UNCHANGED", f"wage-C-same-{len(who):05d}")      # semantically identical = unchanged, even reordered and re-typed
        self.assertTrue(self.hist()["history_complete"])
        self.assertEqual(len(self.hist()["records"]), 1)

    def test_D_first_legitimate_correction_of_a_never_cleared_record_keeps_both_identities(self):
        self.wage(uncleared(), "wage-D-orig-00001")
        i1 = self.hist()["records"][0]["content_identity"]
        self.wage(wage_args(by="Corrector", note="conformance approved"), "wage-D-fix-000001")
        h = self.hist()
        self.assertTrue(h["history_complete"])
        recs = h["records"]
        self.assertEqual(len(recs), 2)
        self.assertEqual(recs[0]["content_identity"], i1)                             # the previous accepted identity is preserved, append-only
        self.assertNotEqual(recs[0]["content_identity"], recs[1]["content_identity"])
        self.assertEqual([r["by"] for r in recs], ["Lee Reviewer", "Corrector"])
        self.assertEqual(recs[1]["content_identity"], integration.wage_identity_from_state(server.PROJECTS[self.pid]))   # committed = what the engine really stored
        self.assertTrue(self.get()["pricing"]["wage"]["cleared"])

    def test_E_cleared_then_expired_or_voided_still_rejects_same_modification_changes(self):
        self.wage(wage_args(), "wage-E-orig-00001")
        server.PROJECTS[self.pid]["policy"]["as_of"] = "2027-01-15"
        self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan()})
        self.assertFalse(self.get()["pricing"]["wage"]["cleared"])
        self.refused(wage_args(employer_burden=dict(pct=0.31, source_ref="late")), "WAGE_HISTORICALLY_CLEARED", "wage-E-chg-000001")
        server.PROJECTS[self.pid]["scope"]["scope_version"] += 1
        self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan(diff="hard")})
        self.assertFalse(self.get()["pricing"]["wage"]["recorded"])
        self.refused(uncleared(), "WAGE_HISTORICALLY_CLEARED", "wage-E-chg-000002")

    def test_F_previously_pricing_authorizing_determination_rejects_same_modification_changes(self):
        self.wage(wage_args(), "wage-F-orig-00001")
        self.post("decisions/crew-plan", {**WHO, **plan()})
        self.assertTrue(self.hist()["records"][0]["ever_authorized_pricing"])
        self.refused(wage_args(employer_burden=dict(pct=0.29, source_ref="x")), "WAGE_MODIFICATION_NOT_HIGHER", "wage-F-chg-000001")

    def test_G_missing_or_malformed_committed_identity_fails_closed(self):
        broken = {"missing key": lambda r: r.pop("content_identity"), "None": lambda r: r.__setitem__("content_identity", None),
                  "short": lambda r: r.__setitem__("content_identity", "abc"), "non-hex": lambda r: r.__setitem__("content_identity", "z" * 64),
                  "wrong type": lambda r: r.__setitem__("content_identity", 12345), "uppercase": lambda r: r.__setitem__("content_identity", r["content_identity"].upper()),
                  "wrong spec": lambda r: r.__setitem__("identity_spec", "wage-content-identity-v0"), "spec missing": lambda r: r.pop("identity_spec")}
        for name, b in broken.items():
            with self.subTest(name):
                self.setUp()
                self.wage(uncleared(), "wage-G-orig-00001")
                b(server.WAGE_HISTORY[self.pid]["records"][0])
                h = self.hist()
                self.assertFalse(h["history_complete"], name)
                self.assertIn("missing or malformed", h["incomplete_reason"])
                self.refused(wage_args(by="Corrector"), "WAGE_HISTORY_UNAVAILABLE", "wage-G-fix-000001")
                self.tearDown()

    def test_H_client_supplied_hashes_or_flags_confer_no_authority(self):
        self.wage(uncleared(), "wage-H-orig-00001")
        real = self.hist()["records"][0]["content_identity"]
        for field in ("content_identity", "content_sha256", "ever_cleared", "never_cleared", "history_complete"):
            c, out = self.call("POST", f"/projects/{self.pid}/{W}", {**wage_args(by="Corrector"), field: real}, idem=f"wage-H-top-{field[:6]}-1")
            self.assertEqual((c, out["code"]), (400, "BAD_REQUEST"), field)          # unknown top-level fields
        self.live()["employer_burden"]["pct"] = 0.99
        forged = wage_args(by="Corrector")
        forged["determination"] = {**forged["determination"], "content_identity": real, "content_sha256": real, "history_complete": True}
        forged["employer_burden"] = {**forged["employer_burden"]}
        self.refused(forged, "WAGE_HISTORY_UNAVAILABLE", "wage-H-fake-00001")        # embedded fake hashes cannot restore trust
        self.assertFalse(self.hist()["history_complete"])
        # nor can a fake hash make changed content look unchanged against a cleared record
        self.setUp()
        self.wage(wage_args(), "wage-H-cleared-001")
        ident = self.hist()["records"][0]["content_identity"]
        chg = wage_args(employer_burden=dict(pct=0.5, source_ref="x"))
        chg["determination"] = {**chg["determination"], "content_identity": ident}
        self.refused(chg, "WAGE_MODIFICATION_NOT_HIGHER", "wage-H-cleared-002")

    def test_I_a_higher_lawful_modification_after_an_untrusted_event_is_accepted_but_never_restores_trust(self):
        self.wage(wage_args(), "wage-I-orig-00001")
        self.post("decisions/crew-plan", {**WHO, **plan()})                           # flags set: cleared and authorized pricing
        self.live()["employer_burden"]["pct"] = 0.99
        self.assertFalse(self.hist()["history_complete"])
        flags_before = [(r["ever_cleared"], r["ever_authorized_pricing"]) for r in self.hist()["records"]]
        self.wage(mod(1, by="Second Reviewer"), "wage-I-mod1-00001")                 # existing policy: a strictly higher modification does not need history
        h = self.hist()
        self.assertEqual(self.get()["pricing"]["wage"]["decision"]["modification"], "1")
        self.assertFalse(h["history_complete"])                                       # trust is NOT restored
        self.assertEqual(len(h["records"]), 2)
        self.assertEqual([(r["ever_cleared"], r["ever_authorized_pricing"]) for r in h["records"][:1]], flags_before)   # earlier flags untouched
        self.assertGreaterEqual(len(h["incomplete_events"]), 1)
        self.refused(mod(1, employer_burden=dict(pct=0.4, source_ref="x")), "WAGE_HISTORY_UNAVAILABLE", "wage-I-chg-000001")   # same-modification edits stay blocked
        self.refused(mod(0, by="Back"), "WAGE_HISTORY_UNAVAILABLE", "wage-I-low-000001")                                         # and lower ones

    def test_J_exact_replay_and_raw_bytes_are_unchanged_even_after_the_history_became_untrusted(self):
        raw1, raw2 = [], []
        c, o1 = self.call("POST", f"/projects/{self.pid}/{W}", uncleared(), idem="wage-J-orig-00001", raw_out=raw1)
        self.assertEqual(c, 200)
        self.live()["employer_burden"]["pct"] = 0.99
        self.assertFalse(self.hist()["history_complete"])
        before, muts, h = self.frozen(), self.mutations(), {}
        c, o2 = self.call("POST", f"/projects/{self.pid}/{W}", uncleared(), idem="wage-J-orig-00001", raw_out=raw2, headers_out=h)
        self.assertEqual(c, 200)
        self.assertEqual(raw2[0], raw1[0])                                            # byte-identical to the original response
        self.assertEqual((h["idempotent-replay"], h["x-idempotency-result"]), ("true", "historical"))
        self.assertEqual((self.frozen(), self.mutations()), (before, muts))

    def test_K_rejected_attempts_change_nothing_but_the_documented_quota_counter(self):
        self.wage(uncleared(), "wage-K-orig-00001")
        self.live()["employer_burden"]["pct"] = 0.99
        before = json.loads(self.frozen())                                          # this request observes the tamper and distrusts the history once
        live_before = copy.deepcopy(self.live())
        hist_before = copy.deepcopy(server.WAGE_HISTORY[self.pid])
        self.assertFalse(hist_before["complete"])
        for i in range(3):
            self.refused(wage_args(by="Corrector"), "WAGE_HISTORY_UNAVAILABLE", f"wage-K-bad-{i:07d}")
        self.assertEqual(self.live(), live_before)                                    # the authoritative wage record
        self.assertEqual(server.WAGE_HISTORY[self.pid], hist_before)                  # history (and its incomplete_events) not re-appended
        after = json.loads(self.frozen())
        for k in ("audit", "pricing", "estimate", "proposal_digest", "labor_review", "adapter"):
            self.assertEqual(after[k], before[k], k)

    def test_L_concurrent_identical_retries_still_execute_once(self):
        import threading
        res, lock, barrier = [], threading.Lock(), threading.Barrier(10)

        def go():
            raw, h = [], {}
            barrier.wait()
            c, _ = self.call("POST", f"/projects/{self.pid}/{W}", uncleared(), idem="wage-L-burst-0001", headers_out=h, raw_out=raw)
            with lock:
                res.append((c, "idempotent-replay" in h, raw[0]))
        ts = [threading.Thread(target=go) for _ in range(10)]
        [t.start() for t in ts]
        [t.join(30) for t in ts]
        self.assertEqual({c for c, _, _ in res}, {200})
        self.assertEqual(len([1 for _, rep, _ in res if not rep]), 1)
        self.assertEqual(len({b for _, _, b in res}), 1)
        self.assertEqual(len(self.hist()["records"]), 1)
        self.assertTrue(self.hist()["history_complete"])


if __name__ == "__main__":
    unittest.main()

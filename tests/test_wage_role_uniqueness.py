"""Pass 6: duplicate role / classification keys are invalid wage data. The evaluator (pricing/prevailing.py) uses the FIRST row for a role (exact `role_key`
equality) and the LAST duplicate schedule entry (`classification.strip().lower()`), so order would change behavior while an order-independent identity would
not. Policy: such content is rejected BEFORE acceptance or identity commitment (400 `WAGE_ROW_DUPLICATE_ROLE` / `WAGE_SCHEDULE_DUPLICATE_CLASSIFICATION`),
even when duplicates carry identical values; never merged, repaired or first/last-picked. Unique-key content is order independent for BOTH identity and
evaluator (asserted by permutation). Quota policy unchanged: a rejected attempt counts toward the demo mutation cap; an exact replay never does."""
import copy
import datetime
import itertools
import json
import os
import threading
import unittest
from unittest import mock

from api import server
from engine import integration
from pricing import prevailing
from tests.http_harness import HttpBase, WHO, plan
from tests.test_ratebook_workflow import wage_args, good_rows, row, OPR

W = "decisions/wage-determination"
ROLES = ["R1", "R2", "R3", "R4"]
AS_OF = datetime.date(2026, 10, 13)


def evaluate(body):
    rec = {k: body[k] for k in ("determination", "schedule", "rows", "employer_burden", "production_rates_approved", "certified_payroll_admin")}
    return json.dumps(prevailing.evaluate(rec, ROLES, AS_OF), sort_keys=True, default=str)


def with_dup_r1(identical=False, **kw):
    a = wage_args(**kw)
    extra = copy.deepcopy(a["rows"][0])
    if not identical:
        extra.update(classification="Operator", base_rate=29.80, fringe_rate=11.25)
    a["rows"] = a["rows"] + [extra]
    return a


def uncleared():
    r = good_rows()
    r[3] = row("R4", OPR, status="proposed_for_conformance")
    return wage_args(rows=r)


class Rule(unittest.TestCase):
    """The uniqueness rule, derived from the evaluator's actual matching (no invented aliases)."""
    def test_role_keys_are_exact_strings_no_case_folding_or_trimming(self):
        rows = [{"role_key": "R1"}, {"role_key": "r1"}, {"role_key": "R1 "}, {"role_key": "R2"}]
        self.assertEqual(integration.wage_ambiguities([], rows), [])                       # distinct strings are distinct keys, exactly as the evaluator treats them
        self.assertEqual(integration.wage_ambiguities([], rows + [{"role_key": "R1"}]), [("WAGE_ROW_DUPLICATE_ROLE", "R1")])

    def test_schedule_classifications_use_the_evaluators_strip_lower_key(self):
        self.assertEqual(integration.wage_ambiguities([{"classification": "Laborer"}, {"classification": "  laborer "}], []),
                         [("WAGE_SCHEDULE_DUPLICATE_CLASSIFICATION", "laborer")])
        self.assertEqual(integration.wage_ambiguities([{"classification": "Laborer"}, {"classification": "Laborer Group 2"}], []), [])

    def test_non_string_blank_and_non_dict_entries_are_not_keys(self):
        self.assertEqual(integration.wage_ambiguities([{"classification": " "}, {"classification": " "}, {"classification": None}, {"classification": None}, "x", 3], []), [])
        self.assertEqual(integration.wage_ambiguities([], [{"role_key": None}, {"role_key": None}, {"role_key": 5}, {"role_key": 5}, "x"]), [])

    def test_duplicates_have_no_identity(self):
        for body in (with_dup_r1(), with_dup_r1(identical=True)):
            with self.assertRaises(integration.WageAmbiguity):
                integration.wage_identity_from_request(body)
        s = wage_args()
        s["schedule"].append({**s["schedule"][0], "classification": s["schedule"][0]["classification"].upper() + " "})
        with self.assertRaises(integration.WageAmbiguity):
            integration.wage_identity_from_request(s)

    def test_D_unique_rows_in_every_order_share_identity_and_evaluator_result(self):
        base = wage_args()
        ids, evs = set(), set()
        for perm in itertools.permutations(range(len(base["rows"]))):
            for rev in (False, True):
                b = copy.deepcopy(base)
                b["rows"] = [base["rows"][i] for i in perm]
                b["schedule"] = list(reversed(base["schedule"])) if rev else list(base["schedule"])
                ids.add(integration.wage_identity_from_request(b))
                evs.add(evaluate(b))
        self.assertEqual((len(ids), len(evs)), (1, 1))                                      # 48 orderings: one identity, one evaluator result
        # and the premise this rule exists for: with duplicates the evaluator IS order sensitive
        a1, a2 = with_dup_r1(), with_dup_r1()
        a2["rows"] = [a1["rows"][-1]] + a1["rows"][:-1]
        self.assertNotEqual(evaluate(a1), evaluate(a2))


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

    def rejected(self, body, code, idem, status=400):
        before, muts = self.frozen(), self.mutations()
        c, out = self.call("POST", f"/projects/{self.pid}/{W}", body, idem=idem)
        self.assertEqual((c, out.get("code")), (status, code), out)
        self.assertEqual(self.frozen(), before)                                              # summary: audit, wage, pricing, plan, digest, ledger, history
        self.assertEqual(self.mutations(), muts + 1)                                         # documented quota policy
        return out


class Rejection(Base):
    def test_A_duplicate_r1_rows_with_different_rates_are_rejected_with_a_specific_code(self):
        out = self.rejected(with_dup_r1(), "WAGE_ROW_DUPLICATE_ROLE", "wage-A-dup-000001")
        self.assertEqual(out["details"], [{"code": "WAGE_ROW_DUPLICATE_ROLE", "key": "R1"}])
        self.assertIn("nothing was recorded", out["error"])
        self.assertFalse(self.get()["pricing"]["wage"]["recorded"])

    def test_B_duplicate_r1_rows_with_identical_rates_are_rejected_too(self):
        self.rejected(with_dup_r1(identical=True), "WAGE_ROW_DUPLICATE_ROLE", "wage-B-dup-000001")

    def test_B2_duplicate_schedule_classifications_are_rejected_under_the_evaluators_normalization(self):
        a = wage_args()
        a["schedule"].append({**a["schedule"][0], "classification": " " + a["schedule"][0]["classification"].lower()})
        self.rejected(a, "WAGE_SCHEDULE_DUPLICATE_CLASSIFICATION", "wage-B2-dup-00001")

    def test_B3_no_invented_aliases_a_differently_cased_role_key_is_just_an_unknown_role(self):
        a = wage_args()
        a["rows"].append({**a["rows"][0], "role_key": "r1"})
        self.wage(a, "wage-B3-case-00001")                                                  # accepted as DATA; the evaluator flags the unknown role itself
        self.assertIn("WAGE_ROW_UNKNOWN_ROLE", self.get()["pricing"]["wage"]["blockers"])
        self.assertFalse(self.get()["pricing"]["wage"]["cleared"])

    def test_I_rejected_duplicates_create_no_pricing_wage_approval_plan_or_digest_mutation(self):
        self.wage(wage_args(), "wage-I-orig-00001")
        self.post("decisions/crew-plan", {**WHO, **plan()})
        before = json.loads(self.frozen())
        live_before = copy.deepcopy(self.live())
        hist_before = copy.deepcopy(server.WAGE_HISTORY[self.pid])
        muts = self.mutations()
        bodies = [with_dup_r1(), with_dup_r1(identical=True), with_dup_r1(by="Other"), with_dup_r1(note="other")]
        mod1 = with_dup_r1()
        mod1["determination"] = {**mod1["determination"], "modification": "1"}
        bodies.append(mod1)                                                                  # a duplicate at a HIGHER modification is rejected as well
        for i, b in enumerate(bodies):
            c, out = self.call("POST", f"/projects/{self.pid}/{W}", b, idem=f"wage-I-dup-{i:06d}")
            self.assertEqual((c, out["code"]), (400, "WAGE_ROW_DUPLICATE_ROLE"))
        after = json.loads(self.frozen())
        for k in ("audit", "pricing", "estimate", "proposal_digest", "labor_review", "adapter", "status"):
            self.assertEqual(after[k], before[k], k)
        self.assertEqual(self.live(), live_before)
        self.assertEqual(server.WAGE_HISTORY[self.pid], hist_before)
        self.assertEqual(after["pricing"]["crew_plan"]["plan_version"], 1)
        self.assertEqual(self.mutations(), muts + len(bodies))                               # refused attempts consume quota; nothing else changes

    def test_I2_a_rejected_duplicate_is_never_stored_for_replay(self):
        for _ in range(2):
            c, out = self.call("POST", f"/projects/{self.pid}/{W}", with_dup_r1(), idem="wage-I2-dup-00001")
            self.assertEqual((c, out["code"]), (400, "WAGE_ROW_DUPLICATE_ROLE"))
        self.assertEqual([d for d in self.get()["adapter"]["decisions"] if d["route"] == "wage-determination"], [])
        self.wage(wage_args(), "wage-I2-dup-00001")                                          # the key was not burned; a corrected request works with it

    def test_J_no_bypass_through_other_shapes_routes_or_client_hashes(self):
        a = wage_args()
        shapes = {"rows as object": {**a, "rows": {"R1": a["rows"][0], "R2": a["rows"][1]}},
                  "rows as tuple-like pairs": {**a, "rows": [["R1", 1], ["R1", 2]]},
                  "rows string": {**a, "rows": "R1,R1"},
                  "unhashable role keys": {**a, "rows": [{**a["rows"][0], "role_key": ["R1"]}, {**a["rows"][0], "role_key": ["R1"]}]}}
        for name, body in shapes.items():
            before = self.frozen()
            c, out = self.call("POST", f"/projects/{self.pid}/{W}", body, idem=f"wage-J-shape-{abs(hash(name)) % 10**6:06d}")
            self.assertIn(c, (400, 409), name)
            self.assertEqual(self.frozen(), before, name)
        d = with_dup_r1()
        for field in ("content_identity", "content_sha256", "idempotency_key", "ever_cleared"):
            c, out = self.call("POST", f"/projects/{self.pid}/{W}", {**d, field: "0" * 64}, idem=f"wage-J-top-{field[:5]}-1")
            self.assertEqual(c, 400)                                                        # unknown top-level field, nothing recorded
        d["rows"][-1]["content_identity"] = "0" * 64
        d["determination"] = {**d["determination"], "content_identity": "0" * 64}
        self.rejected(d, "WAGE_ROW_DUPLICATE_ROLE", "wage-J-hash-000001")                    # client hashes inside rows/determination cannot hide the duplicate
        for route, body in (("decisions/crew-plan", {**WHO, **plan(), "rows": d["rows"]}), ("decisions/ruleset-approval", {**WHO, "ruleset_sha256": "0" * 64, "rows": d["rows"]})):
            c, out = self.call("POST", f"/projects/{self.pid}/{route}", body)
            self.assertEqual(c, 400, route)                                                 # other decision routes cannot carry wage rows
        before = self.frozen()
        c, out = self.call("POST", f"/projects/{self.pid}/labor/resolve", {"by": "x", "decision": "verified_standard", "certified_payroll": False, "applicability_review": "x",
                                                                          "note": "x", "classifications": [{"role_key": "R1"}, {"role_key": "R1"}]})
        self.assertIn(c, (400, 409))                                                       # the company-rate labor route cannot carry wage rows into a prevailing-wage project
        self.assertEqual(self.frozen(), before)

    def test_J2_the_dangerous_path_is_closed_for_corrections_of_a_never_cleared_record(self):
        self.wage(uncleared(), "wage-J2-orig-00001")
        live_before = copy.deepcopy(self.live())
        self.rejected(with_dup_r1(by="Corrector"), "WAGE_ROW_DUPLICATE_ROLE", "wage-J2-fix-000001")
        self.assertEqual(self.live(), live_before)
        self.wage(wage_args(by="Corrector"), "wage-J2-fix-000002")                          # the legitimate correction (unique rows) still works
        self.assertTrue(self.get()["pricing"]["wage"]["cleared"])


class History(Base):
    def v1_identity(self, body):
        """The pass-5 algorithm (v1, no ambiguity check): what an OLD committed hash looked like, including for duplicate-bearing content."""
        det = integration._project(body["determination"], integration._DET_KEYS)
        det["modification"] = str(body["determination"]["modification"])
        obj = {"spec": "wage-content-identity-v1", "determination": det,
               "schedule": integration._sorted_unique_order([integration._project(x, integration._SCHED_KEYS) for x in body["schedule"]]),
               "rows": integration._sorted_unique_order([integration._project(x, integration._ROW_KEYS) for x in body["rows"]]),
               "employer_burden": integration._canon_val(body["employer_burden"]), "production_rates_approved": integration._canon_val(body["production_rates_approved"]),
               "certified_payroll_admin": integration._canon_val(body["certified_payroll_admin"])}
        import hashlib
        return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()

    def live_body(self):
        w = self.live()
        return {k: copy.deepcopy(w[k]) for k in ("determination", "schedule", "rows", "employer_burden", "production_rates_approved", "certified_payroll_admin")}

    def test_C_a_committed_old_hash_does_not_make_ambiguous_content_trusted_in_any_order(self):
        self.wage(uncleared(), "wage-C-orig-00001")
        # simulate a pass-5-era record: the live record gained a duplicate R1 row and history holds the matching OLD v1 hash
        self.live()["rows"].append({**self.live()["rows"][0], "classification": "Operator", "base_rate": 29.80, "fringe_rate": 11.25})
        rec = server.WAGE_HISTORY[self.pid]["records"][0]
        rec["content_identity"], rec["identity_spec"] = self.v1_identity(self.live_body()), "wage-content-identity-v1"
        h = self.hist()
        self.assertFalse(h["history_complete"])                                              # hash matches, yet it is NOT trusted
        self.assertIn("ambiguous duplicate", h["incomplete_reason"])
        self.live()["rows"].reverse()                                                        # reordering the duplicates cannot make them 'equivalent'
        rec["content_identity"] = self.v1_identity(self.live_body())
        self.assertFalse(self.hist()["history_complete"])
        before = self.frozen()
        c, out = self.call("POST", f"/projects/{self.pid}/{W}", wage_args(by="Corrector"), idem="wage-C-fix-000001")
        self.assertEqual((c, out["code"]), (409, "WAGE_HISTORY_UNAVAILABLE"))                # same-modification change fails closed
        self.assertEqual(self.frozen(), before)
        self.assertEqual(len(server.WAGE_HISTORY[self.pid]["records"]), 1)                   # the old record and its identity are neither erased nor rewritten

    def test_E_a_legacy_v1_commitment_stays_trusted_for_unambiguous_content_and_legitimate_corrections_work(self):
        self.wage(uncleared(), "wage-E-orig-00001")
        rec = server.WAGE_HISTORY[self.pid]["records"][0]
        self.assertEqual(rec["identity_spec"], "wage-content-identity-v2")
        rec["content_identity"], rec["identity_spec"] = self.v1_identity(self.live_body()), "wage-content-identity-v1"      # as committed by pass 5
        self.assertTrue(self.hist()["history_complete"])                                      # unambiguous v1 history is not distrusted
        self.wage(wage_args(by="Corrector"), "wage-E-fix-000001")
        recs = self.hist()["records"]
        self.assertEqual([r["identity_spec"] for r in recs], ["wage-content-identity-v1", "wage-content-identity-v2"])   # old identity preserved, new one appended
        self.assertTrue(self.get()["pricing"]["wage"]["cleared"])

    def test_F_cleared_or_authorized_decisions_stay_protected_after_invalidation(self):
        self.wage(wage_args(), "wage-F-orig-00001")
        self.post("decisions/crew-plan", {**WHO, **plan()})
        server.PROJECTS[self.pid]["policy"]["as_of"] = "2027-01-15"
        self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan(diff="hard")})
        self.assertFalse(self.get()["pricing"]["wage"]["cleared"])
        before = self.frozen()
        c, out = self.call("POST", f"/projects/{self.pid}/{W}", wage_args(employer_burden=dict(pct=0.31, source_ref="late")), idem="wage-F-chg-000001")
        self.assertEqual((c, out["code"]), (409, "WAGE_HISTORICALLY_CLEARED"))
        server.PROJECTS[self.pid]["scope"]["scope_version"] += 1
        self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan()})
        self.assertFalse(self.get()["pricing"]["wage"]["recorded"])
        c, out = self.call("POST", f"/projects/{self.pid}/{W}", uncleared(), idem="wage-F-chg-000002")
        self.assertEqual((c, out["code"]), (409, "WAGE_HISTORICALLY_CLEARED"))
        h = self.hist()["records"][0]
        self.assertEqual((h["ever_cleared"], h["ever_authorized_pricing"]), (True, True))

    def test_G_missing_malformed_or_mismatched_history_fails_closed(self):
        cases = {"identity missing": lambda r, l: r.pop("content_identity"), "identity malformed": lambda r, l: r.__setitem__("content_identity", "xyz"),
                 "spec unknown": lambda r, l: r.__setitem__("identity_spec", "wage-content-identity-v9"),
                 "content mismatch": lambda r, l: l["employer_burden"].__setitem__("pct", 0.77),
                 "actor mismatch": lambda r, l: l.__setitem__("recorded_by", "Out Of Band")}
        for name, f in cases.items():
            with self.subTest(name):
                self.setUp()
                self.wage(uncleared(), "wage-G-orig-00001")
                f(server.WAGE_HISTORY[self.pid]["records"][0], self.live())
                self.assertFalse(self.hist()["history_complete"], name)
                c, out = self.call("POST", f"/projects/{self.pid}/{W}", wage_args(by="Corrector"), idem="wage-G-fix-000001")
                self.assertEqual((c, out["code"]), (409, "WAGE_HISTORY_UNAVAILABLE"), name)
                self.tearDown()
        self.setUp()
        self.wage(uncleared(), "wage-G-nohist-0001")
        del server.WAGE_HISTORY[self.pid]                                                    # history absent entirely
        c, out = self.call("POST", f"/projects/{self.pid}/{W}", wage_args(by="Corrector"), idem="wage-G-nohist-0002")
        self.assertEqual((c, out["code"]), (409, "WAGE_HISTORY_UNAVAILABLE"))
        self.tearDown()


class ReplayAndConcurrency(Base):
    def test_H_exact_replays_keep_raw_bytes_and_are_served_at_the_cap(self):
        raw1, raw2 = [], []
        c, o1 = self.call("POST", f"/projects/{self.pid}/{W}", wage_args(), idem="wage-H-orig-00001", raw_out=raw1)
        self.assertEqual(c, 200)
        cap = self.mutations() + 1
        with mock.patch.dict(os.environ, {"DEMO_MAX_MUTATIONS": str(cap)}):
            self.call("POST", f"/projects/{self.pid}/{W}", with_dup_r1(), idem="wage-H-dup-000001")      # a rejected attempt consumes the last unit of quota
            self.assertEqual(self.mutations(), cap)
            before, muts, h = self.frozen(), self.mutations(), {}
            c, o2 = self.call("POST", f"/projects/{self.pid}/{W}", wage_args(), idem="wage-H-orig-00001", raw_out=raw2, headers_out=h)
            self.assertEqual(c, 200)                                                         # replay at the cap is served
            self.assertEqual(raw2[0], raw1[0])                                               # byte-identical to the original response
            self.assertEqual((h["idempotent-replay"], h["x-idempotency-result"]), ("true", "historical"))
            self.assertEqual((self.frozen(), self.mutations()), (before, muts))
            c, out = self.call("POST", f"/projects/{self.pid}/{W}", wage_args(by="Other"), idem="wage-H-orig-00001")
            self.assertEqual((c, out["code"]), (429, "RATE_LIMITED"))                       # a changed actor at the cap does not bypass it
            c, out = self.call("POST", f"/projects/{self.pid}/{W}", with_dup_r1(), idem="wage-H-new-000001")
            self.assertEqual((c, out["code"]), (429, "RATE_LIMITED"))                       # and a new (here invalid) request is still capped

    def test_K_ten_concurrent_identical_valid_retries_execute_once(self):
        res, lock, barrier = [], threading.Lock(), threading.Barrier(10)

        def go():
            raw, h = [], {}
            barrier.wait()
            c, _ = self.call("POST", f"/projects/{self.pid}/{W}", wage_args(), idem="wage-K-burst-0001", headers_out=h, raw_out=raw)
            with lock:
                res.append((c, "idempotent-replay" in h, raw[0]))
        ts = [threading.Thread(target=go) for _ in range(10)]
        [t.start() for t in ts]
        [t.join(30) for t in ts]
        self.assertEqual({c for c, _, _ in res}, {200})
        self.assertEqual(len([1 for _, rep, _ in res if not rep]), 1)
        self.assertEqual(len({b for _, _, b in res}), 1)
        self.assertEqual(len(self.hist()["records"]), 1)

    def test_K2_ten_concurrent_identical_duplicate_row_retries_all_reject_and_record_nothing(self):
        codes, lock, barrier = [], threading.Lock(), threading.Barrier(10)
        before = self.frozen()

        def go():
            barrier.wait()
            c, out = self.call("POST", f"/projects/{self.pid}/{W}", with_dup_r1(), idem="wage-K2-burst-001")
            with lock:
                codes.append((c, out.get("code")))
        ts = [threading.Thread(target=go) for _ in range(10)]
        [t.start() for t in ts]
        [t.join(30) for t in ts]
        self.assertEqual(set(codes), {(400, "WAGE_ROW_DUPLICATE_ROLE")})
        a, b = json.loads(self.frozen()), json.loads(before)
        for k in ("audit", "pricing", "adapter", "estimate"):
            self.assertEqual(a[k], b[k], k)


if __name__ == "__main__":
    unittest.main()

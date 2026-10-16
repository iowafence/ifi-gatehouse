"""Rate-book mode of the three-gate workflow, including the end-to-end acceptance scenario:
original package (G3 width unresolved, Addendum 01 already bundled) -> stop at G3 -> Addendum 02 -> named Scope Gate
approvals -> Labor Gate -> separately attached rate book -> base + alternate costs -> Release Gate bound to the exact
revision and pricing version -> later addendum / rate-book changes invalidate approvals and preserve history.
All geometry and rates are fictional test data; ADDENDUM_02_TEST_WIDTH_FT is a test value, not any real G3 width."""
import copy
import json
import unittest
from decimal import Decimal

from api import server
from engine import workflow as wf
from pricing import ratebook as rb
from tests import pricing_helpers as H
from tests import scope_fixtures as sf
from tests import xlsx_builder as xb

POLICY = {"as_of": "2026-10-13"}
SHA2, SHA3 = "2" * 64, "3" * 64
ADD02 = {"doc_id": "ADD02", "doc_revision": 2, "sha256": SHA2}


def blocking(s):
    return {e["code"] for e in s["exceptions"] if e["severity"] == "blocking"}


def opt(s, code, option=None):
    ex = next(e for e in s["exceptions"] if e["code"] == code)
    return ex["exception_id"], option or ex["candidate_resolutions"][0]["option_id"]


def approve_rules(s, by="Pat Estimator", note="reviewed rule table"):
    return wf.approve_quantity_ruleset(s, by=by, note=note, ruleset_sha256=s["ruleset"]["sha256"])


def accept(s, by="Test Approver", note="accepted"):
    return wf.accept_addendum(s, by=by, note=note, scope_version=s["pending_acceptance"]["scope_version"])


def start(scope=None, book=None):
    return wf.start(scope or sf.base_scope(), None, ratebook=book or H.book(), policy=POLICY)


def to_scope_cleared(s):
    wf.revise_scope(s, sf.addendum_02_facts(), source=ADD02, by="intake-service", note="Addendum 02 ingested")
    approve_rules(s, by="Pat Estimator", note="reviewed rule table v1.0.0")
    accept(s, by="Test Approver", note="G3 now 12 ft per Addendum 02")
    return s


def labor(s, **kw):
    args = dict(by="Lee Reviewer", decision="verified_standard", certified_payroll=False, source_refs=["company wage schedule 2026"],
                applicability_review="private work, no prevailing wage", note="company rates apply")
    args.update(kw)
    return wf.approve_labor(s, **args)


def ready(book=None, scope=None):
    s = start(scope, book)
    to_scope_cleared(s)
    labor(s)
    assert s["status"] == wf.READY, (s["status"], blocking(s))
    return s


class Acceptance(unittest.TestCase):
    def test_full_scenario(self):
        # 1-4: upload, extract, deterministic quantities, STOP at unresolved G3
        s = start()
        self.assertEqual(s["status"], wf.SCOPE_REVIEW)
        self.assertEqual(blocking(s), {"MISSING_VALUE"})
        self.assertIn("gates > 2 > clear_width_ft", next(e for e in s["exceptions"] if e["code"] == "MISSING_VALUE")["question"])
        self.assertIsNone(s["takeoff"])
        self.assertIsNone(s["quantities"])
        self.assertIsNone(s["estimate"])
        with self.assertRaises(wf.GateError):
            labor(s)
        with self.assertRaises(wf.GateError):
            wf.release(s, "Test Approver", 1, "0" * 64)
        self.assertEqual(s["scope"]["gates"][2]["clear_width_ft"], sf.fact(None, "unresolved"))   # nothing was invented

        # 5: Addendum 02 arrives for the same project
        wf.revise_scope(s, sf.addendum_02_facts(), source=ADD02, by="intake-service", note="Addendum 02 ingested")
        self.assertEqual(s["scope"]["scope_version"], 2)
        self.assertEqual(s["scope"]["gates"][2]["clear_width_ft"]["value"], sf.ADDENDUM_02_TEST_WIDTH_FT)
        self.assertIsNotNone(s["takeoff"])
        self.assertIsNotNone(s["quantities"])
        self.assertIsNone(s["estimate"])
        self.assertEqual(blocking(s), {"QUANTITY_RULESET_UNAPPROVED", "ADDENDUM_ACCEPTANCE_REQUIRED"})
        self.assertEqual(s["status"], wf.SCOPE_REVIEW)
        with self.assertRaises(wf.GateError):
            labor(s)                                              # new information does not silently grant approval

        # 6: named Scope Gate approvals
        with self.assertRaises(wf.GateError):
            approve_rules(s, by="  ", note="x")
        approve_rules(s, by="Pat Estimator", note="reviewed rule table v1.0.0")
        self.assertEqual(blocking(s), {"ADDENDUM_ACCEPTANCE_REQUIRED"})
        accept(s, by="Test Approver", note="G3 now 12 ft per Addendum 02")
        self.assertEqual(s["status"], wf.LABOR_REVIEW)
        self.assertIsNone(s["estimate"])                          # still no money before the labor basis is approved

        # 7: Labor Gate
        labor(s)
        self.assertEqual(s["status"], wf.READY)
        lr = s["labor_review"]
        self.assertEqual(lr["ratebook_labor_sha256"], s["ratebook"]["hashes"]["labor_sha256"])

        # 8-9: separately attached rate book -> base and alternate costs, quantities, qualifications
        est = s["estimate"]
        self.assertEqual(set(est["scenarios"]), {"BASE", "ALT-A1"})
        self.assertEqual(est["ratebook_ref"], s["ratebook_ref"])
        base, alt = est["scenarios"]["BASE"], est["scenarios"]["ALT-A1"]
        self.assertGreater(alt["price_total"], 0)
        self.assertGreater(base["price_total"], alt["price_total"])
        self.assertEqual(est["price_total"], base["price_total"])
        self.assertEqual([l["item_id"] for l in base["materials"]["lines"]].count("M40"), 1)       # concrete once
        self.assertNotIn("M41", {l["item_id"] for sc in est["scenarios"].values() for l in sc["materials"]["lines"]})
        m05 = next(l for l in base["materials"]["lines"] if l["item_id"] == "M05")
        self.assertEqual((m05["quantity"], m05["status"]), (550, "confirmed"))
        self.assertTrue(all(l["unit_price"] > 0 for sc in est["scenarios"].values() for l in sc["materials"]["lines"]))
        quals = wf.qualifications(s)
        self.assertEqual({q["type"] for q in quals}, {"quantity_ruleset_approved", "addendum_accepted"})

        # 10: Release Gate bound to this exact revision and pricing version
        digest = s["proposal_digest"]
        with self.assertRaises(wf.GateError):
            wf.release(s, "Test Approver", 1, digest)                       # stale scope version
        with self.assertRaises(wf.GateError):
            wf.release(s, "Test Approver", 2, "f" * 64)                     # wrong digest
        pkg = wf.release(s, "Test Approver", 2, digest, note="approved")
        self.assertEqual(s["status"], wf.RELEASED)
        self.assertEqual(pkg["ratebook_ref"], s["ratebook_ref"])
        self.assertEqual(pkg["scope_version"], 2)
        self.assertEqual(pkg["proposal_digest"], digest)
        self.assertEqual(pkg["ruleset"]["approved_by"], "Pat Estimator")
        self.assertIn("M05", {i.get("item_id") for i in pkg["quantities"]["BASE"]["items"]})

    def test_no_money_before_every_gate_and_never_from_a_model(self):
        s = start()
        self.assertNotIn("estimate", json.dumps({k: v for k, v in s.items() if k == "estimate" and v}))
        to_scope_cleared(s)
        self.assertIsNone(s["estimate"])
        s2 = start()
        self.assertTrue(all(not k.lower().startswith(("price", "cost", "wage")) for k in s2["scope"]))


class Addenda(unittest.TestCase):
    def test_addendum_changes_quantities_not_prices_and_preserves_the_previous_version(self):
        s = ready()
        old_est, old_digest = copy.deepcopy(s["estimate"]), s["proposal_digest"]
        old_prices = {l["item_id"]: l["unit_price"] for l in old_est["scenarios"]["BASE"]["materials"]["lines"]}
        g2 = sf.fact(10.0, unit="ft", doc="ADD03", page=1, sheet="ADD-03", rev=3, excerpt="G2 revised to 10 ft (test)")
        wf.revise_scope(s, [{"path": "/gates/1/clear_width_ft", "fact": g2}], source={"doc_id": "ADD03", "doc_revision": 3, "sha256": SHA3},
                        by="intake-service", note="Addendum 03 ingested")
        self.assertEqual(s["scope"]["scope_version"], 3)
        self.assertIsNone(s["estimate"])
        self.assertEqual(s["labor_review"]["status"], "unresolved")                 # labor approval invalidated
        self.assertEqual(s["status"], wf.SCOPE_REVIEW)
        self.assertIn("ADDENDUM_ACCEPTANCE_REQUIRED", blocking(s))
        # the previous estimate version is preserved, untouched
        prior = [h for h in s["history"] if h["kind"] == "scope_revision"][-1]["snapshot"]
        self.assertEqual(prior["estimate"], old_est)
        self.assertEqual(prior["proposal_digest"], old_digest)
        self.assertEqual(prior["scope_version"], 2)
        # before/after quantity differences are available for the Scope Gate
        d = s["last_change"]["diff"]
        qd = {(r["scope_ref"], r["key"]): r for r in d["quantities"]}
        self.assertEqual(qd[("BASE", "M21")]["delta"], -4)                          # G2 x2 narrows 12 -> 10 ft: 38 -> 34 LF of gate leaf fabric
        self.assertEqual(qd[("BASE", "M35")]["before"], 38)
        self.assertEqual(qd[("BASE", "M19")]["delta"], 4)                           # net fabric grows as the opening narrows
        self.assertEqual(qd[("BASE", "M05")]["delta"] if ("BASE", "M05") in qd else 0, 0)   # continuous top rail unchanged
        self.assertEqual(s["last_change"]["changes"][0]["before"], 12.0)
        # re-authorize: acceptance, then labor again
        accept(s, by="Test Approver", note="accept G2 = 10 ft")
        self.assertEqual(s["status"], wf.LABOR_REVIEW)
        labor(s)
        self.assertEqual(s["status"], wf.READY)
        self.assertNotEqual(s["proposal_digest"], old_digest)
        new_prices = {l["item_id"]: l["unit_price"] for l in s["estimate"]["scenarios"]["BASE"]["materials"]["lines"]}
        for k, v in new_prices.items():
            self.assertEqual(v, old_prices[k], k)                                   # human-controlled prices did not move
        self.assertEqual(s["estimate"]["ratebook_ref"], old_est["ratebook_ref"])

    def test_cost_diff_is_reported_when_both_versions_were_priced(self):
        s = ready()
        before = s["estimate"]["scenarios"]["BASE"]["price_total"]
        g2 = sf.fact(10.0, unit="ft", doc="ADD03", page=1, sheet="ADD-03", rev=3)
        wf.revise_scope(s, [{"path": "/gates/1/clear_width_ft", "fact": g2}], source={"doc_id": "ADD03", "doc_revision": 3, "sha256": SHA3}, by="intake", note="x")
        accept(s, by="Test Approver", note="ok")
        before_snapshot = [h for h in s["history"] if h["kind"] == "scope_revision"][-1]["snapshot"]
        labor(s)
        from pricing import compare
        d = compare.diff(before_snapshot, wf._snapshot(s))
        cost = d["costs"]["BASE"]["price_total"]
        self.assertEqual(cost["before"], before)
        self.assertEqual(cost["after"], s["estimate"]["scenarios"]["BASE"]["price_total"])
        self.assertNotEqual(cost["delta"], 0)
        self.assertFalse(d["ratebook_changed"])
        self.assertTrue(any(l["item_id"] == "M21" for l in d["material_lines"]))

    def test_addendum_after_release_supersedes_the_released_artifact_without_editing_it(self):
        s = ready()
        digest = s["proposal_digest"]
        pkg = wf.release(s, "Test Approver", 2, digest)
        frozen = copy.deepcopy(pkg)
        g2 = sf.fact(10.0, doc="ADD03", page=1, sheet="ADD-03", rev=3)
        wf.revise_scope(s, [{"path": "/gates/1/clear_width_ft", "fact": g2}], source={"doc_id": "ADD03", "doc_revision": 3, "sha256": SHA3}, by="intake", note="x")
        self.assertNotEqual(s["status"], wf.RELEASED)
        self.assertIsNone(s["approved_by"])
        art = next(h for h in s["history"] if h["kind"] == "released_artifact")
        self.assertTrue(art["superseded"])
        self.assertEqual(art["snapshot"]["proposal_digest"], digest)
        self.assertEqual(pkg, frozen)
        self.assertIn("release_superseded", [a["event"] for a in s["audit"]])
        with self.assertRaises(wf.GateError):
            wf.release(s, "Test Approver", 2, digest)

    def test_g2_six_to_eight_foot_precedence_is_visible_in_the_evidence(self):
        s = start(sf.base_scope())
        ev = s["scope"]["gates"][1]["clear_width_ft"]["evidence"][0]
        self.assertEqual((ev["doc_id"], ev["doc_revision"]), ("ADD01", 1))
        self.assertEqual(s["doc_revision"], 1)

    def test_refused_revisions(self):
        s = start()
        fact = sf.addendum_02_facts()
        with self.assertRaises(wf.GateError):                                        # earlier than what is already applied
            wf.revise_scope(s, fact, source={"doc_id": "ADD00", "doc_revision": 1, "sha256": "1" * 64}, by="intake", note="x")
        with self.assertRaises(wf.GateError):                                        # evidence does not cite the ingested document
            wf.revise_scope(s, [{"path": "/gates/2/clear_width_ft", "fact": sf.fact(12.0, doc="OTHER", page=1, rev=2)}], source=ADD02, by="intake", note="x")
        with self.assertRaises(wf.GateError):                                        # no citation at all
            wf.revise_scope(s, [{"path": "/gates/2/clear_width_ft", "fact": {"value": 12.0, "status": "confirmed", "evidence": []}}], source=ADD02, by="intake", note="x")
        with self.assertRaises(wf.GateError):                                        # an addendum cannot un-establish a fact
            wf.revise_scope(s, [{"path": "/gates/0/clear_width_ft", "fact": sf.fact(None, "unresolved")}], source=ADD02, by="intake", note="x")
        with self.assertRaises(wf.GateError):                                        # a model/ingester cannot mark something human-resolved
            wf.revise_scope(s, [{"path": "/gates/2/clear_width_ft", "fact": dict(sf.fact(12.0, doc="ADD02", page=1, rev=2), status="human_resolved")}], source=ADD02, by="intake", note="x")
        with self.assertRaises(wf.GateError):                                        # invalid value
            wf.revise_scope(s, [{"path": "/gates/2/clear_width_ft", "fact": sf.fact(-3.0, doc="ADD02", page=1, rev=2)}], source=ADD02, by="intake", note="x")
        with self.assertRaises(wf.GateError):                                        # not a fact path
            wf.revise_scope(s, [{"path": "/gates/2/quantity", "fact": sf.fact(2, doc="ADD02", page=1, rev=2)}], source=ADD02, by="intake", note="x")
        with self.assertRaises(wf.GateError):                                        # blank actor
            wf.revise_scope(s, fact, source=ADD02, by=" ", note="x")
        with self.assertRaises(wf.GateError):                                        # malformed source
            wf.revise_scope(s, fact, source={"doc_id": "ADD02", "doc_revision": 2}, by="intake", note="x")
        self.assertEqual(s["scope"]["scope_version"], 1)                              # every refusal left state untouched

    def test_duplicate_and_contradictory_revisions(self):
        s = start()
        wf.revise_scope(s, sf.addendum_02_facts(), source=ADD02, by="intake", note="x")
        with self.assertRaises(wf.GateError):
            wf.revise_scope(s, sf.addendum_02_facts(), source=ADD02, by="intake", note="again")          # duplicate document
        with self.assertRaises(wf.GateError):                                                            # same revision, different content
            wf.revise_scope(s, sf.addendum_02_facts(14.0), source={"doc_id": "ADD02B", "doc_revision": 2, "sha256": "9" * 64}, by="intake", note="x")
        self.assertEqual(s["scope"]["gates"][2]["clear_width_ft"]["value"], sf.ADDENDUM_02_TEST_WIDTH_FT)

    def test_new_fact_can_be_added_under_global_requirements_only(self):
        s = start(sf.with_g3())
        f = sf.fact("yes", doc="ADD03", page=1, rev=3)
        wf.revise_scope(s, [{"path": "/global_requirements/core_drilling_required", "fact": f}],
                        source={"doc_id": "ADD03", "doc_revision": 3, "sha256": SHA3}, by="intake", note="x")
        with self.assertRaises(wf.GateError):
            wf.revise_scope(s, [{"path": "/fence_runs/0/new_thing", "fact": sf.fact(1.0, doc="ADD04", page=1, rev=4)}],
                            source={"doc_id": "ADD04", "doc_revision": 4, "sha256": "4" * 64}, by="intake", note="x")

    def test_acceptance_is_bound_to_the_current_scope_version(self):
        s = start()
        wf.revise_scope(s, sf.addendum_02_facts(), source=ADD02, by="intake", note="x")
        with self.assertRaises(wf.GateError):
            wf.accept_addendum(s, by="Test Approver", note="ok", scope_version=1)
        with self.assertRaises(wf.GateError):
            wf.accept_addendum(s, by="", note="ok", scope_version=2)


class RateBookChanges(unittest.TestCase):
    def newer(self, version="1.1.0", **price):
        def f(spec):
            xb.row(spec, "Meta", "key", "version")["value"] = version
            for k, v in price.items():
                xb.row(spec, "Materials", "item_id", k)["unit_price"] = v
        return H.book(f)

    def test_price_only_change_keeps_labor_but_kills_the_old_release_digest(self):
        s = ready()
        digest, price = s["proposal_digest"], s["estimate"]["price_total"]
        wf.attach_ratebook(s, self.newer(M05=9.0), by="Test Approver", note="vendor price update")
        self.assertEqual(s["status"], wf.READY)                                      # labor basis untouched by a materials price
        self.assertNotEqual(s["proposal_digest"], digest)
        self.assertGreater(s["estimate"]["price_total"], price)
        self.assertEqual(s["ratebook_ref"]["version"], "1.1.0")
        with self.assertRaises(wf.GateError):
            wf.release(s, "Test Approver", 2, digest)                               # approval of the previous rate version is dead
        d = s["last_change"]["diff"]
        self.assertTrue(d["ratebook_changed"])
        self.assertTrue(any(l["item_id"] == "M05" for l in d["material_lines"]))
        self.assertEqual(s["history"][-1]["snapshot"]["estimate"]["price_total"], price)

    def test_labor_input_change_invalidates_the_labor_decision(self):
        s = ready()
        b = H.book(lambda sp: (xb.row(sp, "Meta", "key", "version").update(value="1.1.0"), xb.row(sp, "Roles", "role_key", "R2").update(base_wage_per_hr=30)))
        wf.attach_ratebook(s, b, by="Test Approver", note="wage update")
        self.assertEqual(s["status"], wf.LABOR_REVIEW)
        self.assertEqual(s["labor_review"]["status"], "unresolved")
        self.assertIn("labor_invalidated", [a["event"] for a in s["audit"]])
        labor(s)
        self.assertEqual(s["status"], wf.READY)

    def test_rate_book_change_after_release_supersedes_it(self):
        s = ready()
        wf.release(s, "Test Approver", 2, s["proposal_digest"])
        wf.attach_ratebook(s, self.newer(M05=9.0), by="Test Approver", note="vendor price update")
        self.assertEqual(s["status"], wf.READY)
        self.assertTrue(any(h["kind"] == "released_artifact" and h["superseded"] for h in s["history"]))
        self.assertIsNone(s["approved_by"])

    def test_stale_reused_and_duplicate_rate_books_are_refused(self):
        s = ready(book=self.newer("1.2.0"))
        with self.assertRaises(wf.GateError) as cm:
            wf.attach_ratebook(s, self.newer("1.1.0"), by="Test Approver", note="old")
        self.assertIn("STALE_RATEBOOK_VERSION", str(cm.exception))
        with self.assertRaises(wf.GateError) as cm:
            wf.attach_ratebook(s, self.newer("1.2.0", M05=7.0), by="Test Approver", note="same version, new rates")
        self.assertIn("VERSION_REUSE", str(cm.exception))
        with self.assertRaises(wf.GateError):
            wf.attach_ratebook(s, self.newer("1.2.0"), by="Test Approver", note="identical")
        with self.assertRaises(wf.GateError):
            wf.attach_ratebook(s, self.newer("1.3.0"), by="", note="no name")
        self.assertEqual(s["ratebook_ref"]["version"], "1.2.0")

    def test_rate_book_not_yet_effective_or_too_old_blocks_at_the_scope_gate(self):
        early = wf.start(sf.with_g3(), None, ratebook=H.book(), policy={"as_of": "2026-01-01"})
        self.assertIn("PRICING_RATEBOOK_NOT_EFFECTIVE", blocking(early))
        old = wf.start(sf.with_g3(), None, ratebook=H.book(), policy={"as_of": "2027-12-31", "max_ratebook_age_days": 90})
        self.assertIn("PRICING_RATEBOOK_STALE", blocking(old))
        self.assertIsNone(old["estimate"])

    def test_attached_rate_book_must_validate(self):
        s = start()
        bad = copy.deepcopy(H.book())
        bad["materials"][0]["unit_price"] = -5
        with self.assertRaises(wf.GateError):
            wf.attach_ratebook(s, bad, by="Test Approver", note="x")

    def test_missing_rate_is_a_scope_gate_blocker_not_a_zero(self):
        b = H.book(lambda sp: sp["Materials"].update(rows=[r for r in sp["Materials"]["rows"] if r["item_id"] != "M38"]))
        s = start(sf.with_g3(), b)
        self.assertIn("PRICING_MISSING_MATERIAL_RATE", blocking(s))
        ex = next(e for e in s["exceptions"] if e["code"] == "PRICING_MISSING_MATERIAL_RATE")
        self.assertIn("M38", ex["question"])
        self.assertEqual(s["status"], wf.SCOPE_REVIEW)
        self.assertIsNone(s["estimate"])
        s2 = wf.attach_ratebook(s, H.book(lambda sp: xb.row(sp, "Meta", "key", "version").update(value="1.1.0")), by="Test Approver", note="complete book")
        self.assertNotIn("PRICING_MISSING_MATERIAL_RATE", blocking(s2))


class ScopeGateRules(unittest.TestCase):
    def test_inferred_fact_blocks_until_a_named_human_approves_it(self):
        sc = sf.with_g3()
        sc["fence_runs"][1]["length_lf"] = sf.fact(150.0, "inferred")
        s = start(sc)
        self.assertIn("INFERRED_FACT_UNAPPROVED", blocking(s))
        self.assertIsNone(s["takeoff"])
        wf.resolve(s, *opt(s, "INFERRED_FACT_UNAPPROVED", "approve_inferred"), by="Pat Estimator", note="scaled from C101, checked")
        self.assertEqual(s["scope"]["fence_runs"][1]["length_lf"]["status"], "human_resolved")
        self.assertNotIn("INFERRED_FACT_UNAPPROVED", blocking(s))
        m20 = next(i for i in s["quantities"]["BASE"]["items"] if i.get("item_id") == "M20")
        self.assertEqual([r["by"] for r in m20["approved_resolutions"]], ["Pat Estimator"])
        self.assertIn("inferred_value_approved", {q["type"] for q in wf.qualifications(s)})

    def test_catalog_gap_is_a_blocker(self):
        sc = sf.with_g3()
        sc["accessories"].append({"accessory_id": "AC-BOLLARD", "kind": "bollard", "length_lf": sf.fact(100.0), "height_ft": sf.fact(2.0)})
        s = start(sc)
        self.assertIn("NO_PRICING_MAPPING", blocking(s))

    def test_facts_the_extractor_omitted_become_unresolved_questions_a_named_human_can_answer(self):
        sc = sf.with_g3()
        del sc["global_requirements"]["footing_terminal_depth_in"]
        del sc["global_requirements"]["top_rail_continuous_across_gate_openings"]
        s = start(sc)
        self.assertEqual(blocking(s), {"MISSING_VALUE"})
        self.assertEqual(s["scope"]["global_requirements"]["footing_terminal_depth_in"], {"value": None, "status": "unresolved", "evidence": []})
        self.assertEqual(s["audit"][0]["unresolved_placeholders_added"], ["top_rail_continuous_across_gate_openings", "footing_terminal_depth_in"])
        ids = {e["affects"][0]: e["exception_id"] for e in s["exceptions"]}
        with self.assertRaises(wf.GateError):                                             # validation of what a person types
            wf.resolve(s, ids["/global_requirements/footing_terminal_depth_in"], value=-42, by="Pat Estimator", note="spec 32 31 13")
        with self.assertRaises(wf.GateError):
            wf.resolve(s, ids["/global_requirements/top_rail_continuous_across_gate_openings"], value="maybe", by="Pat Estimator", note="x")
        wf.resolve(s, ids["/global_requirements/footing_terminal_depth_in"], value=42, by="Pat Estimator", note="spec 32 31 13 footing depth")
        wf.resolve(s, ids["/global_requirements/top_rail_continuous_across_gate_openings"], value="yes", by="Pat Estimator", note="note on F501")
        self.assertNotIn("MISSING_VALUE", blocking(s))
        m40 = next(i for i in s["quantities"]["BASE"]["items"] if i.get("item_id") == "M40")
        self.assertEqual(m40["status"], "confirmed")
        self.assertEqual({r["by"] for r in m40["approved_resolutions"]}, {"Pat Estimator"})
        self.assertIn("human_scope_assumption", {q["type"] for q in wf.qualifications(s)})

    def test_extractor_values_are_never_overwritten_by_placeholders(self):
        s = start(sf.with_g3())
        self.assertEqual(s["scope"]["global_requirements"]["footing_terminal_depth_in"]["value"], 42.0)
        self.assertEqual(s["audit"][0]["unresolved_placeholders_added"], [])

    def test_ruleset_approval_needs_the_exact_digest_and_a_name(self):
        s = start(sf.with_g3())
        with self.assertRaises(wf.GateError):
            wf.approve_quantity_ruleset(s, by="Pat Estimator", note="ok", ruleset_sha256="0" * 64)
        with self.assertRaises(wf.GateError):
            wf.approve_quantity_ruleset(s, by="", note="ok", ruleset_sha256=s["ruleset"]["sha256"])
        wf.approve_quantity_ruleset(s, by="Pat Estimator", note="ok", ruleset_sha256=s["ruleset"]["sha256"])
        self.assertNotIn("QUANTITY_RULESET_UNAPPROVED", blocking(s))

    def test_changed_ruleset_voids_its_approval(self):
        s = start(sf.with_g3())
        wf.approve_quantity_ruleset(s, by="Pat Estimator", note="ok", ruleset_sha256=s["ruleset"]["sha256"])
        s["ruleset"]["sha256"] = "e" * 64
        wf._advance(s)
        self.assertIn("QUANTITY_RULESET_UNAPPROVED", blocking(s))
        self.assertIn("ruleset_approval_invalidated", [a["event"] for a in s["audit"]])

    def test_qualified_assumption_still_works_for_private_work(self):
        s = start(sf.with_g3())
        approve_rules(s)
        with self.assertRaises(wf.GateError):
            labor(s, loaded_hourly_rate=40.0)                                        # cannot override the rate book's wages
        labor(s, decision="human_assumption_with_qualification", qualification="crew mix assumed from last job", source_refs=[], certified_payroll="unknown")
        self.assertTrue(s["labor_review"]["provisional"])
        self.assertIn("labor_assumption", {q["type"] for q in wf.qualifications(s)})

    def test_labor_gate_needs_the_scope_gate_first(self):
        s = start(sf.with_g3())
        with self.assertRaises(wf.GateError):
            labor(s)


class Containment(unittest.TestCase):
    def test_summary_does_not_expose_the_rate_book(self):
        s = ready()
        out = server.summary("p1", s)
        text = json.dumps(out)
        self.assertNotIn("ratebook", set(out))
        self.assertNotIn(s["ratebook"]["hashes"]["file_sha256"], text)
        for m in s["ratebook"]["materials"][:5]:
            self.assertNotIn(m["spec"], text) if m["spec"] else None
        self.assertEqual(out["status"], wf.READY)

    def test_legacy_mode_is_unchanged(self):
        with open("config/rates.example.json") as fh:
            rates = json.load(fh)
        s = wf.start(sf.with_g3(), rates)
        self.assertNotIn("INFERRED_FACT_UNAPPROVED", blocking(s))
        self.assertNotIn("quantities", s)


class ReviewRegressions(unittest.TestCase):
    """Defects an independent reviewer reproduced; each was a real bypass, corruption or crash."""

    def test_labor_cannot_be_decided_while_the_scope_gate_has_blockers_even_under_hold(self):
        s = start()
        wf.revise_scope(s, sf.addendum_02_facts(), source=ADD02, by="intake", note="x")
        wf.hold(s, by="Pat Estimator", reason="RFI to owner")
        with self.assertRaises(wf.GateError):
            labor(s)
        self.assertEqual(s["labor_review"]["status"], "unresolved")

    def test_legacy_mode_cannot_take_addenda_so_acceptance_cannot_be_skipped(self):
        with open("config/rates.example.json") as fh:
            rates = json.load(fh)
        s = wf.start(sf.with_g3(), rates)
        with self.assertRaises(wf.GateError):
            wf.revise_scope(s, sf.addendum_02_facts(), source={"doc_id": "ADD03", "doc_revision": 3, "sha256": SHA3}, by="intake", note="x")

    def test_a_crash_midway_leaves_state_untouched(self):
        s = ready()
        wf.release(s, "Test Approver", 2, s["proposal_digest"])
        before = copy.deepcopy(s)
        s["policy"]["max_ratebook_age_days"] = "x"                      # corrupted after start: _advance will crash
        before["policy"] = copy.deepcopy(s["policy"])
        newer = H.book(lambda sp: (xb.row(sp, "Meta", "key", "version").update(value="1.1.0"), xb.row(sp, "Materials", "item_id", "M05").update(unit_price=9)))
        with self.assertRaises(TypeError):
            wf.attach_ratebook(s, newer, by="Test Approver", note="x")
        self.assertEqual(s, before)                                      # not superseded, not swapped, no history
        g2 = sf.fact(10.0, doc="ADD03", page=1, sheet="ADD-03", rev=3)
        with self.assertRaises(TypeError):
            wf.revise_scope(s, [{"path": "/gates/1/clear_width_ft", "fact": g2}], source={"doc_id": "ADD03", "doc_revision": 3, "sha256": SHA3}, by="i", note="x")
        self.assertEqual(s, before)

    def test_malformed_policy_is_refused_at_start(self):
        for bad in ("x", {"as_of": "garbage"}, {"as_of": 123}, {"max_ratebook_age_days": "x"}, {"max_ratebook_age_days": float("nan")},
                    {"max_ratebook_age_days": -1}, {"max_ratebook_age_days": True}):
            with self.assertRaises(wf.GateError, msg=repr(bad)):
                wf.start(sf.base_scope(), None, ratebook=H.book(), policy=bad)

    def test_pending_acceptance_survives_a_scope_bump_from_another_resolution(self):
        s = ready()
        g2 = sf.fact(10.0, doc="ADD03", page=1, sheet="ADD-03", rev=3)
        wf.revise_scope(s, [{"path": "/gates/1/clear_width_ft", "fact": g2}], source={"doc_id": "ADD03", "doc_revision": 3, "sha256": SHA3}, by="i", note="x")
        wf.revise_scope(s, [{"path": "/fence_runs/1/length_lf", "fact": sf.fact(150.0, "inferred", doc="ADD04", page=1, rev=4)}],
                        source={"doc_id": "ADD04", "doc_revision": 4, "sha256": "4" * 64}, by="i", note="x")
        wf.resolve(s, *opt(s, "INFERRED_FACT_UNAPPROVED", "approve_inferred"), by="Pat Estimator", note="checked")
        accept(s, by="Test Approver", note="accepted")      # no longer deadlocked
        self.assertEqual(s["status"], wf.LABOR_REVIEW)

    def test_released_package_cannot_alias_or_tamper_with_history(self):
        s = ready()
        pkg = wf.release(s, "Test Approver", 2, s["proposal_digest"])
        original = pkg["estimate"]["price_total"]
        pkg["estimate"]["price_total"] = 1.0
        pkg["ratebook_ref"]["version"] = "9.9.9"
        g2 = sf.fact(10.0, doc="ADD03", page=1, sheet="ADD-03", rev=3)
        wf.revise_scope(s, [{"path": "/gates/1/clear_width_ft", "fact": g2}], source={"doc_id": "ADD03", "doc_revision": 3, "sha256": SHA3}, by="i", note="x")
        art = next(h for h in s["history"] if h["kind"] == "released_artifact")["snapshot"]
        self.assertEqual(art["estimate"]["price_total"], original)
        self.assertNotEqual(s["ratebook_ref"]["version"], "9.9.9")

    def test_overridden_human_decision_is_flagged_and_no_longer_claimed(self):
        sc = sf.with_g3()
        sc["gates"][1]["clear_width_ft"] = sf.fact(None, "unresolved")
        s = start(sc)
        ex = next(e for e in s["exceptions"] if e["affects"] == ["/gates/1/clear_width_ft"])
        wf.resolve(s, ex["exception_id"], value=8.0, by="Pat Estimator", note="scaled from plan")
        self.assertIn("human_scope_assumption", {q["type"] for q in wf.qualifications(s)})
        f = sf.fact(10.0, doc="ADD03", page=1, sheet="ADD-03", rev=3)
        wf.revise_scope(s, [{"path": "/gates/1/clear_width_ft", "fact": f}], source={"doc_id": "ADD03", "doc_revision": 3, "sha256": SHA3}, by="i", note="x")
        self.assertIn("OVERRIDES A HUMAN DECISION", s["pending_acceptance"]["summary"])
        self.assertNotIn("human_scope_assumption", {q["type"] for q in wf.qualifications(s)})

    def test_labor_record_names_the_book_now_in_force_after_a_price_only_swap(self):
        s = ready()
        newer = H.book(lambda sp: (xb.row(sp, "Meta", "key", "version").update(value="1.1.0"), xb.row(sp, "Materials", "item_id", "M05").update(unit_price=9)))
        wf.attach_ratebook(s, newer, by="Test Approver", note="x")
        self.assertEqual(s["labor_review"]["ratebook_ref"]["version"], "1.1.0")
        self.assertIn("v1.1.0", s["labor_review"]["rate_source"])

    def test_malformed_update_entries_are_refused(self):
        s = start()
        for bad in (["str"], [[1]], [None]):
            with self.assertRaises(wf.GateError):
                wf.revise_scope(s, bad, source=ADD02, by="i", note="x")


class PrevailingWageAndProduction(unittest.TestCase):
    def test_typed_decisions_cannot_be_given_through_generic_resolution(self):
        s = start()
        wf.revise_scope(s, sf.addendum_02_facts(), source=ADD02, by="intake", note="x")
        for code in ("QUANTITY_RULESET_UNAPPROVED", "ADDENDUM_ACCEPTANCE_REQUIRED"):
            ex = next(e for e in s["exceptions"] if e["code"] == code)
            self.assertEqual(ex["candidate_resolutions"], [])
            self.assertIn("type", ex["required_decision"])
            with self.assertRaises(wf.GateError):
                wf.resolve(s, ex["exception_id"], value="yes", by="Test Approver", note="x")

    def test_production_policy_refuses_a_draft_ruleset_even_with_a_named_approval(self):
        s = wf.start(sf.with_g3(), None, ratebook=H.book(), policy=dict(POLICY, production=True))
        self.assertEqual(s["ruleset"]["rules"]["status"], "draft_pending_estimator_review")
        approve_rules(s)
        self.assertIn("QUANTITY_RULESET_UNAPPROVED", blocking(s))
        self.assertIsNone(s["estimate"])
        s["ruleset"]["rules"]["status"] = "approved"                  # what an estimator's edit of the file looks like after re-approval
        wf._advance(s)
        self.assertNotIn("QUANTITY_RULESET_UNAPPROVED", blocking(s))

    def test_shipped_ruleset_is_a_draft(self):
        from pricing import quantities
        self.assertEqual(quantities.load_ruleset()["rules"]["status"], "draft_pending_estimator_review")


# --- Davis-Bacon inputs. All values are the FICTIONAL demonstration decision FDB-DP001 (Section 00 0800 Attachment A) or invented test values.
SCHEDULE = [dict(classification="Laborer, common or general", base_rate=24.50, fringe_rate=9.10),
            dict(classification="Power equipment operator, skid steer", base_rate=29.80, fringe_rate=11.25),
            dict(classification="Cement mason, concrete finisher", base_rate=28.40, fringe_rate=10.70)]
LAB, OPR = SCHEDULE[0], SCHEDULE[1]


def row(role, cls=LAB, status="listed", **kw):
    r = dict(role_key=role, classification=cls["classification"], classification_status=status, base_rate=cls["base_rate"],
             fringe_rate=cls["fringe_rate"], source_ref="FDB-DP001 mod 0 Att. A")
    r.update(kw)
    return r


def good_rows():       # a named human maps foreman, installer and laborer to the listed Laborer class and the operator to the skid-steer class
    return [row("R1"), row("R2"), row("R3"), row("R4", OPR)]


def wage_args(**over):
    a = dict(by="Lee Reviewer", note="classifications assigned from FDB-DP001 mod 0",
             determination=dict(decision_id="FDB-DP001", modification="0", date="2026-10-05", valid_through="2026-12-31", source_ref="Section 00 0800 Att. A"),
             schedule=copy.deepcopy(SCHEDULE), rows=good_rows(), employer_burden=dict(pct=0.20, source_ref="payroll cost sheet (fictional test value)"),
             production_rates_approved=True,
             certified_payroll_admin=dict(basis="per_week", unit_cost=85.0, weeks=4, source_ref="payroll administrator quote (fictional test value)"))
    a.update(over)
    return a


def davis_bacon_scope():
    return sf.dp001_requirements(sf.with_g3())


def wage_ready():
    s = start(davis_bacon_scope())
    approve_rules(s)
    assert s["status"] == wf.LABOR_REVIEW, (s["status"], blocking(s))
    return s


def codes_of(s):
    return {e["code"] for e in s["exceptions"] if e["severity"] == "blocking"}


class DavisBaconLaborGate(unittest.TestCase):
    """Prevailing wage reaches the Labor Gate, and a fully human-verified determination legitimately passes it and prices."""

    def test_project_enters_the_labor_gate_and_asks_for_a_wage_determination(self):
        s = wage_ready()
        self.assertEqual(blocking(s), {"WAGE_DETERMINATION_REQUIRED"})
        ex = next(e for e in s["exceptions"] if e["code"] == "WAGE_DETERMINATION_REQUIRED")
        self.assertEqual(ex["required_decision"], {"type": "wage_determination", "roles": ["R1", "R2", "R3", "R4"]})
        self.assertIsNotNone(s["takeoff"])
        self.assertIsNone(s["estimate"])

    def test_FULLY_CALCULATED_DAVIS_BACON_SCENARIO_passes_the_labor_gate_and_releases(self):
        s = wage_ready()
        wf.record_wage_determination(s, **wage_args())
        self.assertEqual(blocking(s), set())
        self.assertEqual(s["status"], wf.READY)
        lr = s["labor_review"]
        self.assertEqual((lr["status"], lr["wage_basis"], lr["decided_by"], lr["provisional"]), ("decided", "prevailing_wage", "Lee Reviewer", False))
        est = s["estimate"]["scenarios"]["BASE"]
        lab = est["labor"]
        self.assertEqual(lab["basis"], "prevailing_wage")

        # independent first-principles recomputation of every labor figure
        E = lambda x: Decimal(repr(x))
        cent = lambda x: x.quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")
        qty = {i["driver_key"]: E(i["quantity"]) for i in s["quantities"]["BASE"]["items"] if "driver_key" in i}
        book = s["ratebook"]
        wage = {"R1": E(24.50), "R2": E(24.50), "R3": E(24.50), "R4": E(29.80)}
        fringe = {"R1": E(9.10), "R2": E(9.10), "R3": E(9.10), "R4": E(11.25)}
        burden = E(0.20)
        want = {"wages": Decimal(0), "fringe": Decimal(0), "employer_costs": Decimal(0)}
        hours_total = Decimal(0)
        ext_want = Decimal(0)
        for t in book["labor_tasks"]:
            crew = next(c for c in book["crews"] if c["crew_id"] == t["crew_id"])["members"]
            hours = qty[t["driver_key"]] / E(t["production_rate"])
            hours_total += hours
            parts = {"wages": sum(wage[r] * n for r, n in crew.items()), "fringe": sum(fringe[r] * n for r, n in crew.items()),
                     "employer_costs": sum(wage[r] * burden * n for r, n in crew.items())}
            for k in want:
                want[k] += cent(hours * parts[k])
            line = next(l for l in lab["lines"] if l["task_id"] == t["task_id"])
            once = cent(hours * (parts["wages"] + parts["fringe"] + parts["employer_costs"]))           # owner decision 2026-10-16 3:28 PM: ONE rounding per task
            ext_want += once
            self.assertEqual(E(line["extended"]), once, t["task_id"])
            self.assertLessEqual(abs(E(line["wages"]) + E(line["fringe"]) + E(line["employer_costs"]) - E(line["extended"])), Decimal("0.02"), t["task_id"])   # components are supporting detail
        self.assertEqual({k: E(v) for k, v in lab["components"].items()}, want)
        self.assertEqual(E(lab["subtotal"]), ext_want)
        self.assertIn("rounded ONCE", lab["components_note"])
        self.assertEqual(E(lab["certified_payroll_admin"]["extended"]), Decimal("340.00"))      # 4 weeks x $85.00, human-owned
        self.assertGreater(want["fringe"], 0)                                                       # fringe is a distinct, non-zero obligation
        self.assertEqual(E(lab["subtotal"]) + E(340), E(lab["subtotal"]) + E(lab["certified_payroll_admin"]["extended"]))

        # direct cost foots across every distinct component, then the markups apply to it
        mats = E(est["materials"]["subtotal"])
        direct = mats + E(est["sales_tax"]["amount"]) + E(est["services"]["subtotal"]) + E(lab["subtotal"]) + Decimal("340.00") \
            + E(est["equipment"]["subtotal"]) + E(est["mobilization"]["subtotal"])
        self.assertEqual(E(est["direct_cost"]), direct)
        # owner sales-tax exemption (SC-3.6.1): incorporated materials exempt, nothing else touched
        self.assertEqual((est["sales_tax"]["exemption_applies"], est["sales_tax"]["amount"], est["sales_tax"]["taxable_base"]), (True, 0, 0))
        self.assertEqual(E(est["sales_tax"]["exempt_base"]), mats)
        self.assertTrue(all(l["tax_exempt"] for l in est["materials"]["lines"]))
        # first-class DP-001 items priced with their own units
        self.assertEqual({l["item_id"]: l["uom"] for l in est["materials"]["lines"] if l["item_id"] in ("M42", "M43", "M44")}, {"M42": "LF", "M43": "EA", "M44": "EA"})
        core = est["services"]["lines"][0]
        self.assertEqual((core["service_id"], core["uom"], core["quantity"]), ("S01", "EA", 12 + 29 + 2 + 14))
        self.assertEqual(E(core["extended"]), E(core["quantity"]) * E(core["unit_cost"]))
        types = {q["type"] for q in est["qualifications"]}
        self.assertTrue({"owner_sales_tax_exemption", "prevailing_wage_basis"} <= types)
        # compliant labor costs more than the company-rate basis would have
        co = start(sf.with_g3())
        approve_rules(co)
        labor(co)
        company = co["estimate"]["scenarios"]["BASE"]["labor"]["subtotal"]
        self.assertGreater(lab["subtotal"], company)

        # the Release Gate binds this exact wage determination
        digest = s["proposal_digest"]
        pkg = wf.release(s, "Test Approver", s["scope"]["scope_version"], digest)
        self.assertEqual(pkg["labor_review"]["wage_determination"]["determination"]["decision_id"], "FDB-DP001")
        self.assertEqual(s["status"], wf.RELEASED)

    def test_no_company_rate_decision_or_generic_assumption_clears_it(self):
        s = wage_ready()
        for kw in (dict(), dict(decision="human_assumption_with_qualification", qualification="company crew", source_refs=[], certified_payroll="unknown"),
                   dict(decision="verified_federal", classifications=["laborer"], loaded_hourly_rate=55.0, certified_payroll=True)):
            with self.assertRaises(wf.GateError) as cm:
                labor(s, **kw)
            self.assertIn("record_wage_determination", str(cm.exception))
        self.assertEqual(s["labor_review"]["status"], "unresolved")
        self.assertIsNone(s["estimate"])

    def test_certified_payroll_flag_alone_also_refuses_company_rates(self):
        s = start(sf.with_g3())
        approve_rules(s)
        with self.assertRaises(wf.GateError):
            labor(s, certified_payroll=True)

    # ---- classification: assignment is a human determination; conformance only when the human says the class is not listed
    def test_a_listed_class_assigned_to_installers_needs_no_conformance(self):
        s = wage_ready()
        wf.record_wage_determination(s, **wage_args())            # no "fence erector" title exists; the human chose the listed Laborer class
        self.assertEqual(s["status"], wf.READY)

    def test_unlisted_class_proposed_for_conformance_blocks_that_role_only(self):
        s = wage_ready()
        rows = good_rows()
        rows[1] = row("R2", dict(classification="Fence erector", base_rate=27.00, fringe_rate=9.50), "proposed_for_conformance")
        wf.record_wage_determination(s, **wage_args(rows=rows))
        self.assertEqual(blocking(s), {"WAGE_CONFORMANCE_PENDING"})
        self.assertEqual(s["status"], wf.LABOR_REVIEW)
        self.assertIsNone(s["estimate"])
        part = next(e for e in s["exceptions"] if e["code"] == "WAGE_PARTIAL_RESULT")["evidence"][0]
        self.assertEqual(part["unresolved_roles"], ["R2"])
        self.assertEqual(sorted(part["roles"]), ["R1", "R3", "R4"])                       # supported roles ARE calculated
        self.assertIn("CR1", part["crews"])                                              # layout crew has no R2: fully calculable
        self.assertNotIn("CR2", part["crews"])                                           # install crew includes R2: not cleared
        t = {x["task_id"]: x for x in part["tasks"]}
        self.assertIn("wages", t["L01"])
        self.assertIn("blocked", t["L03"])
        self.assertIsNone(s["proposal_digest"])

    def test_conformance_approval_with_its_reference_clears_the_role(self):
        s = wage_ready()
        rows = good_rows()
        rows[1] = row("R2", dict(classification="Fence erector", base_rate=27.00, fringe_rate=9.50), "approved_conformance", conformance_ref="Agency conformance letter 2026-10-09")
        wf.record_wage_determination(s, **wage_args(rows=rows))
        self.assertEqual(s["status"], wf.READY)
        wf.release(s, "Test Approver", s["scope"]["scope_version"], s["proposal_digest"])

    def test_approved_conformance_without_a_reference_stays_blocked(self):
        s = wage_ready()
        rows = good_rows()
        rows[1] = row("R2", dict(classification="Fence erector", base_rate=27.00, fringe_rate=9.50), "approved_conformance")
        wf.record_wage_determination(s, **wage_args(rows=rows))
        self.assertEqual(blocking(s), {"WAGE_CONFORMANCE_REF_MISSING"})

    def test_incorrect_classification_is_caught_against_the_decisions_own_schedule(self):
        s = wage_ready()
        cases = {
            "CLASSIFICATION_NOT_IN_DECISION": row("R2", dict(classification="Fence erector", base_rate=27.0, fringe_rate=9.5), "listed"),   # claims listed; is not
            "WAGE_RATE_BELOW_DECISION": row("R4", OPR, base_rate=25.00),                                                                          # listed class, wrong base rate
            "WAGE_CLASSIFICATION_IS_LISTED": row("R3", LAB, "proposed_for_conformance"),                                                     # claims unlisted; it is listed
        }
        for code, bad in cases.items():
            rows = good_rows()
            rows[[r["role_key"] for r in rows].index(bad["role_key"])] = bad
            wf.record_wage_determination(s, **wage_args(rows=rows))
            self.assertIn(code, blocking(s), code)
            self.assertEqual(s["status"], wf.LABOR_REVIEW)
            self.assertIsNone(s["estimate"])
        rows = good_rows()
        rows[3] = row("R4", dict(classification="Cement mason, concrete finisher", base_rate=28.40, fringe_rate=10.69))                      # base meets, fringe a cent under: each is checked on its own
        wf.record_wage_determination(s, **wage_args(rows=rows))
        self.assertIn("WAGE_RATE_BELOW_DECISION", blocking(s))
        rows[3] = row("R4", dict(classification="Cement mason, concrete finisher", base_rate=28.39, fringe_rate=10.70))
        wf.record_wage_determination(s, **wage_args(rows=rows))
        self.assertIn("WAGE_RATE_BELOW_DECISION", blocking(s))

    def test_rates_at_or_above_the_decision_floor_are_accepted_and_flagged(self):
        """ITB 7.4: the decision is a floor. Foreman $32.00 / Installer $26.00 under Laborer (schedule 24.50 / 9.10) meet it."""
        from engine import integration
        s = wage_ready()
        rows = good_rows()
        rows[0] = row("R1", base_rate=32.00)
        rows[1] = row("R2", base_rate=26.00)
        wf.record_wage_determination(s, **wage_args(rows=rows))
        self.assertEqual(blocking(s), set())
        self.assertEqual(s["status"], wf.READY)
        rc = {r["role_key"]: r for r in integration.view(s)["wage"]["role_classifications"]}
        self.assertEqual([(rc[k]["classification"], rc[k]["base_rate"], rc[k]["fringe_rate"], rc[k]["above_decision"], rc[k]["decision_base_rate"], rc[k]["decision_fringe_rate"])
                          for k in ("R1", "R2")],
                         [("Laborer, common or general", 32.0, 9.1, True, 24.5, 9.1), ("Laborer, common or general", 26.0, 9.1, True, 24.5, 9.1)])
        self.assertFalse(rc["R3"]["above_decision"])                                    # exactly at the decision: accepted, not flagged
        self.assertEqual(rc["R1"]["priced"]["wages"], 32.0)                             # the recorded (higher) rate is what prices, never the schedule's
        exact = wage_ready()
        wf.record_wage_determination(exact, **wage_args(rows=good_rows()))
        self.assertGreater(s["estimate"]["price_total"], exact["estimate"]["price_total"])
        rows[0] = row("R1", fringe_rate=9.10 + 1)                                       # fringe above, base at the decision
        wf.record_wage_determination(s, **wage_args(rows=rows))
        self.assertTrue({r["role_key"]: r for r in integration.view(s)["wage"]["role_classifications"]}["R1"]["above_decision"])
        rows[0] = row("R1", base_rate=24.49, fringe_rate=20.00)                         # base below even with a high fringe: refused
        wf.record_wage_determination(s, **wage_args(rows=rows))
        self.assertIn("WAGE_RATE_BELOW_DECISION", blocking(s))

    def test_omitted_fringe_is_never_treated_as_zero(self):
        s = wage_ready()
        rows = good_rows()
        rows[0] = row("R1", fringe_rate=None)
        wf.record_wage_determination(s, **wage_args(rows=rows))
        self.assertEqual(blocking(s), {"WAGE_FRINGE_MISSING"})
        self.assertIsNone(s["estimate"])
        rows[0] = row("R1", fringe_rate=0)                     # an explicit 0 that contradicts the schedule is a mismatch, not a clearance
        wf.record_wage_determination(s, **wage_args(rows=rows))
        self.assertEqual(blocking(s), {"WAGE_RATE_BELOW_DECISION"})

    def test_missing_rate_classification_source_or_role_each_block(self):
        s = wage_ready()
        for code, mutate in (("WAGE_RATE_MISSING", lambda r: r[0].update(base_rate=None)), ("WAGE_ROLE_UNCLASSIFIED", lambda r: r[0].update(classification=" ")),
                             ("WAGE_SOURCE_MISSING", lambda r: r[0].update(source_ref="")), ("WAGE_ROLE_UNCLASSIFIED", lambda r: r.pop()),
                             ("WAGE_CLASSIFICATION_STATUS_INVALID", lambda r: r[0].update(classification_status="maybe"))):
            rows = good_rows()
            mutate(rows)
            wf.record_wage_determination(s, **wage_args(rows=rows))
            self.assertIn(code, blocking(s), code)
            self.assertIsNone(s["estimate"])

    def test_missing_approvals_and_cost_inputs_block(self):
        s = wage_ready()
        for code, kw in (("WAGE_PRODUCTION_UNAPPROVED", dict(production_rates_approved=False)),
                         ("WAGE_EMPLOYER_COST_MISSING", dict(employer_burden=None)),
                         ("WAGE_EMPLOYER_COST_MISSING", dict(employer_burden=dict(pct=0.2))),
                         ("CERTIFIED_PAYROLL_COST_MISSING", dict(certified_payroll_admin=None)),
                         ("CERTIFIED_PAYROLL_COST_MISSING", dict(certified_payroll_admin=dict(basis="lump_sum", source_ref="quote"))),
                         ("CERTIFIED_PAYROLL_COST_MISSING", dict(certified_payroll_admin=dict(basis="per_week", unit_cost=85.0, source_ref="quote"))),
                         ("CERTIFIED_PAYROLL_COST_MISSING", dict(certified_payroll_admin=dict(basis="not_charged", source_ref="x"))),
                         ("WAGE_SCHEDULE_MISSING", dict(schedule=[]))):
            wf.record_wage_determination(s, **wage_args(**kw))
            self.assertIn(code, blocking(s), (code, kw))
            self.assertIsNone(s["estimate"])

    def test_certified_payroll_cost_is_human_owned_never_invented(self):
        s = wage_ready()
        wf.record_wage_determination(s, **wage_args(certified_payroll_admin=dict(basis="not_charged", reason="absorbed in overhead per bid policy", source_ref="bid policy 7")))
        self.assertEqual(s["status"], wf.READY)
        self.assertEqual(s["estimate"]["scenarios"]["BASE"]["labor"]["certified_payroll_admin"]["extended"], 0)
        wf.record_wage_determination(s, **wage_args(certified_payroll_admin=dict(basis="lump_sum", unit_cost=500.0, source_ref="quote")))
        self.assertEqual(s["estimate"]["scenarios"]["BASE"]["labor"]["certified_payroll_admin"]["extended"], 500)
        wf.record_wage_determination(s, **wage_args(certified_payroll_admin=dict(basis="per_crew_hour", unit_cost=1.0, source_ref="quote")))
        hours = s["estimate"]["scenarios"]["BASE"]["labor"]["crew_hours"]
        self.assertEqual(s["estimate"]["scenarios"]["BASE"]["labor"]["certified_payroll_admin"]["extended"], round(hours, 2))

    # ---- decision currency
    def test_expired_and_not_yet_effective_wage_decisions_block(self):
        s = wage_ready()
        det = wage_args()["determination"]
        wf.record_wage_determination(s, **wage_args(determination=dict(det, valid_through="2026-10-01")))
        self.assertEqual(blocking(s), {"WAGE_DECISION_EXPIRED"})
        wf.record_wage_determination(s, **wage_args(determination=dict(det, date="2026-12-01")))
        self.assertEqual(blocking(s), {"WAGE_DECISION_NOT_EFFECTIVE"})
        wf.record_wage_determination(s, **wage_args())
        self.assertEqual(s["status"], wf.READY)

    def test_a_decision_that_expires_after_it_was_cleared_blocks_release(self):
        s = wage_ready()
        wf.record_wage_determination(s, **wage_args())
        digest = s["proposal_digest"]
        s["policy"]["as_of"] = "2027-01-15"                      # time passes beyond valid_through = 2026-12-31
        with self.assertRaises(wf.GateError):
            wf.release(s, "Test Approver", s["scope"]["scope_version"], digest)
        self.assertNotEqual(s["status"], wf.RELEASED)
        wf._advance(s)
        self.assertIn("WAGE_DECISION_EXPIRED", blocking(s))
        self.assertIsNone(s["estimate"])

    def test_older_wage_decision_modification_is_stale_and_a_newer_one_replaces_it(self):
        s = wage_ready()
        det = wage_args()["determination"]
        wf.record_wage_determination(s, **wage_args(determination=dict(det, modification="1")))
        d1 = s["proposal_digest"]
        before = copy.deepcopy(s)
        with self.assertRaises(wf.GateError) as cm:
            wf.record_wage_determination(s, **wage_args(determination=dict(det, modification="0")))
        self.assertIn("stale", str(cm.exception))
        self.assertEqual(s, before)
        newer = [row("R1", fringe_rate=9.25), row("R2"), row("R3"), row("R4", OPR)]
        sched = copy.deepcopy(SCHEDULE)
        sched[0]["fringe_rate"] = 9.25
        newer = [dict(r, fringe_rate=9.25) if r["classification"].startswith("Laborer") else r for r in good_rows()]
        wf.record_wage_determination(s, **wage_args(determination=dict(det, modification="2"), schedule=sched, rows=newer))
        self.assertEqual(s["status"], wf.READY)
        self.assertNotEqual(s["proposal_digest"], d1)

    def test_stale_release_digest_after_any_wage_input_changes(self):
        s = wage_ready()
        wf.record_wage_determination(s, **wage_args())
        d1 = s["proposal_digest"]
        wf.record_wage_determination(s, **wage_args(employer_burden=dict(pct=0.21, source_ref="revised payroll cost sheet")))
        self.assertNotEqual(s["proposal_digest"], d1)
        with self.assertRaises(wf.GateError):
            wf.release(s, "Test Approver", s["scope"]["scope_version"], d1)
        wf.release(s, "Test Approver", s["scope"]["scope_version"], s["proposal_digest"])

    def test_determination_is_voided_when_scope_or_labor_inputs_change(self):
        s = wage_ready()
        wf.record_wage_determination(s, **wage_args())
        g = sf.fact(12.0, doc="ADD03", page=1, sheet="ADD-03", rev=3)
        wf.revise_scope(s, [{"path": "/gates/2/clear_width_ft", "fact": g}], source={"doc_id": "ADD03", "doc_revision": 3, "sha256": SHA3}, by="intake", note="x")
        self.assertIsNone(s["wage_determination"])
        self.assertEqual(s["labor_review"]["status"], "unresolved")
        self.assertIn("wage_determination_invalidated", [a["event"] for a in s["audit"]])
        accept(s)
        self.assertEqual(blocking(s), {"WAGE_DETERMINATION_REQUIRED"})
        wf.record_wage_determination(s, **wage_args())
        newer = H.book(lambda sp: (xb.row(sp, "Meta", "key", "version").update(value="1.1.0"), xb.row(sp, "Roles", "role_key", "R2").update(base_wage_per_hr=30)))
        wf.attach_ratebook(s, newer, by="Test Approver", note="wage update")
        self.assertIsNone(s["wage_determination"])

    # ---- structure
    def test_garbage_input_is_refused_and_leaves_state_untouched(self):
        s = wage_ready()
        before = copy.deepcopy(s)
        for kw in (dict(rows="x"), dict(rows=[1]), dict(schedule="x"), dict(schedule=[{"classification": "L", "base_rate": -1, "fringe_rate": 0}]),
                   dict(rows=[dict(good_rows()[0], base_rate=-3)]), dict(rows=[dict(good_rows()[0], fringe_rate=float("nan"))]),
                   dict(employer_burden="x"), dict(certified_payroll_admin="x"), dict(by="")):
            with self.assertRaises(wf.GateError, msg=repr(kw)[:60]):
                wf.record_wage_determination(s, **wage_args(**kw))
        self.assertEqual(s, before)

    def test_an_incomplete_determination_is_stored_and_blocked_not_accepted(self):
        s = wage_ready()
        wf.record_wage_determination(s, **wage_args(determination={}))
        self.assertIn("WAGE_DETERMINATION_INCOMPLETE", blocking(s))
        self.assertIsNone(s["estimate"])
        wf.record_wage_determination(s, **wage_args(determination=dict(wage_args()["determination"], modification="one")))
        self.assertIn("WAGE_DETERMINATION_INCOMPLETE", blocking(s))

    def test_cannot_be_used_unless_the_documents_say_prevailing_wage_applies(self):
        s = start(sf.with_g3())
        approve_rules(s)
        with self.assertRaises(wf.GateError):
            wf.record_wage_determination(s, **wage_args())

    def test_the_applicability_question_is_always_asked_when_the_documents_are_silent(self):
        sc = sf.with_g3()
        del sc["global_requirements"]["prevailing_wage_required"]          # "the drawings do not establish whether prevailing wage applies"
        s = start(sc)
        self.assertIn("MISSING_VALUE", blocking(s))
        self.assertIn("/global_requirements/prevailing_wage_required", [e["affects"][0] for e in s["exceptions"]])
        with self.assertRaises(wf.GateError):
            labor(s)

    def test_a_yes_answer_still_requires_the_wage_determination(self):
        sc = sf.with_g3()
        sc["global_requirements"]["prevailing_wage_required"] = sf.fact(None, "unresolved")
        s = start(sc)
        ex = next(e for e in s["exceptions"] if e["affects"] == ["/global_requirements/prevailing_wage_required"])
        wf.resolve(s, ex["exception_id"], value="yes", by="Pat Estimator", note="SC-3.4.1 Davis-Bacon applies by contract")
        approve_rules(s)
        self.assertEqual(blocking(s), {"WAGE_DETERMINATION_REQUIRED"})


class WageEngineIndependence(unittest.TestCase):
    """The engine re-validates the wage basis itself: nobody can hand it a half-cleared record, and fringe is never double counted."""

    def labor_basis(self, book, **over):
        rec = dict(determination=wage_args()["determination"], schedule=copy.deepcopy(SCHEDULE), rows=good_rows(), employer_burden=dict(pct=0.2, source_ref="x"),
                   production_rates_approved=True, certified_payroll_admin=dict(basis="lump_sum", unit_cost=100.0, source_ref="q"))
        rec.update(over)
        return {"status": "decided", "wage_basis": "prevailing_wage", "ratebook_labor_sha256": book["hashes"]["labor_sha256"], "wage_determination": rec}

    def codes(self, basis, book):
        from pricing import engine
        return {p["code"] for p in engine.check(H.payload({"D12": 100}), book, labor_basis=basis, as_of=H.AS_OF)}

    def test_engine_blocks_every_uncleared_record_itself(self):
        book = H.book()
        self.assertEqual(self.codes(self.labor_basis(book), book), set())
        rows = good_rows(); rows[0]["fringe_rate"] = None
        self.assertEqual(self.codes(self.labor_basis(book, rows=rows), book), {"WAGE_FRINGE_MISSING"})
        rows = good_rows(); rows[1] = row("R2", dict(classification="Fence erector", base_rate=27.0, fringe_rate=9.5), "proposed_for_conformance")
        self.assertEqual(self.codes(self.labor_basis(book, rows=rows), book), {"WAGE_CONFORMANCE_PENDING"})
        self.assertEqual(self.codes(self.labor_basis(book, production_rates_approved=False), book), {"WAGE_PRODUCTION_UNAPPROVED"})
        stale = dict(self.labor_basis(book), ratebook_labor_sha256="0" * 64)
        self.assertEqual(self.codes(stale, book), {"LABOR_APPROVAL_STALE"})

    def test_rate_book_burden_is_ignored_so_fringe_and_benefits_are_not_double_counted(self):
        from pricing import engine
        a = H.book()
        b = H.book(lambda sp: [r.update({"burden_pct (taxes)": 0.9}) for r in sp["Roles"]["rows"]])      # a hugely different company burden
        self.assertNotEqual(a["roles"][0]["burden_pct"], b["roles"][0]["burden_pct"])
        pa = engine.price(H.payload({"D12": 110, "D04": 60}), a, labor_basis=self.labor_basis(a), as_of=H.AS_OF)
        pb = engine.price(H.payload({"D12": 110, "D04": 60}), b, labor_basis=self.labor_basis(b), as_of=H.AS_OF)
        self.assertEqual(pa["labor"], pb["labor"])
        # L01 = D12 110 / 11 per hr = 10 crew-hours on CR1 (R1+R3 laborers, R4 operator): wages 78.80, fringe 29.45, employer 20% of wages = 15.76
        l1 = next(l for l in pa["labor"]["lines"] if l["task_id"] == "L01")
        self.assertEqual((l1["wages"], l1["fringe"], l1["employer_costs"], l1["extended"]), (788.0, 294.5, 157.6, 1240.1))

    def test_company_rate_labor_is_unchanged(self):
        from pricing import engine
        book = H.book()
        est = engine.price(H.payload({"D12": 110}), book, labor_basis=H.labor_ok(book), as_of=H.AS_OF)
        self.assertEqual(est["labor"]["basis"], "company_rates")
        self.assertNotIn("components", est["labor"])


class OwnerSalesTaxExemption(unittest.TestCase):
    def test_exemption_covers_incorporated_materials_only(self):
        from unittest import mock
        from pricing import engine, vocab
        book = H.book()
        q = {"M05": 100, "M01": 10, "S01": 20, "D12": 50}
        taxed = engine.price(H.payload(q), book, labor_basis=H.labor_ok(book), as_of=H.AS_OF)
        p = H.payload(q)
        p["revision"]["sales_tax_exemption"] = {"applies": True, "evidence_refs": [{"fact_path": "/global_requirements/owner_sales_tax_exempt", "doc_id": "SC", "page": 3}]}
        exempt = engine.price(p, book, labor_basis=H.labor_ok(book), as_of=H.AS_OF)
        self.assertGreater(taxed["sales_tax"]["amount"], 0)
        self.assertEqual(exempt["sales_tax"]["amount"], 0)
        self.assertEqual(exempt["materials"]["subtotal"], taxed["materials"]["subtotal"])       # the exemption changes tax, never material cost
        self.assertEqual((exempt["labor"], exempt["equipment"], exempt["mobilization"], exempt["services"]),
                         (taxed["labor"], taxed["equipment"], taxed["mobilization"], taxed["services"]))
        # an item that is NOT incorporated into the Work stays taxable even under the exemption
        with mock.patch.object(vocab, "INCORPORATED", frozenset(set(vocab.MATERIALS) - {"M05"})):
            part = engine.price(p, book, labor_basis=H.labor_ok(book), as_of=H.AS_OF)
        m05 = next(l for l in part["materials"]["lines"] if l["item_id"] == "M05")
        self.assertFalse(m05["tax_exempt"])
        self.assertEqual(part["sales_tax"]["taxable_base"], m05["extended"])
        self.assertEqual(part["sales_tax"]["amount"], round(m05["extended"] * book["markups"]["tax_materials_pct"], 2))
        self.assertTrue(all(l["tax_exempt"] for l in part["materials"]["lines"] if l["item_id"] != "M05"))

    def test_exemption_qualification_prints_the_cited_section_and_all_materials_are_exempt(self):
        from pricing import engine, vocab
        book = H.book()
        q = {k: 1 for k in ("M01", "M05", "M38", "M42")}
        p = H.payload(q)
        ref = {"fact_path": "/global_requirements/owner_sales_tax_exempt", "doc_id": "dp001_project_manual_ansi_b_pkg", "doc_revision": 0, "page": 6, "sheet_label": "00 0800 SC-3.6.1"}
        p["revision"]["sales_tax_exemption"] = {"applies": True, "evidence_refs": [ref]}
        est = engine.price(p, book, labor_basis=H.labor_ok(book), as_of=H.AS_OF)
        note = next(x["note"] for x in est["qualifications"] if x["type"] == "owner_sales_tax_exemption")
        self.assertIn("00 0800 SC-3.6.1", note)
        self.assertIn("page 6", note)
        self.assertEqual(est["sales_tax"]["amount"], 0)
        self.assertTrue(all(l["tax_exempt"] for l in est["materials"]["lines"]))
        self.assertEqual(book["markups"]["tax_materials_pct"], 0.07)      # the pinned workbook rate is untouched; 0% comes from the exemption

    def test_exemption_without_a_document_citation_is_refused(self):
        from pricing import engine
        book = H.book()
        p = H.payload({"M05": 10})
        p["revision"]["sales_tax_exemption"] = {"applies": True, "evidence_refs": []}
        self.assertEqual({x["code"] for x in engine.check(p, book, labor_basis=H.labor_ok(book), as_of=H.AS_OF)}, {"TAX_EXEMPTION_UNSUPPORTED"})

    def test_services_are_never_taxed_or_exempted(self):
        from pricing import engine
        book = H.book()
        est = engine.price(H.payload({"S01": 10, "D12": 10}), book, labor_basis=H.labor_ok(book), as_of=H.AS_OF)
        self.assertEqual(est["services"]["subtotal"], 400)             # 10 holes x $40 (test book)
        self.assertEqual(est["sales_tax"]["taxable_base"], 0)


class SessionClassPolicy(unittest.TestCase):
    def test_public_demo_session_accepts_fictional_books_only(self):
        demo = dict(POLICY, allowed_ratebook_classes=["FICTIONAL_DEMO"])
        wf.start(sf.base_scope(), None, ratebook=H.book(), policy=demo)
        private = H.book(lambda sp: xb.row(sp, "Meta", "key", "data_classification").update(value="COMPANY_PRIVATE"))
        with self.assertRaises(wf.GateError):
            wf.start(sf.base_scope(), None, ratebook=private, policy=demo)
        s = wf.start(sf.base_scope(), None, ratebook=H.book(), policy=demo)
        newer = H.book(lambda sp: (xb.row(sp, "Meta", "key", "version").update(value="1.1.0"), xb.row(sp, "Meta", "key", "data_classification").update(value="COMPANY_PRIVATE")))
        with self.assertRaises(wf.GateError):
            wf.attach_ratebook(s, newer, by="Test Approver", note="x")
        self.assertEqual(s["ratebook_ref"]["version"], "1.0.0")
        with self.assertRaises(wf.GateError):
            wf.start(sf.base_scope(), None, ratebook=H.book(), policy=dict(POLICY, allowed_ratebook_classes=["SECRET"]))


class Dp001ShapedRequirements(unittest.TestCase):
    """The requirements the authoritative package states are now priced as first-class items; anything the catalog still cannot price blocks."""

    def test_fence_guard_core_drilling_drop_rod_and_tax_exemption_no_longer_block_and_are_priced_separately(self):
        sc = sf.dp001_requirements(sf.with_g3())
        sc["global_requirements"]["prevailing_wage_required"] = sf.fact("no")
        s = start(sc)
        self.assertNotIn("NO_PRICING_MAPPING", blocking(s))
        approve_rules(s)
        labor(s)
        self.assertEqual(s["status"], wf.READY)
        est = s["estimate"]["scenarios"]["BASE"]
        by = {l["item_id"]: l for l in est["materials"]["lines"]}
        self.assertEqual((by["M42"]["uom"], by["M42"]["quantity"]), ("LF", 150))
        self.assertEqual((by["M43"]["quantity"], by["M44"]["quantity"]), (2, 2))
        self.assertEqual(est["services"]["lines"][0]["service_id"], "S01")
        self.assertEqual(est["sales_tax"]["amount"], 0)
        self.assertEqual(est["labor"]["basis"], "company_rates")

    def test_a_rate_book_without_a_core_drilling_rate_blocks_item_specifically(self):
        book = H.book(lambda sp: sp["Services"].update(rows=[]))
        sc = sf.dp001_requirements(sf.with_g3())
        sc["global_requirements"]["prevailing_wage_required"] = sf.fact("no")
        s = start(sc, book)
        ex = next(e for e in s["exceptions"] if e["code"] == "PRICING_MISSING_SERVICE_RATE")
        self.assertIn("S01", ex["question"])
        self.assertIn("Core drilling", ex["question"])
        self.assertIsNone(s["estimate"])

    def test_g3_gate_post_size_waits_for_its_width_and_a_source(self):
        sc = sf.base_scope()
        sc["gates"][2]["gate_post_od_in"] = sf.fact(None, "unresolved")
        s = start(sc)
        self.assertEqual(sum(1 for e in s["exceptions"] if e["code"] == "MISSING_VALUE"), 2)         # width AND post size
        wf.revise_scope(s, sf.addendum_02_facts(), source=ADD02, by="intake", note="x")
        self.assertEqual({e["affects"][0] for e in s["exceptions"] if e["code"] == "MISSING_VALUE"}, {"/gates/2/gate_post_od_in"})
        self.assertIsNone(s["takeoff"])                                                               # the width alone does not release the posts
        ex = next(e for e in s["exceptions"] if e["code"] == "MISSING_VALUE")
        wf.resolve(s, ex["exception_id"], value=2.875, by="Pat Estimator", note="confirmed with the opening width per 2.1.B")
        self.assertIsNotNone(s["takeoff"])

    def test_unmodeled_stated_requirements_are_never_silently_dropped(self):
        sc = sf.with_g3()
        sc["global_requirements"]["liquidated_damages_clause"] = sf.fact("yes")
        s = start(sc)
        self.assertIn("liquidated_damages_clause", " ".join(e["question"] for e in s["exceptions"] if e["code"] == "NO_PRICING_MAPPING"))
        sc["global_requirements"]["liquidated_damages_clause"]["price_affecting"] = False
        self.assertNotIn("NO_PRICING_MAPPING", blocking(start(sc)))

    def test_double_leaf_gate_quantities_follow_the_addendum(self):
        from engine.takeoff import compute_takeoff
        from pricing import quantities
        sc = sf.dp001_requirements(sf.with_g3())
        out = quantities.build_payload(sc, compute_takeoff(sc), quantities.load_ruleset())["payload"]
        k = {(i.get("item_id") or i["driver_key"]): i["quantity"] for i in out["items"]}
        # leaves: G1 1, G2 two locations x two 6-ft leaves = 4, G3 1  => 6 leaves; 3 hinges and 1 hold-back per leaf; one fork latch per gate
        self.assertEqual((k["M32"], k["M34"], k["M33"]), (18, 6, 4))
        self.assertEqual((k["M43"], k["M44"]), (2, 2))


if __name__ == "__main__":
    unittest.main()

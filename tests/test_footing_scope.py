"""footing-scope.v1: per-run, per-post-class footings. Everything is driven through the real workflow (Scope Gate -> Labor Gate -> Release) with the public DP-001
documents; the arithmetic expected here is written independently of the code under test (closed-form cylinder volumes, hand-listed segments).

Never touches the private evaluation material: only tests/footing_fixtures (public fictional DP-001 data) and samples/public-demo/reference_pricing_workbook_v2_3_0.fictional.xlsx."""
import copy
import json
import math
import unittest

from engine import integration, pricing_service as svc, workflow as wf
from engine.guards import geometry_problems, structural_problems, value_problems
from engine.validate import validate_scope
from pricing import engine as pengine, footings, quantities, vocab
from engine.takeoff import compute_takeoff
from engine.util import apply_patch
from tests import footing_helpers as H

V = H.vol
SEGMENTS_BASE = [25, 30, 105, 37, 37, 176, 37, 37]       # hand-derived from C101, in layout order N (3 segments), E (2), S (1), W (2): 31 / 38 / 107 chain, G3 12 ft (assumed), G1 4 ft, G2 12 ft at mid-side
SEGMENTS_ALT = [25, 30, 67, 37, 37, 138, 37, 37]
BASE_CLASSES = {"A_LINE": 43, "A_CORNER_TERMINAL": 4, "GATE_G1": 2, "GATE_G2": 4, "GATE_G3": 2, "B_LINE": 18, "B_TERMINAL": 6}
ALT_CLASSES = {"A_LINE": 35, "A_CORNER_TERMINAL": 4, "GATE_G1": 2, "GATE_G2": 4, "GATE_G3": 2, "B_LINE": 12, "B_TERMINAL": 4}
DIMS = {"A_LINE": (12, 48), "A_CORNER_TERMINAL": (16, 48), "GATE_G1": (16, 48), "GATE_G2": (16, 48), "GATE_G3": (16, 48), "B_LINE": (8, 30), "B_TERMINAL": (10, 30)}


def with_g3(scope, width=12.0):
    s = copy.deepcopy(scope)
    s["gates"][2]["clear_width_ft"] = {"value": width, "status": "human_resolved", "evidence": []}
    return s


def schedule(scope, scenario="BASE", legacy=True):
    leg = None
    if legacy:
        try:
            leg = compute_takeoff(scope)
        except (TypeError, KeyError, ValueError):
            leg = None
    return footings.evaluate(scope, H.params(), scenario=scenario, legacy_takeoff=leg)


def rec(sch, cid):
    return next(r for r in sch["records"] if r["post_class"] == cid)


class Fixture(unittest.TestCase):
    def test_the_dp001_footing_scope_is_structurally_valid_and_has_no_money_like_keys(self):
        s = H.fixture()
        self.assertEqual(structural_problems(s), [])
        self.assertEqual(value_problems(s), [])
        self.assertEqual(geometry_problems(s), [])
        self.assertEqual(validate_scope(s), [])

    def test_every_class_keeps_document_identity_and_a_reference_for_every_known_value(self):
        for cid, c in H.fixture()["footing_scope"]["classes"].items():
            for f in ("diameter_in", "depth_in"):
                fact = c[f]
                self.assertTrue(fact["evidence"], (cid, f))
                if fact["status"] == "confirmed":
                    e = fact["evidence"][0]
                    self.assertTrue(e["doc_id"] and isinstance(e["page"], int) and e["sheet_label"] and "DIA" in e["excerpt"], (cid, f))

    def test_g3_is_unresolved_with_both_sides_of_the_open_question_cited_not_applied(self):
        g3 = H.fixture()["footing_scope"]["classes"]["GATE_G3"]
        for f in ("diameter_in", "depth_in", "post_od_in"):
            self.assertEqual((g3[f]["value"], g3[f]["status"]), (None, "unresolved"))
        text = " ".join(e["excerpt"] for e in g3["diameter_in"]["evidence"])
        self.assertIn("SIZE IS NOT SPECIFIED", text)
        self.assertIn("NOT OTHERWISE NOTED", text.upper())      # 3.2.D is carried as evidence for a human, not applied

    def test_class_table_is_the_specified_table(self):
        c = H.fixture()["footing_scope"]["classes"]
        got = {k: (c[k]["diameter_in"]["value"], c[k]["depth_in"]["value"]) for k in c}
        self.assertEqual(got, {"A_LINE": (12.0, 48.0), "A_CORNER_TERMINAL": (16.0, 48.0), "GATE_G1": (16.0, 48.0), "GATE_G2": (16.0, 48.0),
                               "GATE_G3": (None, None), "B_LINE": (8.0, 30.0), "B_TERMINAL": (10.0, 30.0)})


class Structure(unittest.TestCase):
    def bad(self, mutate, needle):
        s = H.fixture()
        mutate(s)
        probs = structural_problems(s)
        self.assertTrue(any(needle in m for _, m in probs), (needle, probs))

    def test_wrong_contract_version(self):
        self.bad(lambda s: s["footing_scope"].update(schema_version="footing-scope.v2"), "footing-scope.v1")

    def test_a_project_wide_footing_cannot_coexist(self):
        def m(s):
            s["global_requirements"]["footing_line_diameter_in"] = {"value": 12.0, "status": "confirmed", "evidence": [{"doc_id": "d", "page": 1}]}
        self.bad(m, "silently apply one footing")

    def test_every_fence_run_must_be_covered(self):
        self.bad(lambda s: s["footing_scope"]["runs"].pop(1), "has no footing layout")

    def test_every_gate_needs_its_own_class_no_default(self):
        self.bad(lambda s: s["footing_scope"]["runs"][0]["gate_classes"].pop("G3"), "no default")

    def test_a_gate_cannot_borrow_a_corner_or_terminal_class_to_get_priced(self):
        self.bad(lambda s: s["footing_scope"]["runs"][0]["gate_classes"].update(G3="A_CORNER_TERMINAL"), "may not silently borrow")

    def test_a_gate_class_must_state_its_post_size_even_if_unresolved(self):
        self.bad(lambda s: s["footing_scope"]["classes"]["GATE_G3"].pop("post_od_in"), "must state its post size")

    def test_two_gates_cannot_share_a_class(self):
        self.bad(lambda s: s["footing_scope"]["runs"][0]["gate_classes"].update(G3="GATE_G1"), "is shared by gates")

    def test_a_gate_class_cannot_serve_as_the_line_or_corner_class(self):
        self.bad(lambda s: s["footing_scope"]["runs"][0].update(line_class="GATE_G1"), "line_class")

    def test_unknown_class_reference(self):
        self.bad(lambda s: s["footing_scope"]["runs"][0].update(line_class="NOPE"), "unknown class")

    def test_class_id_grammar(self):
        def m(s):
            s["footing_scope"]["classes"]["bad id"] = copy.deepcopy(s["footing_scope"]["classes"]["A_LINE"])
        self.bad(m, "not allowed")

    def test_every_gate_location_is_placed_exactly_once(self):
        def drop(s):
            s["footing_scope"]["runs"][0]["layout"]["sides"][3]["gates"] = []          # second G2 location missing
        self.bad(drop, "every gate location must be placed exactly once")

        def twice(s):
            s["footing_scope"]["runs"][0]["layout"]["sides"][2]["gates"] = [copy.deepcopy(s["footing_scope"]["runs"][0]["layout"]["sides"][1]["gates"][0])]
        self.bad(twice, "placed twice")

    def test_closed_run_needs_one_side_per_corner(self):
        self.bad(lambda s: s["footing_scope"]["runs"][0]["layout"]["sides"].pop(2), "one per corner")

    def test_open_run_is_one_side(self):
        def m(s):
            s["footing_scope"]["runs"][1]["layout"]["sides"].append({"side_id": "X", "length_lf": copy.deepcopy(s["footing_scope"]["runs"][1]["layout"]["sides"][0]["length_lf"]), "gates": []})
        self.bad(m, "exactly one side")

    def test_non_fact_dimension(self):
        self.bad(lambda s: s["footing_scope"]["classes"]["A_LINE"].update(diameter_in=12.0), "expected object")

    def test_spacing_must_be_a_fact(self):
        self.bad(lambda s: s["fence_runs"][0].pop("section_spacing_ft"), "maximum on-center spacing")

    def test_value_problems(self):
        for v in (0, -3, "12", float("nan")):
            s = H.fixture()
            s["footing_scope"]["classes"]["B_LINE"]["diameter_in"] = {"value": v, "status": "confirmed", "evidence": [{"doc_id": "d", "page": 1}]}
            self.assertTrue(value_problems(s), v)

    def test_geometry_problems(self):
        s = with_g3(H.fixture())
        s["footing_scope"]["runs"][0]["layout"]["sides"][0]["length_lf"]["value"] = 170.0
        self.assertTrue(any("add up" in m for _, m in geometry_problems(s)))
        s = with_g3(H.fixture(), 12.0)
        s["footing_scope"]["runs"][0]["layout"]["sides"][0]["gates"][0]["station_ft"]["value"] = 6.0          # G3 opening 0..12: its post would sit on the corner
        self.assertTrue(any("coincide with the corner post" in m for _, m in geometry_problems(s)))
        s = with_g3(H.fixture(), 80.0)                                                                       # G3 opening -9..71 runs past the corner and over G1
        self.assertTrue(geometry_problems(s))


class Counting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = with_g3(H.fixture())
        cls.alt = apply_patch(cls.base, cls.base["bid_structure"]["alternates"][0]["patch"])
        cls.sb, cls.sa = schedule(cls.base, "BASE"), schedule(cls.alt, "ALT-A1")

    def test_per_class_counts_match_the_hand_derived_ledger(self):
        for sch, want in ((self.sb, BASE_CLASSES), (self.sa, ALT_CLASSES)):
            self.assertEqual({r["post_class"]: r["quantity"] for r in sch["records"]}, want)
        self.assertEqual((self.sb["totals"]["posts"], self.sa["totals"]["posts"]), (79, 63))

    def test_segments_are_the_hand_derived_segments_and_each_rounds_on_its_own(self):
        for sch, want in ((self.sb, SEGMENTS_BASE), (self.sa, SEGMENTS_ALT)):
            segs = [s for s in next(r for r in sch["runs"] if r["run_id"] == "FR-A")["segments"]]
            self.assertEqual([s["length_lf"] for s in segs], want)
            self.assertEqual([s["line_posts"] for s in segs], [max(0, math.ceil(round(x / 10, 6)) - 1) for x in want])

    def test_the_aggregate_lower_bound_is_not_used(self):
        a = next(r for r in self.sb["runs"] if r["run_id"] == "FR-A")
        self.assertEqual(a["line_posts_per_instance"], 43)
        self.assertEqual(math.ceil(484 / 10) - 8, 41)                  # what the legacy aggregate would say
        self.assertNotEqual(a["line_posts_per_instance"], 41)

    def test_segment_counts_sum_to_the_class_count_and_net_length(self):
        for sch in (self.sb, self.sa):
            a = next(r for r in sch["runs"] if r["run_id"] == "FR-A")
            self.assertEqual(sum(s["line_posts"] for s in a["segments"]), rec(sch, "A_LINE")["quantity"])
        self.assertEqual(sum(SEGMENTS_BASE), 484)                      # = net Type A: 524 - (4 + 24 + 12)
        self.assertEqual(sum(SEGMENTS_ALT), 408)

    def test_shared_endpoints_are_one_physical_post(self):
        ids = [p["post_id"] for p in self.sb["posts"]]
        self.assertEqual(len(ids), len(set(ids)))
        corners = [p for p in self.sb["posts"] if p["post_id"].startswith("FR-A#1:C")]
        self.assertEqual(len(corners), 4)                              # four sides share four corners, not eight
        self.assertEqual(len([p for p in self.sb["posts"] if p["post_class"] == "GATE_G2"]), 4)    # 2 locations x 2 posts
        self.assertEqual(self.sb["ownership_audit"]["duplicate_post_ids"], [])

    def test_every_post_has_one_class_one_owner_and_gate_posts_belong_to_their_gate(self):
        for p in self.sb["posts"]:
            self.assertIn(p["post_class"], H.fixture()["footing_scope"]["classes"])
            if p["post_class"].startswith("GATE_"):
                self.assertEqual(p["owner"], "GATE:" + p["post_class"][5:])
            else:
                self.assertEqual(p["owner"], "RUN:" + p["run_id"])
        self.assertEqual(sum(r["quantity"] for r in self.sb["records"]), len(self.sb["posts"]))

    def test_reconciliation_explains_every_hole_of_difference(self):
        for sch, legacy, new in ((self.sb, 77, 79), (self.sa, 61, 63)):
            rc = sch["reconciliation"]
            self.assertEqual((rc["legacy_holes"], rc["schedule_holes"], rc["holes_delta"]), (legacy, new, 2))
            self.assertEqual((rc["explained_delta"], rc["unexplained_delta"]), (2, 0))
            a = next(r for r in rc["runs"] if r["run_id"] == "FR-A")
            self.assertEqual((a["terminals_delta"], a["line_posts_delta"]), (0, 2))
            self.assertEqual(a["explanation"]["sum_of_segment_ceilings"] - a["explanation"]["ceiling_of_sum_of_segments"], 2)
            b = next(r for r in rc["runs"] if r["run_id"] == "FR-B")
            self.assertEqual((b["terminals_delta"], b["line_posts_delta"]), (0, 0))

    def test_count_is_insensitive_to_the_post_center_offset_for_dp001(self):
        for sch in (self.sb, self.sa):
            for r in sch["runs"]:
                self.assertFalse(r["convention_sensitivity"]["sensitive"], r["run_id"])
                self.assertEqual(r["convention_sensitivity"]["nominal"], r["convention_sensitivity"]["offset_bound"])

    def test_a_count_that_depends_on_the_convention_is_flagged_and_never_bid_ready(self):
        s = with_g3(H.fixture())
        # make the north segment after G1 exactly 10.2 ft: 10.2 -> 2 intervals (1 post); with a 0.2 ft post offset it is 10.0 -> still 1... use 10.05 -> 2 vs 1
        side = s["footing_scope"]["runs"][0]["layout"]["sides"][0]
        side["length_lf"]["value"] = 81.1                 # G1 far face at 71.0 -> last segment 10.1 ft (2 intervals); offset 0.5 -> 9.6 (1 interval)
        s["footing_scope"]["runs"][0]["layout"]["sides"][2]["length_lf"]["value"] = 81.1
        s["fence_runs"][0]["length_lf"]["value"] = 81.1 * 2 + 86 * 2
        sch = schedule(s, legacy=False)
        n = next(r for r in sch["runs"] if r["run_id"] == "FR-A")["convention_sensitivity"]
        self.assertTrue(n["sensitive"], n)
        self.assertFalse(sch["posture"]["bid_ready"])
        self.assertIn("COUNT_SENSITIVE_TO_POST_OFFSET", [x["code"] for x in sch["posture"]["reasons"]])

    def test_g3_width_unresolved_makes_adjacent_segments_unknown_never_zero(self):
        sch = schedule(H.fixture(), legacy=False)
        a = rec(sch, "A_LINE")
        self.assertIsNone(a["quantity"])
        self.assertIsNone(a["core_drill_holes"])
        self.assertEqual(a["quantity_known_minimum"], 39)              # the six segments that do not touch G3 are still counted: 43 - 2 - 2
        run = next(r for r in sch["runs"] if r["run_id"] == "FR-A")
        self.assertEqual(run["unresolved_segments"], ["FR-A:N:S1", "FR-A:N:S2"])
        self.assertIsNone(sch["totals"]["posts"])
        self.assertEqual(rec(sch, "GATE_G3")["quantity"], 2)           # two gate posts exist whatever the opening width

    def test_a_gate_adds_two_posts_and_removes_its_opening(self):
        s = with_g3(H.fixture())
        s["gates"][1]["quantity"] = 1                                   # drop one G2 location
        s["footing_scope"]["runs"][0]["layout"]["sides"][3]["gates"] = []
        sch = schedule(s, legacy=False)
        self.assertEqual(rec(sch, "GATE_G2")["quantity"], 2)

    def test_evaluate_is_pure(self):
        s = with_g3(H.fixture())
        before = json.dumps(s, sort_keys=True)
        a, b = footings.evaluate(s, H.params()), footings.evaluate(s, H.params())
        self.assertEqual(json.dumps(s, sort_keys=True), before)
        self.assertEqual(a["schedule_sha256"], b["schedule_sha256"])


class Concrete(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = with_g3(H.fixture())
        cls.sb = schedule(cls.base, "BASE")

    def test_class_volumes_are_pi_r2_h_per_footing_times_count(self):
        for cid, n in BASE_CLASSES.items():
            r = rec(self.sb, cid)
            if cid == "GATE_G3":
                self.assertIsNone(r["concrete_cy"])
                continue
            d, h = DIMS[cid]
            self.assertAlmostEqual(r["footing_volume_cy_each"], V(d, h), places=6)
            self.assertAlmostEqual(r["concrete_cy"], n * V(d, h), places=5, msg=cid)

    def test_known_concrete_reconciles_to_the_reference_7_96_cy(self):
        known = sum(n * V(*DIMS[c]) for c, n in BASE_CLASSES.items() if c != "GATE_G3")
        self.assertAlmostEqual(self.sb["totals"]["known_concrete_cy"], known, places=5)
        self.assertEqual(round(self.sb["totals"]["known_concrete_cy"], 2), 7.96)

    def test_unknown_concrete_is_none_never_zero_and_not_in_a_complete_total(self):
        self.assertIsNone(self.sb["totals"]["concrete_cy"])
        self.assertFalse(self.sb["totals"]["complete"])
        self.assertEqual(self.sb["totals"]["posts_with_unresolved_dimensions"], 2)

    def test_the_legacy_single_footing_total_is_not_like_for_like(self):
        legacy = 18 * V(16, 48) + 59 * V(12, 48)                      # 6 Type B terminals + 18 Type B line posts at Type A sizes, plus G3 at Type A terminal
        self.assertAlmostEqual(legacy, 10.588331, places=5)
        self.assertGreater(legacy - self.sb["totals"]["known_concrete_cy"], 2.0)


class Unresolved(unittest.TestCase):
    """G3 unresolved: the Scope Gate refuses; nothing is priced; the known part is separated from the unknown exposure."""
    @classmethod
    def setUpClass(cls):
        cls.st = H.start(H.fixture())
        H.select(cls.st, "base")
        H.approve_inferred(cls.st)

    def test_blocked_by_the_g3_facts_and_no_estimate(self):
        codes = sorted(e["exception_id"] for e in H.blocking(self.st))
        self.assertEqual(codes, ["EX-MISSING_VALUE-/footing_scope/classes/GATE_G3/depth_in", "EX-MISSING_VALUE-/footing_scope/classes/GATE_G3/diameter_in",
                                 "EX-MISSING_VALUE-/footing_scope/classes/GATE_G3/post_od_in", "EX-MISSING_VALUE-/gates/2/clear_width_ft"])
        self.assertIsNone(self.st["estimate"])
        self.assertIsNone(self.st["proposal_digest"])
        self.assertEqual(self.st["status"], wf.SCOPE_REVIEW)

    def test_g3_width_alone_does_not_unblock_the_footing(self):
        st = copy.deepcopy(self.st)
        H.give(st, "gates/2/clear_width_ft", 12.0)
        self.assertEqual(sorted(e["exception_id"].rsplit("/", 1)[1] for e in H.blocking(st)), ["depth_in", "diameter_in", "post_od_in"])
        self.assertIsNone(st["estimate"])
        self.assertIsNone(st.get("quantities"))

    def test_partial_cost_is_labelled_not_an_estimate_and_lists_exposure_without_guessing(self):
        p = self.st["footing_partial"]["BASE"]
        self.assertFalse(p["is_estimate"])
        self.assertEqual(p["label"], "PARTIAL_UNRECONCILED")
        classes = {e["post_class"]: e for e in p["unknown_exposure"]}
        self.assertEqual(set(classes), {"GATE_G3", "A_LINE"})
        self.assertEqual(classes["GATE_G3"]["posts"], 2)
        self.assertIsNone(classes["A_LINE"]["posts"])
        self.assertEqual(classes["A_LINE"]["posts_known_minimum"], 39)
        for ex in p["unknown_exposure"]:
            self.assertNotIn("extended", ex)                          # no dollar and no quantity is invented for an unknown class
        lines = {l.get("item_id") or l.get("service_id"): l for l in p["lines"]}
        self.assertEqual(lines["M01"]["quantity"], 10)                # 4 corners + 6 G1/G2 posts; the 2 G3 posts are NOT priced as Type A terminals
        self.assertEqual(lines["S01"]["quantity"], 34)                # 10 + 24 Type B holes
        self.assertEqual(self.st["footing_schedule"]["BASE"]["posture"]["release_class"], "NOT_PRICEABLE_PARTIAL_UNRECONCILED")

    def test_pricing_service_reports_unpriced(self):
        r = svc.labor_result(self.st)
        self.assertFalse(r["priced"])
        self.assertTrue(r["blockers"])

    def test_g3_is_never_defaulted_from_a_neighbouring_class(self):
        g3 = rec(self.st["footing_schedule"]["BASE"], "GATE_G3")
        self.assertEqual((g3["diameter_in"], g3["depth_in"], g3["post_od_in"], g3["concrete_cy"]), (None, None, None, None))
        self.assertEqual(g3["value_basis"], "unresolved")
        self.assertEqual(g3["review"]["state"], "BLOCKED_UNRESOLVED")
        self.assertEqual({l["item_id"]: l["quantity"] for l in self.st["footing_partial"]["BASE"]["lines"] if "item_id" in l}["M01"], 10)


class Priced(unittest.TestCase):
    """A fully resolved what-if (G3 width, post and footing assumed by a named, self-declared human) priced through the real engine."""
    @classmethod
    def setUpClass(cls):
        cls.b, cls.a = H.priced("BASE"), H.priced("ALT-A1")
        cls.legacy = json.loads((H.FIX / "pass6_legacy_baseline.json").read_text())

    def est(self, st):
        e = st["estimate"]
        return e["scenarios"][e["headline_scope_ref"]]

    def test_both_scenarios_price_and_are_ready(self):
        self.assertEqual((self.b["status"], self.a["status"]), (wf.READY, wf.READY))

    def test_quantities_are_the_per_class_quantities(self):
        for st, sref, classes in ((self.b, "BASE", BASE_CLASSES), (self.a, "ALT-A1", ALT_CLASSES)):
            q = H.qty(st, sref)
            self.assertEqual(q["M02"]["quantity"], classes["A_LINE"])
            self.assertEqual(q["M01"]["quantity"], classes["A_CORNER_TERMINAL"] + classes["GATE_G1"] + classes["GATE_G2"] + classes["GATE_G3"])
            self.assertEqual((q["M03"]["quantity"], q["M04"]["quantity"]), (classes["B_TERMINAL"], classes["B_LINE"]))
            want_cy = round(sum(n * V(*DIMS[c]) for c, n in classes.items()), 6)
            self.assertAlmostEqual(q["M40"]["quantity"], want_cy, places=5)
            self.assertEqual(q["M40"]["quantity"], q["D05"]["quantity"])
            total = sum(classes.values())
            self.assertEqual((q["D03"]["quantity"], q["D04"]["quantity"], q["S01"]["quantity"]), (total, total, total))

    def test_every_physical_post_is_costed_once(self):
        for st, sref in ((self.b, "BASE"), (self.a, "ALT-A1")):
            sch = st["footing_schedule"][sref]
            q = H.qty(st, sref)
            n = len(sch["posts"])
            self.assertEqual(sum(q[k]["quantity"] for k in ("M01", "M02", "M03", "M04")), n)        # post material, once each
            self.assertEqual(q["D03"]["quantity"], n)                                                # set once
            self.assertEqual(q["D04"]["quantity"], n)                                                # drilled once
            self.assertEqual(q["S01"]["quantity"], n)                                                # core-drill service once
            self.assertEqual(len({p["post_id"] for p in sch["posts"]}), n)

    def test_gate_each_scope_carries_no_post_footing_or_drilling_items(self):
        gate_items = ["M21", "M22", "M28", "M29", "M30", "M31", "M32", "M33", "M34", "M35", "M36", "M37", "M43", "M44", "D09"]
        for k in gate_items:
            self.assertNotRegex(vocab.MATERIALS.get(k, vocab.DRIVERS.get(k, ("", "")))[1].lower(), r"post|footing|concrete|drill")
        for sref, st in (("BASE", self.b), ("ALT-A1", self.a)):
            q = H.qty(st, sref)
            for k in gate_items:
                self.assertEqual(q[k]["quantity"], self.legacy[sref]["quantities"][sref][k]["q"], k)

    def test_only_the_post_footing_items_changed_everything_else_is_pass6(self):
        for sref, st in (("BASE", self.b), ("ALT-A1", self.a)):
            q = H.qty(st, sref)
            old = self.legacy[sref]["quantities"][sref]
            changed = {k for k in old if old[k]["q"] != q[k]["quantity"]}
            # M09/M10: owner decision 2026-10-16 (one brace band per side, two per assembly) changed them from the Pass 6 rule of two per side
            self.assertEqual(changed, {"D03", "D04", "D05", "M02", "M09", "M10", "M17", "M24", "M40", "S01"}, sref)
            self.assertEqual((old["M09"]["q"], old["M10"]["q"], q["M09"]["quantity"], q["M10"]["quantity"]), (32, 32, 16, 16))

    def test_net_fabric_tension_wire_and_gross_top_rail_are_unchanged(self):
        for sref, st in (("BASE", self.b), ("ALT-A1", self.a)):
            q = H.qty(st, sref)
            old = self.legacy[sref]["quantities"][sref]
            for k in ("M05", "D06", "M19", "M20", "M23", "D01", "D02", "D07", "D11", "D12", "M06"):
                self.assertEqual(q[k]["quantity"], old[k]["q"], k)
        q = H.qty(self.b, "BASE")
        self.assertEqual((q["D01"]["quantity"], q["D02"]["quantity"], q["M05"]["quantity"], q["D12"]["quantity"]), (484, 192, 716, 716))

    def test_mixed_footing_classes_do_not_collapse_to_one_rate(self):
        q = H.qty(self.b, "BASE")["M40"]["quantity"]
        single_terminal = 79 * V(16, 48)
        single_line = 79 * V(12, 48)
        self.assertLess(q, single_terminal)
        self.assertNotAlmostEqual(q, single_line, places=3)
        self.assertNotAlmostEqual(q, 18 * V(16, 48) + 61 * V(12, 48), places=3)          # the legacy two-size model

    def test_known_subtotal_lines_equal_the_engine_lines_item_by_item(self):
        for st, sref in ((self.b, "BASE"), (self.a, "ALT-A1")):
            sc = self.est(st)
            part = footings.known_subtotals(st["footing_schedule"][sref], st["ratebook"])
            self.assertEqual(part["label"], "KNOWN_SUBTOTAL_COMPLETE_FOR_THESE_ITEMS")
            self.assertEqual(part["unknown_exposure"], [])
            mats = {l["item_id"]: l["extended"] for l in sc["materials"]["lines"]}
            for l in part["lines"]:
                if "item_id" in l:
                    self.assertEqual(l["extended"], mats[l["item_id"]], l["item_id"])
                else:
                    self.assertEqual(l["extended"], sc["services"]["lines"][0]["extended"])

    def test_totals_follow_the_engine_arithmetic_with_no_invented_delta(self):
        for sref, st in (("BASE", self.b), ("ALT-A1", self.a)):
            sc = self.est(st)
            d = sc["materials"]["subtotal"] + sc["sales_tax"]["amount"] + sc["services"]["subtotal"] + sc["labor"]["subtotal"] + (sc["labor"].get("certified_payroll_admin") or {}).get("extended", 0) + sc["equipment"]["subtotal"] + sc["mobilization"]["subtotal"]
            self.assertAlmostEqual(d, sc["direct_cost"], places=2)
            self.assertAlmostEqual(sc["direct_cost"] + sc["overhead"]["amount"] + sc["contingency"]["amount"] + sc["profit"]["amount"], sc["price_total"], places=2)

    def test_release_is_a_demonstration_not_a_bid_ready_result(self):
        for st in (self.b, self.a):
            self.assertEqual(list(st["footing_schedule"].values())[0]["posture"]["release_class"], "QUALIFIED_DEMONSTRATION_ONLY_NOT_BID_READY")
            self.assertTrue([q for q in wf.qualifications(st) if q["type"] == "footing_scope_not_bid_ready"])
            self.assertIn("FOOTING_SCOPE_NOT_BID_READY", [e["code"] for e in st["exceptions"] if e["severity"] == "advisory"])
        st = copy.deepcopy(self.b)
        pkg = wf.release(st, "Visitor A (self-declared, fictional)", st["scope"]["scope_version"], st["proposal_digest"], note="demonstration release")
        self.assertFalse(pkg["bid_ready"])
        self.assertEqual(pkg["footing_release_class"], {"BASE": "QUALIFIED_DEMONSTRATION_ONLY_NOT_BID_READY", "ALT-A1": "QUALIFIED_DEMONSTRATION_ONLY_NOT_BID_READY"})
        self.assertEqual(pkg["footing_schedule"]["BASE"]["schedule_sha256"], self.b["footing_schedule"]["BASE"]["schedule_sha256"])

    def test_acknowledging_a_warning_does_not_change_the_posture(self):
        st = copy.deepcopy(self.b)
        adv = next(e for e in st["exceptions"] if e["code"] == "FOOTING_SCOPE_NOT_BID_READY")
        with self.assertRaises(wf.GateError):
            wf.resolve(st, adv["exception_id"], value="acknowledged", by=H.WHO, note="ack")
        self.assertEqual(st["footing_schedule"]["BASE"]["posture"]["bid_ready"], False)

    def test_every_assumption_is_carried_as_a_qualification_with_a_named_human(self):
        quals = wf.qualifications(self.b)
        g3 = [q for q in quals if q["type"] == "human_scope_assumption" and "GATE_G3" in q["exception_id"]]
        self.assertEqual(len(g3), 3)
        for q in g3:
            self.assertEqual(q["by"], H.WHO)
        approvals = rec(self.b["footing_schedule"]["BASE"], "A_LINE")["review"]
        self.assertEqual(approvals["state"], "QUALIFIED_BY_NAMED_HUMAN")
        self.assertTrue(all(a["by"] == H.WHO for a in approvals["approvals"]))

    def test_base_and_alternate_are_independent(self):
        qa, qb = H.qty(self.a, "ALT-A1"), H.qty(self.b, "BASE")
        self.assertNotEqual(qa["M40"]["quantity"], qb["M40"]["quantity"])
        self.assertEqual(list(self.a["quantities"]), ["ALT-A1"])
        self.assertEqual(list(self.b["quantities"]), ["BASE", "ALT-A1"])
        self.assertEqual(H.qty(self.b, "ALT-A1")["S01"]["quantity"], 63)
        self.assertEqual(H.qty(self.b, "BASE")["S01"]["quantity"], 79)
        self.assertNotEqual(self.b["footing_schedule"]["BASE"]["schedule_sha256"], self.b["footing_schedule"]["ALT-A1"]["schedule_sha256"])

    def test_released_view_exposes_the_schedule_additively(self):
        v = integration.view(self.b)
        self.assertEqual(set(v["footing"]), {"BASE", "ALT-A1"})
        self.assertEqual(v["footing"]["BASE"]["posture"]["release_class"], "QUALIFIED_DEMONSTRATION_ONLY_NOT_BID_READY")
        self.assertTrue(v["estimate_view"])


class Authority(unittest.TestCase):
    def priced_base(self):
        return H.priced("BASE")

    def revise(self, st, path, value, rev=2):
        fact = {"value": value, "status": "confirmed", "evidence": [{"doc_id": "dp001_addendum_02", "page": 1, "source_type": "spec_section", "excerpt": "revised", "doc_revision": rev}]}
        return wf.revise_scope(st, [{"path": path, "fact": fact}], source={"doc_id": "dp001_addendum_02", "doc_revision": rev, "sha256": "ab" * 32}, by="ingest", note="addendum 02 revises a footing fact")

    def test_changing_a_footing_dimension_voids_labor_release_and_the_digest(self):
        st = self.priced_base()
        old = st["proposal_digest"]
        old_sch = st["footing_schedule"]["BASE"]["schedule_sha256"]
        self.revise(st, "/footing_scope/classes/A_LINE/depth_in", 54.0)
        self.assertIsNone(st["crew_plan"])
        self.assertIsNone(st["wage_determination"])
        self.assertEqual(st["labor_review"]["status"], "unresolved")
        self.assertIsNone(st["proposal_digest"])
        self.assertIsNone(st["estimate"])
        self.assertNotEqual(st["status"], wf.READY)
        self.assertNotEqual(st["footing_schedule"]["BASE"]["schedule_sha256"], old_sch)
        self.assertFalse(svc.digest_is_current(st, old)["current"])
        with self.assertRaises(wf.GateError):
            wf.release(st, "Visitor A (self-declared, fictional)", st["scope"]["scope_version"], old)

    def test_changing_a_post_count_input_voids_labor_release_and_changes_the_count(self):
        st = self.priced_base()
        old = st["proposal_digest"]
        self.assertEqual(H.qty(st, "BASE")["S01"]["quantity"], 79)
        self.revise(st, "/footing_scope/runs/0/layout/sides/0/gates/0/station_ft", 30.0)          # moves G3: segments 24 and 31 -> one more line post
        self.assertEqual(st["footing_schedule"]["BASE"]["totals"]["posts"], 80)
        self.assertIsNone(st["crew_plan"])
        self.assertIsNone(st["proposal_digest"])
        self.assertNotEqual(st["status"], wf.READY)
        self.assertFalse(svc.digest_is_current(st, old)["current"])

    def test_changing_the_g3_assumption_voids_dependent_decisions(self):
        st = self.priced_base()
        old = st["proposal_digest"]
        self.revise(st, "/footing_scope/classes/GATE_G3/diameter_in", 20.0)
        self.assertIsNone(st["crew_plan"])
        self.assertIsNone(st["proposal_digest"])
        self.assertFalse(svc.digest_is_current(st, old)["current"])

    def test_stale_digest_is_refused_and_current_digest_releases_once(self):
        st = self.priced_base()
        with self.assertRaises(wf.GateError):
            wf.release(st, "Visitor A (self-declared, fictional)", st["scope"]["scope_version"], "0" * 64)
        self.assertEqual(st["status"], wf.READY)
        pkg = wf.release(st, "Visitor A (self-declared, fictional)", st["scope"]["scope_version"], st["proposal_digest"])
        self.assertEqual(st["status"], wf.RELEASED)
        self.assertFalse(pkg["bid_ready"])

    def test_digest_binds_the_footing_schedule(self):
        st = self.priced_base()
        d1 = wf.proposal_digest(st)
        st["footing_schedule"]["BASE"]["schedule_sha256"] = "f" * 64
        self.assertNotEqual(wf.proposal_digest(st), d1)

    def test_wage_and_crew_protections_still_hold(self):
        st = H.start(H.fixture())
        H.select(st, "base")
        H.approve_inferred(st)
        H.g3_whatif(st)
        H.approve_inferred(st)
        self.assertNotEqual(st["status"], wf.READY)
        self.assertIsNone(st["estimate"])
        wf.approve_quantity_ruleset(st, by=H.WHO, note="draft ruleset", ruleset_sha256=st["ruleset"]["sha256"])
        self.assertIsNone(st["estimate"])                                              # prevailing wage applies: no price without a cleared wage decision
        self.assertIn("WAGE_DETERMINATION_REQUIRED", [e["code"] for e in st["exceptions"]])

    def test_scope_resolution_with_a_bad_value_changes_nothing(self):
        st = H.start(H.fixture())
        H.select(st, "base")
        H.approve_inferred(st)
        before = json.dumps({k: st[k] for k in ("scope", "audit", "exceptions")}, sort_keys=True, default=str)
        ex = next(e for e in H.blocking(st) if "GATE_G3/diameter_in" in e["exception_id"])
        for bad in (-4, 0, "sixteen", float("nan"), True):
            with self.assertRaises(wf.GateError):
                wf.resolve(st, ex["exception_id"], value=bad, by=H.WHO, note="bad value")
        self.assertEqual(json.dumps({k: st[k] for k in ("scope", "audit", "exceptions")}, sort_keys=True, default=str), before)


class FailClosed(unittest.TestCase):
    def blocked(self, mutate):
        s = H.fixture()
        mutate(s)
        st = H.start(s)
        self.assertIsNone(st["estimate"])
        self.assertTrue(H.blocking(st))
        return st

    def test_malformed_footing_scope_blocks_instead_of_being_ignored(self):
        st = self.blocked(lambda s: s["footing_scope"]["classes"]["A_LINE"].update(diameter_in="12"))
        self.assertIn("SCOPE_INVALID", [e["code"] for e in H.blocking(st)])
        self.assertIsNone(st.get("footing_schedule", {}).get("BASE") if st.get("footing_schedule") else None)

    def test_uncovered_run_blocks(self):
        st = self.blocked(lambda s: s["footing_scope"]["runs"].pop())
        self.assertIn("SCOPE_INVALID", [e["code"] for e in H.blocking(st)])

    def test_global_footing_alongside_footing_scope_blocks(self):
        def m(s):
            s["global_requirements"]["footing_line_depth_in"] = {"value": 48.0, "status": "confirmed", "evidence": [{"doc_id": "d", "page": 1}]}
        st = self.blocked(m)
        self.assertIn("SCOPE_INVALID", [e["code"] for e in H.blocking(st)])

    def test_nan_dimension_blocks(self):
        s = H.fixture()
        s["footing_scope"]["classes"]["B_LINE"]["diameter_in"] = {"value": float("nan"), "status": "confirmed", "evidence": [{"doc_id": "d", "page": 1}]}
        self.assertTrue(value_problems(s))
        st = H.start(s)
        self.assertIn("INVALID_VALUE", [e["code"] for e in H.blocking(st)])
        self.assertIsNone(st["estimate"])

    def test_gate_post_that_cannot_exist_blocks(self):
        s = with_g3(H.fixture(), 80.0)
        st = H.start(s)
        self.assertIn("GEOMETRY_INVALID", [e["code"] for e in st["exceptions"]])
        self.assertIsNone(st["estimate"])

    def test_a_different_gate_post_size_than_the_run_terminals_is_not_priced_as_one_family(self):
        st = H.start(H.fixture())
        H.select(st, "base")
        H.approve_inferred(st)
        H.g3_whatif(st, footing=(16.0, 48.0, 3.5))
        H.approve_inferred(st)
        self.assertIn("NO_PRICING_MAPPING", [e["code"] for e in H.blocking(st)])
        self.assertIsNone(st["estimate"])

    def test_malformed_shapes_never_crash_and_never_price(self):
        muts = {
            "string": lambda s: s.__setitem__("footing_scope", "x"), "list": lambda s: s.__setitem__("footing_scope", [1]), "none": lambda s: s.__setitem__("footing_scope", None),
            "empty": lambda s: s.__setitem__("footing_scope", {}), "classes_list": lambda s: s["footing_scope"].__setitem__("classes", []),
            "runs_str": lambda s: s["footing_scope"].__setitem__("runs", "a"), "sides_str": lambda s: s["footing_scope"]["runs"][0]["layout"].__setitem__("sides", "abc"),
            "side_none": lambda s: s["footing_scope"]["runs"][0]["layout"]["sides"].__setitem__(0, None),
            "instance_str": lambda s: s["footing_scope"]["runs"][0]["layout"]["sides"][0]["gates"][0].__setitem__("instance", "1"),
            "station_str": lambda s: s["footing_scope"]["runs"][0]["layout"]["sides"][0]["gates"][0].__setitem__("station_ft", {"value": "31", "status": "confirmed", "evidence": []}),
            "length_negative": lambda s: s["footing_scope"]["runs"][0]["layout"]["sides"][0].__setitem__("length_lf", {"value": -1, "status": "confirmed", "evidence": [{"doc_id": "d", "page": 1}]}),
            "spacing_zero": lambda s: s["fence_runs"][0].__setitem__("section_spacing_ft", {"value": 0, "status": "confirmed", "evidence": [{"doc_id": "d", "page": 1}]}),
            "diameter_inf": lambda s: s["footing_scope"]["classes"]["A_LINE"].__setitem__("diameter_in", {"value": float("inf"), "status": "confirmed", "evidence": [{"doc_id": "d", "page": 1}]}),
            "gates_none": lambda s: s.__setitem__("gates", [None]),
        }
        for name, mutate in muts.items():
            s = H.fixture()
            mutate(s)
            st = H.start(s)                                          # must not raise
            self.assertIsNone(st["estimate"], name)
            self.assertTrue(H.blocking(st), name)
            self.assertIsNone(st["proposal_digest"], name)

    def test_type_a_footing_classes_on_a_type_b_run_are_refused(self):
        s = H.fixture()
        s["footing_scope"]["classes"]["B_LINE"]["fence_type"] = "A"
        st = H.start(s)
        H.select(st, "base")
        H.approve_inferred(st)
        H.g3_whatif(st)
        H.approve_inferred(st)
        self.assertIn("NO_PRICING_MAPPING", [e["code"] for e in H.blocking(st)])
        self.assertTrue(any("other fence type" in e["question"] for e in H.blocking(st)))
        self.assertIsNone(st["estimate"])

    def test_adjust_takeoff_is_idempotent_and_does_not_mutate(self):
        s = with_g3(H.fixture())
        tk = compute_takeoff(s)
        before = json.dumps(tk, sort_keys=True)
        sch = schedule(s)
        a = footings.adjust_takeoff(s, tk, sch)
        self.assertEqual(json.dumps(tk, sort_keys=True), before)
        b = footings.adjust_takeoff(s, a, sch)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertEqual((a["totals"]["footings"], a["totals"]["line_posts"], a["totals"]["terminals"]), (79, 61, 18))
        self.assertEqual(a["runs"]["FR-A"]["legacy_aggregate"]["line_posts"], 41)


class LegacyDrift(unittest.TestCase):
    """A scope WITHOUT footing_scope keeps Pass 6 quantities and labor; Jordan's later gate material decision changes its price."""
    def test_legacy_scope_has_no_footing_artifacts_and_identical_results(self):
        legacy = json.loads((H.FIX / "pass6_legacy_baseline.json").read_text())
        for sref in ("BASE", "ALT-A1"):
            st = H.start(H.fixture("dp001_legacy_scope.json"))
            H.select(st, "base" if sref == "BASE" else "ALT-A1")
            H.approve_inferred(st)
            H.give(st, "gates/2/clear_width_ft", 12.0, "WHAT-IF ONLY")
            H.approve_inferred(st)
            H.labor(st)
            self.assertNotIn("footing_schedule", st)
            self.assertNotIn("footing_partial", st)
            self.assertNotIn("footing", integration.view(st))
            e = st["estimate"]["scenarios"][sref]
            old = legacy[sref]["estimate"]
            self.assertEqual({x["item_id"] for x in e["materials"]["lines"] if x["item_id"].startswith("OVR-GATE-")},
                             {"OVR-GATE-G1", "OVR-GATE-G2", "OVR-GATE-G3"})
            from tests.test_gate_assembly_key import key_total, without_override       # the un-overridden engine still equals the recorded Pass 6 price,
            from pricing.quantities import scenario_scopes                              # and the overridden price equals the independent key
            unover = without_override(st)["scenarios"][sref]
            # the ONLY difference from the recorded Pass 6 price is the brace-band decision (32 -> 16 each of M09 and M10): derive it independently
            from decimal import Decimal as _D
            mk = st["ratebook"]["markups"]
            lines = {x["item_id"]: x for x in unover["materials"]["lines"]}
            rates = {m["item_id"]: m for m in st["ratebook"]["materials"]}
            import math as _m
            drop = _D(0)
            for k in ("M09", "M10"):
                old_order = _m.ceil(_D(32) * (1 + _D(str(rates[k]["overage_pct"]))))
                drop += (_D(old_order) - _D(str(lines[k]["order_quantity"]))) * _D(str(rates[k]["unit_price"]))
            self.assertGreater(drop, 0)
            exp_direct = (_D(str(old["direct_cost"])) - drop).quantize(_D("0.01"))
            self.assertEqual(_D(str(unover["direct_cost"])), exp_direct)
            oh, ct = (exp_direct * _D(str(mk["overhead_pct"]))).quantize(_D("0.01"), "ROUND_HALF_UP"), (exp_direct * _D(str(mk["contingency_pct"]))).quantize(_D("0.01"), "ROUND_HALF_UP")
            sub = exp_direct + oh + ct
            self.assertEqual(_D(str(unover["price_total"])), sub + (sub * _D(str(mk["profit_pct"]))).quantize(_D("0.01"), "ROUND_HALF_UP"))
            direct, total, _, _ = key_total(unover, scenario_scopes(st["scope"])[sref], st["ratebook"]["markups"])
            self.assertEqual((str(e["price_total"]), str(e["direct_cost"])), (str(total), str(direct)))
            self.assertEqual(e["labor"]["subtotal"], old["labor"])
            want = {k: v["q"] for k, v in legacy[sref]["quantities"][sref].items()}
            want.update(M09=16, M10=16)                                              # owner decision 2026-10-16: one brace band per side (Pass 6 had two)
            self.assertEqual({k: v["quantity"] for k, v in H.qty(st, sref).items()}, want)
            self.assertEqual(st["takeoff"]["totals"], legacy[sref]["takeoff_totals"])
            pkg = wf.release(st, "Visitor A (self-declared, fictional)", st["scope"]["scope_version"], st["proposal_digest"])
            self.assertNotIn("footing_schedule", pkg)
            self.assertNotIn("bid_ready", pkg)

    def test_frozen_service_surface_is_unchanged(self):
        pinned = json.loads((H.ROOT / "docs/pricing/engine_interface.v1.json").read_text())
        self.assertEqual(svc.SURFACE, pinned)
        self.assertEqual(svc.CONTRACT_VERSION, "pricing-service.v1")


class UnitMetadata(unittest.TestCase):
    """independent audit P0: a fact may declare its field's exact unit or none; a contradictory, malformed or unsupported declaration is rejected BEFORE any calculation."""
    CL = ("footing_scope", "classes")
    SIDE = ("footing_scope", "runs", 0, "layout", "sides", 0)

    def set(self, s, path, **kw):
        cur = s
        for p in path:
            cur = cur[p]
        cur.update(kw)

    def rejected(self, mutate):
        s = H.fixture()
        mutate(s)
        probs = structural_problems(s)
        self.assertTrue(probs and all(m.startswith("FOOTING_UNIT_INVALID:") for _, m in probs), probs)
        st = H.start(s)
        self.assertEqual({e["code"] for e in H.blocking(st)}, {"FOOTING_UNIT_INVALID"})
        self.assertIsNone(st["estimate"])
        self.assertIsNone(st["proposal_digest"])
        self.assertFalse(st["footing_schedule"])          # no schedule is computed for an invalid scope
        with self.assertRaises(ValueError):
            footings.evaluate(s, H.params())            # a direct caller cannot bypass the validation either

    def test_diameter_declaring_feet_is_rejected_not_read_as_inches(self):
        self.rejected(lambda s: self.set(s, self.CL + ("A_LINE", "diameter_in"), unit="ft"))

    def test_depth_declaring_feet(self):
        self.rejected(lambda s: self.set(s, self.CL + ("A_LINE", "depth_in"), unit="ft"))

    def test_post_od_declaring_feet(self):
        self.rejected(lambda s: self.set(s, self.CL + ("A_CORNER_TERMINAL", "post_od_in"), unit="ft"))

    def test_lengths_stations_spacing_and_gate_widths_declaring_inches(self):
        self.rejected(lambda s: self.set(s, self.SIDE + ("length_lf",), unit="in"))
        self.rejected(lambda s: self.set(s, self.SIDE + ("gates", 0, "station_ft"), unit="in"))
        self.rejected(lambda s: self.set(s, ("fence_runs", 0, "length_lf"), unit="in"))
        self.rejected(lambda s: self.set(s, ("fence_runs", 0, "section_spacing_ft"), unit="in"))
        self.rejected(lambda s: self.set(s, ("gates", 0, "clear_width_ft"), unit="in"))

    def test_invalid_units_types_and_casing(self):
        for bad in ("IN", "In", "inch", "inches", "furlong", "", " in", 12, None, ["in"], {"u": "in"}, True):
            self.rejected(lambda s, b=bad: self.set(s, self.CL + ("B_LINE", "diameter_in"), unit=b))

    def test_unsupported_extra_metadata(self):
        self.rejected(lambda s: self.set(s, self.CL + ("A_LINE", "diameter_in"), uom="ft"))
        self.rejected(lambda s: self.set(s, self.CL + ("A_LINE", "depth_in"), unit_of_measure="ft"))
        self.rejected(lambda s: self.set(s, self.CL + ("A_LINE", "depth_in"), scale=12))

    def test_unresolved_g3_may_not_smuggle_a_unit(self):
        self.rejected(lambda s: self.set(s, self.CL + ("GATE_G3", "diameter_in"), unit="ft"))

    def test_externally_supplied_quantities_are_rejected_by_the_schema(self):
        for path, kw in (((self.CL + ("A_LINE",)), {"concrete_cy": 1.0}), (("footing_scope", "runs", 0), {"post_count": 43}), (("footing_scope", "convention"), {"units": "ft"}),
                         ((self.CL + ("A_LINE",)), {"core_drill_holes": 43})):
            s = H.fixture()
            self.set(s, path, **kw)
            self.assertTrue(structural_problems(s), kw)
            self.assertIsNone(H.start(s)["estimate"])

    def test_valid_matching_units_and_valid_omission_are_accepted_with_identical_results(self):
        a = footings.evaluate(with_g3(H.fixture()), H.params())
        s = with_g3(H.fixture())
        for f in ("diameter_in", "depth_in"):
            s["footing_scope"]["classes"]["A_LINE"][f].pop("unit")
        s["footing_scope"]["runs"][0]["layout"]["sides"][0]["length_lf"]["unit"] = "lf"
        self.assertEqual(structural_problems(s), [])
        b = footings.evaluate(s, H.params())
        self.assertEqual([r["quantity"] for r in a["records"]], [r["quantity"] for r in b["records"]])
        self.assertEqual(a["totals"], b["totals"])

    def test_known_concrete_is_unchanged_and_gate_material_uses_the_override(self):
        self.assertEqual(round(schedule(with_g3(H.fixture()), "BASE")["totals"]["known_concrete_cy"], 4), 7.9566)
        alt = apply_patch(with_g3(H.fixture()), with_g3(H.fixture())["bid_structure"]["alternates"][0]["patch"])
        self.assertEqual(round(schedule(alt, "ALT-A1")["totals"]["known_concrete_cy"], 4), 6.7308)
        for sref in ("BASE", "ALT-A1"):
            lines = H.priced(sref)["estimate"]["scenarios"][sref]["materials"]["lines"]
            self.assertEqual({x["item_id"] for x in lines if x["item_id"].startswith("OVR-GATE-")},
                             {"OVR-GATE-G1", "OVR-GATE-G2", "OVR-GATE-G3"})

    def test_a_bad_unit_arriving_after_pricing_changes_nothing(self):
        st = H.priced("BASE")
        keys = ("scope", "audit", "estimate", "proposal_digest", "crew_plan", "wage_determination", "labor_review", "footing_schedule", "exceptions")
        before = json.dumps({k: st[k] for k in keys}, sort_keys=True, default=str)
        fact = {"value": 14.0, "status": "confirmed", "unit": "ft", "evidence": [{"doc_id": "dp001_addendum_02", "page": 1, "source_type": "spec_section", "excerpt": "x", "doc_revision": 2}]}
        with self.assertRaises(wf.GateError):
            wf.revise_scope(st, [{"path": "/footing_scope/classes/A_LINE/diameter_in", "fact": fact}], source={"doc_id": "dp001_addendum_02", "doc_revision": 2, "sha256": "ab" * 32}, by="i", note="n")
        self.assertEqual(json.dumps({k: st[k] for k in keys}, sort_keys=True, default=str), before)

    def test_legacy_scope_without_footing_scope_is_unaffected(self):
        s = H.fixture("dp001_legacy_scope.json")
        s["fence_runs"][0]["length_lf"]["unit"] = "in"            # legacy facts are not validated by the footing contract: exact Pass 6 behavior
        self.assertEqual(unit_problems_of(s), [])


def unit_problems_of(s):
    return footings.unit_problems(s)


class ContractDocs(unittest.TestCase):
    def test_the_schema_file_validates_the_fixture_and_rejects_bad_shapes(self):
        from pricing import jsonschema_lite
        fs = H.fixture()["footing_scope"]
        self.assertEqual(jsonschema_lite.problems(fs, "footing_scope.v1"), [])
        for mutate in (lambda f: f["classes"].update({"bad id": f["classes"]["A_LINE"]}), lambda f: f["runs"][0]["layout"].update(kind="ring"),
                       lambda f: f.update(extra=1), lambda f: f["classes"]["A_LINE"].update(role="post"), lambda f: f["runs"][0]["layout"]["sides"][0].update(length_lf=176)):
            bad = copy.deepcopy(fs)
            mutate(bad)
            self.assertTrue(jsonschema_lite.problems(bad, "footing_scope.v1"))
            s = H.fixture()
            s["footing_scope"] = bad
            self.assertTrue(structural_problems(s))


    def test_pinned_footing_contract_matches_the_code(self):
        pin = json.loads((H.ROOT / "docs/pricing/footing_scope.v1.json").read_text())
        self.assertEqual(pin["contract_version"], footings.CONTRACT_VERSION)
        self.assertEqual(pin["calc_version"], footings.CALC_VERSION)
        self.assertEqual(pin["schedule_version"], footings.SCHEDULE_VERSION)
        self.assertEqual(pin["measurement_convention"], footings.CONVENTION_ID)
        self.assertEqual(pin["roles"], list(footings.ROLES))
        self.assertEqual(pin["post_item_map"], {f"{k[0]}:{k[1]}": v for k, v in footings.POST_ITEM.items()})
        sch = schedule(with_g3(H.fixture()))
        self.assertEqual(sorted(sch), sorted(pin["schedule_keys"]))
        self.assertEqual(sorted(sch["records"][0]), sorted(pin["record_keys"]))
        self.assertEqual(sorted(sch["posture"]), sorted(pin["posture_keys"]))


if __name__ == "__main__":
    unittest.main()

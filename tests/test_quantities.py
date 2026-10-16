"""Quantity layer: stable-ID mapping, gross vs net, the top-rail investigation, status cascade, and mapping gaps.
Fixtures are invented (tests/scope_fixtures.py); no real drawing geometry and no answer key is used anywhere."""
import copy
import json
import math
import unittest

from engine.takeoff import compute_takeoff
from pricing import jsonschema_lite, quantities, vocab
from tests import scope_fixtures as sf

RS = quantities.load_ruleset()
APPROVAL = {"by": "Pat Estimator"}


def build(scope, **kw):
    kw.setdefault("ruleset_approval", APPROVAL)
    out = quantities.build_payload(scope, compute_takeoff(scope), RS, **kw)
    return out["payload"], out["mapping_problems"]


def by_key(payload):
    return {(i.get("item_id") or i["driver_key"]): i for i in payload["items"]}


def q(payload, key):
    return by_key(payload)[key]["quantity"]


class Mapping(unittest.TestCase):
    def setUp(self):
        self.scope = sf.with_g3()
        self.p, self.problems = build(self.scope)
        self.k = by_key(self.p)

    def test_payload_covers_the_whole_vocabulary_and_conforms_to_the_schema(self):
        self.assertEqual(jsonschema_lite.problems(self.p, "quantity_payload.v1"), [])
        self.assertEqual(set(self.k), set(vocab.MATERIALS) | set(vocab.SERVICES) | set(vocab.DRIVERS))
        self.assertNotIn("M41", self.k)
        self.assertEqual(self.problems, [])
        for key, it in self.k.items():
            self.assertEqual(it["uom"], vocab.uom(key), key)
            self.assertEqual(it["scope_ref"], "BASE")

    def test_payload_never_contains_money(self):
        text = json.dumps(self.p, allow_nan=False).lower()
        for word in ("price", "cost", "wage", "markup", "dollar", "$"):
            self.assertNotIn(word, text)

    # Fixture geometry (invented lengths; gate schedule per DP-001): Type A 400 LF closed, 4 corners; G1 4 ft x1, G2 12 ft double x2,
    # G3 10 ft x1 (test width). 4 gates => 8 gate posts; openings = 4 + 2*12 + 10 = 38. Type B 150 LF, 2 free ends.
    OPEN = 4 + 2 * 12 + 10

    def test_posts_by_type(self):
        # A: terminals 4 corners + 8 gate posts = 12; intervals 12, segments 12-4 = 8; line = ceil(362/10) - 8 = 29. B: 2 terminals, line ceil(15)-1 = 14
        self.assertEqual([q(self.p, k) for k in ("M01", "M02", "M03", "M04")], [12, 29, 2, 14])
        self.assertEqual(q(self.p, "D03"), 12 + 29 + 2 + 14)
        self.assertEqual(q(self.p, "D04"), q(self.p, "D03"))

    def test_gross_versus_net_and_the_top_rail(self):
        net = q(self.p, "M19") + q(self.p, "M20")
        self.assertEqual(net, 400 - self.OPEN + 150)
        self.assertEqual(q(self.p, "D07"), net)
        self.assertEqual(q(self.p, "D11"), net)
        self.assertEqual(q(self.p, "D12"), 550)                       # layout is gross
        # the investigation: the rail is NOT net fabric LF when the drawings say it runs across the openings
        self.assertEqual(q(self.p, "M05"), 550)
        self.assertEqual(q(self.p, "M05") - net, self.OPEN)
        self.assertEqual(q(self.p, "D06"), q(self.p, "M05"))
        self.assertEqual(q(self.p, "M35"), self.OPEN)                 # header rail is a separate member across each opening

    def test_top_rail_follows_the_drawing_note_not_an_assumption(self):
        s = copy.deepcopy(self.scope)
        s["global_requirements"]["top_rail_continuous_across_gate_openings"] = sf.fact("no")
        p, _ = build(s)
        self.assertEqual(q(p, "M05"), 400 - self.OPEN + 150)          # stops at openings
        del s["global_requirements"]["top_rail_continuous_across_gate_openings"]
        p, _ = build(s)
        it = by_key(p)["M05"]
        self.assertEqual((it["quantity"], it["status"]), (None, "unresolved"))
        self.assertIn("continuously across gate openings", it["unresolved_reasons"][0])
        self.assertEqual(by_key(p)["D06"]["status"], "unresolved")

    def test_mid_rail_stays_net_because_the_gate_leaf_occupies_it(self):
        self.assertEqual(q(self.p, "M06"), 400 - self.OPEN)            # Type A net only; type B has no mid rail

    def test_fabric_by_height_and_gates(self):
        self.assertEqual(q(self.p, "M19"), 362)
        self.assertEqual(q(self.p, "M20"), 150)
        self.assertEqual(q(self.p, "M21"), self.OPEN)
        self.assertEqual(q(self.p, "M22"), self.OPEN)                  # 10 ft fence - 7 ft gate = 3 ft transom
        self.assertEqual(q(self.p, "D09"), 4)

    def test_gate_hardware_per_leaf(self):
        # leaves: G1 1, G2 2 x qty 2 = 4, G3 1  => 6 (Addendum 01: three hinges and one hold-back per leaf)
        self.assertEqual(q(self.p, "M32"), 18)
        self.assertEqual(q(self.p, "M31"), 6)
        self.assertEqual(q(self.p, "M34"), 6)
        self.assertEqual(q(self.p, "M33"), 4)                          # one fork latch per gate (active leaf only)
        self.assertEqual(q(self.p, "M28"), (2 * 7 + 3 * 4) + 4 * (2 * 7 + 3 * 6) + (2 * 7 + 3 * 10))

    def test_double_leaf_gate_gets_a_drop_rod_and_ground_sockets_priced_separately(self):
        self.assertEqual((q(self.p, "M43"), q(self.p, "M44")), (2, 2))  # one center drop rod and one socket per double-leaf gate, G2 x2
        self.assertEqual((self.k["M43"]["uom"], self.k["M44"]["uom"]), ("EA", "EA"))
        self.assertIn("Addendum 01", self.k["M43"]["calculation_method"])
        s = copy.deepcopy(self.scope)
        s["gates"][1]["gate_kind"] = sf.fact("single_swing")
        s["gates"][1]["clear_width_ft"] = sf.fact(6.0)
        p, problems = build(s)
        self.assertEqual((q(p, "M43"), q(p, "M44")), (0, 0))
        self.assertEqual(problems, [])

    def test_tension_bars_and_bands_follow_section_2_3_c(self):
        # one full-height bar at each terminal, corner and gate post; bands at 12 in maximum spacing: ceil(120/12)+1 = 11, ceil(42/12)+1 = 5
        self.assertEqual((q(self.p, "M12"), q(self.p, "M13")), (12, 2))
        self.assertEqual(q(self.p, "M14"), 12 * 11)
        self.assertEqual(q(self.p, "M15"), 2 * 5)
        self.assertEqual(q(self.p, "M37"), 6 * 2 * (7 + 1))             # 6 leaves x 2 bars x (ceil(84/12)+1)

    def test_fabric_is_tied_to_every_rail_it_crosses(self):
        # Type A is tied to top AND mid rail at 24 in; Type B only to its top rail
        self.assertEqual(q(self.p, "M26"), math.ceil(362 * 12 / 24) * 2 + math.ceil(150 * 12 / 24))

    def test_bracing_comes_from_the_takeoff_and_is_not_double_counted(self):
        # 3.3.B: corners 2 each (8) + 2 per gate post pair... takeoff: corners*2 + 2 per gate = 8 + 8 = 16
        self.assertEqual(q(self.p, "M08"), 16)
        self.assertEqual(q(self.p, "D08"), 16)
        # owner decision 2026-10-16 2:15 PM CT (ruleset 1.2.1): ONE band per side, TWO per assembly: M09 + M10 = 2 x assemblies
        self.assertEqual(q(self.p, "M09"), 16)
        self.assertEqual(q(self.p, "M10"), 16)
        self.assertEqual(q(self.p, "M09") + q(self.p, "M10"), 2 * q(self.p, "M08"))

    def test_footings_and_concrete_volume_in_cubic_yards(self):
        vol = lambda d, h: math.pi * (d / 2) ** 2 * h / 46656
        want = round((12 + 2) * vol(12, 42) + (29 + 14) * vol(10, 42), 6)
        self.assertAlmostEqual(q(self.p, "M40"), want, places=5)
        self.assertEqual(self.k["M40"]["uom"], "CU YD")
        self.assertEqual(q(self.p, "D05"), q(self.p, "M40"))           # one concrete quantity feeds both; no bagged-concrete twin

    def test_windscreen_and_cable_ties(self):
        self.assertEqual((q(self.p, "M38"), q(self.p, "D10"), q(self.p, "M39")), (120, 120, 240))

    def test_run_repeat_scales_every_quantity(self):
        s = copy.deepcopy(self.scope)
        s["fence_runs"][1]["repeat"] = 2
        p, _ = build(s)
        self.assertEqual(q(p, "M20"), 300)
        self.assertEqual(q(p, "M03"), 4)

    def test_calculation_methods_and_evidence_are_recorded(self):
        m5 = self.k["M05"]
        self.assertIn("continuous across gate openings", m5["calculation_method"])
        self.assertIn({"fact_path": "/fence_runs/0/length_lf", "doc_id": "PLANS", "doc_revision": 0, "page": 2, "sheet_label": "C101"},
                      m5["source_evidence_refs"])
        self.assertTrue(all(i["calculation_method"] for i in self.p["items"]))

    def test_deterministic_and_json_safe(self):
        a, _ = build(self.scope)
        b, _ = build(self.scope)
        self.assertEqual(json.dumps(a, sort_keys=True, allow_nan=False), json.dumps(b, sort_keys=True, allow_nan=False))


class StatusCascade(unittest.TestCase):
    def test_unresolved_g3_width_is_null_never_zero_and_stops_dependent_quantities(self):
        s = sf.with_g3()
        takeoff = compute_takeoff(s)                                   # computed with a width so it can run; the fact is then unsettled
        s["gates"][2]["clear_width_ft"] = sf.fact(None, "unresolved")
        p = quantities.build_payload(s, takeoff, RS, ruleset_approval=APPROVAL)["payload"]
        k = by_key(p)
        for key in ("M19", "D01", "D07", "M21", "M22", "M35", "M28"):
            self.assertEqual((key, k[key]["quantity"], k[key]["status"]), (key, None, "unresolved"))
        self.assertIn("gate G3 clear width", " ".join(k["M19"]["unresolved_reasons"]))
        self.assertEqual(jsonschema_lite.problems(p, "quantity_payload.v1"), [])
        # items that genuinely do not depend on G3's width stay confirmed: gross top rail, and leaf tension bars (leaves x 2)
        self.assertEqual((k["M05"]["status"], k["M05"]["quantity"]), ("confirmed", 550))
        self.assertEqual((k["M36"]["status"], k["M36"]["quantity"]), ("confirmed", 12))      # 6 leaves x 2 bars
        self.assertIn("QUANTITY_UNRESOLVED", {b["code"] for b in quantities.blockers(p)})

    def test_inferred_fact_makes_dependents_provisional_and_blocks_until_approved(self):
        s = sf.with_g3()
        s["fence_runs"][1]["length_lf"] = sf.fact(150.0, "inferred")
        p, _ = build(s)
        self.assertEqual(by_key(p)["M20"]["status"], "provisional")
        self.assertEqual(by_key(p)["M19"]["status"], "confirmed")
        self.assertIn("QUANTITY_PROVISIONAL", {b["code"] for b in quantities.blockers(p)})

    def test_human_resolution_is_attached_to_the_quantities_it_governs(self):
        s = sf.with_g3()
        s["fence_runs"][1]["length_lf"] = {"value": 150.0, "status": "human_resolved", "evidence": [{"doc_id": "human", "page": 1, "source_type": "human_resolution", "excerpt": "scaled"}]}
        res = {"/fence_runs/1/length_lf": {"exception_id": "EX-X", "by": "Pat Estimator", "note": "scaled from C101", "scope_version": 2}}
        p, _ = build(s, resolutions=res)
        m20 = by_key(p)["M20"]
        self.assertEqual((m20["status"], [r["exception_id"] for r in m20["approved_resolutions"]]), ("confirmed", ["EX-X"]))
        self.assertEqual(by_key(p)["M19"]["approved_resolutions"], [])

    def test_unapproved_ruleset_is_visible_in_the_payload_and_blockers(self):
        p, _ = build(sf.with_g3(), ruleset_approval=None)
        self.assertFalse(p["revision"]["ruleset"]["approved"])
        self.assertEqual([b["code"] for b in quantities.blockers(p)], ["QUANTITY_RULESET_NOT_APPROVED"])
        self.assertEqual(quantities.blockers(p, require_ruleset_approval=False), [])

    def test_missing_footing_facts_block_concrete_instead_of_defaulting(self):
        s = sf.with_g3()
        del s["global_requirements"]["footing_line_depth_in"]
        p, _ = build(s)
        self.assertEqual((by_key(p)["M40"]["quantity"], by_key(p)["M40"]["status"]), (None, "unresolved"))
        self.assertIn("line footing depth", by_key(p)["M40"]["unresolved_reasons"][0])


class CatalogGaps(unittest.TestCase):
    """What the catalog cannot price must be reported, not dropped or substituted."""

    def test_unknown_accessory_kind_is_still_reported_not_silently_dropped(self):
        s = sf.with_g3()
        s["accessories"].append({"accessory_id": "AC-BOLLARD", "kind": "bollard", "length_lf": sf.fact(10.0), "height_ft": sf.fact(3.0)})
        _, problems = build(s)
        self.assertEqual([p["code"] for p in problems], ["NO_ITEM_MAPPING"])
        self.assertIn("bollard", problems[0]["message"])

    def test_requirements_that_used_to_block_are_now_first_class_items_with_separate_units(self):
        s = sf.dp001_requirements(sf.with_g3())
        p, problems = build(s)
        k = by_key(p)
        self.assertEqual(problems, [])
        self.assertEqual((k["M42"]["quantity"], k["M42"]["uom"]), (150, "LF"))                          # fence guard, per linear foot
        self.assertEqual((k["M43"]["quantity"], k["M43"]["uom"]), (2, "EA"))                            # drop rods
        self.assertEqual((k["M44"]["quantity"], k["M44"]["uom"]), (2, "EA"))                            # ground sockets
        self.assertEqual((k["S01"]["quantity"], k["S01"]["uom"]), (q(p, "D04"), "EA"))                 # core drill EVERY footing hole
        self.assertEqual(k["S01"]["quantity"], 12 + 29 + 2 + 14)
        self.assertTrue(p["revision"]["sales_tax_exemption"]["applies"])
        self.assertEqual(p["revision"]["sales_tax_exemption"]["evidence_refs"][0]["fact_path"], "/global_requirements/owner_sales_tax_exempt")
        self.assertEqual(jsonschema_lite.problems(p, "quantity_payload.v1"), [])

    def test_core_drilling_is_zero_when_the_documents_say_no_and_unresolved_when_the_holes_are_unknown(self):
        p, _ = build(sf.with_g3())
        self.assertEqual((q(p, "S01"), p["revision"]["sales_tax_exemption"]["applies"]), (0, False))
        resolved = sf.dp001_requirements(sf.with_g3())
        s = copy.deepcopy(resolved)
        s["fence_runs"][0]["post"]["terminal_od_in"] = sf.fact(None, "unresolved")           # posts unknown => holes unknown
        p = quantities.build_payload(s, compute_takeoff(resolved), RS, ruleset_approval=APPROVAL)["payload"]
        self.assertEqual((by_key(p)["S01"]["quantity"], by_key(p)["S01"]["status"]), (None, "unresolved"))

    def test_gate_post_size_that_depends_on_the_opening_width_stays_unresolved_until_established(self):
        s = sf.with_g3()
        s["gates"][2]["gate_post_od_in"] = sf.fact(None, "unresolved")           # 32 31 13 2.1.B: G3 post size is confirmed with the opening width
        takeoff = compute_takeoff(sf.with_g3())
        p = quantities.build_payload(s, takeoff, RS, ruleset_approval=APPROVAL)["payload"]
        for key in ("M01", "M02", "M16", "M40", "D03"):
            self.assertEqual(by_key(p)[key]["status"], "unresolved", key)
        self.assertIn("G3 post size", " ".join(by_key(p)["M01"]["unresolved_reasons"]))
        s["gates"][2]["gate_post_od_in"] = sf.fact(2.875, "human_resolved")
        p, problems = build(s)
        self.assertEqual((by_key(p)["M01"]["status"], problems), ("confirmed", []))
        s["gates"][2]["gate_post_od_in"] = sf.fact(3.5)
        self.assertIn("mixed post sizes", build(s)[1][0]["message"])

    def test_post_sizes_with_no_catalog_family_block_every_family_dependent_item(self):
        s = sf.with_g3()
        s["fence_runs"][1]["post"]["line_od_in"] = sf.fact(3.5)
        p, problems = build(s)
        self.assertIn("NO_FAMILY_MAPPING", {x["code"] for x in problems})
        for key in ("M01", "M19", "M05", "D03", "M40"):
            self.assertEqual(by_key(p)[key]["status"], "unresolved", key)

    def test_height_with_no_catalog_fabric_is_unresolved(self):
        s = sf.with_g3()
        s["fence_runs"][1]["height_ft"] = sf.fact(6.0)
        p, _ = build(s)
        self.assertEqual(by_key(p)["M20"]["status"], "unresolved")
        self.assertIn("no catalog fabric", by_key(p)["M20"]["unresolved_reasons"][0])

    def test_unknown_gate_kind_and_uncatalogued_gate_height(self):
        s = sf.with_g3()
        s["gates"][0]["gate_kind"] = sf.fact("cantilever_slide")
        p, problems = build(s)
        self.assertIn("NO_ITEM_MAPPING", {x["code"] for x in problems})
        self.assertEqual(by_key(p)["M32"]["status"], "unresolved")
        s = sf.with_g3()
        s["gates"][0]["height_ft"] = sf.fact(8.0)
        p, _ = build(s)
        self.assertEqual(by_key(p)["M21"]["status"], "unresolved")

    def test_windscreen_height_outside_catalog(self):
        s = sf.with_g3()
        s["accessories"][0]["height_ft"] = sf.fact(6.0)
        self.assertEqual(by_key(build(s)[0])["M38"]["status"], "unresolved")


class ReviewRegressions(unittest.TestCase):
    def test_unpriced_scope_facts_are_reported(self):
        s = sf.with_g3(); s["fence_runs"][0]["fence_type"] = sf.fact("wood_privacy")
        self.assertIn("NO_ITEM_MAPPING", {x["code"] for x in build(s)[1]})
        self.assertEqual(build(sf.with_g3())[1], [])

    def test_bad_transom_height_is_never_a_silent_drop(self):
        from engine.guards import value_problems
        for bad in (-3, 0, "tall"):          # blocked at the Scope Gate guards, before any takeoff can run
            s = sf.with_g3(); s["gates"][0]["transom"] = {"height_ft": sf.fact(bad)}
            self.assertTrue(value_problems(s), bad)

    def test_sleeves_depend_on_heights_and_end_cups_on_the_continuity_decision(self):
        s = sf.with_g3(); s["gates"][0]["height_ft"] = sf.fact(7.0, "inferred")
        self.assertEqual(by_key(build(s)[0])["M07"]["status"], "provisional")
        yes, _ = build(sf.with_g3())
        s = sf.with_g3(); s["global_requirements"]["top_rail_continuous_across_gate_openings"] = sf.fact("no")
        no, _ = build(s)
        self.assertEqual(q(no, "M11") - q(yes, "M11"), 8)       # 4 gates x 2 posts: a continuous rail has no cup there

    def test_gate_leaf_fabric_does_not_depend_on_gate_kind(self):
        s = sf.with_g3(); s["gates"][0]["gate_kind"] = sf.fact(None, "unresolved")
        p, _ = build(s)
        self.assertEqual(by_key(p)["M21"]["status"], "confirmed")
        self.assertEqual(by_key(p)["M32"]["status"], "unresolved")


class Scenarios(unittest.TestCase):
    def test_base_and_alternate_are_complete_scenarios(self):
        s = sf.with_g3()
        scen = quantities.scenario_scopes(s)
        self.assertEqual(set(scen), {"BASE", "ALT-A1"})
        base, _ = build(scen["BASE"], scope_ref="BASE")
        alt, _ = build(scen["ALT-A1"], scope_ref="ALT-A1")
        self.assertEqual((q(base, "M20"), q(alt, "M20")), (150, 120))
        self.assertEqual((q(base, "M38"), q(alt, "M38")), (120, 90))
        self.assertEqual({i["scope_ref"] for i in alt["items"]}, {"ALT-A1"})
        self.assertEqual(q(base, "M19"), q(alt, "M19"))                 # untouched by the alternate
        self.assertEqual(s["fence_runs"][1]["length_lf"]["value"], 150.0)   # the working scope was not mutated by deriving the alternate

    def test_once_an_alternate_is_selected_base_is_not_invented(self):
        s = sf.with_g3()
        s["bid_structure"]["selected_bid"] = {"value": "ALT-A1", "status": "human_resolved"}
        self.assertEqual(set(quantities.scenario_scopes(s)), {"ALT-A1"})


class Revisions(unittest.TestCase):
    def test_newest_document_revision_governs_the_evidence_reference(self):
        s = sf.with_g3()
        s["gates"][1]["clear_width_ft"]["evidence"] = [sf.ev(doc="PLANS", page=2, sheet="C101", rev=0, excerpt="G2 6-0 single leaf"),
                                                       sf.ev(doc="ADD01", page=1, sheet="ADD-01", rev=1, excerpt="G2 12-0 double leaf")]
        p, _ = build(s)
        ref = next(r for r in by_key(p)["M21"]["source_evidence_refs"] if r["fact_path"] == "/gates/1/clear_width_ft")
        self.assertEqual((ref["doc_id"], ref["doc_revision"]), ("ADD01", 1))


if __name__ == "__main__":
    unittest.main()

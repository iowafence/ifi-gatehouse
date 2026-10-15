"""Preflight tests for Spatial Test 002 (base bid plan crop): crop completeness, oracle behavior, strict scoring, prompt hygiene, evidence preservation.
All 'model outputs' below are written by the tests."""
import hashlib, json, os, pathlib, re, sys, unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from ext import pdf_text, pipeline, spatial2 as S2, spatial_schema2 as SS, vector_inventory  # noqa: E402

PDF = HERE / "documents/dp001_ansi_b_v2_candidate/DP001_Drawings_IFB_Rev0_ANSI_B.pdf"
CFG = json.loads((HERE / "experiments/c101_base_plan_crop_ansi_b_v2.json").read_text())
CROP = CFG["crop_rect_norm_page"]
READY = PDF.exists()


def rel(r, c=CROP):
    if r[2] < c[0] or r[0] > c[2] or r[3] < c[1] or r[1] > c[3]:
        return "out"
    return "in" if r[0] >= c[0] and r[1] >= c[1] and r[2] <= c[2] and r[3] <= c[3] else "straddle"


def assoc(**kw):
    a = {"kind": "gate_tag", "label": "G1", "location_description": "on the fence line", "enclosure_side": "top", "visible_anchor": "G1", "uncertainty": "clear"}
    a.update(kw); return a


def resp(*assocs, unresolved=()):
    return json.dumps({"visual_associations": list(assocs), "unresolved": [{"description": d} for d in unresolved]})


@unittest.skipUnless(READY, "candidate PDF not staged")
class Crop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.words = pdf_text.word_inventory(PDF, 2)["words"]
        cls.paths = vector_inventory.vector_inventory(PDF, 2)["paths"]

    def test_no_text_is_clipped_by_the_crop_edges(self):
        self.assertEqual([w["text"] for w in self.words if rel(w["rect_norm"]) == "straddle"], [])

    def test_only_the_sheet_border_frame_crosses_the_crop_edges(self):
        s = [p for p in self.paths if rel(p["rect_norm"]) == "straddle"]
        self.assertEqual(len(s), 1)
        self.assertGreater(s[0]["w_pt"], 1100)                         # the page border rectangle, not fence geometry

    def test_everything_the_task_needs_is_inside(self):
        inside = [w["text"] for w in self.words if rel(w["rect_norm"]) == "in"]
        for needed in ("G1", "G2", "G3", "B", "A1", "BASE", "(FOUR", "COURTS)", "F501", "F502", "G26", "CL"):
            self.assertIn(needed, inside, needed)
        plan_area = [0.0, 0.07, 0.645, 0.69]                            # where the base bid plan is drawn (the legend swatch of the same weight lies below and to the right)
        heavy = [p for p in self.paths if p["stroke_width_pt"] >= CFG["enclosure_stroke_min_pt"] and rel(p["rect_norm"], plan_area) == "in"]
        self.assertGreaterEqual(len(heavy), 25)
        for p in heavy:                                                 # every perimeter-weight stroke of the plan is wholly inside the crop
            self.assertEqual(rel(p["rect_norm"]), "in", p["rect_norm"])

    def test_unrelated_content_is_excluded(self):
        inside = " ".join(w["text"] for w in self.words if rel(w["rect_norm"]) == "in")
        for excluded in ("GENERAL NOTES", "KEYNOTES", "ABBREVIATIONS", "LEGEND", "ALTERNATE", "(THREE-COURT", "IFI", "LABS", "REVISIONS", "SHEET NUMBER", "FENCE AND GATE REFERENCE"):
            self.assertNotIn(excluded, inside, excluded)
        o = S2.Oracle2(PDF, CFG)
        try:
            self.assertEqual(len(o.occurrences(r"COURT\s?[1-4]\b")), 4)         # only the base bid's four courts, none of the alternate's three
        finally:
            o.close()

    def test_the_crop_is_smaller_than_the_test_001_crop(self):
        t1 = json.loads((HERE / "experiments/spatial_c101_ansi_b_v2_PLAN.json").read_text())["crops"][0]["image_px"]
        t2 = json.loads((HERE / "runs_v2/dp001_ansi_b_v2_drawings/62ab61d7f255/plan2_c101_base_plan_150dpi/render_meta.json").read_text())["image_px"]
        self.assertLess(t2[0] * t2[1], t1[0] * t1[1])


@unittest.skipUnless(READY, "candidate PDF not staged")
class OracleBehavior(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.o = S2.Oracle2(PDF, CFG)

    @classmethod
    def tearDownClass(cls):
        cls.o.close()

    def test_gate_tag_sides_come_from_pdf_positions_relative_to_the_drawn_perimeter(self):
        tags = {t: sorted(l["side"] for l in v) for t, v in self.o.gate_tags().items()}
        self.assertEqual(sorted(tags), ["G1", "G2", "G3"])
        self.assertEqual(sum(len(v) for v in tags.values()), 4)
        self.assertEqual(self.o.fence_type_tags().keys(), {"A", "B"})

    def test_a_crop_declared_for_another_file_is_refused(self):
        other = pathlib.Path.home() / "Downloads/DP001_Public_Bid_Package_Rev0/DP001_Public_Bid_Package/DP001_Drawings_IFB_Rev0.pdf"
        if other.exists():
            with self.assertRaisesRegex(ValueError, "different file"):
                S2.Oracle2(other, CFG)

    def test_side_of_uses_the_nearest_edge_and_calls_far_points_interior(self):
        e = self.o.enclosure
        mid_x, mid_y = (e[0] + e[2]) / 2, (e[1] + e[3]) / 2
        self.assertEqual(self.o.side_of([mid_x, e[1] - 0.01, mid_x + 0.01, e[1]]), "top")
        self.assertEqual(self.o.side_of([e[0] + 0.01, mid_y, e[0] + 0.02, mid_y + 0.01]), "left")
        self.assertEqual(self.o.side_of([mid_x, mid_y, mid_x + 0.01, mid_y + 0.01]), "interior")

    def ev(self, text, normal=True):
        obj, cat, _ = pipeline.strict_parse(text)
        self.assertEqual(cat, "strict_ok")
        return S2.evaluate(obj, self.o, normal)

    def test_a_correct_answer_scores_correct_and_keeps_visual_relations_unverified(self):
        out = self.ev(resp(assoc(label="G3", enclosure_side="top", visible_anchor="G3"), assoc(), assoc(label="G2", enclosure_side="left", visible_anchor="G2"), assoc(label="G2", enclosure_side="right", visible_anchor="G2"),
                           assoc(kind="fence_type_tag", label="B", enclosure_side="interior", visible_anchor="B", location_description="the vertical divider between courts 3 and 4"),
                           assoc(kind="fence_type_tag", label="A", enclosure_side="right", visible_anchor="A", uncertainty="uncertain", location_description="right perimeter fence")))
        s = out["score"]
        self.assertTrue(s["1_valid_and_completed_json"])
        self.assertEqual(s["2_gate_tag_identification"]["correct"], ["G1", "G2", "G3"])
        self.assertEqual(s["2_gate_tag_identification"]["missed_by_model"], [])
        self.assertEqual(len(s["3_gate_side_relationships"]["confirmed"]), 4)
        self.assertEqual(s["3_gate_side_relationships"]["contradicted"], [])
        self.assertEqual(s["4_fence_type_to_drawn_element_associations"]["verified_by_pdf"], [])
        self.assertEqual(s["7_claims_the_oracle_cannot_establish"], [4, 5])
        self.assertEqual(s["6_explicit_uncertainties"]["associations_marked_uncertain_or_cannot_establish"], [5])

    def test_wrong_sides_invented_tags_and_unfound_anchors_are_counted_as_incorrect(self):
        out = self.ev(resp(assoc(enclosure_side="bottom"), assoc(label="G4", visible_anchor="G4"), assoc(label="G3", enclosure_side="top", visible_anchor="NOT PRINTED ANYWHERE")))
        s = out["score"]
        self.assertEqual(s["3_gate_side_relationships"]["contradicted"], [0])
        self.assertEqual(s["2_gate_tag_identification"]["not_in_crop"], ["G4"])
        self.assertEqual(s["5_incorrect_or_unsupported"]["contradicted_or_invalid"], [0, 1])
        self.assertEqual(s["5_incorrect_or_unsupported"]["anchor_not_found"], [1, 2])
        self.assertEqual(s["2_gate_tag_identification"]["missed_by_model"], ["G2"])

    def test_reporting_only_one_of_a_tags_two_places_is_not_an_error(self):
        out = self.ev(resp(assoc(label="G2", enclosure_side="right", visible_anchor="G2")))
        self.assertEqual(out["score"]["3_gate_side_relationships"]["confirmed"], [0])
        self.assertEqual(out["score"]["3_gate_side_relationships"]["contradicted"], [])

    def test_forbidden_or_unknown_fields_invalidate_the_association(self):
        out = self.ev(resp(assoc(opening_width="6'-0\""), assoc(quantity=4), assoc(extra_note="x"), assoc(kind="gate_size"), assoc(uncertainty="sure"), assoc(enclosure_side="north")))
        self.assertTrue(all(r["schema_problems"] for r in out["rows"]))
        self.assertFalse(out["score"]["1_valid_and_completed_json"])
        self.assertEqual(out["score"]["5_incorrect_or_unsupported"]["contradicted_or_invalid"], [0, 1, 2, 3, 4, 5])

    def test_empty_arrays_are_a_valid_completed_answer(self):
        out = self.ev(resp())
        self.assertTrue(out["score"]["1_valid_and_completed_json"])
        self.assertEqual(out["score"]["2_gate_tag_identification"]["missed_by_model"], ["G1", "G2", "G3"])

    def test_valid_shape_requires_visual_associations_first_and_both_arrays(self):
        for bad in ('{"unresolved": [], "visual_associations": []}', '{"visual_associations": []}', '{"visual_associations": {}, "unresolved": []}'):
            obj, cat, _ = pipeline.strict_parse(bad)
            self.assertFalse(S2.evaluate(obj, self.o, True)["shape_ok"], bad)

    def test_a_cancelled_or_truncated_stream_cannot_score_as_completed(self):
        full = resp(assoc())
        self.assertFalse(S2.evaluate(json.loads(full), self.o, outcome_normal=False)["score"]["1_valid_and_completed_json"])
        self.assertEqual(pipeline.strict_parse(full[:-9])[1], "strict_failed")          # truncated output never reaches evaluation


class PromptHygiene(unittest.TestCase):
    def test_the_prompt_is_a_visual_association_task_without_expected_answers(self):
        p = SS.PROMPT
        self.assertFalse(re.search(r"\bG[0-9]\b", p))                     # no tag names
        for leak in ("two places", "both sides", "left side", "right side", "top side", "G1", "G2", "G3", "Type A", "Type B", "176", "107", "answer", "expected", "perimeter fence"):
            self.assertNotIn(leak, p, leak)
        self.assertTrue(p.index('"visual_associations"') < p.index('"unresolved"'))
        for forbidden_request in ("extract every", "transcribe all"):
            self.assertNotIn(forbidden_request, p.lower())
        self.assertIn("Do not report dimensions", p)

    def test_the_prompt_is_not_the_test_001_prompt(self):
        from ext import spatial_schema as S1
        self.assertNotEqual(SS.PROMPT, S1.PROMPT)
        self.assertNotIn("text_facts", SS.PROMPT)


class Preservation(unittest.TestCase):
    def test_test_001_evidence_is_unchanged_and_read_only(self):
        man = json.loads((HERE / "runs_v2/FROZEN_TEST001.json").read_text())
        self.assertEqual(len(man["files"]), 6)
        for f, h in man["files"].items():
            self.assertEqual(hashlib.sha256((HERE / f).read_bytes()).hexdigest(), h, f)
        # The original working directory also made this evidence read-only (mode bits); git does not preserve them, so the hash equality above is the evidence here.

    def test_the_hold_is_in_place_before_the_live_step(self):
        self.assertTrue((HERE / "LIVE_CALLS_DISABLED").exists())


if __name__ == "__main__":
    unittest.main()

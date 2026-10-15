"""Offline tests of the pre-registered Spatial Test 003 scoring and plan integrity. Responses used here are SIMULATED TEST DATA written to exercise the scorer; they say nothing about any model.
Run: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=amd_experiment python3 -m unittest spatial_plan.test_plan -v  (from the repository root; needs requirements-amd.txt)"""
import hashlib, json, pathlib, sys, unittest
HERE = pathlib.Path(__file__).resolve().parent; WS = HERE.parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(WS))
import build_plan as BP, score as S
from oracle3 import Oracle3
H = lambda b: hashlib.sha256(b).hexdigest()
CFG = {"source_doc_id": "dp001_ansi_b_v2_drawings", "source_sha256": BP.PDF_SHA, "page_number": 2, "sheet": "C101", "crop_rect_norm_page": [0.03, 0.095, 0.645, 0.69], "enclosure_stroke_min_pt": 1.9, "edge_to_interior_threshold_in": 1.5}
g = lambda t, s="single_leaf_swing", u="clear": {"tag": t, "adjacent_symbol": s, "uncertainty": u}
ty = lambda t, e, u="clear": {"tag": t, "leader_ends_on": e, "uncertainty": u}

class Plan(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.o = Oracle3(BP.PDF, CFG); cls.plan = json.loads((HERE / "SPATIAL_PLAN_003.json").read_text())
    @classmethod
    def tearDownClass(cls): cls.o.close()

    def test_plan_is_unauthorized_and_makes_no_request(self):
        self.assertIn("NOT AUTHORIZED", self.plan["status"]); self.assertTrue((WS / "amd_experiment/LIVE_CALLS_DISABLED").exists())
        src = "".join(p.read_text() for p in HERE.glob("*.py") if p.name not in ("test_plan.py", "test_executor.py", "run_live_003.py"))
        for bad in ("amd_client", "streaming", "urllib", "http.client", "requests", "socket"): self.assertNotIn("import " + bad, src)

    def test_hashes_recompute(self):
        for c in self.plan["crops"]: self.assertEqual(H((WS / c["image_file"]).read_bytes()), c["image_sha256"])
        for f, h in self.plan["frozen_files_sha256"].items():
            if f != "spatial_plan/build_plan.py": self.assertEqual(H((WS / f).read_bytes()), h, f)
        self.assertEqual(H(BP.SYSTEM.encode()), self.plan["prompt"]["system_sha256"]); self.assertEqual(BP.PDF_SHA, self.plan["source"]["sha256"])
        for c in BP.CROPS: self.assertEqual(H(BP.USER.replace("__ORDER__", BP.ORDERS[c["ask"]]).encode()), next(x for x in self.plan["crops"] if x["crop_id"] == c["crop_id"])["user_prompt_sha256"])

    def test_prompt_has_no_expected_answers_and_no_transcription_request(self):
        u = BP.USER
        for leak in ("G1", "G2", "G3", "Court", "COURT", "diamond B", "interior divider B"): self.assertNotIn(leak, u.replace("a rounded label containing the letter G and a number", ""))
        self.assertIn("Do not transcribe", u); self.assertLessEqual(BP.SETTINGS["max_tokens"], 400); self.assertEqual((BP.SETTINGS["retries"], BP.SETTINGS["parallel_requests"]), (0, 0))

    def test_oracle_preflight_matches_the_drawing(self):
        self.assertEqual(self.o.leader_target("B")["element"], "interior_divider"); self.assertEqual(self.o.leader_target("A")["element"], "perimeter_fence"); self.assertEqual(self.o.leader_target("A")["enclosure_side"], "right")

    def test_scoring_correct_simulated_response(self):
        r1 = {"gate_tags": [g("G3"), g("G1")], "type_tags": [ty("B", "interior_divider")], "ambiguous": []}; s = S.score(r1, "r1_north_band_gates_and_tag", self.o); self.assertTrue(s["pass_for_this_crop"], s)
        self.assertEqual(s["4_adjacent_symbol"]["status"], "VISUAL_ONLY_HUMAN_REVIEW")
        s2 = S.score({"gate_tags": [g("G2", "double_leaf_swing")], "type_tags": [ty("A", "perimeter_fence")], "ambiguous": []}, "r2_east_edge_type_tag_and_gate", self.o); self.assertTrue(s2["pass_for_this_crop"], s2)

    def test_scoring_catches_wrong_order_wrong_leader_and_overconfidence(self):
        s = S.score({"gate_tags": [g("G1"), g("G3")], "type_tags": [ty("B", "perimeter_fence")], "ambiguous": []}, "r1_north_band_gates_and_tag", self.o)
        self.assertFalse(s["2_gate_order"]["correct"]); self.assertEqual(s["3_type_tags"][0]["verdict"], "CONTRADICTED_BY_VECTOR_GEOMETRY"); self.assertEqual(s["5_overconfidence_events"], 1); self.assertFalse(s["pass_for_this_crop"])
        s = S.score({"gate_tags": [g("G3"), g("G1")], "type_tags": [ty("B", "perimeter_fence", "uncertain")], "ambiguous": []}, "r1_north_band_gates_and_tag", self.o); self.assertEqual(s["5_overconfidence_events"], 0); self.assertFalse(s["pass_for_this_crop"], "wrong but humble is still not a pass")
        s = S.score({"gate_tags": [g("G3"), g("G1")], "type_tags": [ty("B", "unclear", "cannot_establish")], "ambiguous": [{"description": "leader end unclear"}]}, "r1_north_band_gates_and_tag", self.o); self.assertEqual(s["3_type_tags"][0]["verdict"], "NOT_VERIFIABLE"); self.assertFalse(s["pass_for_this_crop"])

    def test_shape_validation(self):
        self.assertTrue(S.validate_shape({"type_tags": []})); self.assertTrue(S.validate_shape({"gate_tags": [], "extra": 1}))
        self.assertTrue(S.validate_shape({"gate_tags": [{"tag": "G1", "adjacent_symbol": "arc", "uncertainty": "clear"}]})); self.assertTrue(S.validate_shape({"gate_tags": [], "ambiguous": [{"description": "x", "width": 12}]}))
        self.assertTrue(S.validate_shape({"gate_tags": [g("G1")] * 7})); self.assertEqual(S.validate_shape({"gate_tags": [g("G1")], "type_tags": [], "ambiguous": []}), [])
        self.assertFalse(S.score({"gate_tags": [], "bogus": 1}, "r3_west_edge_gate", self.o, True)["1_valid_completed_json"])
        self.assertFalse(S.score({"gate_tags": [g("G2")], "type_tags": [], "ambiguous": []}, "r3_west_edge_gate", self.o, outcome_normal=False)["1_valid_completed_json"], "a non-normal stream outcome is never valid")

if __name__ == "__main__":
    unittest.main()

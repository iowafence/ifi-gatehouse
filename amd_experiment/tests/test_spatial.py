"""Spatial verification oracle against the staged ANSI B v2 candidate PDF. Claims below are written by the test, not by a model."""
import json, pathlib, sys, unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from ext import spatial  # noqa: E402

PDF = HERE / "documents/dp001_ansi_b_v2_candidate/DP001_Drawings_IFB_Rev0_ANSI_B.pdf"
CFG = json.loads((HERE / "experiments/c101_zones_ansi_b_v2.json").read_text())


@unittest.skipUnless(PDF.exists(), "candidate PDF not staged")
class Oracle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.o = spatial.Oracle(PDF, 2, CFG)

    @classmethod
    def tearDownClass(cls):
        cls.o.close()

    def v(self, **c):
        return spatial.check_claim(c, self.o)["verdict"]

    def test_zone_sanity_the_plan_views_contain_the_court_labels_their_titles_promise(self):
        self.assertEqual(self.o.court_labels("base_bid_plan"), CFG["expected_sanity"]["court_labels_base_bid_plan"])
        self.assertEqual(self.o.court_labels("alternate_a1_plan"), CFG["expected_sanity"]["court_labels_alternate_a1_plan"])

    def test_zones_declared_for_one_file_refuse_another_revision(self):
        other = pathlib.Path.home() / "Downloads/DP001_Public_Bid_Package_Rev0/DP001_Public_Bid_Package/DP001_Drawings_IFB_Rev0.pdf"
        if other.exists():
            with self.assertRaisesRegex(ValueError, "different file"):
                spatial.Oracle(other, 2, CFG)

    def test_tag_claims_are_confirmed_or_contradicted_by_pdf_text_positions(self):
        self.assertEqual(self.v(claim_type="tag_in_view", tag="G1", view="base_bid"), "CONFIRMED_BY_PDF_TEXT_POSITION")
        self.assertEqual(self.v(claim_type="tag_in_view", tag="G2", view="alternate_a1", location_count=2), "CONFIRMED_BY_PDF_TEXT_POSITION")
        self.assertEqual(self.v(claim_type="tag_in_view", tag="G2", view="alternate_a1", location_count=1), "CONTRADICTED_BY_PDF")
        self.assertEqual(self.v(claim_type="tag_in_view", tag="G2", view="base_bid", location_count=3), "CONTRADICTED_BY_PDF")
        self.assertEqual(self.v(claim_type="tag_in_view", tag="G4", view="base_bid"), "MALFORMED")
        r = spatial.check_claim({"claim_type": "tag_in_view", "tag": "G2", "view": "base_bid"}, self.o)
        self.assertEqual(len(r["pdf_text_locations_norm_page"]), 2)

    def test_centerline_labels_are_not_counted_as_gate_tags(self):
        self.assertEqual(len(self.o.tag_locations("G3", "base_bid_plan")), 1)
        self.assertGreater(len(self.o.occurrences("G3", "base_bid_plan")), 1)           # 'CL G3' also exists

    def test_view_identity_needs_a_real_title_quote_naming_that_view(self):
        base = "SITE / FENCE PLAN — BASE BID (FOUR COURTS)"
        alt = "BID ALTERNATE A-1 — THREE-COURT ENCLOSURE (IN LIEU OF BASE BID)"
        self.assertEqual(self.v(claim_type="view_identity", view="base_bid", title_quote=base), "CONFIRMED_BY_PDF_TEXT")
        self.assertEqual(self.v(claim_type="view_identity", view="alternate_a1", title_quote=alt), "CONFIRMED_BY_PDF_TEXT")
        self.assertEqual(self.v(claim_type="view_identity", view="base_bid", title_quote="SITE PLAN — INVENTED TITLE"), "CONTRADICTED_BY_PDF")

    def test_detail_callouts_and_the_reference_table_come_from_the_text_layer(self):
        self.assertEqual(sorted(d["detail"] for d in self.o.detail_callouts()), ["1/F501", "2/F501", "3/F501", "4/F502"])
        self.assertEqual(self.v(claim_type="detail_callout", detail="4/F502"), "CONFIRMED_BY_PDF_TEXT_POSITION")
        self.assertEqual(self.v(claim_type="detail_callout", detail="5/F501"), "CONTRADICTED_BY_PDF")
        self.assertEqual(self.v(claim_type="reference_table_row", tag="A", detail="1/F501"), "CONFIRMED_BY_PDF_TEXT")
        self.assertEqual(self.v(claim_type="reference_table_row", tag="A", detail="2/F501"), "CONTRADICTED_BY_PDF")
        self.assertEqual(self.v(claim_type="reference_table_row", tag="G3", detail="3/F502"), "CONFIRMED_BY_PDF_TEXT")

    def test_gate_openings_and_any_measured_quantity_are_forbidden_inferences(self):
        for tag in ("G1", "G2", "G3"):
            self.assertEqual(self.v(claim_type="gate_opening", tag=tag, value="6'-0\""), "REJECTED_FORBIDDEN_INFERENCE")
        for key in ("quantity", "length_lf", "opening_width", "measured", "price"):
            self.assertEqual(self.v(claim_type="tag_in_view", tag="G1", view="base_bid", **{key: 1}), "REJECTED_FORBIDDEN_INFERENCE")
        self.assertIn("not shown", spatial.check_claim({"claim_type": "gate_opening", "tag": "G3"}, self.o)["why"])

    def test_visual_associations_are_never_confirmed_by_geometry_alone(self):
        self.assertEqual(self.v(claim_type="fence_type_present", view="base_bid", fence_type="B"), "NOT_VERIFIABLE_FROM_PDF")
        self.assertEqual(self.v(claim_type="something_else"), "NOT_VERIFIABLE_FROM_PDF")

    def test_garbage_claims_never_raise(self):
        for junk in (None, 5, {}, {"claim_type": None}, {"claim_type": "tag_in_view"}, {"claim_type": "detail_callout", "detail": None}):
            self.assertIn(spatial.check_claim(junk, self.o)["verdict"], ("MALFORMED", "CONTRADICTED_BY_PDF"))


class Documents(unittest.TestCase):
    def setUp(self):
        self.by = {d["doc_id"]: d for d in json.loads((HERE / "manifests/experiment_manifest.json").read_text())["documents"]}

    def test_candidate_identities_are_registered_exactly_and_separately(self):
        want = {"dp001_ansi_b_v2_drawings": "62ab61d7f2558245f4a6f1708d9320a49e66fd28bf829a2329be5b79db9ac525", "dp001_ansi_b_v2_freecad": "7c17f34688f956b63b4a56736847bda9a2c89fe9f28035b8d8dca15d177ac075",
                "dp001_ansi_b_v2_bid_zip": "5ff1d3198f6e589dbd404be40438ca4ec666133bbeb67e2aa03ad21f5dbaf8c5", "dp001_ansi_d_coordinated_parent": "ddf53f79bce30423d33479f75c2f229a51899e2e5d30377163e328cd53685aa3",
                "dp001_addendum_01_ansi_b_pkg": "390ffe093029fb89a9e498da4ba4e46f5600690bc05ecc7717c91607fc185deb", "c101_34x22_rev0": "fc9e41b07b503bc99a6344da735cefdcc1e8c64e2f33c25c2c82174737e649c1"}
        for k, h in want.items():
            self.assertEqual(self.by[k]["sha256"], h, k)
        self.assertEqual(len({self.by[k]["sha256"] for k in want}), len(want))
        for k in ("dp001_ansi_b_v2_drawings", "dp001_ansi_b_v2_freecad", "dp001_ansi_b_v2_bid_zip", "dp001_ansi_d_coordinated_parent"):
            self.assertFalse(self.by[k]["canonical"], k)

    def test_the_frozen_pre_coordination_source_and_the_coordinated_parent_are_different_documents(self):
        self.assertNotEqual(self.by["c101_34x22_rev0"]["sha256"], self.by["dp001_ansi_d_coordinated_parent"]["sha256"])
        self.assertEqual(self.by["c101_34x22_rev0"]["status"], "available")
        self.assertEqual(self.by["dp001_loose_downloads_copy"]["status"], "excluded_provenance_unconfirmed")      # preserved unchanged
        self.assertEqual(self.by["dp001_ansi_d_coordinated_parent"]["same_bytes_as"], "dp001_loose_downloads_copy")

    @unittest.skipUnless((HERE / "documents/dp001_ansi_b_v2_candidate/DP001_Master_ANSI_B.FCStd").exists(), "the staged ZIP/FreeCAD originals are not published (only the PDFs, under samples/public-demo/)")
    def test_addendum_is_its_own_controlling_document_and_superseded_files_cannot_be_used(self):
        self.assertEqual(self.by["dp001_addendum_01_ansi_b_pkg"]["role"], "controlling_addendum")
        self.assertNotEqual(self.by["dp001_addendum_01_ansi_b_pkg"]["sha256"], self.by["dp001_ansi_b_v2_drawings"]["sha256"])
        sys.path.insert(0, str(HERE))
        from ext import pipeline
        m = json.loads((HERE / "manifests/experiment_manifest.json").read_text())
        for k in ("dp001_ansi_b_v1_superseded_drawings", "dp001_ansi_b_v1_superseded_zip", "dp001_loose_downloads_copy", "ansi_b_11x17_pending"):
            with self.assertRaises(PermissionError):
                pipeline.load_document(m, k)
        self.assertEqual(pipeline.load_document(m, "dp001_ansi_b_v2_drawings")["sha256"], "62ab61d7f2558245f4a6f1708d9320a49e66fd28bf829a2329be5b79db9ac525")

    @unittest.skipUnless((HERE / "documents/dp001_ansi_b_v2_candidate/DP001_Master_ANSI_B.FCStd").exists(), "the staged ZIP/FreeCAD originals are not published (only the PDFs, under samples/public-demo/)")
    def test_staged_files_are_read_only_and_match_the_manifest(self):
        import hashlib, os
        for k in ("dp001_ansi_b_v2_drawings", "dp001_ansi_b_v2_freecad", "dp001_ansi_b_v2_bid_zip", "dp001_addendum_01_ansi_b_pkg", "dp001_ansi_d_coordinated_parent"):
            p = pathlib.Path(self.by[k]["path"])
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), self.by[k]["sha256"], k)
            self.assertFalse(os.access(p, os.W_OK), k)

    def test_live_calls_remain_on_hold(self):
        self.assertTrue((HERE / "LIVE_CALLS_DISABLED").exists())


if __name__ == "__main__":
    unittest.main()

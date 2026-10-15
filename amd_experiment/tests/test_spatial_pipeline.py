"""process_spatial keeps text quotations and visual associations apart, and never promotes a visual claim to a fact. Model outputs here are written by the test."""
import json, pathlib, sys, unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from ext import render, spatial, spatial_schema as S  # noqa: E402

PDF = HERE / "documents/dp001_ansi_b_v2_candidate/DP001_Drawings_IFB_Rev0_ANSI_B.pdf"
CFG = json.loads((HERE / "experiments/c101_zones_ansi_b_v2.json").read_text())
REGION = [0.02, 0.10, 0.64, 0.98]
SRC = {"doc_id": "dp001_ansi_b_v2_drawings", "source_document": PDF.name, "source_sha256": CFG["source_sha256"], "page_number": 2}


def tf(**kw):
    f = {"fact_id": "T1", "category": "gate", "key": "gate location symbol", "value": "GATE LOCATION — SYMBOL ONLY, N.T.S.", "unit": None,
         "evidence_text": "GATE LOCATION — SYMBOL ONLY, N.T.S.", "location_hint": "legend", "dimension_basis": None, "confidence": 0.9, "status": "observed"}
    f.update(kw); return f


def va(**kw):
    a = {"assoc_id": "V1", "claim_type": "tag_in_view", "view": "base_bid", "tag": "G1", "detail": None, "fence_type": None, "title_quote": None, "location_count": 1, "anchor_text": "G1",
         "description": "Gate tag G1 on the north side", "basis": "visual", "confidence": 0.8}
    a.update(kw); return a


def doc(texts, vis):
    return json.dumps({"document": {"title": None, "sheet_number": None, "revision": None, "date": None}, "text_facts": texts, "visual_associations": vis})


@unittest.skipUnless(PDF.exists(), "candidate PDF not staged")
class SpatialPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.o = spatial.Oracle(PDF, 2, CFG)
        cls.page = cls.o.page

    @classmethod
    def tearDownClass(cls):
        cls.o.close()

    def run_(self, texts, vis):
        return S.process_spatial(doc(texts, vis), self.page, SRC, REGION, self.o)

    def test_text_quotations_and_visual_associations_are_kept_in_separate_structures(self):
        out = self.run_([tf()], [va()])
        self.assertEqual(len(out["text_facts_pipeline"]["stage3"]["accepted_facts"]), 1)
        self.assertEqual(out["visual_associations"][0]["pdf_check"]["verdict"], "CONFIRMED_BY_PDF_TEXT_POSITION")
        self.assertNotIn("visual_associations", out["text_facts_pipeline"]["stage3"])

    def test_a_true_looking_but_wrong_visual_claim_is_contradicted_while_the_text_fact_stays_accepted(self):
        out = self.run_([tf()], [va(tag="G2", view="alternate_a1", location_count=1)])
        self.assertEqual(out["visual_associations"][0]["pdf_check"]["verdict"], "CONTRADICTED_BY_PDF")
        self.assertEqual(len(out["text_facts_pipeline"]["stage3"]["accepted_facts"]), 1)

    def test_an_invented_text_quote_is_not_accepted_but_does_not_poison_valid_visual_checks(self):
        out = self.run_([tf(evidence_text="GATE G3 IS 12'-0\" WIDE", value="12'-0\"", unit="ft", category="gate", dimension_basis="stated_text")], [va(tag="G3", location_count=1)])
        self.assertEqual(out["text_facts_pipeline"]["stage3"]["accepted_facts"], [])
        self.assertEqual(out["visual_associations"][0]["pdf_check"]["verdict"], "CONFIRMED_BY_PDF_TEXT_POSITION")

    def test_gate_opening_claims_and_quantities_in_associations_are_rejected(self):
        out = self.run_([], [va(claim_type="gate_opening", tag="G3"), va(assoc_id="V2", quantity=4), va(assoc_id="V3", claim_type="fence_type_present", fence_type="B", tag=None, location_count=None)])
        self.assertEqual([x["pdf_check"]["verdict"] for x in out["visual_associations"]], ["REJECTED_FORBIDDEN_INFERENCE", "REJECTED_FORBIDDEN_INFERENCE", "NOT_VERIFIABLE_FROM_PDF"])
        self.assertTrue(all(x["never_a_quantity"] and x["informational_only"] for x in out["visual_associations"]))

    def test_a_quote_that_exists_on_the_page_but_outside_the_requested_crop_is_not_accepted(self):
        out = self.run_([tf(evidence_text="GATE OPENING SIZES ARE NOT SHOWN ON THIS SHEET.", value="GATE OPENING SIZES ARE NOT SHOWN ON THIS SHEET.")], [])
        self.assertEqual(out["text_facts_pipeline"]["stage3"]["accepted_facts"], [])
        self.assertEqual(len(out["text_facts_pipeline"]["stage3"]["outside_region"]), 1)

    def test_malformed_or_wrongly_shaped_output_yields_nothing(self):
        for bad in ('{"text_facts": [], "visual_associations": [', json.dumps({"facts": []}), json.dumps({"text_facts": {}, "visual_associations": []}), "```json\n{}\n```"):
            out = S.process_spatial(bad, self.page, SRC, REGION, self.o)
            self.assertIsNone(out["text_facts_pipeline"])
            self.assertEqual(out["visual_associations"], [])

    def test_the_prompt_contains_no_expected_answers_or_hints_about_what_is_missing(self):
        p = S.PROMPT.lower()
        for leak in ("g3 is", "not specified", "unresolved gate", "planted", "answer key", "12'-0", "6'-0", "two locations", "alternate a-1 has"):
            self.assertNotIn(leak, p)


if __name__ == "__main__":
    unittest.main()

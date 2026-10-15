"""Offline tests of the deterministic validator and the credential handling. The page text below is invented for the tests; no model is called."""
import json, os, pathlib, stat, sys, tempfile, unittest
from fractions import Fraction

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ext import amd_client, validator as v  # noqa: E402

PAGE_TEXT = """SITE PLAN SHEET Z101  REV 0  DATE 2026-01-02
8 FT CHAIN LINK FENCE, SEE DETAIL 1/Z501
GATE A: 4'-0" CLEAR OPENING, SINGLE LEAF
POST SPACING 10'-0" O.C. MAXIMUM  TOP RAIL 1-5/8" OD"""


class FakePage:
    text = PAGE_TEXT
    def find_rects(self, quote):
        i = PAGE_TEXT.lower().find(quote.lower())
        return [] if i < 0 else [[0.1, 0.1 + 0.05 * PAGE_TEXT[:i].count("\n"), 0.5, 0.15 + 0.05 * PAGE_TEXT[:i].count("\n")]]


def fact(**kw):
    f = {"fact_id": "F1", "category": "dimension", "key": "gate clear opening", "value": "4'-0\"", "unit": None, "evidence_text": "GATE A: 4'-0\" CLEAR OPENING",
         "location_hint": "plan", "bbox_norm": None, "dimension_basis": "stated_text", "confidence": 0.9, "status": "observed", "note": None}
    f.update(kw)
    return f


def doc(*facts, **kw):
    return {"document": {"title": "Site plan", "sheet_number": "Z101", "revision": "0", "date": "2026-01-02"}, "facts": list(facts), "conflicts_or_ambiguities": [], **kw}


SRC = {"source_document": "x.pdf", "source_sha256": "0" * 64, "page_number": 1}


class Lengths(unittest.TestCase):
    def test_exact_parsing(self):
        cases = {"4'-0\"": 48, "12'-0\"": 144, "7'": 84, "84\"": 84, "6 FT": 72, "2-3/8\"": Fraction(19, 8), "1 7/8 IN": Fraction(15, 8), "3'-6\"": 42, "1-5/8\"": Fraction(13, 8)}
        for text, inches in cases.items():
            with self.subTest(text=text):
                self.assertEqual(v.parse_length(text), Fraction(inches))

    def test_non_lengths_and_bare_numbers_need_a_unit(self):
        self.assertIsNone(v.parse_length("EA"))
        self.assertIsNone(v.parse_length("12"))
        self.assertEqual(v.parse_length("12", "ft"), 144)

    def test_lengths_in_evidence(self):
        self.assertIn(Fraction(120), v.lengths_in(PAGE_TEXT.split("\n")[2 + 1]))     # post spacing 10'-0"
        self.assertIn(Fraction(96), v.lengths_in("8 FT CHAIN LINK FENCE"))


class Normalization(unittest.TestCase):
    def test_the_text_layers_wrapped_hyphen_marker_matches_a_real_hyphen(self):
        page_text = "9. CONTRACT LABOR\ufffeCOMPLIANCE DOCUMENTS APPLY"
        self.assertEqual(v.text_match("contract labor-compliance documents apply", page_text), "exact")
        self.assertIsNone(v.text_match("contract labor compliance documents apply and more words here", page_text))

    def test_a_paraphrase_that_drops_words_is_still_unverified(self):
        self.assertIsNone(v.text_match("MUNICIPAL RECREATION DEMONSTRATION PACKAGE", "PROJECT MUNICIPAL RECREATION COURTS DEMONSTRATION PACKAGE 001"))


class Structure(unittest.TestCase):
    def test_valid_document_has_no_problems(self):
        self.assertEqual(v.validate_structure(doc(fact())), [])

    def test_each_defect_is_reported(self):
        bad = [fact(category="bogus"), fact(fact_id="F2", status="maybe"), fact(fact_id="F3", confidence=1.5), fact(fact_id="F4", bbox_norm=[0.5, 0.5, 0.2, 0.9]),
               fact(fact_id="F5", dimension_basis=None), fact(fact_id="F6", status="observed", evidence_text=None, dimension_basis=None, category="note"),
               fact(fact_id="F7", status="unresolved", value="4"), fact(fact_id="F1")]
        paths = {p["path"] + ":" + p["problem"] for p in v.validate_structure(doc(*bad))}
        for needle in ("category", "status", "confidence", "bbox_norm", "dimension_basis", "evidence_text", "value", "duplicate fact_id"):
            self.assertTrue(any(needle in p for p in paths), needle)

    def test_non_objects_are_rejected_not_crashed(self):
        for junk in (None, [], "text", {"facts": "x"}, {"facts": [1, None]}):
            self.assertTrue(v.validate_structure(junk))


class Evidence(unittest.TestCase):
    def run_one(self, f):
        n, r = v.validate(doc(f), FakePage(), SRC)
        return n["facts"][0], r

    def test_real_quote_is_verified_and_observed(self):
        nf, r = self.run_one(fact())
        self.assertEqual((nf["verification"]["text"], nf["effective_status"]), ("VERIFIED_EXACT", "observed"))
        self.assertTrue(nf["value_check"]["value_in_evidence"])
        self.assertEqual(r["evidence_verified_rate"], 1.0)

    def test_invented_quote_stays_unverified_even_if_the_model_says_observed(self):
        nf, r = self.run_one(fact(evidence_text="GATE B: 6'-0\" CLEAR OPENING, DOUBLE LEAF", value="6'-0\""))
        self.assertEqual((nf["verification"]["text"], nf["effective_status"], nf["claimed_status"]), ("UNVERIFIED", "UNVERIFIED", "observed"))
        self.assertEqual(r["evidence_verified_rate"], 0.0)

    def test_value_that_is_not_in_a_real_quote_is_flagged_and_not_observed(self):
        nf, r = self.run_one(fact(value="6'-0\""))                                    # the quote is real, the number is not what it says
        self.assertEqual(nf["verification"]["text"], "VERIFIED_EXACT")
        self.assertFalse(nf["value_check"]["value_in_evidence"])
        self.assertEqual(nf["effective_status"], "UNVERIFIED")
        self.assertEqual(r["value_not_in_evidence"], ["F1"])

    def test_whitespace_case_and_quote_style_do_not_defeat_verification(self):
        nf, _ = self.run_one(fact(evidence_text="gate a:   4’-0”  clear opening"))
        self.assertEqual(nf["verification"]["text"], "VERIFIED_EXACT")

    def test_inferred_and_unresolved_are_never_promoted(self):
        nf, _ = self.run_one(fact(status="inferred", dimension_basis="visual_estimate"))
        self.assertEqual(nf["effective_status"], "inferred (unverified)")
        nf, _ = self.run_one(fact(status="unresolved", value=None, evidence_text=None, dimension_basis="stated_text"))
        self.assertEqual(nf["effective_status"], "unresolved")

    def test_claimed_box_is_checked_against_the_text_layer(self):
        good, _ = self.run_one(fact(bbox_norm=[0.08, 0.18, 0.52, 0.27]))
        self.assertIn(good["verification"]["bbox"], ("VERIFIED",))
        coarse, _ = self.run_one(fact(bbox_norm=[0.0, 0.0, 1.0, 0.5]))          # overlaps the text but is a coarse band, not a placement
        self.assertEqual(coarse["verification"]["bbox"], "MISMATCH")
        bad, r = self.run_one(fact(bbox_norm=[0.8, 0.8, 0.95, 0.95]))
        self.assertEqual(bad["verification"]["bbox"], "MISMATCH")
        self.assertEqual(r["bbox_mismatch"], ["F1"])
        none, _ = self.run_one(fact(evidence_text="NOT ON THE PAGE AT ALL", bbox_norm=[0.1, 0.1, 0.2, 0.2], value="x"))
        self.assertEqual(none["verification"]["bbox"], "UNVERIFIED")

    def test_provenance_is_injected_by_the_harness_not_taken_from_the_model(self):
        f = fact(); f["source_sha256"] = "f" * 64
        nf, _ = self.run_one(f)
        self.assertEqual((nf["source_sha256"], nf["source_document"], nf["page_number"]), ("0" * 64, "x.pdf", 1))


class CrossFact(unittest.TestCase):
    def test_duplicates_and_contradictions(self):
        a, b = fact(), fact(fact_id="F2")
        c = fact(fact_id="F3", value="3'-0\"", evidence_text="x")
        _, r = v.validate(doc(a, b, c), FakePage(), SRC)
        self.assertEqual(r["duplicates"], [{"fact_id": "F2", "duplicate_of": "F1"}])
        self.assertEqual(len(r["contradictions"]), 1)

    def test_equivalent_spellings_of_one_length_are_not_a_contradiction(self):
        a, b = fact(), fact(fact_id="F2", value="48 in", evidence_text="4'-0\" CLEAR")
        self.assertEqual(v.find_contradictions([a, b]), [])

    def test_visual_estimates_are_listed(self):
        _, r = v.validate(doc(fact(dimension_basis="visual_estimate", status="inferred")), FakePage(), SRC)
        self.assertEqual(r["visual_estimates"], ["F1"])

    def test_missing_document_fields_and_sheet_check(self):
        d = doc(fact()); d["document"]["revision"] = None
        _, r = v.validate(d, FakePage(), SRC)
        self.assertEqual(r["document_fields_missing"], ["revision"])
        self.assertTrue(r["sheet_number_found_on_page"])
        d["document"]["sheet_number"] = "Q999"
        self.assertFalse(v.validate(d, FakePage(), SRC)[1]["sheet_number_found_on_page"])

    def test_garbage_input_never_raises(self):
        for junk in (None, [], {"facts": [None, 3, {"fact_id": "a"}]}, {"facts": [{"fact_id": "a", "evidence_text": 5, "value": object.__class__}]}):
            n, r = v.validate(junk if junk is not None else {}, FakePage(), SRC)
            self.assertFalse(r["structurally_valid"] and bool(junk))


class Credentials(unittest.TestCase):
    def test_missing_key_sends_nothing_and_says_so(self):
        old = {k: os.environ.pop(k, None) for k in (amd_client.KEY_VAR, amd_client.BASE_VAR)}
        saved = amd_client.SECRET_FILE
        amd_client.SECRET_FILE = pathlib.Path("/nonexistent/none.env")
        try:
            with self.assertRaises(amd_client.NoCredential):
                amd_client.load_config()
        finally:
            amd_client.SECRET_FILE = saved
            for k, val in old.items():
                if val is not None:
                    os.environ[k] = val

    def test_secret_file_must_be_private(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "k.env"
            p.write_text(f"{amd_client.KEY_VAR}=abc\n")
            p.chmod(0o644)
            saved, amd_client.SECRET_FILE = amd_client.SECRET_FILE, p
            try:
                with self.assertRaises(amd_client.NoCredential):
                    amd_client.load_config()
                p.chmod(0o600)
                key, base = amd_client.load_config()
                self.assertEqual(key, "abc") if not os.environ.get(amd_client.KEY_VAR) else None
            finally:
                amd_client.SECRET_FILE = saved

    def test_redaction_removes_the_key_everywhere(self):
        self.assertNotIn("sekret-key-123", amd_client.redact("Authorization: Bearer sekret-key-123 failed", "sekret-key-123"))


class PublicPdf(unittest.TestCase):
    PDF = pathlib.Path.home() / "Downloads/DP001_Public_Bid_Package_Rev0/DP001_Public_Bid_Package/DP001_Drawings_IFB_Rev0.pdf"

    @unittest.skipUnless(PDF.exists(), "public package PDF not present")
    def test_render_and_text_layer_agree_with_the_file(self):
        from ext import render
        with tempfile.TemporaryDirectory() as d:
            m = render.render_page(self.PDF, 2, 40, pathlib.Path(d) / "p.png")
            self.assertEqual(m["source_sha256"], render.sha256_file(self.PDF))
            self.assertEqual(m["page_number"], 2)
            self.assertEqual(m["page_size_pt"], [2448.0, 1584.0])
            pg = render.PdfiumPageText(self.PDF, 2)
            try:
                self.assertGreater(len(pg.text), 1000)
                first_line = next(l for l in pg.text.splitlines() if len(l.strip()) > 15)
                self.assertTrue(pg.find_rects(first_line.strip()))
            finally:
                pg.close()


if __name__ == "__main__":
    unittest.main()


class SpacingNormalization(unittest.TestCase):
    from ext import normalize as nz

    def test_printed_ten_foot_on_center_maximum_is_a_maximum_spacing_constraint_not_a_length(self):
        r = self.nz.normalize_spacing("SPACE LINE POSTS EQUALLY BETWEEN CORNER, TERMINAL AND GATE POSTS AT 10'-0\" O.C. MAXIMUM.")
        self.assertEqual(len(r), 1)
        c = r[0]
        self.assertEqual((c["kind"], c["basis"], c["bound"], c["value_inches"], c["value_feet"], c["unit"]), ("spacing_constraint", "on_center", "maximum", "120", "10", "ft"))
        self.assertFalse(c["is_measured_length"])
        self.assertTrue(c["informational_only"])
        self.assertEqual(c["applies_to"], "line posts equally between corner, terminal and gate posts")
        self.assertIn("no farther apart", c["meaning"])

    def test_spellings_and_bounds(self):
        cases = {"POSTS AT 8'-0\" O.C.": ("stated_without_bound", "96"), "10'-6\" O.C. MIN.": ("minimum", "126"), "SPACED AT 10 FT ON CENTER MAX": ("maximum", "120"),
                 "AT 10’-0” O.C. MAXIMUM": ("maximum", "120")}
        for text, (bound, inches) in cases.items():
            with self.subTest(text=text):
                c = self.nz.normalize_spacing(text)
                self.assertEqual((c[0]["bound"], c[0]["value_inches"]), (bound, inches))

    def test_lengths_that_are_not_spacing_rules_are_not_normalized(self):
        for text in ("TYPE A FENCE LENGTH 400'-0\"", "GATE G1 4'-0\" CLEAR OPENING", "10'-0\" PERIMETER CHAIN LINK FENCE", "CORNER POSTS O.C."):
            with self.subTest(text=text):
                self.assertEqual(self.nz.normalize_spacing(text), [])

    def test_the_constraint_never_equals_a_quantity(self):
        c = self.nz.normalize_spacing("AT 10'-0\" O.C. MAXIMUM")[0]
        for forbidden in ("quantity", "count", "length_lf", "price"):
            self.assertNotIn(forbidden, c)

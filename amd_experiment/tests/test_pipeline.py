"""Pipeline rules: strict JSON gate, evidence-verified acceptance, quarantined salvage, PDF-derived positions, manifest separation, live-call hold."""
import hashlib, json, pathlib, sys, tempfile, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ext import pipeline as P  # noqa: E402

TEXT = """GENERAL NOTES
4. SPACE LINE POSTS EQUALLY BETWEEN CORNER, TERMINAL AND GATE POSTS AT 10'-0" O.C. MAXIMUM.
3. GATE OPENING SIZES ARE NOT SHOWN ON THIS SHEET.
REVISIONS 0 10/12/26 ISSUED FOR BID
FOUR-COURT FACILITY OUTSIDE THE REGION NOTE"""
RECTS = {"SPACE LINE POSTS EQUALLY BETWEEN CORNER, TERMINAL AND GATE POSTS AT 10'-0\" O.C. MAXIMUM.": [[0.70, 0.10, 0.90, 0.12]],
         "GATE OPENING SIZES ARE NOT SHOWN ON THIS SHEET.": [[0.70, 0.13, 0.90, 0.15]],
         "FOUR-COURT FACILITY OUTSIDE THE REGION NOTE": [[0.05, 0.80, 0.30, 0.82]]}
REGION = [0.65, 0.05, 0.95, 0.25]
SRC = {"doc_id": "d", "source_document": "x.pdf", "source_sha256": "a" * 64, "page_number": 1}


class Page:
    text = TEXT
    def find_rects(self, quote):
        for k, v in RECTS.items():
            if quote.lower() in k.lower():
                return v
        return []


def fact(**kw):
    f = {"fact_id": "F1", "category": "dimension", "key": "post spacing", "value": "10'-0\"", "unit": "ft", "evidence_text": "SPACE LINE POSTS EQUALLY BETWEEN CORNER, TERMINAL AND GATE POSTS AT 10'-0\" O.C. MAXIMUM.",
         "location_hint": "notes", "bbox_norm": [0.0, 0.0, 0.1, 0.1], "dimension_basis": "stated_text", "confidence": 0.9, "status": "observed", "note": None}
    f.update(kw)
    return f


def content(*facts):
    return json.dumps({"document": {"title": None, "sheet_number": None, "revision": None, "date": None}, "facts": list(facts), "conflicts_or_ambiguities": []})


def run(*facts, region=REGION):
    return P.process_content(content(*facts), Page(), SRC, region)


class RequestBuilding(unittest.TestCase):
    def test_json_mode_adds_the_documented_response_format_only_when_asked(self):
        a = P.build_request("m", [], 500, 0.0, json_mode=True)
        b = P.build_request("m", [], 500, 0.0, json_mode=False)
        self.assertEqual(a["response_format"], {"type": "json_object"})
        self.assertNotIn("response_format", b)
        self.assertEqual(set(b), {"model", "messages", "max_tokens", "temperature"})

    def test_extra_cannot_silently_override_a_documented_field(self):
        with self.assertRaises(ValueError):
            P.build_request("m", [], 500, 0.0, extra={"max_tokens": 9})
        self.assertEqual(P.build_request("m", [], 500, 0.0, extra={"top_p": 0.9})["top_p"], 0.9)


class StrictParsing(unittest.TestCase):
    def test_only_a_single_clean_json_object_passes(self):
        self.assertEqual(P.strict_parse('{"a": 1}')[1], "strict_ok")
        for bad, cat in (('```json\n{"a":1}\n```', "markdown_fence"), ('{"a":1} trailing', "strict_failed"), ('{"a":1, "a":2}', "strict_failed"), ('{"a": NaN}', "strict_failed"),
                         ('[1,2]', "wrong_top_level_type"), ('{"key":Post spacing", "": 1}', "strict_failed"), ("", "strict_failed"), (None, "not_a_string")):
            with self.subTest(bad=str(bad)[:25]):
                self.assertEqual(P.strict_parse(bad)[1], cat)
                self.assertIsNone(P.strict_parse(bad)[0])


class AcceptanceRules(unittest.TestCase):
    def test_a_valid_fact_with_verbatim_evidence_is_accepted_with_pdf_derived_position(self):
        out = run(fact())
        acc = out["stage3"]["accepted_facts"]
        self.assertEqual([f["fact_id"] for f in acc], ["F1"])
        self.assertEqual(acc[0]["position_source"], "pdf_text_layer")
        self.assertEqual(acc[0]["pdf_text_locations_norm_page"], [[0.70, 0.10, 0.90, 0.12]])
        self.assertEqual((acc[0]["origin"], acc[0]["verification"]), ("strict_parse", "VERIFIED_EXACT"))
        self.assertEqual(acc[0]["source_sha256"], "a" * 64)

    def test_valid_json_does_not_make_an_invented_quote_true(self):
        out = run(fact(evidence_text="GATE G9 IS 20'-0\" WIDE", value="20'-0\""))
        self.assertEqual(out["strict_parse"]["category"], "strict_ok")
        self.assertEqual(out["stage3"]["accepted_facts"], [])
        self.assertEqual(len(out["stage3"]["unverified"]), 1)

    def test_a_real_quote_with_a_value_not_in_it_is_not_accepted(self):
        out = run(fact(value="12'-0\""))
        self.assertEqual(out["stage3"]["accepted_facts"], [])
        self.assertEqual(out["stage3"]["unverified"][0]["value_check"]["value_in_evidence"], False)

    def test_model_boxes_are_never_authoritative(self):
        wild = run(fact(bbox_norm=[0.9, 0.9, 0.99, 0.99]))
        none = run(fact(bbox_norm=None))
        broken = run(fact(bbox_norm=[0.5, 0.5, 0.1, 0.1]))        # structurally invalid box
        for out in (wild, none, broken):
            self.assertEqual(out["stage3"]["accepted_facts"][0]["pdf_text_locations_norm_page"], [[0.70, 0.10, 0.90, 0.12]])
            self.assertNotIn("bbox_norm", out["stage3"]["accepted_facts"][0])
        self.assertEqual(wild["stage2"]["candidates"][0]["model_claimed_bbox_unverified"], [0.9, 0.9, 0.99, 0.99])

    def test_structurally_bad_facts_are_rejected_with_reasons_and_never_repaired(self):
        out = run(fact(), fact(fact_id="F2", status="maybe"), fact(fact_id="F3", confidence=7), fact(fact_id="F4", category="dimension", dimension_basis=None))
        self.assertEqual([c["fact_id"] for c in out["stage2"]["candidates"]], ["F1"])
        self.assertEqual(sorted(r["index"] for r in out["stage2"]["rejected"]), [1, 2, 3])
        self.assertTrue(all(r["problems"] for r in out["stage2"]["rejected"]))

    def test_only_observed_claims_with_exact_evidence_inside_the_region_are_accepted(self):
        out = run(fact(status="inferred", dimension_basis="visual_estimate"), fact(fact_id="F2", category="note", dimension_basis=None, value="not shown", unit=None, key="gate sizes",
                  evidence_text="GATE OPENING SIZES ARE NOT SHOWN ON THIS SHEET."), fact(fact_id="F3", category="note", dimension_basis=None, unit=None, key="outside", value="outside the region note",
                  evidence_text="FOUR-COURT FACILITY OUTSIDE THE REGION NOTE"))
        self.assertEqual([f["fact_id"] for f in out["stage3"]["accepted_facts"]], ["F2"])
        self.assertEqual([f["fact_id"] for f in out["stage3"]["not_observed"]], ["F1"])
        self.assertEqual([f["fact_id"] for f in out["stage3"]["outside_region"]], ["F3"])

    def test_a_malformed_response_yields_no_candidates_no_accepted_facts_and_a_diagnostic_only_salvage(self):
        bad = '{"facts": [{"fact_id": "F1", "key":Post spacing", "": "x", "evidence_text": "GATE OPENING SIZES ARE NOT SHOWN ON THIS SHEET."}]}'
        out = P.process_content(bad, Page(), SRC, REGION)
        self.assertEqual((out["stage2"]["candidates"], out["stage3"]["accepted_facts"], out["stage4"]), ([], [], []))
        self.assertTrue(out["diagnostic_salvage"]["DIAGNOSTIC_ONLY"])
        self.assertEqual(out["diagnostic_salvage"]["salvaged"][0]["text_match"], "exact")
        self.assertIsInstance(out["diagnostic_salvage"]["salvaged"][0], P.SalvagedFact)


class Quarantine(unittest.TestCase):
    def test_salvaged_values_cannot_be_accepted_by_type(self):
        s = P.SalvagedFact(quote="GATE", origin="salvage", text_match="exact")
        with self.assertRaises(TypeError):
            P.AcceptedFacts().accept(s)

    def test_a_hand_built_fact_cannot_be_accepted_without_the_required_provenance(self):
        for f in ({"origin": "strict_parse"}, {"origin": "salvage", "verification": "VERIFIED_EXACT", "position_source": "pdf_text_layer"},
                  {"origin": "strict_parse", "verification": "VERIFIED_EXACT", "position_source": "model_bbox"}):
            with self.assertRaises(ValueError):
                P.AcceptedFacts().accept(f)

    def test_constraints_derive_only_from_the_accepted_collection(self):
        with self.assertRaises(TypeError):
            P.stage4_constraints([{"evidence_text": "AT 10'-0\" O.C. MAXIMUM", "fact_id": "X"}])
        unverified = run(fact(evidence_text="POSTS AT 10'-0\" O.C. MAXIMUM EVERYWHERE", value="10'-0\""))
        self.assertEqual(unverified["stage4"], [])

    def test_the_spacing_rule_becomes_a_maximum_constraint_not_a_quantity(self):
        c = run(fact())["stage4"]
        self.assertEqual(len(c), 1)
        self.assertEqual((c[0]["bound"], c[0]["value_inches"], c[0]["is_measured_length"], c[0]["informational_only"]), ("maximum", "120", False, True))
        self.assertFalse(P.FORBIDDEN_CONSTRAINT_KEYS & set(c[0]))


class Documents(unittest.TestCase):
    def manifest(self, tmp):
        f = pathlib.Path(tmp) / "a.pdf"; f.write_bytes(b"%PDF-1.4 a")
        g = pathlib.Path(tmp) / "b.pdf"; g.write_bytes(b"%PDF-1.4 b")
        h = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        return {"documents": [{"doc_id": "doc_a", "path": str(f), "sha256": h(f), "status": "available"}, {"doc_id": "doc_b", "path": str(g), "sha256": h(g), "status": "available"},
                              {"doc_id": "pending", "path": None, "sha256": None, "status": "pending_not_received"},
                              {"doc_id": "stale", "path": str(f), "sha256": "0" * 64, "status": "available"}]}

    def test_pending_and_stale_documents_are_refused_and_good_ones_load(self):
        with tempfile.TemporaryDirectory() as d:
            m = self.manifest(d)
            self.assertEqual(P.load_document(m, "doc_a")["doc_id"], "doc_a")
            with self.assertRaises(PermissionError):
                P.load_document(m, "pending")
            with self.assertRaisesRegex(ValueError, "HASH MISMATCH"):
                P.load_document(m, "stale")
            with self.assertRaises(KeyError):
                P.load_document(m, "nope")

    def test_run_directories_are_separated_by_document_and_hash(self):
        a, b = {"doc_id": "doc_a", "sha256": "1" * 64}, {"doc_id": "doc_b", "sha256": "2" * 64}
        self.assertNotEqual(P.run_dir("r", a, "x"), P.run_dir("r", b, "x"))
        self.assertIn("111111111111", str(P.run_dir("r", a, "x")))

    def rec(self, doc, sha, **over):
        r = {"source": {"doc_id": doc, "source_sha256": sha}, "input": {"page_number": 2, "region_norm_page": [0, 0, 1, 1], "dpi": 100, "image_sha256": "i", "prompt_sha256": "p", "system_sha256": "s"},
             "request": {"model": "A", "temperature": 0.0, "max_tokens": 700, "stream": True, "response_format": {"type": "json_object"}}}
        for k, v in over.items():
            sect, key = k.split("__")
            r[sect][key] = v
        return r

    def test_comparison_labels(self):
        same = P.equivalence(self.rec("d", "a"), self.rec("d", "a", request__model="B"))
        self.assertIn("Equivalent", same["label"])
        diff = P.equivalence(self.rec("d", "a"), self.rec("d", "a", request__max_tokens=3000, input__dpi=150))
        self.assertTrue(diff["label"].startswith("NON-EQUIVALENT") and "request.max_tokens" in diff["differences"] and "dpi" in diff["differences"])
        other = P.equivalence(self.rec("d34", "a"), self.rec("d11", "b"))
        self.assertFalse(other["same_document"])
        self.assertIn("NOT a model-performance benchmark", other["label"])


class Safety(unittest.TestCase):
    def test_write_once_refuses_overwrite_frozen_dirs_and_credential_shapes(self):
        with tempfile.TemporaryDirectory() as d:
            P.write_once(d, "a.json", {"x": 1})
            with self.assertRaises(FileExistsError):
                P.write_once(d, "a.json", {"x": 2})
            with self.assertRaises(ValueError):
                P.write_once(d, "k.json", {"k": "rc-" + "0" * 40})
        with self.assertRaises(PermissionError):
            P.write_once(pathlib.Path("runs/exp2/anything"), "a.json", {})

    def test_live_calls_need_explicit_authorization_and_no_hold(self):
        real = "https://developer.amd.com.cn/radeon/api/v1"
        with self.assertRaises(PermissionError):
            P.assert_live_allowed(real, authorized=False)
        P.assert_live_allowed("http://127.0.0.1:9/v1", authorized=False)         # loopback test servers are exempt
        with tempfile.TemporaryDirectory() as d:
            old = P.HARNESS_DIR
            P.HARNESS_DIR = pathlib.Path(d)
            try:
                P.assert_live_allowed(real, authorized=True)                      # no hold file: allowed once authorized
                (pathlib.Path(d) / "LIVE_CALLS_DISABLED").write_text("hold")
                with self.assertRaisesRegex(PermissionError, "on hold"):
                    P.assert_live_allowed(real, authorized=True)
            finally:
                P.HARNESS_DIR = old

    def test_the_harness_hold_file_exists_right_now(self):
        self.assertTrue((P.HARNESS_DIR / "LIVE_CALLS_DISABLED").exists())


if __name__ == "__main__":
    unittest.main()

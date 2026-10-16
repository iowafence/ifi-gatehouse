"""Deterministic G3 RFI drafts: pending, no candidate values, G2 never conflated with G3, citations verbatim in the ingested PDFs."""
import copy
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from engine import rfi_drafts

ROOT = Path(__file__).resolve().parent.parent
SCOPE = json.loads((ROOT / "dp001" / "scope_dp001_footing.json").read_text())
DOCS = ROOT / "samples" / "public-demo" / "dp001"
PDF = {rfi_drafts.DRAWINGS: "DP001_Drawings_IFB_Rev0_ANSI_B.pdf", rfi_drafts.MANUAL: "DP001_Project_Manual.pdf",
       rfi_drafts.ADD01: "DP001_Addendum_01.pdf"}


def norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


class G3RfiDrafts(unittest.TestCase):
    def test_two_pending_drafts_for_the_two_open_questions(self):
        d = rfi_drafts.g3_rfi_drafts(SCOPE)
        self.assertEqual([x["draft_id"] for x in d], ["RFI-G3-OPENING", "RFI-G3-POST-FOOTING"])
        for x in d:
            self.assertEqual((x["status"], x["approved_by"], x["approved_utc"], x["sent"]), (rfi_drafts.PENDING, None, None, False))
            self.assertEqual(x["gate_id"], "G3")
            self.assertIsNone(x["candidate_values"])

    def test_no_candidate_values_anywhere_in_the_question_text(self):
        for x in rfi_drafts.g3_rfi_drafts(SCOPE):
            text = " ".join([x["subject"], *x["requests"]])
            self.assertIsNone(re.search(r"\d", text.replace("G3", "")), text)   # the tag G3 is the only digit allowed

    def test_opening_cites_the_required_sources(self):
        o = rfi_drafts.g3_rfi_drafts(SCOPE)[0]
        self.assertEqual([c["sheet_label"] for c in o["citations"]],
                         ["F502 note 4", "F502 gate schedule, G3 column", "C101 keynote 7", "32 31 13 2.5.I", "Addendum 01 item 2.2"])
        self.assertEqual(o["unresolved_paths"], ["/gates/2/clear_width_ft"])

    def test_post_and_footing_asks_only_for_what_is_unresolved(self):
        p = rfi_drafts.g3_rfi_drafts(SCOPE)[1]
        self.assertEqual(p["unresolved_paths"], [f"/footing_scope/classes/GATE_G3/{f}" for f in ("post_od_in", "diameter_in", "depth_in")])
        s = copy.deepcopy(SCOPE)
        for f in ("diameter_in", "depth_in"):
            s["footing_scope"]["classes"]["GATE_G3"][f] = {"value": 1, "status": "confirmed", "evidence": []}
        self.assertEqual(rfi_drafts.g3_rfi_drafts(s)[1]["unresolved_paths"], ["/footing_scope/classes/GATE_G3/post_od_in"])

    def test_g2_is_established_and_never_asks_or_is_asked_about(self):
        g2 = SCOPE["footing_scope"]["classes"]["GATE_G2"]
        self.assertEqual({f: g2[f]["status"] for f in ("post_od_in", "diameter_in", "depth_in")}, dict.fromkeys(("post_od_in", "diameter_in", "depth_in"), "confirmed"))
        self.assertEqual(g2["post_od_in"]["value"], 2.875)
        self.assertTrue(any("Addendum 01" in e.get("sheet_label", "") for e in g2["post_od_in"]["evidence"]))
        for x in rfi_drafts.g3_rfi_drafts(SCOPE):
            self.assertNotIn("G2", json.dumps(x))
            self.assertNotIn("GATE_G2", json.dumps(x))

    def test_no_draft_once_the_documents_establish_the_facts(self):
        s = copy.deepcopy(SCOPE)
        s["gates"][2]["clear_width_ft"] = {"value": 1, "status": "confirmed", "evidence": []}
        for f in ("post_od_in", "diameter_in", "depth_in"):
            s["footing_scope"]["classes"]["GATE_G3"][f] = {"value": 1, "status": "confirmed", "evidence": []}
        self.assertEqual(rfi_drafts.g3_rfi_drafts(s), [])

    def test_a_human_typed_value_does_not_close_the_rfi(self):
        s = copy.deepcopy(SCOPE)
        s["gates"][2]["clear_width_ft"] = {"value": 1, "status": "human_resolved", "evidence": []}
        d = rfi_drafts.g3_rfi_drafts(s)
        self.assertEqual(d[0]["basis_state"], "ASSUMED_RFI_PENDING")
        self.assertIsNone(d[0]["candidate_values"])

    @unittest.skipUnless(shutil.which("pdftotext"), "pdftotext not installed")
    def test_every_citation_is_verbatim_on_its_cited_page(self):
        for key, c in rfi_drafts.CITE.items():
            out = subprocess.run(["pdftotext", "-raw", "-f", str(c["page"]), "-l", str(c["page"]), str(DOCS / PDF[c["doc_id"]]), "-"],
                                 capture_output=True, check=True, timeout=60).stdout.decode("utf-8", "replace")
            self.assertIn(norm(c["excerpt"]), norm(out), key)


if __name__ == "__main__":
    unittest.main()


class RfiDraftsInProjectState(unittest.TestCase):
    """Drafts are stored in project state, derived from the scope, pending, never sent, and stay open on a human assumption."""

    def setUp(self):
        from tests import footing_helpers as H
        self.H = H
        self.st = H.start(H.fixture())

    def test_state_carries_two_pending_drafts(self):
        d = self.st["rfi_drafts"]
        self.assertEqual([x["draft_id"] for x in d], ["RFI-G3-OPENING", "RFI-G3-POST-FOOTING"])
        for x in d:
            self.assertEqual((x["status"], x["sent"], x["approved_by"], x["basis_state"]), (rfi_drafts.PENDING, False, None, "MISSING_VALUE"))

    def test_human_typed_value_keeps_rfi_pending_and_never_leaks_the_value(self):
        self.H.approve_inferred(self.st)
        self.H.give(self.st, "gates/2/clear_width_ft", 12.0, "typed by estimator for what-if; RFI open")
        d = {x["draft_id"]: x for x in self.st["rfi_drafts"]}
        self.assertEqual(d["RFI-G3-OPENING"]["basis_state"], "ASSUMED_RFI_PENDING")
        self.assertEqual(d["RFI-G3-POST-FOOTING"]["basis_state"], "MISSING_VALUE")
        self.assertIn("RFI-G3-OPENING", d)
        for x in d.values():
            self.assertIsNone(x["candidate_values"])
            self.assertFalse(x["sent"])
            self.assertNotIn("12", json.dumps(x["requests"]))

    def test_summary_exposes_drafts(self):
        from api import server
        self.assertEqual(server.summary("p", self.st)["rfi_drafts"], self.st["rfi_drafts"])

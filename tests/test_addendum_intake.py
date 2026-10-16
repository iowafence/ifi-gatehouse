"""Addendum 02 intake through the Scope Gate, against DECOY PDFs only (never the real ADDENDUM_02.pdf).
Six negative tests: invalid PDF, oversize, duplicate, G2 unchanged, contradictory G3, stale digest after release."""
import copy
import hashlib
import unittest

from engine import addendum_intake as ai, workflow as wf
from intake import addendum as pdfin
from tests import footing_helpers as H
from tests.decoy_pdf import G2_LINE, G3_LINE, decoy, make_pdf

WHO = "Estimator Test (self-declared)"
G3_PATH = "/gates/2/clear_width_ft"
G2_PATH = "/gates/1/clear_width_ft"


def parser_for(*facts, model="decoy-parser-not-a-model"):
    def mock_parser(pages, context):
        return list(facts), {"model": model}
    return mock_parser


def g3(value=14, page=1, excerpt="THE CLEAR OPENING WIDTH IS 14 FEET"):
    return {"path": G3_PATH, "value": value, "unit": "ft", "page": page, "excerpt": excerpt}


def g2(value=12, excerpt="CLEAR OPENING IS 12 FEET, DOUBLE LEAF"):
    return {"path": G2_PATH, "value": value, "unit": "ft", "page": 1, "excerpt": excerpt}


def fresh():
    return H.start(H.fixture())


def accept(st, rec, by="Named Reviewer (self-declared)"):
    return ai.accept_addendum_intake(st, intake_id=rec["intake_id"], by=by, note="reviewed the Before/After against the cited page",
                                     scope_version=st["scope"]["scope_version"], proposal_digest=st.get("proposal_digest"))


class Pipeline(unittest.TestCase):
    def test_upload_verify_before_after_accept_bumps_version_and_preserves_history(self):
        st = fresh()
        v0, pdf = st["scope"]["scope_version"], decoy(G3_LINE)
        rec = ai.submit_addendum(st, pdf, "ADD 02 decoy.pdf", parser=parser_for(g3()), by="Uploader (self-declared)")
        self.assertEqual(rec["status"], ai.PROPOSED)
        self.assertEqual(rec["source"]["sha256"], hashlib.sha256(pdf).hexdigest())
        self.assertEqual(rec["source"]["doc_revision"], 2)                        # Addendum 01 is revision 1; this is its own revision
        self.assertEqual(rec["parse"]["model"], "decoy-parser-not-a-model")
        ba = rec["before_after"][0]
        self.assertEqual((ba["path"], ba["before"], ba["before_status"], ba["after"], ba["cited_page"]), (G3_PATH, None, "unresolved", 14, 1))
        self.assertIn("14 FEET", ba["cited_excerpt"])
        self.assertEqual(st["scope"]["scope_version"], v0)                         # nothing changed before a named human accepts
        self.assertEqual(st["scope"]["gates"][2]["clear_width_ft"]["status"], "unresolved")
        accept(st, rec)
        self.assertEqual(st["scope"]["scope_version"], v0 + 1)
        fact = st["scope"]["gates"][2]["clear_width_ft"]
        self.assertEqual((fact["value"], fact["status"]), (14, "confirmed"))
        self.assertEqual(fact["evidence"][0]["doc_id"], rec["source"]["doc_id"])
        self.assertEqual(st["addenda"][rec["intake_id"]]["status"], ai.APPLIED)
        self.assertTrue(any(h["kind"] == "scope_revision" and h["snapshot"]["scope"]["gates"][2]["clear_width_ft"]["status"] == "unresolved" for h in st["history"]))
        events = [e["event"] for e in st["audit"]]
        self.assertEqual([e for e in events if e.startswith("addendum")], ["addendum_received", "addendum_processing", "addendum_proposed", "addendum_accepted", "addendum_intake_accepted"])
        self.assertEqual(st["rfi_drafts"][0]["draft_id"], "RFI-G3-POST-OD")      # the opening RFI is answered; post/footing is still open

    def test_acceptance_needs_a_named_human_and_a_note(self):
        st = fresh()
        rec = ai.submit_addendum(st, decoy(G3_LINE), "d.pdf", parser=parser_for(g3()), by=WHO)
        for by, note in (("", "n"), ("  ", "n"), ("A Name", ""), (None, None)):
            with self.assertRaises(wf.GateError):
                ai.accept_addendum_intake(st, intake_id=rec["intake_id"], by=by, note=note, scope_version=1, proposal_digest=None)
        self.assertEqual(st["scope"]["gates"][2]["clear_width_ft"]["status"], "unresolved")

    def test_idempotent_reupload_creates_nothing_new(self):
        st, pdf = fresh(), decoy(G3_LINE)
        a = ai.submit_addendum(st, pdf, "one.pdf", parser=parser_for(g3()), by=WHO)
        n = len(st["audit"])
        b = ai.submit_addendum(st, pdf, "renamed.pdf", parser=parser_for(), by=WHO)          # same bytes; a parser that would find nothing is not even needed
        self.assertEqual((a["intake_id"], b["intake_id"], len(st["addenda"]), len(st["audit"])), (a["intake_id"], a["intake_id"], 1, n))
        accept(st, a)
        v = st["scope"]["scope_version"]
        c = ai.submit_addendum(st, pdf, "again.pdf", parser=parser_for(), by=WHO)
        self.assertEqual((c["status"], st["scope"]["scope_version"], len(st["addenda"])), (ai.APPLIED, v, 1))

    def test_live_parser_is_refused_while_the_hold_exists(self):
        st = fresh()
        rec = ai.submit_addendum(st, decoy(G3_LINE), "d.pdf", parser=ai.live_parser, by=WHO)
        self.assertEqual(rec["status"], "HELD_PARSE_UNAVAILABLE")
        self.assertEqual(rec["parse"]["model"], "NOT_REPORTED")
        self.assertEqual(st["scope"]["scope_version"], 1)
        with self.assertRaises(wf.GateError):
            accept(st, rec)

    def test_a_typed_g3_value_is_shown_as_overridden_not_silently_replaced(self):
        st = H.priced()                                                             # a human typed G3 (what-if); estimate exists
        rec = ai.submit_addendum(st, decoy(G3_LINE), "d.pdf", parser=parser_for(g3()), by=WHO)
        self.assertEqual(rec["status"], ai.PROPOSED)
        self.assertTrue(rec["before_after"][0]["supersedes_human_resolution"])
        accept(st, rec)
        self.assertEqual(st["labor_review"]["status"], "unresolved")                # labor invalidated
        self.assertIsNone(st.get("released_at"))


class Negative(unittest.TestCase):
    """The six negative tests. Each must HOLD or refuse, never progress silently."""

    def assertUnchanged(self, st, v0):
        self.assertEqual(st["scope"]["scope_version"], v0)
        self.assertEqual(st["scope"]["gates"][2]["clear_width_ft"]["status"], "unresolved")

    def test_1_invalid_pdf(self):
        st = fresh()
        for bad in (b"", b"not a pdf at all", b"%PDF-1.4\ngarbage with no end", b"PK\x03\x04zip", decoy(G3_LINE)[:200], b"%PDF-1.4\n" + b"x" * 100 + b"\n%%EOF\n"):
            with self.assertRaises(pdfin.AddendumRefused) as c:
                ai.submit_addendum(st, bad, "x.pdf", parser=parser_for(g3()), by=WHO)
            self.assertEqual(c.exception.code, "INVALID_PDF")
        self.assertEqual(st.get("addenda", {}), {})
        self.assertTrue(any(e["event"] == "addendum_upload_refused" for e in st["audit"]))
        self.assertUnchanged(st, 1)

    def test_2_oversize(self):
        st = fresh()
        big = decoy(G3_LINE) + b"\n%" + b"0" * pdfin.MAX_PDF_BYTES + b"\n%%EOF\n"
        with self.assertRaises(pdfin.AddendumRefused) as c:
            ai.submit_addendum(st, big, "big.pdf", parser=parser_for(g3()), by=WHO)
        self.assertEqual(c.exception.code, "TOO_LARGE")
        self.assertEqual(st.get("addenda", {}), {})
        self.assertUnchanged(st, 1)

    def test_3_duplicate(self):
        st, pdf = fresh(), decoy(G3_LINE)
        rec = ai.submit_addendum(st, pdf, "a.pdf", parser=parser_for(g3()), by=WHO)
        accept(st, rec)
        v = st["scope"]["scope_version"]
        with self.assertRaises(wf.GateError):                                       # the engine also refuses the same document twice
            wf.revise_scope(st, rec["updates"], source=rec["source"], by=WHO, note="replay")
        with self.assertRaises(wf.GateError):                                       # accepting twice
            accept(st, st["addenda"][rec["intake_id"]])
        self.assertEqual((st["scope"]["scope_version"], len(st["addenda"])), (v, 1))

    def test_4_g2_unchanged(self):
        st = fresh()
        rec = ai.submit_addendum(st, decoy(G2_LINE), "g2.pdf", parser=parser_for(g2()), by=WHO)
        self.assertEqual(rec["status"], "HELD_NO_CHANGE")
        self.assertIsNone(rec["bound"])
        with self.assertRaises(wf.GateError):
            accept(st, rec)
        self.assertEqual(st["scope"]["scope_version"], 1)
        self.assertEqual(st["scope"]["gates"][1]["clear_width_ft"]["value"], 12.0)  # G2 stays at Addendum 01's 12 ft

    def test_5_contradictory_g3(self):
        st = fresh()
        a = ai.submit_addendum(st, decoy(G3_LINE, "ITEM 3 GATE G3: THE CLEAR OPENING WIDTH IS 16 FEET (DECOY)"), "c.pdf",
                               parser=parser_for(g3(), g3(16, excerpt="THE CLEAR OPENING WIDTH IS 16 FEET")), by=WHO)
        self.assertEqual(a["status"], "HELD_CONTRADICTORY")
        with self.assertRaises(wf.GateError):
            accept(st, a)
        self.assertUnchanged(st, 1)

    def test_6_stale_digest_and_release(self):
        st = H.priced()
        rec = ai.submit_addendum(st, decoy(G3_LINE), "late.pdf", parser=parser_for(g3()), by=WHO)
        self.assertEqual(rec["status"], ai.PROPOSED)
        d, v = st["proposal_digest"], st["scope"]["scope_version"]
        with self.assertRaises(wf.GateError) as c:                                   # a pending proposal blocks release, stable code
            wf.release(st, "Visitor A (self-declared, fictional)", v, d, note="demonstration release")
        self.assertIn("ADDENDUM_PENDING", str(c.exception))
        self.assertNotEqual(st["status"], wf.RELEASED)
        ai.decline_addendum_intake(st, intake_id=rec["intake_id"], by="Named Reviewer", note="not needed")
        self.assertEqual(st["addenda"][rec["intake_id"]]["status"], "DECLINED")
        with self.assertRaises(wf.GateError):                                        # a declined proposal cannot be accepted
            accept(st, st["addenda"][rec["intake_id"]])
        self.assertEqual(st["scope"]["scope_version"], v)
        wf.release(st, "Visitor A (self-declared, fictional)", v, d, note="demonstration release")
        self.assertEqual(st["status"], wf.RELEASED)
        # a NEW upload after release binds to the released state; accepting it supersedes the release and keeps it in history
        pdf2 = decoy(G3_LINE, "SECOND COPY WITH DIFFERENT BYTES")
        late = ai.submit_addendum(st, pdf2, "late2.pdf", parser=parser_for(g3()), by=WHO)
        self.assertEqual((late["status"], late["bound"]["status"]), (ai.PROPOSED, wf.RELEASED))
        with self.assertRaises(wf.GateError) as c:
            ai.accept_addendum_intake(st, intake_id=late["intake_id"], by="Named Reviewer", note="x", scope_version=v, proposal_digest="0" * 64)
        self.assertIn("STALE_PROPOSAL", str(c.exception))                            # a forged digest is refused
        self.assertEqual((st["status"], st["scope"]["scope_version"]), (wf.RELEASED, v))   # the released artifact is untouched
        accept(st, late)
        self.assertNotEqual(st["status"], wf.RELEASED)
        self.assertTrue(any(h["kind"] == "released_artifact" and h["superseded"] for h in st["history"]))

    def test_6b_accept_is_refused_after_the_project_moves_on(self):
        import copy
        def moved(change):
            st = H.priced()
            rec = ai.submit_addendum(st, decoy(G3_LINE), "m.pdf", parser=parser_for(g3()), by=WHO)
            v, d = st["scope"]["scope_version"], st["proposal_digest"]
            change(st)
            w0, v1 = st["scope"]["gates"][2]["clear_width_ft"]["value"], st["scope"]["scope_version"]
            with self.assertRaises(wf.GateError) as c:
                ai.accept_addendum_intake(st, intake_id=rec["intake_id"], by="Named Reviewer", note="late", scope_version=v, proposal_digest=d)
            self.assertIn("STALE_PROPOSAL", str(c.exception))
            self.assertEqual((st["scope"]["gates"][2]["clear_width_ft"]["value"], st["scope"]["scope_version"]), (w0, v1))   # nothing applied
        # (b) the crew plan is re-approved (the digest changes)
        moved(lambda st: wf.approve_crew_plan(st, by=H.WHO, note="re-approved", preferred_crew="CR13", assignments={"L02": "CR13"},
                                              use_default_for_unassigned=False, difficulty={"default": "hard", "overrides": {}}))
        # (c) another scope decision (the version changes)
        moved(lambda st: wf.hold(st, by="Reviewer", reason="hold for question"))
        # (d) another addendum revision is applied first (the version changes)
        def another(st):
            other = ai.submit_addendum(st, decoy("ITEM 9 GATE G3: THE CLEAR OPENING WIDTH IS 14 FEET (DECOY)"), "o.pdf", parser=parser_for(g3()), by=WHO)
            accept(st, other)
        moved(another)

    def test_g2_contradicting_addendum_01_is_held(self):
        st = fresh()
        line = "ITEM 2 GATE G2: THE CLEAR OPENING WIDTH IS 8 FEET (DECOY)"
        rec = ai.submit_addendum(st, decoy(line), "g2.pdf", parser=parser_for({"path": G2_PATH, "value": 8, "unit": "ft", "page": 1,
                                 "excerpt": "THE CLEAR OPENING WIDTH IS 8 FEET"}), by=WHO)
        self.assertEqual(rec["status"], "HELD_CONTRADICTORY")
        c = rec["conflicts"][0]
        self.assertEqual(c["code"], "CONTRADICTS_ESTABLISHED_FACT")
        self.assertEqual((c["established"]["value"], c["addendum"]["value"]), (12.0, 8))
        self.assertTrue(any("Addendum 01 item 1.1" in x["sheet_label"] and "12'-0\"" in x["excerpt"] for x in c["established"]["citations"]))   # the established side's citation
        self.assertEqual((c["addendum"]["citation"]["page"], c["addendum"]["citation"]["excerpt"]), (1, "THE CLEAR OPENING WIDTH IS 8 FEET"))          # the addendum side's citation
        self.assertEqual(c["suggested_precedence"]["suggests"], "ADDENDUM_VALUE")
        self.assertFalse(c["suggested_precedence"]["decided"])
        self.assertIn("named person", rec["message"])
        self.assertEqual((st["scope"]["scope_version"], st["scope"]["gates"][1]["clear_width_ft"]["value"]), (1, 12.0))

    def test_a_held_contradiction_blocks_release_until_a_named_human_decides(self):
        st = H.priced()
        rec = ai.submit_addendum(st, decoy("ITEM 2 GATE G2: THE CLEAR OPENING WIDTH IS 8 FEET (DECOY)"), "g2.pdf", parser=parser_for(
            {"path": G2_PATH, "value": 8, "unit": "ft", "page": 1, "excerpt": "THE CLEAR OPENING WIDTH IS 8 FEET"}), by=WHO)
        self.assertEqual(rec["status"], "HELD_CONTRADICTORY")
        with self.assertRaises(wf.GateError) as c:
            wf.release(st, "Visitor A (self-declared, fictional)", st["scope"]["scope_version"], st["proposal_digest"])
        self.assertIn("ADDENDUM_PENDING", str(c.exception))
        for bad in (dict(decision="maybe", by="A Name", note="n"), dict(decision="keep_established", by="", note="n"), dict(decision="keep_established", by="A Name", note="")):
            with self.assertRaises(wf.GateError):
                ai.decide_addendum_conflict(st, intake_id=rec["intake_id"], **bad)
        self.assertEqual(st["addenda"][rec["intake_id"]]["status"], "HELD_CONTRADICTORY")

    def test_decision_keep_established_closes_it_and_unblocks_release(self):
        st = H.priced()
        rec = ai.submit_addendum(st, decoy("ITEM 2 GATE G2: THE CLEAR OPENING WIDTH IS 8 FEET (DECOY)"), "g2.pdf", parser=parser_for(
            {"path": G2_PATH, "value": 8, "unit": "ft", "page": 1, "excerpt": "THE CLEAR OPENING WIDTH IS 8 FEET"}), by=WHO)
        v = st["scope"]["scope_version"]
        ai.decide_addendum_conflict(st, intake_id=rec["intake_id"], decision="keep_established", by="Named Reviewer", note="Addendum 01 stands for G2")
        r = st["addenda"][rec["intake_id"]]
        self.assertEqual((r["status"], r["conflict_decision"]["by"], st["scope"]["scope_version"], st["scope"]["gates"][1]["clear_width_ft"]["value"]), ("DECLINED", "Named Reviewer", v, 12.0))
        wf.release(st, "Visitor A (self-declared, fictional)", v, st["proposal_digest"])
        self.assertEqual(st["status"], wf.RELEASED)

    def test_decision_accept_addendum_value_still_needs_its_own_named_acceptance(self):
        st = H.priced()
        rec = ai.submit_addendum(st, decoy("ITEM 2 GATE G2: THE CLEAR OPENING WIDTH IS 8 FEET (DECOY)"), "g2.pdf", parser=parser_for(
            {"path": G2_PATH, "value": 8, "unit": "ft", "page": 1, "excerpt": "THE CLEAR OPENING WIDTH IS 8 FEET"}), by=WHO)
        v = st["scope"]["scope_version"]
        ai.decide_addendum_conflict(st, intake_id=rec["intake_id"], decision="accept_addendum_value", by="Named Decider", note="later addendum governs (suggested rule)")
        r = st["addenda"][rec["intake_id"]]
        self.assertEqual((r["status"], r["before_after"][0]["supersedes_established_fact"], r["before_after"][0]["before"], r["before_after"][0]["after"]), (ai.PROPOSED, True, 12.0, 8.0))
        self.assertEqual((st["scope"]["scope_version"], st["scope"]["gates"][1]["clear_width_ft"]["value"]), (v, 12.0))     # nothing applied by the decision alone
        with self.assertRaises(wf.GateError):
            ai.decide_addendum_conflict(st, intake_id=rec["intake_id"], decision="keep_established", by="Named Decider", note="again")   # decided once
        accept(st, r)
        self.assertEqual((st["scope"]["scope_version"], st["scope"]["gates"][1]["clear_width_ft"]["value"]), (v + 1, 8.0))
        self.assertTrue(any(h["snapshot"]["scope"]["gates"][1]["clear_width_ft"]["value"] == 12.0 for h in st["history"]))   # the earlier state is preserved

    def test_a_document_that_contradicts_itself_is_not_decidable(self):
        st = fresh()
        rec = ai.submit_addendum(st, decoy(G3_LINE, "ITEM 3 GATE G3: THE CLEAR OPENING WIDTH IS 16 FEET (DECOY)"), "c.pdf",
                                 parser=parser_for(g3(), g3(16, excerpt="THE CLEAR OPENING WIDTH IS 16 FEET")), by=WHO)
        self.assertEqual((rec["status"], bool(rec.get("conflicts"))), ("HELD_CONTRADICTORY", False))
        with self.assertRaises(wf.GateError):
            ai.decide_addendum_conflict(st, intake_id=rec["intake_id"], decision="accept_addendum_value", by="A Name", note="n")

    def test_a_later_addendum_cannot_overturn_an_established_g3(self):
        st = fresh()
        first = ai.submit_addendum(st, decoy(G3_LINE), "one.pdf", parser=parser_for(g3()), by=WHO)
        accept(st, first)
        second = ai.submit_addendum(st, decoy("ITEM 1 GATE G3: THE CLEAR OPENING WIDTH IS 20 FEET (DECOY)"), "two.pdf",
                                    parser=parser_for(g3(20, excerpt="THE CLEAR OPENING WIDTH IS 20 FEET")), by=WHO)
        self.assertEqual(second["status"], "HELD_CONTRADICTORY")
        self.assertEqual(st["scope"]["gates"][2]["clear_width_ft"]["value"], 14)

    def test_stable_rejection_codes_and_bad_values(self):
        st = fresh()
        cases = {"QUOTE_NOT_ON_PAGE": g3(excerpt="THE CLEAR OPENING WIDTH IS 99 FEET"), "PAGE_NOT_IN_DOCUMENT": g3(page=5),
                 "NUMBER_MISMATCH": g3(11), "VALUE_NOT_NUMERIC": g3("14")}
        for code, f in cases.items():
            rec = ai.submit_addendum(fresh(), decoy(G3_LINE), "c%s.pdf" % code, parser=parser_for(f), by=WHO)
            self.assertEqual(rec["status"], "HELD_UNVERIFIED_EVIDENCE", code)
        for bad in (True, float("nan"), float("inf"), -14, 0):
            rec = ai.submit_addendum(fresh(), decoy(G3_LINE), "n.pdf", parser=parser_for(g3(bad)), by=WHO)
            self.assertEqual(rec["status"], "HELD_UNVERIFIED_EVIDENCE", repr(bad))
            self.assertIn(rec["rejected"][0]["code"], ("VALUE_NOT_NUMERIC", "NUMBER_MISMATCH"))
        r = ai.submit_addendum(fresh(), decoy(G3_LINE), "p.pdf", parser=parser_for(g3(page=5)), by=WHO)
        self.assertEqual(r["rejected"][0]["code"], "PAGE_NOT_IN_DOCUMENT")
        r = ai.submit_addendum(fresh(), decoy(G3_LINE), "q.pdf", parser=parser_for(g3(11)), by=WHO)
        self.assertEqual(r["rejected"][0]["code"], "NUMBER_MISMATCH")

    def test_the_wrong_field_excerpt_is_refused(self):
        line = "GATE G3 POST SIZE IS 2.875 IN OD"
        rec = ai.submit_addendum(fresh(), decoy(line), "w.pdf", parser=parser_for({"path": G3_PATH, "value": 2.875, "page": 1, "excerpt": line}), by=WHO)
        self.assertEqual(rec["status"], "HELD_UNVERIFIED_EVIDENCE")
        self.assertEqual(rec["rejected"][0]["code"], "NUMBER_NOT_TIED_TO_FIELD")

    def test_inches_proposed_for_a_feet_field_are_refused(self):
        rec = ai.submit_addendum(fresh(), decoy("GATE G3 CLEAR OPENING IS 168 IN"), "i.pdf", parser=parser_for(g3(168, excerpt="GATE G3 CLEAR OPENING IS 168 IN")), by=WHO)
        self.assertEqual((rec["status"], rec["rejected"][0]["code"]), ("HELD_UNVERIFIED_EVIDENCE", "NUMBER_MISMATCH"))

    def test_no_text_layer_encrypted_and_applied_reupload(self):
        st = fresh()
        blank = make_pdf([[""]])
        with self.assertRaises(pdfin.AddendumRefused) as c:
            ai.submit_addendum(st, blank, "scan.pdf", parser=parser_for(g3()), by=WHO)
        self.assertEqual(c.exception.code, "NO_TEXT_LAYER")
        enc = decoy(G3_LINE).replace(b"/Root 1 0 R", b"/Root 1 0 R /Encrypt << /Filter /Standard /V 1 /R 2 /O (aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa) /U (bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb) /P -4 >> /ID [<00> <00>]")
        with self.assertRaises(pdfin.AddendumRefused):
            ai.submit_addendum(st, enc, "enc.pdf", parser=parser_for(g3()), by=WHO)
        rec = ai.submit_addendum(st, decoy(G3_LINE), "ok.pdf", parser=parser_for(g3()), by=WHO)
        accept(st, rec)
        n, v = len(st["audit"]), st["scope"]["scope_version"]
        again = ai.submit_addendum(st, decoy(G3_LINE), "ok.pdf", parser=parser_for(), by=WHO)
        self.assertEqual((again["status"], len(st["audit"]), st["scope"]["scope_version"]), (ai.APPLIED, n, v))

    def test_unverified_citation_holds_the_whole_parse(self):
        st = fresh()
        pdf = decoy(G3_LINE)
        rec = ai.submit_addendum(st, pdf, "u.pdf", parser=parser_for(g3(excerpt="THE CLEAR OPENING WIDTH IS 99 FEET")), by=WHO)
        self.assertEqual((rec["status"], len(rec["rejected"])), ("HELD_UNVERIFIED_EVIDENCE", 1))
        self.assertUnchanged(st, 1)
        self.assertFalse(pdfin.excerpt_on_page([{"page": 1, "text": "A B C"}], 2, "a b c a b c a b c"))
        self.assertFalse(pdfin.excerpt_on_page([{"page": 1, "text": "x" * 600}], 1, "x" * 500))
        self.assertTrue(pdfin.excerpt_on_page([{"page": 1, "text": "The  clear\nopening is 14’-0”"}], 1, "THE CLEAR OPENING IS 14'-0\""))

    def test_cited_text_on_a_different_page_is_refused(self):
        st = fresh()
        pdf = make_pdf([["PAGE ONE UNRELATED TEXT"], [G3_LINE]])
        rec = ai.submit_addendum(st, pdf, "p.pdf", parser=parser_for(g3(page=1)), by=WHO)
        self.assertEqual(rec["status"], "HELD_UNVERIFIED_EVIDENCE")
        rec2 = ai.submit_addendum(st, pdf, "p.pdf", parser=parser_for(g3(page=2)), by=WHO)       # same bytes: held records are idempotent
        self.assertEqual(rec2["status"], "HELD_UNVERIFIED_EVIDENCE")
        pdf2 = make_pdf([["PAGE ONE UNRELATED TEXT"], [G3_LINE, "SECOND DECOY"]])
        rec3 = ai.submit_addendum(st, pdf2, "p2.pdf", parser=parser_for(g3(page=2)), by=WHO)
        self.assertEqual(rec3["status"], ai.PROPOSED)

    def test_parser_output_is_never_trusted_structurally(self):
        st = fresh()
        for n, out in enumerate(("junk", [{"path": "no-slash", "value": 1, "page": 1, "excerpt": "x"}], [{"path": G3_PATH}], [g3()] * 30)):
            rec = ai.submit_addendum(st, decoy(G3_LINE, "N%d" % n), "j%d.pdf" % n, parser=lambda p, c, o=out: o, by=WHO)
            self.assertEqual(rec["status"], "HELD_UNVERIFIED_EVIDENCE")
        self.assertUnchanged(st, 1)

    def test_a_path_outside_existing_facts_is_held(self):
        st = fresh()
        bad = {"path": "/gates/2/price_per_gate", "value": 1, "page": 1, "excerpt": "THE CLEAR OPENING WIDTH IS 14 FEET"}
        rec = ai.submit_addendum(st, decoy(G3_LINE), "b.pdf", parser=parser_for(bad), by=WHO)
        self.assertEqual(rec["status"], "HELD_UNVERIFIED_EVIDENCE")          # no deterministic unit rule for that field
        self.assertUnchanged(st, 1)


FOOT = "/footing_scope/classes/GATE_G3/"


def fp(field, value, excerpt, page=1):
    return {"path": FOOT + field, "value": value, "page": page, "excerpt": excerpt}


class UnitsAndFields(unittest.TestCase):
    """How G3 footing diameter and depth are resolved: each number is read deterministically from its own cited words."""
    LINE = "GATE G3 FOOTING 1'-4\" DIA. X 4'-0\" DEEP"

    def run_facts(self, st, lines, *facts):
        return ai.submit_addendum(st, decoy(*lines), "f.pdf", parser=parser_for(*facts), by=WHO)

    def test_feet_inches_are_normalized_and_each_number_goes_to_its_own_field(self):
        st = fresh()
        rec = self.run_facts(st, [self.LINE], fp("diameter_in", 16, "FOOTING 1'-4\" DIA. X 4'-0\" DEEP"), fp("depth_in", 48, "FOOTING 1'-4\" DIA. X 4'-0\" DEEP"))
        self.assertEqual(rec["status"], ai.PROPOSED)
        self.assertEqual({b["path"].rsplit("/", 1)[1]: b["after"] for b in rec["before_after"]}, {"diameter_in": 16.0, "depth_in": 48.0})
        accept(st, rec)
        g = st["scope"]["footing_scope"]["classes"]["GATE_G3"]
        self.assertEqual((g["diameter_in"]["value"], g["depth_in"]["value"], g["diameter_in"]["status"]), (16.0, 48.0, "confirmed"))
        self.assertEqual(g["post_od_in"]["status"], "unresolved")                      # not stated, so NOT derived from G2 or any generic row
        self.assertIsNone(g["post_od_in"]["value"])
        d = {x["draft_id"]: x for x in st["rfi_drafts"]}
        self.assertEqual(d["RFI-G3-POST-OD"]["unresolved_paths"], [FOOT + "post_od_in"])   # only the unanswered field stays in the RFI
        self.assertIn("RFI-G3-OPENING", d)

    def test_a_swapped_number_is_refused(self):
        st = fresh()
        rec = self.run_facts(st, [self.LINE], fp("diameter_in", 48, "FOOTING 1'-4\" DIA. X 4'-0\" DEEP"))
        self.assertEqual(rec["status"], "HELD_UNVERIFIED_EVIDENCE")
        self.assertIn("does not equal", rec["rejected"][0]["reason"])

    def test_width_in_inches_becomes_feet(self):
        st = fresh()
        rec = self.run_facts(st, ["GATE G3 CLEAR OPENING IS 168 IN"], g3(14, excerpt="GATE G3 CLEAR OPENING IS 168 IN"))
        self.assertEqual(rec["before_after"][0]["after"], 14.0)
        rec2 = self.run_facts(fresh(), ["GATE G3 CLEAR OPENING IS 14'-6\""], g3(14.5, excerpt="GATE G3 CLEAR OPENING IS 14'-6\""))
        self.assertEqual(rec2["before_after"][0]["after"], 14.5)

    def test_unlabeled_ambiguous_or_double_claimed_numbers_are_refused(self):
        for line, f in (("GATE G3 IS 14 FEET", g3(14, excerpt="GATE G3 IS 14 FEET")),
                        ("THE CLEAR OPENING WIDTH IS 14 FEET AND 16 FEET", g3(14, excerpt="THE CLEAR OPENING WIDTH IS 14 FEET AND 16 FEET")),
                        ("FOOTING 16 IN DIA. X 48 IN", fp("depth_in", 48, "FOOTING 16 IN DIA. X 48 IN")),
                        ("THE CLEAR OPENING WIDTH IS FOURTEEN FEET", g3(14, excerpt="THE CLEAR OPENING WIDTH IS FOURTEEN FEET"))):
            rec = self.run_facts(fresh(), [line], f)
            self.assertEqual(rec["status"], "HELD_UNVERIFIED_EVIDENCE", line)

    def test_post_od_fraction_and_decimal_read_the_same(self):
        from intake import units
        self.assertEqual(units.read_field("post_od_in", "GATE POST 2-7/8 IN OD")[0], 2.875)
        self.assertEqual(units.read_field("post_od_in", "GATE POST 2.875 IN OD")[0], 2.875)
        self.assertEqual(units.read_field("post_od_in", "FOOTING 16 IN DIA. X 48 IN DEEP")[0], None)


def ref(field, src="GATE_G1", page=1, excerpt="GATE G3 POST AND FOOTING: SAME AS GATE G1"):
    return {"path": FOOT + field, "same_as": src, "page": page, "excerpt": excerpt}


SAME_LINES = ["GATE G3 CLEAR OPENING IS 4'-0\"", "GATE G3 POST AND FOOTING: SAME AS GATE G1"]
W4 = {"path": G3_PATH, "value": 4.0, "unit": "ft", "page": 1, "excerpt": "GATE G3 CLEAR OPENING IS 4'-0\""}
ALL_REFS = (ref("post_od_in"), ref("diameter_in"), ref("depth_in"))


class SameAsGateG1(unittest.TestCase):
    """Addendum 02 says G3 post and footing are the same as Gate G1: an explicit reference, never restated numbers."""

    def go(self, st, *facts, lines=SAME_LINES):
        return ai.submit_addendum(st, decoy(*lines), "same.pdf", parser=parser_for(*facts), by=WHO)

    def test_same_as_g1_copies_g1s_confirmed_values_and_shows_the_source(self):
        st = fresh()
        rec = self.go(st, W4, *ALL_REFS)
        self.assertEqual(rec["status"], ai.PROPOSED)
        rows = {r["path"].rsplit("/", 1)[1]: r for r in rec["before_after"]}
        self.assertEqual({k: r["after"] for k, r in rows.items()}, {"clear_width_ft": 4.0, "post_od_in": 2.875, "diameter_in": 16.0, "depth_in": 48.0})
        self.assertIsNone(rows["clear_width_ft"]["inherited_from"])                 # width is a normal stated value
        for k in ("post_od_in", "diameter_in", "depth_in"):
            inh = rows[k]["inherited_from"]
            self.assertEqual((inh["gate"], inh["inherited_from"], inh["source_status"]), ("G1", f"/footing_scope/classes/GATE_G1/{k}", "confirmed"))
            self.assertTrue(inh["source_evidence"])                                  # G1's own document citation travels with it
        self.assertEqual(st["scope"]["footing_scope"]["classes"]["GATE_G3"]["depth_in"]["status"], "unresolved")   # nothing changes before acceptance
        accept(st, rec)
        g = st["scope"]["footing_scope"]["classes"]["GATE_G3"]
        self.assertEqual([(g[k]["value"], g[k]["status"]) for k in ("post_od_in", "diameter_in", "depth_in")], [(2.875, "confirmed"), (16.0, "confirmed"), (48.0, "confirmed")])
        ev = g["depth_in"]["evidence"][0]
        self.assertEqual((ev["excerpt"], ev["inherited_from"]["path"]), ("GATE G3 POST AND FOOTING: SAME AS GATE G1", "/footing_scope/classes/GATE_G1/depth_in"))
        self.assertEqual(st["scope"]["gates"][2]["clear_width_ft"]["value"], 4.0)
        self.assertEqual(st["rfi_drafts"], [])                                       # every G3 fact is now document-confirmed and accepted
        self.assertEqual(st["scope"]["footing_scope"]["classes"]["GATE_G1"]["depth_in"]["value"], 48.0)   # the source is untouched

    def test_unresolved_g1_field_is_inherited_as_blocked_and_named(self):
        sc = H.fixture()
        sc["footing_scope"]["classes"]["GATE_G1"]["diameter_in"] = {"value": None, "status": "unresolved", "evidence": []}
        st = H.start(sc)
        rec = self.go(st, W4, *ALL_REFS)
        self.assertEqual(rec["status"], ai.PROPOSED)
        self.assertEqual({r["path"].rsplit("/", 1)[1] for r in rec["before_after"]}, {"clear_width_ft", "post_od_in", "depth_in"})
        self.assertEqual([(b["path"].rsplit("/", 1)[1], b["inherited_from"], b["source_status"]) for b in rec["blocked"]],
                         [("diameter_in", "/footing_scope/classes/GATE_G1/diameter_in", "unresolved")])
        self.assertIn("/footing_scope/classes/GATE_G1/diameter_in", rec["blocked"][0]["reason"])
        accept(st, rec)
        g = st["scope"]["footing_scope"]["classes"]["GATE_G3"]
        self.assertEqual((g["diameter_in"]["status"], g["diameter_in"]["value"]), ("unresolved", None))     # stays blocked
        self.assertEqual((g["post_od_in"]["value"], g["depth_in"]["value"]), (2.875, 48.0))
        self.assertEqual(st["rfi_drafts"], [])                                       # footing is never an RFI question (32 31 13 3.2.D); the engine blocker names the field
        self.assertTrue(any(e["severity"] == "blocking" and "GATE_G3/diameter_in" in e["exception_id"] for e in st["exceptions"]))

    def test_nothing_resolvable_holds_and_names_the_g1_field(self):
        sc = H.fixture()
        for k in ("post_od_in", "diameter_in", "depth_in"):
            sc["footing_scope"]["classes"]["GATE_G1"][k] = {"value": None, "status": "unresolved", "evidence": []}
        st = H.start(sc)
        rec = self.go(st, *ALL_REFS, lines=SAME_LINES[1:])
        self.assertEqual(rec["status"], "HELD_INHERITED_UNRESOLVED")
        self.assertIn("GATE_G1/post_od_in", rec["message"])
        with self.assertRaises(wf.GateError):
            accept(st, rec)

    def test_a_typed_g1_value_is_not_inherited(self):
        sc = H.fixture()
        sc["footing_scope"]["classes"]["GATE_G1"]["depth_in"] = {"value": 48.0, "status": "human_resolved", "evidence": [{"doc_id": "human", "doc_revision": 0, "page": 1, "excerpt": "typed", "source_type": "human_resolution"}]}
        st = H.start(sc)
        rec = self.go(st, ref("depth_in"), lines=SAME_LINES[1:])
        self.assertEqual((rec["status"], rec["blocked"][0]["source_status"]), ("HELD_INHERITED_UNRESOLVED", "human_resolved"))

    def test_reference_text_must_say_it_in_that_direction_and_not_contradict_g1(self):
        bad = {"G1 same as G3": "GATE G1 POST AND FOOTING: SAME AS GATE G3", "G2 named": "GATE G3 POST AND FOOTING: SAME AS GATE G2",
               "disagreeing number": "GATE G3 POST AND FOOTING: SAME AS GATE G1, 20 IN DIA.", "no phrase": "GATE G3 POST AND FOOTING ARE GATE G1",
               "third gate": "GATE G3 POST AND FOOTING: SAME AS GATE G1 AND GATE G2"}
        for name, line in bad.items():
            rec = self.go(fresh(), ref("diameter_in", excerpt=line, src="GATE_G1"), lines=[line])
            self.assertEqual(rec["status"], "HELD_UNVERIFIED_EVIDENCE", name)

    def test_other_reference_abuse_is_refused(self):
        line = SAME_LINES[1]
        for name, f in {"value alongside": {**ref("diameter_in"), "value": 16}, "width by reference": {**ref("diameter_in"), "path": G3_PATH},
                        "self reference": ref("diameter_in", src="GATE_G3"), "unknown gate": ref("diameter_in", src="GATE_G9"),
                        "quote not on page": ref("diameter_in", excerpt="GATE G3 POST AND FOOTING: SAME AS GATE G1 EXCEPT DEEPER")}.items():
            rec = self.go(fresh(), f, lines=[line])
            self.assertEqual(rec["status"], "HELD_UNVERIFIED_EVIDENCE", name)
            self.assertEqual(rec["updates"], [], name)

    def test_g3_width_four_feet_is_a_normal_stated_value(self):
        st = fresh()
        rec = self.go(st, W4, lines=SAME_LINES[:1])
        self.assertEqual((rec["status"], rec["before_after"][0]["after"], rec["before_after"][0]["inherited_from"]), (ai.PROPOSED, 4.0, None))


SENTENCE = "Gate G3 post size and footing are the same as Gate G1: 2.875 in OD post with the terminal / gate footing, Detail 3/F501."
SENTENCE_LINES = ["Gate G3 post size and footing are the same as Gate G1:", "2.875 in OD post with the terminal / gate footing, Detail 3/F501."]


class SameAsWithStatedPost(unittest.TestCase):
    """The sentence Addendum 02 is expected to use: a labeled post OD plus a citation (Detail 3/F501, not a dimension)."""

    def run_it(self, st, lines=SENTENCE_LINES, sentence=SENTENCE, fields=("post_od_in", "diameter_in", "depth_in")):
        return ai.submit_addendum(st, decoy(*lines), "a02.pdf", parser=parser_for(*[ref(f, excerpt=sentence) for f in fields]), by=WHO)

    def test_the_sentence_resolves_post_and_footing_from_g1(self):
        st = fresh()
        rec = self.run_it(st)
        self.assertEqual(rec["status"], ai.PROPOSED)
        self.assertEqual({r["path"].rsplit("/", 1)[1]: (r["after"], r["inherited_from"]["gate"]) for r in rec["before_after"]},
                         {"post_od_in": (2.875, "G1"), "diameter_in": (16.0, "G1"), "depth_in": (48.0, "G1")})
        accept(st, rec)
        g = st["scope"]["footing_scope"]["classes"]["GATE_G3"]
        self.assertEqual([(g[k]["value"], g[k]["status"]) for k in ("post_od_in", "diameter_in", "depth_in")], [(2.875, "confirmed"), (16.0, "confirmed"), (48.0, "confirmed")])
        self.assertEqual([d["draft_id"] for d in st["rfi_drafts"]], ["RFI-G3-OPENING"])        # only the width remains open

    def test_the_stated_post_od_must_agree_with_g1(self):
        s2 = SENTENCE.replace("2.875", "3.5")
        rec = self.run_it(fresh(), [SENTENCE_LINES[0], SENTENCE_LINES[1].replace("2.875", "3.5")], s2, ("post_od_in",))
        self.assertEqual(rec["status"], "HELD_UNVERIFIED_EVIDENCE")
        self.assertIn("contradicts itself", rec["rejected"][0]["reason"])

    def test_a_citation_is_not_a_dimension_but_an_unlabeled_dimension_is_refused(self):
        from intake import units
        self.assertEqual(units.quantities(SENTENCE), [(units.quantities(SENTENCE)[0][0], units.quantities(SENTENCE)[0][1], units.Fraction(2875, 1000), "2.875 in")])
        bad = "Gate G3 post size and footing are the same as Gate G1, 20 FEET, Detail 3/F501."
        rec = self.run_it(fresh(), [bad], bad, ("post_od_in",))
        self.assertEqual(rec["status"], "HELD_UNVERIFIED_EVIDENCE")

    def test_when_g1_post_is_not_confirmed_the_stated_number_is_not_used(self):
        sc = H.fixture()
        sc["footing_scope"]["classes"]["GATE_G1"]["post_od_in"] = {"value": None, "status": "unresolved", "evidence": []}
        st = H.start(sc)
        rec = self.run_it(st, fields=("post_od_in",))
        self.assertEqual((rec["status"], rec["blocked"][0]["source_status"]), ("HELD_INHERITED_UNRESOLVED", "unresolved"))
        self.assertEqual(st["scope"]["footing_scope"]["classes"]["GATE_G3"]["post_od_in"]["value"], None)


if __name__ == "__main__":
    unittest.main()

"""Addendum routes over HTTP, decoy PDFs only. The live parser is held, so an upload through the real route is HELD, never faked;
a test parser is injected only by patching the module attribute."""
import base64
from unittest import mock

from api import server
from tests.decoy_pdf import G3_LINE, decoy
from tests.http_harness import HttpBase, OWNER_A, OWNER_B
from tests.test_addendum_intake import g3, parser_for


def wait(case, pid, iid, want=("PROCESSING",), tries=100):
    """Poll the status route until the intake leaves PROCESSING."""
    import time
    for _ in range(tries):
        c, out = case.call("GET", f"/projects/{pid}/addenda/{iid}")
        if out["status"] not in want:
            return out
        time.sleep(0.05)
    raise AssertionError("intake stayed PROCESSING")


def body(pdf, name="decoy.pdf", by="Uploader (self-declared)"):
    return {"filename": name, "content_base64": base64.b64encode(pdf).decode(), "by": by}


class AddendumRoutes(HttpBase):
    def test_real_parser_is_held_not_faked(self):
        c, out = self.call("POST", f"/projects/{self.pid}/addenda", body(decoy(G3_LINE)))
        self.assertEqual((c, out["status"]), (202, "PROCESSING"))
        self.assertEqual(out["poll"], f"/projects/{self.pid}/addenda/{out['intake_id']}")
        done = wait(self, self.pid, out["intake_id"])
        self.assertEqual(done["status"], "HELD_PARSE_UNAVAILABLE")
        self.assertEqual(done["intake"]["parse"]["model"], "NOT_REPORTED")
        self.assertEqual(self.call("GET", f"/projects/{self.pid}")[1]["scope_version"], 1)
        self.assertEqual(self.call("GET", f"/projects/{self.pid}/addenda/nope")[0], 404)

    def test_upload_then_named_accept_closes_the_opening_rfi(self):
        with mock.patch.object(server, "ADDENDUM_PARSER", parser_for(g3())):
            c, up = self.call("POST", f"/projects/{self.pid}/addenda", body(decoy(G3_LINE)))
        self.assertEqual((c, up["status"]), (202, "PROCESSING"))
        done = wait(self, self.pid, up["intake_id"])
        self.assertEqual(done["status"], "PROPOSED")
        self.assertEqual(done["intake"]["before_after"][0]["after"], 14)
        up = self.call("GET", f"/projects/{self.pid}")[1]
        up["intake"] = done["intake"]
        self.assertIn("RFI-G3-OPENING", {d["draft_id"] for d in up["rfi_drafts"]})                                 # an upload closes nothing
        iid, v = done["intake_id"], up["scope_version"]
        c, bad = self.call("POST", f"/projects/{self.pid}/addenda/{iid}/accept", {"by": "", "note": "n", "scope_version": v, "proposal_digest": None})
        self.assertEqual(c, 409, bad)
        c, ok = self.call("POST", f"/projects/{self.pid}/addenda/{iid}/accept", {"by": "Named Reviewer", "note": "checked page 1", "scope_version": v, "proposal_digest": None})
        self.assertEqual(c, 200, ok)
        self.assertEqual(ok["scope_version"], v + 1)
        self.assertNotIn("RFI-G3-OPENING", {d["draft_id"] for d in ok["rfi_drafts"]})                              # closed by the accepted, document-confirmed fact

    def test_invalid_oversize_and_bad_requests(self):
        c, out = self.call("POST", f"/projects/{self.pid}/addenda", body(b"not a pdf"))
        self.assertEqual((c, out["code"]), (422, "INVALID_PDF"))
        c, out = self.call("POST", f"/projects/{self.pid}/addenda", {"filename": "x.pdf", "content_base64": "@@@", "by": "A B"})
        self.assertEqual(c, 422)
        c, out = self.call("POST", f"/projects/{self.pid}/addenda", {**body(decoy(G3_LINE)), "scope": {}})
        self.assertEqual(c, 400)
        big = decoy(G3_LINE) + b"\n%" + b"0" * 10_000_001 + b"\n%%EOF\n"
        c, out = self.call("POST", f"/projects/{self.pid}/addenda", body(big))
        self.assertEqual((c, out["code"]), (413, "TOO_LARGE"))

    def test_other_owner_cannot_reach_the_project(self):
        c, _ = self.call("POST", f"/projects/{self.pid}/addenda", body(decoy(G3_LINE)), owner=OWNER_B)
        self.assertEqual(c, 404)


class AddendumAsync(HttpBase):
    def test_post_returns_before_a_slow_parse_and_a_double_post_parses_once(self):
        import threading, time
        calls, gate = [], threading.Event()

        def slow(pages, ctx):
            calls.append(1)
            gate.wait(5)
            return [g3()], {"model": "decoy-parser-not-a-model"}
        pdf = decoy(G3_LINE)
        with mock.patch.object(server, "ADDENDUM_PARSER", slow):
            t0 = time.monotonic()
            c1, a = self.call("POST", f"/projects/{self.pid}/addenda", body(pdf))
            c2, b = self.call("POST", f"/projects/{self.pid}/addenda", body(pdf, name="again.pdf"))
            self.assertLess(time.monotonic() - t0, 3)                    # neither request waited for the parse
            self.assertEqual((c1, c2, a["status"], b["status"], a["intake_id"] == b["intake_id"]), (202, 202, "PROCESSING", "PROCESSING", True))
            gate.set()
            done = wait(self, self.pid, a["intake_id"])
        self.assertEqual((done["status"], len(calls)), ("PROPOSED", 1))      # one parse (one live call) however many times it was posted


class AddendumHttpEdges(HttpBase):
    def test_oversize_body_gets_a_clean_413_not_a_reset(self):
        for n in (15_000_000, 40_000_000):                      # just over the route limit, and ~4x the PDF limit
            c, out = self.call("POST", f"/projects/{self.pid}/addenda", raw=b"{" + b" " * n + b"}")
            self.assertEqual(c, 413, n)

    def test_decline_route_and_pending_blocks_release(self):
        with mock.patch.object(server, "ADDENDUM_PARSER", parser_for(g3())):
            c, up = self.call("POST", f"/projects/{self.pid}/addenda", body(decoy(G3_LINE)))
        done = wait(self, self.pid, up["intake_id"])
        self.assertEqual(done["status"], "PROPOSED")
        st = self.call("GET", f"/projects/{self.pid}")[1]
        c, out = self.call("POST", f"/projects/{self.pid}/release", {"approver": "A Name", "expected_scope_version": st["scope_version"],
                                                                      "expected_proposal_digest": st["proposal_digest"] or "0" * 64})
        self.assertEqual(c, 409)
        self.assertIn("ADDENDUM_PENDING", out["engine_codes"])
        c, bad = self.call("POST", f"/projects/{self.pid}/addenda/{up['intake_id']}/decline", {"by": "", "note": "n"})
        self.assertEqual(c, 409)
        c, ok = self.call("POST", f"/projects/{self.pid}/addenda/{up['intake_id']}/decline", {"by": "Named Reviewer", "note": "not needed"})
        self.assertEqual(c, 200)
        self.assertEqual(self.call("GET", f"/projects/{self.pid}/addenda/{up['intake_id']}")[1]["status"], "DECLINED")
        self.assertEqual(ok["scope_version"], st["scope_version"])


class AddendumDecide(HttpBase):
    def test_contradiction_is_held_with_both_citations_then_a_named_human_decides(self):
        line = "ITEM 2 GATE G2: THE CLEAR OPENING WIDTH IS 8 FEET (DECOY)"
        fact = {"path": "/gates/1/clear_width_ft", "value": 8, "unit": "ft", "page": 1, "excerpt": "THE CLEAR OPENING WIDTH IS 8 FEET"}
        with mock.patch.object(server, "ADDENDUM_PARSER", parser_for(fact)):
            c, up = self.call("POST", f"/projects/{self.pid}/addenda", body(decoy(line)))
        done = wait(self, self.pid, up["intake_id"])
        self.assertEqual(done["status"], "HELD_CONTRADICTORY")
        conf = done["intake"]["conflicts"][0]
        self.assertTrue(conf["established"]["citations"] and conf["addendum"]["citation"]["page"] == 1)
        self.assertIn("suggested_precedence", conf)
        pid, iid = self.pid, up["intake_id"]
        c, _ = self.call("POST", f"/projects/{pid}/addenda/{iid}/decide", {"by": "", "note": "n", "decision": "keep_established"})
        self.assertEqual(c, 409)
        c, out = self.call("POST", f"/projects/{pid}/addenda/{iid}/decide", {"by": "Named Decider", "note": "later addendum governs", "decision": "accept_addendum_value"})
        self.assertEqual(c, 200)
        self.assertEqual(self.call("GET", f"/projects/{pid}/addenda/{iid}")[1]["status"], "PROPOSED")


class AddendumAcceptanceRecord(HttpBase):
    def test_accept_route_records_the_acceptance_and_takes_an_optional_human_label(self):
        with mock.patch.object(server, "ADDENDUM_PARSER", parser_for(g3())):
            c, up = self.call("POST", f"/projects/{self.pid}/addenda", body(decoy(G3_LINE)))
        done = wait(self, self.pid, up["intake_id"])
        iid, v = done["intake_id"], self.call("GET", f"/projects/{self.pid}")[1]["scope_version"]
        self.assertTrue(all(done["intake"][k] is None for k in ("accepted_by", "accepted_utc", "accepted_note", "scope_version_produced", "addendum_label")))
        c, bad = self.call("POST", f"/projects/{self.pid}/addenda/{iid}/accept", {"by": "Named Reviewer", "note": "n", "scope_version": v, "proposal_digest": None, "addendum_label": "x" * 80})
        self.assertEqual(c, 409)
        c, bad = self.call("POST", f"/projects/{self.pid}/addenda/{iid}/accept", {"by": "Named Reviewer", "note": "n", "scope_version": v, "proposal_digest": None, "section": "1.1"})
        self.assertEqual(c, 400)                                                           # there is no section field
        c, ok = self.call("POST", f"/projects/{self.pid}/addenda/{iid}/accept", {"by": "Named Reviewer", "note": "checked page 1", "scope_version": v,
                                                                                  "proposal_digest": None, "addendum_label": "Addendum 02"})
        self.assertEqual(c, 200, ok)
        rec = next(r for r in ok["addenda"] if r["intake_id"] == iid)
        self.assertEqual((rec["accepted_by"], rec["accepted_note"], rec["scope_version_produced"], rec["addendum_label"]),
                         ("Named Reviewer", "checked page 1", v + 1, {"value": "Addendum 02", "source": "HUMAN"}))
        accepted = [e for e in ok["audit"] if e["event"] == "addendum_accepted"]
        self.assertEqual((accepted[-1]["intake_id"], accepted[-1]["actor"]), (iid, "Named Reviewer"))

"""overrides_acknowledged: exists only at release; lists every run-time override in force with releaser, UTC time, scope version and estimate / proposal revision;
changes no total, label, rule or fingerprint."""
import copy
import unittest

from engine import bid_schedule, wage_rows, workflow as wf
from pricing import quantities
from tests import footing_helpers as H
from tests.http_harness import HttpBase, WHO, plan
from tests.test_addendum_intake import SAME_LINES, W4, ALL_REFS, parser_for
from tests.test_wage_rows import MAP
from engine import addendum_intake as ai
from tests.decoy_pdf import decoy

RELEASER = "Visitor A (self-declared, fictional)"
IDS = ["gate_assembly_rate", "material_tax_exemption", "item_16_labor_coverage", "allowances", "certified_payroll_zero"]


def with_zero_payroll(st):
    wd = st["wage_determination"]
    rows = wage_rows.rows_from_workbook(st["ratebook"], wd["schedule"], MAP, "FDB-DP001 mod 0 Att. A")
    wf.record_wage_determination(st, by=H.WHO, note="test", determination=wd["determination"], schedule=wd["schedule"], rows=rows,
                                 employer_burden={"pct": 0.35, "source_ref": "pinned workbook Roles burden_pct"}, production_rates_approved=True,
                                 certified_payroll_admin={"basis": "not_charged", "reason": "the pinned workbook carries no such line", "source_ref": "workbook"})
    return st


def release(st):
    return wf.release(st, RELEASER, st["scope"]["scope_version"], st["proposal_digest"])


class Before(unittest.TestCase):
    def test_nothing_exists_before_release_or_after_a_refused_release(self):
        st = with_zero_payroll(H.priced())
        self.assertNotIn("overrides_acknowledged", st)
        for kw in (dict(expected_scope_version=st["scope"]["scope_version"] + 1, expected_proposal_digest=st["proposal_digest"]),
                   dict(expected_scope_version=st["scope"]["scope_version"], expected_proposal_digest="0" * 64)):
            with self.assertRaises(wf.GateError):
                wf.release(st, RELEASER, **kw)
            self.assertNotIn("overrides_acknowledged", st)
        with self.assertRaises(wf.GateError):                                   # an unnamed releaser records nothing
            wf.release(st, "  ", st["scope"]["scope_version"], st["proposal_digest"])
        self.assertNotIn("overrides_acknowledged", st)
        self.assertEqual(st["status"], wf.READY)


class After(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = with_zero_payroll(H.priced())
        cls.totals = {s: e["price_total"] for s, e in cls.st["estimate"]["scenarios"].items()}
        cls.digest = cls.st["proposal_digest"]
        cls.pkg = release(cls.st)
        cls.ack = cls.st["overrides_acknowledged"]

    def test_the_block_is_complete(self):
        a = self.ack
        self.assertEqual(sorted(a), ["bid_revisions", "estimate_digest", "overrides", "proposal_digest", "released_by", "released_utc", "scope_version"])
        self.assertEqual((a["released_by"], a["released_utc"], a["scope_version"], a["proposal_digest"], a["estimate_digest"]),
                         (RELEASER, self.st["released_at"], self.st["scope"]["scope_version"], self.st["proposal_digest"], self.st["estimate"]["digest"]))
        self.assertEqual([o["id"] for o in a["overrides"]], IDS)
        for o in a["overrides"]:
            self.assertEqual((o["acknowledged_by"], o["acknowledged_utc"], o["scope_version"], o["proposal_digest"]), (RELEASER, a["released_utc"], a["scope_version"], a["proposal_digest"]))
            self.assertEqual(o["decision"]["by"], "Jordan")
            self.assertTrue(o["decision"]["decided"] and o["statement"] and o["name"])
        by = {o["id"]: o for o in a["overrides"]}
        self.assertEqual(by["gate_assembly_rate"]["value"]["rate_per_lf"], 250.0)
        self.assertEqual(sorted(by["gate_assembly_rate"]["value"]["gate_lines"]), ["ALT-A1", "BASE"])
        self.assertEqual(by["allowances"]["value"], {"amount": 0.0, "locked": True})
        self.assertEqual(by["certified_payroll_zero"]["value"]["amount"], 0.0)
        self.assertIn("SC-3.6.1", by["material_tax_exemption"]["statement"])
        self.assertIn("top-rail", by["item_16_labor_coverage"]["statement"])

    def test_the_estimate_and_bid_revisions_match_the_released_state(self):
        view = bid_schedule.view(self.st)["scenarios"]
        self.assertEqual(self.ack["bid_revisions"], {s: v["bid_revision"] for s, v in view.items()})
        self.assertEqual(set(self.ack["bid_revisions"]), {"BASE", "ALT-A1"})

    def test_the_package_carries_the_same_block(self):
        self.assertEqual(self.pkg["overrides_acknowledged"], self.ack)

    def test_nothing_else_moved(self):
        self.assertEqual({s: e["price_total"] for s, e in self.st["estimate"]["scenarios"].items()}, self.totals)
        self.assertEqual(self.st["proposal_digest"], self.digest)                 # the block is not part of the proposal digest
        self.assertEqual(quantities.load_ruleset()["sha256"], "1845b6b0df7ad826685738fb85bf33b72016adb4e424e387548a9666d830ec4d")

    def test_without_the_zero_payroll_statement_it_is_not_listed(self):
        st = H.priced()                                                          # this project charges payroll administration per week
        release(st)
        self.assertNotIn("certified_payroll_zero", [o["id"] for o in st["overrides_acknowledged"]["overrides"]])


class Superseded(unittest.TestCase):
    def test_a_later_acceptance_moves_the_block_into_history_and_the_next_release_records_its_own(self):
        st = with_zero_payroll(H.priced())
        release(st)
        first = copy.deepcopy(st["overrides_acknowledged"])
        fact = {"path": "/gates/2/clear_width_ft", "value": 14, "unit": "ft", "page": 1, "excerpt": "THE CLEAR OPENING WIDTH IS 14 FEET"}
        from tests.decoy_pdf import G3_LINE
        rec = ai.submit_addendum(st, decoy(G3_LINE), "late.pdf", parser=parser_for(fact), by="Uploader (self-declared)")
        ai.accept_addendum_intake(st, intake_id=rec["intake_id"], by="Named Reviewer", note="late", scope_version=st["scope"]["scope_version"], proposal_digest=st["proposal_digest"])
        self.assertNotIn("overrides_acknowledged", st)                            # the release is superseded; nothing is left standing
        hist = [h for h in st["history"] if h["kind"] == "released_artifact"]
        self.assertEqual(hist[-1]["snapshot"]["overrides_acknowledged"], first)
        H.labor(st)
        with_zero_payroll(st)
        release(st)
        second = st["overrides_acknowledged"]
        self.assertGreater(second["scope_version"], first["scope_version"])
        self.assertNotEqual(second["proposal_digest"], first["proposal_digest"])


class Served(HttpBase):
    def test_summary_has_no_block_before_release_and_the_release_response_and_summary_have_it_after(self):
        self.to_wage_cleared()
        out = self.post("decisions/crew-plan", {**WHO, **plan("CR13")})
        self.assertNotIn("overrides_acknowledged", out)
        self.assertNotIn("overrides_acknowledged", self.get())
        code, rel = self.call("POST", f"/projects/{self.pid}/release", {"approver": "Test Approver", "expected_scope_version": out["scope_version"], "expected_proposal_digest": out["proposal_digest"]})
        self.assertEqual(code, 200, rel)
        # the summary always carries it after release; the release RESPONSE carries it for footing-scope projects only (the pinned legacy response shape is unchanged)
        a = self.get()["overrides_acknowledged"]
        self.assertEqual((a["released_by"], a["scope_version"], a["proposal_digest"]), ("Test Approver", out["scope_version"], out["proposal_digest"]))
        self.assertTrue(a["overrides"])
        self.assertNotIn("overrides_acknowledged", rel)                          # this demo project has no footing scope: its release response keeps the legacy shape

    def test_a_footing_scope_project_release_response_carries_the_block(self):
        from tests import footing_helpers as FH
        from api import server
        st = FH.priced()
        with server.LOCK:
            server.PROJECTS["fp"] = st
            server.META["fp"] = {"owner": None, "touched": 0, "mutations": 0}
        try:
            c, rel = self.call("POST", "/projects/fp/release", {"approver": "Test Approver", "expected_scope_version": st["scope"]["scope_version"], "expected_proposal_digest": st["proposal_digest"]}, owner=None)
        finally:
            server.PROJECTS.pop("fp", None)
            server.META.pop("fp", None)
        self.assertEqual(c, 200, rel)
        self.assertEqual(rel["overrides_acknowledged"]["released_by"], "Test Approver")


if __name__ == "__main__":
    unittest.main()

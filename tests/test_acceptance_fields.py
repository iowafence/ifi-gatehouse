"""Additive acceptance record: who accepted, when, with what note, which scope revision it produced, which intake and document (full sha256), and an optional
HUMAN addendum label. Empty until accepted, never defaulted. The citation has NO section field: the section is not stated."""
import copy
import unittest

from engine import addendum_intake as ai, workflow as wf
from pricing import quantities
from tests import footing_helpers as H
from tests.decoy_pdf import G3_LINE, decoy
from tests.test_addendum_intake import SAME_LINES, W4, ALL_REFS, parser_for, WHO

ACCEPT_KEYS = ("accepted_by", "accepted_utc", "accepted_note", "scope_version_produced", "addendum_label")
NAMED = "Named Reviewer (self-declared)"


def propose(st, label_lines=SAME_LINES, facts=(W4, *ALL_REFS), name="ADDENDUM_02.pdf"):
    return ai.submit_addendum(st, decoy(*label_lines), name, parser=parser_for(*facts), by=WHO)


def accept(st, rec, label=None, by=NAMED, note="checked page 1 against the Before/After"):
    return ai.accept_addendum_intake(st, intake_id=rec["intake_id"], by=by, note=note, scope_version=st["scope"]["scope_version"],
                                     proposal_digest=st.get("proposal_digest"), addendum_label=label)


def addendum_evidence(st, rec):
    out = []
    for u in rec["updates"]:
        out += [e for e in u["fact"]["evidence"] if e.get("doc_id") == rec["source"]["doc_id"]]
    return out


class Before(unittest.TestCase):
    def test_acceptance_fields_are_empty_before_acceptance_but_identity_is_present(self):
        st = H.start(H.fixture())
        rec = propose(st)
        self.assertEqual(rec["status"], ai.PROPOSED)
        for k in ACCEPT_KEYS:
            self.assertIsNone(rec[k], k)
        self.assertEqual((rec["intake_id"], rec["sha256"]), (rec["source"]["sha256"][:16], rec["source"]["sha256"]))
        ev = addendum_evidence(st, rec)
        self.assertEqual(len(ev), 4)
        for e in ev:
            self.assertTrue(all(e[k] is None for k in ACCEPT_KEYS), e)
            self.assertEqual((e["intake_id"], e["sha256"]), (rec["intake_id"], rec["sha256"]))
        self.assertEqual(st["scope"]["gates"][2]["clear_width_ft"]["status"], "unresolved")       # nothing reached the scope


class After(unittest.TestCase):
    def setUp(self):
        self.st = H.start(H.fixture())
        self.rec = propose(self.st)
        self.v0 = self.st["scope"]["scope_version"]
        accept(self.st, self.rec, label="Addendum 02")
        self.rec = self.st["addenda"][self.rec["intake_id"]]

    def test_the_record_carries_the_acceptance(self):
        r = self.rec
        self.assertEqual((r["status"], r["accepted_by"], r["accepted_note"], r["scope_version_produced"], r["applied_scope_version"]),
                         (ai.APPLIED, NAMED, "checked page 1 against the Before/After", self.v0 + 1, self.v0 + 1))
        self.assertEqual(r["scope_version_produced"], self.st["scope"]["scope_version"])
        self.assertRegex(r["accepted_utc"], r"^\d{4}-\d\d-\d\dT")
        self.assertEqual(r["addendum_label"], {"value": "Addendum 02", "source": "HUMAN"})
        self.assertEqual(len(r["sha256"]), 64)

    def test_every_addendum_evidence_entry_on_the_accepted_facts_carries_it(self):
        gates, cls = self.st["scope"]["gates"][2]["clear_width_ft"], self.st["scope"]["footing_scope"]["classes"]["GATE_G3"]
        facts = [gates] + [cls[k] for k in ("post_od_in", "diameter_in", "depth_in")]
        for f in facts:
            ev = [e for e in f["evidence"] if e.get("doc_id") == self.rec["source"]["doc_id"]]
            self.assertEqual(len(ev), 1)
            e = ev[0]
            self.assertEqual((e["accepted_by"], e["scope_version_produced"], e["accepted_utc"], e["accepted_note"], e["intake_id"], e["sha256"]),
                             (NAMED, self.v0 + 1, self.rec["accepted_utc"], self.rec["accepted_note"], self.rec["intake_id"], self.rec["sha256"]))
            self.assertEqual(e["addendum_label"], {"value": "Addendum 02", "source": "HUMAN"})
            self.assertEqual((e["page"], e["source_type"]), (1, "addendum_pdf"))
            self.assertNotIn("section", e)                                                         # the section is NOT STATED: no field, never inferred
        for e in cls["depth_in"]["evidence"]:                                                      # the source gate's own evidence is left exactly as it was
            if e.get("doc_id") != self.rec["source"]["doc_id"]:
                self.assertNotIn("accepted_by", e)

    def test_audit_events_carry_the_intake_the_acceptor_and_the_label(self):
        ev = {e["event"]: e for e in self.st["audit"] if e["event"] in ("addendum_accepted", "addendum_intake_accepted", "scope_revised")}
        a = ev["addendum_accepted"]
        self.assertEqual((a["intake_id"], a["actor"], a["scope_version"], a["addendum_label"]), (self.rec["intake_id"], NAMED, self.v0 + 1, {"value": "Addendum 02", "source": "HUMAN"}))
        self.assertEqual(ev["addendum_intake_accepted"]["scope_version_produced"], self.v0 + 1)
        self.assertEqual(ev["scope_revised"]["after_version"], self.v0 + 1)


class Label(unittest.TestCase):
    def test_no_label_stays_empty_and_is_never_inferred_from_the_filename_or_document(self):
        st = H.start(H.fixture())
        rec = propose(st, name="ADDENDUM_02.pdf")
        accept(st, rec)                                                                             # no label given
        r = st["addenda"][rec["intake_id"]]
        self.assertIsNone(r["addendum_label"])
        self.assertIsNone(next(e for e in st["audit"] if e["event"] == "addendum_accepted").get("addendum_label"))
        self.assertTrue(all(e["addendum_label"] is None for e in addendum_evidence(st, r)))
        self.assertIn("ADDENDUM_02", r["filename"])                                                 # the filename says "02" and the engine did not use it

    def test_blank_label_is_empty_and_bad_labels_are_refused_before_anything_changes(self):
        for blank in ("", "   ", None):
            st = H.start(H.fixture())
            rec = propose(st)
            accept(st, rec, label=blank)
            self.assertIsNone(st["addenda"][rec["intake_id"]]["addendum_label"])
        for bad in (5, ["Addendum 02"], "x" * 61, "line\nbreak"):
            st = H.start(H.fixture())
            rec = propose(st)
            before = copy.deepcopy(st)
            with self.assertRaises(wf.GateError):
                accept(st, rec, label=bad)
            self.assertEqual(st, before)
            self.assertEqual(st["addenda"][rec["intake_id"]]["status"], ai.PROPOSED)


class Unchanged(unittest.TestCase):
    def test_the_label_and_the_acceptance_fields_never_move_a_total_or_a_quantity(self):
        fact = {"path": "/gates/2/clear_width_ft", "value": 14, "unit": "ft", "page": 1, "excerpt": "THE CLEAR OPENING WIDTH IS 14 FEET"}
        runs = []
        for label in (None, "Addendum 02", "Addendum 07"):
            st = H.priced()
            rec = propose(st, label_lines=[G3_LINE], facts=(fact,))
            accept(st, rec, label=label)
            H.labor(st)                                                                              # the acceptance invalidated labor; re-approve as the workflow requires
            self.assertEqual(st["status"], wf.READY)
            runs.append(({s: e["price_total"] for s, e in st["estimate"]["scenarios"].items()},
                         {s: [(i.get("item_id") or i["driver_key"], i["quantity"]) for i in p["items"]] for s, p in st["quantities"].items()}))
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(runs[1], runs[2])

    def test_the_ruleset_fingerprint_is_unchanged(self):
        self.assertEqual(quantities.load_ruleset()["sha256"], "5bd9e61a74267592a03b986851aaa8990270a8ee655c60af475477b9176068b5")


if __name__ == "__main__":
    unittest.main()

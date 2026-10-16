"""Deterministic RFI drafts for genuinely unresolved gate facts. CODE only: no model, no candidate values.

A draft is created PENDING. Nothing here approves or sends it: only a named human does that, outside this module.
A draft asks; it never states, suggests or implies a width, post size, footing diameter or depth.
Only facts whose status is `unresolved` produce a draft, so a gate whose facts are established (G2: Addendum 01 item 1.5 and
Detail 3/F501 supply its post and footing) can never get one. G3's opening and G3's post/footing are separate questions, each
tracked by its own unresolved facts."""
from .util import get_ptr

PENDING = "PENDING_NAMED_HUMAN_APPROVAL"

DRAWINGS, MANUAL, ADD01 = "dp001_ansi_b_v2_drawings", "dp001_project_manual_ansi_b_pkg", "dp001_addendum_01_ansi_b_pkg"

# Citations checked against the ingested PDFs by tests/test_rfi_drafts.py. Excerpts are verbatim document text.
CITE = {
    "F502_NOTE_4": {"doc_id": DRAWINGS, "doc_revision": 0, "page": 5, "sheet_label": "F502 note 4",
                    "excerpt": "GATE G3: CLEAR OPENING WIDTH IS NOT SPECIFIED AND GATE POST SIZE IS NOT SPECIFIED"},
    "F502_SCHEDULE": {"doc_id": DRAWINGS, "doc_revision": 0, "page": 5, "sheet_label": "F502 gate schedule, G3 column",
                      "excerpt": "NOT SPECIFIED - SEE NOTE 4"},
    "C101_NOTE_7": {"doc_id": DRAWINGS, "doc_revision": 0, "page": 2, "sheet_label": "C101 keynote 7",
                    "excerpt": "GATE G3. LOCATION SHOWN BY SYMBOL ONLY, NOT TO SCALE; DO NOT SCALE"},
    "SPEC_2_5_I": {"doc_id": MANUAL, "doc_revision": 0, "page": 15, "sheet_label": "32 31 13 2.5.I",
                   "excerpt": "As indicated on the Drawings"},
    "SPEC_2_1_B": {"doc_id": MANUAL, "doc_revision": 0, "page": 14, "sheet_label": "32 31 13 2.1.B",
                   "excerpt": "gate posts for G3: size confirmed with the"},
    "SPEC_3_2_D": {"doc_id": MANUAL, "doc_revision": 0, "page": 16, "sheet_label": "32 31 13 3.2.D",
                   "excerpt": "Gate posts and footings not otherwise noted are as for terminal posts, Detail 3/F501."},
    "F502_NOTE_5": {"doc_id": DRAWINGS, "doc_revision": 0, "page": 5, "sheet_label": "F502 note 5",
                    "excerpt": "GATE POSTS AND FOOTINGS NOT OTHERWISE NOTED: AS FOR TERMINAL POSTS, 3/F501"},
    "ADD01_2_2": {"doc_id": ADD01, "doc_revision": 1, "page": 1, "sheet_label": "Addendum 01 item 2.2",
                  "excerpt": "This Addendum does not establish the clear opening width of Gate G3."},
}

OPENING_PATH = "/gates/{i}/clear_width_ft"
# Only the post size is asked. G3's footing diameter and depth are NOT "otherwise noted" (F502 note 4 names only the opening width and the
# post size), so 32 31 13 3.2.D and F502 note 5 give them: as for terminal posts, Detail 3/F501. They are never put in an RFI.
FOOTING_FIELDS = (("post_od_in", "gate post size (outside diameter)"),)
FOOTING_NOT_ASKED = ("diameter_in", "depth_in")


def _unresolved(fact):
    """True while the document set has not supplied the fact: missing, or only a human-typed assumption (RFI still pending)."""
    if not isinstance(fact, dict):
        return False
    return (fact.get("status") == "unresolved" and fact.get("value") is None) or fact.get("status") == "human_resolved"


def _basis(facts):
    return "ASSUMED_RFI_PENDING" if any(isinstance(f, dict) and f.get("status") == "human_resolved" for f in facts) else "MISSING_VALUE"


def _draft(draft_id, gate_id, subject, requests, cites, paths, basis, not_asked=None):
    return {"draft_id": draft_id, "kind": "RFI_DRAFT", "gate_id": gate_id, "subject": subject, "requests": requests,
            "citations": [dict(CITE[c]) for c in cites], "unresolved_paths": paths, "not_asked": not_asked or [],
            "candidate_values": None, "basis_state": basis, "status": PENDING, "approved_by": None, "approved_utc": None, "sent": False}


def g3_rfi_drafts(scope):
    """Return the pending RFI drafts the scope's unresolved G3 facts call for (possibly none)."""
    drafts = []
    gates = scope.get("gates")
    for i, g in enumerate(gates if isinstance(gates, list) else []):
        if isinstance(g, dict) and g.get("gate_id") == "G3" and _unresolved(g.get("clear_width_ft")):
            drafts.append(_draft(
                "RFI-G3-OPENING", "G3", "Gate G3 clear opening width",
                ["State the clear opening width of Gate G3, face of gate post to face of gate post."],
                ["F502_NOTE_4", "F502_SCHEDULE", "C101_NOTE_7", "SPEC_2_5_I", "ADD01_2_2"], [OPENING_PATH.format(i=i)], _basis([g.get("clear_width_ft")])))
    try:
        cls = get_ptr(scope, "/footing_scope/classes/GATE_G3")
    except (KeyError, IndexError, ValueError, TypeError):
        cls = None
    if isinstance(cls, dict):
        open_fields = [(f, label) for f, label in FOOTING_FIELDS if _unresolved(cls.get(f))]
        if open_fields:
            drafts.append(_draft(
                "RFI-G3-POST-OD", "G3", "Gate G3 post size",
                [f"State the {label} for Gate G3." for _, label in open_fields],
                ["F502_NOTE_4", "F502_SCHEDULE", "SPEC_2_1_B", "ADD01_2_2"],
                [f"/footing_scope/classes/GATE_G3/{f}" for f, _ in open_fields], _basis([cls.get(f) for f, _ in open_fields]),
                not_asked=[{"fields": [f"/footing_scope/classes/GATE_G3/{f}" for f in FOOTING_NOT_ASKED],
                            "reason": "supplied by the documents; not an open question", "citations": [dict(CITE["SPEC_3_2_D"]), dict(CITE["F502_NOTE_5"])]}]))
    return drafts

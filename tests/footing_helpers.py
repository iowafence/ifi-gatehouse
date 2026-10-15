"""Shared helpers for the footing-scope.v1 tests: fixtures, an in-process DP-001 flow through the real workflow, closed-form footing arithmetic."""
import copy
import json
import math
import pathlib

from engine import workflow as wf
from pricing import quantities, ratebook as pratebook
from tests.test_ratebook_workflow import wage_args

FIX = pathlib.Path(__file__).resolve().parent / "footing_fixtures"
ROOT = pathlib.Path(__file__).resolve().parent.parent
WHO = "Visitor A (self-declared, fictional)"
AS_OF = "2026-10-13"
_book = None


def book():
    global _book
    if _book is None:
        _book = pratebook.import_workbook((ROOT / "samples/public-demo/reference_pricing_workbook_v2_3_0.fictional.xlsx").read_bytes())["ratebook"]
    return copy.deepcopy(_book)


def fixture(name="dp001_footing_scope.json"):
    return json.loads((FIX / name).read_text())


def params():
    return quantities.load_ruleset()["rules"]["params"]


def vol(d, h):
    """Independent closed form: CU YD of one cylindrical footing."""
    return math.pi * (d / 2) ** 2 * h / 46656


def start(scope):
    return wf.start(copy.deepcopy(scope), None, ratebook=book(), policy={"as_of": AS_OF})


def blocking(st):
    return [e for e in st["exceptions"] if e["severity"] == "blocking"]


def approve_inferred(st):
    n = 0
    while True:
        inf = [e for e in blocking(st) if e["code"] == "INFERRED_FACT_UNAPPROVED"]
        if not inf:
            return n
        wf.resolve(st, inf[0]["exception_id"], option_id="approve_inferred", by=WHO, note="derivation checked against the cited dimensions")
        n += 1


def select(st, option):
    ex = next(e for e in blocking(st) if e["code"] == "BID_SELECTION_REQUIRED")
    wf.resolve(st, ex["exception_id"], option_id=option, by=WHO, note="bid option selected for this estimate")


def give(st, path_part, value, note="WHAT-IF ONLY: not stated in any document"):
    ex = next(e for e in blocking(st) if e["code"] == "MISSING_VALUE" and path_part in e["exception_id"])
    wf.resolve(st, ex["exception_id"], value=value, by=WHO, note=note)


def g3_whatif(st, width=12.0, footing=(16.0, 48.0, 2.875)):
    """The self-declared demonstration assumptions: a G3 clear opening and (optionally) a G3 post/footing. Labelled WHAT-IF, never documented."""
    give(st, "gates/2/clear_width_ft", width, "WHAT-IF ONLY: G3 clear opening assumed; not stated in any document")
    if footing:
        for part, v in zip(("GATE_G3/diameter_in", "GATE_G3/depth_in", "GATE_G3/post_od_in"), footing):
            give(st, part, v, "WHAT-IF ONLY: G3 post/footing assumed for demonstration; RFI open")


def labor(st, drill="CR13"):
    if not st.get("ruleset_approval"):
        wf.approve_quantity_ruleset(st, by=WHO, note="self-declared demo approval of the DRAFT ruleset", ruleset_sha256=st["ruleset"]["sha256"])
    wf.record_wage_determination(st, **wage_args())
    wf.approve_crew_plan(st, by=WHO, note="self-declared demo crew plan (fleet crew)", preferred_crew=drill, assignments={"L02": drill},
                         use_default_for_unassigned=False, difficulty={"default": "standard", "overrides": {}})
    return st


def priced(scenario="BASE", scope=None, whatif=True):
    """DP-001 driven to a priced (ready) state through the real gates."""
    st = start(scope or fixture())
    select(st, "base" if scenario == "BASE" else "ALT-A1")
    approve_inferred(st)
    if whatif:
        g3_whatif(st)
    approve_inferred(st)
    labor(st)
    return st


def qty(st, sref):
    return {(i.get("item_id") or i.get("driver_key")): i for i in st["quantities"][sref]["items"]}

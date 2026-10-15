"""Synthetic, fictional scope fixtures for pricing tests. Run lengths, footings and every dollar are invented; none of it is taken from any
answer key. Gate types follow the issued DP-001 documents (Section 32 31 13 2.5.I and Addendum 01 item 1): G1 pedestrian 4'-0" x1; G2 revised
by Addendum 01 from a 6'-0" single leaf to a 12'-0" DOUBLE-leaf opening, quantity 2; G3 single leaf whose width is NOT in the documents.
ADDENDUM_02_TEST_WIDTH_FT is a TEST VALUE only."""
import copy

ADDENDUM_02_TEST_WIDTH_FT = 10.0


def ev(doc="PLANS", page=2, sheet="C101", rev=0, excerpt="synthetic"):
    return {"doc_id": doc, "page": page, "sheet_label": sheet, "source_type": "plan_sheet", "excerpt": excerpt, "doc_revision": rev}


def fact(value, status="confirmed", unit=None, **evkw):
    f = {"value": value, "status": status}
    if status == "unresolved":
        f["evidence"] = []
        return f
    if unit:
        f["unit"] = unit
    if status == "inferred":
        f["inference_note"] = "derived in test"
    f["evidence"] = [ev(**evkw)]
    return f


def base_scope():
    """Original package + Addendum 01 (G2 is a 12 ft double-leaf opening, doc_revision 1). G3 width is NOT in the documents."""
    return {
        "scope_version": 1, "project_ref": "SYN-GATEHOUSE-TEST",
        "documents": [{"doc_id": "PLANS", "doc_type": "synthetic", "revision": 0}, {"doc_id": "ADD01", "doc_type": "addendum", "revision": 1}],
        "fence_runs": [
            {"run_id": "FR-A", "label": "Type A perimeter", "fence_type": fact("chain_link"), "height_ft": fact(10.0, unit="ft"),
             "length_lf": fact(400.0, unit="lf"), "section_spacing_ft": fact(10.0),
             "post": {"terminal_od_in": fact(2.875), "line_od_in": fact(2.375)}, "geometry": {"closed": True, "corners": 4}},
            {"run_id": "FR-B", "label": "Type B divider", "fence_type": fact("chain_link"), "height_ft": fact(3.5, unit="ft"),
             "length_lf": fact(150.0, unit="lf"), "section_spacing_ft": fact(10.0),
             "post": {"terminal_od_in": fact(2.375), "line_od_in": fact(1.875)}, "geometry": {"closed": False, "corners": 0, "free_ends": 2}},
        ],
        "gates": [
            {"gate_id": "G1", "run_id": "FR-A", "gate_kind": fact("single_swing"), "clear_width_ft": fact(4.0, unit="ft", sheet="32 31 13 2.5.I"),
             "height_ft": fact(7.0, unit="ft"), "quantity": 1, "transom": {"included_in_gate_item": True}},
            {"gate_id": "G2", "run_id": "FR-A", "gate_kind": fact("double_swing", doc="ADD01", page=1, sheet="ADD-01", rev=1, excerpt="double leaf"),
             "clear_width_ft": fact(12.0, unit="ft", doc="ADD01", page=1, sheet="ADD-01", rev=1,
                                    excerpt="Gate G2 revised from 6'-0\" single leaf to a 12'-0\" clear opening, double leaf (two 6'-0\" leaves)"),
             "height_ft": fact(7.0, unit="ft"), "quantity": 2, "transom": {"included_in_gate_item": True}},
            {"gate_id": "G3", "run_id": "FR-A", "gate_kind": fact("single_swing"), "clear_width_ft": fact(None, "unresolved"),
             "height_ft": fact(7.0, unit="ft"), "quantity": 1, "transom": {"included_in_gate_item": True}},
        ],
        "accessories": [
            {"accessory_id": "AC-WIND", "kind": "windscreen", "length_lf": fact(120.0, unit="lf"), "height_ft": fact(9.0, unit="ft")},
        ],
        "bid_structure": {
            "pricing_basis": "unit_price", "pay_items": [],
            "alternates": [{"alternate_id": "ALT-A1", "label": "Reduced divider and windscreen", "scope_change": "shorter divider, less windscreen",
                            "patch": [{"op": "replace", "path": "/fence_runs/1/length_lf", "value": fact(120.0, unit="lf")},
                                      {"op": "replace", "path": "/accessories/0/length_lf", "value": fact(90.0, unit="lf")}]}],
            "selected_bid": {"value": "base", "status": "human_resolved", "evidence": [{"doc_id": "human", "page": 1, "source_type": "human_resolution", "excerpt": "base"}]},
        },
        "global_requirements": {
            "core_drilling_required": fact("no"),
            "prevailing_wage_required": fact("no", sheet="00 0800"), "owner_sales_tax_exempt": fact("no", sheet="00 0800"),
            "top_rail_continuous_across_gate_openings": fact("yes", sheet="F501", excerpt="top rail continuous across gate openings"),
            "footing_terminal_diameter_in": fact(12.0), "footing_terminal_depth_in": fact(42.0),
            "footing_line_diameter_in": fact(10.0), "footing_line_depth_in": fact(42.0),
        },
    }


def with_g3(width=ADDENDUM_02_TEST_WIDTH_FT):
    """Scope as it stands after Addendum 02 has been applied (test value only)."""
    s = copy.deepcopy(base_scope())
    s["gates"][2]["clear_width_ft"] = fact(width, unit="ft", doc="ADD02", page=1, sheet="ADD-02", rev=2, excerpt="Gate G3 clear width (test value)")
    return s


def addendum_02_facts(width=ADDENDUM_02_TEST_WIDTH_FT):
    return [{"path": "/gates/2/clear_width_ft",
             "fact": fact(width, unit="ft", doc="ADD02", page=1, sheet="ADD-02", rev=2, excerpt="Gate G3 clear width (test value)")}]


def dp001_requirements(scope):
    """Layer the DP-001 requirements the catalog now prices onto a scope: fence guard on the Type B divider, core drilling at every
    footing, owner sales-tax exemption and Davis-Bacon. (Quantities stay invented.)"""
    import copy as _c
    s = _c.deepcopy(scope)
    ge = s["global_requirements"]
    ge["core_drilling_required"] = fact("yes", sheet="32 31 13 3.2.E")
    ge["owner_sales_tax_exempt"] = fact("yes", sheet="00 0800 SC-3.6.1")
    ge["prevailing_wage_required"] = fact("yes", sheet="00 0800 SC-3.4.1")
    s["accessories"].append({"accessory_id": "AC-GUARD", "kind": "fence_guard", "length_lf": fact(150.0, unit="lf", sheet="SC item 16"), "height_ft": fact(3.5, unit="ft")})
    return s

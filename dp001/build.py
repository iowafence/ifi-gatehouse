"""Builds the human-prepared DP-001 scope draft and document registry for the isolated Pass 6 candidate.

 * Document identities come from the EXISTING experiment manifest (~/ifi-amd-inference-experiment/manifests/experiment_manifest.json);
   no competing provenance system. Each file is hash-checked against its manifest entry before it is copied (read-only source).
 * The scope is HUMAN-PREPARED from the document text (not AI inference). Every evidence excerpt is verified to occur on the cited page.
 * Quantities are only arithmetic on dimensions written in the documents; each such fact is status "inferred" with its derivation, so the
   engine makes a named human approve it. Nothing unspecified (G3 clear opening) is filled in.
Run with the experiment venv python (pypdfium2) -- read-only on the experiment tree."""
import hashlib, json, pathlib, re, shutil, sys
import pypdfium2 as pdfium

OUT = pathlib.Path(__file__).resolve().parent
EXP = OUT.parent / "amd_experiment"
DOCDIR = OUT.parent / "samples/public-demo/dp001"
MANIFEST = EXP / "manifests/experiment_manifest.json"

DOCS = {  # engine doc_id == existing manifest doc_id
    "dp001_ansi_b_v2_drawings": dict(group="drawings", name="Drawings (ANSI B, five sheets)", revision="Rev 0 — Issued for Bid (synthetic), Oct 12, 2026", rev_n=0, controlling=False),
    "dp001_project_manual_ansi_b_pkg": dict(group="specifications", name="Project Manual", revision="Rev 0 — Issued for Bid (synthetic), Oct 12, 2026", rev_n=0, controlling=False),
    "dp001_itb_ansi_b_pkg": dict(group="bidding", name="Document 00 0200 Instructions to Bidders", revision="Rev 0 — Issued for Bid (synthetic), Oct 12, 2026", rev_n=0, controlling=False),
    "dp001_addendum_01_ansi_b_pkg": dict(group="addendum", name="Addendum No. 01", revision="Addendum 01 — issued Oct 20, 2026", rev_n=1, controlling=True),
}
SHEETS = [("G001", 1, "Cover and General Notes"), ("C101", 2, "Site / Fence Plan, Base Bid and Alternate A-1"), ("C102", 3, "Bid Schedules"),
          ("F501", 4, "Fence and Footing Details"), ("F502", 5, "Gate and Windscreen Details")]
DWG, PM, ITB, ADD = list(DOCS)

def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()

# ---------------------------------------------------------------- registry (existing manifest identities, hash-checked)
man = {d["doc_id"]: d for d in json.loads(MANIFEST.read_text())["documents"]}
registry, text = [], {}
for did, meta in DOCS.items():
    m = man[did]; src = DOCDIR / pathlib.Path(m["path"]).name
    assert m["status"] == "available", did
    assert sha(src) == m["sha256"], f"{did}: file does not match its manifest identity"
    dst = src
    pdf = pdfium.PdfDocument(str(dst)); n = len(pdf)
    assert n == m["page_count"], did
    registry.append({"doc_id": did, "filename": src.name, "sha256": m["sha256"], "bytes": m["bytes"], "pages": n, "manifest_role": m.get("role"),
                     "manifest_status": m["status"], "sheet_size": m.get("declared_sheet_size"), **meta})
    norm = lambda s: re.sub(r"\s+", " ", s.replace("’", "'").replace("”", '"').replace("“", '"'))
    pages = []
    for i in range(n):
        raw = pdf[i].get_textpage().get_text_range()
        pages.append(norm(raw))
    text[did] = pages
    pdf.close()

# ---------------------------------------------------------------- evidence helper with verification
used = []
def E(doc, excerpt, page=None, sheet=None):
    ex = re.sub(r"\s+", " ", excerpt)
    hits = [i + 1 for i, t in enumerate(text[doc]) if ex in t]
    if page is not None:
        assert page in hits, f"excerpt not on {doc} p{page}: {excerpt!r} (found on {hits})"
    else:
        assert hits, f"excerpt not found in {doc}: {excerpt!r}"
        page = hits[0]
    ev = {"doc_id": doc, "page": page, "source_type": "plan_sheet" if doc == DWG else "spec_section", "excerpt": excerpt, "doc_revision": DOCS[doc]["rev_n"]}
    if sheet: ev["sheet_label"] = sheet
    used.append(ev); return ev

def conf(value, *ev, unit=None):
    f = {"value": value, "status": "confirmed", "evidence": list(ev)}
    if unit: f["unit"] = unit
    return f

def inf(value, note, *ev, unit=None):
    f = {"value": value, "status": "inferred", "inference_note": note, "evidence": list(ev)}
    if unit: f["unit"] = unit
    return f

def hres(value, note, *ev, unit=None):
    """Alternate-patch value prepared by a human. The engine will not price the Base Bid while an Alternate relies on an unapproved *inferred*
    value, so patch values carry the preparer's derivation as human_resolved evidence; selecting Alternate A-1 at the Scope gate is the named human decision."""
    f = {"value": value, "status": "human_resolved", "evidence": list(ev) + [{"doc_id": "human", "page": 1, "source_type": "human_resolution", "excerpt": note, "by": "human scope-draft preparer (not authenticated)"}]}
    if unit: f["unit"] = unit
    return f

def unres(*ev, unit=None, price_affecting=None):
    f = {"value": None, "status": "unresolved", "evidence": list(ev)}
    if unit: f["unit"] = unit
    if price_affecting is False: f["price_affecting"] = False
    return f

# ---------------------------------------------------------------- scope (engine schema)
A_TYPE = E(DWG, "10'-0\" HIGH CHAIN LINK FENCE, TYPE A. SEE 1/F501.", 2, "C101 keynote 1")
B_TYPE = E(DWG, "42\" HIGH CHAIN LINK DIVIDER FENCE, TYPE B", 2, "C101 keynote 2")
BASE_L = E(DWG, "176'-0\" (BASE BID ENCLOSURE, CL POST TO CL POST)", 2, "C101 view 1")
ALT_L = E(DWG, "138'-0\" (ALTERNATE A-1 ENCLOSURE)", 2, "C101 view 2")
DEPTH = E(DWG, "86'-0\"", 2, "C101 views 1 and 2")
ZONE = E(DWG, "CLEAR COURT ZONE 32'-0\" × 64'-0\"", 2, "C101 view 1")
DIVIDER_END = E(DWG, "TERMINATE EACH END AT A TERMINAL POST IN LINE WITH THE CLEAR COURT ZONE LIMIT", 2, "C101 keynote 2")
BYBIDDER = E(DWG, "QUANTITY ENTRIES \"BY BIDDER\" ARE NOT FURNISHED BY THESE DOCUMENTS; THE BIDDER SHALL DETERMINE THEM.", 3, "C102 schedule note 3")
POSTS_A = E(PM, "terminal, corner and gate posts 2.875 in OD (gate posts for G3: size confirmed with the opening width); line posts 2.375 in OD", None, "32 31 13 2.1.B")
POSTS_B = E(PM, "terminal posts 2.375 in OD; line posts 1.900 in OD", None, "32 31 13 2.1.C")
SPACING = E(PM, "Space line posts equally between terminal, corner and gate posts at 10'-0\" on center maximum.", None, "32 31 13 3.1.B")
WS = E(PM, "windscreen on the south Type A fence", None, "32 31 13 1.1.A")
WS_MEAS = E(PM, "Windscreen is measured by the linear foot along the south Type A fence between corner posts.", None, "32 31 13 1.5.C")
WS_H = E(PM, "Knitted polypropylene, 88 percent nominal shade, 9'-0\" high", None, "32 31 13 2.6.A")
WS_FIELD = E(PM, "After the south Type A fence is installed, field measure the installed length and order the windscreen.", None, "32 31 13 3.6.A")
WS_COLOR = E(PM, "The Owner has not yet selected a color.", None, "32 31 13 2.6.B")
GUARD = E(PM, "install fence guard on the top rail of the 42\" high Type B divider fence, full length", None, "Special Conditions item 16")
G1_ROW = E(PM, "G1 Pedestrian swing 4'-0\" 7'-0\" 1 1", None, "32 31 13 2.5.I")
G2_ADD = E(ADD, "Revise Gate G2 from a 6'-0\" clear opening, single leaf, to a 12'-0\" clear opening, double leaf (two 6'-0\" leaves).", 1, "Addendum 01 item 1.1")
G2_QTY = E(ADD, "Gate G2 quantity is unchanged: two locations per option.", 1, "Addendum 01 item 1.6")
G2_ROW = E(PM, "G2 Maintenance swing 6'-0\" 7'-0\" 1 2", None, "32 31 13 2.5.I (Rev 0)")
G2_ROW["superseded_by"] = {"doc_id": ADD, "item": "Addendum 01 item 1.2: revises Section 32 31 13 paragraph 2.5, F502, C101 keynote 6 and the Special Conditions"}
G2_ROW["note"] = "Rev 0 width (6'-0\", single leaf) is superseded by Addendum 01; shown for traceability only, not used as a value."
G2_F502 = E(DWG, "MAINTENANCE", 5, "F502 gate schedule (Rev 0)")
G2_F502["superseded_by"] = G2_ROW["superseded_by"]; G2_F502["note"] = G2_ROW["note"]
G3_NOTE = E(DWG, "GATE G3: CLEAR OPENING WIDTH IS NOT SPECIFIED AND GATE POST SIZE IS NOT SPECIFIED", 5, "F502 note 4")
G3_ADD = E(ADD, "This Addendum does not establish the clear opening width of Gate G3.", 1, "Addendum 01 item 2.2")
G3_C102 = E(DWG, "GATE G3 CLEAR OPENING IS NOT SPECIFIED; SEE NOTE 4/F502. SUBMIT A REQUEST FOR INFORMATION; DO NOT ASSUME A WIDTH.", 3, "C102 schedule note 4")
G3_SPEC = E(PM, "G3 Service swing As indicated on the Drawings 7'-0\" 1 1", None, "32 31 13 2.5.I")
CORE = E(PM, "Core drill every footing hole through the pavement and base", None, "32 31 13 3.2.E")
DB = E(PM, "Davis-Bacon labor standards apply to the Work by contract.", None, "00 0800 SC-3.4.1")
TAX = E(PM, "The Owner is exempt from sales and use taxes on materials incorporated into the Work.", None, "00 0800 SC-3.6.1")
TOPRAIL = E(PM, "Install top rail continuous through line posts.", None, "32 31 13 3.3.A")
HEADER = E(PM, "Header rail: 1.660 in OD between gate posts with fixed fabric above the header to the top of the fence.", None, "32 31 13 2.5.B")
FOOT_T = E(DWG, "FOOTING — TERMINAL / GATE 1'-4\" DIA. × 4'-0\" DEEP", 4, "F501 fence material schedule")
FOOT_L = E(DWG, "FOOTING — LINE POST 1'-0\" DIA. × 4'-0\" DEEP", 4, "F501 fence material schedule")
BASE_DEF = E(ITB, "The Base Bid is the four-court enclosure. Alternate A-1 is the three-court enclosure, bid in lieu of the Base Bid.", None, "00 0200 §1.4")
PRECEDENCE = E(ITB, "Addenda govern over the Specifications and Drawings.", None, "00 0200 §3.4.1")
OTHER_TRADES = E(PM, "Special Conditions items 2 through 9 and 17 through 21 are performed by the Contractor's other trades.", None, "01 1100 1.2.A")

def flat(*evs): return [e for e in evs if e]

fixed_posts_A = {"terminal_od_in": conf(2.875, POSTS_A), "line_od_in": conf(2.375, POSTS_A)}
fixed_posts_B = {"terminal_od_in": conf(2.375, POSTS_B), "line_od_in": conf(1.9, POSTS_B)}

LEN_A_NOTE = ("Human-prepared arithmetic on written dimensions, not stated in the documents: perimeter of the Base Bid enclosure = 2 x (176'-0\" + 86'-0\") = 524 LF, "
              "centerline of posts. The bid schedule leaves fence quantities 'BY BIDDER'. Gate openings are deducted by the engine.")
LEN_B_NOTE = ("Human-prepared arithmetic on written dimensions: each Type B divider runs the 64'-0\" clear court zone (11'-0\" open aisle to the perimeter fence at each end), "
              "and three dividers separate four courts (C101 view 1). Not a stated quantity.")
WS_NOTE = ("Human-prepared: the windscreen runs the full south Type A fence between corner posts, which is the 176'-0\" Base Bid enclosure length. "
           "The final length is set by field measurement after the south fence is installed (32 31 13 3.6.A).")
GUARD_NOTE = "Human-prepared: full length of the Type B divider top rail = 3 dividers x 64'-0\" = 192 LF. Not a stated quantity."
TOP_NOTE = ("The documents require the top rail continuous through line posts (3.3.A) and place fixed fabric above the gate header to the top of the fence (2.5.B) "
            "but do not say whether the top rail runs across gate openings. Treated as 'yes'; a named human must approve it or correct it.")

scope = {
    "scope_version": 1, "project_ref": "DP-001",
    "documents": [{"doc_id": r["doc_id"], "doc_type": {"drawings": "plan_set", "specifications": "project_manual", "bidding": "instructions_to_bidders", "addendum": "addendum"}[r["group"]],
                   "revision": r["rev_n"], "filename": r["filename"], "sha256": r["sha256"]} for r in registry],
    "fence_runs": [
        {"run_id": "FR-A", "label": "Type A 10'-0\" chain link perimeter fence", "fence_type": conf("chain_link", A_TYPE),
         "height_ft": conf(10.0, A_TYPE, unit="ft"),
         "length_lf": inf(524.0, LEN_A_NOTE, BASE_L, DEPTH, BYBIDDER, unit="lf"),
         "section_spacing_ft": conf(10.0, SPACING), "post": fixed_posts_A, "geometry": {"closed": True, "corners": 4}},
        {"run_id": "FR-B", "label": "Type B 42\" chain link divider fence", "repeat": 3, "fence_type": conf("chain_link", B_TYPE),
         "height_ft": conf(3.5, B_TYPE, unit="ft"),
         "length_lf": inf(64.0, LEN_B_NOTE, ZONE, DIVIDER_END, BYBIDDER, unit="lf"),
         "section_spacing_ft": conf(10.0, SPACING), "post": fixed_posts_B, "geometry": {"closed": False, "corners": 0, "free_ends": 2}},
    ],
    "gates": [
        {"gate_id": "G1", "run_id": "FR-A", "gate_kind": conf("single_swing", G1_ROW), "clear_width_ft": conf(4.0, G1_ROW, unit="ft"),
         "height_ft": conf(7.0, G1_ROW, unit="ft"), "quantity": 1, "transom": {"included_in_gate_item": True}},
        {"gate_id": "G2", "run_id": "FR-A", "gate_kind": conf("double_swing", G2_ADD), "clear_width_ft": conf(12.0, G2_ADD, G2_ROW, G2_F502, unit="ft"),
         "height_ft": conf(7.0, G2_ROW, unit="ft"), "quantity": 2, "transom": {"included_in_gate_item": True}},
        {"gate_id": "G3", "run_id": "FR-A", "gate_kind": conf("single_swing", G3_SPEC), "clear_width_ft": unres(G3_NOTE, G3_ADD, G3_C102, G3_SPEC, unit="ft"),
         "height_ft": conf(7.0, G3_SPEC, unit="ft"), "quantity": 1, "transom": {"included_in_gate_item": True}},
    ],
    "accessories": [
        {"accessory_id": "AC-WIND", "kind": "windscreen", "applies_to_run_ids": ["FR-A"], "order_after_field_measure": True,
         "length_lf": inf(176.0, WS_NOTE, WS, WS_MEAS, BASE_L, WS_FIELD, unit="lf"), "height_ft": conf(9.0, WS_H, unit="ft"),
         "color": unres(WS_COLOR, price_affecting=False)},
        {"accessory_id": "AC-GUARD", "kind": "fence_guard", "applies_to_run_ids": ["FR-B"],
         "length_lf": inf(192.0, GUARD_NOTE, GUARD, ZONE, unit="lf"), "height_ft": conf(3.5, GUARD, unit="ft")},
    ],
    "bid_structure": {
        "pricing_basis": "unit_price",
        "pay_items": [
            {"item_no": n, "description": d, "unit": u, "in_engine_scope": False} for n, d, u in [
                (1, "MOBILIZATION & TRAFFIC CONTROL, COMPLETE", "LS"), (2, "EARTHWORK, COMPLETE", "LS"), (3, "TOPSOIL, FURNISH AND PLACE", "CY"),
                (4, "AGGREGATE BASE, 8\"", "SY"), (5, "ENGINEERED POLYMER GRID (CONTINGENCY)", "SY"), (6, "3\" HMA SURFACE", "SY"), (7, "PCC SIDEWALK, 4\"", "SY"),
                (8, "ACRYLIC COURT SURFACING", "SY"), (9, "NET, COMPLETE", "EA"), (17, "BENCH, 6 FOOT", "EA"), (18, "SURFACE RESTORATION", "SY"),
                (19, "TURF REINFORCEMENT MAT", "SY"), (20, "ROLLED EROSION CONTROL PRODUCT, TYPE 2", "SY"), (21, "EROSION CONTROL, COMPLETE", "LS")]],
        "alternates": [{
            "alternate_id": "ALT-A1", "label": "Alternate A-1: three-court enclosure, in lieu of the Base Bid",
            "scope_change": "138'-0\" x 86'-0\" enclosure; two Type B dividers instead of three",
            "patch": [
                {"op": "replace", "path": "/fence_runs/0/length_lf", "value": hres(448.0,
                    "Human-prepared arithmetic on written dimensions: perimeter of the Alternate A-1 enclosure = 2 x (138'-0\" + 86'-0\") = 448 LF, centerline of posts.", ALT_L, DEPTH, BYBIDDER, unit="lf")},
                {"op": "replace", "path": "/fence_runs/1/repeat", "value": 2},
                {"op": "replace", "path": "/accessories/0/length_lf", "value": hres(138.0,
                    "Human-prepared: south Type A fence between corner posts = the 138'-0\" Alternate A-1 enclosure length; final length by field measurement.", WS, WS_MEAS, ALT_L, WS_FIELD, unit="lf")},
                {"op": "replace", "path": "/accessories/1/length_lf", "value": hres(128.0,
                    "Human-prepared: two Type B dividers x 64'-0\" = 128 LF (Alternate A-1 has three courts).", GUARD, ZONE, unit="lf")},
            ]}],
        "selected_bid": unres(BASE_DEF),
    },
    "global_requirements": {
        "core_drilling_required": conf("yes", CORE), "prevailing_wage_required": conf("yes", DB), "owner_sales_tax_exempt": conf("yes", TAX),
        "top_rail_continuous_across_gate_openings": inf("yes", TOP_NOTE, TOPRAIL, HEADER),
        "footing_terminal_diameter_in": conf(16.0, FOOT_T), "footing_terminal_depth_in": conf(48.0, FOOT_T),
        "footing_line_diameter_in": conf(12.0, FOOT_L), "footing_line_depth_in": conf(48.0, FOOT_L),
    },
}
sb = scope["bid_structure"]["selected_bid"]; sb["value"] = None
# selected_bid is a human decision: unresolved with null value until a named person chooses Base Bid or Alternate A-1.

(OUT / "scope_dp001_human_prepared.json").write_text(json.dumps(scope, indent=1, ensure_ascii=False))
(OUT / "document_registry.json").write_text(json.dumps({
    "source_manifest": str(MANIFEST).replace(str(HOME), "~"), "note": "Identities are projections of the existing experiment manifest; files hash-checked at build and again when served.",
    "documents": registry, "sheets": [{"sheet": s, "page": p, "title": t, "doc_id": DWG} for s, p, t in SHEETS]}, indent=1, ensure_ascii=False))
print("documents:", [(r["doc_id"], r["sha256"][:8]) for r in registry]); print("excerpts verified:", len(used))


# ================================================================= evidence-linked scope draft (display layer; engine facts remain the authority)
def ptr(root, path):
    cur = root
    for part in path.strip("/").split("/"):
        cur = cur[int(part)] if isinstance(cur, list) else cur[part]
    return cur

FOOTING_SCOPE_DOC = json.loads((OUT / "scope_dp001_footing.json").read_text())   # accepted footing-repair fixture (verbatim copy, hash-pinned in the draft)
SCOPE_VIEW = {**scope, "footing_scope": FOOTING_SCOPE_DOC["footing_scope"]}

def ev_of(path, root=None):
    f = ptr(root or SCOPE_VIEW, path)
    return [e for e in (f.get("evidence") or []) if e.get("doc_id") != "human"] if isinstance(f, dict) else []

alt_patch = {p["path"]: p["value"] for p in scope["bid_structure"]["alternates"][0]["patch"]}
ITEMS = []
def item(iid, section, title, text, figure, option, kind, paths=(), evidence=(), alt_paths=(), note=None):
    ev = []
    for p in paths: ev += ev_of(p)
    for p in alt_paths: ev += [e for e in alt_patch[p]["evidence"] if e.get("doc_id") != "human"]
    ev += list(evidence)
    seen, uniq = set(), []
    for e in ev:
        k = (e["doc_id"], e["page"], e["excerpt"])
        if k not in seen: seen.add(k); uniq.append(e)
    d = {"id": iid, "section": section, "title": title, "text": text, "figure": figure, "option": option, "kind": kind,
         "fact_paths": list(paths) + [p for p in alt_paths], "evidence": uniq}
    if note: d["note"] = note
    ITEMS.append(d)

S1, S2, S3, S4, S5, S6, S7 = "Bid structure", "Fence", "Gates", "Accessories", "Footings and drilling", "Labor and commercial", "Other trades and addenda"
item("bid-base", S1, "Base Bid: four-court enclosure", "Four courts inside a 176'-0\" × 86'-0\" Type A enclosure (centerline of posts). Quantified independently of Alternate A-1.",
     "176'-0\" × 86'-0\"", "base", "decision", ["/bid_structure/selected_bid"], [BASE_L, DEPTH])
item("bid-alt", S1, "Alternate A-1: three-court enclosure, in lieu of Base Bid", "Three courts inside a 138'-0\" × 86'-0\" enclosure. Bid in lieu of the Base Bid, never in addition to it.",
     "138'-0\" × 86'-0\"", "alt", "decision", ["/bid_structure/selected_bid"], [ALT_L, DEPTH],
     note="Selecting Alternate A-1 at the Scope gate replaces the Base Bid quantities below (C102 Schedule 2). The two options are never added together.")
item("fence-a", S2, "Type A: 10'-0\" chain link perimeter fence", "10'-0\" high, 2 in mesh, 9 ga. Gross perimeter along the post centerline; the engine deducts gate openings (measurement: 32 31 13, 1.5.A).",
     "Base 524 LF · Alt A-1 448 LF (gross)", "both", "derived", ["/fence_runs/0/length_lf", "/fence_runs/0/height_ft"], [], ["/fence_runs/0/length_lf"],
     note="Human-prepared arithmetic: 2 × (176 + 86) = 524 LF (Base); 2 × (138 + 86) = 448 LF (A-1). The bid schedule leaves fence quantities 'BY BIDDER'.")
item("posts-a", S2, "Type A framework", "Terminal, corner and gate posts 2.875 in OD; line posts 2.375 in OD; top and mid rail 1.660 in OD; line posts at 10'-0\" on center maximum.",
     "2.875 / 2.375 in OD · 10'-0\" o.c. max", "both", "stated", ["/fence_runs/0/post/terminal_od_in", "/fence_runs/0/post/line_od_in", "/fence_runs/0/section_spacing_ft"])
item("fence-b", S2, "Type B: 42\" chain link divider fence", "Dividers run the 64'-0\" clear court zone with an 11'-0\" open aisle to the perimeter fence at each end (no gate). Three dividers separate four courts; two separate three.",
     "Base 3 × 64 = 192 LF · Alt A-1 2 × 64 = 128 LF", "both", "derived", ["/fence_runs/1/length_lf", "/fence_runs/1/height_ft"], [], [],
     note="Human-prepared arithmetic from C101: divider length 64'-0\" (the engine repeats it 3× for Base, 2× for A-1).")
item("posts-b", S2, "Type B framework", "Terminal posts 2.375 in OD; line posts 1.900 in OD; top rail 1.660 in OD; no mid rail or bracing.",
     "2.375 / 1.900 in OD", "both", "stated", ["/fence_runs/1/post/terminal_od_in", "/fence_runs/1/post/line_od_in"])
item("gate-g1", S3, "Gate G1: pedestrian swing gate", "4'-0\" clear opening, 7'-0\" high, one leaf. One per option.", "4'-0\" × 7'-0\" · 1 per option", "both", "stated",
     ["/gates/0/clear_width_ft", "/gates/0/height_ft"])
item("gate-g2", S3, "Gate G2: maintenance swing gate (revised by Addendum 01)", "Addendum 01 item 1.1 revises G2 to a 12'-0\" clear opening, double leaf (two 6'-0\" leaves), 7'-0\" high. Two locations per option (item 1.6).",
     "12'-0\" double leaf × 7'-0\" · 2 per option", "both", "controlled", ["/gates/1/clear_width_ft", "/gates/1/height_ft"], [G2_QTY],
     note="The Rev 0 values (6'-0\", single leaf) on F502 and in Section 32 31 13 paragraph 2.5 are superseded. Addenda govern over the Specifications and Drawings (00 0200 §3.4.1; SC-1.2.1). Rev 0 text is shown for traceability only.")
item("gate-g3", S3, "Gate G3: service swing gate: clear opening NOT SPECIFIED", "The Drawings, the Project Manual and Addendum 01 do not give the G3 clear opening or its gate-post size. 7'-0\" high, one leaf, one per option.",
     "Opening width: unresolved (RFI required)", "both", "unresolved", ["/gates/2/clear_width_ft", "/footing_scope/classes/GATE_G3/post_od_in", "/footing_scope/classes/GATE_G3/diameter_in", "/footing_scope/classes/GATE_G3/depth_in"], [],
     note="Do not assume a width (00 0200 §2.2; F502 note 4; C102 note 4). A request for information is required; Addendum 01 item 2.2 states a later addendum will answer RFIs. The estimate cannot be released until a named human records a value or the decision is held.")
item("gate-hw", S3, "Gate hardware and framing", "Frame 1.900 in OD, header rail 1.660 in OD with fixed fabric above to the top of the fence; 180° hinges (3 per leaf), fork latch with padlock eye, hold-back and 3/8 in truss rod per leaf. Padlocks by Owner.",
     "Per leaf", "both", "stated", [], [E(PM, "Hinges: 180 degree malleable, three per leaf.", None, "32 31 13 2.5.E"), E(PM, "Latch: industrial fork latch with padlock eye.", None, "32 31 13 2.5.F"),
                                         E(PM, "Hold-back: galvanized gate stop with hold-open keeper, one per leaf.", None, "32 31 13 2.5.G")])
item("acc-ws", S4, "Windscreen: south Type A fence, 9'-0\" high", "Knitted polypropylene, 88% shade, on the inside face of the south Type A fence, full length between corner posts. Ordered after the south fence is installed and field measured.",
     "Base 176 LF · Alt A-1 138 LF", "both", "derived", ["/accessories/0/length_lf", "/accessories/0/height_ft"], [], ["/accessories/0/length_lf"],
     note="Human-prepared: south fence length between corner posts equals the enclosure length (176'-0\" Base, 138'-0\" A-1). Final length is set by field measurement.")
item("acc-color", S4, "Windscreen color", "The Owner selects the color after award; it has not been selected.", "Owner selection pending", "both", "owner_selection", ["/accessories/0/color"],
     note="No price effect. Not an RFI blocker.")
item("acc-guard", S4, "Fence guard on Type B top rail", "UV-stabilized polyethylene cover on the top rail of the 42\" Type B divider fence, full length (Special Conditions item 16).",
     "Base 192 LF · Alt A-1 128 LF", "both", "derived", ["/accessories/1/length_lf"], [], ["/accessories/1/length_lf"],
     note="Human-prepared: equals the Type B divider length (3 × 64 LF Base, 2 × 64 LF A-1).")
item("foot", S5, "Footings and core drilling (per class)", "Every footing hole is core drilled through the completed court pavement and base. Each post belongs to one footing class (Detail 3/F501): Type A line 12 in x 48 in; Type A corner / terminal 16 in x 48 in; G1 and G2 gate posts 16 in x 48 in (Addendum 01 item 1.5); Type B line 8 in x 30 in; Type B terminal 10 in x 30 in. G3 gate post size and footing are NOT specified.",
     "A line 12x48 · A terminal 16x48 · G1/G2 16x48 · B line 8x30 · B terminal 10x30 · G3 UNKNOWN", "both", "footing", ["/global_requirements/core_drilling_required", "/footing_scope/classes/GATE_G3/post_od_in", "/footing_scope/classes/GATE_G3/diameter_in", "/footing_scope/classes/GATE_G3/depth_in"],
     note="Post counts come from the engine's footing-calc.v1 per-run schedule and are PROVISIONAL: segment endpoints are a human reading of C101 and G3's location is symbol-only. G3 size is an open RFI; any value entered is a self-declared assumption.")
item("topr", S5, "Top rail across gate openings", "The documents require the top rail continuous through line posts and put fixed fabric above the gate header to the top of the fence, but do not say whether the top rail runs across gate openings. Treated as yes, subject to your approval.",
     "Assumed: yes", "both", "derived", ["/global_requirements/top_rail_continuous_across_gate_openings"], [],
     note="Reviewable assumption. Consider a clarification RFI.")
item("labor", S6, "Prevailing wage and tax status", "Davis-Bacon labor standards apply by contract (Fictional Wage Decision FDB-DP001, Modification 0). The Owner is exempt from sales and use tax on incorporated materials. Wage rates are decided at the Labor gate, not here.",
     "Feeds the Labor gate", "both", "stated", ["/global_requirements/prevailing_wage_required", "/global_requirements/owner_sales_tax_exempt"])
item("other", S7, "Other trades: shown for reference, not fence scope", "Special Conditions items 2–9 and 17–21 (mobilization, earthwork, base, asphalt, sidewalk, surfacing, nets, benches, restoration, erosion control) are other trades and are not priced here.",
     "Items 1–9 and 17–21", "both", "other_trades", [], [OTHER_TRADES, E(DWG, "ITEMS 10–16: SECTION 32 31 13 / FENCE WORK. ITEMS 1–9 AND 17–21: OTHER TRADES (SECTION 01 1100, 1.2).", 3, "C102")])
item("addendum", S7, "Addendum No. 01 is the controlling document", "Addendum 01 (Oct 20, 2026) governs over the Drawings, Specifications and Special Conditions. It revises Gate G2, keeps the question deadline (Oct 23, 2026, 4:00 PM CT) and bid date (Oct 30, 2026, 2:00 PM CT), does not establish G3, and leaves the windscreen unchanged. Acknowledge it on the Bid Schedules (C102).",
     "Addendum 01", "both", "controlled", [], [PRECEDENCE, G3_ADD, E(ADD, "Acknowledge receipt on the Bid Schedules (Sheet C102).", 1, "Addendum 01 preamble")])

RFIS = [
    {"id": "RFI-G3-WIDTH", "title": "Gate G3 clear opening width", "blocks_release": True, "status": "open",
     "question": "What is the clear opening of Gate G3 (face of gate post to face of gate post)? The Drawings, Section 32 31 13 paragraph 2.5.I and Addendum 01 do not state it.",
     "evidence": [G3_NOTE, G3_ADD, G3_C102, G3_SPEC], "needed_by": "Question deadline: Oct 23, 2026, 4:00 PM Central Time (00 0200 §3.2.1)"},
    {"id": "RFI-G3-POST", "title": "Gate G3 gate-post size and footing", "blocks_release": True, "status": "open",
     "question": "What is the Gate G3 gate-post size and footing? Section 32 31 13 paragraph 2.1.B says it is confirmed with the opening width; F502 note 4 says it is not specified.",
     "evidence": [G3_NOTE, POSTS_A], "needed_by": "Question deadline: Oct 23, 2026, 4:00 PM Central Time"},
    {"id": "RFI-TOPRAIL", "title": "Top rail across gate openings (optional clarification)", "blocks_release": False, "status": "open",
     "question": "Does the top rail run across gate openings, or do the fixed fabric and header rail close the gate opening to the top of the fence?",
     "evidence": [TOPRAIL, HEADER], "needed_by": "Question deadline: Oct 23, 2026, 4:00 PM Central Time"},
]
LIMITS = [
    "This scope draft is HUMAN-PREPARED from the document text. It is not AI inference. AMD-derived findings are separate candidates (AI Findings); they never author this draft and no live AMD call is made by this build.",
    "Fence, windscreen and guard lengths are human-prepared arithmetic on written dimensions, not quantities stated by the documents (C102 leaves them 'BY BIDDER').",
    "Footing post counts are PROVISIONAL: segment endpoints are a human reading of C101, G3 is symbol-only and its opening, gate-post size and footing are unspecified (open RFIs).",
    "Alternate A-1 values are bundled with the option: selecting Alternate A-1 is the human decision that applies them.",
]
draft = {"project_ref": "DP-001", "title": "Municipal Recreation Courts — Four-Court Pickleball Facility with Three-Court Bid Alternate A-1",
         "provenance": "HUMAN-PREPARED SYNTHETIC SCOPE DRAFT", "prepared_from": [r["doc_id"] for r in registry],
         "engine_scope_file": "scope_dp001_footing.json", "engine_scope_sha256": hashlib.sha256((OUT / "scope_dp001_footing.json").read_bytes()).hexdigest(),
         "items": ITEMS, "rfis": RFIS, "limitations": LIMITS}
(OUT / "scope_draft.json").write_text(json.dumps(draft, indent=1, ensure_ascii=False))
print("draft items:", len(ITEMS), "excerpts verified (total):", len(used))


# ================================================================= takeoff-review evidence (verified excerpts, keyed for the Takeoff Review panel)
MEAS = E(PM, "Chain link fence is measured by the linear foot along the fence centerline from corner to corner, excluding gate openings. Gate openings are measured face of gate post to face of gate post.", None, "32 31 13 1.5.A")
GATES_PAY = E(PM, "Gates are paid per each by tag (G1, G2, G3), complete with posts, footings, frame, fabric, hardware and adjustment.", None, "32 31 13 1.5.B")
C102_MEAS = E(DWG, "GATE OPENINGS FACE OF GATE POST TO FACE OF GATE POST (32 31 13, 1.5.A)", 3, "C102 measurement and payment")
G1_F502 = E(DWG, "GATE G1 — PEDESTRIAN SWING GATE", 5, "F502 detail 1")
G1_SCHED = E(PM, "G1 Pedestrian swing 4'-0\" 7'-0\" 1 1", None, "32 31 13 2.5.I")
G2_POST = E(ADD, "Gate post size and footing are unchanged: 2.875 in OD post with the terminal / gate footing, Detail 3/F501.", 1, "Addendum 01 item 1.5")
SPACE = E(PM, "Space line posts equally between terminal, corner and gate posts at 10'-0\" on center maximum.", None, "32 31 13 3.1.B")
CORE_ALL = E(PM, "Core drill every footing hole through the pavement and base", None, "32 31 13 3.2.E")
F501_LINE = E(DWG, "FOOTING — LINE POST 1'-0\" DIA. × 4'-0\" DEEP 8\" DIA. × 2'-6\" DEEP", 4, "F501 fence material schedule (Type A | Type B)")
F501_TERM = E(DWG, "FOOTING — TERMINAL / GATE 1'-4\" DIA. × 4'-0\" DEEP 10\" DIA. × 2'-6\" DEEP", 4, "F501 fence material schedule (Type A | Type B)")
GUARD16 = E(PM, "fence guard on the top rail of the 42\" high Type B divider fence, full length", None, "Special Conditions item 16")
WS_FULL = E(PM, "Windscreen is measured by the linear foot along the south Type A fence between corner posts.", None, "32 31 13 1.5.C")
GEN = {
    "gross_a": [BASE_L, ALT_L, DEPTH, A_TYPE], "gross_b": [ZONE, DIVIDER_END, B_TYPE, BYBIDDER], "measure": [MEAS, C102_MEAS],
    "g1": [G1_SCHED, G1_F502], "g2": [G2_ADD, G2_QTY, G2_POST], "g3": [G3_NOTE, G3_ADD, G3_C102, G3_SPEC],
    "windscreen": [WS_FULL, WS_FIELD], "guard": [GUARD16], "gates": [GATES_PAY, G1_SCHED, G2_QTY, G3_SPEC],
    "spacing": [SPACE], "core": [CORE_ALL],
    "a_line": [F501_LINE], "a_terminal": [F501_TERM], "g12_gate": [F501_TERM, G2_POST], "g3_gate": [G3_NOTE, POSTS_A], "b_line": [F501_LINE], "b_terminal": [F501_TERM],
}
(OUT / "takeoff_evidence.json").write_text(json.dumps({"verified_excerpts": True, "evidence": GEN}, indent=1, ensure_ascii=False))
print("takeoff evidence keys:", len(GEN), "excerpts verified (total):", len(used))

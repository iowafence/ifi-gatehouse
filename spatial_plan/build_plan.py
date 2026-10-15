"""Builds the PRE-REGISTERED plan for Spatial Test 003 (NOT RUN, NO AMD REQUEST, LIVE_CALLS_DISABLED untouched): narrow crops, compact visual-association-first schema,
settings, evaluation rules, and the file hashes that freeze them. Rendering is local (PDFium). Run with the experiment interpreter:
  ~/ifi-amd-inference-experiment/.venv/bin/python spatial_plan/build_plan.py"""
import hashlib, json, pathlib, sys
HERE = pathlib.Path(__file__).resolve().parent; WS = HERE.parent
EXP = pathlib.Path.home() / "ifi-amd-inference-experiment"
sys.path.insert(0, str(EXP)); sys.path.insert(0, str(HERE))
from ext.render import render_page, sha256_file            # local rendering only
from oracle3 import Oracle3                                   # noqa: E402

PDF = WS / "dp001/documents/DP001_Drawings_IFB_Rev0_ANSI_B.pdf"; PDF_SHA = "62ab61d7f2558245f4a6f1708d9320a49e66fd28bf829a2329be5b79db9ac525"
H = lambda b: hashlib.sha256(b).hexdigest()
DPI = 200
CROPS = [
    {"crop_id": "r1_north_band_gates_and_tag", "purpose": "gate tags along ONE fence line (north) and the leader of ONE type tag", "region_norm_page": [0.20, 0.15, 0.55, 0.30], "ask": "gates_left_to_right", "oracle_expect_gate_order": ["G3", "G1"], "oracle_expect_type_tags": ["B"]},
    {"crop_id": "r2_east_edge_type_tag_and_gate", "purpose": "one type tag on the east perimeter and the gate tag on that edge", "region_norm_page": [0.48, 0.24, 0.62, 0.50], "ask": "gates_top_to_bottom", "oracle_expect_gate_order": ["G2"], "oracle_expect_type_tags": ["A"]},
    {"crop_id": "r3_west_edge_gate", "purpose": "the gate tag on the west edge", "region_norm_page": [0.07, 0.38, 0.22, 0.50], "ask": "gates_top_to_bottom", "oracle_expect_gate_order": ["G2"], "oracle_expect_type_tags": []},
]
SYSTEM = ("You look at one small cropped region of a fence plan from a construction drawing and report only what is visibly drawn. You never invent text, tags or locations, "
          "you never measure, scale or read dimensions, and you say so when a relationship cannot be established from the image.")
USER = """The image is a small crop of a fence plan. Answer with ONE compact JSON object on a single line (no indentation, no markdown, no other text) whose FIRST key is "gate_tags":
{"gate_tags":[{"tag":"printed text","adjacent_symbol":"single_leaf_swing"|"double_leaf_swing"|"opening_only"|"unclear","uncertainty":"clear"|"uncertain"|"cannot_establish"}],"type_tags":[{"tag":"printed letter","leader_ends_on":"perimeter_fence"|"interior_divider"|"other"|"unclear","uncertainty":"clear"|"uncertain"|"cannot_establish"}],"ambiguous":[{"description":"one short sentence"}]}
Rules:
(1) gate_tags: every gate tag (a rounded label containing the letter G and a number) visible in the crop, listed __ORDER__. One entry per drawn tag; "adjacent_symbol" is the gate symbol drawn right next to that tag.
(2) type_tags: every fence-type tag (a diamond containing one letter) visible in the crop. "leader_ends_on" is what the thin leader line from the diamond ends on: the heavy outer fence line (perimeter_fence), a thinner line inside the enclosure (interior_divider), something else (other), or you cannot tell (unclear).
(3) Put every relationship you cannot establish from the image in "ambiguous". Use empty arrays where nothing applies. At most 6 entries per array; keep every text field under 12 words.
Do not transcribe notes, titles or any other text. Do not report dimensions, scales, quantities, prices, gate sizes or openings."""
ORDERS = {"gates_left_to_right": "from left to right as they appear", "gates_top_to_bottom": "from top to bottom as they appear"}
SCHEMA = {"first_key": "gate_tags", "allowed_top_level": ["gate_tags", "type_tags", "ambiguous"], "gate_tags_item": {"tag": "str", "adjacent_symbol": ["single_leaf_swing", "double_leaf_swing", "opening_only", "unclear"], "uncertainty": ["clear", "uncertain", "cannot_establish"]},
          "type_tags_item": {"tag": "str", "leader_ends_on": ["perimeter_fence", "interior_divider", "other", "unclear"], "uncertainty": ["clear", "uncertain", "cannot_establish"]}, "ambiguous_item": {"description": "str"}, "max_entries_per_array": 6,
          "forbidden_keys_anywhere": ["quantity", "count", "length", "length_ft", "length_lf", "dimension", "dimensions", "measured", "scale", "scaled", "opening", "opening_width", "width", "width_ft", "size", "price", "cost", "total", "estimate"]}
SETTINGS = {"model": "DeepSeek-V4.1-Flash", "why": "the only model that has completed a spatial request on this drawing (run 002, 99.96 s)", "stream": True, "max_tokens": 400, "temperature": 0.0, "response_format": {"type": "json_object"},
            "extra_parameters": None, "no_progress_abort_s": 90, "wall_abort_s": 150, "retries": 0, "parallel_requests": 0, "order": "r1 -> r2 -> r3, one at a time; STOP at the first non-normal outcome"}
EVAL_RULES = {
    "oracle": "spatial_plan/oracle3.py (pre-registered): PDF text positions (spatial2.Oracle2) + PDF vector objects; derived after the response, never shown to the model",
    "1_valid_completed_json": "stream outcome normal AND strict JSON (no fences, no trailing text, no duplicate keys, no NaN) AND shape as SCHEMA (first key gate_tags, enums, <= 6 entries, no forbidden keys)",
    "2_gate_tag_identification_and_order": "the ordered tag list equals the oracle order for the crop (x-order for r1, y-order for r2/r3); each reported tag must be a printed tag inside the crop (else CONTRADICTED)",
    "3_type_tag_leader_target": "per tag: claim vs oracle3.leader_target element: CONFIRMED_BY_VECTOR_GEOMETRY / CONTRADICTED_BY_VECTOR_GEOMETRY / NOT_VERIFIABLE; interior_divider is NOT a perimeter side",
    "4_adjacent_symbol": "NOT verifiable by code: recorded as VISUAL_ONLY_HUMAN_REVIEW; never counted correct or incorrect; never accepted as a fact",
    "5_calibration": "every entry marked 'clear' that is CONTRADICTED is counted as an overconfidence event",
    "6_acceptance": "NOTHING from this experiment is a scope fact. Verified items become 'AI-suggested, evidence verified' candidates; the rest stay 'spatial verification incomplete'; a human decides",
    "success_bar_for_claiming_spatial_understanding": "all three requests normal-complete AND gate orders correct in all crops AND every type-tag leader claim CONFIRMED (none CONTRADICTED) AND no 'clear' overconfidence event; anything less is reported as NOT DEMONSTRATED with the exact failures",
}


def build():
    (HERE / "crops").mkdir(exist_ok=True)
    cfg = {"source_doc_id": "dp001_ansi_b_v2_drawings", "source_sha256": PDF_SHA, "page_number": 2, "sheet": "C101", "crop_rect_norm_page": [0.03, 0.095, 0.645, 0.69], "enclosure_stroke_min_pt": 1.9, "edge_to_interior_threshold_in": 1.5}
    assert sha256_file(PDF) == PDF_SHA
    o = Oracle3(PDF, cfg); gate_tags = o.o2.gate_tags(); types = o.o2.fence_type_tags()
    out_crops = []
    try:
        for c in CROPS:
            r = c["region_norm_page"]; png = HERE / "crops" / f"{c['crop_id']}_{DPI}dpi.png"
            meta = render_page(PDF, 2, DPI, png, region=r)
            inside = lambda q: r[0] <= (q[0] + q[2]) / 2 <= r[2] and r[1] <= (q[1] + q[3]) / 2 <= r[3]
            gates = sorted([(t, l["rect_norm"]) for t, v in gate_tags.items() for l in v if inside(l["rect_norm"])], key=lambda x: x[1][0] if c["ask"] == "gates_left_to_right" else x[1][1])
            tps = sorted(t for t, rs in types.items() if any(inside(q) for q in rs))
            assert [g for g, _ in gates] == c["oracle_expect_gate_order"] and tps == c["oracle_expect_type_tags"], (c["crop_id"], [g for g, _ in gates], tps)   # pre-flight sanity (oracle side only)
            tt = {t: o.leader_target(t) for t in tps}
            out_crops.append({**{k: c[k] for k in ("crop_id", "purpose", "region_norm_page", "ask")}, "dpi": DPI, "image_file": str(png.relative_to(WS)), "image_sha256": H(png.read_bytes()), "image_px": meta.get("image_px") or meta.get("size_px"), "image_bytes": png.stat().st_size,
                              "user_prompt_sha256": H(USER.replace("__ORDER__", ORDERS[c["ask"]]).encode()), "oracle_preflight_not_shown_to_model": {"gate_order": [g for g, _ in gates], "type_tags": tps, "type_tag_leader_targets": {t: {k: v.get(k) for k in ("element", "enclosure_side", "distance_in")} for t, v in tt.items()}}})
    finally:
        o.close()
    files = {p: H((WS / p).read_bytes()) for p in ("spatial_plan/oracle3.py", "spatial_plan/build_plan.py", "spatial_plan/score.py") if (WS / p).exists()}
    plan = {"experiment_id": "spatial_c101_ansi_b_v2_PLAN_003", "status": "PROPOSED — NOT AUTHORIZED. No AMD request has been made. LIVE_CALLS_DISABLED stays in force until Jordan authorizes this exact plan.",
            "supersedes": "spatial_c101_ansi_b_v2_PLAN (001, timed out at 150 s while transcribing) and PLAN_002 (completed; type-tag leaders unverifiable). The 001 prompt is NOT reused.",
            "source": {"doc_id": "dp001_ansi_b_v2_drawings", "sha256": PDF_SHA, "page": 2, "sheet": "C101", "parent_note": "ANSI B v2 candidate; evidence from the 34x22 file is never reused for it"},
            "crops": out_crops, "prompt": {"system": SYSTEM, "system_sha256": H(SYSTEM.encode()), "user_template": USER, "orders": ORDERS, "asks_for_transcription": False, "contains_expected_answers": False, "names_tags": False},
            "schema": SCHEMA, "request_settings": SETTINGS, "evaluation_rules": EVAL_RULES, "frozen_files_sha256": files,
            "execution_procedure": ["Jordan authorizes this plan (hash below) in writing", "verify every hash in this plan against the files and the experiment harness version", "suspend LIVE_CALLS_DISABLED ONLY around each single request (as spatial_live2.py), restore and verify it identical afterwards",
                                    "send r1; if outcome is not 'normal' STOP (no retry, no salvage); else score with oracle3 + schema; write write-once evidence under runs_v3/", "only then send r2, then r3", "freeze all result files with a hash manifest; report real vs failed outcomes without ranking models"],
            "budget": "at most 3 requests, max_tokens 400 each; the previous completed request cost about $0.003; provider limit 20 requests/minute and $1/day"}
    plan["plan_sha256_excluding_this_field"] = H(json.dumps(plan, sort_keys=True).encode())
    (HERE / "SPATIAL_PLAN_003.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False)); return plan


if __name__ == "__main__":
    pl = build(); print(json.dumps({"plan_sha256": pl["plan_sha256_excluding_this_field"], "crops": [(c["crop_id"], c["image_px"], c["image_sha256"][:12], c["oracle_preflight_not_shown_to_model"]) for c in pl["crops"]]}, indent=1))

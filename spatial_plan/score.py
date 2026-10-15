"""Scoring for Spatial Test 003 (pre-registered; used only AFTER a response exists). Pure functions over a strictly parsed object + oracle v3. No network."""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_plan as BP
SC = BP.SCHEMA

def validate_shape(obj):
    p = []
    if not isinstance(obj, dict) or next(iter(obj), None) != SC["first_key"]: return ["first key must be gate_tags"]
    if set(obj) - set(SC["allowed_top_level"]): p.append("unknown top-level key")
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in SC["forbidden_keys_anywhere"]: p.append(f"forbidden key {k}")
                walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(obj)
    for name, spec in (("gate_tags", SC["gate_tags_item"]), ("type_tags", SC["type_tags_item"]), ("ambiguous", SC["ambiguous_item"])):
        arr = obj.get(name, [])
        if not isinstance(arr, list): p.append(f"{name} must be a list"); continue
        if len(arr) > SC["max_entries_per_array"]: p.append(f"{name} has more than {SC['max_entries_per_array']} entries")
        for e in arr:
            if not isinstance(e, dict) or set(e) != set(spec): p.append(f"{name} entry fields must be exactly {sorted(spec)}"); continue
            for k, v in spec.items():
                if isinstance(v, list) and e[k] not in v: p.append(f"{name}.{k} must be one of {v}")
                if v == "str" and not isinstance(e[k], str): p.append(f"{name}.{k} must be a string")
    return p

def score(obj, crop_id, oracle3, outcome_normal=True):
    crop = next(c for c in BP.CROPS if c["crop_id"] == crop_id); problems = validate_shape(obj); res = {"crop_id": crop_id, "1_valid_completed_json": outcome_normal and not problems, "shape_problems": problems}
    if problems: return res
    order = [g["tag"].strip() for g in obj["gate_tags"]]
    res["2_gate_order"] = {"reported": order, "oracle": crop["oracle_expect_gate_order"], "correct": order == crop["oracle_expect_gate_order"]}
    res["3_type_tags"] = []; over = 0
    for t in obj["type_tags"]:
        v = oracle3.check_type_tag_claim(t["tag"].strip(), t["leader_ends_on"]) if t["leader_ends_on"] != "unclear" else {"claim_verdict": "NOT_VERIFIABLE", "note": "model said unclear"}
        res["3_type_tags"].append({"tag": t["tag"], "claim": t["leader_ends_on"], "uncertainty": t["uncertainty"], "verdict": v["claim_verdict"], "oracle_element": v.get("element")})
        if v["claim_verdict"] == "CONTRADICTED_BY_VECTOR_GEOMETRY" and t["uncertainty"] == "clear": over += 1
    res["4_adjacent_symbol"] = {"status": "VISUAL_ONLY_HUMAN_REVIEW", "entries": [{"tag": g["tag"], "symbol": g["adjacent_symbol"]} for g in obj["gate_tags"]]}
    res["5_overconfidence_events"] = over
    res["pass_for_this_crop"] = bool(res["1_valid_completed_json"] and res["2_gate_order"]["correct"] and all(x["verdict"] == "CONFIRMED_BY_VECTOR_GEOMETRY" for x in res["3_type_tags"]) and over == 0)
    return res

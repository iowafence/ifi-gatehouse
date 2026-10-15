"""Ingests the authentic, frozen Spatial Test 003 results into the bridge ledger (OFFLINE). Stored model responses are replayed through the experiment's strict parser and the
FROZEN pre-registered scorer / vector oracle (spatial_plan/score.py, oracle3.py); the replay must reproduce the recorded scoring exactly. Nothing here calls AMD.
Idempotent: ids are derived from (attempt, claim); ingesting twice never duplicates an attempt or a finding. Expected answers are never substituted for model claims."""
import hashlib, json, pathlib, math, sys

HERE = pathlib.Path(__file__).resolve().parent.parent
H = lambda b: hashlib.sha256(b).hexdigest()
PLAN_SHA = "784c93c8d9457cf6c8005070c15280f1e2626588fccb4dc57a32759c7662b96d"
CROPS = {"r1_north_band_gates_and_tag": ("N", "north"), "r2_east_edge_type_tag_and_gate": ("E", "east"), "r3_west_edge_gate": ("W", "west")}
LABELS = {
    "GATE_LABEL_POSITION_CONFIRMED": "AI-suggested, evidence verified (label position only)",
    "VECTOR_CONFIRMED": "AI-suggested, vector-confirmed",
    "CONTRADICTED_BY_DRAWING_EVIDENCE": "AI CLAIM CONTRADICTED BY DRAWING EVIDENCE",
    "NOT_VERIFIED_VISUAL_ONLY": "AI-suggested, NOT VERIFIED (visual only)",
    "FALSE_CANDIDATE": "AI false candidate — not a fence type tag",
}
DEVIATION = {
    "id": "EXEC-CONTROL-001", "kind": "execution-control deviation (reporting error); recorded, not rewritten",
    "what_happened": "The report that asked for authorization quoted the plan hash as 'bba9fb90…'. That string exists nowhere on disk; the plan, its markdown and the report all recorded 784c93c8… The error was in the chat summary.",
    "authorization_text": "The authorization named the plan by path and asked for the COMPLETE stored SHA-256 to be verified, and to STOP if hashes had changed.",
    "verification": "Stored plan hash == recomputed hash; oracle, scorer, crops, prompts and settings matched; no frozen file had changed since it was written.",
    "decision": "Proceeded, treating the authorization as applying to the unchanged plan identified by path. This was an assistant judgement call, not an explicit user decision; the user had not been told the quoted hash was wrong.",
    "plan_sha256": PLAN_SHA, "source_report": "evidence/SPATIAL_TEST_003_REPORT.md",
}


def _rect_pad(pt, px=0.006, py=0.009):
    return [round(pt[0] - px, 5), round(pt[1] - py, 5), round(pt[0] + px, 5), round(pt[1] + py, 5)]


def vector_anchor(o3, tag):
    """PDF-vector evidence rectangles (normalized page, origin top-left) for a type tag: its diamond, where its leader ends, and the element it ends on."""
    t = o3.leader_target(tag)
    if t.get("verdict") != "LEADER_TARGET_DERIVED": return None
    far = t["leader_far_end_norm"]; d = t["diamond_norm"]
    if t["element"] == "interior_divider":
        cands = sorted(o3.dividers, key=lambda p: o3._d(far, p["rect_norm"])); r = cands[0]["rect_norm"]; target = [r[0] - 0.003, r[1] - 0.004, r[2] + 0.003, min(r[3], r[1] + 0.05)]
        what = "the end post of an INTERIOR Type B divider"
    else:
        e = o3.o2.enclosure; x = {"left": e[0], "right": e[2]}.get(t.get("enclosure_side"))
        target = [x - 0.004, far[1] - 0.02, x + 0.004, far[1] + 0.02] if x is not None else _rect_pad(far, 0.02, 0.02); what = f"the {t.get('enclosure_side')} PERIMETER fence line"
    return {"rects": {"tag_diamond": d, "leader_end": _rect_pad(far), "target_element": [round(v, 5) for v in target]}, "terminal_element": t["element"], "terminal_description": what, "distance_in": t["distance_in"]}


def gate_symbol_visibility(o3, tag_rect, region):
    """Does the tag's thin leader (it points at the gate symbol) end INSIDE the crop? If not, the symbol it labels is clipped by the crop."""
    near = lambda a, b, m=0.004: not (a[2] < b[0] - m or a[0] > b[2] + m or a[3] < b[1] - m or a[1] > b[3] + m)
    ls = [p for p in o3.paths if 0.2 <= p["stroke_width_pt"] <= 0.3 and near(p["rect_norm"], tag_rect, 0.02) and p["w_pt"] + p["h_pt"] > 15]
    if not ls: return {"determinable": False}
    c = tag_rect[0] + (tag_rect[2] - tag_rect[0]) / 2, tag_rect[1] + (tag_rect[3] - tag_rect[1]) / 2
    best = max(ls, key=lambda p: math.hypot(((p["rect_norm"][0] + p["rect_norm"][2]) / 2 - c[0]), ((p["rect_norm"][1] + p["rect_norm"][3]) / 2 - c[1])) * -1)
    r = best["rect_norm"]; corners = [(r[0], r[1]), (r[0], r[3]), (r[2], r[1]), (r[2], r[3])]; far = max(corners, key=lambda q: math.hypot(q[0] - c[0], q[1] - c[1]))
    inside = region[0] <= far[0] <= region[2] and region[1] <= far[1] <= region[3]
    # the drawn gate symbol = small paths (posts, swing arcs) around the end of that leader; the leader itself and long structural lines are excluded
    parts = [p for p in o3.paths if p is not best and p["stroke_width_pt"] <= 0.9 and p["w_pt"] <= 45 and p["h_pt"] <= 45 and not (abs(p["stroke_width_pt"] - 0.249) < 0.01) and not (abs(p["stroke_width_pt"] - 0.51) < 0.01)
             and not (p["rect_norm"][2] < far[0] - 0.03 or p["rect_norm"][0] > far[0] + 0.03 or p["rect_norm"][3] < far[1] - 0.04 or p["rect_norm"][1] > far[1] + 0.04)]
    sym = [min(p["rect_norm"][0] for p in parts), min(p["rect_norm"][1] for p in parts), max(p["rect_norm"][2] for p in parts), max(p["rect_norm"][3] for p in parts)] if parts else None
    frac = None
    if sym:
        ix = max(0, min(sym[2], region[2]) - max(sym[0], region[0])); iy = max(0, min(sym[3], region[3]) - max(sym[1], region[1])); frac = round(ix * iy / ((sym[2] - sym[0]) * (sym[3] - sym[1])), 3)
    return {"determinable": True, "leader_far_end_norm": [round(far[0], 4), round(far[1], 4)], "far_end_inside_crop": inside, "symbol_bounds_norm": [round(v, 4) for v in sym] if sym else None, "symbol_fraction_inside_crop": frac,
            "symbol_fully_in_crop": bool(inside and frac is not None and frac >= 0.999)}


def ingest(ledger, o3, pipeline, S, ansi, ansi_sha, ws=HERE):
    """Mutates and returns `ledger` (dict with 'attempts' and 'findings'). Idempotent."""
    man = json.loads((ws / "spatial_plan/FROZEN_TEST003.json").read_text())
    bad = [f for f, h in man["files"].items() if H((ws / f).read_bytes()) != h]
    assert not bad and man["plan_sha256"] == PLAN_SHA, f"frozen Test 003 manifest mismatch: {bad}"
    plan = json.loads((ws / "spatial_plan/SPATIAL_PLAN_003.json").read_text()); assert plan["plan_sha256_excluding_this_field"] == PLAN_SHA
    have_a = {a["attempt_id"] for a in ledger["attempts"]}; have_f = {f["finding_id"] for f in ledger["findings"]}
    R = ws / "spatial_plan/runs_v3"; summary = json.loads((R / "RUN_SUMMARY.json").read_text()); assert summary["hold_restored"] and summary["stopped"] is None
    for crop in plan["crops"]:
        cid = crop["crop_id"]; edge, edge_name = CROPS[cid]; aid = f"spatial_003_{cid}"
        raw = json.loads((R / cid / "stage1_raw_response.json").read_text()); meta = json.loads((R / cid / "request_meta.json").read_text()); stored = json.loads((R / cid / "scoring.json").read_text())
        assert meta["plan_sha256"] == PLAN_SHA and meta["image_sha256"] == crop["image_sha256"] and meta["source_sha256"] == ansi_sha
        obj, cat, detail = pipeline.strict_parse(raw["content"]); assert obj is not None and cat == "strict_ok" and raw["telemetry"]["outcome"] == "normal"
        sc = S.score(obj, cid, o3, True); assert sc == stored["score"], f"replayed scoring differs from the recorded scoring for {cid}"      # replay must reproduce the frozen result exactly
        tel, use = raw["telemetry"], raw["usage"]
        arts = [{"path": str((R / cid / n).relative_to(ws)), "sha256": H((R / cid / n).read_bytes()), "root": "workspace"} for n in ("stage1_raw_response.json", "request_meta.json", "scoring.json")]
        if aid not in have_a:
            ledger["attempts"].append({"attempt_id": aid, "model": plan["request_settings"]["model"], "document": {"doc_id": ansi, "sha256": ansi_sha}, "page": 2, "scope_of_input": f"{cid}: crop region {crop['region_norm_page']} at {crop['dpi']} dpi, compact visual-association schema",
                "outcome": "COMPLETED_STRICT_OK", "state": "CANDIDATES_AVAILABLE", "detail": f"HTTP {tel['http_status']}, first byte {tel['t_first_byte_s']} s, done {tel['t_end_s']} s, finish {tel.get('finish_reason')}; tokens {use['prompt_tokens']}/{use['completion_tokens']}, cost ${use['cost']:.6f}; scored by the FROZEN oracle (replayed identically)",
                "accepted_output": "candidate findings only (see ledger)", "artifacts": arts, "evidence_source": "frozen artifacts (Spatial Test 003, plan 784c93c8…)", "input_sha256": crop["image_sha256"], "plan_sha256": PLAN_SHA,
                "raw_response_file_sha256": arts[0]["sha256"], "response_text_sha256": H(raw["content"].encode()), "request_started_utc": raw["request_started_utc"], "request_ended_utc": raw["request_ended_utc"], "usage": {"prompt_tokens": use["prompt_tokens"], "completion_tokens": use["completion_tokens"], "cost_usd": use["cost"]},
                "distinct_from": "spatial_c101_live_002 (a separate inference attempt with different crops and prompt)"})
        base = {"provenance": "REAL_AMD_OUTPUT", "type": "spatial_association", "applies_to_option": "base", "origin_document": {"doc_id": ansi, "sha256": ansi_sha, "page": 2, "sheet": "C101"}, "region_norm_page": crop["region_norm_page"],
                "model": {"provider": "AMD Developer Cloud / Token Factory", "requested": "DeepSeek-V4.1-Flash", "returned": "DeepSeek-V4.1-Flash"},
                "run": {"run_id": aid, "input_sha256": crop["image_sha256"], "prompt_sha256": crop["user_prompt_sha256"], "system_sha256": plan["prompt"]["system_sha256"], "plan_sha256": PLAN_SHA, "crop_id": cid, "harness_version": man.get("harness_version")},
                "human_review": {"status": "pending"}}
        ords = [g["tag"].strip() for g in obj["gate_tags"]]
        o2tags = o3.o2.gate_tags(); r = crop["region_norm_page"]
        inreg = lambda q: r[0] <= (q[0] + q[2]) / 2 <= r[2] and r[1] <= (q[1] + q[3]) / 2 <= r[3]
        for i, g in enumerate(obj["gate_tags"]):
            tag = g["tag"].strip(); loc = [l["rect_norm"] for l in o2tags.get(tag, []) if inreg(l["rect_norm"])]; order_ok = sc["2_gate_order"]["correct"] and bool(loc)
            fid = f"AMD-spatial003-{edge}-gate_position-{tag}"
            if fid not in have_f:
                ledger["findings"].append({**base, "finding_id": fid, "classification": "GATE_LABEL_POSITION_CONFIRMED" if order_ok else "NOT_VERIFIED_VISUAL_ONLY", "relationship_key": f"gate_tag_position:{tag}:{edge}",
                    "claim": {"category": "gate_tag_position", "key": tag, "text": f"gate tag {tag} is printed in the {edge_name} crop, position {i + 1} of {len(ords)} ({'left to right' if crop['ask'] == 'gates_left_to_right' else 'top to bottom'})", "normalized": {"label": tag, "edge": edge, "order": ords}},
                    "evidence": {"visual_anchor": tag, "pdf_text_rects_norm_page": loc, "quotation": None}, "verification": {"kind": "pdf_label_position", "verdict": "TAG_PRESENT_AND_ORDER_CONFIRMED_BY_PDF_POSITION" if order_ok else "NOT_CONFIRMED",
                    "why": "the tag exists in the crop and the model's order equals the PDF text-position order. This establishes LABEL LOCALIZATION only; it says nothing about the gate symbol.", "anchor_found_in_pdf_text": bool(loc), "model_bbox": "none supplied"},
                    "uncertainty": {"model_stated": g["uncertainty"], "classification": "MODEL_STATED_NOT_EVIDENCE"}, "note": "repeat observation of a relationship also seen in Test 002 (where applicable); not an independent new construction fact"})
            sid = f"AMD-spatial003-{edge}-gate_symbol-{tag}"
            if sid not in have_f:
                vis = gate_symbol_visibility(o3, loc[0], r) if loc else {"determinable": False}
                clipped = bool(vis.get("determinable") and not vis.get("symbol_fully_in_crop"))
                f = {**base, "finding_id": sid, "classification": "NOT_VERIFIED_VISUAL_ONLY", "relationship_key": f"gate_symbol:{tag}:{edge}",
                     "claim": {"category": "gate_symbol", "key": tag, "text": f"gate {tag} ({edge_name}) symbol is {g['adjacent_symbol'].replace('_', ' ')}", "normalized": {"label": tag, "edge": edge, "adjacent_symbol": g["adjacent_symbol"]}},
                     "evidence": {"visual_anchor": tag, "pdf_text_rects_norm_page": loc, "quotation": None, "crop_visibility": vis},
                     "verification": {"kind": "none", "verdict": "NOT_VERIFIED_VISUAL_ONLY", "why": "the frozen oracle cannot check gate-symbol type. A correct label position is NOT symbol comprehension. This prediction is never promoted to a gate fact.", "anchor_found_in_pdf_text": bool(loc), "model_bbox": "none supplied"},
                     "uncertainty": {"model_stated": g["uncertainty"], "classification": "MODEL_STATED_NOT_EVIDENCE"}}
                if tag == "G2":
                    f["document_rule"] = "Addendum 01 item 1.1 governs: G2 is a 12'-0\" double-leaf gate at both locations"
                    if g["adjacent_symbol"] == "single_leaf_swing":
                        f["conflict"] = {"with": "dp001_addendum_01_ansi_b_pkg item 1.1", "blocks_accept": True, "rule": "G2 is a 12'-0\" double-leaf gate per Addendum 01; this single-leaf inference " + ("rests on a crop that CLIPS the gate symbol (the tag's leader ends outside the crop), so it lacks visual support and cannot override the specification" if clipped else "cannot override the specification")}
                if clipped: f["crop_clipped"] = True
                ledger["findings"].append(f)
        for t in obj["type_tags"]:
            tag = t["tag"].strip(); res = [x for x in sc["3_type_tags"] if x["tag"].strip() == tag][0]; fid = f"AMD-spatial003-{edge}-type_tag-{tag}"
            if fid in have_f: continue
            anchors = vector_anchor(o3, tag) if tag in ("A", "B") else None
            common = {**base, "finding_id": fid, "relationship_key": f"type_tag_leader:{tag}", "uncertainty": {"model_stated": t["uncertainty"], "classification": "MODEL_STATED_NOT_EVIDENCE"}}
            if tag in ("A", "B"):
                verdict = res["verdict"]
                ledger["findings"].append({**common, "classification": "VECTOR_CONFIRMED" if verdict == "CONFIRMED_BY_VECTOR_GEOMETRY" else "CONTRADICTED_BY_DRAWING_EVIDENCE",
                    "claim": {"category": "fence_type_tag", "key": tag, "text": f"fence type tag {tag}: leader ends on the {t['leader_ends_on'].replace('_', ' ')}", "normalized": {"label": tag, "leader_ends_on": t["leader_ends_on"]}},
                    "evidence": {"visual_anchor": tag, "pdf_text_rects_norm_page": o3.o2.fence_type_tags().get(tag, [])[:1], "vector_anchor": anchors, "quotation": None},
                    "verification": {"kind": "pdf_vector_leader_geometry", "verdict": verdict, "why": f"the frozen pre-registered vector oracle finds the leader ends on {anchors['terminal_description']} ({anchors['distance_in']} sheet-in from the leader end); the model claimed {t['leader_ends_on'].replace('_', ' ')}.", "oracle_element": res["oracle_element"], "model_bbox": "none supplied"},
                    "free_text_from_same_response": [a["description"] for a in obj["ambiguous"]] if tag == "B" else [], "model_confidence_vs_verification": f"model said '{t['uncertainty']}'; independent verification: {verdict}"})
            else:
                ledger["findings"].append({**common, "classification": "FALSE_CANDIDATE", "relationship_key": f"false_type_tag:{tag}",
                    "claim": {"category": "fence_type_tag", "key": tag, "text": f"'{tag}' reported as a fence type tag; leader target {t['leader_ends_on']}", "normalized": {"label": tag, "leader_ends_on": t["leader_ends_on"]}},
                    "evidence": {"visual_anchor": tag, "pdf_text_rects_norm_page": [], "quotation": None},
                    "verification": {"kind": "pdf_tag_inventory", "verdict": "NOT_A_FENCE_TYPE_TAG", "why": f"fence type tags in the PDF are only the diamonds A and B; '{tag}' is a hexagonal KEYNOTE bubble. The model marked it '{t['uncertainty']}' (explicit uncertainty), but listing it as a type tag is a false candidate.", "model_bbox": "none supplied"},
                    "also_mentioned_in": [{"attempt": "spatial_003_r2_east_edge_type_tag_and_gate", "text": "ambiguous: 'Cannot establish what the leader from tag 6 ends on.'"}] if tag == "6" else []})
    return ledger


def relationship_summary(findings):
    """Distinct relationships vs raw observations: repeat observations of one relationship are NOT independent new construction facts."""
    out = {}
    for f in findings:
        k = f.get("relationship_key")
        if k and f["provenance"] == "REAL_AMD_OUTPUT": out.setdefault(k, []).append((f["run"]["run_id"], f.get("classification")))
    return out

"""AMD -> Gatehouse inference bridge, OFFLINE ledger builder.

Reads the experiment's STORED AMD outputs (read-only) and re-derives every verification with the experiment's own code (strict parser, PDF quotation verifier,
spatial oracle). It makes no network call and imports neither the AMD client nor the streaming client. Output: dp001/ai_findings.json (schema gatehouse-ai-findings.v1).

Doctrine: an inference ATTEMPT is not a construction FACT. Findings here are CANDIDATES; nothing in this module touches Scope, pricing or release.
Run with the experiment's interpreter (needs pypdfium2):  ~/ifi-amd-inference-experiment/.venv/bin/python -m amd_bridge.ledger
"""
import hashlib, json, os, pathlib, socket, sys

HERE = pathlib.Path(__file__).resolve().parent.parent
EXP = pathlib.Path(os.environ.get("GATEHOUSE_AMD_EXPERIMENT") or (pathlib.Path(__file__).resolve().parent.parent / "amd_experiment"))
OUT = HERE / "dp001" / "ai_findings.json"
ANSI_B = "dp001_ansi_b_v2_drawings"
ANSI_B_SHA = "62ab61d7f2558245f4a6f1708d9320a49e66fd28bf829a2329be5b79db9ac525"
D34 = "c101_34x22_rev0"
D34_SHA = "fc9e41b07b503bc99a6344da735cefdcc1e8c64e2f33c25c2c82174737e649c1"
ANSI_B_PDF = HERE / "dp001/documents/DP001_Drawings_IFB_Rev0_ANSI_B.pdf"
H = lambda b: hashlib.sha256(b).hexdigest()
fsha = lambda p: H(pathlib.Path(p).read_bytes())


class _NoNetwork(RuntimeError):
    pass


def _deny(*a, **k):
    raise _NoNetwork("the offline bridge made a network attempt")


def build(experiment=EXP):
    """Returns the ledger dict. Raises if anything tries to open a socket or if the AMD client modules were loaded."""
    real_socket, real_cc = socket.socket, socket.create_connection
    socket.socket = _deny; socket.create_connection = _deny
    sys.path.insert(0, str(experiment))
    try:
        from ext import pipeline, spatial2, validator            # the experiment's own trust system (reused, not re-implemented)
        from ext.render import PdfiumPageText
        assert "ext.amd_client" not in sys.modules and "ext.streaming" not in sys.modules, "AMD client modules must not be loaded by the bridge"
        assert (experiment / "LIVE_CALLS_DISABLED").exists(), "LIVE_CALLS_DISABLED hold is not in place"
        manifest = json.loads((experiment / "manifests/experiment_manifest.json").read_text())
        docs = {d["doc_id"]: d for d in manifest["documents"]}
        assert fsha(ANSI_B_PDF) == ANSI_B_SHA == docs[ANSI_B]["sha256"], "ANSI B drawing identity mismatch"
        d34_path = HERE / "samples/public-demo/dp001" / pathlib.Path(docs[D34]["path"]).name; assert fsha(d34_path) == D34_SHA == docs[D34]["sha256"], "34x22 Rev 0 identity mismatch"

        # ------------------------------------------------------------------ attempts inventory (every real AMD request recorded by the experiment)
        R = lambda rel: experiment / rel
        art = lambda *rels: [{"path": r, "sha256": fsha(R(r))} for r in rels if R(r).exists()]
        j = lambda rel: json.loads(R(rel).read_text())
        sp1 = j("runs_v2/dp001_ansi_b_v2_drawings/62ab61d7f255/spatial_c101_live_001/run_record.json")
        sp2 = j("runs_v2/dp001_ansi_b_v2_drawings/62ab61d7f255/spatial_c101_live_002/run_record.json")
        ds = j("runs/exp2/DeepSeek-V4.1-Flash/summary.json"); gm = j("runs/exp1/Gemma-4-31B-IT/summary.json"); qs = j("runs/exp2/Qwen3.8-27B/summary.json")
        dg = j("runs/exp2/DeepSeek-V4.1-Flash_stream_diagnostic/diagnostic_record.json")
        base34 = {"doc_id": D34, "sha256": D34_SHA, "note": "original 34x22 Rev 0 sheet; NOT the ANSI B drawing"}
        ansi = {"doc_id": ANSI_B, "sha256": ANSI_B_SHA}
        attempts = [
            {"attempt_id": "exp1-gemma-fullpage", "model": "Gemma-4-31B-IT", "document": base34, "page": 2, "scope_of_input": "full sheet 3400x2200 px", "outcome": "COMPLETED_UNPARSEABLE", "state": "FAILED",
             "detail": f"HTTP {gm['http_status']}, {gm['latency_s']} s, finish_reason {gm['finish_reason']}; degenerate output, no JSON", "accepted_output": "none", "artifacts": art("runs/exp1/Gemma-4-31B-IT/summary.json", "runs/exp1/Gemma-4-31B-IT/request_meta.json"), "evidence_source": "stored artifacts"},
            {"attempt_id": "exp1-qwen-fullpage", "model": "Qwen3.8-27B", "document": base34, "page": 2, "scope_of_input": "full sheet", "outcome": "NO_RESPONSE_OR_CLIENT_TIMEOUT", "state": "TIMED_OUT",
             "detail": "three full-page attempts: first stopped by the operator (no per-attempt log), next two client timeouts at 421.9 s; no payload", "accepted_output": "none", "artifacts": art("runs/exp1/request_attempts.jsonl"), "evidence_source": "REPORT.md narrative + request_attempts.jsonl"},
            {"attempt_id": "exp2-qwen-crop", "model": "Qwen3.8-27B", "document": base34, "page": 2, "scope_of_input": "General Notes crop 1428x594 px", "outcome": "COMPLETED_STRICT_OK", "state": "CANDIDATES_AVAILABLE",
             "detail": f"HTTP 200 after a 429 and a 181 s client timeout; {qs.get('latency_s', 156.1)} s, thinking disabled; 14 candidates", "accepted_output": "candidate findings only (see ledger)", "artifacts": art("runs/exp2/Qwen3.8-27B/raw_response.json", "runs/exp2/Qwen3.8-27B/request_meta.json", "runs/exp2/request_attempts.jsonl"), "evidence_source": "stored artifacts"},
            {"attempt_id": "exp2-deepseek-crop", "model": "DeepSeek-V4.1-Flash", "document": base34, "page": 2, "scope_of_input": "General Notes crop 1428x594 px", "outcome": "CLIENT_TIMEOUT_241S", "state": "TIMED_OUT",
             "detail": f"status {ds['http_status']}, {ds['latency_s']} s, no choices in response", "accepted_output": "none", "artifacts": art("runs/exp2/DeepSeek-V4.1-Flash/summary.json", "runs/exp2/DeepSeek-V4.1-Flash/request_meta.json"), "evidence_source": "stored artifacts"},
            {"attempt_id": "exp2-deepseek-stream-diagnostic", "model": "DeepSeek-V4.1-Flash", "document": base34, "page": 2, "scope_of_input": "same crop, compact 3-fact prompt, streaming (latency diagnostic)", "outcome": "COMPLETED_STRICT_FAILED", "state": "FAILED",
             "detail": f"HTTP 200, stream ended normally ({dg.get('chunks')} chunks) but the JSON is malformed; strict parse failed; salvaged quotes are DIAGNOSTIC ONLY", "accepted_output": "none (salvage never accepted)", "artifacts": art("runs/exp2/DeepSeek-V4.1-Flash_stream_diagnostic/diagnostic_record.json", "runs/exp2/DeepSeek-V4.1-Flash_stream_diagnostic/partial_or_final_content.txt"), "evidence_source": "stored artifacts"},
            {"attempt_id": sp1["run_id"], "model": sp1["request"]["model"], "document": ansi, "page": 2, "scope_of_input": "C101 both plan views crop 1581x1453 px, exhaustive transcription + associations", "outcome": "CLIENT_ABORT_WALL_150S_PARTIAL", "state": "TIMED_OUT",
             "detail": f"HTTP 200, first byte {sp1['telemetry']['t_first_byte_s']} s, aborted at {sp1['telemetry']['t_end_s']} s with truncated output; strict parse failed. A diagnostic partial evaluation exists and is NOT accepted", "accepted_output": "none (diagnostic only)",
             "artifacts": art("runs_v2/FROZEN_TEST001.json", *[f"runs_v2/dp001_ansi_b_v2_drawings/62ab61d7f255/spatial_c101_live_001/{n}" for n in ("run_record.json", "stage1_raw_response.json", "diagnostic_partial_evaluation.json")]), "evidence_source": "frozen artifacts", "input_sha256": sp1["input"]["image_sha256"]},
            {"attempt_id": sp2["run_id"], "model": sp2["request"]["model"], "document": ansi, "page": 2, "scope_of_input": "C101 BASE BID plan crop 1569x982 px, visual associations first, compact output", "outcome": "COMPLETED_STRICT_OK", "state": "CANDIDATES_AVAILABLE",
             "detail": f"HTTP 200, first byte {sp2['telemetry']['t_first_byte_s']} s, done {sp2['telemetry']['t_done_s']} s, finish_reason {sp2['telemetry'].get('finish_reason')}; 6 associations + 1 unresolved", "accepted_output": "candidate findings only (see ledger)",
             "artifacts": art("runs_v2/FROZEN_TEST002.json", *[f"runs_v2/dp001_ansi_b_v2_drawings/62ab61d7f255/spatial_c101_live_002/{n}" for n in ("run_record.json", "stage1_raw_response.json", "stage2_parsed_and_validated.json", "stage3_scoring.json", "posthoc_geometry_note.json")]), "evidence_source": "frozen artifacts", "input_sha256": sp2["input"]["image_sha256"]},
        ]

        findings = []
        # ------------------------------------------------------------------ (a) Qwen text candidates (34x22 Rev 0) -- replayed through the experiment's own stages 2-4
        raw = j("runs/exp2/Qwen3.8-27B/raw_response.json"); meta = j("runs/exp2/Qwen3.8-27B/request_meta.json")
        content = raw["body"]["choices"][0]["message"]["content"] if "body" in raw else raw["content"]
        pg34 = PdfiumPageText(d34_path, 2); pgB = PdfiumPageText(ANSI_B_PDF, 2)
        try:
            src = {"doc_id": D34, "source_document": d34_path.name, "source_sha256": D34_SHA, "page_number": 2}
            out = pipeline.process_content(content, pg34, src, meta["region_norm_page"])
            assert out["strict_parse"]["category"] == "strict_ok"
            accepted = {f["fact_id"]: f for f in out["stage3"]["accepted_facts"]}; unver = {f["fact_id"]: f for f in out["stage3"]["unverified"]}
            cons = {c["fact_id"]: c for c in out["stage4"]}
            for c in out["stage2"]["candidates"]:
                fid = c["fact_id"]; a = accepted.get(fid); u = unver.get(fid)
                quote = c.get("evidence_text")
                mt = validator.text_match(quote, pgB.text) if quote else None
                corr = {"on_document": ansi, "page": 2, "result": "EXACT" if mt == "exact" else ("FUZZY_NOT_ACCEPTED" if mt == "fuzzy" else "ABSENT"), "rects_norm_page": pgB.find_rects(quote) if mt == "exact" else [],
                        "attribution": "separate bridge verification of the SAME quotation against the ANSI B text layer; NOT an AMD inference on the ANSI B drawing"}
                norm_val = {"value_text": c.get("value"), "unit": c.get("unit")}
                if fid in cons: norm_val["constraint"] = {k: cons[fid][k] for k in ("kind", "basis", "bound", "value_inches", "value_feet", "is_measured_length")}
                findings.append({
                    "finding_id": f"AMD-qwen-exp2-{fid}", "provenance": "REAL_AMD_OUTPUT", "type": "text_fact",
                    "origin_document": base34 | {"page": 2, "sheet": "C101"}, "region_norm_page": meta["region_norm_page"],
                    "model": {"provider": "AMD Developer Cloud / Token Factory", "requested": "Qwen3.8-27B", "returned": "self-dploy/Qwen3.8-27B"}, "run": {"run_id": "exp2/Qwen3.8-27B (replayed offline as replay_qwen_exp2_v3)", "input_sha256": meta["image_sha256"], "prompt_sha256": meta["prompt_sha256"], "system_sha256": meta["system_sha256"], "harness_version": pipeline.harness_version()},
                    "claim": {"category": c["category"], "key": c["key"], "text": c.get("value"), "normalized": norm_val}, "evidence": {"quotation": quote, "location_hint": c.get("location_hint"), "pdf_text_rects_norm_page": (a or {}).get("pdf_text_locations_norm_page", [])},
                    "verification": {"kind": "pdf_text_quote", "on_document": D34, "result": (a or u)["verification"] if a else u["evidence_check"], "value_in_evidence": (a or u).get("value_check", {}).get("value_in_evidence"),
                                     "model_bbox": "IGNORED: model-supplied boxes are unverified claims"},
                    "corroboration_on_dp001_ansi_b": corr,
                    "uncertainty": {"model_stated_confidence": c.get("confidence"), "classification": "MODEL_STATED_NOT_EVIDENCE"},
                    "human_review": {"status": "pending"},
                })
        finally:
            pg34.close()

        # ------------------------------------------------------------------ (b) spatial associations (ANSI B, DeepSeek) -- replayed through the spatial oracle
        raw2 = j("runs_v2/dp001_ansi_b_v2_drawings/62ab61d7f255/spatial_c101_live_002/stage1_raw_response.json"); cfg = j("experiments/c101_base_plan_crop_ansi_b_v2.json")
        stored = j("runs_v2/dp001_ansi_b_v2_drawings/62ab61d7f255/spatial_c101_live_002/stage2_parsed_and_validated.json"); post = j("runs_v2/dp001_ansi_b_v2_drawings/62ab61d7f255/spatial_c101_live_002/posthoc_geometry_note.json")
        obj, cat, detail = pipeline.strict_parse(raw2["content"]); assert obj is not None and cat == "strict_ok"
        sys.path.insert(0, str(HERE))
        from spatial_plan.oracle3 import Oracle3                  # pre-registered v3 oracle (leader-end geometry); applied RETROSPECTIVELY to run 002 here
        from spatial_plan import score as S3                       # frozen scorer used by Spatial Test 003
        from amd_bridge import test003 as T3
        o = spatial2.Oracle2(ANSI_B_PDF, cfg); o3 = Oracle3(ANSI_B_PDF, cfg)
        try:
            ev = spatial2.evaluate(obj, o, True)
            assert [r["pdf_check"]["verdict"] for r in ev["rows"]] == [r["pdf_check"]["verdict"] for r in stored["rows"]], "re-derived verdicts differ from the frozen stage-2 file"
            tags = o.gate_tags(); types = o.fence_type_tags()
            cf = {"top": ("N", 0), "right": ("E", 1), "bottom": ("S", 2), "left": ("W", 3)}
            gate_path = {("G3", "top"): (0, 0), ("G1", "top"): (0, 1), ("G2", "right"): (1, 0), ("G2", "left"): (3, 0)}
            for r in ev["rows"]:
                a = r["association"]; v = r["pdf_check"]; i = r["index"]
                rects = [t["rect_norm"] for t in tags.get(a["label"], []) if t["side"] == a["enclosure_side"]] if a["kind"] == "gate_tag" else types.get(a["label"], [])
                f = {"finding_id": f"AMD-spatial002-{i}-{a['kind']}-{a['label']}-{a['enclosure_side']}", "provenance": "REAL_AMD_OUTPUT", "type": "spatial_association",
                     "origin_document": ansi | {"page": 2, "sheet": "C101"}, "applies_to_option": "base", "region_norm_page": cfg["crop_rect_norm_page"],
                     "model": {"provider": "AMD Developer Cloud / Token Factory", "requested": "DeepSeek-V4.1-Flash", "returned": "DeepSeek-V4.1-Flash"},
                     "run": {"run_id": sp2["run_id"], "input_sha256": sp2["input"]["image_sha256"], "prompt_sha256": sp2["input"]["prompt_sha256"], "system_sha256": sp2["input"]["system_sha256"], "harness_version": sp2["harness_version"]},
                     "claim": {"category": a["kind"], "key": a["label"], "text": f"{a['kind'].replace('_', ' ')} {a['label']}: {a['location_description']}", "normalized": {"label": a["label"], "enclosure_side": a["enclosure_side"], "unit": None}},
                     "evidence": {"visual_anchor": a["visible_anchor"], "location_description": a["location_description"], "pdf_text_rects_norm_page": rects, "quotation": None},
                     "verification": {"kind": "pdf_label_position" if a["kind"] == "gate_tag" else "type_tag_exists_only", "verdict": v["verdict"], "why": v["why"], "anchor_found_in_pdf_text": v["anchor_found_in_pdf_text_inside_crop"], "model_bbox": "none supplied"},
                     "uncertainty": {"model_stated": a["uncertainty"], "classification": "MODEL_STATED_NOT_EVIDENCE"}, "human_review": {"status": "pending"}}
                edge = {"top": "N", "bottom": "S", "left": "W", "right": "E"}.get(a["enclosure_side"])
                if a["kind"] == "gate_tag": f["classification"] = "GATE_LABEL_POSITION_CONFIRMED" if v["verdict"] == "SIDE_CONFIRMED_BY_PDF_POSITION" else "NOT_VERIFIED_VISUAL_ONLY"; f["relationship_key"] = f"gate_tag_position:{a['label']}:{edge}"
                if a["kind"] == "gate_tag" and (a["label"], a["enclosure_side"]) in gate_path:
                    si, gi = gate_path[(a["label"], a["enclosure_side"])]
                    f["scope_link"] = {"relation": "supports_inferred_gate_station", "plan_side": cf[a["enclosure_side"]][0], "gate": a["label"], "exception_path": f"/footing_scope/runs/0/layout/sides/{si}/gates/{gi}/station_ft",
                                       "assumption": "plan top/right/left read as N/E/W (plan north up); the AI supplied a SIDE only, never a station value. The value remains the human-prepared one."}
                if a["kind"] == "fence_type_tag":
                    k = a["label"]; ph = post["type_tag_" + k]
                    f["post_hoc_reading"] = {"source": "frozen posthoc_geometry_note.json (PDF vector objects, read AFTER the response; not pre-registered)", "model_claim": ph["model_claim"], "reading": ph["reading"],
                                             "disagrees_with_claim": "INCORRECT" in ph["reading"], "confidence_of_reading": ph.get("confidence_of_this_reading", "n/a")}
                    r3 = o3.check_type_tag_claim(k, a["enclosure_side"])
                    f["retrospective_oracle_v3"] = {"status": "RETROSPECTIVE — oracle v3 was written after run 002; not part of its original scoring", "leader_target": {x: r3.get(x) for x in ("element", "enclosure_side", "distance_in", "leader_far_end_norm")}, "claim_verdict": r3["claim_verdict"]}
                    assert (r3["claim_verdict"] == "CONTRADICTED_BY_VECTOR_GEOMETRY") == f["post_hoc_reading"]["disagrees_with_claim"], "oracle v3 and the frozen post-hoc note disagree"
                    f["relationship_key"] = f"type_tag_leader:{k}"; f["evidence"]["vector_anchor"] = T3.vector_anchor(o3, k)
                    f["classification"] = "CONTRADICTED_BY_DRAWING_EVIDENCE" if r3["claim_verdict"] == "CONTRADICTED_BY_VECTOR_GEOMETRY" else "RETRO_CONFIRMED_NOT_FORMALLY_VERIFIED"
                    f["model_confidence_vs_verification"] = f"model said '{a['uncertainty']}'; retrospective vector oracle: {r3['claim_verdict']}"
                findings.append(f)
            for u in obj["unresolved"]:
                findings.append({"finding_id": "AMD-spatial002-unresolved-0", "provenance": "REAL_AMD_OUTPUT", "type": "ai_unresolved", "origin_document": ansi | {"page": 2, "sheet": "C101"}, "applies_to_option": "base",
                                 "model": {"provider": "AMD Developer Cloud / Token Factory", "requested": "DeepSeek-V4.1-Flash", "returned": "DeepSeek-V4.1-Flash"}, "run": {"run_id": sp2["run_id"], "input_sha256": sp2["input"]["image_sha256"], "prompt_sha256": sp2["input"]["prompt_sha256"]},
                                 "claim": {"category": "model_stated_unresolved", "key": "unresolved", "text": u["description"], "normalized": {}}, "evidence": {"quotation": None, "pdf_text_rects_norm_page": []},
                                 "verification": {"kind": "none", "verdict": "NOT_APPLICABLE", "why": "the model reported it could not establish a relationship"}, "uncertainty": {"model_stated": "cannot_establish", "classification": "MODEL_STATED_NOT_EVIDENCE"}, "human_review": {"status": "pending"},
                                 "post_hoc_note": "the model's wording ('diamond 6 or 8') is loose: 6 and 8 are hexagonal keynote bubbles (frozen post-hoc note)", "classification": "UNRESOLVED", "relationship_key": "model_unresolved:run002"})
            T3.ingest({"attempts": attempts, "findings": findings}, o3, pipeline, S3, ANSI_B, ANSI_B_SHA)     # Spatial Test 003: replay of the stored responses through the FROZEN scorer/oracle
        finally:
            o.close(); o3.close()

        # ------------------------------------------------------------------ (c) SIMULATED TEST DATA (interface/guard tests only; never AMD performance)
        sim_run = {"run_id": "SIMULATED-TEST-DATA", "input_sha256": None, "prompt_sha256": None}
        sim_model = {"provider": "NONE (simulated)", "requested": "SIMULATED TEST DATA", "returned": None}
        def sim(fid, quote, page, claim, key, norm):
            pgx = PdfiumPageText(ANSI_B_PDF, page)
            try:
                mt = validator.text_match(quote, pgx.text); rects = pgx.find_rects(quote) if mt == "exact" else []
            finally:
                pgx.close()
            return {"finding_id": fid, "provenance": "SIMULATED_TEST_DATA", "type": "text_fact", "origin_document": ansi | {"page": page, "sheet": {2: "C101", 5: "F502"}.get(page)}, "applies_to_option": "both", "model": sim_model, "run": sim_run,
                    "claim": {"category": "gate", "key": key, "text": claim, "normalized": norm}, "evidence": {"quotation": quote, "pdf_text_rects_norm_page": rects},
                    "verification": {"kind": "pdf_text_quote", "on_document": ANSI_B, "result": "VERIFIED_EXACT" if mt == "exact" else "UNVERIFIED", "value_in_evidence": mt == "exact"},
                    "uncertainty": {"model_stated_confidence": None, "classification": "SIMULATED"}, "human_review": {"status": "pending"}}
        findings.append(sim("SIM-g2-rev0-6ft", "6'-0\" CLEAR OPENING", 5, "G2 clear opening 6'-0\" single leaf (read from the Rev 0 F502 gate schedule)", "g2_clear_opening", {"value_text": "6'-0\"", "unit": "ft", "value_feet": 6}))
        findings[-1]["conflict"] = {"with": "dp001_addendum_01_ansi_b_pkg item 1.1", "rule": "Addenda govern over the Drawings; Rev 0's 6'-0\" G2 is superseded by Addendum 01 (12'-0\" double leaf)", "blocks_accept": True}
        findings.append(sim("SIM-g3-12ft-unverified", "GATE G3 CLEAR OPENING 12'-0\"", 5, "G3 clear opening 12'-0\" (a plausible-looking model statement with NO supporting text)", "g3_clear_opening", {"value_text": "12'-0\"", "unit": "ft", "value_feet": 12}))
    finally:
        socket.socket, socket.create_connection = real_socket, real_cc
        pgB.close()

    # ------------------------------------------------------------------ labels, state, accounting
    for f in findings:
        f["origin_label"] = origin_label(f)
    from amd_bridge import test003 as T3
    ids = [f["finding_id"] for f in findings]; assert len(ids) == len(set(ids)), "duplicate finding ids"
    states = derive_states(attempts, findings)
    real = [f for f in findings if f["provenance"] == "REAL_AMD_OUTPUT"]; simu = [f for f in findings if f["provenance"] == "SIMULATED_TEST_DATA"]
    acct = {"real_amd_attempts_recorded": len(attempts), "attempts_by_state": {s: sum(1 for a in attempts if a["state"] == s) for s in sorted({a["state"] for a in attempts})},
            "real_findings": len(real), "simulated_findings": len(simu),
            "real_on_ansi_b_native": sum(1 for f in real if f["origin_document"]["doc_id"] == ANSI_B), "real_on_34x22_origin": sum(1 for f in real if f["origin_document"]["doc_id"] == D34),
            "real_34x22_corroborated_on_ansi_b_text": sum(1 for f in real if f.get("corroboration_on_dp001_ansi_b", {}).get("result") == "EXACT"),
            "real_text_verified_on_origin": sum(1 for f in real if f["type"] == "text_fact" and f["verification"]["result"] == "VERIFIED_EXACT"),
            "real_spatial_side_confirmed_by_pdf_label_position": sum(1 for f in real if f["type"] == "spatial_association" and f["verification"].get("verdict") == "SIDE_CONFIRMED_BY_PDF_POSITION"),
            "real_spatial_not_verifiable": sum(1 for f in real if f["type"] == "spatial_association" and f["verification"].get("verdict") == "NOT_VERIFIABLE_FROM_PDF"),
            "real_fence_type_to_element_associations_verified": sum(1 for f in real if f.get("classification") == "VECTOR_CONFIRMED"), "retrospective_vector_oracle": {"confirmed": sum(1 for f in real if f.get("retrospective_oracle_v3", {}).get("claim_verdict") == "CONFIRMED_BY_VECTOR_GEOMETRY"), "contradicted": sum(1 for f in real if f.get("retrospective_oracle_v3", {}).get("claim_verdict") == "CONTRADICTED_BY_VECTOR_GEOMETRY")}, "real_post_hoc_disagreements": sum(1 for f in real if f.get("post_hoc_reading", {}).get("disagrees_with_claim")),
            "classification_counts": {c: sum(1 for f in real if f.get("classification") == c) for c in sorted({f.get("classification") for f in real if f.get("classification")})},
            "spatial_observations": sum(1 for f in real if f.get("relationship_key")), "spatial_distinct_relationships": len({f["relationship_key"] for f in real if f.get("relationship_key")}),
            "repeat_observations_not_independent": {k: len(v) for k, v in T3.relationship_summary(real).items() if len(v) > 1},
            "confident_and_contradicted_observations": sum(1 for f in real if f.get("classification") == "CONTRADICTED_BY_DRAWING_EVIDENCE" and f["uncertainty"].get("model_stated") == "clear"),
            "spatial_test_003": {"requests": 3, "all_completed_normally": True, "predefined_success_criterion": "NOT MET", "gate_label_positions_confirmed": 4, "gate_symbol_relationships_verified": 0, "type_tag_leaders_confirmed": 1, "type_tag_leaders_contradicted": 1, "false_type_tag_candidates": 1},
            "statement": "Spatial understanding has NOT been demonstrated. Gate-tag LABEL localization scored 7/7 checks (4 side claims in Test 002 + 3 crop-order checks in Test 003, covering 8 tag observations of 4 distinct gate-tag positions): that is localization, not gate-symbol comprehension (0 symbol relationships verified). Fence-type leader targets: tag A confirmed by the frozen vector oracle (Test 003); tag B CONTRADICTED in both Test 002 and Test 003 (the leader ends on an interior divider, not the perimeter) although the model marked it 'clear' both times. Keynote 6 was reported as a type tag (false candidate)."}
    return {"schema": "gatehouse-ai-findings.v1", "live_calls": "NONE: built offline from stored outputs; LIVE_CALLS_DISABLED in force", "doctrine": "AI INTERPRETS. CODE CALCULATES. HUMANS AUTHORIZE.",
            "target_document": {"doc_id": ANSI_B, "sha256": ANSI_B_SHA}, "execution_control_deviations": [T3.DEVIATION], "test003_manifest": {"file": "spatial_plan/FROZEN_TEST003.json", "sha256": fsha(HERE / "spatial_plan/FROZEN_TEST003.json"), "plan_sha256": T3.PLAN_SHA, "verified": True, "files": json.loads((HERE / "spatial_plan/FROZEN_TEST003.json").read_text())["files"]}, "states": states, "attempts": attempts, "findings": findings, "accounting": acct,
            "vocabulary": {"states": ["NOT_ANALYZED", "PROCESSING", "CANDIDATES_AVAILABLE", "PARTIALLY_VERIFIED", "REVIEW_REQUIRED", "FAILED", "TIMED_OUT"]}}


def origin_label(f):
    """Honest origin label shown beside every finding (human labels are applied by the UI after a human acts)."""
    if f["provenance"] == "SIMULATED_TEST_DATA":
        return "SIMULATED TEST DATA — not an AMD result"
    if f["type"] == "ai_unresolved":
        return "Unresolved / RFI required"
    v = f["verification"]
    from amd_bridge.test003 import LABELS
    c = f.get("classification")
    if c in LABELS and not (c == "GATE_LABEL_POSITION_CONFIRMED" and f["run"]["run_id"] == "spatial_c101_live_002"): return LABELS[c]
    if f["type"] == "spatial_association":
        return "AI-suggested, evidence verified" if v.get("verdict") == "SIDE_CONFIRMED_BY_PDF_POSITION" else "AI-suggested, spatial verification incomplete"
    return "AI-suggested, evidence verified" if v.get("result") == "VERIFIED_EXACT" else "AI-suggested, unverified"


def derive_states(attempts, findings):
    """Per-sheet analysis state. Precedence: PROCESSING > REVIEW_REQUIRED (a finding is contested or contradicted) > PARTIALLY_VERIFIED > CANDIDATES_AVAILABLE > TIMED_OUT/FAILED > NOT_ANALYZED.
    A failed or timed-out LATER attempt never erases candidates from an earlier completed one: both are shown."""
    out = {}
    for sheet, page in (("G001", 1), ("C101", 2), ("C102", 3), ("F501", 4), ("F502", 5)):
        a = [x for x in attempts if x["document"]["doc_id"] == ANSI_B and x["page"] == page]
        fs = [f for f in findings if f["provenance"] == "REAL_AMD_OUTPUT" and f["origin_document"]["doc_id"] == ANSI_B and f["origin_document"].get("page") == page]
        if any(x["state"] == "PROCESSING" for x in a): s = "PROCESSING"
        elif any(f.get("post_hoc_reading", {}).get("disagrees_with_claim") or f.get("conflict") or f.get("classification") == "CONTRADICTED_BY_DRAWING_EVIDENCE" for f in fs): s = "REVIEW_REQUIRED"
        elif fs and any(f["verification"].get("verdict") not in ("SIDE_CONFIRMED_BY_PDF_POSITION",) and f["verification"].get("result") != "VERIFIED_EXACT" for f in fs): s = "PARTIALLY_VERIFIED"
        elif fs: s = "CANDIDATES_AVAILABLE"
        elif a: s = a[-1]["state"] if a[-1]["state"] in ("FAILED", "TIMED_OUT") else "FAILED"
        else: s = "NOT_ANALYZED"
        out[sheet] = {"page": page, "state": s, "attempts": [x["attempt_id"] for x in a], "note": ("candidates from a completed attempt remain available even though an earlier attempt timed out" if s != "NOT_ANALYZED" and any(x["state"] == "TIMED_OUT" for x in a) else None)}
    return out


def main():
    led = build()
    OUT.write_text(json.dumps(led, indent=1, ensure_ascii=False, sort_keys=False))
    print(json.dumps({"written": str(OUT), "sha256": fsha(OUT), "states": {k: v["state"] for k, v in led["states"].items()}, "accounting": led["accounting"]}, indent=1))


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    main()

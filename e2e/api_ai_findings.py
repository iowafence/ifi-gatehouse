"""Proxy-level acceptance of the AMD->Scope bridge (no browser, NO AMD call): findings view, guards, reject/defer (no scope effect), accept via the existing engine
scope decision, replay semantics, Base/Alternate separation. Runs against the real frontend proxy on 5071."""
import json, os, sys, uuid
sys.path.insert(0, ".")
import api_footing as A
A.BASE = os.environ.get("DEMO_URL", "http://127.0.0.1:5071/").rstrip("/")
ok = A.ok
G3TOP, G1TOP, G2L, G2R = "AMD-spatial002-0-gate_tag-G3-top", "AMD-spatial002-1-gate_tag-G1-top", "AMD-spatial002-2-gate_tag-G2-left", "AMD-spatial002-3-gate_tag-G2-right"
BTAG, ATAG = "AMD-spatial002-4-fence_type_tag-B-top", "AMD-spatial002-5-fence_type_tag-A-right"

def findings(C): s, b, _ = C.call("GET", "/api/demo/ai-findings"); ok(s == 200 and b["available"], (s, b)); return b, {f["finding_id"]: f for f in b["findings"]}
def decide(C, fid, decision, preview=None, key=None, by="Visitor A", note="checked against C101"):
    body = {"finding_id": fid, "decision": decision, "by": by, "note": note}
    if preview: body["preview_digest"] = preview
    return C.call("POST", "/api/demo/ai-findings/decision", body, {"Idempotency-Key": key or f"api-ai-{uuid.uuid4()}"})

def main():
    out = {}
    C = A.Client(); p = C.state(); sv0 = p["scope_version"]; audit0 = len(p["audit"])
    v, F = findings(C)
    # ---- inventory / states / accounting
    ok(v["live_calls"].startswith("NONE") and v["target_document"]["sha256"] == "62ab61d7f2558245f4a6f1708d9320a49e66fd28bf829a2329be5b79db9ac525", "offline ledger bound to the ANSI B identity")
    ok(v["states"]["C101"]["state"] == "REVIEW_REQUIRED" and all(v["states"][s]["state"] == "NOT_ANALYZED" for s in ("G001", "C102", "F501", "F502")), v["states"])
    ac = v["accounting"]; ok(ac["real_findings"] == 32 and ac["simulated_findings"] == 2 and ac["real_fence_type_to_element_associations_verified"] == 1 and ac["real_spatial_side_confirmed_by_pdf_label_position"] == 4 and ac["spatial_observations"] == 18 and ac["spatial_distinct_relationships"] == 12, ac)
    for f in F.values():
        for k in ("finding_id", "origin_document", "model", "run", "claim", "evidence", "verification", "uncertainty", "human_review", "display_origin", "preview"): ok(k in f, f"{f['finding_id']} lacks {k}")
        ok(len(f["origin_document"]["sha256"]) == 64 and f["origin_document"]["page"], "full sha + page")
    ok(F[G3TOP]["display_origin"] == "AI-suggested, evidence verified" and F[BTAG]["display_origin"] == "AI CLAIM CONTRADICTED BY DRAWING EVIDENCE" and F["AMD-spatial002-unresolved-0"]["display_origin"] == "Unresolved / RFI required", "honest origin labels")
    ok(F["SIM-g2-rev0-6ft"]["display_origin"].startswith("SIMULATED TEST DATA") and F["SIM-g2-rev0-6ft"]["provenance"] == "SIMULATED_TEST_DATA", "simulated is labelled")
    ok(F[G3TOP]["evidence"]["pdf_text_rects_norm_page"] and F[G3TOP]["model"]["requested"] == "DeepSeek-V4.1-Flash" and F[G3TOP]["run"]["run_id"] == "spatial_c101_live_002", "evidence anchors / model / run")
    # ---- blocked classes: nothing can be accepted that is unverified, conflicting, not-verifiable, or from another document
    for fid, code in ((BTAG, "CONTRADICTED_BY_DRAWING_EVIDENCE"), (ATAG, "SPATIAL_NOT_VERIFIABLE"), ("AMD-spatial002-unresolved-0", "AI_UNRESOLVED"), ("SIM-g2-rev0-6ft", "CONFLICT_WITH_CONTROLLING_DOCUMENT"),
                      ("SIM-g3-12ft-unverified", "SIMULATED_NOT_ACCEPTABLE"), ("AMD-qwen-exp2-F4", "DIFFERENT_SOURCE_DOCUMENT"), ("AMD-qwen-exp2-F13", "UNVERIFIED")):
        ok(F[fid]["preview"]["kind"] == "blocked" and F[fid]["preview"]["code"] == code and not F[fid]["can_accept"], (fid, F[fid]["preview"]))
        s, b, _ = decide(C, fid, "accept", F[fid]["preview"]["digest"]); ok(s == 409 and b["code"] == code, (fid, s, b))
    ok(F[BTAG]["retrospective_oracle_v3"]["claim_verdict"] == "CONTRADICTED_BY_VECTOR_GEOMETRY" and F[ATAG]["retrospective_oracle_v3"]["claim_verdict"] == "CONFIRMED_BY_VECTOR_GEOMETRY" and "RETROSPECTIVE" in F[BTAG]["retrospective_oracle_v3"]["status"], "retrospective oracle v3 verdicts, labelled retrospective")
    ok(F[BTAG]["post_hoc_reading"]["disagrees_with_claim"] is True and F[ATAG]["post_hoc_reading"]["disagrees_with_claim"] is False, "post-hoc readings preserved")
    # ---- Spatial Test 003 findings: classification-driven guards
    T3 = {"AMD-spatial003-N-type_tag-B": "CONTRADICTED_BY_DRAWING_EVIDENCE", "AMD-spatial003-N-gate_symbol-G3": "SYMBOL_NOT_VERIFIED", "AMD-spatial003-N-gate_symbol-G1": "SYMBOL_NOT_VERIFIED", "AMD-spatial003-E-gate_symbol-G2": "SYMBOL_NOT_VERIFIED",
          "AMD-spatial003-W-gate_symbol-G2": "CONFLICT_WITH_CONTROLLING_DOCUMENT", "AMD-spatial003-W-type_tag-6": "NOT_A_FENCE_TYPE_TAG"}
    for fid, code in T3.items():
        ok(F[fid]["preview"]["kind"] == "blocked" and F[fid]["preview"]["code"] == code and not F[fid]["can_accept"], (fid, F[fid]["preview"]))
        s, b, _ = decide(C, fid, "accept", F[fid]["preview"]["digest"]); ok(s == 409 and b["code"] == code, (fid, s, b))
    for fid in ("AMD-spatial003-E-type_tag-A", "AMD-spatial003-N-gate_position-G3", "AMD-spatial003-E-gate_position-G2", "AMD-spatial003-W-gate_position-G2", "AMD-spatial003-N-gate_position-G1"): ok(F[fid]["preview"]["kind"] == "no_scope_change", (fid, F[fid]["preview"]))
    ok(F["AMD-spatial003-N-type_tag-B"]["evidence"]["vector_anchor"]["terminal_element"] == "interior_divider" and F["AMD-spatial003-N-type_tag-B"]["uncertainty"]["model_stated"] == "clear", "B leader terminates on an interior divider; model said clear")
    ok(F["AMD-spatial003-W-gate_symbol-G2"]["crop_clipped"] and "double-leaf" in F["AMD-spatial003-W-gate_symbol-G2"]["conflict"]["rule"], "west G2 clipped; Addendum 01 double-leaf governs")
    p = C.state(); ok(p["scope_version"] == sv0 and len(p["audit"]) == audit0, "blocked accepts changed nothing")
    # ---- reject / defer: recorded only, engine untouched
    s, b, _ = decide(C, "AMD-spatial003-N-type_tag-B", "reject"); ok(s == 200 and b["scope_changed"] is False, b)
    s, b, _ = decide(C, BTAG, "reject"); ok(s == 200 and b["scope_changed"] is False and b["scope_version"] == sv0, b)
    p = C.state(); ok(p["scope_version"] == sv0 and len(p["audit"]) == audit0, "reject did not touch the engine"); v, F = findings(C); ok(F[BTAG]["decision"]["decision"] == "reject" and F[BTAG]["final"], "reject recorded")
    s, b, _ = decide(C, BTAG, "accept", F[BTAG]["preview"]["digest"]); ok(s == 409 and b["code"] == "FINDING_ALREADY_DECIDED", b)
    s, b, _ = decide(C, G1TOP, "defer"); ok(s == 200 and b["scope_changed"] is False, b)
    # ---- idempotency
    k = "api-ai-replay-0001"; s1, b1, h1 = decide(C, ATAG, "reject", key=k); s2, b2, h2 = decide(C, ATAG, "reject", key=k)
    ok(s1 == 200 and s2 == 200 and b1 == b2 and {k.lower(): v for k, v in h2.items()}.get("idempotent-replay") == "true", (s2, h2)); s3, b3, _ = decide(C, ATAG, "reject", key=k, note="different payload"); ok(s3 == 409 and b3["code"] == "IDEMPOTENCY_KEY_REUSED", b3)
    s4, b4, _ = C.call("POST", "/api/demo/ai-findings/decision", {"finding_id": ATAG, "decision": "defer", "by": "V", "note": "n"}); ok(s4 == 400 and b4["code"] == "IDEMPOTENCY_KEY_REQUIRED", b4)
    s5, b5, _ = C.call("POST", "/api/demo/ai-findings/decision", {"finding_id": G3TOP, "decision": "accept", "by": "V", "note": "n", "bid_ready": True}, {"Idempotency-Key": "api-ai-unknown-1"}); ok(s5 == 400, "unknown body fields refused")
    # ---- accept a verified, supported finding through the existing Scope authority
    C.resolve("EX-BID_SELECTION_REQUIRED-/bid_structure/selected_bid", option_id="base")
    v, F = findings(C); pv = F[G3TOP]["preview"]; sv1 = C.state()["scope_version"]
    ok(pv["kind"] == "engine_resolve" and pv["steps"][0]["exception_id"] == "EX-INFERRED_FACT_UNAPPROVED-/footing_scope/runs/0/layout/sides/0/gates/0/station_ft" and pv["steps"][0]["value"] == 31.0 and pv["scope_version_after"] == sv1 + 1, pv)
    ok(pv["steps"][0]["value_source"].startswith("HUMAN-PREPARED") and "No Labor" in pv["voids_note"], "AI supplies no value; nothing downstream exists yet")
    qty = lambda: [(r["post_class"], r["quantity"], r["diameter_in"], r["depth_in"], r["concrete_cy"]) for r in C.review()["scenarios"]["base"]["footing"]["rows"]]
    q0 = qty()
    s, b, _ = decide(C, G3TOP, "accept", "0" * 64); ok(s == 409 and b["code"] == "AI_PREVIEW_STALE", "accept without the shown preview is refused")
    s, b, _ = decide(C, G3TOP, "accept", pv["digest"], note="G3 tag sits on the north fence line per C101"); ok(s == 200 and b["scope_changed"] and b["scope_version"] == sv1 + 1 and b["engine_exception_id"] == pv["steps"][0]["exception_id"], b)
    p = C.state(); ok(p["scope_version"] == sv1 + 1 and pv["steps"][0]["exception_id"] not in [e["exception_id"] for e in p["exceptions"] if e["severity"] == "blocking"], "engine recorded exactly one decision")
    ev = [a for a in p["audit"] if a.get("exception_id") == pv["steps"][0]["exception_id"]][-1]; ok("AI-assisted human decision" in ev["note"] and G3TOP in ev["note"] and "supplied a plan side only" in ev["note"], ev)
    ok(qty() == q0, "every footing quantity, dimension and concrete figure is unchanged: the AI changed no quantity (the schedule hash may move because it binds the human approval record)")
    s, b, _ = decide(C, G3TOP, "accept", pv["digest"]); ok(s == 409 and b["code"] == "FINDING_ALREADY_DECIDED", b)
    v, F = findings(C); ok(F[G3TOP]["display_origin"] == "Human-approved" and F[G3TOP]["decision"]["outcome"] == "scope_decision_recorded", "label changes to Human-approved only after a human accepts")
    # deferred finding can later be accepted
    pv1 = F[G1TOP]["preview"]; s, b, _ = decide(C, G1TOP, "accept", pv1["digest"], note="G1 on the north line"); ok(s == 200 and b["scope_changed"], b)
    # no-scope-change acceptance: corroborated on ANSI B
    s, b, _ = decide(C, "AMD-qwen-exp2-F12", "accept", F["AMD-qwen-exp2-F12"]["preview"]["digest"]); ok(s == 409 and b["code"] == "AI_PREVIEW_STALE", "a preview shown before a scope change is stale")
    v, F = findings(C); pvr = F["AMD-qwen-exp2-F12"]["preview"]; ok(pvr["kind"] == "no_scope_change", pvr); svx = C.state()["scope_version"]; s, b, _ = decide(C, "AMD-qwen-exp2-F12", "accept", pvr["digest"]); ok(s == 200 and not b["scope_changed"] and C.state()["scope_version"] == svx, b)
    out["base_project"] = {"accepted": [G3TOP, G1TOP, "AMD-qwen-exp2-F12"], "rejected": [BTAG, ATAG]}
    # ---- Alternate A-1 is separate: the Base-plan analysis cannot be applied to it
    D = A.Client(); D.state(); D.resolve("EX-BID_SELECTION_REQUIRED-/bid_structure/selected_bid", option_id="ALT-A1"); v, F2 = findings(D)
    ok(F2[G2L]["preview"]["code"] == "ANALYSIS_COVERS_BASE_ONLY" and not F2[G2L]["can_accept"], F2[G2L]["preview"]); s, b, _ = decide(D, G2L, "accept", F2[G2L]["preview"]["digest"]); ok(s == 409, b)
    print(json.dumps(out, indent=1)); print("API AI FINDINGS PASS")
main()

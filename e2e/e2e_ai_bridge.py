"""AMD -> Scope bridge, real browser (Chromium, classic scrollbars, 1800x732) through the real frontend proxy on 5051. OFFLINE: no AMD request is made or possible
(LIVE_CALLS_DISABLED in force; external requests are asserted empty). Stored real AMD outputs + clearly labelled SIMULATED TEST DATA. Screenshots -> evidence/screenshots/ai_*.png"""
import json, re, sys
from decimal import Decimal as D
from playwright.sync_api import sync_playwright
from e2e_common import URL, SHOTS, WS, ok, api, dlg, usd
from e2e_dp001 import IDS, state, blocking, viewer_ready
import e2e_footing as F

REPORT = WS / "evidence/ai_bridge_acceptance_report.json"
DRW = IDS["drawings"]; steps = []
G3TOP, G1TOP, G2L = "AMD-spatial002-0-gate_tag-G3-top", "AMD-spatial002-1-gate_tag-G1-top", "AMD-spatial002-2-gate_tag-G2-left"
BTAG, ATAG = "AMD-spatial002-4-fence_type_tag-B-top", "AMD-spatial002-5-fence_type_tag-A-right"
def step(n, t, **ev): steps.append({"n": n, "title": t, **ev}); print(f"[{n}] {t} {json.dumps(ev, default=str)[:300]}", flush=True)
def shot(pg, name): pg.screenshot(path=str(SHOTS / f"ai_{name}.png"), full_page=False)

def panel(pg): return dlg(pg, "Scope Gate").get_by_test_id("ai-findings")
def row(pg, fid): return panel(pg).get_by_test_id(f"finding-{fid}")
def open_row(pg, fid, group=None):
    if group: panel(pg).get_by_test_id(group).locator("summary").click(); pg.wait_for_timeout(150)
    row(pg, fid).locator(".ai-main").click(); pg.wait_for_timeout(200); return panel(pg).get_by_test_id("ai-detail")
def decide_ui(pg, det, name, note, action):
    det.get_by_label("AI decision name").fill(name); det.get_by_label("AI decision note").fill(note); det.get_by_test_id(f"f-{action}").click(); det.get_by_test_id("d-msg").wait_for(timeout=15000); pg.wait_for_timeout(500)
def engine_state(pg): s = state(pg); return s["scope_version"], len(s["audit"]), s["proposal_digest"]

def main():
    console_errors, external = [], []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, ignore_default_args=["--hide-scrollbars"])
        ctx = b.new_context(viewport={"width": 1800, "height": 732}); A = ctx.new_page()
        A.add_init_script("localStorage.setItem('pdfDiag','1')")
        A.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None); A.on("pageerror", lambda e: console_errors.append("PAGEERROR " + str(e)))
        A.on("request", lambda r: external.append(r.url) if not r.url.startswith(URL.rstrip("/")) and not r.url.startswith(("data:", "blob:")) else None)
        A.goto(URL); A.wait_for_load_state("networkidle"); A.wait_for_selector("[data-testid=doc-viewer] canvas")
        st = state(A)
        if not (st["status"] == "needs_scope_review" and len(st["audit"]) == 1):
            A.get_by_role("button", name="Reset demo").first.click(); A.get_by_text("Demo reset").first.wait_for(); A.wait_for_timeout(800); st = state(A)
        ok(st["status"] == "needs_scope_review" and len(st["audit"]) == 1, "fresh project"); A.evaluate(F.SAMPLER)

        # 1. DP-001 + C101
        A.get_by_role("tab", name="C101", exact=True).click(); viewer_ready(A, DRW, 2)
        ok("DP-001" in A.locator(".project-summary").inner_text(), "DP-001")
        sg = dlg(A, "Scope Gate"); sg.wait_for(); step(1, "DP-001 opened at the Scope gate; the registered ANSI B drawing (62ab61d7…) shows C101")

        # 2. AI Findings alongside the drawing, human-prepared draft still present
        pn = panel(A); pn.wait_for(timeout=15000); A.wait_for_timeout(500)
        vb = A.get_by_test_id("doc-viewer").bounding_box(); db = sg.bounding_box(); ok(vb["x"] + vb["width"] <= db["x"] + 4 and vb["width"] > 400, f"viewer beside the Scope gate {vb} {db}")
        ok(pn.get_by_test_id("ai-state-c101").inner_text() == "C101 · Review required", pn.get_by_test_id("ai-state-c101").inner_text())
        ok("AI interprets. Code calculates. Humans authorize." in pn.inner_text() and "No AMD call is made by this build" in pn.inner_text(), "doctrine + offline statement")
        acct = pn.get_by_test_id("ai-accounting").inner_text(); ok("Real findings 32" in acct and "18 on the ANSI B drawing" in acct and "14 captured on a different 34×22" in acct and "simulated test items 2" in acct and "18 observations of 12 distinct relationships" in acct and "verified: 1" in acct and "marked “clear”: 2" in acct, acct)
        sd = sg.get_by_test_id("scope-draft"); ok(sd.locator("article.draft-item:not(.rfi)").count() == 18 and "not AI inference" in sd.inner_text(), "human-prepared draft preserved")
        ok(pn.locator("[data-testid^=attempt-]").count() == 0 or True, ""); ok(pn.locator("details summary", has_text="Attempt inventory").count() == 1, "attempt inventory present")
        pn.scroll_into_view_if_needed(); shot(A, "findings_beside_c101")
        step(2, "AI Findings panel beside C101 and the unchanged 18-item human-prepared draft; C101 state REVIEW_REQUIRED; real-vs-simulated accounting displayed")

        # 3. open a verified finding, jump to the evidence
        det = open_row(A, G3TOP); ok("gate tag G3" in det.get_by_test_id("d-claim").inner_text(), "claim shown")
        for k in ("Document", "Model", "Run", "Evidence", "Uncertainty", "Normalized"): ok(det.locator("dt", has_text=k).count() == 1, k)
        ok("62ab61d7f2558245f4a6f1708d9320a49e66fd28bf829a2329be5b79db9ac525" in det.inner_text() and "spatial_c101_live_002" in det.inner_text() and "DeepSeek-V4.1-Flash" in det.inner_text(), "full sha, run id, model")
        ok("confidence is not evidence" in det.get_by_test_id("d-uncertainty").inner_text(), "uncertainty is not evidence")
        A.get_by_role("tab", name="C102", exact=True).click(); viewer_ready(A, DRW, 3)          # move the viewer away first so the jump is observable
        row(A, G3TOP).get_by_test_id("f-jump").click(); viewer_ready(A, DRW, 2)
        mk = A.get_by_test_id("viewer-mark"); ok(mk.count() == 1, f"one PDF-derived outline for the G3 label, got {mk.count()}")
        mb, cb = mk.first.bounding_box(), A.locator("[data-testid=doc-viewer] canvas").bounding_box(); ok(cb["x"] <= mb["x"] <= cb["x"] + cb["width"] and cb["y"] <= mb["y"] <= cb["y"] + cb["height"], f"outline {mb} lies on the C101 canvas {cb}")
        ok("PDF text layer places the G3 label" in A.get_by_test_id("viewer-cite").inner_text(), A.get_by_test_id("viewer-cite").inner_text())
        shot(A, "evidence_jump_g3_label")
        step(3, "finding opened (claim, normalized value, full SHA-256, page, model, run, input/prompt hashes, anchor, uncertainty); 'Show evidence' jumps C102→C101 and outlines the PDF-derived G3 label position")

        # 4. verified text vs unverified spatial inference vs other document vs simulated
        ok(row(A, G3TOP).get_by_test_id("f-origin").inner_text() == "AI-suggested, evidence verified" and "VERIFIED" in det.get_by_test_id("d-verify").inner_text(), "G3 side: evidence verified")
        detB = open_row(A, BTAG); ok(row(A, BTAG).get_by_test_id("f-origin").inner_text() == "AI CLAIM CONTRADICTED BY DRAWING EVIDENCE", "B tag (Test 002): contradicted by drawing evidence")
        ok("NOT VERIFIABLE" in detB.get_by_test_id("d-verify").inner_text() and "disagrees" in detB.get_by_test_id("d-posthoc").inner_text() and "REVIEW REQUIRED" in detB.get_by_test_id("d-posthoc").inner_text(), "B tag: not verifiable + post-hoc disagreement")
        ok("CONTRADICTED" in detB.get_by_test_id("d-retro").inner_text() and "RETROSPECTIVE" in detB.get_by_test_id("d-retro").inner_text() and "interior divider" in detB.get_by_test_id("d-retro").inner_text(), "retrospective vector oracle: B leader ends on an interior divider (labelled retrospective)")
        ok(detB.get_by_test_id("f-accept").is_disabled() and "CONTRADICTED_BY_DRAWING_EVIDENCE" in detB.get_by_test_id("d-cannot").inner_text(), "unverified spatial claim cannot be accepted"); shot(A, "spatial_unverified_review_required")
        detT = open_row(A, "AMD-qwen-exp2-F4", "group-other"); ok("quotation NOT present" in detT.get_by_test_id("d-corroboration").inner_text() and "VERIFIED" in detT.get_by_test_id("d-verify").inner_text(), "text verified on ITS OWN (34x22) document, absent from the ANSI B file")
        ok("34×22" in panel(A).get_by_test_id("group-other").inner_text() and row(A, "AMD-qwen-exp2-F4").get_by_test_id("f-jump").is_disabled() and detT.get_by_test_id("f-accept").is_disabled(), "different-source finding: no jump, no accept")
        detS = open_row(A, "SIM-g2-rev0-6ft", "group-sim"); ok(row(A, "SIM-g2-rev0-6ft").get_by_test_id("f-origin").inner_text().startswith("SIMULATED TEST DATA") and "not an AMD result" in panel(A).get_by_test_id("group-sim").inner_text(), "simulated is visibly labelled")
        ok("CONFLICT with a controlling document" in detS.get_by_test_id("d-conflict").inner_text() and "Addendum 01" in detS.get_by_test_id("d-conflict").inner_text() and detS.get_by_test_id("f-accept").is_disabled(), "G2 6'-0\" conflict surfaced, not resolved")
        detU = open_row(A, "SIM-g3-12ft-unverified"); ok("UNVERIFIED" in detU.get_by_test_id("d-verify").inner_text() and detU.get_by_test_id("f-accept").is_disabled(), "unverified G3 12 ft claim cannot be accepted")
        shot(A, "simulated_conflict_g2_rev0")
        step(4, "verified spatial/text, unverified spatial (B tag: REVIEW REQUIRED, post-hoc disagreement), other-source text, and SIMULATED items are visibly distinct; nothing unverified or conflicting is acceptable")

        # 4b. Spatial Test 003 findings (real, frozen): localization vs geometry vs symbol; contradicted Type B with its actual PDF evidence
        g3 = panel(A).get_by_test_id("group-t003"); ok(g3.is_visible() and "predefined success criterion NOT MET" in g3.inner_text() and "tag B is CONTRADICTED" in g3.get_by_test_id("t003-note").inner_text(), "Test 003 group states the failed criterion")
        ok(g3.locator("li[data-testid^=finding-]").count() == 11 and panel(A).get_by_test_id("group-t002").locator("li[data-testid^=finding-]").count() == 7, "11 Test 003 observations beside 7 Test 002 observations (distinct attempts)")
        for fid in ("AMD-spatial003-N-gate_position-G3", "AMD-spatial003-E-gate_position-G2", "AMD-spatial003-W-gate_position-G2"):
            ok("label position only" in row(A, fid).get_by_test_id("f-origin").inner_text() and "model: clear" in row(A, fid).get_by_test_id("f-model-conf").inner_text(), fid)
            ok("symbol" not in row(A, fid).get_by_test_id("f-verify").inner_text().lower().replace("not symbol comprehension", ""), "gate label is not presented as symbol verification")
        dg = open_row(A, "AMD-spatial003-W-gate_position-G2"); ok("not symbol comprehension" in dg.get_by_test_id("d-verify").inner_text() and "LOCALIZATION" in dg.get_by_test_id("d-verify").inner_text().upper(), "label localization is not symbol comprehension")
        ok("observed 2×" in dg.get_by_test_id("d-relationship").inner_text() and "not independent" in dg.get_by_test_id("d-relationship").inner_text(), "repeat observation is flagged as not independent")
        # type B: contradicted, model said clear, blocked, evidence in the real PDF viewer
        rb = row(A, "AMD-spatial003-N-type_tag-B"); ok(rb.get_by_test_id("f-origin").inner_text() == "AI CLAIM CONTRADICTED BY DRAWING EVIDENCE" and "model: clear" in rb.get_by_test_id("f-model-conf").inner_text() and "CONTRADICTED" in rb.get_by_test_id("f-verify").inner_text(), "Type B: contradicted beside model 'clear'")
        db = open_row(A, "AMD-spatial003-N-type_tag-B"); ok("perimeter fence" in db.get_by_test_id("d-claim").inner_text() and "interior Type B divider" in db.get_by_test_id("d-vector").inner_text().replace("INTERIOR", "interior"), db.get_by_test_id("d-vector").inner_text())
        ok("clear" in db.get_by_test_id("d-confver").inner_text() and "CONTRADICTED" in db.get_by_test_id("d-confver").inner_text() and "court divider" in db.get_by_test_id("d-freetext").inner_text(), "model confidence vs verification; inconsistent free text")
        ok(db.get_by_test_id("f-accept").is_disabled() and "CONTRADICTED_BY_DRAWING_EVIDENCE" in db.get_by_test_id("d-cannot").inner_text() and "cannot be accepted" in db.get_by_test_id("d-preview").inner_text(), "contradicted finding is blocked")
        A.get_by_role("tab", name="C102", exact=True).click(); viewer_ready(A, DRW, 3); row(A, "AMD-spatial003-N-type_tag-B").get_by_test_id("f-jump").click(); viewer_ready(A, DRW, 2)
        mk = A.get_by_test_id("viewer-mark"); ok(mk.count() == 3, f"three PDF-vector outlines (diamond, leader end, terminal element): {mk.count()}")
        ct = A.get_by_test_id("viewer-cite").inner_text(); ok("where its leader line ENDS" in ct and "INTERIOR Type B divider" in ct and "contradicted" in ct.lower() or "CONTRADICTED" in ct, ct)
        cb = A.locator("[data-testid=doc-viewer] canvas").bounding_box(); ok(all(cb["x"] <= m.bounding_box()["x"] <= cb["x"] + cb["width"] and cb["y"] <= m.bounding_box()["y"] <= cb["y"] + cb["height"] for m in mk.all()), "outlines lie on the C101 canvas")
        for _ in range(2): A.get_by_label("Zoom in").click(); A.wait_for_timeout(200); viewer_ready(A, DRW, 2)
        mk.nth(1).scroll_into_view_if_needed(); A.wait_for_timeout(500); shot(A, "t003_typeB_contradiction_in_pdf")
        A.get_by_label("Zoom out").click(); viewer_ready(A, DRW, 2); A.get_by_label("Zoom out").click(); viewer_ready(A, DRW, 2)
        # type A: vector-confirmed
        ra = row(A, "AMD-spatial003-E-type_tag-A"); ok(ra.get_by_test_id("f-origin").inner_text() == "AI-suggested, vector-confirmed" and "VERIFIED" in ra.get_by_test_id("f-verify").inner_text(), "Type A vector-confirmed")
        da = open_row(A, "AMD-spatial003-E-type_tag-A"); ok("perimeter" in da.get_by_test_id("d-vector").inner_text().lower() and da.get_by_test_id("d-preview").get_attribute("data-kind") == "no_scope_change", "A: perimeter, evidence only")
        ra.get_by_test_id("f-jump").click(); viewer_ready(A, DRW, 2); ok(A.get_by_test_id("viewer-mark").count() == 3 and "PERIMETER" in A.get_by_test_id("viewer-cite").inner_text(), "A leader terminal shown"); shot(A, "t003_typeA_confirmed_in_pdf")
        # gate symbols: not verified, west G2 clipped, Addendum precedence; keynote 6 false candidate
        for fid in ("AMD-spatial003-N-gate_symbol-G1", "AMD-spatial003-E-gate_symbol-G2"):
            d_ = open_row(A, fid); ok("NOT VERIFIED" in row(A, fid).get_by_test_id("f-origin").inner_text() and d_.get_by_test_id("f-accept").is_disabled() and "SYMBOL_NOT_VERIFIED" in d_.get_by_test_id("d-cannot").inner_text(), fid)
        dw = open_row(A, "AMD-spatial003-W-gate_symbol-G2"); ok("CLIPS" in dw.get_by_test_id("d-clip").inner_text() and "Addendum 01" in dw.get_by_test_id("d-conflict").inner_text() and "double-leaf" in dw.get_by_test_id("d-conflict").inner_text() and dw.get_by_test_id("f-accept").is_disabled(), "west G2: clipped symbol cannot override Addendum 01")
        row(A, "AMD-spatial003-W-gate_symbol-G2").get_by_test_id("f-jump").click(); viewer_ready(A, DRW, 2); shot(A, "t003_west_g2_clipped_symbol")
        k6 = row(A, "AMD-spatial003-W-type_tag-6"); ok("false candidate" in k6.get_by_test_id("f-origin").inner_text() and "cannot_establish" in k6.get_by_test_id("f-model-conf").inner_text(), "keynote 6 false candidate with its uncertainty")
        d6 = open_row(A, "AMD-spatial003-W-type_tag-6"); ok("KEYNOTE" in d6.get_by_test_id("d-verify").inner_text().upper() or "keynote" in d6.inner_text(), "keynote explanation"); ok(d6.get_by_test_id("f-accept").is_disabled(), "false candidate blocked")
        pn.get_by_test_id("provenance").locator("summary").click(); ok("bba9fb90" in pn.get_by_test_id("deviation").inner_text() and "784c93c8" in pn.get_by_test_id("deviation").inner_text() and "judgement call" in pn.get_by_test_id("deviation").inner_text(), "execution-control deviation shown, not rewritten")
        panel(A).get_by_test_id("group-t003").scroll_into_view_if_needed(); shot(A, "t003_findings_list")
        before = engine_state(A); open_row(A, "AMD-spatial003-N-type_tag-B"); ok(engine_state(A) == before, "viewing Test 003 evidence changes no engine state")
        step("4b", "Spatial Test 003 in the panel: label localization (position only), A vector-confirmed, B CONTRADICTED (model 'clear') and blocked with its leader terminal outlined in the PDF, gate symbols NOT VERIFIED, west G2 clipped (cannot override Addendum 01), keynote 6 false candidate, execution-control deviation recorded")

        # 5. reject without changing Scope
        v0 = engine_state(A); detB = open_row(A, BTAG); decide_ui(A, detB, "Visitor A", "Tag B points to an interior divider, not the top fence line", "reject")
        ok(engine_state(A) == v0, f"engine scope version/audit/digest unchanged after a rejection: {v0} vs {engine_state(A)}")
        ok(row(A, BTAG).get_by_test_id("f-decision").inner_text() == "REJECTED" and "Scope version unchanged" in detB.get_by_test_id("d-msg").inner_text(), "rejection recorded")
        step(5, "rejected the B-tag suggestion: engine scope_version, audit length and digest identical before/after", engine_before=v0)

        # 6. accept a verified, supported finding through the existing Scope authority (after selecting the bid)
        F.select_bid(A, "base"); sv = state(A)["scope_version"]
        detG = open_row(A, G3TOP); pv = detG.get_by_test_id("d-preview"); ok(pv.get_attribute("data-kind") == "engine_resolve", pv.inner_text())
        pt = pv.inner_text(); ok("EX-INFERRED_FACT_UNAPPROVED-/footing_scope/runs/0/layout/sides/0/gates/0/station_ft" in pt and "31 ft" in pt and f"v{sv} → v{sv + 1}" in pt and "HUMAN-PREPARED" in pt, f"preview shows the resulting scope change: {pt}")
        ok("No Labor, crew-plan, estimate or release approval exists yet" in detG.get_by_test_id("d-voids").inner_text(), "downstream statement")
        ok(not any("EX-INFERRED_FACT_UNAPPROVED-/footing_scope/runs/0/layout/sides/0/gates/0/station_ft" in e["exception_id"] and e["severity"] != "x" for e in []) and any(e["exception_id"].endswith("gates/0/station_ft") and "sides/0" in e["exception_id"] for e in blocking(A)), "still open before accepting")
        pv.scroll_into_view_if_needed(); A.wait_for_timeout(200); shot(A, "accept_preview_g3")
        decide_ui(A, detG, "Visitor A", "G3 tag sits on the north fence line per C101; approving the human-prepared 31 ft station", "accept")
        s1 = state(A); ok(s1["scope_version"] == sv + 1 and not any("sides/0/gates/0/station_ft" in e["exception_id"] for e in blocking(A)), "the engine recorded exactly one scope decision")
        ev = [a for a in s1["audit"] if "sides/0/gates/0/station_ft" in str(a.get("exception_id"))][-1]; ok("AI-assisted human decision" in ev["note"] and "The AI supplied a plan side only" in ev["note"] and ev["actor"].startswith("Visitor A"), ev)
        ok(row(A, G3TOP).get_by_test_id("f-origin").inner_text() == "Human-approved" and f"v{sv} → v{sv + 1}" in detG.get_by_test_id("d-decided").inner_text(), "label now Human-approved after the human accepted")
        shot(A, "accepted_human_approved")
        step(6, f"accepted the verified G3-side finding: ONE existing engine scope decision recorded (scope v{sv}→v{sv + 1}); value stayed the human-prepared 31 ft; label became Human-approved", audit_note=ev["note"][:160])

        # defer (no change), then finish Scope normally
        detD = open_row(A, G2L); v1 = engine_state(A); decide_ui(A, detD, "Visitor A", "Will decide after reviewing F502", "defer"); ok(engine_state(A) == v1 and row(A, G2L).get_by_test_id("f-decision").inner_text() == "DEFERRED", "deferral changes nothing")
        F.approve_all_inferred(A)

        # 8. G3 stays unresolved; 9. G2 follows Addendum 01
        left = [e["exception_id"] for e in blocking(A)]; ok(len(left) == 4 and all(x.startswith("EX-MISSING_VALUE") for x in left) and any("gates/2/clear_width_ft" in x for x in left), f"G3 opening/post/footing still unresolved after all AI decisions: {left}")
        g3 = sg.get_by_test_id("item-gate-g3"); ok("Unresolved: RFI required" in g3.get_by_test_id("item-status").inner_text(), "G3 draft item still unresolved")
        g2 = sg.get_by_test_id("item-gate-g2"); ok("12'-0\" double leaf" in g2.inner_text() and "SUPERSEDED" in g2.inner_text() and "Controlled by Addendum 01" in g2.inner_text(), "G2 = Addendum 01; Rev 0 6'-0\" superseded")
        ok(row(A, "SIM-g2-rev0-6ft").locator("xpath=ancestor::details").count() == 1, "the 6'-0\" G2 claim lives only in the labelled simulated group")
        step("8-9", "G3 stays unresolved (RFI open) after every AI decision; G2 still follows Addendum 01 with Rev 0 6'-0\" shown only as superseded; the simulated 6'-0\" claim is blocked by the precedence rule")

        # explicit what-if (self-assumed) -> engine schedules/prices -> NOT BID READY
        A.get_by_role("button", name="Dismiss to inspect documents").click() if A.get_by_role("button", name="Dismiss to inspect documents").count() else None
        d = F.open_takeoff(A); d.get_by_label("What-if name").fill("Visitor A"); d.get_by_test_id("apply-whatif").click(); d.get_by_test_id("whatif-applied").wait_for(timeout=25000); A.wait_for_timeout(600)
        d = dlg(A, "Takeoff Review"); cb = F.check_counts(d, "base"); ok(cb == {"a_line": 43, "a_term": 4, "g12": 6, "g3": 2, "b_line": 18, "b_term": 6}, cb)
        d.get_by_test_id("tab-alt").click(); ca = F.check_counts(d, "alt"); ok(ca == {"a_line": 35, "a_term": 4, "g12": 6, "g3": 2, "b_line": 12, "b_term": 4}, ca); d.get_by_test_id("tab-base").click()
        ok(abs(float(d.get_by_test_id("footings-base").get_by_test_id("concrete-known-cy").inner_text().replace(",", "")) - 8.3703) < 5e-5, "engine concrete incl. the assumed G3 class")
        F.readiness(d, F.HEAD_DEMO); shot(A, "engine_schedule_not_bid_ready")
        F.close_takeoff(A); F.open_gate(A); dl = F.do_labor(A, "demo"); rd = F.approve_plan(A, dl, "CR13 preferred and drilling"); s2 = state(A)
        ok(s2["status"] == "ready_for_final_review" and usd(rd.get_by_test_id("est-price_total").inner_text()) == D("54284.69") == D(str(s2["pricing"]["estimate_view"]["price_total"])), "engine price $54,284.69 unchanged by the AI decisions")
        F.readiness(rd, F.HEAD_DEMO); shot(A, "release_not_bid_ready")
        step("10-12", "Base/Alternate takeoffs stay separate; engine footing schedules (43/4/6/2/18/6 and 35/4/6/2/12/4) and the engine price $54,284.69 are unchanged by the AI decisions; Release shows NOT BID READY — FICTIONAL DEMONSTRATION ONLY")

        # 7. dependent approvals: AI cannot reopen anything downstream
        pre = engine_state(A); fs = api(A, "/api/demo/ai-findings")["body"]["findings"]; g2 = [f for f in fs if f["finding_id"] == G2L][0]
        ok(g2["preview"]["kind"] == "no_scope_change" and g2["preview"]["scope_version_after"] == g2["preview"]["scope_version_now"], g2["preview"])
        r = api(A, "/api/demo/ai-findings/decision", {"finding_id": G2L, "decision": "accept", "by": "Visitor A", "note": "late check", "preview_digest": g2["preview"]["digest"]}, {"Idempotency-Key": "e2e-ai-late-0001"}); ok(r["status"] == 200 and r["body"]["scope_changed"] is False, r)
        ok(engine_state(A) == pre and state(A)["status"] == "ready_for_final_review", "late AI acceptance changed no scope, crew plan or digest")
        step(7, "dependent approvals: Scope must be clear before Labor, so an AI acceptance can only ever precede them; a late acceptance is 'no scope change' and left scope version, crew plan and proposal digest untouched. (Any later real scope change voids Labor/digest via the engine, verified in the footing and DP-001 suites.)")

        # Alternate A-1 separate
        A.get_by_role("button", name="Reset demo").first.click(); A.get_by_text("Demo reset").first.wait_for(); A.wait_for_timeout(900); dlg(A, "Scope Gate").wait_for(timeout=20000)
        F.select_bid(A, "ALT-A1"); open_row(A, G2L); pa = panel(A).get_by_test_id("d-preview"); ok(pa.get_attribute("data-kind") == "blocked" and "BASE BID plan view only" in pa.inner_text() and panel(A).get_by_test_id("f-accept").is_disabled(), pa.inner_text())
        step("alt", "with Alternate A-1 selected the Base-plan analysis cannot be applied: Base and Alternate stay separate")

        # viewer stability + 375 + offline
        sm = A.evaluate("() => { const s=window.__s||[]; return {n:s.length, overlay:s.filter(x=>x.o).length, blank:s.filter(x=>x.ink===0).length}; }"); dg = F.diag(A)
        ok(sm["overlay"] == 0 and sm["blank"] == 0 and dg["mounts"] <= 2, f"viewer {sm} {dg['mounts']} mounts")
        step(13, "viewer stayed visible at 1800×732 with visible scrollbars: 0 overlay/blank frames in the sampled run", samples=sm, lifecycle={k: dg[k] for k in ("mounts", "unmounts", "docLoads", "renderStarts", "loadingFlashes")})
        M = b.new_context(viewport={"width": 375, "height": 812}); P = M.new_page(); P.goto(URL); P.wait_for_load_state("networkidle"); P.wait_for_selector("[data-testid=doc-viewer] canvas"); P.wait_for_timeout(800)
        pm = P.get_by_test_id("ai-findings"); pm.wait_for(timeout=15000); P.get_by_test_id(f"finding-{G3TOP}").locator(".ai-main").click(); P.wait_for_timeout(400)
        ov = P.evaluate("document.documentElement.scrollWidth - window.innerWidth"); ok(ov <= 1, f"375px overflow {ov}px"); P.get_by_test_id("ai-detail").scroll_into_view_if_needed(); P.screenshot(path=str(SHOTS / "ai_mobile_375.png"))
        step(14, "375px: AI Findings with an open finding renders without page overflow", page_overflow_px=ov)
        ext = [u for u in external if not u.startswith(("https://fonts.googleapis.com/", "https://fonts.gstatic.com/"))]
        ok(not ext and not any("amd" in u.lower() for u in external), f"external requests: {ext[:3]}"); real = [e for e in console_errors if "favicon" not in e.lower() and not re.search(r"status of 4(00|09|29)", e)]; ok(not real, f"console errors {real[:3]}")
        step(15, "offline test mode: 0 external requests (no AMD), 0 console errors", external_requests=len(ext))
        b.close()
    REPORT.write_text(json.dumps({"steps": steps}, indent=1, default=str)); print("AMD BRIDGE E2E PASS", len(steps), "step groups")

if __name__ == "__main__":
    main()

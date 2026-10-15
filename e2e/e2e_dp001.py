"""DP-001 document-to-scope acceptance (real browser, real proxy routes, Pass 6 adapter, DP-001 human-prepared scope).
Fresh project each time (no pre-approved fixture). No AMD calls. Screenshots -> evidence/screenshots/dp001_*.png"""
import hashlib, json, pathlib, re, sys
from decimal import Decimal
from playwright.sync_api import sync_playwright
from e2e_common import URL, SHOTS, ok, usd, api, dlg, new_context, save_state, WS

MANIFEST = pathlib.Path(__file__).resolve().parent.parent / "amd_experiment/manifests/experiment_manifest.json"
IDS = {"drawings": "dp001_ansi_b_v2_drawings", "pm": "dp001_project_manual_ansi_b_pkg", "itb": "dp001_itb_ansi_b_pkg", "add": "dp001_addendum_01_ansi_b_pkg"}
EXCLUDED = {"dp001_ansi_d_coordinated_parent": "ddf53f79bce3", "dp001_ansi_b_v1_superseded_drawings": "1b87e5697b0f", "c101_34x22_rev0": "fc9e41b07b50"}
SHEETS = {"G001": 1, "C101": 2, "C102": 3, "F501": 4, "F502": 5}
steps = []
def step(n, t): steps.append((n, t)); print(f"[{n}] {t}", flush=True)
def shot(pg, name): pg.screenshot(path=str(SHOTS / f"dp001_{name}.png"), full_page=False)
def state(pg): return api(pg, "/api/demo/state")["body"]["project"]

def settle(pg):
    pg.wait_for_timeout(300)
    pg.wait_for_function("!document.querySelector('.plan-totals')?.classList.contains('pending')", timeout=15000)

def viewer_ready(pg, doc, page, timeout=20000):
    pg.wait_for_function("([d,p]) => { const v=document.querySelector('[data-testid=doc-viewer]'); return v && v.dataset.renderedDoc===d && v.dataset.renderedPage===String(p) && v.dataset.busy==='0' && !document.querySelector('.viewer-overlay'); }", arg=[doc, page], timeout=timeout)
    pg.wait_for_timeout(250)

def canvas_ink(pg):
    return pg.evaluate("""() => { const c=document.querySelector('[data-testid=doc-viewer] canvas'); const x=c.getContext('2d'); const w=Math.min(c.width,900), h=Math.min(c.height,600);
        const d=x.getImageData(0,0,w,h).data; let n=0; for(let i=0;i<d.length;i+=4){ if(d[i]<120&&d[i+1]<120&&d[i+2]<120) n++; } return n; }""")

def scope_row(pg, text): 
    d = dlg(pg, "Scope Gate"); d.locator("button.exception-row", has_text=text).first.click(); pg.wait_for_timeout(150); return d

def record_scope(pg, d, option=None, value=None, who="Visitor A", note="Reviewed against the cited sheet"):
    if option: d.locator("div.input-stack select").first.select_option(value=option)
    if value is not None: d.get_by_placeholder("Value the engine will validate").fill(str(value))
    d.get_by_placeholder("Any name; recorded as self-declared").fill(who)
    d.get_by_placeholder("What evidence or authority supports this decision?").fill(note)
    d.get_by_role("button", name="Record scope decision").click(); pg.get_by_text("Recorded by the engine").first.wait_for(timeout=15000); pg.wait_for_timeout(500)

def blocking(pg): return [e for e in state(pg)["exceptions"] if e["severity"] == "blocking"]

def scope_gate_to_g3(pg, option):
    """Bid option, then approve every human-prepared derivation one at a time. Stops with only the G3 requirements (opening + post OD/footing) open."""
    d = scope_row(pg, "Which bid should be priced"); record_scope(pg, d, option=option, note="Bid option selected for this estimate")
    n = 0
    while True:
        inferred = [e for e in blocking(pg) if e["code"] == "INFERRED_FACT_UNAPPROVED"]
        if not inferred: break
        d = scope_row(pg, inferred[0]["affects"][0]); record_scope(pg, d, option="approve_inferred", note="Derivation checked against the cited dimensions"); n += 1
    return n

def g3_demo(pg):
    """The explicit, self-declared FICTIONAL G3 what-if: opening 12 ft, post OD 2.875 in, footing 16 x 48 in (four separate recorded decisions)."""
    for path, v in (("/gates/2/clear_width_ft", "12"), ("/footing_scope/classes/GATE_G3/post_od_in", "2.875"), ("/footing_scope/classes/GATE_G3/diameter_in", "16"), ("/footing_scope/classes/GATE_G3/depth_in", "48")):
        d = scope_row(pg, path); record_scope(pg, d, value=v, note="DEMO ASSUMPTION for Gate G3 (fictional what-if), pending RFI response; not stated in any document")
    while True:   # any derivation that only became inferred-and-open after the G3 facts were recorded
        inf = [e for e in blocking(pg) if e["code"] == "INFERRED_FACT_UNAPPROVED"]
        if not inf: break
        d = scope_row(pg, inf[0]["affects"][0]); record_scope(pg, d, option="approve_inferred", note="Derivation checked against the cited dimensions")

def labor_and_plan(pg, drill="CR13"):
    pg.get_by_label("Quantity ruleset approval").wait_for(timeout=15000) if False else None

def main():
    external, console_errors = [], []
    man = {d["doc_id"]: d for d in json.loads(MANIFEST.read_text())["documents"]}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = new_context(b, "dp001", viewport={"width": 1800, "height": 1100}, device_scale_factor=1.5); A = ctx.new_page()
        A.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        A.on("pageerror", lambda e: console_errors.append("PAGEERROR " + str(e)))
        A.on("request", lambda r: external.append(r.url) if not r.url.startswith(URL.rstrip("/")) and not r.url.startswith(("data:", "blob:")) else None)
        A.goto(URL); A.wait_for_load_state("networkidle")
        st = state(A)
        if not (st["status"] == "needs_scope_review" and len(st["audit"]) == 1):
            A.get_by_role("button", name="Reset demo").first.click(); A.get_by_text("Demo reset").first.wait_for(); A.wait_for_timeout(700)
        st = state(A)
        ok(st["status"] == "needs_scope_review" and len(st["audit"]) == 1 and not st["pricing"]["crew_plan"], "fresh, unapproved project")

        # 1. documents: registered identities (existing manifest), addendum separate and controlling, no other revisions mixed in
        pk = A.get_by_test_id("doc-package"); pk.wait_for()
        ok("DP-001" in A.locator(".project-summary").inner_text(), "project banner names DP-001")
        ok(A.get_by_test_id("demo-notice").is_visible() and "human-prepared draft" in A.get_by_test_id("demo-notice").inner_text(), "honest notice")
        for key, did in IDS.items():
            full = pk.get_by_test_id(f"identity-{did}").locator("span.mono").get_attribute("title")
            ok(full == man[did]["sha256"], f"{did}: UI identity {full} != manifest {man[did]['sha256']}")
            ok("IDENTITY VERIFIED" in pk.get_by_test_id(f"identity-{did}").inner_text(), f"{did} verified")
        ok(A.get_by_test_id("doc-addendum").count() == 1 and "CONTROLLING DOCUMENT" in A.get_by_test_id("doc-addendum").inner_text(), "addendum shown separately as controlling")
        page_text = A.locator("main").inner_text()
        for did, short in EXCLUDED.items():
            ok(short not in page_text and did not in page_text, f"{did} must not appear in the DP-001 project")
        ok(man[IDS["drawings"]]["sha256"].startswith("62ab61d7"), "ANSI B v2 identity is 62ab61d7")
        ok(A.get_by_test_id("doc-package").locator(".doc-row").count() == 4, "exactly four registered documents")
        # bytes served by the proxy equal the registered identity
        for did in IDS.values():
            r = ctx.request.get(URL + f"api/demo/documents/{did}"); ok(r.status == 200 and r.headers["content-type"] == "application/pdf", f"{did} serve")
            ok(hashlib.sha256(r.body()).hexdigest() == man[did]["sha256"], f"{did}: served bytes match the manifest identity")
        ok(ctx.request.get(URL + "api/demo/documents/ddf53f79").status == 404 and ctx.request.get(URL + "api/demo/documents/dp001_ansi_d_coordinated_parent").status == 404, "unregistered ids are not served")
        step(1, "four registered documents; identities equal the existing manifest (62ab61d7…, 9fe8c894…, c2fe76dd…, 390ffe09…); addendum separate+controlling; served bytes hash-equal; ANSI D / v1 not present")

        # 2. viewer: sheet navigation, real pixels, identity strip. (dismiss the auto-opened Scope gate to inspect the package first)
        A.get_by_role("button", name="Dismiss to inspect documents").click(); A.wait_for_timeout(300)
        shot(A, "documents_overview")
        v = A.get_by_test_id("doc-viewer")
        for sheet, pg_n in SHEETS.items():
            A.get_by_role("tab", name=sheet, exact=True).click(); viewer_ready(A, IDS["drawings"], pg_n)
            ok(canvas_ink(A) > 800, f"{sheet} rendered with content")
            ok(f"p{pg_n} of 5" in v.inner_text() and "DP001_Drawings_IFB_Rev0_ANSI_B.pdf" in v.inner_text() and "Rev 0" in v.inner_text(), f"{sheet} identity strip")
            ok("62ab61d7f255" in v.locator("span.mono").first.get_attribute("title"), f"{sheet}: sha-256 shown")
        for tab, did, pages in (("Project Manual", IDS["pm"], 20), ("Instructions to Bidders", IDS["itb"], 2), ("Addendum 01", IDS["add"], 1)):
            A.get_by_role("tab", name=re.compile(tab)).click(); viewer_ready(A, did, 1); ok(canvas_ink(A) > 500, f"{tab} rendered")
            ok(f"p1 of {pages}" in v.inner_text(), f"{tab} has {pages} pages")
        ok("Controlling document" in v.inner_text(), "addendum viewer shows controlling status")
        shot(A, "addendum_viewer")
        step(2, "viewer opens G001, C101, C102, F501, F502, Project Manual (20 p), ITB (2 p) and Addendum 01 with real page content and the SHA-256/revision strip")

        # 3. Scope Gate: evidence-linked, human-prepared draft with the C101 drawing alongside
        A.get_by_role("button", name=re.compile("Review required")).click(); d = dlg(A, "Scope Gate"); d.wait_for()
        sd = d.get_by_test_id("scope-draft"); sd.wait_for()
        ok(sd.locator("article.draft-item:not(.rfi)").count() == 18, "18 draft items")
        ok(sd.locator("span.mini-tag.human").count() == 18, "every item labeled human-prepared")
        ok("not AI inference" in sd.inner_text() and "AMD" in sd.inner_text(), "draft states it is not AI inference")
        for it in sd.locator("article.draft-item:not(.rfi)").all():
            ok(it.get_by_test_id("item-status").count() == 1, "each item shows a status")
        ok(all(sd.get_by_test_id(f"item-{i}").locator(".ev-row").count() >= 1 for i in ("bid-base", "bid-alt", "fence-a", "fence-b", "gate-g1", "gate-g2", "gate-g3", "acc-ws", "acc-guard", "foot", "other", "addendum")), "evidence on each item")
        ok("Base Bid" in sd.get_by_test_id("item-bid-base").inner_text() and "ALTERNATE A-1" in sd.get_by_test_id("item-bid-alt").inner_text(), "base and alternate listed separately")
        ok("524 LF" in sd.get_by_test_id("item-fence-a").inner_text() and "448 LF" in sd.get_by_test_id("item-fence-a").inner_text(), "base 524 / alt 448 shown distinctly")
        g2 = sd.get_by_test_id("item-gate-g2"); ok("12'-0\" double leaf" in g2.inner_text() and "SUPERSEDED" in g2.inner_text() and "Controlled by Addendum 01" in g2.inner_text(), "G2 follows Addendum 01; Rev 0 shown only as superseded")
        ok(g2.locator(".ev-row.superseded").count() >= 1, "Rev 0 G2 evidence is struck/superseded")
        g3 = sd.get_by_test_id("item-gate-g3"); ok("NOT SPECIFIED" in g3.inner_text() and "Unresolved: RFI required" in g3.inner_text(), "G3 unresolved")
        ok(not re.search(r"\b\d+'-\d+\"\s*(clear|wide)", g3.get_by_test_id("item-status").inner_text()) and "unresolved (RFI required)" in g3.inner_text(), "no invented G3 width")
        ok("BLOCKS RELEASE" in sd.get_by_test_id("rfi-RFI-G3-WIDTH").inner_text(), "RFI-G3 flagged as blocking")
        # evidence chip -> the C101 drawing opens beside the review, with the cited text outlined where the text layer allows
        g_chip = sd.get_by_test_id("item-fence-a").locator(".chip-btn", has_text="C101 view 1"); g_chip.click(); viewer_ready(A, IDS["drawings"], 2)
        ok(A.get_by_test_id("viewer-cite").is_visible() and "176'-0\"" in A.get_by_test_id("viewer-cite").inner_text(), "cited text shown")
        print("   outline marks on C101:", A.get_by_test_id("viewer-mark").count(), flush=True)
        box = A.get_by_test_id("doc-viewer").bounding_box(); dbox = d.bounding_box()
        ok(box["x"] + box["width"] <= dbox["x"] + 4 and 0 <= box["y"] < 1100, f"viewer {box} sits beside the Scope Gate drawer {dbox}")
        shot(A, "c101_beside_scope_review")
        # addendum evidence for G2
        sd.get_by_test_id("item-gate-g2").locator(".chip-btn", has_text="Addendum 01").first.click(); viewer_ready(A, IDS["add"], 1)
        ok("Revise Gate G2" in A.get_by_test_id("viewer-cite").inner_text(), "G2 addendum citation")
        shot(A, "g2_addendum_citation")
        sd.get_by_test_id("item-gate-g3").locator(".chip-btn").first.click(); viewer_ready(A, IDS["drawings"], 5)
        shot(A, "g3_not_specified_f502")
        step(3, "Scope Gate shows the 18-item human-prepared draft with evidence per item; Base/A-1 distinct; G2 = Addendum 01 (Rev 0 superseded); G3 unresolved + blocking RFI; C101 opens beside the review")

        # 4. human Scope decisions (nothing auto-approved)
        ok(len(blocking(A)) == 15, f"fifteen blocking items at open (accepted footing engine), got {len(blocking(A))}")
        n_inf = scope_gate_to_g3(A, "base")
        left = blocking(A); ok(len(left) == 4 and all(e["code"] == "MISSING_VALUE" for e in left) and any("gates/2/clear_width_ft" in e["exception_id"] for e in left) and sum("GATE_G3" in e["exception_id"] for e in left) == 3, f"only the four G3 requirements remain: {[e['exception_id'] for e in left]}")
        s1 = state(A); ok(s1["status"] == "needs_scope_review" and s1["pricing"]["crew_plan"] is None and s1["proposal_digest"] is None, "blocked at Scope")
        d = dlg(A, "Scope Gate"); d.locator("button.exception-row", has_text="/gates/2/clear_width_ft").first.click(); A.wait_for_timeout(200)
        ok(d.get_by_test_id("missing-value-warning").is_visible(), "G3 form warns that a typed value is only a qualified assumption")
        ok(d.get_by_role("button", name="Record scope decision").is_disabled(), "cannot record a G3 decision without a value, name and note")
        shot(A, "g3_blocker")
        # release and downstream gates refuse while G3 is unresolved (no manufactured answer)
        before = state(A)
        r = api(A, "/api/demo/release", {"approver": "Visitor A", "expected_scope_version": before["scope_version"], "expected_proposal_digest": "0" * 64}); ok(r["status"] in (400, 409), f"release refused: {r}")
        r = api(A, "/api/demo/decision/crew-plan", {"by": "V", "note": "n", "preferred_crew": "CR12", "assignments": {}, "use_default_for_unassigned": False, "difficulty": {"default": "standard", "overrides": {}}}, {"Idempotency-Key": "dp001-early-plan-1"})
        ok(r["status"] == 409, f"crew plan refused before Scope clears: {r['status']} {r['body'].get('code')}")
        ok(state(A)["audit"] == before["audit"], "refusals changed nothing")
        step(4, f"Base Bid selected and {n_inf} human-prepared derivations approved one at a time (self-declared); G3 is the only blocker; release and crew plan are refused while it is unresolved")

        # 5. explicit qualified assumption for G3 (self-declared; NOT a documented answer), then the existing Labor workflow
        g3_demo(A)
        s2 = state(A); ok([e["code"] for e in s2["exceptions"] if e["severity"] == "blocking"] == ["QUANTITY_RULESET_UNAPPROVED"], "only the typed ruleset approval remains")
        rf = A.get_by_label("Quantity ruleset approval"); rf.wait_for(timeout=15000)
        ok("Contractor approval outstanding" in rf.inner_text() and "draft" in rf.inner_text().lower() and "Self-declared demo approval — identity not authenticated." in rf.inner_text(), "ruleset still draft/unapproved + self-declared label")
        rf.get_by_placeholder("Any name; recorded as self-declared").fill("Visitor A"); rf.get_by_placeholder("What did you review?").fill("Reviewed the rule table (demo)")
        rf.get_by_role("button", name="Approve this exact ruleset").click(); dl = dlg(A, "Labor Gate"); dl.wait_for(timeout=15000); A.wait_for_timeout(700)
        ok(state(A)["pricing"]["ruleset"]["contractor_approved"] is False, "visitor approval is not contractor approval")
        w = dl.get_by_label("Davis-Bacon wage determination")
        w.get_by_role("button", name="Load the fictional demonstration decision (FDB-DP001)").click()
        w.get_by_placeholder("Any name; recorded as self-declared").fill("Visitor A"); w.get_by_placeholder("What did you review?").fill("Transcribed from Attachment A, Section 00 0800")
        w.get_by_role("button", name="Record wage determination").click(); A.get_by_text("Recorded by the engine").first.wait_for(); A.wait_for_timeout(800); settle(A)
        dl.get_by_label("Preferred crew").select_option(value="CR12"); settle(A)
        dl.locator('button[data-task="L02"][data-crew="CR13"]').click(); settle(A)
        ok(dl.get_by_test_id("draft-total").is_visible(), "pricing preview")
        prev_total = usd(dl.get_by_test_id("draft-total").inner_text())
        ok("Estimated gross profit (at bid)" in dl.inner_text(), "estimated-at-bid wording")
        shot(A, "labor_crew_preview")
        dl.get_by_label("Crew plan approver name").fill("Visitor A"); dl.get_by_label("Crew plan note").fill("CR13 drills; CR12 elsewhere")
        dl.get_by_role("button", name="Approve crew plan").click(); rd = dlg(A, "Release Gate"); rd.wait_for(timeout=15000); A.wait_for_timeout(800)
        base = state(A); ok(base["status"] == "ready_for_final_review" and base["proposal_digest"], "release gate reached")
        ok(usd(rd.get_by_test_id("est-price_total").inner_text()) == prev_total, "approved total equals the preview")
        base_total, base_digest, base_fence = prev_total, base["proposal_digest"], base["takeoff"]["totals"]["fence_lf"]
        qual = " ".join(base["pricing"]["estimate_view"]["qualifications"])
        ok("entered for an unresolved fact" in qual and "12 entered" in qual and "2.875 entered" in qual and "footing scope is QUALIFIED_DEMONSTRATION_ONLY_NOT_BID_READY" in qual, f"the G3 assumption is carried into the estimate qualifications: {qual[:300]}")
        ok("not contractor-approved" in rd.inner_text(), "release gate states the quantity rules are not contractor-approved")
        shot(A, "release_gate_base")
        step(5, f"G3 qualified assumption recorded as self-declared; ruleset (draft, not contractor-approved) → wage → crew preview/approval → Release gate (Base total {base_total}, {base_fence} LF)")

        # 6. changing a scope decision after approvals invalidates the plan, the wage-dependent estimate and the release digest
        color = [e for e in base["exceptions"] if e["code"] == "OWNER_SELECTION_PENDING"][0]
        v0 = base["scope_version"]
        r = api(A, "/api/demo/scope/resolve", {"exception_id": color["exception_id"], "by": "Visitor A", "note": "Owner color decision recorded", "value": "Owner to select after award"}); ok(r["status"] == 200, r)
        s3 = state(A)
        ok(s3["scope_version"] == v0 + 1 and s3["status"] == "needs_labor_review" and s3["proposal_digest"] is None and s3["pricing"]["crew_plan"] is None, f"scope change voids approvals: {s3['status']} v{s3['scope_version']}")
        r = api(A, "/api/demo/release", {"approver": "Visitor A", "expected_scope_version": v0, "expected_proposal_digest": base_digest}); ok(r["status"] in (400, 409), f"stale release refused: {r['status']}")
        r = api(A, "/api/demo/release", {"approver": "Visitor A", "expected_scope_version": s3["scope_version"], "expected_proposal_digest": base_digest}); ok(r["status"] in (400, 409), "old digest refused at the new scope version")
        ok(state(A)["status"] != "released", "nothing released")
        A.reload(); A.wait_for_load_state("networkidle"); A.wait_for_timeout(800)
        dl = dlg(A, "Labor Gate"); dl.wait_for(); shot(A, "labor_reopened_after_scope_change")
        step(6, f"scope decision after approval: scope v{v0}→v{v0+1}, status back to Labor, crew plan and digest voided, stale version/digest releases refused")

        # 7. re-approve through the UI and complete the permitted fictional release (G3 assumption is a qualified assumption under existing policy)
        w = dl.get_by_label("Davis-Bacon wage determination") if dl.get_by_label("Davis-Bacon wage determination").count() else None
        wage_state = state(A)["pricing"]["wage"]
        if not wage_state.get("cleared"):
            w.get_by_role("button", name="Load the fictional demonstration decision (FDB-DP001)").click()
            w.get_by_placeholder("Any name; recorded as self-declared").fill("Visitor A"); w.get_by_placeholder("What did you review?").fill("Re-recorded after the scope change")
            w.get_by_role("button", name=re.compile("wage determination")).last.click(); A.wait_for_timeout(1200)
        settle(A)
        dl = dlg(A, "Labor Gate"); dl.get_by_label("Preferred crew").select_option(value="CR12"); settle(A)
        dl.locator('button[data-task="L02"][data-crew="CR13"]').click(); settle(A)
        dl.get_by_label("Crew plan approver name").fill("Visitor A"); dl.get_by_label("Crew plan note").fill("Re-approved after the scope change")
        dl.get_by_role("button", name=re.compile("Approve (revised )?crew plan")).click(); rd = dlg(A, "Release Gate"); rd.wait_for(timeout=15000); A.wait_for_timeout(800)
        s4 = state(A); ok(s4["status"] == "ready_for_final_review" and s4["proposal_digest"] and s4["proposal_digest"] != base_digest, "new digest after the scope change")
        # DP-001 release is QUALIFIED: a current Takeoff Review and an explicit acknowledgement of the open qualifications (mixed-footing pricing unsupported, G3 assumption...)
        A.get_by_test_id("open-takeoff").click(); tk = dlg(A, "Takeoff Review"); tk.get_by_test_id("takeoff-review").wait_for(timeout=15000)
        tk.get_by_label("Takeoff reviewer name").fill("Visitor A"); tk.get_by_label("Takeoff review note").fill("Checked deductions against C101 and F502")
        tk.get_by_role("button", name="Record takeoff review").click(); A.get_by_test_id("att-msg").wait_for(); A.wait_for_timeout(500); tk.get_by_role("button", name="Close").click()
        A.get_by_role("button", name=re.compile("Review required")).click(); rd = dlg(A, "Release Gate"); rd.wait_for(); A.wait_for_timeout(800)
        rd.get_by_placeholder("Any name; recorded as self-declared").fill("Visitor A"); rd.get_by_test_id("ack-qualified").check()
        rd.get_by_role("button", name=re.compile("Record QUALIFIED demonstration release")).click(); A.get_by_text("Recorded by the engine").first.wait_for(); A.wait_for_timeout(700)
        ok(state(A)["status"] == "released", "released with the current digest (qualified)"); shot(A, "release_gate_released_base")
        step(7, "re-approved wage + crew plan after the change; new digest; fictional release completed under the existing policy with the G3 assumption disclosed")

        # 8. Alternate A-1 is distinct: new project, same steps, different scope facts, different totals
        A.get_by_role("button", name="Reset demo").first.click(); A.get_by_text("Demo reset").first.wait_for(); A.wait_for_timeout(800)
        ok(state(A)["status"] == "needs_scope_review" and len(state(A)["audit"]) == 1, "fresh project for Alternate A-1")
        n_alt = scope_gate_to_g3(A, "ALT-A1")
        alt_left = blocking(A); ok(len(alt_left) == 4, [e["exception_id"] for e in alt_left])
        ok("Alternate A-1 (three courts, in lieu of the Base Bid)" in A.get_by_test_id("bid-state").inner_text(), "draft shows A-1 selected")
        ok("Selected by you" in dlg(A, "Scope Gate").get_by_test_id("item-bid-alt").inner_text() and "Not selected" in dlg(A, "Scope Gate").get_by_test_id("item-bid-base").inner_text(), "Base marked not selected (in lieu)")
        g3_demo(A)
        rf = A.get_by_label("Quantity ruleset approval"); rf.wait_for(timeout=15000)
        rf.get_by_placeholder("Any name; recorded as self-declared").fill("Visitor A"); rf.get_by_placeholder("What did you review?").fill("Reviewed the rule table (demo)")
        rf.get_by_role("button", name="Approve this exact ruleset").click(); dl = dlg(A, "Labor Gate"); dl.wait_for(timeout=15000); A.wait_for_timeout(700)
        w = dl.get_by_label("Davis-Bacon wage determination")
        w.get_by_role("button", name="Load the fictional demonstration decision (FDB-DP001)").click()
        w.get_by_placeholder("Any name; recorded as self-declared").fill("Visitor A"); w.get_by_placeholder("What did you review?").fill("Transcribed from Attachment A")
        w.get_by_role("button", name="Record wage determination").click(); A.get_by_text("Recorded by the engine").first.wait_for(); A.wait_for_timeout(800); settle(A)
        dl.get_by_label("Preferred crew").select_option(value="CR12"); settle(A); dl.locator('button[data-task="L02"][data-crew="CR13"]').click(); settle(A)
        dl.get_by_label("Crew plan approver name").fill("Visitor A"); dl.get_by_label("Crew plan note").fill("Same crews as the Base Bid run")
        dl.get_by_role("button", name="Approve crew plan").click(); rd = dlg(A, "Release Gate"); rd.wait_for(timeout=15000); A.wait_for_timeout(800)
        alt = state(A); alt_total = usd(rd.get_by_test_id("est-price_total").inner_text()); alt_fence = alt["takeoff"]["totals"]["fence_lf"]
        ok(alt["status"] == "ready_for_final_review", "A-1 reaches the Release gate")
        ok(base_fence == 716.0 and alt_fence == 576.0, f"fence LF base {base_fence} / alt {alt_fence}")
        ok(alt_total < base_total and alt["proposal_digest"] != base_digest, f"A-1 total {alt_total} < Base total {base_total}; digests differ")
        ok(alt["takeoff"]["totals"]["gates"] == 4 and alt["takeoff"]["totals"]["terminals"] == 16, "A-1 takeoff is its own")
        shot(A, "release_gate_alt_a1")
        step(8, f"Alternate A-1 distinct: {alt_fence} LF vs Base {base_fence} LF; total {alt_total} vs {base_total}; separate digests; Base never added")

        # 9. mobile 375 and console/external cleanliness
        A.set_viewport_size({"width": 375, "height": 812}); A.wait_for_timeout(700)
        ov = A.evaluate("document.documentElement.scrollWidth - window.innerWidth"); ok(ov <= 1, f"375px overflow {ov}px"); shot(A, "mobile_375")
        A.set_viewport_size({"width": 1800, "height": 1100})
        external = [u for u in external if not u.startswith(("https://fonts.googleapis.com/", "https://fonts.gstatic.com/"))]
        ok(not external, f"unexpected external requests: {external[:3]}")
        real_err = [e for e in console_errors if "favicon" not in e.lower() and "status of 409" not in e and "status of 400" not in e and "status of 429" not in e]
        ok(not real_err, f"console errors: {real_err[:3]}")
        save_state(ctx, "dp001"); b.close()
    print("DP-001 DOCUMENT-TO-SCOPE E2E PASS", len(steps), "steps")

if __name__ == "__main__":
    main()

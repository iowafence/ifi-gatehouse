"""DP-001 accepted-footing-engine integration, real browser (Chromium, classic scrollbars, 1800x732) through the real frontend proxy routes on 5041.
Engine = ~/ifi-gatehouse-footing-repair/engine (byte-verified copy). Expected values live in THIS TEST ONLY (assignment table + accepted-engine reference outputs).
No AMD calls. Screenshots -> evidence/screenshots/footing_*.png"""
import json, pathlib, re, sys
from decimal import Decimal as D
from playwright.sync_api import sync_playwright
from e2e_common import URL, SHOTS, WS, ok, api, dlg, usd
from e2e_dp001 import IDS, record_scope, state, blocking, viewer_ready

REPORT = WS / "evidence/footing_acceptance_report.json"
DRW = IDS["drawings"]; steps = []
HEAD_DEMO = "NOT BID READY — FICTIONAL DEMONSTRATION ONLY"
QCLASS = "QUALIFIED_DEMONSTRATION_ONLY_NOT_BID_READY"
EXP = {"base": dict(a_line=43, a_term=4, g12=6, g3=2, b_line=18, b_term=6, holes=79, known_cy=7.9566, total=D("54284.69"), label="Base Bid"),
       "alt":  dict(a_line=35, a_term=4, g12=6, g3=2, b_line=12, b_term=4, holes=63, known_cy=6.7308, total=D("45771.50"), label="Alternate A-1")}
def step(n, t, **ev): steps.append({"n": n, "title": t, **ev}); print(f"[{n}] {t} {json.dumps(ev, default=str)[:300]}", flush=True)
def shot(pg, name): pg.screenshot(path=str(SHOTS / f"footing_{name}.png"), full_page=False)
def settle(pg):
    pg.wait_for_timeout(300); pg.wait_for_function("!document.querySelector('.plan-totals')?.classList.contains('pending')", timeout=15000)
SAMPLER = """() => { window.__s=[]; window.__siv=setInterval(()=>{ const c=document.querySelector('[data-testid=doc-viewer] canvas'); let ink=-1;
    if(c&&c.width){ const x=c.getContext('2d'); const W=Math.min(c.width,800),H=Math.min(c.height,500); const d=x.getImageData(0,0,W,H).data; ink=0; for(let i=0;i<d.length;i+=28){ if(d[i]<120&&d[i+1]<120&&d[i+2]<120) ink++; } }
    window.__s.push({ink,o:!!document.querySelector('.viewer-overlay')}); },200); }"""
SEG = []
def seg(pg, label): s = pg.evaluate("() => { const s=window.__s||[]; return {n:s.length, overlay:s.filter(x=>x.o).length, blank:s.filter(x=>x.ink===0).length}; }"); SEG.append({label: s}); return s
def diag(pg): return pg.evaluate("() => ({...window.__pdfDiag})")
def samples(pg): return pg.evaluate("() => { const s=window.__s||[]; return {n:s.length, overlay:s.filter(x=>x.o).length, blank:s.filter(x=>x.ink===0).length}; }")

def open_takeoff(pg):
    pg.get_by_test_id("open-takeoff").click(); d = dlg(pg, "Takeoff Review"); d.get_by_test_id("takeoff-review").wait_for(timeout=15000); pg.wait_for_timeout(500); return d
def close_takeoff(pg): dlg(pg, "Takeoff Review").get_by_role("button", name="Close").click(); pg.wait_for_timeout(300)
def open_gate(pg, name="Scope Gate"):
    pg.get_by_role("button", name=re.compile("Review required")).click(); d = dlg(pg, name); d.wait_for(); return d
def scope_row_path(pg, path):
    d = dlg(pg, "Scope Gate"); d.locator("button.exception-row", has_text=path).first.click(); pg.wait_for_timeout(150); return d
def approve_all_inferred(pg):
    n = 0
    while True:
        inf = [e for e in blocking(pg) if e["code"] == "INFERRED_FACT_UNAPPROVED"]
        if not inf: return n
        d = scope_row_path(pg, inf[0]["affects"][0]); record_scope(pg, d, option="approve_inferred", note="Derivation checked against the cited dimensions"); n += 1
def select_bid(pg, option):
    d = dlg(pg, "Scope Gate"); d.locator("button.exception-row", has_text="Which bid should be priced").first.click(); pg.wait_for_timeout(150)
    record_scope(pg, d, option=option, note="Bid option selected for this estimate")

def rows(d, sc):
    out = {}
    for pc in ("A_LINE", "A_CORNER_TERMINAL", "GATE_G1", "GATE_G2", "GATE_G3", "B_LINE", "B_TERMINAL"):
        t = d.get_by_test_id(f"footings-{sc}").get_by_test_id(f"class-{pc}").get_by_test_id("count").inner_text().strip().split("\n")[0].split(" ")[0]
        out[pc] = None if t == "UNKNOWN" else int(t)
    return out
def check_counts(d, sc):
    e = EXP[sc]; r = rows(d, sc); g12 = d.get_by_test_id(f"footings-{sc}").get_by_test_id("class-G12").get_by_test_id("count").inner_text()
    got = dict(a_line=r["A_LINE"], a_term=r["A_CORNER_TERMINAL"], g12=int(g12), g3=r["GATE_G3"], b_line=r["B_LINE"], b_term=r["B_TERMINAL"])
    ok(got == {k: e[k] for k in got}, f"{sc} classes {got} != expected"); ok(r["GATE_G1"] + r["GATE_G2"] == e["g12"], "G1+G2 = 6")
    return got
def readiness(d, headline, bid_ready="false", rclass=QCLASS, artifact=None):
    b = d.get_by_test_id("readiness-banner"); b.wait_for(timeout=10000)
    ok(headline in b.get_by_test_id("rd-headline").inner_text(), f"headline {b.get_by_test_id('rd-headline').inner_text()!r}")
    ok(b.get_by_test_id("rd-bid_ready").inner_text().startswith(bid_ready), f"bid_ready {b.get_by_test_id('rd-bid_ready').inner_text()}")
    if rclass: ok(b.get_by_test_id("rd-release_class").inner_text() == rclass, f"release_class {b.get_by_test_id('rd-release_class').inner_text()}")
    fr = b.get_by_test_id("rd-footing_release_class").inner_text()
    if artifact: ok(b.get_by_test_id("rd-artifact_kind").inner_text() == artifact, "artifact_kind")
    return {"headline": b.get_by_test_id("rd-headline").inner_text(), "bid_ready": b.get_by_test_id("rd-bid_ready").inner_text(), "release_class": b.get_by_test_id("rd-release_class").inner_text(),
            "artifact_kind": b.get_by_test_id("rd-artifact_kind").inner_text(), "footing_release_class": fr}

def do_labor(pg, note):
    rf = pg.get_by_label("Quantity ruleset approval"); rf.wait_for(timeout=15000)
    rf.get_by_placeholder("Any name; recorded as self-declared").fill("Visitor A"); rf.get_by_placeholder("What did you review?").fill("Reviewed the rule table (demo)")
    rf.get_by_role("button", name="Approve this exact ruleset").click(); dl = dlg(pg, "Labor Gate"); dl.wait_for(timeout=15000); pg.wait_for_timeout(700)
    w = dl.get_by_label("Davis-Bacon wage determination"); w.get_by_role("button", name="Load the fictional demonstration decision (FDB-DP001)").click()
    w.get_by_placeholder("Any name; recorded as self-declared").fill("Visitor A"); w.get_by_placeholder("What did you review?").fill("Transcribed from Attachment A, Section 00 0800")
    w.get_by_role("button", name="Record wage determination").click(); pg.get_by_text("Recorded by the engine").first.wait_for(); pg.wait_for_timeout(800); settle(pg)
    dl.get_by_label("Preferred crew").select_option(value="CR13"); settle(pg)
    dl.locator('button[data-task="L02"][data-crew="CR13"]').click(); settle(pg)
    return dl
def approve_plan(pg, dl, note):
    dl.get_by_label("Crew plan approver name").fill("Visitor A"); dl.get_by_label("Crew plan note").fill(note)
    dl.get_by_role("button", name=re.compile("Approve (revised )?crew plan")).click(); rd = dlg(pg, "Release Gate"); rd.wait_for(timeout=15000); pg.wait_for_timeout(1000); return rd

def main():
    console_errors, external, rel_resp = [], [], []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, ignore_default_args=["--hide-scrollbars"])
        ctx = b.new_context(viewport={"width": 1800, "height": 732}); A = ctx.new_page()
        A.add_init_script("localStorage.setItem('pdfDiag','1')")
        A.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None); A.on("pageerror", lambda e: console_errors.append("PAGEERROR " + str(e)))
        A.on("request", lambda r: external.append(r.url) if not r.url.startswith(URL.rstrip("/")) and not r.url.startswith(("data:", "blob:")) else None)
        A.on("response", lambda r: rel_resp.append(r) if r.url.endswith("/api/demo/release") and r.request.method == "POST" else None)
        A.goto(URL); A.wait_for_load_state("networkidle"); A.wait_for_selector("[data-testid=doc-viewer] canvas")
        st = state(A)
        if not (st["status"] == "needs_scope_review" and len(st["audit"]) == 1):
            A.get_by_role("button", name="Reset demo").first.click(); A.get_by_text("Demo reset").first.wait_for(); A.wait_for_timeout(800); st = state(A)
        ok(st["status"] == "needs_scope_review" and len(st["audit"]) == 1, "fresh project")
        A.evaluate(SAMPLER)

        # 1. DP-001 at the Scope gate
        ok("DP-001" in A.locator(".project-summary").inner_text(), "DP-001 project")
        sg = dlg(A, "Scope Gate"); sg.wait_for(); ok(len(blocking(A)) >= 12, f"scope gate open with {len(blocking(A))} blocking items")
        ok(any("footing_scope" in x for e in st["exceptions"] for x in (e.get("affects") or e.get("affected_paths") or [])), "footing-scope exceptions present (G3 footing facts + stations)")
        step(1, "DP-001 opened at the Scope gate on the accepted footing engine (footing-scope.v1 scope); footing-scope exceptions present", blocking=len(blocking(A)))

        # 2. C101 + Takeoff Review together; select Base, approve the human-prepared derivations one at a time (self-declared)
        select_bid(A, "base"); n_inf = approve_all_inferred(A)
        left = [e["exception_id"] for e in blocking(A)]; ok(len(left) == 4 and all(x.startswith("EX-MISSING_VALUE") for x in left), left)
        A.get_by_role("button", name="Dismiss to inspect documents").click() if A.get_by_role("button", name="Dismiss to inspect documents").count() else None
        A.get_by_role("tab", name="C101", exact=True).click(); viewer_ready(A, DRW, 2)
        d = open_takeoff(A); vb = A.get_by_test_id("doc-viewer").bounding_box(); db = d.bounding_box()
        ok(vb["x"] + vb["width"] <= db["x"] + 4 and vb["width"] > 400 and 0 <= vb["y"] < 732, f"C101 viewer beside the review {vb} {db}")
        viewer_ready(A, DRW, 2); step(2, "C101 viewer displayed beside the Takeoff Review; Base selected; derivations approved one at a time", derivations_approved=n_inf)

        # 5 (first). G3 unresolved: unknowns, partial pricing, NOT BID READY / NOT SUBMITTABLE
        ok(d.get_by_test_id("g3-state").get_attribute("data-state") == "unresolved", "G3 unresolved")
        rd0 = readiness(d, "NOT BID READY / NOT SUBMITTABLE", rclass="NOT_PRICEABLE_PARTIAL_UNRECONCILED")
        base = d.get_by_test_id("footings-base"); r0 = rows(d, "base")
        ok(r0["A_LINE"] is None and r0["GATE_G3"] == 2 and r0["A_CORNER_TERMINAL"] == 4 and r0["B_LINE"] == 18 and r0["B_TERMINAL"] == 6, f"S0 classes {r0}")
        ok("UNKNOWN" in base.get_by_test_id("class-GATE_G3").inner_text() and "UNKNOWN" in base.get_by_test_id("holes-total").inner_text() and "UNKNOWN" in base.get_by_test_id("concrete-total").inner_text(), "G3/total unknown, not zero")
        ok(base.get_by_test_id("class-A_LINE").get_by_test_id("count").inner_text().strip().startswith("UNKNOWN"), "A line UNKNOWN")
        pcb = d.get_by_test_id("partial-base"); ok(pcb.get_by_test_id("partial-label").inner_text() == "PARTIAL_UNRECONCILED" and "NOT A PRICE" in pcb.inner_text() and "3,630.50" in pcb.get_by_test_id("partial-subtotal").inner_text(), pcb.inner_text()[:200])
        ok(pcb.get_by_test_id("unknown-exposure").locator("li").count() >= 2 and "Complete bid price: NONE" in pcb.get_by_test_id("no-complete-price").inner_text(), "unknown exposure listed; no complete price")
        for c in ("G3_OPENING_UNRESOLVED", "G3_POST_FOOTING_UNRESOLVED"): ok("hard block" in d.get_by_test_id(f"blocker-{c}").inner_text(), c)
        ok("NOT SENT" in d.get_by_test_id("g3-state").inner_text() and "OPEN" in d.get_by_test_id("g3-state").inner_text(), "RFI open and not sent")
        ok(d.get_by_test_id("pricing-status").count() == 0, "no engine price while G3 is unresolved")
        ok(d.get_by_test_id("att-blocked").is_visible(), "takeoff review cannot be recorded while G3 unresolved")
        ok(d.get_by_test_id("crosscheck-state").inner_text().startswith("AGREES"), "independent reference agrees at S0")
        shot(A, "g3_unresolved_partial_not_bid_ready")
        step(5, "G3 unresolved: A-line posts and G3 footing UNKNOWN (≥ minimum, never zero); partial known cost PARTIAL_UNRECONCILED beside listed unknown exposure; no complete price; NOT BID READY / NOT SUBMITTABLE; RFI open+unsent", readiness=rd0)

        # opening only (Scope gate form) -> S1 : expected conditional quantities
        close_takeoff(A); open_gate(A); sd = dlg(A, "Scope Gate"); scope_row_path(A, "/gates/2/clear_width_ft")
        record_scope(A, sd, value="12", note="DEMO ASSUMPTION for Gate G3 clear opening, pending RFI response; not stated in any document")
        approve_all_inferred(A); close_gate = None
        d = open_takeoff(A); ok(d.get_by_test_id("g3-state").get_attribute("data-state") == "partially_assumed", "partly assumed")
        # 3. Base classifications and concrete
        cb = check_counts(d, "base"); base = d.get_by_test_id("footings-base")
        dims = {pc: base.get_by_test_id(f"class-{pc}").locator("td").nth(2).inner_text().split("\n")[0] for pc in ("A_LINE", "A_CORNER_TERMINAL", "GATE_G1", "GATE_G2", "GATE_G3", "B_LINE", "B_TERMINAL")}
        ok(dims == {"A_LINE": "12″ × 48″", "A_CORNER_TERMINAL": "16″ × 48″", "GATE_G1": "16″ × 48″", "GATE_G2": "16″ × 48″", "GATE_G3": "UNKNOWN", "B_LINE": "8″ × 30″", "B_TERMINAL": "10″ × 30″"}, dims)
        ok(float(base.get_by_test_id("concrete-known-cy").inner_text().replace(",", "")) == EXP["base"]["known_cy"], base.get_by_test_id("concrete-known-cy").inner_text())
        ok("UNKNOWN (not zero): GATE_G3" in base.get_by_test_id("concrete-known").inner_text(), "G3 concrete unknown, not in totals")
        ok("not billed again in fence LF" in base.get_by_test_id("class-GATE_G1").inner_text() and "Type A" not in base.get_by_test_id("class-GATE_G3").inner_text().split("owner")[0], "gate posts owned by the gate EACH")
        ok(all("review-state" in base.get_by_test_id(f"class-{pc}").inner_html() for pc in ("A_LINE", "GATE_G3")), "approval/review state shown per class")
        ok("S01" in base.get_by_test_id("class-A_CORNER_TERMINAL").inner_text() and "unknown — not zero" in base.get_by_test_id("class-GATE_G3").inner_text(), "cost basis per class; unknown for G3")
        ok(base.get_by_test_id("legacy-recon").count() == 1 and "unexplained 0" in base.get_by_test_id("legacy-recon").text_content(), "legacy-to-schedule reconciliation, unexplained 0")
        ok("PROVISIONAL" in d.locator(".guardrail").first.inner_text() and "not verified design quantities" in d.locator(".guardrail").first.inner_text(), "provisional qualification")
        ok(d.get_by_test_id("crosscheck-state").inner_text().startswith("AGREES"), "reference agrees at S1")
        ok(d.get_by_test_id("pricing-status").count() == 0, "still no price (G3 post/footing unresolved)")
        base.scroll_into_view_if_needed(); shot(A, "base_footing_schedule_s1")
        hb = int(base.get_by_test_id("holes-total").inner_text()); step(3, "Base: classes 43/4/6/2/18/6, known-class concrete 7.9566 CY (G3 UNKNOWN, excluded, not zero), per-class dimensions, owner, cost basis, review state, provisional notice; legacy→schedule reconciliation", classes=cb, holes_total=hb)
        # 4. Alternate independently
        d.get_by_test_id("tab-alt").click(); ca = check_counts(d, "alt"); alt = d.get_by_test_id("footings-alt")
        ok(float(alt.get_by_test_id("concrete-known-cy").inner_text().replace(",", "")) == EXP["alt"]["known_cy"], alt.get_by_test_id("concrete-known-cy").inner_text())
        ok(d.get_by_test_id("not-selected").is_visible() and "never added" in d.get_by_test_id("not-selected").inner_text(), "alternate shown independently, never added")
        ok(base.get_attribute("data-schedule-sha") != alt.get_attribute("data-schedule-sha") if base.count() and alt.count() else True, "separate schedule hashes")
        alt_sha, base_sha = alt.get_attribute("data-schedule-sha"), d.get_by_test_id("tab-base").click() or d.get_by_test_id("footings-base").get_attribute("data-schedule-sha")
        ok(alt_sha != base_sha, "scenario-specific schedule hashes"); d.get_by_test_id("tab-alt").click(); shot(A, "alt_footing_schedule_s1"); d.get_by_test_id("tab-base").click()
        step(4, "Alternate A-1 independent: classes 35/4/6/2/12/4, known-class concrete 6.7308 CY; own schedule hash; never added to Base", classes=ca, schedule_sha_base=base_sha, schedule_sha_alt=alt_sha)

        # 6. explicit fictional what-if via the Takeoff panel (applies the remaining three self-declared facts)
        pre_sha = d.get_by_test_id("footings-base").get_attribute("data-schedule-sha")
        ok(d.get_by_test_id("apply-whatif").is_disabled(), "what-if needs a name")
        d.get_by_label("What-if name").fill("Visitor A"); ok(d.get_by_test_id("apply-whatif").is_enabled(), "what-if enabled once named")
        d.get_by_test_id("apply-whatif").click(); d.get_by_test_id("whatif-applied").wait_for(timeout=20000); A.wait_for_timeout(600)
        d = dlg(A, "Takeoff Review"); ok(d.get_by_test_id("g3-state").get_attribute("data-state") == "assumed", "G3 assumed")
        for f in ("opening", "post_od", "diameter", "depth"): ok("HUMAN_ASSUMPTION — NOT DOCUMENTED" in d.get_by_test_id(f"g3-{f}").inner_text(), f)
        ok("12 ft" in d.get_by_test_id("g3-opening").inner_text() and "2.875 in" in d.get_by_test_id("g3-post_od").inner_text() and "16 in" in d.get_by_test_id("g3-diameter").inner_text() and "48 in" in d.get_by_test_id("g3-depth").inner_text(), "exact what-if values")
        post_sha = d.get_by_test_id("footings-base").get_attribute("data-schedule-sha"); ok(post_sha != pre_sha, "schedule hash changed with the assumption (digest binds it)")
        b2 = d.get_by_test_id("footings-base"); ok(b2.get_by_test_id("class-GATE_G3").get_by_test_id("count").inner_text().strip() == "2" and "16″ × 48″" in b2.get_by_test_id("class-GATE_G3").inner_text() and "ASSUMED" in b2.get_by_test_id("class-GATE_G3").inner_text(), "G3 now 2 posts 16x48, basis ASSUMED")
        ok(int(b2.get_by_test_id("holes-total").inner_text()) == 79 and abs(float(b2.get_by_test_id("concrete-total").inner_text().replace(",", "")) - 8.3703) < 5e-5, "79 holes; 8.3703 CY with the assumed G3 class")
        ok(float(b2.get_by_test_id("concrete-known-cy").inner_text().replace(",", "")) == 8.3703, "engine known concrete now includes the assumed class")
        d.get_by_test_id("tab-alt").click(); a2 = d.get_by_test_id("footings-alt"); ok(int(a2.get_by_test_id("holes-total").inner_text()) == 63, "alt 63 holes"); d.get_by_test_id("tab-base").click()
        rd1 = readiness(d, HEAD_DEMO); shot(A, "g3_whatif_recorded_not_bid_ready")
        step(6, "Explicit fictional G3 what-if (12 ft · 2.875 in OD · 16 × 48 in) recorded through the Scope gate as self-declared assumptions; schedule hash changed; headline now NOT BID READY — FICTIONAL DEMONSTRATION ONLY", readiness=rd1)

        # labor gate: estimate view readiness, four-crew comparison, engine pricing
        close_takeoff(A); open_gate(A)
        dl = do_labor(A, "demo"); rdy = readiness(dl, HEAD_DEMO)
        eligible = {t: dl.locator(f'button[data-task="{t}"][data-eligible="true"]').count() for t in ("L02",)}; allc = dl.locator('button[data-task="L02"]').count()
        ok(allc >= 4 and eligible["L02"] >= 1, f"crew comparison grid {allc} crews, eligible for drilling {eligible}")
        crew_ids = sorted({x.get_attribute("data-crew") for x in dl.locator('button[data-task="L01"]').all()}); elig_ids = sorted({x.get_attribute("data-crew") for x in dl.locator('button[data-task="L01"][data-eligible="true"]').all()})
        ok(len(elig_ids) == 4, f"four eligible fleet crews: {elig_ids} of {crew_ids}")
        costs = {}
        for pref in elig_ids:   # the four eligible fleet crews, each as the preferred crew for every task (drilling stays on CR13)
            dl.get_by_label("Preferred crew").select_option(value=pref); settle(A); costs[pref] = str(usd(A.get_by_test_id("draft-total").inner_text()))
        ok(len(set(costs.values())) >= 2, f"the crew choice changes the engine's price: {costs}")
        dl.get_by_label("Preferred crew").select_option(value="CR13"); settle(A); dl.locator('button[data-task="L02"][data-crew="CR13"]').click(); settle(A)
        prev = usd(dl.get_by_test_id("draft-total").inner_text()); shot(A, "labor_four_crews_readiness")
        step(9, "Labor gate: four eligible fleet crews compared; preferred-crew choice changes the engine preview; readiness banner present in the estimate view", eligible_crews=elig_ids, preferred_crew_totals=costs, preview_total=str(prev), readiness=rdy)
        rd = approve_plan(A, dl, "CR13 preferred and drilling (matches the accepted-engine reference inputs)"); s1 = state(A); ok(s1["status"] == "ready_for_final_review" and s1["proposal_digest"], s1["status"])
        total = usd(rd.get_by_test_id("est-price_total").inner_text()); ok(total == prev, "approved total equals the preview")
        ok(total == EXP["base"]["total"], f"engine total {total} != accepted-engine reference {EXP['base']['total']}")
        ok(total == D(str(s1["pricing"]["estimate_view"]["price_total"])), "UI total is the engine's price_total (no browser price)")
        d = None
        step(7, f"Base priced by the actual integrated engine: ${total} equals the accepted-engine reference output under identical inputs (same rate book, FDB-DP001 wage record, crew plan CR13 preferred / CR13 drilling); UI total equals the engine's price_total", total=str(total))

        # 8. release-readiness fields: Release view + Takeoff view
        rdr = readiness(rd, HEAD_DEMO); ok("DEMONSTRATION ONLY · NOT A BID" in rd.inner_text(), "total labelled demonstration only")
        ok("footing scope is QUALIFIED_DEMONSTRATION_ONLY_NOT_BID_READY" in rd.get_by_test_id("rd-qualification-text").inner_text(), "server's original qualification text preserved")
        ok(rd.get_by_role("button", name="Authorize final proposal").count() == 0 and rd.get_by_role("button", name=re.compile("Record QUALIFIED demonstration release")).is_visible(), "no normal-looking authorize button")
        ok("QUALIFIED DEMONSTRATION release only" in rd.inner_text() and "Ready for final authorization" not in rd.inner_text(), "release gate wording says demonstration only, not final authorization")
        rd.get_by_test_id("readiness-banner").scroll_into_view_if_needed(); A.wait_for_timeout(250); shot(A, "release_gate_not_bid_ready")
        A.get_by_test_id("open-takeoff").click(); d = dlg(A, "Takeoff Review"); d.get_by_test_id("takeoff-review").wait_for(); A.wait_for_timeout(500)
        rdt = readiness(d, HEAD_DEMO); ok(d.get_by_test_id("pricing-qualifier").inner_text() == "QUALIFIED DEMONSTRATION ONLY — NOT BID READY", "pricing qualifier in the takeoff view")
        lab = {k: d.get_by_test_id(f"labor-{k}").locator("td").all_inner_texts() for k in ("L01", "L02", "L03", "L06")}
        ok(lab["L02"][1].startswith("79") and lab["L02"][2].startswith("79") and lab["L03"][1].startswith("79"), f"engine labor drivers use the schedule's 79 holes/posts: {lab['L02']}")
        ok(lab["L01"][1].startswith("716") and lab["L06"][1].startswith("676"), "gross 716 for layout, net 676 for fabric")
        ok(d.get_by_test_id("crosscheck-state").inner_text().startswith("AGREES"), "reference agrees with priced engine takeoff")
        ok(float(d.get_by_test_id("cost-direct_cost").inner_text().split("$")[-1].replace(",", "")) > 0, "engine cost lines shown")
        d.get_by_test_id("pricing-status").scroll_into_view_if_needed(); shot(A, "takeoff_engine_pricing")
        step(8, "All four engine readiness fields displayed in the Takeoff, Labor (estimate) and Release views; original qualification text preserved; no normal authorize button", release_view=rdr, takeoff_view=rdt)

        # 10-11. takeoff review, then stale-release attempts
        d.get_by_label("Takeoff reviewer name").fill("Visitor A"); d.get_by_label("Takeoff review note").fill("Checked deductions and the per-class schedule against C101 / F501 / F502; geometry provisional")
        d.get_by_role("button", name="Record takeoff review").click(); A.get_by_test_id("att-msg").wait_for(); A.wait_for_timeout(600)
        ok(d.get_by_test_id("att-state").get_attribute("data-current") == "1", "review current"); dg = d.get_by_test_id("takeoff-review").get_attribute("data-digest")
        k = "e2e-footing-review-1"; body = {"by": "Visitor A", "note": "Checked deductions and the per-class schedule against C101 / F501 / F502; geometry provisional", "takeoff_digest": dg}
        r1 = api(A, "/api/demo/takeoff/review", body, {"Idempotency-Key": k}); r2 = api(A, "/api/demo/takeoff/review", body, {"Idempotency-Key": k})
        ok(r1["status"] == 200 and r2["headers"].get("idempotent-replay") == "true" and r2["body"] == r1["body"], "review exact replay")
        ok(api(A, "/api/demo/takeoff/review", {**body, "note": "other"}, {"Idempotency-Key": k})["status"] == 409 and api(A, "/api/demo/takeoff/review", body)["status"] == 400, "same key other payload 409; missing key 400")
        close_takeoff(A); A.get_by_role("button", name=re.compile("Review required")).click(); rd = dlg(A, "Release Gate"); rd.wait_for(); A.wait_for_timeout(900)
        sv, dgst = s1["scope_version"], s1["proposal_digest"]; ack = api(A, "/api/demo/takeoff")["body"]["release_ack_required"]
        r = api(A, "/api/demo/release", {"approver": "Visitor A", "expected_scope_version": sv, "expected_proposal_digest": dgst, "takeoff_digest": dg}); ok(r["status"] == 409 and r["body"]["code"] == "NOT_BID_READY_ACKNOWLEDGEMENT_REQUIRED", r)
        r = api(A, "/api/demo/release", {"approver": "Visitor A", "expected_scope_version": sv, "expected_proposal_digest": dgst, "takeoff_digest": dg, "acknowledged_blockers": ack[:1]}); ok(r["status"] == 409, "partial acknowledgement refused")
        r = api(A, "/api/demo/release", {"approver": "Visitor A", "expected_scope_version": sv, "expected_proposal_digest": dgst, "takeoff_digest": dg, "acknowledged_blockers": ack, "bid_ready": True}); ok(r["status"] == 400 and "Unknown field" in r["body"]["error"], f"client bid_ready is rejected, never authority: {r}")
        ok(state(A)["status"] == "ready_for_final_review", "nothing released")
        step(10, "Scope + Labor authorization exercised (typed ruleset approval, wage determination, crew plan); takeoff review recorded with idempotent exact replay; release refused without full acknowledgement; client-supplied bid_ready rejected")

        # 12. supported scope change after Labor approval: digest invalidation + stale release
        color = [e for e in s1["exceptions"] if e["code"] == "OWNER_SELECTION_PENDING"][0]
        r = api(A, "/api/demo/scope/resolve", {"exception_id": color["exception_id"], "by": "Visitor A", "note": "Owner color decision recorded", "value": "Owner to select after award"}); ok(r["status"] == 200, r)
        s2 = state(A); ok(s2["scope_version"] == sv + 1 and s2["status"] == "needs_labor_review" and s2["proposal_digest"] is None and s2["pricing"]["crew_plan"] is None, "scope change voided labor + release digest")
        t2 = api(A, "/api/demo/takeoff")["body"]; ok(t2["digest"] != dg and t2["attestation"]["current"] is False, "takeoff digest changed; review STALE")
        r = api(A, "/api/demo/release", {"approver": "Visitor A", "expected_scope_version": sv, "expected_proposal_digest": dgst, "takeoff_digest": dg, "acknowledged_blockers": ack}); ok(r["status"] in (400, 409), f"stale version/digest refused: {r['status']} {r['body'].get('code')}")
        r = api(A, "/api/demo/release", {"approver": "Visitor A", "expected_scope_version": s2["scope_version"], "expected_proposal_digest": dgst, "takeoff_digest": dg, "acknowledged_blockers": ack}); ok(r["status"] in (400, 409), "old digest refused at the new version")
        ok(state(A)["status"] != "released", "nothing released")
        step(11, "Stale release rejected (old scope version / old proposal digest / old takeoff digest)")
        step(12, f"Supported scope change after approvals: scope v{sv}→v{s2['scope_version']}; Labor/crew plan/release digest voided; takeoff review STALE. (A persistent revision of a recorded footing/G3 fact is not exposed by the HTTP adapter: engine-level revision tests cover it.)")

        # reload mid-flow: viewer must stay put; re-approve labor
        pre = seg(A, "start_to_reload_1"); ok(pre["overlay"] == 0 and pre["blank"] == 0 and pre["n"] > 50, f"no viewer overlay/blank frames before reload: {pre}")
        A.reload(); A.wait_for_load_state("networkidle"); A.wait_for_selector("[data-testid=doc-viewer] canvas"); A.evaluate(SAMPLER); A.wait_for_timeout(1000)
        dl = dlg(A, "Labor Gate"); dl.wait_for(); settle(A)
        if not state(A)["pricing"]["wage"].get("cleared"):
            w = dl.get_by_label("Davis-Bacon wage determination"); w.get_by_role("button", name="Load the fictional demonstration decision (FDB-DP001)").click()
            w.get_by_placeholder("Any name; recorded as self-declared").fill("Visitor A"); w.get_by_placeholder("What did you review?").fill("Re-recorded after the scope change")
            w.get_by_role("button", name=re.compile("wage determination")).last.click(); A.wait_for_timeout(1200); settle(A)
        dl = dlg(A, "Labor Gate"); dl.get_by_label("Preferred crew").select_option(value="CR13"); settle(A); dl.locator('button[data-task="L02"][data-crew="CR13"]').click(); settle(A)
        rd = approve_plan(A, dl, "Re-approved after the scope change"); s3 = state(A)
        ok(s3["status"] == "ready_for_final_review" and s3["proposal_digest"] != dgst, "new engine digest")
        r = api(A, "/api/demo/release", {"approver": "Visitor A", "expected_scope_version": s3["scope_version"], "expected_proposal_digest": s3["proposal_digest"], "takeoff_digest": dg, "acknowledged_blockers": ack}); ok(r["status"] == 409 and r["body"]["code"] == "TAKEOFF_REVIEW_STALE", f"stale review cannot authorize: {r}")
        A.get_by_test_id("open-takeoff").click(); d = dlg(A, "Takeoff Review"); d.get_by_test_id("takeoff-review").wait_for(); A.wait_for_timeout(500)
        d.get_by_label("Takeoff reviewer name").fill("Visitor A"); d.get_by_label("Takeoff review note").fill("Re-reviewed after the scope change")
        d.get_by_role("button", name="Record takeoff review").click(); A.get_by_test_id("att-msg").wait_for(); A.wait_for_timeout(600); close_takeoff(A)

        # 13. the only permitted release: QUALIFIED FICTIONAL DEMONSTRATION
        A.get_by_role("button", name=re.compile("Review required")).click(); rd = dlg(A, "Release Gate"); rd.wait_for(); A.wait_for_timeout(1000)
        ok(rd.get_by_test_id("tr-review").inner_text().startswith("Takeoff review CURRENT"), "review current")
        rd.get_by_placeholder("Any name; recorded as self-declared").fill("Visitor A")
        btn = rd.get_by_role("button", name=re.compile("Record QUALIFIED demonstration release")); ok(btn.is_disabled(), "disabled until acknowledged")
        rd.get_by_test_id("ack-qualified").check(); ok(btn.is_enabled(), "enabled after acknowledgement"); shot(A, "release_gate_qualified")
        with A.expect_response(lambda r: r.url.endswith("/api/demo/release") and r.request.method == "POST") as ri: btn.click()
        resp = ri.value; hb = resp.json(); A.get_by_text("Recorded by the engine").first.wait_for(timeout=15000); A.wait_for_timeout(900)
        ok(resp.status == 200 and hb["bid_ready"] is False and hb["release_class"] == QCLASS and hb["artifact_kind"] == "QUALIFIED_FICTIONAL_DEMONSTRATION" and hb["footing_release_class"] == {"BASE": QCLASS, "ALT-A1": QCLASS}, f"release HTTP response: {resp.status} {json.dumps({k: v for k, v in hb.items() if k != 'qualifications'})}")
        ok(any("footing scope is" in (q if isinstance(q, str) else json.dumps(q)) for q in hb["qualifications"]), "server qualification text in the HTTP response")
        fin = state(A); ok(fin["status"] == "released", "released"); rel_audit = [a for a in fin["audit"] if a.get("event") in ("released", "release")][-1]
        ok("QUALIFIED DEMONSTRATION RELEASE — NOT BID READY" in json.dumps(rel_audit, ensure_ascii=False), "qualification recorded in the engine's release record")
        step(13, "Only the qualified fictional demonstration release was recorded (after a current takeoff review + explicit acknowledgement)", http_status=resp.status, response={k: v for k, v in hb.items() if k != "qualifications"})

        # 14. cannot be confused with a bid-ready artifact
        A.wait_for_timeout(600)
        if not A.locator("[role=dialog]").count(): A.get_by_role("button", name=re.compile("View release record")).click(); A.wait_for_timeout(800)   # the app closes the drawer after a release
        rd = dlg(A, "Release Gate")
        rdf = readiness(rd, HEAD_DEMO, artifact="QUALIFIED_FICTIONAL_DEMONSTRATION"); txt = rd.inner_text()
        ok("Qualified demonstration release recorded (not a bid)" in txt and "Proposal already released" not in txt, "released record wording")
        ok(A.get_by_test_id("status-demo").first.is_visible() and "Proposal released" not in A.locator("main").inner_text(), "status shows Demonstration release · NOT a bid, never 'Proposal released'")
        ok(not re.search(r"submit(?:ted)? (?:the )?bid|download (?:approved )?proposal|Authorize final proposal|bid[- ]ready: true", txt, re.I), "no bid-submission wording")
        ok(rd.get_by_role("button", name=re.compile("Proposal PDF not available")).is_disabled() and A.locator('a[href$=".pdf"]:visible, a[download]').count() == 0, "no submittable PDF or download link")
        r = api(A, "/api/demo/release", {"approver": "Visitor A", "expected_scope_version": fin["scope_version"], "expected_proposal_digest": fin["proposal_digest"] or "0" * 64, "takeoff_digest": dg}); ok(r["status"] in (400, 409), "second release refused")
        seg(A, "reload_1_to_reload_2")
        A.reload(); A.wait_for_load_state("networkidle"); A.wait_for_selector("[data-testid=doc-viewer] canvas"); A.evaluate(SAMPLER); A.wait_for_timeout(1500)
        if not A.locator("[role=dialog]").count(): A.get_by_role("button", name=re.compile("View release record")).click(); A.wait_for_timeout(800)
        rdf2 = readiness(dlg(A, "Release Gate"), HEAD_DEMO, artifact="QUALIFIED_FICTIONAL_DEMONSTRATION"); dlg(A, "Release Gate").get_by_test_id("readiness-banner").scroll_into_view_if_needed(); A.wait_for_timeout(250); shot(A, "release_record_not_bid_ready")
        step(14, "Released artifact shows NOT BID READY — FICTIONAL DEMONSTRATION ONLY with artifact_kind QUALIFIED_FICTIONAL_DEMONSTRATION (also after reload); no bid wording, no PDF, second release refused", after_release=rdf, after_reload=rdf2)

        # viewer stability across the whole Base run
        sm = seg(A, "reload_2_to_end"); dg_ = diag(A); tot = {k: sum(list(x.values())[0][k] for x in SEG) for k in ("n", "overlay", "blank")}
        ok(tot["overlay"] == 0 and tot["blank"] == 0 and tot["n"] > 100, f"viewer overlay/blank frames across the Base run: {tot} {SEG}"); ok(dg_["mounts"] <= 2 and dg_["docLoads"] <= 4, f"viewer lifecycle {dg_}")
        step("viewer", "viewer stayed visible (1800×732, scrollbars visible)", segments=SEG, total=tot, lifecycle={k: dg_[k] for k in ("mounts", "unmounts", "docLoads", "renderStarts", "loadingFlashes")})

        # Alternate A-1 as its own project: whole what-if applied from S0 through the Takeoff button
        A.get_by_role("button", name="Reset demo").first.click(); A.get_by_text("Demo reset").first.wait_for(); A.wait_for_timeout(900)
        dlg(A, "Scope Gate").wait_for(timeout=20000); select_bid(A, "ALT-A1"); approve_all_inferred(A)
        A.get_by_role("button", name="Dismiss to inspect documents").click() if A.get_by_role("button", name="Dismiss to inspect documents").count() else None
        d = open_takeoff(A); ok(d.get_by_test_id("takeoff-review").get_attribute("data-selected") == "alt", "alt selected"); d.get_by_test_id("tab-alt").click()
        rows_alt0 = rows(d, "alt"); ok(rows_alt0["A_LINE"] is None, "alt S0: A line unknown")
        d.get_by_label("What-if name").fill("Visitor A"); d.get_by_test_id("apply-whatif").click(); d.get_by_test_id("whatif-applied").wait_for(timeout=25000); A.wait_for_timeout(600)
        d = dlg(A, "Takeoff Review"); d.get_by_test_id("tab-alt").click(); ca2 = check_counts(d, "alt")
        ok(int(d.get_by_test_id("footings-alt").get_by_test_id("holes-total").inner_text()) == 63, "alt 63 holes"); readiness(d, HEAD_DEMO); close_takeoff(A); open_gate(A)
        dl = do_labor(A, "alt"); rd = approve_plan(A, dl, "Same crews as the Base Bid run"); salt = state(A)
        talt = usd(rd.get_by_test_id("est-price_total").inner_text()); ok(talt == EXP["alt"]["total"] == D(str(salt["pricing"]["estimate_view"]["price_total"])), f"alt engine total {talt} vs accepted reference {EXP['alt']['total']}")
        ok(salt["pricing"]["estimate_view"]["scope_ref"] == "ALT-A1" and salt["proposal_digest"] != dgst and talt < total, "alt priced separately, never added to Base"); readiness(rd, HEAD_DEMO); shot(A, "alt_release_gate_not_bid_ready")
        step("alt", f"Alternate A-1 (own project, what-if applied from the unresolved state): classes 35/4/6/2/12/4, 63 holes, engine total ${talt} equals the accepted-engine reference; Base never added", classes=ca2, total=str(talt))

        # 375 px
        M = b.new_context(viewport={"width": 375, "height": 812}); P = M.new_page(); P.goto(URL); P.wait_for_load_state("networkidle"); P.wait_for_selector("[data-testid=doc-viewer] canvas")
        P.get_by_role("button", name="Dismiss to inspect documents").click() if P.get_by_role("button", name="Dismiss to inspect documents").count() else None; P.wait_for_timeout(300)
        P.get_by_test_id("open-takeoff").click(); P.get_by_test_id("takeoff-review").wait_for(timeout=15000); P.wait_for_timeout(800)
        ov = P.evaluate("document.documentElement.scrollWidth - window.innerWidth"); ok(ov <= 1, f"375px overflow {ov}px"); P.screenshot(path=str(SHOTS / "footing_mobile_375.png"))
        ok(P.get_by_test_id("readiness-banner").is_visible(), "readiness visible at 375px")
        step("mobile", "375px: Takeoff Review + readiness render without page overflow", page_overflow_px=ov)

        ext = [u for u in external if not u.startswith(("https://fonts.googleapis.com/", "https://fonts.gstatic.com/"))]
        ok(not ext, f"unexpected external requests: {ext[:3]}"); ok(not any("amd" in u.lower() for u in external), "no AMD request")
        real = [e for e in console_errors if "favicon" not in e.lower() and not re.search(r"status of 4(00|09|29)", e)]; ok(not real, f"console errors {real[:3]}")
        step(15, "no viewer flashing (0 overlay/blank frames across the run), no console errors, no external or AMD requests", external_requests=len(ext))
        b.close()
    REPORT.write_text(json.dumps({"steps": steps}, indent=1, default=str)); print("FOOTING ENGINE INTEGRATION E2E PASS", len(steps), "step groups")

if __name__ == "__main__":
    main()

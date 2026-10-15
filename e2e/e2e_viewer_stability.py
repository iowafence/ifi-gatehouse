"""PDF viewer stability acceptance on the REAL DP-001 files (Chromium, classic scrollbars like a real browser, viewport 1800x732 which
reproduced the render loop before the fix). Evidence is lifecycle/network counters (window.__pdfDiag, opt-in) plus a 5 Hz in-page sampler of the
visible canvas (ink pixels, loading overlay, canvas pixel size) -- not screenshots. Writes evidence/viewer_stability_report.json."""
import json, pathlib, re, sys, time
from playwright.sync_api import sync_playwright
from e2e_common import URL, SHOTS, WS, ok, api, dlg
from e2e_dp001 import IDS, scope_gate_to_g3, record_scope, scope_row, state, blocking, viewer_ready, g3_demo

REPORT = WS / "evidence/viewer_stability_report.json"
DRW = IDS["drawings"]
report = {"checks": []}
def check(n, title, **ev): report["checks"].append({"n": n, "title": title, **ev}); print(f"[{n}] {title} {json.dumps(ev)}", flush=True)

SAMPLER = """() => { window.__s=[]; const tick=()=>{ const c=document.querySelector('[data-testid=doc-viewer] canvas'); let ink=-1,w=0,h=0;
    if(c&&c.width){ w=c.width;h=c.height; const x=c.getContext('2d'); const W=Math.min(w,800),H=Math.min(h,500); const d=x.getImageData(0,0,W,H).data; ink=0; for(let i=0;i<d.length;i+=28){ if(d[i]<120&&d[i+1]<120&&d[i+2]<120) ink++; } }
    window.__s.push({ink,w,h,o:!!document.querySelector('.viewer-overlay'),t:performance.now()}); }; window.__siv=setInterval(tick,200); }"""
def diag(pg): return pg.evaluate("() => { const d=window.__pdfDiag; return {mounts:d.mounts,unmounts:d.unmounts,renderStarts:d.renderStarts,renderDone:d.renderDone,cancelled:d.cancelled,loadingFlashes:d.loadingFlashes,docLoads:d.docLoads,resizes:d.resizes}; }")
def delta(a, b): return {k: b[k] - a[k] for k in a}
def samples(pg):
    s = pg.evaluate("() => window.__s"); pg.evaluate("() => { window.__s=[]; }"); return s
def summarize(s):
    inks = [x["ink"] for x in s if x["ink"] >= 0]
    return {"samples": len(s), "min_ink": min(inks) if inks else None, "overlay_frames": sum(1 for x in s if x["o"]),
            "blank_frames": sum(1 for x in s if x["ink"] == 0), "canvas_size_changes": sum(1 for i in range(1, len(s)) if (s[i]["w"], s[i]["h"]) != (s[i-1]["w"], s[i-1]["h"]))}

def main():
    pdf_gets, failed, console_errors, bad_status = {}, [], [], []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, ignore_default_args=["--hide-scrollbars"])      # classic scrollbars, as in a real browser
        ctx = b.new_context(viewport={"width": 1800, "height": 732}); A = ctx.new_page()
        A.add_init_script("localStorage.setItem('pdfDiag','1')")
        def on_req(r):
            m = re.search(r"/api/demo/documents/([a-z0-9_]+)$", r.url.split("#")[0])
            if m: pdf_gets[m.group(1)] = pdf_gets.get(m.group(1), 0) + 1
        A.on("request", on_req); A.on("requestfailed", lambda r: failed.append(r.url))
        A.on("response", lambda r: bad_status.append((r.status, r.url)) if "/api/demo/documents" in r.url and r.status >= 400 else None)
        A.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None); A.on("pageerror", lambda e: console_errors.append("PAGEERROR " + str(e)))
        A.goto(URL); A.wait_for_load_state("networkidle"); A.wait_for_selector("[data-testid=doc-viewer] canvas")
        A.evaluate(SAMPLER)
        viewer_ready(A, DRW, 2)

        def hold(label, secs):
            d0 = diag(A); samples(A); time.sleep(secs); s = summarize(samples(A)); d = delta(d0, diag(A))
            ok(d["renderStarts"] == 0 and d["mounts"] == 0 and d["unmounts"] == 0 and d["docLoads"] == 0 and d["loadingFlashes"] == 0 and d["cancelled"] == 0, f"{label}: lifecycle moved {d}")
            ok(s["overlay_frames"] == 0 and s["blank_frames"] == 0 and s["canvas_size_changes"] == 0 and s["min_ink"] > 200, f"{label}: visible canvas changed {s}")
            return {**s, **{"delta_" + k: v for k, v in d.items()}}
        # 1-2. leave G001 and C101 displayed for 30 s each
        A.get_by_role("tab", name="G001", exact=True).click(); viewer_ready(A, DRW, 1)
        check(1, "G001 displayed 30 s: no re-render, no overlay, no blank frame, no size change", **hold("G001", 30))
        A.get_by_role("tab", name="C101", exact=True).click(); viewer_ready(A, DRW, 2)
        check(2, "C101 displayed 30 s: same", **hold("C101", 30))

        # 3-4. scroll (page, stage, drawer) and zoom: only the zoom steps may re-render, never reload
        d0 = diag(A); samples(A)
        A.mouse.wheel(0, 600); A.wait_for_timeout(500); A.mouse.wheel(0, -600); A.wait_for_timeout(500)
        A.evaluate("() => { const s=document.querySelector('.viewer-stage'); s.scrollTop=300; s.scrollLeft=0; document.querySelector('.gate-dialog')?.scrollTo(0, 800); window.scrollTo(0, 400); }"); A.wait_for_timeout(1200)
        A.evaluate("() => { window.scrollTo(0, 0); document.querySelector('.gate-dialog')?.scrollTo(0, 0); }"); A.wait_for_timeout(800)
        sd = diag(A); ssum = summarize(samples(A)); dd = delta(d0, sd)
        ok(dd["renderStarts"] == 0 and dd["docLoads"] == 0 and dd["mounts"] == 0 and ssum["overlay_frames"] == 0 and ssum["blank_frames"] == 0, f"scroll: {dd} {ssum}")
        samples(A)
        zoomed = []
        for _ in range(3):
            before = diag(A)["renderDone"]; A.get_by_role("button", name="Zoom in").click()
            A.wait_for_function("(n) => window.__pdfDiag.renderDone > n", arg=before, timeout=15000); A.wait_for_timeout(400); zoomed.append(diag(A)["renderDone"] - before)
        for _ in range(3):
            before = diag(A)["renderDone"]; A.get_by_role("button", name="Zoom out").click()
            A.wait_for_function("(n) => window.__pdfDiag.renderDone > n", arg=before, timeout=15000); A.wait_for_timeout(400)
        zs = summarize(samples(A)); zd = delta(sd, diag(A))
        ok(zd["docLoads"] == 0 and zd["mounts"] == 0 and zd["loadingFlashes"] == 0 and zs["overlay_frames"] == 0 and zs["blank_frames"] == 0, f"zoom: {zd} {zs}")
        ok(all(z == 1 for z in zoomed), f"each zoom step renders exactly once: {zoomed}")
        check(3, "scroll (page, stage, drawer) caused 0 renders/reloads; 6 zoom steps = 6 renders, each exactly once, no overlay, never blank", scroll_delta=dd, zoom_delta=zd, zoom_summary=zs)

        # 5. sheet switching on one PDF: one render each, no reload, canvas never blank
        d0 = diag(A); samples(A); order = [("G001", 1), ("C101", 2), ("F501", 4), ("F502", 5), ("C101", 2)]
        for sheet, pg_n in order:
            A.get_by_role("tab", name=sheet, exact=True).click(); viewer_ready(A, DRW, pg_n); A.wait_for_timeout(600)
        sw = summarize(samples(A)); swd = delta(d0, diag(A))
        ok(swd["renderDone"] <= len(order) + 3 and swd["docLoads"] == 0 and swd["mounts"] == 0 and sw["blank_frames"] == 0 and sw["overlay_frames"] == 0, f"{swd} {sw}")
        ok(pdf_gets.get(DRW) == 1, f"drawings PDF fetched once for the whole session: {pdf_gets}")
        check(5, "G001→C101→F501→F502→C101: no PDF reload (1 fetch total), 0 mounts, 0 blank frames, 0 overlay", delta=swd, summary=sw, pdf_fetches=dict(pdf_gets))

        # 6. other documents
        for tab, did, n in (("Project Manual", IDS["pm"], 20), ("Instructions to Bidders", IDS["itb"], 2), ("Addendum 01", IDS["add"], 1)):
            A.get_by_role("tab", name=re.compile(tab)).click(); viewer_ready(A, did, 1); A.wait_for_timeout(400)
        A.get_by_role("tab", name=re.compile("Project Manual")).click(); viewer_ready(A, IDS["pm"], 1); A.get_by_role("button", name="Next page").click(); viewer_ready(A, IDS["pm"], 2)
        ok(all(pdf_gets.get(i) == 1 for i in IDS.values()), f"each document fetched once: {pdf_gets}")
        check(6, "Project Manual (+next page), ITB and Addendum 01 open; each PDF fetched exactly once", pdf_fetches=dict(pdf_gets))

        # 7. evidence chips -> correct page + highlight (drawer is open on the fresh project)
        d = dlg(A, "Scope Gate"); sd_ = d.get_by_test_id("scope-draft"); chips = []
        for item, label, doc, pg_n, cite in (("fence-a", "C101 view 1", DRW, 2, "176'-0\""), ("gate-g2", "Addendum 01", IDS["add"], 1, "Revise Gate G2"),
                                             ("gate-g3", "F502 note 4", DRW, 5, "CLEAR OPENING WIDTH IS NOT SPECIFIED"), ("acc-ws", "32 31 13 1.5.C", IDS["pm"], None, "Windscreen is measured")):
            sd_.get_by_test_id(f"item-{item}").locator(".chip-btn", has_text=label).first.click()
            if pg_n is None:
                A.wait_for_function("(d) => document.querySelector('[data-testid=doc-viewer]').dataset.renderedDoc===d && document.querySelector('[data-testid=doc-viewer]').dataset.busy==='0'", arg=doc, timeout=20000); pg_n = int(A.get_by_test_id("doc-viewer").get_attribute("data-rendered-page"))
            else: viewer_ready(A, doc, pg_n)
            A.wait_for_timeout(500)
            ok(cite.lower() in A.get_by_test_id("viewer-cite").inner_text().lower(), f"{item}: cite")
            chips.append({"item": item, "doc": doc[:22], "page": pg_n, "outline_marks": A.get_by_test_id("viewer-mark").count()})
        ok(chips[0]["outline_marks"] >= 1 and chips[1]["outline_marks"] >= 1, f"highlights appear for text-layer matches: {chips}")
        check(7, "evidence chips open the right document/page and outline the cited text", chips=chips)

        # 8-9. unrelated project/scope/pricing updates while the PDF stays open and visible
        A.get_by_role("tab", name=re.compile("Drawings")).click(); A.get_by_role("tab", name="C101", exact=True).click(); viewer_ready(A, DRW, 2)
        d0 = diag(A); samples(A)
        for _ in range(3):
            A.get_by_role("button", name="Refresh state").click(); A.wait_for_timeout(900)
        d = scope_row(A, "Which bid should be priced"); record_scope(A, d, option="base", note="Bid option selected for this estimate")   # real scope decision + state refresh
        n = 0
        while [e for e in blocking(A) if e["code"] == "INFERRED_FACT_UNAPPROVED"]:
            e = [e for e in blocking(A) if e["code"] == "INFERRED_FACT_UNAPPROVED"][0]
            d = scope_row(A, e["affects"][0].strip("/").replace("/", " > ")); record_scope(A, d, option="approve_inferred", note="Derivation checked against the cited dimensions"); n += 1
        g3_demo(A)
        up = summarize(samples(A)); ud = delta(d0, diag(A))
        ok(ud["renderStarts"] == 0 and ud["mounts"] == 0 and ud["unmounts"] == 0 and ud["docLoads"] == 0 and ud["loadingFlashes"] == 0, f"project/scope updates touched the viewer: {ud}")
        ok(up["blank_frames"] == 0 and up["overlay_frames"] == 0 and up["canvas_size_changes"] == 0, f"viewer not stable during updates: {up}")
        # pricing / approval state changes: ruleset approval moves the project to Labor (the drawer changes from Scope Gate to Labor Gate)
        rf = A.get_by_label("Quantity ruleset approval"); rf.wait_for(timeout=15000)
        rf.get_by_placeholder("Any name; recorded as self-declared").fill("Visitor A"); rf.get_by_placeholder("What did you review?").fill("Reviewed the rule table (demo)")
        rf.get_by_role("button", name="Approve this exact ruleset").click(); dlg(A, "Labor Gate").wait_for(timeout=15000); A.wait_for_timeout(1500)
        w = dlg(A, "Labor Gate").get_by_label("Davis-Bacon wage determination")
        w.get_by_role("button", name="Load the fictional demonstration decision (FDB-DP001)").click()
        w.get_by_placeholder("Any name; recorded as self-declared").fill("Visitor A"); w.get_by_placeholder("What did you review?").fill("Transcribed from Attachment A")
        w.get_by_role("button", name="Record wage determination").click(); A.get_by_text("Recorded by the engine").first.wait_for(); A.wait_for_timeout(1500)
        up2 = summarize(samples(A)); ud2 = delta(d0, diag(A))
        ok(ud2["renderStarts"] == 0 and ud2["mounts"] == 0 and ud2["unmounts"] == 0 and ud2["docLoads"] == 0 and ud2["loadingFlashes"] == 0, f"pricing/approval updates touched the viewer: {ud2}")
        ok(up2["blank_frames"] == 0 and up2["overlay_frames"] == 0 and up2["canvas_size_changes"] == 0, f"viewer blanked during approval changes: {up2}")
        ok(state(A)["status"] == "needs_labor_review", state(A)["status"])
        check(8, f"3× Refresh state, bid selection + {n} derivation approvals + G3 + ruleset (Scope→Labor drawer swap) + wage decision: viewer lifecycle delta all zero", delta=ud2, summary=up2)
        check(9, "the drawing stayed visible in every 200 ms sample across all of those updates", min_ink=up2["min_ink"], blank_frames=up2["blank_frames"], overlay_frames=up2["overlay_frames"])
        A.evaluate("() => clearInterval(window.__siv)")

        # 10. console + network
        ok(all(v == 1 for v in pdf_gets.values()), f"PDF fetch counts {pdf_gets}"); ok(not failed and not bad_status, f"failed {failed} bad {bad_status}")
        real = [e for e in console_errors if "favicon" not in e.lower() and not re.search(r"status of 4(00|09|29)", e)]
        ok(not real, f"console errors {real[:3]}")
        check(10, "network and console clean", pdf_fetches=dict(pdf_gets), failed_requests=len(failed), bad_document_status=len(bad_status), console_errors=len(real))

        # regression sweep of the exact viewport band that looped (1800 x 690..790) with the fixed build
        loops = []
        for H in range(690, 792, 3):
            A.set_viewport_size({"width": 1800, "height": H}); A.wait_for_timeout(700); a = diag(A); A.wait_for_timeout(900)
            if diag(A)["renderStarts"] != a["renderStarts"]: loops.append(H)
        ok(not loops, f"render loop at heights {loops}")
        check("sweep", "viewport heights 690-789 step 3 (the band that looped): no render activity while idle", loops=loops)
        A.set_viewport_size({"width": 1800, "height": 1100}); A.wait_for_timeout(1200)

        # 375px mobile: viewer in the drawer when the Scope Gate is open; stable for 15 s; no horizontal overflow
        M = b.new_context(viewport={"width": 375, "height": 812}); P = M.new_page(); P.add_init_script("localStorage.setItem('pdfDiag','1')")
        P.goto(URL); P.wait_for_load_state("networkidle"); P.wait_for_selector("[data-testid=doc-viewer] canvas"); P.evaluate(SAMPLER); viewer_ready(P, DRW, 2)
        d0 = diag(P); samples(P); time.sleep(15); ms = summarize(samples(P)); md = delta(d0, diag(P))
        ok(md["renderStarts"] == 0 and md["mounts"] == 0 and md["docLoads"] == 0 and ms["blank_frames"] == 0 and ms["overlay_frames"] == 0, f"mobile {md} {ms}")
        ov = P.evaluate("document.documentElement.scrollWidth - window.innerWidth"); ok(ov <= 1, f"375px overflow {ov}")
        P.get_by_role("tab", name="F501", exact=True).click(); viewer_ready(P, DRW, 4); P.get_by_role("button", name="Zoom in").click(); P.wait_for_timeout(1200)
        P.screenshot(path=str(SHOTS / "viewer_mobile_375.png"))
        check("mobile", "375px: viewer (in the Scope drawer) stable for 15 s, sheet switch + zoom work, no horizontal overflow", delta=md, summary=ms, overflow_px=ov)
        b.close()
    REPORT.write_text(json.dumps(report, indent=1)); print("VIEWER STABILITY PASS", len(report["checks"]), "checks")

if __name__ == "__main__":
    main()

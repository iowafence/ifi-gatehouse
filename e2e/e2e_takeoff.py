"""DP-001 Takeoff Review ledger acceptance (Chromium, classic scrollbars, 1800x732, real proxy routes, ACCEPTED footing engine).
Expected quantities are computed INDEPENDENTLY by the independent reference (dp001/reference/dp001_takeoff_review.py), not by the app:
gross -> opening deductions -> net, windscreen, fence guard, gates, per-class post counts and holes, for Base and Alternate A-1 (G3 unresolved / 12 / 14 ft).
The full Scope -> Labor -> Release, pricing and readiness flow is e2e_footing.py; this suite keeps the original takeoff acceptance (and its reference)."""
import json, math, pathlib, re, sys
from decimal import Decimal as D
from playwright.sync_api import sync_playwright
from e2e_common import URL, SHOTS, WS, ok, api, dlg
from e2e_dp001 import IDS, record_scope, state, blocking, viewer_ready
from e2e_footing import SAMPLER, diag, select_bid, approve_all_inferred, scope_row_path, open_takeoff, close_takeoff, open_gate
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "dp001/reference"))
from dp001_takeoff_review import reconcile as REF

REPORT = WS / "evidence/takeoff_acceptance_report.json"
DRW = IDS["drawings"]; steps = []
def step(n, t, **ev): steps.append({"n": n, "title": t, **ev}); print(f"[{n}] {t} {json.dumps(ev, default=str)[:300]}", flush=True)
def shot(pg, name): pg.screenshot(path=str(SHOTS / f"takeoff_{name}.png"), full_page=False)
def n_(s): return float(re.sub(r"[^\d.\-]", "", s.replace("−", "-")) or "nan")
def count(d, sc, pc):
    t = d.get_by_test_id(f"footings-{sc}").get_by_test_id(f"class-{pc}").get_by_test_id("count").inner_text().strip().split("\n")[0].split(" ")[0]
    return None if t == "UNKNOWN" else int(t)
def classes(d, sc):
    f = lambda pc: count(d, sc, pc)
    g12 = d.get_by_test_id(f"footings-{sc}").get_by_test_id("class-G12").get_by_test_id("count").inner_text().strip()
    return {"a_line": f("A_LINE"), "a_terminal": f("A_CORNER_TERMINAL"), "g12_gate": int(g12), "g3_gate": f("GATE_G3"), "b_line": f("B_LINE"), "b_terminal": f("B_TERMINAL")}
def expect_for(scn, g3): return REF("base" if scn == "base" else "alternate_a1", D(str(g3)) if g3 is not None else None)

def check_ledger(d, scn, g3):
    want = expect_for(scn, g3); L = d.get_by_test_id(f"ledger-{scn}")
    ok(n_(L.get_by_test_id("row-net-a").locator("td").nth(1).inner_text()) == want["net_type_a_lf"], f"{scn} net A {want['net_type_a_lf']}")
    ok(n_(L.get_by_test_id("row-net-b").locator("td").nth(1).inner_text()) == want["net_type_b_lf"], f"{scn} net B")
    ok(n_(L.get_by_test_id("row-net-total").locator("td").nth(1).inner_text()) == want["net_fence_lf"], f"{scn} net total {want['net_fence_lf']}")
    cl = classes(d, scn); ta, tb = want["type_a_post_count"], want["type_b_post_count"]
    exp = {"a_line": ta["line"], "a_terminal": ta["corners"], "g12_gate": ta["gate_posts_total"] - ta["gate_posts_unknown_size_g3"], "g3_gate": ta["gate_posts_unknown_size_g3"], "b_line": tb["line"], "b_terminal": tb["terminals"]}
    ok(cl == exp, f"{scn} classes {cl} != reference {exp}")
    ok(int(d.get_by_test_id(f"footings-{scn}").get_by_test_id("holes-total").inner_text()) == want["total_core_drill_holes"] == sum(exp.values()), f"{scn} holes")
    ok(d.get_by_test_id("crosscheck-state").inner_text().startswith("AGREES"), f"{scn}: engine schedule agrees with the independent reference")
    return want, cl

def main():
    console_errors = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, ignore_default_args=["--hide-scrollbars"])
        ctx = b.new_context(viewport={"width": 1800, "height": 732}); A = ctx.new_page()
        A.add_init_script("localStorage.setItem('pdfDiag','1')")
        A.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None); A.on("pageerror", lambda e: console_errors.append("PAGEERROR " + str(e)))
        A.goto(URL); A.wait_for_load_state("networkidle"); A.wait_for_selector("[data-testid=doc-viewer] canvas")
        st = state(A)
        if not (st["status"] == "needs_scope_review" and len(st["audit"]) == 1):
            A.get_by_role("button", name="Reset demo").first.click(); A.get_by_text("Demo reset").first.wait_for(); A.wait_for_timeout(800); st = state(A)
        ok(st["status"] == "needs_scope_review" and len(st["audit"]) == 1, "fresh project"); A.evaluate(SAMPLER)
        A.get_by_role("tab", name="C101", exact=True).click(); viewer_ready(A, DRW, 2)
        ok("DP-001" in A.locator(".project-summary").inner_text(), "DP-001 project")
        step(1, "DP-001 opened; C101 displayed in the viewer")

        # 2-4. Base takeoff with G3 unknown (both options before any selection)
        A.get_by_role("button", name="Dismiss to inspect documents").click() if A.get_by_role("button", name="Dismiss to inspect documents").count() else None
        d = open_takeoff(A)
        ok("PROVISIONAL" in d.locator(".guardrail").first.inner_text() and "GROSS composite" in d.locator(".guardrail").first.inner_text(), "provisional + gross-not-net banner")
        ok("NOT BID READY" in d.get_by_test_id("rd-headline").inner_text(), "not bid ready shown")
        base = d.get_by_test_id("ledger-base"); ok(base.get_attribute("data-status") == "BLOCKED_G3_UNRESOLVED", "base blocked")
        want = expect_for("base", None)
        ok(n_(base.get_by_test_id("row-gross-a").locator("td").nth(1).inner_text()) == want["gross_type_a_lf"] == 524, "gross A 524")
        ok(n_(base.get_by_test_id("row-gross-b").locator("td").nth(1).inner_text()) == 192, "gross B 192")
        ok(n_(base.get_by_test_id("row-gross-total").locator("td").nth(1).inner_text()) == 716 and "not billable net" in base.get_by_test_id("row-gross-total").inner_text(), "gross 716 labelled not billable")
        ok("4 LF" in base.get_by_test_id("row-open-G1").inner_text(), "G1 deduction 4")
        g2 = base.get_by_test_id("row-open-G2").inner_text(); ok("24" in g2 and "12" in g2 and "superseded" in g2, f"G2 = 2 x 12 per Addendum 01, Rev 0 superseded: {g2}")
        g3 = base.get_by_test_id("row-open-G3").inner_text(); ok("UNKNOWN" in g3 and "RFI" in g3 and "Never defaulted to 0" in g3, g3)
        ok("UNKNOWN" in base.get_by_test_id("row-net-a").inner_text() and "524 − 28 − G3 width" in base.get_by_test_id("row-net-a").inner_text(), "net A unknown, formula shown")
        ok("688 − G3 width" in base.get_by_test_id("row-net-total").inner_text() and "NO FINAL NUMBER" in base.get_by_test_id("row-net-total").inner_text(), "net total formula 688 - G3")
        ok(n_(base.get_by_test_id("row-windscreen").locator("td").nth(1).inner_text()) == 176 and n_(base.get_by_test_id("row-guard").locator("td").nth(1).inner_text()) == 192, "windscreen 176 / guard 192")
        gt = base.get_by_test_id("row-gates").inner_text(); ok("G1 × 1" in gt and "G2 × 2" in gt and "G3 × 1" in gt, "gates by tag")
        c0 = classes(d, "base"); ok(c0["a_line"] is None and c0["g3_gate"] == 2 and c0["b_line"] == 18 and c0["b_terminal"] == 6 and c0["a_terminal"] == 4 and c0["g12_gate"] == 6, f"unresolved G3: {c0}")
        ok("UNKNOWN" in d.get_by_test_id("footings-base").get_by_test_id("holes-total").inner_text(), "total holes unknown while G3 unresolved")
        ok("UNKNOWN" in d.get_by_test_id("footings-base").get_by_test_id("class-GATE_G3").inner_text(), "G3 footing unknown")
        ok("NOT SENT" in d.get_by_test_id("g3-state").inner_text(), "RFI unsent")
        vb = A.get_by_test_id("doc-viewer").bounding_box(); db = d.bounding_box(); ok(vb["x"] + vb["width"] <= db["x"] + 4, f"viewer beside review {vb} {db}")
        d.get_by_test_id("ledger-base").locator(".chip-btn", has_text="C101").first.click(); viewer_ready(A, DRW, 2); A.wait_for_timeout(300); shot(A, "base_g3_unresolved")
        d.get_by_test_id("tab-alt").click(); alt = d.get_by_test_id("ledger-alt")
        ok("448 − 28 − G3 width" in alt.get_by_test_id("row-net-a").inner_text() and "548 − G3 width" in alt.get_by_test_id("row-net-total").inner_text(), "alt formulas 420-G3 / 548-G3")
        ok(n_(alt.get_by_test_id("row-gross-total").locator("td").nth(1).inner_text()) == 576 and n_(alt.get_by_test_id("row-windscreen").locator("td").nth(1).inner_text()) == 138, "alt gross 576, windscreen 138")
        ok(d.get_by_test_id("not-selected").is_visible(), "alt marked not selected"); d.get_by_test_id("tab-base").click()
        step("2-4", "Base takeoff: gross 524/192/716 (not billable), G1 4, G2 2×12 (Rev 0 superseded), G3 UNKNOWN, net A/total UNKNOWN with formulas 496−G3 / 688−G3; Alt 420−G3 / 548−G3; windscreen/guard/gates; G3-independent classes only")

        # 5-6. scope decisions via the UI, then the self-declared G3 OPENING (post/footing stay unresolved)
        close_takeoff(A); open_gate(A); select_bid(A, "base"); n_inf = approve_all_inferred(A)
        d = open_takeoff(A); ok(d.get_by_test_id("takeoff-review").get_attribute("data-selected") == "base", "base selected")
        ok("UNKNOWN" in d.get_by_test_id("ledger-base").get_by_test_id("row-net-a").inner_text(), "still unknown until specifically assumed")
        ok("hard block" in d.get_by_test_id("blocker-G3_OPENING_UNRESOLVED").inner_text(), "G3_OPENING_UNRESOLVED blocker")
        close_takeoff(A); sd = open_gate(A); scope_row_path(A, "/gates/2/clear_width_ft"); record_scope(A, sd, value="12", note="DEMO ASSUMPTION for Gate G3 clear opening, pending RFI response; not stated in any document"); approve_all_inferred(A)
        d = open_takeoff(A)
        wb, clb = check_ledger(d, "base", 12); ok(wb["net_type_a_lf"] == 484 and wb["net_fence_lf"] == 676 and wb["total_core_drill_holes"] == 79, "reference: 484/676/79")
        ok("HUMAN_ASSUMPTION — NOT DOCUMENTED" in d.get_by_test_id("ledger-base").get_by_test_id("row-open-G3").inner_text(), "assumption labelled undocumented")
        ok("12 ft" in d.get_by_test_id("g3-opening").inner_text() and "NOT SENT" in d.get_by_test_id("g3-state").inner_text(), "G3 assumption + RFI open/unsent")
        d.get_by_test_id("tab-alt").click(); wa, cla = check_ledger(d, "alt", 12); ok(wa["net_type_a_lf"] == 408 and wa["net_fence_lf"] == 536 and wa["total_core_drill_holes"] == 63, "reference alt: 408/536/63")
        d.get_by_test_id("tab-base").click(); shot(A, "base_g3_assumed_ledger")
        ft = d.get_by_test_id("footings-base"); dim = {c: ft.get_by_test_id(f"class-{c}").locator("td").nth(2).inner_text().split("\n")[0] for c in ("A_LINE", "A_CORNER_TERMINAL", "GATE_G1", "GATE_G2", "B_LINE", "B_TERMINAL", "GATE_G3")}
        ok(dim == {"A_LINE": "12″ × 48″", "A_CORNER_TERMINAL": "16″ × 48″", "GATE_G1": "16″ × 48″", "GATE_G2": "16″ × 48″", "B_LINE": "8″ × 30″", "B_TERMINAL": "10″ × 30″", "GATE_G3": "UNKNOWN"}, dim)
        ok("not billed again in fence LF" in ft.get_by_test_id("class-GATE_G1").inner_text() and "not billed again in fence LF" in ft.get_by_test_id("class-GATE_G2").inner_text(), "ownership: gate posts under gate EACH")
        ok(abs(float(ft.get_by_test_id("concrete-known-cy").inner_text().replace(",", "")) - 7.9566) < 5e-5, "known-class concrete 7.9566 CY")
        step("5-6", "G3 opening recorded (self-declared) → net 484/676, 79 holes; Alt 408/536/63; per-class dimensions; engine schedule agrees with the independent reference", n_scope_approvals=n_inf)

        # no engine price while G3 post/footing unresolved: review cannot be recorded, release refused
        ok(d.get_by_test_id("pricing-status").count() == 0 and d.get_by_test_id("att-blocked").is_visible(), "no price; review refused while the G3 post/footing is open")
        close_takeoff(A)

        # Alternate A-1 as its own project with a DIFFERENT opening (14 ft): classes/net/holes vs the reference
        A.get_by_role("button", name="Reset demo").first.click(); A.get_by_text("Demo reset").first.wait_for(); A.wait_for_timeout(900)
        sd = dlg(A, "Scope Gate"); sd.wait_for(timeout=20000); select_bid(A, "ALT-A1"); approve_all_inferred(A); scope_row_path(A, "/gates/2/clear_width_ft")
        record_scope(A, sd, value="14", note="DEMO ASSUMPTION for Gate G3 clear opening, pending RFI response; not stated in any document"); approve_all_inferred(A)
        d = open_takeoff(A); ok(d.get_by_test_id("takeoff-review").get_attribute("data-selected") == "alt", "alt selected"); d.get_by_test_id("tab-alt").click()
        wa14, cla14 = check_ledger(d, "alt", 14); ok(wa14["net_type_a_lf"] == 406 and wa14["net_fence_lf"] == 534, f"alt G3=14 → 406/534: {wa14['net_type_a_lf']}/{wa14['net_fence_lf']}")
        d.get_by_test_id("tab-base").click(); wb14 = expect_for("base", 14); L = d.get_by_test_id("ledger-base")
        ok(n_(L.get_by_test_id("row-net-a").locator("td").nth(1).inner_text()) == wb14["net_type_a_lf"] == 482, "base conditional ledger at 14 ft = 482 (independent reference)")
        ok(d.get_by_test_id("no-engine-schedule").is_visible() and d.get_by_test_id("footings-base").count() == 0, "no engine footing schedule is shown for the unselected Base (the engine replaces it with Alternate A-1)")
        ok("Not selected" in d.get_by_test_id("not-selected").inner_text(), "base not selected, shown independently")
        d.get_by_test_id("tab-alt").click(); shot(A, "alt_selected_g3_14")
        step("alt", "Alternate A-1 project, opening 14 ft: net 406/534, class counts and holes match the independent reference; Base shown independently as not selected", reference_holes=wa14["total_core_drill_holes"])
        close_takeoff(A)
        s = A.evaluate("() => { clearInterval(window.__siv); const s=window.__s; return {n:s.length, overlay:s.filter(x=>x.o).length, blank:s.filter(x=>x.ink===0).length}; }"); dg_ = diag(A)
        ok(s["overlay"] == 0 and s["blank"] == 0, f"viewer overlay/blank frames: {s}"); ok(dg_["mounts"] <= 2 and dg_["docLoads"] <= 4, f"viewer lifecycle {dg_}")
        step("viewer", "viewer stayed visible through the run at 1800×732 with scrollbars", samples=s, lifecycle={k: dg_[k] for k in ("mounts", "unmounts", "docLoads", "renderStarts", "loadingFlashes")})

        # 375 px mobile
        M = b.new_context(viewport={"width": 375, "height": 812}); P = M.new_page(); P.goto(URL); P.wait_for_load_state("networkidle"); P.wait_for_selector("[data-testid=doc-viewer] canvas")
        P.get_by_role("button", name="Dismiss to inspect documents").click() if P.get_by_role("button", name="Dismiss to inspect documents").count() else None; P.wait_for_timeout(300); P.get_by_test_id("open-takeoff").click(); P.get_by_test_id("takeoff-review").wait_for(timeout=15000); P.wait_for_timeout(800)
        ov = P.evaluate("document.documentElement.scrollWidth - window.innerWidth"); ok(ov <= 1, f"375px overflow {ov}px")
        tw = P.evaluate("() => Math.max(...[...document.querySelectorAll('.takeoff .table-scroll')].map(t=>t.scrollWidth-t.clientWidth))"); P.screenshot(path=str(SHOTS / "takeoff_mobile_375.png"))
        step("mobile", "375px: Takeoff Review renders without page overflow (tables scroll inside their cards)", page_overflow_px=ov, widest_table_scroll_px=tw)
        real = [e for e in console_errors if "favicon" not in e.lower() and not re.search(r"status of 4(00|09|29)", e)]; ok(not real, f"console errors {real[:3]}")
        step("console", "no console errors"); b.close()
    REPORT.write_text(json.dumps({"steps": steps}, indent=1, default=str)); print("TAKEOFF REVIEW E2E PASS", len(steps), "step groups")

if __name__ == "__main__":
    main()

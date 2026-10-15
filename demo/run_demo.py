"""Scripted, timed rehearsal / recording of the 150-second Gatehouse demo against the REAL UI and proxy (no AMD call; stored model outputs only).
Modes:  functional  = fresh sessions built from scratch through the UI (no staging), unpaced, 1800x732, viewer sampler on
        timed       = pre-staged sessions A/B/C (demo/stage.py), paced to the scene budgets, 1920x1080, video recorded
        recovery    = 'Reset demo' on a used session, replay scenes 1-4, re-stage B/C, replay 5-6, 1800x732
Everything displayed comes from the app; the two caption/overlay elements injected by this harness (scene caption, 'actual API response' box) are labelled as harness overlays.
Usage: run_demo.py MODE [--out DIR] [--base URL]"""
import json, os, pathlib, re, sys, time
from decimal import Decimal as D
HERE = pathlib.Path(__file__).resolve().parent; WS = HERE.parent
sys.path.insert(0, str(WS / "e2e")); sys.path.insert(0, str(HERE))
from playwright.sync_api import sync_playwright
from e2e_common import URL, ok, api, dlg, usd
import e2e_footing as F
from e2e_dp001 import IDS, state, viewer_ready
import e2e_ai_bridge as AI
import stage as ST

DRW = IDS["drawings"]
BUDGET = [(1, "The project", 20), (2, "AMD intelligence — recorded, replayed offline", 25), (3, "The contradiction", 30), (4, "Humans retain authority", 25), (5, "Deterministic pricing", 30), (6, "Responsible release", 20)]
REF = {"BASE": D("54284.69"), "ALT-A1": D("45771.50")}     # accepted conditional reference outputs: COMPARED to what the engine returns, never injected
CAP_JS = """([t,s]) => { let e=document.getElementById('demo-caption'); if(!e){e=document.createElement('div'); e.id='demo-caption'; e.setAttribute('data-harness-overlay','caption');
  e.style.cssText='position:fixed;left:12px;bottom:12px;z-index:99999;max-width:560px;background:rgba(10,20,40,.92);color:#fff;font:600 15px system-ui;padding:10px 14px;border-radius:8px;pointer-events:none;box-shadow:0 2px 12px rgba(0,0,0,.4)'; document.body.appendChild(e);}
  e.innerHTML='<div style="font:11px monospace;opacity:.7">HARNESS CAPTION</div>'+t+(s?'<div style="font-weight:400;font-size:13px;margin-top:4px;opacity:.9">'+s+'</div>':''); }"""
API_JS = """(h) => { let e=document.getElementById('demo-api'); if(!e){e=document.createElement('div'); e.id='demo-api'; e.setAttribute('data-harness-overlay','api');
  e.style.cssText='position:fixed;left:50%;top:12px;transform:translateX(-50%);z-index:99999;width:min(780px,92vw);background:#fff;border:3px solid #b5382c;color:#2b0d09;font:13px/1.45 ui-monospace,monospace;padding:12px 16px;border-radius:8px;box-shadow:0 4px 20px rgba(0,0,0,.4)'; document.body.appendChild(e);} e.innerHTML=h; }"""

class Run:
    def __init__(self, mode, out, base):
        self.mode, self.out, self.times, self.notes, self.checks = mode, pathlib.Path(out), {}, [], []
        self.out.mkdir(parents=True, exist_ok=True); (self.out / "shots").mkdir(exist_ok=True); self.t_scene = None
    def shot(self, pg, name): pg.screenshot(path=str(self.out / "shots" / f"{name}.png"))
    def check(self, cond, msg): self.checks.append({"ok": bool(cond), "check": msg}); ok(cond, msg)
    def begin(self, n): self.t_scene = (n, time.perf_counter())
    def end(self, pg, pace=False):
        n, t0 = self.t_scene; b = dict((a, c) for a, _, c in BUDGET)[n]; active = time.perf_counter() - t0; el = active
        if pace and el < b: time.sleep(b - el); el = time.perf_counter() - t0
        self.times[n] = {"scene": dict((a, t) for a, t, _ in BUDGET)[n], "budget_s": b, "active_s": round(active, 1), "actual_s": round(el, 1), "within_budget": active <= b + 0.5}
        print(f"scene {n} {self.times[n]}", flush=True)
def cap(pg, t, s=""): pg.evaluate(CAP_JS, [t, s])
def hold(r, pg, sec): pg.wait_for_timeout(int(sec * 1000)) if r.mode == "timed" else pg.wait_for_timeout(250)

def use_state(ctx, pg, st, url):
    ctx.clear_cookies(); ctx.add_cookies(json.loads((HERE / os.environ.get("DEMO_STAGED", "staged") / f"{st}.json").read_text())["cookies"]); pg.goto(url); pg.wait_for_load_state("networkidle"); pg.wait_for_selector("[data-testid=doc-viewer] canvas"); pg.wait_for_timeout(700)

def scenes_1_to_4(r, pg, ctx, pace, fresh_select=False):
    pn = lambda: AI.panel(pg)
    # ---- 1 the project
    r.begin(1); cap(pg, "Scene 1 · The project", "Real synthetic DP-001 fencing package — not a production bid")
    sg = dlg(pg, "Scope Gate"); sg.wait_for(timeout=15000)
    for sh, n in (("G001", 1), ("C101", 2), ("C102", 3), ("F501", 4), ("F502", 5), ("C101", 2)):
        pg.get_by_role("tab", name=sh, exact=True).click(); viewer_ready(pg, DRW, n); hold(r, pg, 0.6)
    ok("DP-001" in pg.locator(".project-summary").inner_text(), "DP-001")
    if fresh_select: F.select_bid(pg, "base")
    sd = sg.get_by_test_id("scope-draft"); sd.scroll_into_view_if_needed(); r.check(sd.locator("article.draft-item:not(.rfi)").count() == 18 and "HUMAN-PREPARED" in sd.inner_text(), "scene1: five sheets + 18-item human-prepared scope draft"); hold(r, pg, 2); r.shot(pg, "s1_project_scope_review"); r.end(pg, pace)
    # ---- 2 AMD intelligence
    r.begin(2); cap(pg, "Scene 2 · AI Findings = stored AMD outputs, replayed offline", "No live inference. Provenance, model + run, independent verification, model confidence vs verified status")
    p = pn(); p.scroll_into_view_if_needed(); p.wait_for(); hold(r, pg, 1.5)
    ok("No AMD call is made by this build" in p.inner_text() and "Real AMD attempts recorded: 10" in p.get_by_test_id("ai-accounting").inner_text(), "offline replay labelled")
    det = AI.open_row(pg, "AMD-spatial003-N-gate_position-G3"); det.scroll_into_view_if_needed()
    r.check("spatial_003_r1_north_band_gates_and_tag" in det.inner_text() and "DeepSeek-V4.1-Flash" in det.inner_text() and "62ab61d7f2558245f4a6f1708d9320a49e66fd28bf829a2329be5b79db9ac525" in det.inner_text() and "label position only" in det.get_by_test_id("d-verify").inner_text(), "scene2: provenance, model+run, verification (label position only)")
    r.check("model: clear" in AI.row(pg, "AMD-spatial003-N-gate_position-G3").get_by_test_id("f-model-conf").inner_text(), "scene2: model confidence beside verification"); hold(r, pg, 4); r.shot(pg, "s2_ai_findings_provenance"); r.end(pg, pace)
    # ---- 3 the contradiction
    r.begin(3); cap(pg, "Scene 3 · The AI says “perimeter fence”, confidence: clear", "The drawing says otherwise")
    before = (state(pg)["scope_version"], len(state(pg)["audit"]), state(pg)["proposal_digest"])
    db = AI.open_row(pg, "AMD-spatial003-N-type_tag-B"); rb = AI.row(pg, "AMD-spatial003-N-type_tag-B")
    r.check(rb.get_by_test_id("f-origin").inner_text() == "AI CLAIM CONTRADICTED BY DRAWING EVIDENCE" and "model: clear" in rb.get_by_test_id("f-model-conf").inner_text() and "perimeter fence" in db.get_by_test_id("d-claim").inner_text(), "scene3: authentic Test 003 Type B finding, contradicted, model said clear")
    r.check("SIMULATED" not in db.inner_text().upper().replace("NOT SIMULATED", "") and AI.row(pg, "AMD-spatial003-N-type_tag-B").get_attribute("data-provenance") == "REAL_AMD_OUTPUT", "scene3: real AMD output, not simulated")
    rb.get_by_test_id("f-jump").click(); viewer_ready(pg, DRW, 2); hold(r, pg, 1)
    for _ in range(3): pg.get_by_label("Zoom in").click(); pg.wait_for_timeout(250); viewer_ready(pg, DRW, 2)
    mk = pg.get_by_test_id("viewer-mark"); r.check(mk.count() == 3, "scene3: diamond, leader end and terminal element outlined")
    pg.evaluate("""() => { const f=document.querySelector('.viewer-stage'); const ms=[...document.querySelectorAll('[data-testid=viewer-mark]')]; const fb=f.getBoundingClientRect();
        const xs=ms.map(m=>m.getBoundingClientRect()); const cx=(Math.min(...xs.map(b=>b.left))+Math.max(...xs.map(b=>b.right)))/2, cy=(Math.min(...xs.map(b=>b.top))+Math.max(...xs.map(b=>b.bottom)))/2;
        f.scrollLeft+=cx-(fb.left+fb.width/2); f.scrollTop+=cy-(fb.top+fb.height/2); }"""); pg.wait_for_timeout(500); hold(r, pg, 3); r.shot(pg, "s3_typeB_leader_endpoint_in_pdf")
    det_b = pn().get_by_test_id("ai-detail"); det_b.scroll_into_view_if_needed(); r.check(det_b.get_by_test_id("f-accept").is_disabled() and "CONTRADICTED_BY_DRAWING_EVIDENCE" in det_b.get_by_test_id("d-cannot").inner_text(), "scene3: UI refuses acceptance"); r.shot(pg, "s3_accept_blocked_in_ui")
    fid = "AMD-spatial003-N-type_tag-B"; res = pg.evaluate("""async (fid) => { const v=await (await fetch('/api/demo/ai-findings',{cache:'no-store'})).json(); const f=v.findings.find(x=>x.finding_id===fid);
        const r=await fetch('/api/demo/ai-findings/decision',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':'demo-b-'+Math.random().toString(36).slice(2,12)},body:JSON.stringify({finding_id:fid,decision:'accept',by:'Demo presenter',note:'attempting to accept the contradicted claim',preview_digest:f.preview.digest})});
        return {status:r.status, body: await r.json()}; }""", fid)
    after = (state(pg)["scope_version"], len(state(pg)["audit"]), state(pg)["proposal_digest"])
    r.check(res["status"] == 409 and res["body"]["code"] == "CONTRADICTED_BY_DRAWING_EVIDENCE", f"scene3: actual API refuses: {res['status']} {res['body'].get('code')}"); r.check(before == after, f"scene3: scope version / audit / digest unchanged {before} -> {after}")
    pg.evaluate(API_JS, [f"<div style='font-weight:700;color:#b5382c'>ACTUAL API RESPONSE (live call from this page, harness overlay)</div>POST /api/demo/ai-findings/decision accept → <b>HTTP {res['status']} {res['body'].get('code')}</b><br>{res['body'].get('error','')[:150]}…<br>Engine scope version v{before[0]} → v{after[0]} · audit events {before[1]} → {after[1]} · nothing changed"])
    hold(r, pg, 3); r.shot(pg, "s3_api_409_contradicted"); pg.evaluate("()=>document.getElementById('demo-api')?.remove()")
    r.end(pg, pace)
    for _ in range(3): pg.get_by_label("Zoom out").click(); pg.wait_for_timeout(250); viewer_ready(pg, DRW, 2)
    # ---- 4 humans retain authority
    r.begin(4); cap(pg, "Scene 4 · A permitted finding: the human decides", "The AI localized the G3 label. The 31 ft station is HUMAN-PREPARED. G3's gate size and footing stay an open RFI")
    d4 = AI.open_row(pg, "AMD-spatial002-0-gate_tag-G3-top"); AI.row(pg, "AMD-spatial002-0-gate_tag-G3-top").get_by_test_id("f-jump").click(); viewer_ready(pg, DRW, 2); sv = state(pg)["scope_version"]; pv = d4.get_by_test_id("d-preview"); pv.scroll_into_view_if_needed()
    t = pv.inner_text(); r.check(pv.get_attribute("data-kind") == "engine_resolve" and "31 ft" in t and "HUMAN-PREPARED" in t and f"v{sv} → v{sv + 1}" in t and "the AI supplied a plan side only" in t.lower().replace("The AI supplied a plan side only", "the AI supplied a plan side only") or "plan side only" in t, f"scene4: review preview shows the human-prepared value and version change: {t[:200]}")
    hold(r, pg, 2); r.shot(pg, "s4_review_preview_human_value")
    d4.get_by_label("AI decision name").fill("Contractor reviewer"); d4.get_by_label("AI decision note").fill("G3 tag is on the north fence line per C101; approving the human-prepared 31 ft station"); d4.get_by_test_id("f-accept").click(); d4.get_by_test_id("d-msg").wait_for(timeout=15000); pg.wait_for_timeout(500)
    s2 = state(pg); r.check(s2["scope_version"] == sv + 1, f"scene4: engine scope version v{sv} -> v{s2['scope_version']}"); r.check(AI.row(pg, "AMD-spatial002-0-gate_tag-G3-top").get_by_test_id("f-origin").inner_text() == "Human-approved", "scene4: label becomes Human-approved only after the human accepts")
    r.check(any("gates/2/clear_width_ft" in e["exception_id"] for e in s2["exceptions"] if e["severity"] == "blocking") and sum("GATE_G3" in e["exception_id"] for e in s2["exceptions"] if e["severity"] == "blocking") == 3, "scene4: G3 opening and footing facts remain unresolved")
    sg = dlg(pg, "Scope Gate"); g3 = sg.get_by_test_id("item-gate-g3"); g3.scroll_into_view_if_needed(); r.check("Unresolved: RFI required" in g3.get_by_test_id("item-status").inner_text(), "scene4: G3 draft item still 'Unresolved: RFI required'")
    pg.evaluate("()=>document.querySelector('[data-testid=viewer-slot],.viewer-slot')?.scrollIntoView()"); hold(r, pg, 2); r.shot(pg, "s4_scope_version_changed_g3_unresolved"); r.end(pg, pace)
    return {"scope_version_before": sv, "scope_version_after": s2["scope_version"]}

def scenes_5_6(r, pgB, pace, release=True):
    out = {}
    # ---- 5 deterministic pricing (session B = Base, session C = Alternate)
    r.begin(5); cap(pgB, "Scene 5 · Code calculates", "Engine-generated quantities and prices under the explicitly self-declared G3 what-if and the reference CR13 crew plan")
    pgB.wait_for_timeout(600); d = F.open_takeoff(pgB); fb = d.get_by_test_id("footings-base"); fb.scroll_into_view_if_needed()
    rows = {pc: fb.get_by_test_id(f"class-{pc}").get_by_test_id("count").inner_text().strip().split("\n")[0] for pc in ("A_LINE", "A_CORNER_TERMINAL", "B_LINE", "B_TERMINAL")}; hb = int(fb.get_by_test_id("holes-total").inner_text())
    r.check(hb == 79 and "16″" in fb.get_by_test_id("class-A_CORNER_TERMINAL").inner_text() and "8″ × 30″" in fb.get_by_test_id("class-B_LINE").inner_text(), f"scene5: Base 79 provisional holes; Type A vs Type B classes {rows}"); hold(r, pgB, 2.5); r.shot(pgB, "s5_takeoff_base_type_a_vs_b")
    d.get_by_test_id("tab-alt").click(); pgB.wait_for_timeout(400); ha = int(d.get_by_test_id("footings-alt").get_by_test_id("holes-total").inner_text()); r.check(ha == 63, "scene5: Alternate A-1 63 provisional holes"); d.get_by_test_id("footings-alt").scroll_into_view_if_needed(); hold(r, pgB, 2); r.shot(pgB, "s5_takeoff_alternate_63_holes")
    d.get_by_test_id("tab-base").click(); eng = d.get_by_test_id("engine-total").inner_text(); out["engine_total_base_shown"] = eng
    r.check(usd(eng) == REF["BASE"], f"scene5: engine Base total {eng} equals the accepted conditional reference (compared, not injected)"); F.close_takeoff(pgB)
    s0 = state(pgB); dig0 = s0["proposal_digest"]
    # crew comparison (planner preview only; nothing is approved)
    pgB.get_by_role("button", name=re.compile("Revise crew plan")).first.click() if pgB.get_by_role("button", name=re.compile("Revise crew plan")).count() else None
    if not dlg(pgB, "Labor Gate").count(): pgB.get_by_role("button", name=re.compile("Review required")).click(); dlg(pgB, "Release Gate").wait_for(); dlg(pgB, "Release Gate").get_by_role("button", name=re.compile("Revise crew plan")).click()
    dl = dlg(pgB, "Labor Gate"); dl.wait_for(timeout=10000); pgB.wait_for_timeout(800); tot = {}
    elig = sorted({x.get_attribute("data-crew") for x in dl.locator('button[data-task="L01"][data-eligible="true"]').all()}); r.check(len(elig) == 4, f"scene5: four eligible crews {elig}")
    for c in elig: dl.get_by_label("Preferred crew").select_option(value=c); F.settle(pgB); tot[c] = str(usd(pgB.get_by_test_id("draft-total").inner_text())); hold(r, pgB, 0.6)
    dl.get_by_label("Preferred crew").select_option(value="CR13"); F.settle(pgB); hold(r, pgB, 1.2); r.shot(pgB, "s5_four_crew_comparison"); out["crew_preview_totals"] = tot
    r.check(len(set(tot.values())) >= 3, f"scene5: the crew choice changes the engine price {tot}")
    s1 = state(pgB); r.check(s1["proposal_digest"] == dig0 and s1["status"] == "ready_for_final_review", "scene5: previewing crews did not change the approved plan or digest")
    r.end(pgB, pace)
    # ---- 6 responsible release
    r.begin(6); cap(pgB, "Scene 6 · Humans authorize — and the engine classifies", "NOT BID READY — FICTIONAL DEMONSTRATION ONLY")
    pgB.get_by_role("button", name=re.compile("Dismiss to inspect documents")).click() if pgB.get_by_role("button", name=re.compile("Dismiss to inspect documents")).count() else None; pgB.wait_for_timeout(300)
    pgB.get_by_role("button", name=re.compile("Review required")).click(); rd = dlg(pgB, "Release Gate"); rd.wait_for(); pgB.wait_for_timeout(800)
    b = F.readiness(rd, F.HEAD_DEMO); rd.get_by_test_id("readiness-banner").scroll_into_view_if_needed(); hold(r, pgB, 3); r.shot(pgB, "s6_release_gate_not_bid_ready")
    r.check(usd(rd.get_by_test_id("est-price_total").inner_text()) == REF["BASE"], "scene6: release total is the engine total"); out["readiness_before_release"] = b
    rd.get_by_test_id("takeoff-release").scroll_into_view_if_needed(); hold(r, pgB, 2.5)
    if release:
        rd.get_by_placeholder("Any name; recorded as self-declared").fill("Contractor reviewer"); rd.get_by_test_id("ack-qualified").check()
        rd.get_by_role("button", name=re.compile("Record QUALIFIED demonstration release")).click(); pgB.get_by_text("Recorded by the engine").first.wait_for(timeout=15000); pgB.wait_for_timeout(900)
        if not pgB.locator("[role=dialog]").count(): pgB.get_by_role("button", name=re.compile("View release record")).click(); pgB.wait_for_timeout(800)
        rr = dlg(pgB, "Release Gate"); out["readiness_after_release"] = F.readiness(rr, F.HEAD_DEMO, artifact="QUALIFIED_FICTIONAL_DEMONSTRATION"); rr.get_by_test_id("readiness-banner").scroll_into_view_if_needed(); r.shot(pgB, "s6_release_record_artifact_kind")
        r.check(pgB.get_by_test_id("status-demo").first.is_visible(), "scene6: status says Demonstration release · NOT a bid")
    cap(pgB, "“The AI can be wrong. The estimate doesn’t have to be.”", "AI interprets · Code calculates · Humans authorize"); hold(r, pgB, 2.5); r.end(pgB, pace)
    return out

def main():
    mode = sys.argv[1]; out = pathlib.Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else HERE / f"rehearsal_{mode}"; r = Run(mode, out, URL); res = {"mode": mode, "url": URL}
    vp = {"width": 1920, "height": 1080} if mode == "timed" else {"width": 1800, "height": 732}
    ext, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, ignore_default_args=["--hide-scrollbars"])
        kw = {"viewport": vp}
        if mode == "timed": kw.update(record_video_dir=str(out / "video"), record_video_size=vp)
        ctx = b.new_context(**kw); pg = ctx.new_page(); pg.add_init_script("localStorage.setItem('pdfDiag','1')")
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None); pg.on("pageerror", lambda e: errs.append("PAGEERROR " + str(e)))
        pg.on("request", lambda q: ext.append(q.url) if not q.url.startswith(URL.rstrip("/")) and not q.url.startswith(("data:", "blob:")) else None)
        t_all = time.perf_counter()
        if mode == "functional":      # genuinely fresh: no stored state, nothing pre-selected, B and C built through the UI
            pg.goto(URL); pg.wait_for_load_state("networkidle"); pg.wait_for_selector("[data-testid=doc-viewer] canvas"); r.check(len(state(pg)["audit"]) == 1, "fresh project, no stale browser state"); pg.evaluate(F.SAMPLER)
            res["scenes_1_4"] = scenes_1_to_4(r, pg, ctx, False, fresh_select=True)
            seg = pg.evaluate("() => { const s=window.__s||[]; return {n:s.length, overlay:s.filter(x=>x.o).length, blank:s.filter(x=>x.ink===0).length}; }"); r.check(seg["overlay"] == 0 and seg["blank"] == 0, f"C101 viewer: no flashing frames {seg}"); res["viewer_samples"] = seg
            cB = b.new_context(viewport=vp); pB = cB.new_page(); pB.goto(URL); pB.wait_for_load_state("networkidle"); pB.wait_for_selector("[data-testid=doc-viewer] canvas"); ST.stage_priced(pB, "base")
            res["scenes_5_6"] = scenes_5_6(r, pB, False)
        else:
            if mode == "recovery":    # use the (already used) staged A project, then Reset demo
                use_state(ctx, pg, "A", URL); pg.get_by_role("button", name="Reset demo").first.click(); pg.get_by_text("Demo reset").first.wait_for(); pg.wait_for_timeout(1000); r.check(len(state(pg)["audit"]) == 1, "reset produced a fresh project"); dlg(pg, "Scope Gate").wait_for(timeout=20000)
            else: use_state(ctx, pg, "A", URL)
            pg.evaluate(F.SAMPLER); res["scenes_1_4"] = scenes_1_to_4(r, pg, ctx, mode == "timed", fresh_select=(mode == "recovery"))
            seg = pg.evaluate("() => { const s=window.__s||[]; return {n:s.length, overlay:s.filter(x=>x.o).length, blank:s.filter(x=>x.ink===0).length}; }"); r.check(seg["overlay"] == 0 and seg["blank"] == 0, f"C101 viewer: no flashing frames {seg}"); res["viewer_samples"] = seg
            if mode == "recovery":
                import subprocess; subprocess.run([sys.executable, str(HERE / "stage.py"), "B"], check=True, capture_output=True)
            use_state(ctx, pg, "B", URL); res["scenes_5_6"] = scenes_5_6(r, pg, mode == "timed")
            if mode == "timed":    # Alternate A-1 window (session C)
                use_state(ctx, pg, "C", URL); pg.get_by_role("button", name=re.compile("Dismiss to inspect documents")).click() if pg.get_by_role("button", name=re.compile("Dismiss to inspect documents")).count() else None
                pg.get_by_role("button", name=re.compile("Review required")).click(); rc = dlg(pg, "Release Gate"); rc.wait_for(); pg.wait_for_timeout(800); alt = usd(rc.get_by_test_id("est-price_total").inner_text()); res["alternate_total_shown"] = str(alt)
                r.check(alt == REF["ALT-A1"], f"alternate window: engine Alternate A-1 total {alt} equals the accepted conditional reference"); r.shot(pg, "s5_alternate_release_total")
        res["total_wall_s"] = round(time.perf_counter() - t_all, 1)
        ext = [u for u in ext if not u.startswith(("https://fonts.googleapis.com/", "https://fonts.gstatic.com/"))]; r.check(not ext and not any("amd" in u.lower() for u in ext), f"no external/AMD requests {ext[:2]}")
        real = [e for e in errs if "favicon" not in e.lower() and not re.search(r"status of 4(00|09|29)", e)]; r.check(not real, f"no console errors {real[:2]}")
        ctx.close(); b.close()
    res["scene_times"] = r.times; res["scene_total_s"] = round(sum(v["actual_s"] for v in r.times.values()), 1); res["checks"] = r.checks; res["external_requests"] = len(ext)
    (out / "result.json").write_text(json.dumps(res, indent=1, default=str)); print(json.dumps({"mode": mode, "scene_times": {k: v["actual_s"] for k, v in r.times.items()}, "scene_total_s": res["scene_total_s"], "checks_ok": all(c["ok"] for c in r.checks), "n_checks": len(r.checks)}))

if __name__ == "__main__":
    main()

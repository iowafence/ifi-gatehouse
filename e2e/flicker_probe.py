"""Lifecycle/network probe for the PDF viewer (needs the opt-in diagnostics: localStorage.pdfDiag=1, set here).
Opens G001 and watches for N seconds with classic (visible) scrollbars, as a real browser has. Reports component mounts, render starts,
loading overlays, canvas size changes (a resized canvas is cleared = a blank frame), PDF requests and ResizeObserver events.
Usage: flicker_probe.py LABEL SECONDS WIDTH HEIGHT"""
import json, sys, time
from playwright.sync_api import sync_playwright
from e2e_common import URL
label = sys.argv[1] if len(sys.argv) > 1 else "probe"; secs = int(sys.argv[2]) if len(sys.argv) > 2 else 15
W = int(sys.argv[3]) if len(sys.argv) > 3 else 1800; H = int(sys.argv[4]) if len(sys.argv) > 4 else 1100
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, ignore_default_args=["--hide-scrollbars"])
    c = b.new_context(viewport={"width": W, "height": H}); pg = c.new_page()
    pg.add_init_script("localStorage.setItem('pdfDiag','1')")
    reqs = []; pg.on("request", lambda r: reqs.append(r.url.split("/api/demo/")[-1]) if "/documents/" in r.url else None)
    pg.goto(URL); pg.wait_for_load_state("networkidle"); pg.wait_for_selector("[data-testid=doc-viewer] canvas")
    pg.get_by_role("tab", name="G001", exact=True).click(); pg.wait_for_timeout(1500)
    pg.evaluate("""() => { window.__samples=[]; window.__iv=setInterval(()=>{ const c=document.querySelector('[data-testid=doc-viewer] canvas');
        window.__samples.push({w:c?c.width:0, o:!!document.querySelector('.viewer-overlay')}); },50); }""")
    base = pg.evaluate("() => ({...window.__pdfDiag, events: undefined})")
    time.sleep(secs)
    r = pg.evaluate("() => { clearInterval(window.__iv); const s=window.__samples; let changes=0; for(let i=1;i<s.length;i++) if(s[i].w!==s[i-1].w) changes++;"
                    " return {samples:s.length, overlay_frames:s.filter(x=>x.o).length, canvas_size_changes:changes, distinct_widths:[...new Set(s.map(x=>x.w))].length, diag:window.__pdfDiag}; }")
    d = r["diag"]
    out = {"label": label, "viewport": f"{W}x{H}", "watch_seconds": secs, "pdf_requests_total": len(reqs), "samples_50ms": r["samples"],
           "frames_with_loading_overlay": r["overlay_frames"], "canvas_size_changes": r["canvas_size_changes"],
           "during_watch": {k: d[k] - base[k] for k in ("mounts", "unmounts", "renderStarts", "renderDone", "cancelled", "loadingFlashes", "resizes", "docLoads")}}
    print(json.dumps(out)); b.close()

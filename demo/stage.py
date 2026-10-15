"""Pre-stages the browser sessions the 150-second demo uses, through the REAL UI and proxy (nothing is injected into the engine):
  A  fresh DP-001 project at the Scope gate with the Base Bid selected
  B  Base Bid, all derivations approved, explicit fictional G3 what-if, ruleset+wage+crew plan (CR13), takeoff review recorded -> waiting at the Release gate
  C  Alternate A-1, same path
Each session is a signed cookie for its own engine project; storage states are written to demo/staged/. Re-run to re-stage (about 60-90 s each). Usage: stage.py [A] [B] [C]"""
import json, os, pathlib, sys, time
HERE = pathlib.Path(__file__).resolve().parent; WS = HERE.parent; STAGED = os.environ.get("DEMO_STAGED", "staged"); (HERE / STAGED).mkdir(exist_ok=True)
sys.path.insert(0, str(WS / "e2e"))
from playwright.sync_api import sync_playwright
from e2e_common import URL, ok, dlg, usd
import e2e_footing as F
from e2e_dp001 import state

def new_fresh(b):
    ctx = b.new_context(viewport={"width": 1800, "height": 732}); pg = ctx.new_page(); pg.goto(URL); pg.wait_for_load_state("networkidle"); pg.wait_for_selector("[data-testid=doc-viewer] canvas")
    st = state(pg); ok(st["status"] == "needs_scope_review" and len(st["audit"]) == 1, "fresh project"); return ctx, pg

def stage_priced(pg, bid):
    F.select_bid(pg, bid); F.approve_all_inferred(pg)
    pg.get_by_role("button", name="Dismiss to inspect documents").click() if pg.get_by_role("button", name="Dismiss to inspect documents").count() else None
    d = F.open_takeoff(pg); d.get_by_label("What-if name").fill("Demo presenter"); d.get_by_test_id("apply-whatif").click(); d.get_by_test_id("whatif-applied").wait_for(timeout=25000); pg.wait_for_timeout(500); F.close_takeoff(pg)
    F.open_gate(pg); dl = F.do_labor(pg, "demo"); rd = F.approve_plan(pg, dl, "CR13 preferred and drilling (reference crew plan)"); pg.wait_for_timeout(800)
    pg.get_by_test_id("open-takeoff").click(); d = dlg(pg, "Takeoff Review"); d.get_by_test_id("takeoff-review").wait_for(timeout=15000); pg.wait_for_timeout(400)
    d.get_by_label("Takeoff reviewer name").fill("Demo presenter"); d.get_by_label("Takeoff review note").fill("Reviewed the per-class schedule against C101/F501; geometry provisional")
    d.get_by_role("button", name="Record takeoff review").click(); pg.get_by_test_id("att-msg").wait_for(); pg.wait_for_timeout(500); F.close_takeoff(pg)
    s = state(pg); ok(s["status"] == "ready_for_final_review", s["status"]); return s

def main():
    want = [a.upper() for a in sys.argv[1:]] or ["A", "B", "C"]; facts = {}
    ff = HERE / STAGED / "staged_facts.json"; facts = json.loads(ff.read_text()) if ff.exists() else {}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, ignore_default_args=["--hide-scrollbars"])
        for name in want:
            t0 = time.time(); ctx, pg = new_fresh(b)
            if name == "A":
                F.select_bid(pg, "base"); s = state(pg); facts["A"] = {"project_id": s["project_id"], "scope_version": s["scope_version"], "status": s["status"], "bid": "base"}
            else:
                s = stage_priced(pg, "base" if name == "B" else "ALT-A1"); ev = s["pricing"]["estimate_view"]
                facts[name] = {"project_id": s["project_id"], "scope_version": s["scope_version"], "status": s["status"], "scope_ref": ev["scope_ref"], "engine_price_total": ev["price_total"], "proposal_digest": s["proposal_digest"], "crew_plan": "CR13 preferred / CR13 drilling"}
            ctx.storage_state(path=str(HERE / STAGED / f"{name}.json")); (HERE / STAGED / f"{name}.json").chmod(0o600); facts[name]["staged_seconds"] = round(time.time() - t0, 1); facts[name]["staged_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            print(name, json.dumps(facts[name]), flush=True); ctx.close()
        b.close()
    ff.write_text(json.dumps(facts, indent=1))

if __name__ == "__main__":
    main()

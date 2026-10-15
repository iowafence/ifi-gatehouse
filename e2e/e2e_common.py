"""Shared helpers for the Pass 6 integration browser checks (headless Chromium via Playwright, no browser extension).
Everything goes through the real frontend proxy routes on http://127.0.0.1:5071 -- never straight to the engine, except one
read-only engine summary used to learn which internal hash strings must NOT reach the browser."""
import json, pathlib, re, os
from decimal import Decimal

import os
URL = os.environ.get("DEMO_URL", "http://127.0.0.1:5071/")
WS = pathlib.Path(__file__).resolve().parent.parent
STATE_DIR = WS / "run"
SHOTS = WS / "evidence/screenshots"

def ok(c, m):
    if not c: raise AssertionError(m)

def state_path(name): return STATE_DIR / f"e2e_state_{name}.json"

def new_context(browser, name, **kw):
    sp = state_path(name)
    if sp.exists():
        try: return browser.new_context(storage_state=str(sp), **kw)
        except Exception: pass
    return browser.new_context(**kw)

def save_state(ctx, name):
    ctx.storage_state(path=str(state_path(name))); state_path(name).chmod(0o600)

def usd(text):
    m = re.search(r"-?\$([\d,]+\.\d{2})", text); ok(m, f"no dollar amount in {text!r}")
    return Decimal(m.group(1).replace(",", ""))

def num(text):
    m = re.search(r"-?[\d,]+\.?\d*", text); ok(m, f"no number in {text!r}")
    return Decimal(m.group(0).replace(",", ""))

def api(pg, path, body=None, headers=None):
    """GET when body is None, else POST JSON. Returns status, parsed body and the (lower-cased) response headers."""
    return pg.evaluate("""async ([p,b,h]) => { const init = b===null ? {cache:'no-store'} : {method:'POST',headers:{'Content-Type':'application/json',...(h||{})},body:JSON.stringify(b)};
        const r = await fetch(p, init); const hd = {}; r.headers.forEach((v,k)=>{hd[k]=v});
        return {status:r.status, body: await r.json().catch(()=>null), headers: hd}; }""", [path, body, headers])

def dlg(pg, name): return pg.get_by_role("dialog", name=name)

def engine_summary(pid):
    """Read-only engine summary (needs the engine env, which is never printed)."""
    import urllib.request
    env = dict(l.strip().split("=", 1) for l in (STATE_DIR / "engine.env").read_text().splitlines() if "=" in l and not l.startswith("#"))
    key = env.get("ENGINE_API_KEY") or env.get("GATEHOUSE_ENGINE_API_KEY") or next((v for k, v in env.items() if "KEY" in k), "")
    return key

def ensure_pristine(pg):
    pg.goto(URL); pg.wait_for_load_state("networkidle")
    st = api(pg, "/api/demo/state")["body"]["project"]
    if not (st["status"] == "needs_scope_review" and len(st["audit"]) == 1 and not (st.get("pricing") or {}).get("crew_plan")):
        pg.get_by_role("button", name="Reset demo").first.click(); pg.get_by_text("Demo reset").first.wait_for(); pg.wait_for_timeout(600)

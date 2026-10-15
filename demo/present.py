"""Opens the pre-staged demo sessions as three headed browser windows for a LIVE presentation (separate, isolated browser contexts; no stale state).
  Window A  fresh project at the Scope gate (Base Bid selected)        -> scenes 1-4
  Window B  Base Bid priced, takeoff reviewed, waiting at Release gate  -> scenes 5-6
  Window C  Alternate A-1 priced, waiting at Release gate               -> Alternate total in scene 5
Usage: DEMO_URL=http://127.0.0.1:5071/ DEMO_STAGED=staged python3 demo/present.py      (Enter in this terminal closes the windows)
Use a SEPARATE browser profile from any manual tab on the same host: cookies are shared across ports on 127.0.0.1."""
import json, os, pathlib, sys
from playwright.sync_api import sync_playwright
HERE = pathlib.Path(__file__).resolve().parent; URL = os.environ.get("DEMO_URL", "http://127.0.0.1:5071/"); ST = os.environ.get("DEMO_STAGED", "staged")
with sync_playwright() as p:
    b = p.chromium.launch(headless=False, ignore_default_args=["--hide-scrollbars"], args=["--window-size=1920,1080"]); pages = {}
    for i, n in enumerate("ABC"):
        f = HERE / ST / f"{n}.json"
        if not f.exists(): print(f"missing {f}: run demo/stage.py first"); continue
        ctx = b.new_context(storage_state=str(f), viewport={"width": 1920, "height": 1000}); pg = ctx.new_page(); pg.goto(URL); pages[n] = pg
    print("Windows open:", ", ".join(pages), "| A=scenes 1-4, B=scenes 5-6 (Base), C=Alternate. Press Enter to close."); input()
    b.close()

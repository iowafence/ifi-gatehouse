"""Browser proof of the audit trust boundary (real Chromium) against a container whose audit directory holds a TAMPERED copy of the corrected audit
(only I2 changed to SUPPORTED; every run/trace/case/document/quote binding intact). Start it with hosting/run-local.sh using AUDIT_HOST_DIR (TEST ONLY).
EXPECTED: the audit is rejected, NOTHING is cleared (no active shortlist, D2 never actionable), and the screen says why. OFFLINE and READ-ONLY (GET only).
DEMO_URL is REQUIRED (the frozen demo's ports are refused). Screenshot: FR_SCREENSHOT."""
import json, os, pathlib, re, sys
from playwright.sync_api import sync_playwright
from e2e_common import ok

URL = os.environ.get("DEMO_URL", "").rstrip("/")
if not URL or re.search(r":(5071|5051)\b", URL): sys.exit("DEMO_URL is required and must not be the frozen demo")
OK_TRACE = os.environ.get("FR_OK_TRACE", "GH-TRACE-06b4b6d525133f8a"); CASES = os.environ.get("FR_CASES", "GH-CASE-5131630cf9d1,GH-CASE-b661ad38637b").split(",")
SHOT = pathlib.Path(os.environ.get("FR_SCREENSHOT", "/tmp/audit_tamper.png"))

def main():
    console, external, writes = [], [], []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, ignore_default_args=["--hide-scrollbars"]); A = b.new_context(viewport={"width": 1800, "height": 900}).new_page()
        A.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
        A.on("request", lambda r: external.append(r.url) if not r.url.startswith(URL) and not r.url.startswith(("data:", "blob:", "https://fonts.googleapis.com/", "https://fonts.gstatic.com/")) else None)
        A.on("request", lambda r: writes.append((r.method, r.url)) if r.method not in ("GET", "HEAD") else None)
        A.goto(URL + "/"); A.wait_for_load_state("networkidle"); A.wait_for_selector("[data-testid=doc-viewer] canvas")
        A.locator("[data-testid=open-flight-recorder]:visible").first.click(); d = A.get_by_test_id("flight-recorder"); d.wait_for(); A.get_by_test_id("fr-notice").wait_for(timeout=15000); A.wait_for_timeout(300)
        X = d.get_by_test_id("fr-selected"); ok(X.get_by_test_id("fr-exec-id").inner_text() == OK_TRACE, "the successful execution is selected")
        ok(X.get_by_test_id("fr-audit-unverifiable").count() == 1 and "could not be authenticated" in X.get_by_test_id("fr-audit-unverifiable").inner_text(), "the screen says the audit evidence could not be authenticated")
        ok(X.get_by_test_id("fr-shortlist").count() == 0, "NO active shortlist: unauthenticated audit evidence clears nothing, not even D1")
        ok(X.get_by_test_id("fr-audit").count() == 0 and X.get_by_test_id("fr-g3-scope").count() == 0 and X.get_by_test_id("fr-clarifications").count() == 0, "no audit provenance, G3 scope or clarification is presented as authenticated")
        ok(X.get_by_test_id("fr-flagged-section").count() == 0, "the tampered 'SUPPORTED' is not shown anywhere as an assessment")
        U = X.get_by_test_id("fr-unaudited"); cards = U.get_by_test_id("fr-case"); ok(cards.count() == 2, "both cases are in the 'not cleared' group")
        for i in range(cards.count()):
            c = cards.nth(i); ok(c.get_attribute("data-assessment") == "AUDIT_UNVERIFIABLE" and "NOT CLEARED" in c.get_by_test_id("fr-flag").inner_text(), f"{c.get_attribute('data-case-id')} NOT CLEARED")
            ok(c.get_by_test_id("fr-assess-pill").inner_text() == "AUDIT RECORD COULD NOT BE VERIFIED" and "NONE RECORDED" in c.get_by_test_id("fr-assure-human").inner_text(), "assurance row: unverified; human authorization none")
        ok(sorted(c.get_attribute("data-case-id") for c in cards.all()) == sorted(CASES), "the same two cases, original text preserved")
        pills = X.get_by_test_id("fr-issues").locator("li").evaluate_all("l=>l.map(x=>[x.textContent.slice(0,2),x.dataset.assessment])"); ok(pills == [["I1", "AUDIT_UNVERIFIABLE"], ["I2", "AUDIT_UNVERIFIABLE"], ["I3", "AUDIT_UNVERIFIABLE"]], f"issue assessments {pills}")
        src = d.get_by_test_id("fr-sources").inner_text(); ok("REJECTED" in src and "differ from the digest pinned in the release manifest" in src and "AUDIT-GH-RUN-e5bbcecef551-2.json" in src, "trace-file list names the rejection and why")
        ok("Original validator" in X.get_by_test_id("fr-validator").inner_text() or "original result, unchanged" in X.get_by_test_id("fr-validator").inner_text(), "the original validator result is still shown unchanged")
        U.scroll_into_view_if_needed(); A.wait_for_timeout(200); d.screenshot(path=str(SHOT))
        ok(not writes and not external, f"GET only, no external call: {writes} {external}")
        ok(not [m for m in console if "fonts" not in m.lower() and "ERR_NETWORK_CHANGED" not in m], f"console errors: {console}")
        b.close()
    print("AUDIT TAMPER E2E PASS")

if __name__ == "__main__": main()

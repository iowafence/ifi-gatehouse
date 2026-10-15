"""Live Evolus execution + pending-review RFI cases in the Flight Recorder (real browser, Chromium) against a running hosting-candidate container.
OFFLINE and READ-ONLY: no Evolus or AMD request is made; every request the page makes while the recorder is open must be a GET to the same origin, and the project's
status, scope version, audit trail and price/quantity totals must be identical before and after. DEMO_URL is REQUIRED (the frozen demo's ports are refused).
Expected data (env, defaults = ANVIL 2's first genuine run): FR_OK_TRACE, FR_FAIL_TRACE, FR_EXEC_ID, FR_CASES (comma list). Screenshot: FR_SCREENSHOT."""
import json, os, pathlib, re, sys
from playwright.sync_api import sync_playwright
from e2e_common import ok, api
from e2e_dp001 import state

URL = os.environ.get("DEMO_URL", "").rstrip("/")
if not URL or re.search(r":(5071|5051)\b", URL): sys.exit("DEMO_URL is required and must not be the frozen demo")
OK_TRACE = os.environ.get("FR_OK_TRACE", "GH-TRACE-06b4b6d525133f8a"); FAIL_TRACE = os.environ.get("FR_FAIL_TRACE", "GH-TRACE-2b2a7a1397a9599b")
EXEC_ID = os.environ.get("FR_EXEC_ID", "a161a9f6-0bc8-f111-bf5b-000d3aae6dc8")
CASES = os.environ.get("FR_CASES", "GH-CASE-5131630cf9d1,GH-CASE-b661ad38637b").split(",")
SHOT = pathlib.Path(os.environ.get("FR_SCREENSHOT", "/tmp/evolus_cases.png"))
steps = []
def step(n, t, **ev): steps.append(n); print(f"[{n}] {t} {json.dumps(ev, default=str)[:260]}", flush=True)
def lay(X, n): return X.get_by_test_id(f"fr-layer-{n}")

def main():
    console, external, writes = [], [], []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, ignore_default_args=["--hide-scrollbars"])
        A = b.new_context(viewport={"width": 1800, "height": 900}).new_page()
        A.on("console", lambda m: console.append(m.text) if m.type == "error" else None); A.on("pageerror", lambda e: console.append("PAGEERROR " + str(e)))
        A.on("request", lambda r: external.append(r.url) if not r.url.startswith(URL) and not r.url.startswith(("data:", "blob:", "https://fonts.googleapis.com/", "https://fonts.gstatic.com/")) else None)
        A.goto(URL + "/"); A.wait_for_load_state("networkidle"); A.wait_for_selector("[data-testid=doc-viewer] canvas")
        before = state(A); totals_before = A.locator(".plan-totals").inner_text() if A.locator(".plan-totals").count() else ""
        A.on("request", lambda r: writes.append((r.method, r.url)) if r.method not in ("GET", "HEAD") else None)  # from here on: the recorder only

        A.locator("[data-testid=open-flight-recorder]:visible").first.click(); d = A.get_by_test_id("flight-recorder"); d.wait_for(); A.get_by_test_id("fr-notice").wait_for(timeout=15000); A.wait_for_timeout(300)

        # 1. the successful execution is selected by default, and is its own run
        X = d.get_by_test_id("fr-selected")
        ok(X.get_by_test_id("fr-exec-id").inner_text() == OK_TRACE, f"newest execution selected: {X.get_by_test_id('fr-exec-id').inner_text()}")
        ok(X.locator(".fr-exec-head [data-testid=fr-state-RECORDED]").count() == 1, "outcome RECORDED")
        ok(lay(X, "evolus").locator(".fr-layer-head [data-testid=fr-state-RECORDED]").count() == 1, "Evolus RECORDED")
        for n in ("amd", "gemma"):
            ok(lay(X, n).locator(".fr-layer-head [data-testid=fr-state-NOT_REPORTED]").count() == 1 and lay(X, n).locator("details.fr-event").count() == 0, f"{n} NOT_REPORTED, no events")
        ev = lay(X, "evolus").locator("details.fr-event").first; ev.locator("summary").click(); A.wait_for_timeout(150)
        ok(ev.get_by_test_id("fr-field-workflow_execution_id").inner_text() == EXEC_ID, "the real workflow execution id is shown")
        ok(re.search(r"sha256 [0-9a-f]{10}…[0-9a-f]{6}", ev.get_by_test_id("fr-source").inner_text()) is not None and "evolus_runs/" in ev.get_by_test_id("fr-source").inner_text(), "source record and hash shown")
        xt = X.inner_text()
        ok(not re.search(r"Gemma-4-31B|DeepSeek|r2_east|Qwen", xt), "no historical or configured-model text inside the execution")
        ok(not re.search(r"token|gpu|retriev", lay(X, "evolus").inner_text(), re.I), "no token, GPU or retrieval value shown for Evolus")
        step(1, "Successful execution selected by default: RECORDED, real execution id, AMD/Gemma NOT_REPORTED", execution_id=EXEC_ID)

        # 2. validator outcome (original, unchanged) + corrected drop explanation + audit provenance
        V = X.get_by_test_id("fr-validator")
        ok(V.get_by_test_id("fr-validator-status").inner_text() == "COMPLETED_VALID" and "matches the hash in the trace" in V.inner_text(), "original validator outcome with verified run record")
        ok("does not mean the conclusions are supported" in V.inner_text(), "validator box says structural validity is not semantic support")
        vc = V.get_by_test_id("fr-validator-counts").inner_text()
        ok("3 issues accepted" in vc and "2 RFI drafts" in vc and "6 package entries omitted before submission" in vc, f"counts: {vc}")
        ok("unchanged during the run (as recorded)" in vc, "project state hash unchanged, as recorded")
        dr = X.get_by_test_id("fr-drops").inner_text()
        ok("“human”" in dr and "not a registered Gatehouse document" in dr and "EXCERPT_NOT_FOUND_IN_SOURCE_PDF_TEXT" in dr and "(a generic code)" in dr, f"drops: computed facts and the original code: {dr[:200]}")
        ok("Audit correction (AUDIT-GH-RUN-e5bbcecef551-2)" in dr and "human-prepared" in dr.lower() and "not PDF quotations that failed text verification" in dr, "corrected six-drop explanation, attributed to the audit record")
        ok("failed to verify" not in dr.lower() and "not found in the source pdf" not in dr.lower(), "the old explanation is gone")
        AU = X.get_by_test_id("fr-audit"); at = AU.inner_text()
        ok("LOOM" in at and "independent report" in at and "AUDIT-GH-RUN-e5bbcecef551-2" in at and re.search(r"sha256 [0-9a-f]{10}…[0-9a-f]{6}", at), "audit provenance: auditor, explicit source (LOOM's own report), additive record id and hash")
        pn = AU.get_by_test_id("fr-audit-pinned").inner_text()
        ok("Pinned by this release" in pn and "d6040e169d…" in pn and "does not prove who wrote it" in pn and "never treated as proof" in pn and "LOOM-GH-RUN-e5bbcecef551-remediation-recheck.md" in pn, f"trust boundary stated honestly on screen: {pn[:140]}")
        sp = AU.get_by_test_id("fr-audit-superseded").inner_text(); ok("AUDIT-GH-RUN-e5bbcecef551-1" in sp and "1e4f1c196c…" in sp and "retained unchanged" in sp and "applied Addendum 01 item 1.5 to G3" in sp, "the earlier audit is shown as superseded and retained")
        G = X.get_by_test_id("fr-g3-scope"); gi = {i.get_attribute("data-item"): i.get_attribute("data-status") for i in G.get_by_test_id("fr-g3-item").all()}
        ok(gi == {"G3_CLEAR_OPENING_WIDTH": "UNRESOLVED", "G3_POST_OD": "UNRESOLVED", "G3_FOOTING": "SPECIFIED"}, f"G3 scope: width and post OD unresolved, footing specified {gi}")
        gt = G.inner_text(); ok("1'-4\" dia. x 4'-0\" deep minimum" in G.get_by_test_id("fr-g3-value").inner_text() and "2.1.B ties it to the opening width" in gt and "belongs to Gate G2 and is not applied to G3" in gt and "No design-team answer and no human authorization is recorded" in gt, "screen explains why G3 post size is unresolved while footing minimums are known")
        G.scroll_into_view_if_needed(); A.wait_for_timeout(200); d.screenshot(path=str(SHOT.with_name(SHOT.stem + "_g3.png")))
        ok("not a human approval, rejection or decision" in AU.get_by_test_id("fr-audit-nothuman").inner_text() and "Human authorization: none recorded" in at, "audit is not a human decision")
        iss = {li.get_attribute("data-assessment"): li.inner_text() for li in V.get_by_test_id("fr-issues").locator("li").all()}
        pills = V.get_by_test_id("fr-issues").locator("li").evaluate_all("l=>l.map(x=>[x.textContent.slice(0,2),x.dataset.assessment])")
        ok(pills == [["I1", "SUPPORTED"], ["I2", "FLAGGED"], ["I3", "SUPPORTED"]], f"issue assessments {pills}")
        step(2, "Original validator result preserved; six-drop explanation corrected and attributed; audit provenance shown; I1 SUPPORTED, I2 FLAGGED, I3 SUPPORTED", counts=vc)

        # 3. shortlist holds only D1; D2 is flagged historical output; four assurance layers are distinct; nothing approved or sent
        SL = X.get_by_test_id("fr-shortlist"); ok(SL.get_by_test_id("fr-case").count() == 1 and SL.get_by_test_id("fr-case-id").inner_text() == CASES[0], "active shortlist = D1 only")
        ok("eligible for human review" in SL.inner_text(), "D1 eligible for human review")
        FS = X.get_by_test_id("fr-flagged-section"); fc = FS.get_by_test_id("fr-flagged-case")
        ok(fc.count() == 1 and CASES[1] in fc.inner_text() and fc.get_by_test_id("fr-flagged-pill").inner_text() == "FLAGGED — UNSUPPORTED BY CONTROLLING EVIDENCE", "D2 visible, flagged, in its own historical section")
        ok(not SL.get_by_text(CASES[1]).count(), "D2 is not on the active shortlist")
        ok("Historical AI output" in FS.inner_text() and "not on the active shortlist" in FS.inner_text(), "section named as historical, not actionable")
        ok(X.get_by_test_id("fr-unaudited").count() == 0, "no unaudited group when the audit verifies")
        CL = X.get_by_test_id("fr-clarifications"); cl = CL.get_by_test_id("fr-clarification"); ct = CL.inner_text()
        ok(cl.count() == 1 and "not an evolus case" in ct.lower() and all(w in ct for w in ("PROPOSED", "NOT APPROVED", "NOT SENT", "NOT AN EVOLUS CASE")), "one proposed clarification, labelled not approved, not sent, not an Evolus case")
        au_ = cl.get_by_test_id("fr-clarif-authorship").inner_text(); ok("Gate G3 post outside diameter" in ct and "drafted by ANVIL 1" in au_ and "not an Evolus- or Gemma-generated case" in au_ and "A named person must review" in au_, "authorship labelled accurately (ANVIL 1 draft from LOOM's recommendation, not an Evolus case)")
        ok("footing" not in cl.get_by_test_id("fr-clarif-question").inner_text().lower() and "footing diameter and depth" in cl.get_by_test_id("fr-clarif-excluded").inner_text(), "the clarification asks about the post OD only; footing is listed as already specified")
        ok(not SL.get_by_text(cl.get_by_test_id("fr-clarif-id").inner_text()).count() and cl.locator("button, input, textarea, a, select").count() == 0, "not on the shortlist; no controls")
        fc.locator("summary").click(); A.wait_for_timeout(200)
        cards = X.get_by_test_id("fr-case"); ok(cards.count() == len(CASES), f"{cards.count()} case cards in total")
        ok(X.get_by_test_id("fr-case-count").inner_text().lower().startswith(f"{len(CASES)} pending-review rfi cases"), "case count")
        ids = [cards.nth(i).get_by_test_id("fr-case-id").inner_text() for i in range(cards.count())]; ok(sorted(ids) == sorted(CASES), f"actual case ids {ids}")
        for i in range(cards.count()):
            c = cards.nth(i); t = c.inner_text(); cid = c.get_attribute("data-case-id")
            ok(c.get_by_test_id("fr-case-status").inner_text() == "PENDING HUMAN REVIEW" and c.get_by_test_id("fr-case-approval").inner_text() == "NOT APPROVED" and c.get_by_test_id("fr-case-sent").inner_text() == "NOT SENT", f"{cid} status pills")
            ok("Proposed RFI: a stored AI draft" in t and "has not been approved by a person and has not been sent to anyone" in t, "stored-draft banner")
            ok(not re.search(r"\bapproved by [A-Z]|APPROVED(?! )", t.replace("NOT APPROVED", "")), "no approved/transmitted wording")
            ok(c.get_by_test_id("fr-case-question").inner_text().strip() and c.get_by_test_id("fr-case-missing").locator("li").count() >= 1, "original question and requirements preserved on screen")
            ok(c.get_by_test_id("fr-case-sources").locator("li").count() >= 2, "cited sources listed")
            as_ = c.get_by_test_id("fr-assurance"); rows = as_.locator("th").all_inner_texts()
            ok(rows == ["Structurally valid AI output", "Source match reported by adapter", "Citation binding checks by the recorder", "Independent assessment of semantic support", "Human authorization"], f"distinct layers {rows}")
            ok("COMPLETED_VALID (original result, unchanged)" in as_.get_by_test_id("fr-assure-structure").inner_text(), "layer 1 is the original validator result")
            ad = as_.get_by_test_id("fr-assure-adapter").inner_text(); ok("Not independently rechecked by the Flight Recorder" in ad and "does not read the PDFs" in ad, "adapter source-match is labelled as not rechecked")
            ok("do not check the quoted text" in as_.get_by_test_id("fr-assure-citations").inner_text(), "recorder binding checks do not claim to check quoted text")
            ok("source match reported by adapter — not independently rechecked by Flight Recorder" in c.get_by_test_id("fr-case-sources").inner_text() and not re.search(r"located in source|verified in source", t, re.I), "case source lines carry the qualified wording")
            ok("NONE RECORDED" in as_.get_by_test_id("fr-assure-human").inner_text() and "No person has approved or rejected" in as_.get_by_test_id("fr-assure-human").inner_text(), "layer 4: no human authorization")
            au = c.get_by_test_id("fr-case-authority").inner_text(); ok("changes scope no" in au and "changes estimate no" in au and "authorizes labor or release no" in au and "marks bid ready no" in au and "needs a named human yes" in au, "recorded authority flags")
            ok(c.locator("button, input, textarea, a, select").count() == 0, "a case card has no controls: nothing to approve, send or edit")
            sem = as_.get_by_test_id("fr-assess-pill").inner_text()
            if cid == CASES[0]: ok(sem == "SUPPORTED" and c.get_by_test_id("fr-flag").count() == 0, "D1 SUPPORTED, no flag")
            else:
                fl = c.get_by_test_id("fr-flag").inner_text(); ok(sem == "FLAGGED — UNSUPPORTED BY CONTROLLING EVIDENCE" and "The footing is NOT missing" in fl and "G3 post outside diameter, however, IS still unresolved" in fl and "does not mean the G3 post size is resolved" in fl, "D2 FLAGGED with the corrected, scoped reason")
                ok("omitted controlling Addendum 01 item 1.5" not in fl, "the overbroad G2-to-G3 rationale is gone")
                ev = c.get_by_test_id("fr-assess-evidence").inner_text(); ok("Gate post size and footing are unchanged: 2.875 in OD post with the terminal / gate footing, Detail 3/F501." in ev and "applies to Gate G2 only — not extended to G3" in ev, "item 1.5 still quoted verbatim, labelled G2-only")
                item15 = c.get_by_test_id("fr-assess-evidence").locator("li", has_text="Gate post size and footing are unchanged").first.inner_text(); ok(item15.startswith("Context") and "Controlling evidence" not in item15, "item 1.5 is context, not the contradiction")
                ok("adapter-supplied excerpt text (may join separate table cells; not a verified contiguous quotation)" in ev.lower() and "the Flight Recorder does not read the PDF" in ev and "FOOTING: SEE NOTE 4" in ev and not re.search(r"quote matches|verbatim", ev, re.I), "D2 excerpts (incl. 'FOOTING: SEE NOTE 4') are labelled adapter-supplied, not verbatim")
                ok("Controlling evidence" in ev and "1'-4\" DIA. × 4'-0\" DEEP" in ev and "CORE-DRILLED FOOTING PER TERMINAL / GATE POST, 3/F501" in ev, "the footing contradiction rests on F501/F502 (3/F501), quoted")
                ok("identical to the excerpt in the package recorded in the run record (compared with the adapter’s text, not with the PDF)" in ev and "DOES NOT MATCH" not in ev.upper().replace("DOES NOT MATCH THE EXCERPT","") , "audit excerpt text compared with the package text only, and said so")
                ok("Addendum 01 item 1.5 is G2-only" in c.get_by_test_id("fr-assess-note").inner_text(), "correction note shown on the card")
                ok("Gate G3 Post and Footing Specifications" in t and "Please provide the required post size and footing dimensions" in t, "original D2 text preserved verbatim")
        step(3, "Shortlist holds D1 (SUPPORTED, eligible, not approved/sent); D2 is visible only as FLAGGED historical output; four assurance layers shown apart", cases=ids)
        A.screenshot(path=str(SHOT))
        X.get_by_test_id("fr-review").scroll_into_view_if_needed(); A.wait_for_timeout(200); d.screenshot(path=str(SHOT.with_name(SHOT.stem + "_review.png")))
        fc.scroll_into_view_if_needed(); A.wait_for_timeout(200); d.screenshot(path=str(SHOT.with_name(SHOT.stem + "_flagged.png")))

        # 4. the earlier failed run is a separate execution with no cases and no validator outcome
        ok(d.get_by_test_id("fr-pick").count() == 2, "picker lists the successful and the failed execution")
        d.get_by_test_id("fr-pick").nth(1).click(); A.wait_for_timeout(250)
        F = d.get_by_test_id("fr-selected"); ok(F.get_by_test_id("fr-exec-id").inner_text() == FAIL_TRACE and F.locator(".fr-exec-head [data-testid=fr-state-FAILED]").count() == 1, "failed execution selectable")
        ok(F.get_by_test_id("fr-case").count() == 0 and F.get_by_test_id("fr-validator").count() == 0 and F.get_by_test_id("fr-audit").count() == 0 and F.get_by_test_id("fr-validator-none").count() == 1, "the failed run shows no cases, no audit and no validator outcome")
        ev2 = lay(F, "evolus").locator("details.fr-event").first; ev2.locator("summary").click(); A.wait_for_timeout(120)
        ok("HTTP_ERROR" in ev2.inner_text() and ev2.get_by_test_id("fr-field-workflow_execution_id").inner_text() == "NOT REPORTED", "failed run: HTTP_ERROR, no execution id")
        ok(EXEC_ID not in F.inner_text() and not any(c in F.inner_text() for c in CASES), "nothing from the successful run appears in the failed run")
        d.get_by_test_id("fr-pick").nth(0).click(); A.wait_for_timeout(200)
        step(4, "The earlier HTTP 400 failure stays a separate execution: HTTP_ERROR, no execution id, no cases, no validator outcome")

        # 5. historical evidence is separate and unchanged
        H = d.get_by_test_id("fr-historical")
        ok("not what happened in the execution above" in H.inner_text() and H.get_by_test_id("fr-hist-layer-amd").locator(".fr-layer-head [data-testid=fr-state-RECORDED]").count() == 1, "historical AMD RECORDED, labelled as earlier runs")
        ok(not any(c in H.inner_text() for c in CASES) and EXEC_ID not in H.inner_text(), "no case or execution id inside the historical section")
        step(5, "Historical AMD/Gemma evidence stays in its own section")

        # 6. trace-files list, read-only proof
        src = d.get_by_test_id("fr-sources").inner_text(); ok(src.count("review case") == len(CASES) and src.count("independent audit record") == 2 and "execution trace" in src and "REJECTED" not in src, f"sources list: {len(CASES)} cases accepted")
        A.screenshot(path=str(SHOT.with_name(SHOT.stem + "_after.png")))
        A.keyboard.press("Escape"); A.wait_for_timeout(200)
        after = state(A); totals_after = A.locator(".plan-totals").inner_text() if A.locator(".plan-totals").count() else ""
        ok(before["status"] == after["status"] and before["scope_version"] == after["scope_version"] and len(before["audit"]) == len(after["audit"]), "status, scope version and audit trail unchanged")
        ok(json.dumps(before, sort_keys=True) == json.dumps(after, sort_keys=True), "the whole project record is byte-identical before and after")
        ok(totals_before == totals_after, f"visible totals unchanged: {totals_before[:60]!r}")
        ok(not writes, f"no non-GET request while the recorder was used: {writes}")
        ok(not external, f"no external request: {external}")
        ok(not [m for m in console if "fonts" not in m.lower() and "ERR_NETWORK_CHANGED" not in m], f"console errors: {console}")
        step(6, "Read-only: project record, totals and audit identical; only GET requests; no external call; no console errors")
        b.close()
    print(f"EVOLUS CASES E2E PASS {len(steps)} step groups")

if __name__ == "__main__": main()

"""AI Flight Recorder, real browser (Chromium, 1800x732) through the real frontend proxy. OFFLINE: no AMD / Evolus request is made or possible;
external requests are asserted empty (Google Fonts excepted, as in the other suites). Shows the three producer layers apart from Gatehouse validation and
human authorization, every provenance state, derived-value labelling, and a REAL human decision appearing in the trace.
Env: DEMO_URL (default the local proxy), FR_SCREENSHOT (path for the screenshot). Mode (which FLIGHT_TRACE_DIR the server was started with):
  default: an empty trace directory (no execution).
  FR_EXPECT_EXTERNAL=1: failed_evolus_http_error_fixture.json (newest), valid_evolus_simulated.json, invalid_unbacked_gpu_number.json (must be REJECTED).
  FR_EXPECT_TRACE_ID=<id>: a single real failed Evolus trace with that trace_id and note HTTP_ERROR (no workflow execution id, no AMD/Gemma facts)."""
import json, os, pathlib, re
from playwright.sync_api import sync_playwright
from e2e_common import URL, ok, api, dlg
from e2e_dp001 import state
import e2e_footing as F

steps = []
def step(n, t, **ev): steps.append({"n": n, "title": t, **ev}); print(f"[{n}] {t} {json.dumps(ev, default=str)[:300]}", flush=True)
SHOT = pathlib.Path(os.environ.get("FR_SCREENSHOT", "/tmp/flight_recorder.png"))
EXPECT_EXTERNAL = os.environ.get("FR_EXPECT_EXTERNAL") == "1"
EXPECT_TRACE_ID = os.environ.get("FR_EXPECT_TRACE_ID")

def layer(pg, name): return pg.get_by_test_id(f"fr-layer-{name}")
def expand(pg, name, tid=None):
    L = pg.get_by_test_id(tid) if tid else layer(pg, name)
    if L.locator(".fr-layer-body").count() == 0: L.locator(".fr-layer-head").click(); pg.wait_for_timeout(120)
    return L
def open_recorder(pg):
    pg.locator("[data-testid=open-flight-recorder]:visible").first.click(); d = pg.get_by_test_id("flight-recorder"); d.wait_for(); pg.get_by_test_id("fr-notice").wait_for(timeout=15000); pg.wait_for_timeout(250); return d
def close_recorder(pg): pg.get_by_role("button", name="Close Flight Recorder").click(); pg.wait_for_timeout(200)
def event_by_text(L, text): return L.locator("details.fr-event", has_text=text).first

def main():
    console_errors, external = [], []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, ignore_default_args=["--hide-scrollbars"])
        ctx = b.new_context(viewport={"width": 1800, "height": 732}); A = ctx.new_page()
        A.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None); A.on("pageerror", lambda e: console_errors.append("PAGEERROR " + str(e)))
        A.on("request", lambda r: external.append(r.url) if not r.url.startswith(URL.rstrip("/")) and not r.url.startswith(("data:", "blob:", "https://fonts.googleapis.com/", "https://fonts.gstatic.com/")) else None)
        A.goto(URL); A.wait_for_load_state("networkidle"); A.wait_for_selector("[data-testid=doc-viewer] canvas")
        st = state(A)
        if not (st["status"] == "needs_scope_review" and len(st["audit"]) == 1):
            A.get_by_role("button", name="Reset demo").first.click(); A.get_by_text("Demo reset").first.wait_for(); A.wait_for_timeout(800)

        # 1. opens from the sidebar; five states explained; separation of producer layers and Gatehouse layers
        d = open_recorder(A)
        ok(d.get_attribute("role") == "dialog" and d.get_attribute("aria-label") == "AI Flight Recorder", "dialog semantics")
        for s in ("LIVE", "RECORDED", "SIMULATED", "FAILED", "NOT_REPORTED"): ok(d.locator(f".fr-legend [data-testid=fr-state-{s}]").count() == 1, f"legend {s}")
        names = [t.strip() for t in d.locator("h4.fr-group").all_inner_texts()]
        ok([n.split("\n")[0].strip() for n in names] == ["Selected execution", "Historical recorded evidence", "This session", "Trace files"], f"groups {names}")
        sel_n = d.get_by_test_id("fr-selected").count()
        ok(sel_n == (0 if not (EXPECT_EXTERNAL or EXPECT_TRACE_ID) else 1), "selected-execution block exists only when a trace was recorded")
        if sel_n: ok(d.locator("[data-testid=fr-selected] section.fr-layer").evaluate_all("l=>l.map(x=>x.dataset.testid)") == ["fr-layer-amd", "fr-layer-gemma", "fr-layer-evolus"], "selected execution has amd, gemma, evolus")
        else: ok(d.get_by_test_id("fr-no-execution").count() == 1 and "No execution trace has been recorded" in d.get_by_test_id("fr-no-execution").inner_text(), "says no execution has been recorded")
        order = [l.get_attribute("data-testid") for l in d.locator("[data-testid=fr-historical] section.fr-layer").all()]
        ok(order == ["fr-hist-layer-amd", "fr-hist-layer-gemma", "fr-hist-layer-evolus", "fr-layer-gatehouse_validation"], f"historical layer order {order}")
        ok("not part of the selected execution" in d.locator("h4.fr-group").nth(1).inner_text().lower() and "not what happened in the execution above" in d.get_by_test_id("fr-hist-meta").inner_text(), "historical section states it is not part of the execution")
        ok(re.search(r"sha256 [0-9a-f]{10}…[0-9a-f]{6}", d.get_by_test_id("fr-hist-meta").inner_text()) and "flight_recorder.json" in d.get_by_test_id("fr-hist-meta").inner_text(), "historical source file and hash shown")
        step(1, "Flight Recorder opens beside the workspace: five states, three producer layers apart from Gatehouse validation and human authorization", order=order)

        # 2. AMD layer: real stored telemetry; derived values are labelled; unreported values say so
        amd = expand(A, "amd", "fr-hist-layer-amd")
        ok(amd.locator("details.fr-event").count() == 10, "ten recorded AMD requests")
        ok("GPU utilization is not reported" in amd.inner_text(), "AMD layer says no GPU figure exists")
        ok(amd.locator("[data-testid=fr-state-RECORDED]").count() >= 5 and amd.locator("[data-testid=fr-state-FAILED]").count() >= 4, "RECORDED and FAILED events are distinguished")
        r2 = event_by_text(amd, "r2_east"); r2.locator("summary").click(); A.wait_for_timeout(150)
        ft = {k: r2.get_by_test_id(f"fr-field-{k}").inner_text() for k in ("ttft_s", "tokens_per_s", "prompt_tokens", "completion_tokens", "http_status", "cost_usd")}
        ok("derived" in ft["ttft_s"] and "t_first_content_token_s - t_request_sent_s" in ft["ttft_s"], f"ttft is labelled derived with its formula: {ft['ttft_s']}")
        ok("derived" in ft["tokens_per_s"] and ft["prompt_tokens"] == "626" and ft["completion_tokens"] == "73" and ft["http_status"] == "200", f"measured values: {ft}")
        ok(re.search(r"sha256 [0-9a-f]{10}…[0-9a-f]{6}", r2.get_by_test_id("fr-source").inner_text()), "record hash shown")
        step(2, "Historical AMD evidence: 10 stored requests, tokens/TTFT only where the record has them, derived values labelled", sample=ft)

        # 3. a request with no streaming telemetry shows NOT REPORTED, not an estimate
        q = amd.locator("details.fr-event", has_text="Qwen3.8-27B").filter(has=A.get_by_test_id("fr-state-RECORDED")).first; q.locator("summary").click(); A.wait_for_timeout(120)
        ok(q.get_by_test_id("fr-field-ttft_s").inner_text() == "NOT REPORTED" and q.get_by_test_id("fr-field-tokens_per_s").inner_text() == "NOT REPORTED", "no TTFT or tokens/s is invented for a non-streamed request")
        step(3, "Non-streamed request: TTFT and tokens/s read NOT REPORTED")

        # 4. Gemma layer holds only the failed Gemma attempt; DeepSeek is never shown as Gemma
        g = expand(A, "gemma", "fr-hist-layer-gemma")
        ok(g.locator("details.fr-event").count() == 1 and "FAILED" in g.inner_text(), "one failed Gemma attempt")
        g.locator("details.fr-event summary").click(); A.wait_for_timeout(120)
        ok(g.get_by_test_id("fr-field-model").inner_text() == "Gemma-4-31B-IT" and g.get_by_test_id("fr-field-citations").inner_text() == "NOT REPORTED", "exact Gemma model, citations NOT REPORTED")
        ok("DeepSeek" not in " ".join(g.locator("details.fr-event").all_inner_texts()), "no non-Gemma model appears as a Gemma event")
        step(4, "Historical Gemma evidence: exact model string, FAILED, no citations; DeepSeek is only under AMD")

        # 5. Selected execution: only that run's facts. Historical AMD/Gemma never appear inside it.
        def sel_layer(n): return d.get_by_test_id("fr-selected").get_by_test_id(f"fr-layer-{n}")
        if EXPECT_EXTERNAL or EXPECT_TRACE_ID:
            X = d.get_by_test_id("fr-selected"); xid = EXPECT_TRACE_ID or "FIXTURE-failed-http-error"
            ok(X.get_by_test_id("fr-exec-id").inner_text() == xid, f"newest execution is selected by default: {X.get_by_test_id('fr-exec-id').inner_text()}")
            ok(X.locator(".fr-exec-head [data-testid=fr-state-FAILED]").count() == 1, "outcome FAILED")
            for n, st in (("evolus", "FAILED"), ("gemma", "NOT_REPORTED"), ("amd", "NOT_REPORTED")):
                ok(sel_layer(n).locator(".fr-layer-head [data-testid=fr-state-%s]" % st).count() == 1, f"selected {n} is {st}")
            ok(sel_layer("amd").locator("details.fr-event").count() == 0 and sel_layer("gemma").locator("details.fr-event").count() == 0, "no AMD or Gemma event inside the execution")
            xt = X.inner_text(); ok("Gemma-4-31B-IT" not in xt and "DeepSeek" not in xt and "r2_east" not in xt and "Qwen" not in xt, "no historical record text inside the execution")
            ev0 = sel_layer("evolus").locator("details.fr-event").first; ev0.locator("summary").click(); A.wait_for_timeout(150)
            ok("HTTP_ERROR" in ev0.inner_text(), "Evolus HTTP_ERROR note shown")
            for k in ("workflow_execution_id", "agent", "review_state"): ok(ev0.get_by_test_id(f"fr-field-{k}").inner_text() == "NOT REPORTED", f"{k} NOT REPORTED")
            ok(ev0.locator("[data-testid^=fr-field-]").evaluate_all("l=>l.map(x=>x.dataset.testid)").__len__() > 0 and not re.search(r"token|gpu", ev0.inner_text(), re.I), "no token or GPU field on the failed execution")
            ok("1 event" in sel_layer("evolus").locator(".fr-layer-head").inner_text(), "one Evolus event")
            # historical block is unchanged next to it
            ok(amd.locator("details.fr-event").count() == 10 and d.get_by_test_id("fr-hist-layer-evolus").locator(".fr-layer-head [data-testid=fr-state-NOT_REPORTED]").count() == 1, "historical evidence intact beside the execution")
            if EXPECT_EXTERNAL:
                ok(d.get_by_test_id("fr-pick").count() == 2, "a picker lists both executions")
                d.get_by_test_id("fr-pick").nth(1).click(); A.wait_for_timeout(200)
                X2 = d.get_by_test_id("fr-selected"); ok(X2.get_by_test_id("fr-exec-id").inner_text() == "fixture-evolus-simulated", "second execution selectable")
                ok(X2.locator(".fr-exec-head [data-testid=fr-state-SIMULATED]").count() == 1 and X2.locator("[data-testid=fr-state-FAILED]").count() == 0, "second execution's states are its own (SIMULATED, no FAILED from the other run)")
                ok("HTTP_ERROR" not in X2.inner_text(), "the failed run's note does not appear in the second execution")
                A.screenshot(path=str(SHOT.with_name(SHOT.stem + "_second_execution.png")))
                d.get_by_test_id("fr-pick").nth(0).click(); A.wait_for_timeout(200)
                src = d.get_by_test_id("fr-sources").inner_text(); ok("REJECTED" in src and "accepted" in src and d.get_by_test_id("fr-rejected").count() == 1, "exactly one rejected file")
            step(5, "Selected execution is FAILED/HTTP_ERROR with AMD and Gemma NOT_REPORTED; historical evidence is separate and intact")
        else:
            ok("No Evolus workflow execution has been recorded" in d.get_by_test_id("fr-hist-layer-evolus").inner_text() or expand(A, "evolus", "fr-hist-layer-evolus").inner_text().count("No Evolus workflow execution has been recorded") == 1, "says why")
            step(5, "No execution recorded: the selected-execution group says so; nothing historical is presented as current")

        # 6. Gatehouse validation: computed from the ledger, separate; the contradicted Type B claim
        v = expand(A, "gatehouse_validation")
        ok(v.locator("details.fr-event", has_text="CONTRADICTED BY DRAWING EVIDENCE").count() == 2, "two contradicted claims")
        c = v.locator("details.fr-event", has_text="type_tag_leader:B").first; c.locator("summary").click(); A.wait_for_timeout(120)
        ok("409 CONTRADICTED_BY_DRAWING_EVIDENCE" in c.get_by_test_id("fr-field-acceptance").inner_text() and c.get_by_test_id("fr-field-model_stated_confidence").inner_text() == "clear", "model said clear; acceptance refused")
        ok(v.locator("[data-testid=fr-state-SIMULATED]").count() == 2, "two SIMULATED guard items are labelled")
        step(6, "Gatehouse validation: model said 'clear', code contradicted it, acceptance refused; simulated guard items labelled SIMULATED")

        # 7. human authorization starts empty; a real decision appears as LIVE with a self-declared warning
        h = expand(A, "human_authorization")
        ok(h.locator("details.fr-event").count() == 0 and "No human decision has been recorded" in h.inner_text(), "no human decision yet; the system start entry is not shown as one")
        A.screenshot(path=str(SHOT.with_name(SHOT.stem + "_before_decision.png")))
        close_recorder(A)
        gate = F.open_gate(A); F.select_bid(A, "base")
        A.wait_for_timeout(400)
        d = open_recorder(A); h = expand(A, "human_authorization")
        ok(h.locator("details.fr-event").count() >= 1 and h.locator("[data-testid=fr-state-LIVE]").count() >= 1, "the decision appears as LIVE")
        h.locator("details.fr-event").first.locator("summary").click(); A.wait_for_timeout(120)
        ok(h.get_by_test_id("fr-field-by").inner_text() == "Visitor A" and "Self-declared" in h.inner_text(), "named, self-declared")
        step(7, "Human authorization: empty until a person decides; then the decision appears LIVE, marked self-declared")

        # 8. contract enforcement visible in the API payload; no secrets; read-only
        r = api(A, "/api/demo/flight-recorder"); body = json.dumps(r["body"])
        ok(r["status"] == 200 and not re.search(r"ENGINE_API_KEY|SESSION_SIGNING|X-Engine-Key|Bearer|AMD_TOKEN", body), "payload carries no credential names or keys")
        bd = r["body"]; ok(all(L["layer"] in ("amd", "gemma", "evolus") for L in bd["historical"]["layers"]) and all(L["layer"] in ("amd", "gemma", "evolus") for x in bd["executions"] for L in x["layers"]), "producer layers are only amd/gemma/evolus"); ok("producer_layers" not in bd, "no merged producer-layer list")
        before = state(A)
        api(A, "/api/demo/flight-recorder"); after = state(A)
        ok(before["scope_version"] == after["scope_version"] and len(before["audit"]) == len(after["audit"]), "the recorder is read-only")
        A.screenshot(path=str(SHOT));
        # layers expanded for the full-field screenshot
        for n in ("amd", "gemma", "evolus"): expand(A, n, f"fr-hist-layer-{n}")
        step(8, "API payload has no credentials; the recorder changes nothing")

        # 9. closes with Escape, focus returns to a usable page; viewer still present
        A.keyboard.press("Escape"); A.wait_for_timeout(250)
        ok(A.get_by_test_id("flight-recorder").count() == 0 and A.locator("[data-testid=doc-viewer] canvas").count() >= 1, "closed; viewer intact")
        step(9, "Escape closes the panel; the evidence viewer is intact")

        ok(not external, f"external requests: {external}")
        real_errors = [m for m in console_errors if "fonts" not in m.lower()]
        ok(not real_errors, f"console errors: {real_errors}")
        step(10, "no external requests (no AMD / Evolus), no console errors", external_requests=len(external))
        b.close()
    print(f"FLIGHT RECORDER E2E PASS {len(steps)} step groups")

if __name__ == "__main__":
    main()

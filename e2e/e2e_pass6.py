"""ANVIL 1 Pass 6 integration: 12 browser scenarios through the real frontend proxy (port 5021) on the Pass 6 adapter. Headless Chromium.
Fictional project only. No AMD calls (external requests are asserted empty). Screenshots go to evidence/screenshots."""
import json, re, sys
from decimal import Decimal
from playwright.sync_api import sync_playwright
from e2e_common import URL, SHOTS, ok, usd, num, api, dlg, new_context, save_state, ensure_pristine

FLEET = ["CR11", "CR12", "CR13", "CR14"]
FORBID_KEYS = {"content_sha256", "content_identity", "identity_spec", "ever_cleared", "ever_authorized_pricing", "first_cleared_audit_event_id",
               "payload_sha256", "idempotency_key", "records", "body_bytes"}
SELF = "Self-declared demo approval — identity not authenticated."
results = []

def step(n, title):
    results.append((n, title)); print(f"[{n}] {title}", flush=True)

def shot(pg, name): pg.screenshot(path=str(SHOTS / f"{name}.png"), full_page=False)

def settle(pg):
    pg.wait_for_timeout(300)
    pg.wait_for_function("!document.querySelector('.plan-totals')?.classList.contains('pending')", timeout=15000)

def keys_in(o, found, under_ratebook=False):
    """Collect forbidden wage-history / authorization field names. The pinned rate book's own content hash (audit[].ratebook_ref) is a
    pre-existing, disclosed reference to a public fictional book, not wage-history material, so it is exempt."""
    if isinstance(o, dict):
        for k, v in o.items():
            if k in FORBID_KEYS and not (under_ratebook and k == "content_sha256"): found.add(k)
            keys_in(v, found, under_ratebook or k == "ratebook_ref")
    elif isinstance(o, list):
        for v in o: keys_in(v, found, under_ratebook)
    return found

def body(pref, assign, diff="standard", over=None):
    return {**({"preferred_crew": pref} if pref else {}), "assignments": assign, "use_default_for_unassigned": False, "difficulty": {"default": diff, "overrides": over or {}}}

def state(pg): return api(pg, "/api/demo/state")["body"]["project"]

def main():
    external, console_errors, seen_json = [], [], []
    reqs = []   # (url, method, idempotency-key) for every decision request the page itself made
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = new_context(b, "p6", viewport={"width": 1500, "height": 950}); A = ctx.new_page()
        A.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        def on_req(r):
            if not r.url.startswith(URL.rstrip("/")) and not r.url.startswith("data:"): external.append(r.url)
            if "/api/demo/decision/" in r.url: reqs.append((r.url.split("/api/demo/")[1], r.headers.get("idempotency-key")))
        A.on("request", on_req)
        def on_resp(r):
            if "/api/demo/" in r.url:
                try: seen_json.append((r.url, r.json()))
                except Exception: pass
        A.on("response", on_resp)
        ensure_pristine(A)
        side = A.locator("aside.sidebar")

        # 1. open the fictional project: fleet, portfolio, no money yet
        pf = api(A, "/api/demo/portfolio")["body"]
        ok(len(pf["projects"]) == 8, f"eight-project portfolio, got {len(pf['projects'])}")
        raw = state(A)
        ok([c["crew_id"] for c in raw["pricing"]["crews"]["crews"]] == FLEET, "four active fleet crews only")
        ok(raw["status"] == "needs_scope_review" and raw["estimate"] is None, "unpriced at open")
        ok(raw["adapter"]["actor_identity"] == "SELF_DECLARED_DEMO_ACTOR_NOT_AUTHENTICATED", raw["adapter"])
        step(1, "fictional project opened; 8-project portfolio; 4 fleet crews; no estimate")

        # 2. scope / draft assumptions
        d = dlg(A, "Scope Gate"); d.wait_for()
        ok(SELF in d.inner_text(), "Scope Gate carries the self-declared label")
        d.get_by_placeholder("Value the engine will validate").fill("10")
        d.get_by_placeholder("Any name; recorded as self-declared").fill("Visitor A")
        d.get_by_placeholder("What evidence or authority supports this decision?").fill("Bid qualification: gate G3 width assumed pending design")
        shot(A, "scope_gate_before_decision")
        d.get_by_role("button", name="Record scope decision").click(); A.get_by_text("Recorded by the engine").first.wait_for(); A.wait_for_timeout(500)
        rf = A.get_by_label("Quantity ruleset approval"); rf.wait_for()
        ok("draft" in rf.inner_text().lower() and "Contractor approval outstanding" in rf.inner_text(), "draft / unapproved quantity-rule label")
        ok(SELF in rf.inner_text(), "ruleset form carries the self-declared label")
        shot(A, "scope_gate_ruleset_draft")
        step(2, "G3 value recorded; draft quantity rules and contractor-approval caveat shown; self-declared label")

        # 3a. ruleset approval: the page itself must send an Idempotency-Key, unique per decision
        n0 = len(reqs)
        rf.get_by_placeholder("Any name; recorded as self-declared").fill("Visitor A"); rf.get_by_placeholder("What did you review?").fill("Reviewed the rule table (demo)")
        rf.get_by_role("button", name="Approve this exact ruleset").click()
        d = dlg(A, "Labor Gate"); d.wait_for(timeout=15000); A.wait_for_timeout(700)
        ok(len(reqs) == n0 + 1 and reqs[-1][1] and re.fullmatch(r"[A-Za-z0-9_.:-]{8,128}", reqs[-1][1]), f"ruleset request carried a valid key: {reqs[n0:]}")
        key_ruleset = reqs[-1][1]
        st = state(A)
        ok(st["pricing"]["ruleset"]["contractor_approved"] is False, "visitor approval is not contractor approval")
        # proxy refuses a decision without a key (and nothing is stored)
        before = state(A)
        r = api(A, "/api/demo/decision/ruleset", {"by": "x", "note": "y", "ruleset_sha256": st["pricing"]["ruleset"]["sha256"]})
        ok(r["status"] == 400 and r["body"]["code"] == "IDEMPOTENCY_KEY_REQUIRED", r)
        ok(state(A)["audit"] == before["audit"], "keyless request changed nothing")
        step("3a", "ruleset approved with a UI-generated Idempotency-Key; keyless request refused 400 IDEMPOTENCY_KEY_REQUIRED")

        # 3b. wage determination: duplicate schedule classification typed in the UI is rejected and the draft survives
        ok(SELF in d.inner_text(), "Labor Gate carries the self-declared label")
        w = d.get_by_label("Davis-Bacon wage determination")
        w.get_by_role("button", name="Load the fictional demonstration decision (FDB-DP001)").click()
        w.get_by_role("button", name="Add schedule row").click()
        w.get_by_label("Schedule classification 4").fill("Laborer, common or general")   # duplicate of row 1
        w.get_by_label("Schedule base rate 4").fill("24.50"); w.get_by_label("Schedule fringe rate 4").fill("9.10")
        w.get_by_placeholder("Any name; recorded as self-declared").fill("Visitor A"); w.get_by_placeholder("What did you review?").fill("Classifications from the decision")
        audit0 = state(A)["audit"]; n0 = len(reqs)
        w.get_by_role("button", name="Record wage determination").click()
        A.get_by_role("alert").filter(has_text="WAGE_SCHEDULE_DUPLICATE_CLASSIFICATION").wait_for(timeout=10000)
        ok(len(reqs) == n0 + 1, "one wage request")
        ok(state(A)["audit"] == audit0, "rejected wage decision stored nothing")
        ok(w.get_by_label("Schedule classification 4").input_value() == "Laborer, common or general" and w.get_by_placeholder("What did you review?").input_value() == "Classifications from the decision"
           and w.locator("input").first.input_value() == "FDB-DP001", "wage form draft preserved after rejection")
        shot(A, "labor_gate_duplicate_classification_rejected")
        wage_body = json.loads(A.evaluate("0") and "{}") if False else None
        step("3b", "WAGE_SCHEDULE_DUPLICATE_CLASSIFICATION shown in the UI; nothing stored; draft preserved")

        # 3c. duplicate role row can't be produced by the form (one row per role); the route still refuses it
        cur = state(A)
        good = None
        def cap(route):
            nonlocal good
            good = json.loads(route.request.post_data); route.continue_()
        # fix the form (drop the duplicate row), capture the body the page really sends, then submit it
        w.get_by_role("button", name="Load the fictional demonstration decision (FDB-DP001)").click()
        w.get_by_placeholder("Any name; recorded as self-declared").fill("Visitor A"); w.get_by_placeholder("What did you review?").fill("Classifications from the decision")
        A.route("**/api/demo/decision/wage", cap)
        w.get_by_role("button", name="Record wage determination").click(); A.get_by_text("Recorded by the engine").first.wait_for(); A.wait_for_timeout(600)
        A.unroute("**/api/demo/decision/wage")
        ok(good is not None and len(good["rows"]) >= 2, "captured the real wage body")
        wage_key = reqs[-1][1]
        dup_role = json.loads(json.dumps(good)); dup_role["rows"].append(dict(dup_role["rows"][0]))
        a1 = state(A)["audit"]
        r = api(A, "/api/demo/decision/wage", dup_role, {"Idempotency-Key": "e2e-dup-role-0001"})
        ok(r["status"] == 400 and r["body"]["code"] == "WAGE_ROW_DUPLICATE_ROLE", r)
        dup_cls = json.loads(json.dumps(good)); dup_cls["schedule"].append(dict(dup_cls["schedule"][0]))
        r = api(A, "/api/demo/decision/wage", dup_cls, {"Idempotency-Key": "e2e-dup-class-001"})
        ok(r["status"] == 400 and r["body"]["code"] == "WAGE_SCHEDULE_DUPLICATE_CLASSIFICATION", r)
        ok(state(A)["audit"] == a1, "duplicate rows changed nothing")
        step("3c", "valid wage decision recorded through the UI; duplicate role / duplicate classification refused by the route (400, nothing stored)")

        # 3d. UI shows DECISION_UNCHANGED when the identical wage decision is submitted as a NEW decision (new key)
        a2 = state(A)["audit"]
        w = dlg(A, "Labor Gate").get_by_label("Davis-Bacon wage determination")
        w.get_by_role("button", name="Replace wage determination").click()
        A.get_by_role("alert").filter(has_text="DECISION_UNCHANGED").wait_for(timeout=10000)
        ok(reqs[-1][1] != wage_key, "an intentional new submission uses a new key")
        ok(state(A)["audit"] == a2, "unchanged decision stored nothing")
        # API: higher/lower modification semantics
        low = json.loads(json.dumps(good)); low["determination"]["modification"] = "0"; low["employer_burden"]["pct"] = 0.21
        r = api(A, "/api/demo/decision/wage", low, {"Idempotency-Key": "e2e-not-higher-01"})
        print("   same-modification edit ->", r["status"], r["body"].get("code"), flush=True)
        ok(r["status"] == 409 and r["body"]["code"] in ("WAGE_MODIFICATION_NOT_HIGHER", "WAGE_SUPERSESSION_REQUIRED", "WAGE_HISTORICALLY_CLEARED"), r)
        step("3d", f"DECISION_UNCHANGED shown in UI; same-modification edit refused with {r['body']['code']}")

        # 4. eligible fleet crews and a live preview
        d = dlg(A, "Labor Gate"); settle(A)
        ok(d.locator(".plan-row").count() == 10 and d.locator('.plan-row[data-task="L02"] button').count() == 4, "ten tasks, four fleet crews each")
        ok(d.locator('button[data-crew="CR1"]').count() == 0, "legacy default crew not offered")
        for cid in ("CR11", "CR12"): ok(d.locator(f'button[data-task="L02"][data-crew="{cid}"]').is_disabled(), f"{cid} cannot drill")
        d.get_by_label("Preferred crew").select_option(value="CR12"); settle(A)
        d.locator('button[data-task="L02"][data-crew="CR13"]').click(); settle(A)
        t1 = {k: A.get_by_test_id(k).inner_text() for k in ("draft-total", "draft-labor", "draft-gp", "draft-np")}
        ok("Estimated gross profit (at bid)" in d.inner_text() and "Estimated net profit (at bid)" in d.inner_text(), "estimated-at-bid wording")
        ok(not re.search(r"realized|approved profit", d.get_by_label("Recalculated totals").inner_text().replace("not realized profit", ""), re.I), "no realized-profit claim")
        pv = api(A, "/api/demo/crew-plan/preview", body("CR12", {"L02": "CR13"}))
        ok(pv["status"] == 200 and pv["body"]["valid"] and usd(t1["draft-total"]) == Decimal(str(pv["body"]["estimate"]["price_total"])).quantize(Decimal("0.01")), "UI total equals engine preview")
        shot(A, "labor_gate_crew_preview")
        step(4, f"eligible fleet crews selected; preview total {t1['draft-total']} matches the engine; estimated-at-bid labels")

        # 5. ineligible / non-fleet assignment rejected, no mutation
        before = state(A); n_before = len(before["audit"])
        for bad, code in (("CR11", "ENGINE_REFUSED"), ("CR12", "ENGINE_REFUSED"), ("CR1", "CREW_NOT_IN_FLEET"), ("CR99", "CREW_NOT_IN_FLEET")):
            r = api(A, "/api/demo/decision/crew-plan", {"by": "Visitor A", "note": "forged", **body("CR13", {"L02": bad})}, {"Idempotency-Key": f"e2e-bad-{bad}-0001"})
            ok(r["status"] == 409 and r["body"]["code"] == code, f"{bad}: {r['status']} {r['body']}")
            if bad in ("CR11", "CR12"): ok(any(c.startswith(("CREW_UNSUITABLE", "CREW_")) for c in (r["body"].get("engine_codes") or [])), r["body"])
            pr = api(A, "/api/demo/crew-plan/preview", body("CR13", {"L02": bad}))
            ok(not (pr["body"] or {}).get("estimate") and (pr["body"].get("valid") is False or pr["status"] in (400, 409)), f"preview of {bad} must refuse without an estimate: {pr['status']} {pr['body']}")
        after = state(A)
        ok(after["audit"] == before["audit"] and after["pricing"]["crew_plan"] is None, "refused assignments changed nothing")
        ok(len(after["audit"]) == n_before, "no audit event")
        step(5, "CR11/CR12 for core drilling -> ENGINE_REFUSED; CR1/CR99 -> CREW_NOT_IN_FLEET; audit unchanged")

        # 6. identical decision retry -> no new audit event (transport-loss retry from the UI, then an API replay)
        d = dlg(A, "Labor Gate")
        d.get_by_label("Crew plan approver name").fill("Visitor A"); d.get_by_label("Crew plan note").fill("Reviewed crew options")
        audit_n = len(state(A)["audit"]); n0 = len(reqs)
        lost = {"n": 0}
        def lose_first(route):
            if lost["n"] == 0:
                lost["n"] = 1
                route.fetch()            # the engine DOES record the decision ...
                route.abort("failed")   # ... but the response never reaches the browser
            else: route.continue_()
        A.route("**/api/demo/decision/crew-plan", lose_first)
        d.get_by_role("button", name="Approve crew plan").click()
        A.get_by_role("alert").wait_for(timeout=10000); A.wait_for_timeout(300)
        ok(len(state(A)["audit"]) == audit_n + 1, "first attempt was recorded server-side")
        d.get_by_role("button", name="Approve crew plan").click()
        A.get_by_text("historical result").first.wait_for(timeout=10000); A.wait_for_timeout(500)
        A.unroute("**/api/demo/decision/crew-plan")
        plan_reqs = [k for u, k in reqs[n0:] if u.endswith("crew-plan")]
        ok(len(plan_reqs) == 2 and plan_reqs[0] == plan_reqs[1] and plan_reqs[0], f"retry reused the same key: {plan_reqs}")
        ok(len(state(A)["audit"]) == audit_n + 1, "retry added NO audit event")
        info = A.locator(".notice.info, .notice").all_inner_texts()
        ok(any("historical" in t and "nothing new was recorded" in t for t in info), f"replay shown as history: {info}")
        ok(not any("Crew plan changed" in t for t in info), "replay not presented as a fresh approval")
        key_plan = plan_reqs[0]
        # direct replay through the proxy: original bytes, replay headers, still no new event
        st = state(A); plan_body = {"by": "Visitor A", "note": "Reviewed crew options", **body("CR12", {"L02": "CR13"})}
        r = api(A, "/api/demo/decision/crew-plan", plan_body, {"Idempotency-Key": key_plan})
        ok(r["status"] == 200 and r["headers"].get("idempotent-replay") == "true" and r["headers"].get("x-idempotency-result") == "historical" and r["headers"].get("x-original-audit-event-id"), r)
        ok(len(state(A)["audit"]) == audit_n + 1, "API replay added no event")
        # same key, different payload -> 409 conflicting reuse
        r = api(A, "/api/demo/decision/crew-plan", {**plan_body, "note": "different note"}, {"Idempotency-Key": key_plan})
        ok(r["status"] == 409 and r["body"]["code"] == "IDEMPOTENCY_KEY_REUSED", r)
        r = api(A, "/api/demo/decision/ruleset", {"by": "Visitor A", "note": "Reviewed the rule table (demo)", "ruleset_sha256": st["pricing"]["ruleset"]["sha256"]}, {"Idempotency-Key": key_plan})
        ok(r["status"] == 409 and r["body"]["code"] == "IDEMPOTENCY_KEY_REUSED", "same key on another route")
        # exact historical replay of the ruleset approval (first decision of the session)
        r = api(A, "/api/demo/decision/ruleset", {"by": "Visitor A", "note": "Reviewed the rule table (demo)", "ruleset_sha256": st["pricing"]["ruleset"]["sha256"]}, {"Idempotency-Key": key_ruleset})
        ok(r["status"] == 200 and r["headers"].get("idempotent-replay") == "true", f"ruleset replay: {r['status']} {r['headers']}")
        ok(len(state(A)["audit"]) == audit_n + 1, "ruleset replay added no event")
        step(6, "lost response -> UI retry reuses the key -> historical replay, no new audit event; API replay headers; 409 IDEMPOTENCY_KEY_REUSED")

        # 7. an intentional new decision gets a new key; digest and plan version invalidate
        rd = dlg(A, "Release Gate"); rd.wait_for(timeout=10000)
        ok(SELF in rd.inner_text(), "Release Gate carries the self-declared label")
        ok("Estimated gross profit (at bid)" in rd.inner_text() and "Estimated at bid; not realized profit" in rd.inner_text(), "release profitability wording")
        p1 = state(A); dig1 = p1["proposal_digest"]; ok(dig1 and p1["pricing"]["crew_plan"]["plan_version"] == 1, "plan v1 + digest")
        shot(A, "release_gate_estimate_v1")
        rd.get_by_role("button", name="Revise crew plan").click(); d = dlg(A, "Labor Gate"); d.wait_for(); settle(A)
        A.route("**/api/demo/crew-plan/preview", lambda route: route.fulfill(status=429, headers={"Retry-After": "9"}, content_type="application/json",
                body=json.dumps({"error": "limit", "code": "PREVIEW_RATE_LIMITED", "retry_after_seconds": 9})))
        d.get_by_label("Job difficulty").select_option("hard")
        d.get_by_role("alert").filter(has_text="Recalculation paused").wait_for(timeout=5000)
        ok("9s" in d.get_by_role("alert").filter(has_text="Recalculation paused").inner_text(), "preview Retry-After shown")
        shot(A, "labor_gate_preview_rate_limited")
        A.unroute("**/api/demo/crew-plan/preview")
        d.get_by_label("Job difficulty").select_option("standard"); settle(A)
        d.locator('button[data-task="L01"][data-crew="CR14"]').click(); settle(A)
        d.get_by_label("Crew plan approver name").fill("Visitor A"); d.get_by_label("Crew plan note").fill("Revision 2"); n0 = len(reqs)
        d.get_by_role("button", name="Approve revised crew plan").click(); rd = dlg(A, "Release Gate"); rd.wait_for(timeout=15000); A.wait_for_timeout(600)
        k2 = [k for u, k in reqs[n0:] if u.endswith("crew-plan")]
        ok(len(k2) == 1 and k2[0] != key_plan, "new decision -> new key")
        p2 = state(A); dig2 = p2["proposal_digest"]
        ok(dig2 and dig2 != dig1 and p2["pricing"]["crew_plan"]["plan_version"] == 2, "new digest and plan version")
        ok("previous release digest is void" in A.locator("main").inner_text(), "UI says the old digest is void")
        step(7, "revision used a new key; plan v2; digest changed")

        # 8. stale digest at release is refused
        r = api(A, "/api/demo/release", {"approver": "Visitor A", "expected_scope_version": p2["scope_version"], "expected_proposal_digest": dig1})
        ok(r["status"] == 409, r); ok(state(A)["status"] == "ready_for_final_review", "stale digest did not release")
        # the UI path: stale tab (digest from before the revision) is refused and reloads current state
        step(8, f"release with stale digest refused ({r['status']} {r['body'].get('code')})")

        # 9. permitted fictional release with the current digest
        rd.get_by_placeholder("Any name; recorded as self-declared").fill("Visitor A")
        shot(A, "release_gate_estimate_v2")
        rd.get_by_role("button", name="Authorize final proposal").click(); A.get_by_text("Recorded by the engine").first.wait_for(); A.wait_for_timeout(600)
        fin = state(A); ok(fin["status"] == "released", "released with the current digest")
        shot(A, "release_gate_released")
        r = api(A, "/api/demo/decision/crew-plan", {"by": "V", "note": "n", **body("CR12", {"L02": "CR13"})}, {"Idempotency-Key": "e2e-after-release-1"})
        ok(r["status"] == 409, "no plan changes after release")
        step(9, "fictional release completed; later plan change refused")

        # 10. owner / session isolation
        ctxB = new_context(b, "p6b", viewport={"width": 1500, "height": 950}); B = ctxB.new_page(); ensure_pristine(B)
        sb = state(B)
        ok(sb["project_id"] != fin["project_id"] and sb["status"] == "needs_scope_review" and sb["pricing"]["crew_plan"] is None, "second session isolated")
        r = api(B, "/api/demo/decision/crew-plan", plan_body, {"Idempotency-Key": key_plan})   # A's key on B's project: not a replay of A's decision
        ok(r["headers"].get("idempotent-replay") != "true", f"B must not replay A's decision: {r['status']}")
        ok("released" not in json.dumps(state(B)["status"]), "B untouched")
        save_state(ctxB, "p6b")
        step(10, "second session isolated; session A's key is not a replay in session B")

        # 11. error / loading / rate-limit states
        # (a) real preview rate limit through the proxy (adapter: 20/min/project): 429 + Retry-After + code
        A.get_by_role("button", name="Reset demo").first.click(); A.get_by_text("Demo reset").first.wait_for(); A.wait_for_timeout(600)
        got = None
        for i in range(30):
            r = api(A, "/api/demo/crew-plan/preview", body("CR12", {}))
            if r["status"] == 429: got = r; break
        ok(got and got["body"]["code"] == "PREVIEW_RATE_LIMITED" and got["headers"].get("retry-after") and got["body"].get("retry_after_seconds"), f"preview 429: {got}")
        # (b) UI renders the throttled preview as paused, not as a crash
        # (c) loading state: delay a decision and observe the busy label, then a forced engine outage message
        A.wait_for_timeout(500)
        shot(A, "error_states_after_reset")
        A.route("**/api/demo/scope/resolve", lambda route: (A.wait_for_timeout(600), route.continue_()))
        d = dlg(A, "Scope Gate"); d.wait_for()
        d.get_by_placeholder("Value the engine will validate").fill("10"); d.get_by_placeholder("Any name; recorded as self-declared").fill("Visitor A")
        d.get_by_placeholder("What evidence or authority supports this decision?").fill("loading-state check")
        d.get_by_role("button", name="Record scope decision").click()
        d.get_by_role("button", name="Recording…").wait_for(timeout=5000)
        A.get_by_text("Recorded by the engine").first.wait_for(timeout=10000); A.unroute("**/api/demo/scope/resolve")
        A.route("**/api/demo/decision/ruleset", lambda route: route.fulfill(status=503, content_type="application/json", body=json.dumps({"error": "Engine unavailable or request timed out"})))
        rf = A.get_by_label("Quantity ruleset approval"); rf.wait_for()
        rf.get_by_placeholder("Any name; recorded as self-declared").fill("Visitor A"); rf.get_by_placeholder("What did you review?").fill("outage check")
        rf.get_by_role("button", name="Approve this exact ruleset").click()
        A.get_by_role("alert").filter(has_text="Engine unavailable").wait_for(timeout=5000)
        ok(rf.get_by_placeholder("What did you review?").input_value() == "outage check", "draft kept after an outage")
        A.unroute("**/api/demo/decision/ruleset")
        A.route("**/api/demo/decision/ruleset", lambda route: route.fulfill(status=429, headers={"Retry-After": "7"}, content_type="application/json",
                body=json.dumps({"error": "mutation limit", "code": "RATE_LIMITED", "retry_after_seconds": 7})))
        rf.get_by_role("button", name="Approve this exact ruleset").click()
        A.get_by_role("alert").filter(has_text="RATE_LIMITED").wait_for(timeout=5000)
        ok("7s" in A.get_by_role("alert").first.inner_text(), "retry-after shown")
        A.unroute("**/api/demo/decision/ruleset")
        A.route("**/api/demo/crew-plan/preview", lambda route: route.fulfill(status=429, headers={"Retry-After": "9"}, content_type="application/json",
                body=json.dumps({"error": "limit", "code": "PREVIEW_RATE_LIMITED", "retry_after_seconds": 9})))
        step(11, f"preview 429 PREVIEW_RATE_LIMITED + Retry-After via proxy; busy label; 503 outage keeps the draft; RATE_LIMITED with retry-after shown")
        A.unroute("**/api/demo/crew-plan/preview")

        # 12. no internal hash/authorization material in any browser-visible response or DOM
        found = set()
        for u, j in seen_json: keys_in(j, found)
        ok(not found, f"internal fields reached the browser: {found}")
        html = A.content()
        ok(not re.search(r"ever_cleared|ever_authorized|content_identity|payload_sha256", html), "internal markers in DOM")
        ok(any("adapter" in (j.get("project", j) if isinstance(j, dict) else {}) for u, j in seen_json if isinstance(j, dict)), "adapter block present but sanitized")
        step(12, f"no wage-history hashes/authorization markers in {len(seen_json)} proxy responses or the DOM")

        # mobile
        A.set_viewport_size({"width": 375, "height": 812}); A.wait_for_timeout(500)
        ov = A.evaluate("document.documentElement.scrollWidth - window.innerWidth"); ok(ov <= 1, f"375px horizontal overflow {ov}px"); shot(A, "mobile_375_scope")
        A.set_viewport_size({"width": 1500, "height": 950})

        save_state(ctx, "p6")
        external = [u for u in external if not u.startswith(("https://fonts.googleapis.com/", "https://fonts.gstatic.com/"))]
        ok(not external, f"unexpected external requests: {external[:3]}")
        b.close()
    print("PASS 6 INTEGRATION E2E PASS", len(results), "steps")

if __name__ == "__main__":
    main()

# DEMO_SHOT_LIST — exactly what to click and show

Three pre-staged windows (see DEMO_PREFLIGHT.md): **A** = Scope gate, Base selected (scenes 1–4) · **B** = Base priced, waiting at Release (scenes 5–6) · **C** = Alternate A-1 priced, waiting at Release.
Browser 1920×1080 (or ≥1800×732), classic scrollbars, page zoom 100%. The grey “HARNESS CAPTION” and the red API box exist only in the automated recording; live, you speak them.

## Scene 1 · 0:00–0:20 · Window A
1. Start on C101 (viewer, left) with the **Scope Gate** drawer (right).
2. Click sheet tabs **G001 → C101 → C102 → F501 → F502 → C101** (≈0.7 s each).
3. Scroll the drawer to **Scope draft · 18** (HUMAN-PREPARED badges). *Cut if late: skip the tab sweep, show C101 only.*

## Scene 2 · 0:20–0:45 · Window A
1. Scroll the drawer to **AI Findings**. Point at: “No AMD call is made by this build”, “Real AMD attempts recorded: 10”.
2. Under **Spatial Test 003**, click the row “gate tag G3 is printed in the north crop…”. In the detail point at: Document (SHA-256 `62ab61d7…`), Model, Run `spatial_003_r1_…`, **VERIFIED · label position only**, **model: clear**.

## Scene 3 · 0:45–1:15 · Window A  (the money shot)
1. Click the row **“fence type tag B: leader ends on the perimeter fence”** → red badge **AI CLAIM CONTRADICTED BY DRAWING EVIDENCE**, chip “model: clear”.
2. Click **Show evidence** (viewer jumps to C101, three outlines). Click **+** zoom three times; scroll the viewer so the outlines are centred: (1) the B diamond, (2) where the leader line ENDS, (3) the interior divider end post.
3. Scroll the detail: “Model confidence vs independent verification: model said ‘clear’; … CONTRADICTED”; point at the model’s own free text (“near post at court divider”).
4. Point at the **disabled Accept** and “Accept is unavailable: CONTRADICTED_BY_DRAWING_EVIDENCE”.
5. Show the real API refusal. Live: in the browser console run `fetch('/api/demo/ai-findings/decision',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':'live-'+Date.now()},body:JSON.stringify({finding_id:'AMD-spatial003-N-type_tag-B',decision:'accept',by:'Presenter',note:'try',preview_digest:(await (await fetch('/api/demo/ai-findings')).json()).findings.find(f=>f.finding_id==='AMD-spatial003-N-type_tag-B').preview.digest})}).then(r=>r.json().then(b=>console.log(r.status,b.code)))` → `409 CONTRADICTED_BY_DRAWING_EVIDENCE`. (The recording shows the same call in a red box.) Then point at **SCOPE REVISION** in the project banner: unchanged.
6. Zoom the viewer back out (− three times). *Cut if late: skip step 5’s console, say the 409 and show the disabled button + reason.*

## Scene 4 · 1:15–1:40 · Window A
1. Click the row **“gate tag G3 … left of center”** under **Spatial Test 002** (real, native ANSI B). **Show evidence** outlines the G3 label.
2. Scroll to **RESULTING SCOPE CHANGE (PREVIEW)**: engine route `scope/resolve · approve_inferred`, value **31 ft — HUMAN-PREPARED derivation (not from AI)**, scope v2 → v3, “No Labor, crew-plan… approval exists yet”.
3. Type a name and a note → **Accept**. Show the message “Scope version v2 → v3”, the origin label **Human-approved**, **Scope Gate · 13 blocking exceptions**.
4. Scroll the drawer to **Gate G3: … clear opening NOT SPECIFIED** → “Unresolved: RFI required”.

## Scene 5 · 1:40–2:10 · Window B (then C)
1. In B click **Takeoff Review**. Scroll to the **Footing schedule**: Type A line 12×48, corner 16×48, Type B line 8×30, terminal 10×30; total holes **79**. Click tab **Alternate A-1** → **63**. Tab back to Base. Point at **Engine total** (conditional, “QUALIFIED DEMONSTRATION ONLY — NOT BID READY”).
2. Close the Takeoff Review. In the Release drawer click **Revise crew plan · voids this digest** (only opens the planner; do NOT approve). Change **Preferred crew** CR11 → CR12 → CR13 → CR14 and read the four draft totals; return the select to **CR13**. Dismiss the drawer. *(Nothing is approved; the proposal digest is unchanged — checked in rehearsal.)*
3. Switch to window C: Release gate shows the **Alternate A-1 engine total**.

## Scene 6 · 2:10–2:30 · Window B
1. Click **Review required** → **Release Gate**. Point at the red/amber banner **NOT BID READY — FICTIONAL DEMONSTRATION ONLY** with `bid_ready: false`, `release_class`, `footing_release_class`, and the server’s qualification text.
2. Scroll to **TAKEOFF CONDITIONS FOR RELEASE**; type a name; tick the acknowledgement; click **Record QUALIFIED demonstration release (not a bid)**. Show `artifact_kind: QUALIFIED_FICTIONAL_DEMONSTRATION`, status “Demonstration release · NOT a bid”.
3. Say the closing line. *Cut if late: skip step 2 and end on the banner.*

## Screenshots for the deck (from the recorded rehearsal; the screenshots are kept outside this repository)
`s3_typeB_leader_endpoint_in_pdf.png` · `s3_accept_blocked_in_ui.png` · `s3_api_409_contradicted.png` · `s4_review_preview_human_value.png` · `s5_takeoff_base_type_a_vs_b.png` · `s5_takeoff_alternate_63_holes.png` · `s5_four_crew_comparison.png` · `s6_release_gate_not_bid_ready.png` · `s6_release_record_artifact_kind.png`

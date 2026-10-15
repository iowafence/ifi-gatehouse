#!/usr/bin/env python3
"""Builds the CORRECTIVE additive independent-audit record AUDIT-<run>-2 (schema gatehouse-independent-audit.v2).
It supersedes, but never edits, AUDIT-<run>-1: the earlier record stays on disk byte-identical and is pinned as SUPERSEDED in the release manifest.
Source: LOOM's own re-check report (evidence/independent_rechecks/...), identified by its sha256. The assessment is LOOM's; this record was transcribed by ANVIL 1 and each quote
was re-found in the stored PDF pages (and, where it has an excerpt id, in the package recorded in the run record). It is never a human decision.
Correction: Addendum 01 item 1.5 sits under 'ITEM 1 GATE G2 REVISED' and is G2-only. G3 post OD stays UNRESOLVED; G3 footing is SPECIFIED by 3/F501 (1'-4" dia x 4'-0" deep minimum).
Usage: tools/build_corrective_audit.py RUN_JSON CASES_DIR TRACE_JSON LOOM_REPORT_MD [OUT_DIR=dp001/independent_audits]
Nothing is written unless the target is new (audit records are additive and never rewritten)."""
import datetime, hashlib, json, pathlib, re, subprocess, sys

root = pathlib.Path(__file__).resolve().parent.parent
run_p, cases_d, trace_p, report_p = (pathlib.Path(a).expanduser() for a in sys.argv[1:5])
out_d = pathlib.Path(sys.argv[5]) if len(sys.argv) > 5 else root / "dp001" / "independent_audits"
sha = lambda b: hashlib.sha256(b).hexdigest()
def norm(s): return re.sub(r"\s+", " ", (s or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")).strip().lower()
def pages(path):
    run = lambda *a: subprocess.run(["pdftotext", *a, str(path), "-"], capture_output=True, check=True, timeout=60).stdout.decode("utf-8", "replace").split("\f")
    lay, raw = run("-layout"), run(); return [l + "\n" + r for l, r in zip(lay, raw)]

run_bytes = run_p.read_bytes(); run = json.loads(run_bytes); rid = run["run_id"]
report_bytes = report_p.read_bytes(); report_sha = sha(report_bytes)
pkg = json.loads(run["evolus_execution"]["input"]); ex = {e["excerpt_id"]: e for e in pkg["excerpts"]}
reg = {d["doc_id"]: d for d in json.loads((root / "dp001/document_registry.json").read_text())["documents"]}
pdf = {}
def page_text(doc_id, page):
    d = reg[doc_id]; f = root / "dp001/documents" / d["filename"]; assert sha(f.read_bytes()) == d["sha256"], f"{f.name}: stored PDF hash differs from the registry"
    return pdf.setdefault(doc_id, pages(f))[page - 1]
def ev(excerpt_id, role, applies_to, controlling=False, locator=None):
    e = ex[excerpt_id]; assert e["doc_sha256"] == reg[e["doc_id"]]["sha256"], f"{excerpt_id}: package document hash differs from the registry"
    assert norm(e["text"]) in norm(page_text(e["doc_id"], e["page"])), f"{excerpt_id}: quote not found in the stored PDF page"
    return {"excerpt_id": excerpt_id, "doc_id": e["doc_id"], "doc_sha256": e["doc_sha256"], "page": e["page"], "locator": locator or e["label"], "quote": e["text"], "role": role,
            "applies_to": applies_to, "controlling_document": controlling, "quote_found_in_stored_pdf": True}
def ev_pdf(doc_id, page, quote, locator, role, applies_to):  # a quote that is in the stored PDF but was not a package excerpt: no excerpt id, so it is PDF-verified here only
    assert norm(quote) in norm(page_text(doc_id, page)), f"{locator}: quote not found in the stored PDF page"
    return {"excerpt_id": None, "doc_id": doc_id, "doc_sha256": reg[doc_id]["sha256"], "page": page, "locator": locator, "quote": quote, "role": role, "applies_to": applies_to,
            "controlling_document": False, "quote_found_in_stored_pdf": True}

cases = {}
for c in sorted(cases_d.expanduser().glob("GH-CASE-*.json")):
    b = c.read_bytes(); j = json.loads(b)
    if j["run_id"] == rid: cases[j["draft"]["draft_id"]] = {"case_id": j["case_id"], "case_sha256": sha(b)}
assert set(cases) == {"D1", "D2"}, f"expected cases D1 and D2, found {sorted(cases)}"
trace = json.loads(trace_p.read_bytes()); assert trace["trace_id"] == run["gatehouse_trace_id"]
prior = out_d / f"AUDIT-{rid}-1.json"; assert prior.exists(), "the earlier audit record must be present (it is superseded, never replaced)"; prior_sha = sha(prior.read_bytes())
# the Addendum heading that scopes item 1.5 to G2 (read from the stored page, not assumed)
add_page = page_text("dp001_addendum_01_ansi_b_pkg", 1)
assert re.search(r"ITEM 1\s+GATE G2 REVISED", add_page) and re.search(r"1\.6\s+Gate G2 quantity", add_page), "Addendum item 1 heading / item 1.6 not found"

item15 = ev("X-b329609b45ee", "context", "G2", True, "Addendum 01 item 1.5 (under 'ITEM 1 GATE G2 REVISED'; items 1.1-1.4 and 1.6 name Gate G2)")
spec21b = ev("X-764fc2e6f5f4", "supports", "G3")
note4 = ev("X-fce6ee7cefa2", "supports", "G3")
add22 = ev("X-f976c8e99761", "supports", "G3", True)
f501 = ev("X-7c60ceb925b2", "controlling_contradicts", "G3", False, "F501 fence material schedule, FOOTING — TERMINAL / GATE (Type A)")
f502n5 = ev("X-1d37521bb671", "controlling_contradicts", "G3")
spec32d = ev("X-59e6227f81ad", "controlling_contradicts", "general")
f501min = ev_pdf("dp001_ansi_b_v2_drawings", 4, "DIAMETERS AND DEPTHS ARE MINIMUMS BELOW FINISH GRADE", "F501 footing note (minimums)", "context", "general")
g3detail = ev_pdf("dp001_ansi_b_v2_drawings", 5, "CORE-DRILLED FOOTING PER TERMINAL / GATE POST, 3/F501", "F502 G3 detail (service swing gate), footing callout", "controlling_contradicts", "G3")

dispositions = [
 {"issue_id": "I1", "draft_id": "D1", **cases["D1"], "disposition": "SUPPORTED", "subject_scope": "G3",
  "summary": "Supported. The clear opening width of Gate G3 remains unresolved: Addendum 01 item 2.2 states that it does not establish it, and the drawings say it is not specified.",
  "evidence": [add22, note4, ev("X-35cd8b5a13fa", "supports", "G3", False)],
  "verification_note": "LOOM re-check: supported. No document in the package supplies a G3 clear opening width. Unchanged from the earlier record."},
 {"issue_id": "I2", "draft_id": "D2", **cases["D2"], "disposition": "FLAGGED_UNSUPPORTED_BY_CONTROLLING_EVIDENCE", "subject_scope": "G3",
  "summary": "Flagged as written; kept as historical AI output and off the active shortlist. D2 asked for the Gate G3 post size AND footing as missing. The footing is NOT missing: the G3 detail and the general gate rule point to 3/F501, whose Type A terminal / gate footing is 1'-4\" dia. x 4'-0\" deep minimum. "
             "The G3 post outside diameter, however, IS still unresolved: Specification 2.1.B says G3 post size is confirmed with the opening width, and F502 note 4 says it is not specified. This flag does not mean the G3 post size is resolved.",
  "evidence": [f501, f502n5, spec32d, g3detail, f501min, spec21b, note4, item15, ev("X-c73f0ccdbf4a", "cited_by_original", "G3")],
  "verification_note": "Correction of the earlier record: Addendum 01 item 1.5 is G2-only (it sits under 'ITEM 1 GATE G2 REVISED' and continues the G2 revision) and is not applied to G3. Its 2.875 in OD is therefore not a determination of the G3 post OD. "
                       "The G3 schedule's 'FOOTING: SEE NOTE 4' reference is imprecise because note 4 concerns width and post size, but the same G3 detail points to 3/F501 and the general fallback (F502 note 5, 32 31 13 3.2.D) does too."},
 {"issue_id": "I3", "draft_id": None, "case_id": None, "case_sha256": None, "disposition": "SUPPORTED", "subject_scope": "G2",
  "summary": "Supported. Addendum 01 revises Gate G2 from a 6'-0\" single leaf to a 12'-0\" double leaf; the original specification schedule shows 6'-0\".",
  "evidence": [ev("X-61df2b0e0b11", "supports", "G2", True), ev("X-17dc72acddcd", "context", "G2")],
  "verification_note": "LOOM re-check: supported. No RFI draft was produced for I3, so there is no case."}]

scope_findings = [
 {"item": "G3_CLEAR_OPENING_WIDTH", "label": "Gate G3 clear opening width", "status": "UNRESOLVED", "value": None,
  "basis": "Addendum 01 item 2.2 does not establish it; F502 note 4 and the C102 schedule say it is not specified and must not be assumed.", "evidence_excerpt_ids": [add22["excerpt_id"], note4["excerpt_id"], "X-35cd8b5a13fa"]},
 {"item": "G3_POST_OD", "label": "Gate G3 post outside diameter", "status": "UNRESOLVED", "value": None,
  "basis": "Specification 2.1.B: G3 post size is confirmed with the opening width. F502 note 4: G3 post size is not specified. Addendum 01 item 1.5 (2.875 in OD) is under 'Gate G2 revised' and is not extended to G3 without explicit controlling evidence.",
  "evidence_excerpt_ids": [spec21b["excerpt_id"], note4["excerpt_id"], item15["excerpt_id"]]},
 {"item": "G3_FOOTING", "label": "Gate G3 terminal / gate footing", "status": "SPECIFIED", "value": "1'-4\" dia. x 4'-0\" deep minimum (Type A, 3/F501)",
  "basis": "The G3 detail calls for a core-drilled footing per terminal / gate post, 3/F501; F502 note 5 and 32 31 13 3.2.D give the same fallback; the F501 schedule gives the Type A dimensions and F501 states diameters and depths are minimums.",
  "evidence_excerpt_ids": [f501["excerpt_id"], f502n5["excerpt_id"], spec32d["excerpt_id"]]}]

clarification = {
 "clarification_id": f"PC-{rid}-G3-POST-OD", "topic": "Gate G3 post outside diameter", "derived_from_issue": "I2",
 "status": "PROPOSED_NOT_APPROVED", "approved": False, "sent": False, "evolus_generated": False, "requires_named_human_review": True,
 "authorship": {"kind": "DRAFTED_BY_ANVIL_1_FROM_LOOM_RECOMMENDATION",
                "description": "Wording drafted by ANVIL 1 from LOOM's recommendation to keep a narrow G3 post-OD clarification open. It is not an Evolus- or Gemma-generated case, it is not LOOM's wording, and no person has reviewed, approved or sent it."},
 "question": "Please confirm the outside diameter of the Gate G3 gate posts. Specification 32 31 13 paragraph 2.1.B says G3 post size is confirmed with the opening width, Sheet F502 note 4 says G3 post size is not specified, "
             "and Addendum 01 item 2.2 does not establish the G3 clear opening width. Addendum 01 item 1.5 concerns Gate G2 and has not been applied to G3. This may be answered together with the pending G3 clear opening width question.",
 "unresolved_requirements": ["Gate G3 post outside diameter"],
 "excluded_because_specified": ["Gate G3 footing diameter and depth: specified by 3/F501 (1'-4\" dia. x 4'-0\" deep minimum); not part of this clarification"],
 "evidence_excerpt_ids": [spec21b["excerpt_id"], note4["excerpt_id"], add22["excerpt_id"], item15["excerpt_id"]]}

drops = run["dropped_unverifiable_excerpts"]; prior_a = json.loads(prior.read_text())
assert prior_a["drops_correction"]["count"] == len(drops) == 6
audit = {
 "schema": "gatehouse-independent-audit.v2", "audit_id": f"AUDIT-{rid}-2", "supersedes": f"AUDIT-{rid}-1", "created_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
 "additive": True, "is_human_decision": False,
 "auditor": {"name": "LOOM", "role": "independent evidence auditor", "reported_verdict": "FAIL — judge publication blocked (re-check of the first remediation)"},
 "source": {"kind": "independent_report", "report_file": report_p.name, "report_sha256": report_sha,
            "description": "LOOM's own independent re-check report, identified by sha256. The assessment is LOOM's; this record was transcribed from it by ANVIL 1, which re-read the cited pages of the stored PDFs. The report is not a human approval or rejection of anything."},
 "human_authorization": {"status": "NONE_RECORDED", "note": "This is an automated audit assessment. It is not a human approval, rejection or completed human decision."},
 "subject": {"gatehouse_trace_id": run["gatehouse_trace_id"], "run_id": rid, "run_sha256": sha(run_bytes), "execution_id": run["execution_id"], "trace_sha256": sha(trace_p.read_bytes()),
             "original_validator_status": run["status"], "original_validator_status_preserved": True},
 "dispositions": dispositions, "scope_findings": scope_findings, "proposed_clarifications": [clarification],
 "drops_correction": prior_a["drops_correction"],
 "verification": {"by": "ANVIL 1 (stored-document reading, no external call)", "supersedes_sha256": prior_sha,
                  "documents": [{"doc_id": k, "sha256": reg[k]["sha256"]} for k in sorted(pdf)],
                  "method": "Each quote was taken verbatim from the package excerpts recorded in the run record (or, where marked, from the stored PDF page) and found again in the stored PDF page text."}}
out_d.mkdir(parents=True, exist_ok=True); out = out_d / f"{audit['audit_id']}.json"
if out.exists(): sys.exit(f"REFUSING: {out} exists (audit records are additive and never rewritten)")
out.write_text(json.dumps(audit, indent=1, sort_keys=True, ensure_ascii=False) + "\n"); print("wrote", out, sha(out.read_bytes()))

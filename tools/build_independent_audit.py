#!/usr/bin/env python3
"""Builds the ADDITIVE independent-audit record for a stored Evolus run (dp001/independent_audits/AUDIT-<run>-<n>.json).
It never modifies the run record, the cases or the traces: it only READS them (and the stored PDFs) and writes one new file. It refuses to overwrite an existing record.
Quotes are copied verbatim from the run record's own package excerpts (what the model was given) and re-verified in the stored PDF page text (same normalisation as the adapter).
The dispositions are the findings reported by LOOM (relayed in the owner's 2026-10-14 assignment; LOOM's own report file was not available here); this script records them with
their evidence and ANVIL 1's independent confirmation. They are an assessment, never a human approval or rejection.
Usage: tools/build_independent_audit.py RUN_JSON CASES_DIR TRACE_JSON [OUT_DIR=dp001/independent_audits]"""
import datetime, hashlib, json, pathlib, re, subprocess, sys

root = pathlib.Path(__file__).resolve().parent.parent
run_p, cases_d, trace_p = (pathlib.Path(a).expanduser() for a in sys.argv[1:4])
out_d = pathlib.Path(sys.argv[4]) if len(sys.argv) > 4 else root / "dp001" / "independent_audits"
sha = lambda b: hashlib.sha256(b).hexdigest()
def norm(s): return re.sub(r"\s+", " ", (s or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")).strip().lower()
def pages(path):
    run = lambda *a: subprocess.run(["pdftotext", *a, str(path), "-"], capture_output=True, check=True, timeout=60).stdout.decode("utf-8", "replace").split("\f")
    lay, raw = run("-layout"), run(); return [l + "\n" + r for l, r in zip(lay, raw)]

run_bytes = run_p.read_bytes(); run = json.loads(run_bytes); rid = run["run_id"]
pkg = json.loads(run["evolus_execution"]["input"]); ex = {e["excerpt_id"]: e for e in pkg["excerpts"]}
reg = {d["doc_id"]: d for d in json.loads((root / "dp001/document_registry.json").read_text())["documents"]}
pdf = {}
def verified(excerpt_id):
    e = ex[excerpt_id]; d = reg[e["doc_id"]]
    assert e["doc_sha256"] == d["sha256"], f"{excerpt_id}: package document hash differs from the registry"
    f = root / "dp001/documents" / d["filename"]; assert sha(f.read_bytes()) == d["sha256"], f"{f.name}: stored PDF hash differs from the registry"
    pg = pdf.setdefault(d["doc_id"], pages(f)); assert norm(e["text"]) in norm(pg[e["page"] - 1]), f"{excerpt_id}: quote not found in the stored PDF page"
    return e
def ev(excerpt_id, role, controlling=False):
    e = verified(excerpt_id)
    return {"excerpt_id": excerpt_id, "doc_id": e["doc_id"], "doc_sha256": e["doc_sha256"], "page": e["page"], "locator": e["label"], "quote": e["text"], "role": role,
            "controlling_document": controlling, "quote_found_in_stored_pdf": True}

cases = {}
for c in sorted(cases_d.expanduser().glob("GH-CASE-*.json")):
    b = c.read_bytes(); j = json.loads(b)
    if j["run_id"] == rid: cases[j["draft"]["draft_id"]] = {"case_id": j["case_id"], "case_sha256": sha(b)}
assert set(cases) == {"D1", "D2"}, f"expected cases D1 and D2, found {sorted(cases)}"
trace = json.loads(trace_p.read_bytes()); assert trace["trace_id"] == run["gatehouse_trace_id"]

dispositions = [
 {"issue_id": "I1", "draft_id": "D1", **cases["D1"], "disposition": "SUPPORTED",
  "summary": "Supported. The clear opening width of Gate G3 remains unresolved: Addendum 01 item 2.2 states that it does not establish it, and the drawings say it is not specified.",
  "evidence": [ev("X-f976c8e99761", "supports", True), ev("X-fce6ee7cefa2", "supports"), ev("X-35cd8b5a13fa", "supports")],
  "verification_note": "ANVIL 1 independent check: confirmed. No document in the package supplies a G3 clear opening width."},
 {"issue_id": "I2", "draft_id": "D2", **cases["D2"], "disposition": "FLAGGED_UNSUPPORTED_BY_CONTROLLING_EVIDENCE",
  "summary": "Unsupported as written. The original citations were genuine, but the conclusion omitted controlling Addendum 01 item 1.5, which states the gate post size and footing, and F502 note 5 / 32 31 13 3.2.D, which set gate posts and footings not otherwise noted as for terminal posts, Detail 3/F501.",
  "evidence": [ev("X-b329609b45ee", "controlling_contradicts", True), ev("X-1d37521bb671", "controlling_contradicts"), ev("X-59e6227f81ad", "controlling_contradicts"), ev("X-7c60ceb925b2", "controlling_contradicts"),
               ev("X-764fc2e6f5f4", "context"), ev("X-c73f0ccdbf4a", "cited_by_original")],
  "verification_note": "ANVIL 1 independent check: confirmed as written. Footing: Addendum 01 item 1.5, F502 note 5, 32 31 13 3.2.D and the F501 terminal / gate footing row (1'-4\" dia. x 4'-0\" deep) establish it, so D2's footing questions are already answered. Post size: Addendum 01 item 1.5 states 2.875 in OD; note that item 1.5 sits under Item 1 (Gate G2 revised) and 32 31 13 2.1.B (context, above) says G3 post size is confirmed with the opening width, which D1 shows is still unresolved. A person should read item 1.5 against G3 before relying on either side."},
 {"issue_id": "I3", "draft_id": None, "case_id": None, "case_sha256": None, "disposition": "SUPPORTED",
  "summary": "Supported. Addendum 01 revises Gate G2 from a 6'-0\" single leaf to a 12'-0\" double leaf; the original specification schedule shows 6'-0\".",
  "evidence": [ev("X-61df2b0e0b11", "supports", True), ev("X-17dc72acddcd", "context")],
  "verification_note": "ANVIL 1 independent check: confirmed. No RFI draft was produced for I3, so there is no case."}]

drops = run["dropped_unverifiable_excerpts"]
scope = json.loads((root / "dp001/scope_dp001_footing.json").read_text())
def walk(o):
    if isinstance(o, dict):
        if "excerpt" in o and "doc_id" in o and "page" in o: yield o
        for v in o.values(): yield from walk(v)
    elif isinstance(o, list):
        for v in o: yield from walk(v)
human = [o for o in walk(scope) if o["doc_id"] not in reg]
assert len(human) == len(drops) == sum(1 for d in drops if d["doc_id"] == "human") == 6, "the dropped entries are not exactly the six human-prepared notes"
audit = {
 "schema": "gatehouse-independent-audit.v1", "audit_id": f"AUDIT-{rid}-1", "created_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
 "additive": True, "is_human_decision": False,
 "auditor": {"name": "LOOM", "role": "independent evidence auditor", "reported_verdict": "EVIDENCE INTEGRITY: PARTIAL"},
 "source": {"kind": "relayed_report", "description": "LOOM's findings as relayed in the owner's 2026-10-14 ANVIL 1 assignment (REMEDIATE LOOM EVIDENCE AUDIT FINDINGS). LOOM's own report file was not available to Gatehouse; each finding below was independently re-checked by ANVIL 1 against the stored package, documents and records."},
 "human_authorization": {"status": "NONE_RECORDED", "note": "This is an automated audit assessment. It is not a human approval, rejection or completed human decision."},
 "subject": {"gatehouse_trace_id": run["gatehouse_trace_id"], "run_id": rid, "run_sha256": sha(run_bytes), "execution_id": run["execution_id"], "trace_sha256": sha(trace_p.read_bytes()),
             "original_validator_status": run["status"], "original_validator_status_preserved": True},
 "dispositions": dispositions,
 "drops_correction": {"count": len(drops), "original_reason_code": "EXCERPT_NOT_FOUND_IN_SOURCE_PDF_TEXT",
   "explanation": "The six omitted entries are human-prepared arithmetic or dimension notes on Alternate A-1 (document id 'human', not a registered document). They were omitted by the package builder before submission to the model. They are not PDF quotations that failed text verification, and the model never saw them. The reason code recorded by the builder is generic.",
   "entries": [{"doc_id": o["doc_id"], "text": o["excerpt"][:200]} for o in human]},
 "verification": {"by": "ANVIL 1 (stored-document reading, no external call)", "documents": [{"doc_id": k, "sha256": reg[k]["sha256"]} for k in sorted(pdf)],
                  "method": "Each quote was taken verbatim from the package excerpts recorded in the run record and found again in the stored PDF page text."}}
out_d.mkdir(parents=True, exist_ok=True); out = out_d / f"{audit['audit_id']}.json"
if out.exists(): sys.exit(f"REFUSING: {out} exists (audit records are additive and never rewritten)")
out.write_text(json.dumps(audit, indent=1, sort_keys=True, ensure_ascii=False) + "\n"); print("wrote", out, sha(out.read_bytes()))

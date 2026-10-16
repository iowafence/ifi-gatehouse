#!/usr/bin/env python3
"""DP-001 verification run, rebuilt from the owner's verification inputs of 2026-10-16 2:15 PM CT and nothing else:
  labor   pinned-workbook crews CR1-CR4 (each task's workbook default crew), workbook production rates, standard difficulty, 35% burden (wages only);
          wage = workbook role rate if >= the Attachment A floor, else the floor, flagged
  braces  one band per side, two per assembly (ruleset 1.2.1)
  payroll certified-payroll administration is charged only if the pinned workbook carries the line (it is searched here; absent => not charged)
  gates   owner decision #4 (assembly per LF of clear opening); tax 0% (SC-3.6.1); no allowances
Addendum 02 is applied from the RECORDED capture of the live parse (verbatim reply), accepted by "John Doe (test)". Every human step is "John Doe (test)".
Writes the INPUTS (data, safe to publish) and, separately, the engine's line-level output with totals (hold until the key's revision is posted)."""
import argparse, copy, json, pathlib, re, sys, zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import addendum_intake as ai, labor_inputs, wage_rows, workflow as wf  # noqa: E402
from pricing import ratebook as pratebook  # noqa: E402
from tests import footing_helpers as H  # noqa: E402

JD = "John Doe (test)"
SCHEDULE = [dict(classification="Laborer, common or general", base_rate=24.50, fringe_rate=9.10),
            dict(classification="Power equipment operator, skid steer", base_rate=29.80, fringe_rate=11.25),
            dict(classification="Cement mason, concrete finisher", base_rate=28.40, fringe_rate=10.70)]     # FDB-DP001 Attachment A as already used in the tests
MAPPING = {"R1": "Laborer, common or general", "R2": "Laborer, common or general", "R3": "Laborer, common or general", "R4": "Power equipment operator, skid steer"}
WORKBOOK = ROOT / "samples/public-demo/reference_pricing_workbook_v2_3_0.fictional.xlsx"


def workbook_mentions(words=("certified", "payroll")):
    z = zipfile.ZipFile(WORKBOOK)
    hits = []
    for n in z.namelist():
        if n.startswith("xl/") and n.endswith(".xml"):
            txt = re.sub(r"<[^>]+>", " ", z.read(n).decode("utf-8", "replace")).lower()
            hits += [(n, w) for w in words if w in txt]
    return hits, sum(1 for n in z.namelist() if n.startswith("xl/worksheets/sheet"))


def build(addendum_pdf):
    scope = json.loads((ROOT / "dp001/scope_dp001_footing.json").read_text())
    st = wf.start(copy.deepcopy(scope), None, ratebook=H.book(), policy={"as_of": H.AS_OF})
    rec = ai.submit_addendum(st, pathlib.Path(addendum_pdf).read_bytes(), "ADDENDUM_02.pdf", parser=ai.recorded_parser, by=JD)
    assert rec["status"] == ai.PROPOSED, (rec["status"], rec["message"])
    ai.accept_addendum_intake(st, intake_id=rec["intake_id"], by=JD, note="TEST acceptance of the recorded Addendum 02 parse", scope_version=st["scope"]["scope_version"], proposal_digest=None)
    bl = lambda: [e for e in st["exceptions"] if e["severity"] == "blocking"]
    wf.resolve(st, next(e for e in bl() if e["code"] == "BID_SELECTION_REQUIRED")["exception_id"], option_id="base", by=JD, note="TEST: base bid selected")
    while True:
        inf = [e for e in bl() if e["code"] == "INFERRED_FACT_UNAPPROVED"]
        if not inf:
            break
        wf.resolve(st, inf[0]["exception_id"], option_id="approve_inferred", by=JD, note="TEST: derivation checked")
    wf.approve_quantity_ruleset(st, by=JD, note="TEST approval of the draft ruleset", ruleset_sha256=st["ruleset"]["sha256"])
    hits, nsheets = workbook_mentions()
    admin = ({"basis": "not_charged", "reason": f"the pinned workbook carries no certified-payroll administration line (searched {nsheets} sheets for 'certified' and 'payroll': {len(hits)} hits)",
              "source_ref": "pinned workbook reference_pricing_workbook_v2_3_0, owner verification input 3"} if not hits else None)
    if admin is None:
        raise SystemExit(f"the workbook mentions certified payroll ({hits}); a person must say which line to charge")
    rows = wage_rows.rows_from_workbook(st["ratebook"], SCHEDULE, MAPPING, "FDB-DP001 mod 0 Att. A")
    wf.record_wage_determination(st, by=JD, note="TEST wage affirmation: workbook rate if at or above the Attachment A floor, else the floor (flagged)",
                                 determination=dict(decision_id="FDB-DP001", modification="0", date="2026-10-05", valid_through="2026-12-31", source_ref="Section 00 0800 Att. A"),
                                 schedule=SCHEDULE, rows=rows, employer_burden={"pct": wage_rows.burden_pct(st["ratebook"]), "source_ref": "pinned workbook Roles burden_pct (taxes)"},
                                 production_rates_approved=True, certified_payroll_admin=admin)
    wf.approve_crew_plan(st, by=JD, note="TEST: the pinned workbook's default crews CR1-CR4, standard difficulty; not the owner's real crew plan", preferred_crew=None, assignments={},
                         use_default_for_unassigned=True, difficulty={"default": "standard", "overrides": {}})
    assert st["status"] == wf.READY, (st["status"], [e["code"] for e in bl()])
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--addendum", default=str(pathlib.Path.home() / "Downloads/ADDENDUM_02.pdf"))
    ap.add_argument("--inputs-out", required=True)
    ap.add_argument("--lines-out", required=True)
    ap.add_argument("--allocation-out", help="write the engine's item 10-16 ALLOC-V1 allocation (both scenarios)")
    ap.add_argument("--crew-matrix-out", help="write the crew matrix, FLEET crews only (the served view)")
    ap.add_argument("--baseline-matrix-out", help="write the matrix for ALL workbook crews incl. CR1-CR4: an engine-math baseline only, never the served view")
    a = ap.parse_args()
    st = build(a.addendum)
    d = labor_inputs.dump(st)
    import subprocess
    d["run"]["engine_commit"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    d["run"]["engine_tree_clean"] = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip() == ""
    d["run"]["which_run"] = "DP-001 verification run rebuilt from the owner's 2:15 PM CT inputs (see scripts/dp001_verification_run.py); disposable in-memory project; every human step 'John Doe (test)'"
    d["verification_inputs"] = {"crews": "pinned-workbook default crew per task (CR1-CR4); not CR13", "production": "workbook crew options (crew production rates), crew efficiency 100, difficulty standard",
                                "burden": "35% (workbook), wages only", "wage": "workbook role rate if >= Attachment A floor else floor, flagged",
                                "brace_bands": "one per side, two per assembly (ruleset 1.2.1)", "classification_mapping": MAPPING,
                                "certified_payroll_admin": d["certified_payroll_admin"]}
    pathlib.Path(a.inputs_out).write_text(json.dumps(d, indent=1) + "\n")
    ests = st["estimate"]["scenarios"]
    def pick(rows, keys):
        return [{k: r.get(k) for k in keys} for r in rows]
    lines = {sref: {"scope_ref": sref,
                    "materials": pick(e["materials"]["lines"], ("item_id", "description", "uom", "quantity", "overage_pct", "order_quantity", "unit_price", "extended", "tax_exempt", "gate_id", "clear_width_ft", "gate_quantity")),
                    "materials_subtotal": e["materials"]["subtotal"],
                    "sales_tax": e["sales_tax"],
                    "services": pick(e["services"]["lines"], ("service_id", "description", "uom", "quantity", "unit_cost", "extended")), "services_subtotal": e["services"]["subtotal"],
                    "labor": pick(e["labor"]["lines"], ("task_id", "task", "driver_key", "uom", "quantity", "crew_id", "production_rate", "effective_production", "crew_hours", "worker_hours", "crew_rate_per_hr", "wages", "fringe", "employer_costs", "extended")),
                    "labor_subtotal": e["labor"]["subtotal"], "certified_payroll_admin": (e["labor"].get("certified_payroll_admin") or {}).get("extended"),
                    "equipment": pick(e["equipment"]["lines"], ("equip_id", "equipment", "basis", "rate", "units", "extended")), "equipment_subtotal": e["equipment"]["subtotal"],
                    "mobilization": pick(e["mobilization"]["lines"], ("line_id", "item", "basis", "unit_cost", "quantity", "extended")), "mobilization_subtotal": e["mobilization"]["subtotal"],
                    "direct_cost": e["direct_cost"], "overhead": e["overhead"], "contingency": e["contingency"], "subtotal_before_profit": e["subtotal_before_profit"],
                    "profit": e["profit"], "price_total": e["price_total"]} for sref, e in ests.items()}
    pathlib.Path(a.lines_out).write_text(json.dumps(lines, indent=1) + "\n")
    if a.allocation_out:
        from engine import bid_schedule
        pathlib.Path(a.allocation_out).write_text(json.dumps(bid_schedule.view(st), indent=1) + "\n")
    if a.crew_matrix_out:
        from engine import crew_matrix
        pathlib.Path(a.crew_matrix_out).write_text(json.dumps(crew_matrix.build(st), indent=1) + "\n")
    if a.baseline_matrix_out:
        from engine import crew_matrix
        pathlib.Path(a.baseline_matrix_out).write_text(json.dumps(crew_matrix.build(st, include_non_fleet=True), indent=1) + "\n")
    print("inputs written; line-level output written (withheld). reproduces all:", all(all(t["reproduces"].values()) for s in d["scenarios"].values() for t in s["tasks"]))


if __name__ == "__main__":
    main()

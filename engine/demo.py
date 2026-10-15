"""End-to-end demo of the three human gates (fictional fixture, example rates). Run: python -m engine.demo"""
import json, pathlib
from . import workflow as wf

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    scope = json.load(open(ROOT / "samples/scope_synthetic.json"))
    rates_path = ROOT / "config/rates.local.json"
    rates = json.load(open(rates_path if rates_path.exists() else ROOT / "config/rates.example.json"))

    s = wf.start(scope, rates)
    print(f"STATUS: {s['status']}  ({rates['profile'][:40]}...)")
    print("\n== SCOPE GATE: the engine refuses to guess ==")
    for e in s["exceptions"]:
        print(f"[{e['severity'].upper():8}] {e['code']:24} {e['question']}")
    assert s["estimate"] is None, "no estimate may exist while blockers are open"

    print("\n-- reviewer resolves (illustrative choices) --")
    for ex_id, opt in [("EX-BID_SELECTION_REQUIRED-/bid_structure/selected_bid", "base"),
                       ("EX-PLAN_SPEC_CONFLICT-/fence_runs/1/height_ft", "v:3.5"),
                       ("EX-PLAN_SPEC_CONFLICT-/accessories/1/applies_to_gates", "v:no")]:
        s = wf.resolve(s, ex_id, option_id=opt, by="Demo Reviewer", note="illustrative choice")
        print(f"resolved {ex_id.split('-',2)[1]:22} -> scope v{s['scope']['scope_version']}  status={s['status']}")

    print("\n== reconciliation (derived from plans vs stated table) ==")
    for r in s["reconciliation"]:
        print(f"  #{r['item_no']:<3}{r['description']:<36}{r['derived_qty']:>8} vs {r['stated_qty']:>6}  {r['status']}")
    print("\n== LABOR GATE: no price exists until a wage basis is documented ==")
    print("status:", s["status"], "| estimate:", s["estimate"])
    s = wf.approve_labor(s, by="Demo Reviewer", decision="human_assumption_with_qualification",
                         certified_payroll="unknown", note="demo only, not a legal determination",
                         applicability_review="No wage schedule in the fictional documents; applicability not verified",
                         qualification="Pricing uses example company rates subject to confirmation of wage obligations")
    est = s["estimate"]
    print("\n== estimate (EXAMPLE RATES) ==")
    for p in est["pay_items"]:
        print(f"  #{p['item_no']:<3}{p['description']:<36}{p['qty']:>8} {p['unit']:<3} ${p['price']:>10,.2f}  (${p['unit_price']}/{p['unit']})")
    print(f"  COGS ${est['cogs']['total']:,.2f}   price ${est['price_total']:,.2f}   COGS/LF ${est['cogs_per_lf']}")

    print("\n== RELEASE GATE ==")
    print("status before approval:", s["status"], "| digest:", s["proposal_digest"][:16] + "...")
    pkg = wf.release(s, approver="Demo Approver", expected_scope_version=s["scope"]["scope_version"],
                     expected_proposal_digest=s["proposal_digest"], note="demo")
    print("released at scope version", pkg["scope_version"], "| audit events:", len(pkg["audit"]),
          "| qualifications:", len(pkg["qualifications"]))


if __name__ == "__main__":
    main()

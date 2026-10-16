"""Engine vs key for owner decision #4 (complete furnished gate assembly per LF of clear opening).

The key side here is an independent Decimal recomputation from first principles: the engine priced WITHOUT the override (the pinned
workbook lines), minus the 14 replaced material lines, plus rate x scope clear width x gate quantity per gate, then the markup chain.
Nothing in the key reads the override's own output to decide what it should be."""
import copy
import json
import unittest
from decimal import Decimal as D, ROUND_HALF_UP

from engine import bid_schedule as bs, integration, ratebook_mode as rm
from pricing import engine as pe, quantities
from pricing.engine import GATE_OVERRIDE_IDS
from tests import footing_helpers as H

FINAL_REPLACED = {"M21", "M22", "M28", "M29", "M30", "M31", "M32", "M33", "M34", "M35", "M36", "M37", "M43", "M44"}    # the owner's final set
KEPT_WHOLE = ("M01", "M06", "M08", "M09", "M10", "M12", "M14", "M16", "M40")
RATE = D("250.00")
c = lambda x: x.quantize(D("0.01"), rounding=ROUND_HALF_UP)
d = lambda x: D(str(x))


def without_override(state):
    return pe.price_scenarios(state["quantities"], state["ratebook"], labor_basis=state["labor_review"], as_of=rm.as_of(state), crew_plan=state.get("crew_plan"),
                              expected_scope_version=state["scope"]["scope_version"], max_ratebook_age_days=state["policy"].get("max_ratebook_age_days"))


def key_total(old, scope, mk):
    """The key's price for one scenario from the un-overridden estimate `old` (a scenario dict) and the scope's gates."""
    removed = [l for l in old["materials"]["lines"] if l["item_id"] in FINAL_REPLACED]
    removed_ext = sum((d(l["extended"]) for l in removed), D(0))
    removed_taxable = sum((d(l["extended"]) for l in removed if not l["tax_exempt"]), D(0))
    new = D(0)
    for g in scope["gates"]:
        w, q = d(g["clear_width_ft"]["value"]), d(g["quantity"]["value"] if isinstance(g["quantity"], dict) else g["quantity"])
        new += c(RATE * w * q)                                     # complete assembly: full clear width, no per-leaf multiplier, 0% tax
    mat = d(old["materials"]["subtotal"]) - removed_ext + new
    taxable = d(old["sales_tax"]["taxable_base"]) - removed_taxable
    tax = c(taxable * d(mk["tax_materials_pct"]))
    adm = d((old["labor"].get("certified_payroll_admin") or {}).get("extended") or 0)
    direct = mat + tax + d(old["services"]["subtotal"]) + d(old["labor"]["subtotal"]) + adm + d(old["equipment"]["subtotal"]) + d(old["mobilization"]["subtotal"])
    oh, ct = c(direct * d(mk["overhead_pct"])), c(direct * d(mk["contingency_pct"]))
    sub = direct + oh + ct
    return direct, sub + c(sub * d(mk["profit_pct"])), new, removed_ext


class EngineVsKey(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = H.priced()
        cls.old = without_override(cls.st)
        cls.scopes = quantities.scenario_scopes(cls.st["scope"])
        cls.mk = cls.st["ratebook"]["markups"]

    def test_the_engine_total_equals_the_independent_key_for_base_and_alternate(self):
        for sref in ("BASE", "ALT-A1"):
            direct, total, new, removed = key_total(self.old["scenarios"][sref], self.scopes[sref], self.mk)
            e = self.st["estimate"]["scenarios"][sref]
            self.assertEqual(d(e["direct_cost"]), direct, sref)
            self.assertEqual(d(e["price_total"]), total, sref)
            self.assertNotEqual(removed, 0)                                    # something real was replaced

    def test_replaced_set_is_exactly_the_owners_final_set_and_gone_from_the_estimate(self):
        from pricing.engine import REPLACED_GATE_MATERIALS
        self.assertEqual(set(REPLACED_GATE_MATERIALS), FINAL_REPLACED)
        for sref, e in self.st["estimate"]["scenarios"].items():
            ids = {l["item_id"] for l in e["materials"]["lines"]}
            self.assertFalse(ids & FINAL_REPLACED, sref)
            self.assertTrue(set(GATE_OVERRIDE_IDS.values()) <= ids)

    def test_kept_lines_are_untouched_whole_and_unsplit(self):
        for sref, e in self.st["estimate"]["scenarios"].items():
            new = {l["item_id"]: l for l in e["materials"]["lines"]}
            old = {l["item_id"]: l for l in self.old["scenarios"][sref]["materials"]["lines"]}
            for k in KEPT_WHOLE:
                self.assertEqual(new[k], old[k], f"{sref} {k} must be carried whole")                 # identical line: no gate-post share split out
            self.assertEqual(e["labor"]["lines"], self.old["scenarios"][sref]["labor"]["lines"])        # install labor unchanged (L08 included)
            self.assertEqual(e["services"], self.old["scenarios"][sref]["services"])
            self.assertEqual(e["mobilization"], self.old["scenarios"][sref]["mobilization"])
            self.assertEqual(e["equipment"], self.old["scenarios"][sref]["equipment"])

    def test_gate_lines_use_the_scope_width_and_quantity_with_no_per_leaf_multiplier(self):
        for sref, e in self.st["estimate"]["scenarios"].items():
            by = {l["gate_id"]: l for l in e["materials"]["lines"] if l["item_id"] in GATE_OVERRIDE_IDS.values()}
            for g in self.scopes[sref]["gates"]:
                w = g["clear_width_ft"]["value"]
                q = g["quantity"]["value"] if isinstance(g["quantity"], dict) else g["quantity"]
                l = by[g["gate_id"]]
                self.assertEqual((l["clear_width_ft"], l["gate_quantity"], l["quantity"], l["unit_price"], l["extended"], l["tax_exempt"]),
                                 (w, q, w * q, 250.0, float(c(RATE * d(w) * d(q))), True))
            g2 = next(g for g in self.scopes[sref]["gates"] if g["gate_id"] == "G2")
            self.assertEqual((by["G2"]["clear_width_ft"], by["G2"]["quantity"]), (12.0, 24.0))              # 12'-0" clear opening x 2 gates; leaves do not multiply it
            self.assertEqual(g2["gate_kind"]["value"] if isinstance(g2["gate_kind"], dict) else g2["gate_kind"], "double_swing")

    def test_gate_quantity_per_item_comes_from_the_bid_schedule_not_a_typed_number(self):
        v = bs.view(self.st)["scenarios"]
        for sref, e in self.st["estimate"]["scenarios"].items():
            items = {r["item_no"]: r for r in v[sref]["items"]}
            for l in e["materials"]["lines"]:
                if l["item_id"] in GATE_OVERRIDE_IDS.values():
                    self.assertEqual(items[l["bid_item"]]["quantity"], l["gate_quantity"], (sref, l["gate_id"]))   # same number the schedule prices the item at
                    self.assertGreaterEqual(items[l["bid_item"]]["direct_attributed"], l["extended"])
            self.assertTrue(v[sref]["available"])

    def test_the_export_prints_the_three_gate_lines_and_the_assumption(self):
        quals = integration.view(self.st)["estimate_view"]["qualifications"]
        for gid, item in (("G1", 12), ("G2", 13), ("G3", 14)):
            self.assertTrue(any(q.startswith(f"Gate {gid} assembly (bid item {item})") and "clear opening" in q and "gate quantity" in q and "$250.00/LF" in q for q in quals), gid)
        self.assertIn("Shared post and bracing lines carried whole; no gate-post share split out.", quals)
        self.assertTrue(any("decision #4" in q and "Replaces" in q or "complete gate assembly" in q for q in quals))

    def test_the_old_pinned_workbook_prices_are_not_edited(self):
        import hashlib, pathlib
        self.assertEqual(hashlib.sha256(pathlib.Path("samples/public-demo/reference_pricing_workbook_v2_3_0.fictional.xlsx").read_bytes()).hexdigest(),
                         "3d43120473c8db3840557d62397e5f4fc5669b7f2b3cf5a0c86005fc88dde8f1")


class OtherScopes(unittest.TestCase):
    def test_a_scope_that_is_not_dp001_is_priced_exactly_as_before(self):
        st = H.priced(scope=None)
        scope = copy.deepcopy(H.fixture())
        scope["project_ref"] = "OTHER"
        other = H.priced(scope=scope)
        ids = {l["item_id"] for l in other["estimate"]["scenarios"]["BASE"]["materials"]["lines"]}
        self.assertTrue({"M21", "M28", "M43"} <= ids)
        self.assertFalse(ids & set(GATE_OVERRIDE_IDS.values()))
        self.assertEqual(other["estimate"]["scenarios"]["BASE"]["price_total"], without_override(other)["scenarios"]["BASE"]["price_total"])


if __name__ == "__main__":
    unittest.main()

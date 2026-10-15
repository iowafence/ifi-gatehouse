"""Pricing engine: exact arithmetic, join rules, and every fail-closed path. Rates here are the fictional test book
from tests/xlsx_builder.py; quantities are written by hand so each expected dollar figure can be checked by eye."""
import copy
import datetime
import random
import unittest
from decimal import Decimal

from pricing import engine, jsonschema_lite
from pricing import ratebook as rb
from tests import pricing_helpers as H
from tests import xlsx_builder as xb


def codes(payload, ratebook, **kw):
    kw.setdefault("labor_basis", H.labor_ok(ratebook))
    kw.setdefault("as_of", H.AS_OF)
    return {p["code"] for p in engine.check(payload, ratebook, **kw)}


def run(payload, ratebook, **kw):
    kw.setdefault("labor_basis", H.labor_ok(ratebook))
    kw.setdefault("as_of", H.AS_OF)
    return engine.price(payload, ratebook, **kw)


class Arithmetic(unittest.TestCase):
    def setUp(self):
        self.book = H.book()

    def test_order_quantity_is_an_exact_decimal_ceiling(self):
        # Binary floats: 180 x 1.1 = 198.00000000000003, so a naive ROUNDUP orders 199. Exact decimal arithmetic orders 198.
        est = run(H.payload({"M39": 180}), self.book)
        line = next(l for l in est["materials"]["lines"] if l["item_id"] == "M39")
        self.assertEqual(line["order_quantity"], 198)
        self.assertEqual(line["extended"], 7821.0)          # 198 x $39.50
        # likewise 10 x 1.1 = 11.000000000000002: M01 orders 11, not 12
        line = next(l for l in run(H.payload({"M01": 10}), self.book)["materials"]["lines"] if l["item_id"] == "M01")
        self.assertEqual(line["order_quantity"], 11)
        # a genuine fraction still rounds up
        line = next(l for l in run(H.payload({"M05": 551}), self.book)["materials"]["lines"] if l["item_id"] == "M05")
        self.assertEqual(line["order_quantity"], 607)        # 551 x 1.1 = 606.1

    def test_cubic_yards_round_up_to_one_decimal(self):
        # M40 is the 40th material: index 40 -> overage 0 (even index). qty 8.4866 -> 8.5
        b = H.book(lambda s: xb.row(s, "Materials", "item_id", "M40").update(overage_pct=0.1))
        line = next(l for l in run(H.payload({"M40": 8.48666}), b)["materials"]["lines"] if l["item_id"] == "M40")
        self.assertEqual(line["order_quantity"], 9.4)       # 8.48666 x 1.1 = 9.335326 -> 9.4

    def test_concrete_is_priced_exactly_once(self):
        est = run(H.payload({"M40": 10}), self.book)
        self.assertEqual([l["item_id"] for l in est["materials"]["lines"]], ["M40"])

    def test_labor_cost_is_quantity_over_production_times_loaded_crew_rate(self):
        # L01 = D12 (layout) on CR1: foreman 32 + laborer 20 + operator 28, 35% burden -> 80 x 1.35 = 108/hr; production 11/hr
        est = run(H.payload({"D12": 110}), self.book)
        line = next(l for l in est["labor"]["lines"] if l["task_id"] == "L01")
        self.assertEqual((line["crew_hours"], line["crew_rate_per_hr"], line["extended"]), (10.0, 108.0, 1080.0))

    def test_equipment_and_mobilization_use_the_scenario_column(self):
        base, alt = run(H.payload(), self.book), run(H.payload(scope_ref="ALT-A1"), self.book)
        self.assertEqual(base["equipment"]["subtotal"], 300 * 2 + 40)
        self.assertEqual(alt["equipment"]["subtotal"], 300 * 1 + 20)
        self.assertEqual((base["mobilization"]["subtotal"], alt["mobilization"]["subtotal"]), (500.0, 250.0))

    def test_roll_up_matches_an_independent_recomputation(self):
        q = {"M01": 12, "M05": 100, "M19": 250, "M21": 40, "M38": 80, "M40": 5.5, "D12": 300, "D04": 40, "D03": 40, "D06": 100,
             "D08": 6, "D07": 250, "D11": 250, "D09": 3, "D10": 80, "D01": 250, "D02": 50}
        est = run(H.payload(q), self.book)
        mats = sum(Decimal(str(l["extended"])) for l in est["materials"]["lines"])
        tax = (mats * Decimal("0.07")).quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")
        direct = mats + tax + Decimal(str(est["labor"]["subtotal"])) + Decimal(str(est["equipment"]["subtotal"])) + Decimal(str(est["mobilization"]["subtotal"]))
        oh, ct = (direct * Decimal("0.10")).quantize(Decimal("0.01"), rounding="ROUND_HALF_UP"), (direct * Decimal("0.05")).quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")
        sub = direct + oh + ct
        profit = (sub * Decimal("0.10")).quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")
        self.assertEqual(Decimal(str(est["price_total"])), sub + profit)
        self.assertEqual(Decimal(str(est["materials"]["subtotal"])), mats)
        self.assertEqual(est["fence_lf"], 300)

    def test_deterministic_and_independent_of_item_order(self):
        p = H.payload({"M05": 100, "D12": 200})
        shuffled = copy.deepcopy(p)
        random.Random(7).shuffle(shuffled["items"])
        a, b = run(p, self.book), run(shuffled, self.book)
        self.assertEqual(a, b)
        s1 = engine.price_scenarios({"BASE": p}, self.book, labor_basis=H.labor_ok(self.book), as_of=H.AS_OF)
        s2 = engine.price_scenarios({"BASE": shuffled}, self.book, labor_basis=H.labor_ok(self.book), as_of=H.AS_OF)
        self.assertEqual(s1["digest"], s2["digest"])

    def test_estimate_conforms_to_its_schema_and_carries_no_nan(self):
        est = engine.price_scenarios({"BASE": H.payload({"M05": 10, "D12": 10}), "ALT-A1": H.payload({"M05": 5, "D12": 5}, scope_ref="ALT-A1")},
                                     self.book, labor_basis=H.labor_ok(self.book), as_of=H.AS_OF)
        self.assertEqual(jsonschema_lite.problems(est, "estimate.v1"), [])
        self.assertEqual(est["headline_scope_ref"], "BASE")
        self.assertLess(est["scenarios"]["ALT-A1"]["price_total"], est["scenarios"]["BASE"]["price_total"])

    def test_no_dollar_value_is_taken_from_the_payload(self):
        p = H.payload({"M05": 10})
        for it in p["items"]:
            it["unit_price"] = 0.01
        self.assertIn("SCHEMA_VIOLATION", codes(p, self.book))


class FailClosed(unittest.TestCase):
    def setUp(self):
        self.book = H.book()

    def test_priceable_baseline(self):
        self.assertEqual(codes(H.payload({"M05": 10}), self.book), set())

    def test_unresolved_quantity_blocks_and_is_never_zero(self):
        p = H.payload({"M05": 10})
        it = H.item(p, "M21")
        it.update(quantity=None, status="unresolved", unresolved_reasons=["gate G3 clear width is not established by the documents"])
        self.assertEqual(codes(p, self.book), {"UNRESOLVED_QUANTITY"})
        with self.assertRaises(engine.PricingBlocked) as cm:
            run(p, self.book)
        self.assertIn("G3", cm.exception.problems[0]["message"])

    def test_confirmed_quantity_may_not_be_null(self):
        p = H.payload()
        H.item(p, "M05")["quantity"] = None
        self.assertEqual(codes(p, self.book), {"SCHEMA_VIOLATION"})

    def test_provisional_never_prices_and_a_recorded_resolution_is_a_qualification_on_confirmed_items(self):
        p = H.payload({"M05": 10}, status={"M05": "provisional"})
        self.assertEqual(codes(p, self.book), {"UNAPPROVED_PROVISIONAL"})
        H.item(p, "M05")["approved_resolutions"] = [{"exception_id": "EX-1", "by": "Pat Estimator", "note": "x", "scope_version": 1}]
        self.assertEqual(codes(p, self.book), {"UNAPPROVED_PROVISIONAL"})          # another fact's resolution cannot release it
        H.item(p, "M05")["status"] = "confirmed"                                     # approving the inferred fact makes it human-resolved
        self.assertEqual(codes(p, self.book), set())
        q = run(p, self.book)["qualifications"]
        self.assertEqual((q[0]["type"], q[0]["by"], q[0]["item"]), ("human_resolution", "Pat Estimator", "M05"))
        H.item(p, "M05")["approved_resolutions"][0]["scope_version"] = 99
        self.assertEqual(codes(p, self.book), {"INVALID_RESOLUTION"})

    def test_payload_missing_items_is_a_blocker_not_a_keyerror(self):
        p = H.payload()
        p["items"] = [i for i in p["items"] if i.get("item_id") != "M40" and i.get("driver_key") != "D01"]
        self.assertEqual(codes(p, self.book), {"MISSING_ITEM"})
        with self.assertRaises(engine.PricingBlocked):
            run(p, self.book)

    def test_no_scenarios_is_blocked(self):
        with self.assertRaises(engine.PricingBlocked):
            engine.price_scenarios({}, self.book)

    def test_unapproved_ruleset_blocks(self):
        rs = dict(H.RULESET, approved=False, approved_by=None)
        self.assertEqual(codes(H.payload({"M05": 10}, ruleset=rs), self.book), {"RULESET_NOT_APPROVED"})

    def test_missing_material_rate_blocks_only_when_quantity_needed(self):
        b = H.book(lambda s: s["Materials"].update(rows=[r for r in s["Materials"]["rows"] if r["item_id"] != "M38"]))
        self.assertEqual(codes(H.payload({"M38": 0}), b), set())              # explicit zero: nothing to price
        self.assertEqual(codes(H.payload({"M38": 120}), b), {"MISSING_MATERIAL_RATE"})

    def test_duplicate_unknown_retired_and_incompatible_items(self):
        p = H.payload()
        p["items"].append(copy.deepcopy(H.item(p, "M05")))
        self.assertEqual(codes(p, self.book), {"DUPLICATE_ITEM_ID"})
        p = H.payload(); H.item(p, "M05")["item_id"] = "M99"
        self.assertIn("UNKNOWN_ITEM_ID", codes(p, self.book))
        p = H.payload(); H.item(p, "M05")["item_id"] = "M41"
        self.assertIn("RETIRED_ITEM_ID", codes(p, self.book))
        p = H.payload(); H.item(p, "M40")["uom"] = "EA"
        self.assertEqual(codes(p, self.book), {"INCOMPATIBLE_UNIT"})

    def test_negative_quantity_is_rejected(self):
        p = H.payload(); H.item(p, "M05")["quantity"] = -5
        self.assertEqual(codes(p, self.book), {"SCHEMA_VIOLATION"})

    def test_labor_task_without_its_driver_quantity(self):
        p = H.payload()
        p["items"] = [i for i in p["items"] if i.get("driver_key") != "D12"]
        self.assertEqual(codes(p, self.book), {"MISSING_DRIVER_QUANTITY"})

    def test_unknown_crew_and_negative_price_in_a_tampered_book(self):
        b = copy.deepcopy(self.book)
        b["labor_tasks"][0]["crew_id"] = "CR9"
        self.assertIn("UNKNOWN_CREW", codes(H.payload(), b))
        b = copy.deepcopy(self.book)
        b["materials"][0]["unit_price"] = -1
        self.assertIn("SCHEMA_VIOLATION", codes(H.payload(), b))

    def test_labor_gate_must_be_open_and_current(self):
        p = H.payload({"D12": 100})
        self.assertEqual(codes(p, self.book, labor_basis=None), {"LABOR_NOT_APPROVED"})
        self.assertEqual(codes(p, self.book, labor_basis={"status": "unresolved"}), {"LABOR_NOT_APPROVED"})
        stale = dict(H.labor_ok(self.book), ratebook_labor_sha256="0" * 64)
        self.assertEqual(codes(p, self.book, labor_basis=stale), {"LABOR_APPROVAL_STALE"})
        wage = H.book(lambda s: xb.row(s, "Roles", "role_key", "R2").update(base_wage_per_hr=99))
        self.assertEqual(codes(p, wage, labor_basis=H.labor_ok(self.book)), {"LABOR_APPROVAL_STALE"})

    def test_stale_or_not_yet_effective_rate_book(self):
        newer = H.book(lambda s: (xb.row(s, "Meta", "key", "version").update(value="1.1.0"), xb.row(s, "Materials", "item_id", "M05").update(unit_price=9)))
        self.assertEqual(codes(H.payload(), newer, expected_ratebook_ref=rb.ref(self.book)), {"STALE_RATEBOOK_VERSION"})
        self.assertEqual(codes(H.payload(), self.book, expected_ratebook_ref=rb.ref(self.book)), set())
        self.assertEqual(codes(H.payload(), self.book, as_of=datetime.date(2026, 1, 1)), {"RATEBOOK_NOT_EFFECTIVE"})
        self.assertEqual(codes(H.payload(), self.book, as_of=datetime.date(2028, 1, 1), max_ratebook_age_days=365), {"RATEBOOK_STALE"})

    def test_scenario_must_exist_in_the_rate_book(self):
        self.assertEqual(codes(H.payload(scope_ref="ALT-Z9"), self.book), {"ALTERNATE_NOT_IN_RATEBOOK"})
        mixed = H.payload()
        mixed["items"][0]["scope_ref"] = "ALT-A1"
        self.assertEqual(codes(mixed, self.book), {"MIXED_SCOPE_REFS"})

    def test_quantities_from_another_scope_version_are_refused(self):
        p = H.payload({"M05": 10})
        p["revision"]["scope_version"] = 3
        self.assertEqual(codes(p, self.book, expected_scope_version=3), set())
        self.assertEqual(codes(p, self.book, expected_scope_version=4), {"CONFLICTING_QUANTITY_VERSION"})
        other = H.payload(scope_ref="ALT-A1")
        with self.assertRaises(engine.PricingBlocked) as cm:
            engine.price_scenarios({"BASE": p, "ALT-A1": other}, self.book, labor_basis=H.labor_ok(self.book), as_of=H.AS_OF)
        self.assertEqual(cm.exception.problems[0]["code"], "CONFLICTING_QUANTITY_VERSION")

    def test_no_substitution_by_similar_name(self):
        def f(s):
            s["Materials"]["rows"] = [r for r in s["Materials"]["rows"] if r["item_id"] != "M05"]
            xb.row(s, "Materials", "item_id", "M06")["item"] = "Top rail"          # same name as M05, different stable ID
        b = H.book(f)
        self.assertEqual(codes(H.payload({"M05": 100}), b), {"MISSING_MATERIAL_RATE"})
        self.assertEqual(codes(H.payload({"M06": 100}), b), set())

    def test_every_blocker_is_reported_not_just_the_first(self):
        p = H.payload({"M05": 10}, status={"M05": "provisional"}, ruleset=dict(H.RULESET, approved=False))
        H.item(p, "M21").update(quantity=None, status="unresolved", unresolved_reasons=["x"])
        self.assertEqual(codes(p, self.book, labor_basis=None), {"RULESET_NOT_APPROVED", "UNAPPROVED_PROVISIONAL", "UNRESOLVED_QUANTITY", "LABOR_NOT_APPROVED"})

    def test_one_blocked_scenario_blocks_the_whole_estimate(self):
        alt = H.payload(scope_ref="ALT-A1"); H.item(alt, "M05").update(quantity=None, status="unresolved", unresolved_reasons=["alt length missing"])
        with self.assertRaises(engine.PricingBlocked) as cm:
            engine.price_scenarios({"BASE": H.payload(), "ALT-A1": alt}, self.book, labor_basis=H.labor_ok(self.book), as_of=H.AS_OF)
        self.assertEqual({p["scope_ref"] for p in cm.exception.problems}, {"ALT-A1"})


if __name__ == "__main__":
    unittest.main()

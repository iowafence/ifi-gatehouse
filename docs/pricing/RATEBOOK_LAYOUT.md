# Rate book layout v2

Excel is the human-editable format. The importer ([`pricing/ratebook.py`](../../pricing/ratebook.py)) reads only **literal input cells**, validates them, and emits the normalized `ratebook.v1` object the engine uses. Formulas are scanned for safety and otherwise ignored; cached results are never read.

## Sheets

`Meta` · `Takeoff_In` · `Materials` · `Roles` · `Crews` · `Labor` · `Equipment` · `Mobilization_Other` are required; `README` and `Summary` are optional and carry no inputs. Any other sheet, any hidden sheet, any merged cell, and any column outside the layout is rejected. Rows are matched by **stable keys** (M01.., D01.., R1.., CR1.., L01.., E01.., O01..), headers by name; Excel row numbers carry no meaning.

| Sheet | Human inputs | Computed (ignored by Python; must stay formulas) |
|---|---|---|
| Meta | ratebook_id, version, effective_date, currency, alternate_id, data_classification, tax_materials_pct, overhead_pct, contingency_pct, profit_pct | n/a |
| Takeoff_In | key, description, uom (vocabulary only) | **qty_base / qty_alt / source_ref must be empty** |
| Materials | item_id, category, item, spec, uom, unit_price, vendor, price_date, source_url_or_sku, overage_pct, notes | qty, order qty, extended |
| Roles | role_key, role, base_wage_per_hr, burden_pct | loaded rate |
| Crews | crew_id, description, `n_R<k>_<role>` headcounts | headcount, crew rate |
| Labor | task_id, task, driver_key, crew_id, production_rate (units per crew-hour) | uom, qty, hours, cost |
| Equipment | equip_id, equipment, owned_or_rented, basis, rate, units/fuel base and alt, delivery | extended |
| Mobilization_Other | line_id, category, item, basis, unit_cost, qty base and alt | extended |

## Blank is never zero

A required number that is blank is `MISSING_*`; zero is accepted only where the schema says `minimum: 0` **and** the cell holds an explicit 0 (overage, fuel, delivery, allowances). Prices, wages and production rates must be positive. Numbers stored as text are rejected, not coerced. A line whose every numeric input is blank is an **unused template line**: excluded, listed in the import result (19 in the reference book), never priced as $0. A partly filled line is an error.

## Version and hash handling

* `content_sha256`: canonical JSON of the normalized book (everything except the hashes). Approvals bind to it.
* `labor_sha256`: roles + crews + labor tasks only. A Labor Gate approval binds to it, so a materials price update does not void the labor decision but a wage or production-rate change does.
* `file_sha256`: the uploaded bytes.
* A new upload of the same `ratebook_id` must have a **higher** version (`STALE_RATEBOOK_VERSION`), and the same version with different content is refused (`VERSION_REUSE_WITH_DIFFERENT_CONTENT`). Identical re-uploads are refused as duplicates.
* `effective_date` later than the evaluation date blocks pricing (`RATEBOOK_NOT_EFFECTIVE`); an optional policy `max_ratebook_age_days` blocks stale books.

## Layout v2 design

| Property | Why |
|---|---|
| Retired id **M41** is refused by the importer; M40 is the sole concrete item, in CU YD | A second concrete item would count concrete twice. |
| **Layout v2 carries no quantities** | Quantities come only from the deterministic takeoff, so a rate book can never smuggle in a quantity. The importer rejects any workbook that carries reference-quantity columns. |
| Formulas fail loud: a missing quantity, price, overage, production rate or crew shows `#N/A`, never a quiet $0 | `IFERROR(…,0)`, `N(blank)` and "blank price counts as $0" are not used. |
| `Meta` sheet; Summary rates read from it | One cell per human input; carries id, version and effective date. |
| Summary!B13 looks up D01/D02 by key | Not tied to Excel row numbers. |
| Crews headers `n_R1_foreman` … | Stable role keys instead of positional columns. |

M01–M40 and D01–D12 keep their IDs. Do not renumber or reuse an ID.

The fictional reference workbook is tracked as `samples/public-demo/reference_pricing_workbook_v2_3_0.fictional.xlsx` (file sha256 `3d43120473c8db3840557d62397e5f4fc5669b7f2b3cf5a0c86005fc88dde8f1`, listed with its provenance in `samples/public-assets.sha256`). Every rate in it is an invented demonstration value and it carries no quantities. A company's real rates belong in a separate private copy of the blank template; the importer rejects any workbook that still carries retired item ids or reference-answer columns (`RETIRED_ITEM_ID`, `UNEXPECTED_COLUMN`, `ANSWER_KEY_COLUMNS_PRESENT`).

## Hostile-file handling

Size ≤ 5 MB, ZIP member/ratio/expansion limits, no path traversal, no encryption, no macros, external links, embedded objects, data connections or pivot caches, no DOCTYPE/ENTITY XML, no external relationships other than ignored hyperlinks, formulas containing external references or `WEBSERVICE`/`INDIRECT`/`HYPERLINK`/DDE rejected, formula-injection text leads rejected, duplicate cells and unexpected columns rejected. A 5,600-case corruption fuzz found raw zip-layer exceptions escaping; every parser failure now surfaces as a clean rejection (regression tests included).

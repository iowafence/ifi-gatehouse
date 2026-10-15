# pricing

**Status: implemented; fictional rates.** The deterministic pricing layer used by the engine's priced mode.

* `quantities.py` + `data/quantity_rules.v1.json` takeoff geometry to the stable M01–M40 / D01–D12 vocabulary. The ruleset is a **draft**: no price is released until a named estimator approves the exact file.
* `footings.py` footing schedule by class (`footing-scope.v1` in, `footing-calc.v1` / `footing-schedule.v1` out); unresolved facts stay UNKNOWN, never zero.
* `engine.py`, `crews.py`, `prevailing.py` pricing, crew plans and wage records.
* `ratebook.py`, `xlsx_reader.py`, `store.py`, `schemas/` hardened rate-book import and versioned schemas. The reference workbook is `samples/public-demo/reference_pricing_workbook_v2_3_0.fictional.xlsx`; every rate in it is an invented demonstration value. Real company rate books are imported from a private location (`GATEHOUSE_RATEBOOK_DIR`) and are never committed.

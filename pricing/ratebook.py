"""Rate-book importer: untrusted .xlsx bytes -> validated, normalized `ratebook.v1` dict (human-controlled inputs, Layer C).

Contract
  * Only literal, human-entered input cells are read. Formulas are scanned for safety and otherwise ignored; cached
    formula results are never read (xlsx_reader.keep_cached stays False), so Excel cannot set a price.
  * A blank is never a zero. Every required number must be present as a real numeric cell; zero is accepted only
    where the schema says minimum 0. Numbers stored as text are rejected, not coerced.
  * Rows are matched by stable keys (M01.., D01.., R1.., CR1.., L01..), never by Excel row number.
  * A row whose every numeric input is blank is an UNUSED TEMPLATE LINE: excluded, and listed in the result so a
    person can see exactly what was left out. A partly filled row is an error.
  * The workbook may not carry quantities or reference answers: Takeoff_In holds the key vocabulary only.
All problems are collected and raised together as RateBookRejected."""
import datetime
import hashlib
import json
import re
from decimal import Decimal

from . import jsonschema_lite, vocab
from .xlsx_reader import Sheet, WorkbookRejected, check_text, col_letter, read_workbook

REQUIRED_SHEETS = ("Meta", "Takeoff_In", "Materials", "Roles", "Crews", "Labor", "Equipment", "Mobilization_Other")
OPTIONAL_SHEETS = ("README", "Summary", "Services", "Crew_Production")
MATERIAL_IN = ("item_id", "category", "item", "spec", "uom", "unit_price", "vendor", "price_date", "source_url_or_sku",
               "overage_pct", "notes")
MATERIAL_DERIVED = ("qty_base", "qty_alt", "order_qty_base", "order_qty_alt", "ext_base", "ext_alt")
TAKEOFF_COLS = ("key", "description", "uom", "qty_base", "qty_alt", "source_ref", "notes")
SERVICE_IN = ("service_id", "service", "uom", "unit_cost", "vendor", "price_date", "source_url_or_sku", "notes")
SERVICE_DERIVED = ("qty_base", "qty_alt", "ext_base", "ext_alt")
ROLE_IN, ROLE_DERIVED = ("role_key", "role", "base_wage_per_hr", "burden_pct"), ("loaded_rate_per_hr",)
CREW_IN, CREW_DERIVED = ("crew_id", "description", "efficiency_pct", "difficulty_easy", "difficulty_standard", "difficulty_hard", "profile_version"), \
    ("headcount", "loaded_rate_per_crew_hr")
CREW_OPTIONAL = ("qualifications",)
CREW_PRODUCTION_IN = ("task_id", "crew_id", "production_rate", "rate_basis")
CREW_COUNT = re.compile(r"^n_(R\d{1,3})(?:_[a-z0-9_]+)?$")
LABOR_IN = ("task_id", "task", "driver_key", "crew_id", "production_rate", "rate_basis")
LABOR_DERIVED = ("uom", "qty_base", "qty_alt", "crew_hrs_base", "crew_hrs_alt", "crew_rate_per_hr", "labor_base",
                 "labor_alt", "per_unit_base")
LABOR_OPTIONAL = ("notes", "required_roles", "required_qualifications")
EQUIP_IN = ("equip_id", "equipment", "owned_or_rented", "basis", "rate", "days_or_units_base", "days_or_units_alt",
            "fuel_and_consumables_base", "fuel_and_consumables_alt", "delivery_pickup_each", "delivery_trips", "notes")
EQUIP_DERIVED = ("ext_base", "ext_alt")
MOB_IN = ("line_id", "category", "item", "basis", "unit_cost", "qty_base", "qty_alt", "notes")
MOB_DERIVED = ("ext_base", "ext_alt")
META_KEYS = ("ratebook_id", "version", "effective_date", "currency", "alternate_id", "data_classification", "workday_hours",
             "tax_materials_pct", "overhead_pct", "contingency_pct", "profit_pct")
DEFAULT_PRICE_MAX_AGE_DAYS = 400


class RateBookRejected(Exception):
    def __init__(self, problems, warnings=()):
        self.problems, self.warnings = list(problems), list(warnings)
        super().__init__("; ".join(f"{p['code']}: {p['message']}" for p in self.problems[:6]) + (" ..." if len(self.problems) > 6 else ""))


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(obj):
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


_QUANT = Decimal("1e-10")
_NOISE = Decimal("1e-13")


def _num(d):
    """Decimal -> int/float such that Decimal(repr(x)) is exact downstream. Spreadsheets store 0.07 as
    0.07000000000000001; noise below 1e-13 is canonicalized, a value with real digits beyond 1e-10 is refused (None)."""
    q = d.quantize(_QUANT).normalize()
    if abs(q - d) > _NOISE:
        return None
    if q == q.to_integral_value() and abs(q) < Decimal(10) ** 15:
        return int(q)
    f = float(q)
    return f if Decimal(repr(f)) == q else None


class _Ctx:
    def __init__(self):
        self.problems, self.warnings, self.unused = [], [], []
        self.rejected = set()   # cells already reported, so one defect never cascades into MISSING_* noise

    def err(self, code, message, where=None):
        self.problems.append({"code": code, "message": message, "where": where})

    def warn(self, code, message, where=None):
        self.warnings.append({"code": code, "message": message, "where": where})


def _header(cell):
    return re.split(r"\s*\(", str(cell.value).strip(), 1)[0].strip() if cell is not None and cell.kind == "s" else None


def _table(sheet, inputs, derived, ctx, optional=(), allow_count_cols=False):
    """Return (rows, colmap). rows = [(excel_row, {header: Cell})] for every non-empty data row."""
    cols = {}
    for c in range(1, sheet.max_col + 1):
        h = _header(sheet.get(1, c))
        if h is None:
            if sheet.get(1, c) is not None or any(sheet.get(r, c) is not None for r in range(2, sheet.max_row + 1)):
                ctx.err("BAD_HEADER", f"column {col_letter(c)} has no usable header", f"{sheet.name}!{col_letter(c)}1")
            continue
        if h in cols:
            ctx.err("DUPLICATE_HEADER", f"header {h!r} appears twice", f"{sheet.name}!{col_letter(c)}1")
        cols[h] = c
    known = set(inputs) | set(derived) | set(optional)
    for h in list(cols):
        if allow_count_cols and CREW_COUNT.match(h):
            continue
        if h not in known:
            code = "ANSWER_KEY_COLUMNS_PRESENT" if h.startswith("ref_") else "UNEXPECTED_COLUMN"
            ctx.err(code, f"column {h!r} is not part of the rate-book layout", f"{sheet.name}!{col_letter(cols[h])}1")
    for h in inputs:
        if h not in cols:
            ctx.err("MISSING_COLUMN", f"required column {h!r} is missing", f"{sheet.name}!1")
    for m in sheet.merges:
        ctx.err("MERGED_CELLS", f"merged cells ({m}) are not allowed; read-by-key needs a plain grid", f"{sheet.name}!{m}")
    rows = []
    for r in range(2, sheet.max_row + 1):
        rec = {}
        for h, c in cols.items():
            cell = sheet.get(r, c)
            if cell is None:
                continue
            where = f"{sheet.name}!{col_letter(c)}{r}"
            if h in derived or (allow_count_cols and h in ("headcount",)):
                if not cell.is_formula:
                    ctx.err("LITERAL_IN_FORMULA_COLUMN", f"{h} is a computed column but holds a typed value", where)
                continue
            if cell.is_formula:
                ctx.err("FORMULA_IN_INPUT_CELL", f"{h} is a human input and must hold a literal value, not a formula", where)
                ctx.rejected.add(where)
                continue
            bad = check_text(cell)
            if bad:
                ctx.err(bad, f"unsafe text in {h}", where)
                ctx.rejected.add(where)
                continue
            if cell.kind == "e":
                ctx.err("ERROR_VALUE_IN_INPUT", f"{h} holds the error value {cell.value}", where)
                ctx.rejected.add(where)
                continue
            rec[h] = cell
        if rec:
            rows.append((r, rec))
    return rows, cols


_EXACT_KEYS = ("item_id", "key", "role_key", "crew_id", "task_id", "driver_key", "equip_id", "line_id", "uom")


def _s(rec, key, where, ctx, required=True, maxlen=None):
    if where in ctx.rejected:
        return None
    c = rec.get(key)
    if c is None:
        if required:
            ctx.err("MISSING_VALUE", f"{key} is required", where)
        return None
    if c.kind != "s" or not c.value.strip():
        ctx.err("INVALID_TEXT", f"{key} must be text", where)
        return None
    if key in _EXACT_KEYS and c.value != c.value.strip():
        ctx.err("INVALID_TEXT", f"{key} must not have leading or trailing whitespace", where)
        return None
    return c.value.strip()


def _opt(rec, key, where, ctx):
    """Optional free text: absent or empty -> ''; a non-text cell is an error."""
    if where in ctx.rejected:
        return ""
    c = rec.get(key)
    if c is None:
        return ""
    if c.kind != "s":
        ctx.err("INVALID_TEXT", f"{key} must be text", where)
        return ""
    return c.value.strip()


def _n(rec, key, where, ctx, lo=None, hi=None, positive=False, integer=False, code=None):
    if where in ctx.rejected:
        return None
    c = rec.get(key)
    if c is None:
        ctx.err(code or "MISSING_VALUE", f"{key} is blank; a blank is never a zero", where)
        return None
    if c.kind == "s":
        ctx.err("NUMBER_STORED_AS_TEXT", f"{key} holds text {c.value!r}, not a number", where)
        return None
    if c.kind != "n":
        ctx.err("INVALID_NUMBER", f"{key} is not a number", where)
        return None
    d = c.value
    if (positive and d <= 0) or (lo is not None and d < lo) or (hi is not None and d > hi):
        ctx.err("OUT_OF_RANGE", f"{key} = {d} is outside the allowed range", where)
        return None
    if integer and d != d.to_integral_value():
        ctx.err("INVALID_NUMBER", f"{key} must be a whole number", where)
        return None
    v = _num(d)
    if v is None:
        ctx.err("NUMBER_PRECISION", f"{key} = {d} cannot be represented exactly", where)
    return v


def _date(rec, key, where, ctx):
    if where in ctx.rejected:
        return None
    c = rec.get(key)
    if c is None:
        ctx.err("MISSING_VALUE", f"{key} is required", where)
        return None
    if c.kind != "d":
        ctx.err("INVALID_DATE", f"{key} must be a real date cell", where)
        return None
    return c.value


def _vocab_key(kind, key, seen, where, ctx):
    if key in vocab.RETIRED:
        ctx.err("RETIRED_ITEM_ID", f"{key} is retired: {vocab.RETIRED[key]}", where)
    elif key not in {"M": vocab.MATERIALS, "S": vocab.SERVICES, "D": vocab.DRIVERS}[kind]:
        ctx.err("UNKNOWN_ITEM_ID" if kind in "MS" else "UNKNOWN_DRIVER", f"{key!r} is not in the stable vocabulary", where)
    if key in seen:
        ctx.err("DUPLICATE_ITEM_ID", f"{key} appears more than once (first at row {seen[key]})", where)
    return key


def _meta(sheet, ctx, as_of):
    rows, _ = _table(sheet, ("key", "value"), (), ctx, optional=("notes",))
    kv = {}
    for r, rec in rows:
        key = _s(rec, "key", f"Meta!A{r}", ctx)
        if key is None:
            continue
        if key not in META_KEYS:
            ctx.err("UNEXPECTED_META_KEY", f"unknown Meta key {key!r}", f"Meta!A{r}")
        elif key in kv:
            ctx.err("DUPLICATE_META_KEY", f"Meta key {key!r} appears twice", f"Meta!A{r}")
        else:
            kv[key] = (r, rec.get("value"))
    missing = [k for k in META_KEYS if k not in kv or kv[k][1] is None]
    for k in missing:
        ctx.err("MISSING_META", f"Meta key {k!r} has no value", "Meta")
    out = {}
    for k, (r, cell) in kv.items():
        if cell is None:
            continue
        where = f"Meta!B{r}"
        rec = {"v": cell}
        if k == "effective_date":
            out[k] = _date(rec, "v", where, ctx)
            if out[k] and out[k] > as_of.isoformat():
                ctx.err("FUTURE_EFFECTIVE_DATE", f"effective_date {out[k]} is later than today ({as_of})", where)
        elif k.endswith("_pct"):
            out[k] = _n(rec, "v", where, ctx, lo=0, hi=1)
        elif k == "workday_hours":
            out[k] = _n(rec, "v", where, ctx, positive=True, hi=24)
        else:
            out[k] = _s(rec, "v", where, ctx)
    return {k: out.get(k) for k in META_KEYS}


def _services(sheet, ctx, as_of, max_age):
    rows, cols = _table(sheet, SERVICE_IN, SERVICE_DERIVED, ctx)
    out, seen = [], {}
    for r, rec in rows:
        def W(h):
            return f"Services!{col_letter(cols[h])}{r}" if h in cols else f"Services!{h}{r}"
        key = _s(rec, "service_id", W("service_id"), ctx)
        if key is None:
            ctx.err("ROW_WITHOUT_KEY", "row has data but no service_id", W("service_id"))
            continue
        if not re.match(r"^S\d{2}$", key):
            ctx.err("UNKNOWN_ITEM_ID", f"{key!r} is not a service id", W("service_id"))
            continue
        n0 = len(ctx.problems)
        if "unit_cost" not in rec and not any(k in rec for k in ("vendor", "price_date", "source_url_or_sku")):
            ctx.unused.append({"sheet": "Services", "id": key})
            ctx.warn("TEMPLATE_LINE_UNUSED", f"service {key} has no rate and is excluded", W("service_id"))
            continue
        _vocab_key("S", key, seen, W("service_id"), ctx)
        seen.setdefault(key, r)
        uom = _s(rec, "uom", W("uom"), ctx)
        want = vocab.uom(key)
        if want and uom and uom != want:
            ctx.err("INCOMPATIBLE_UNIT", f"{key} is {want} in the vocabulary but the rate is per {uom}", W("uom"))
        cost = _n(rec, "unit_cost", W("unit_cost"), ctx, positive=True, hi=1_000_000, code="MISSING_PRICE")
        pdate = _date(rec, "price_date", W("price_date"), ctx)
        if pdate and pdate > as_of.isoformat():
            ctx.err("INVALID_PRICE_DATE", f"price_date {pdate} is in the future", W("price_date"))
        elif pdate and max_age is not None and (as_of - datetime.date.fromisoformat(pdate)).days > max_age:
            ctx.warn("STALE_PRICE_DATE", f"{key} price is dated {pdate}, over {max_age} days old", W("price_date"))
        name = _s(rec, "service", W("service"), ctx)
        text = {k: _opt(rec, k, W(k) if k in cols else k, ctx) for k in ("vendor", "source_url_or_sku", "notes")}
        if len(ctx.problems) == n0:
            out.append({"service_id": key, "service": name, "uom": uom, "unit_cost": cost, "vendor": text["vendor"], "price_date": pdate,
                        "source_ref": text["source_url_or_sku"], "notes": text["notes"]})
    return sorted(out, key=lambda m: m["service_id"])


def _takeoff(sheet, materials_present, ctx):
    rows, cols = _table(sheet, TAKEOFF_COLS, (), ctx)
    seen = {}
    for r, rec in rows:
        where = f"Takeoff_In!A{r}"
        for q in ("qty_base", "qty_alt"):
            if q in rec:
                ctx.err("PREFILLED_QUANTITY", f"{q} must be empty: quantities come only from the deterministic takeoff", f"Takeoff_In!{col_letter(cols[q])}{r}")
        if "source_ref" in rec:
            ctx.err("PREFILLED_SOURCE_REF", "source_ref must be empty in a rate book", f"Takeoff_In!{col_letter(cols['source_ref'])}{r}")
        key = _s(rec, "key", where, ctx)
        if key is None:
            continue
        kind = key[0]
        if kind not in ("M", "D", "S") and key not in vocab.RETIRED:
            ctx.err("UNKNOWN_ITEM_ID", f"{key!r} is not in the stable vocabulary", where)
            continue
        _vocab_key(kind, key, seen, where, ctx)
        seen.setdefault(key, r)
        want, got = vocab.uom(key), _s(rec, "uom", f"Takeoff_In!C{r}", ctx)
        if want and got and got != want:
            ctx.err("INCOMPATIBLE_UNIT", f"{key} is {want} in the vocabulary but {got} here", f"Takeoff_In!C{r}")
    for m in materials_present:
        if m not in seen:
            ctx.err("MATERIAL_WITHOUT_TAKEOFF_KEY", f"{m} has a rate but no Takeoff_In key", "Takeoff_In")
    return seen


def _materials(sheet, ctx, as_of, max_age):
    rows, cols = _table(sheet, MATERIAL_IN, MATERIAL_DERIVED, ctx)
    out, seen = [], {}
    for r, rec in rows:
        def W(h):
            return f"Materials!{col_letter(cols[h])}{r}" if h in cols else f"Materials!{h}{r}"
        key = _s(rec, "item_id", W("item_id"), ctx)
        if key is None:
            ctx.err("ROW_WITHOUT_KEY", "row has data but no item_id", W("item_id"))
            continue
        if not re.match(r"^M\d{2}$", key) and key not in vocab.RETIRED:
            ctx.err("UNKNOWN_ITEM_ID", f"{key!r} is not an item id", W("item_id"))
            continue
        n0 = len(ctx.problems)
        _vocab_key("M", key, seen, W("item_id"), ctx)
        seen.setdefault(key, r)
        uom = _s(rec, "uom", W("uom"), ctx)
        want = vocab.uom(key)
        if want and uom and uom != want:
            ctx.err("INCOMPATIBLE_UNIT", f"{key} is {want} in the vocabulary but the rate is per {uom}", W("uom"))
        price = _n(rec, "unit_price", W("unit_price"), ctx, positive=True, hi=1_000_000, code="MISSING_PRICE")
        over = _n(rec, "overage_pct", W("overage_pct"), ctx, lo=0, hi=1, code="MISSING_OVERAGE")
        pdate = _date(rec, "price_date", W("price_date"), ctx)
        if pdate:
            if pdate > as_of.isoformat():
                ctx.err("INVALID_PRICE_DATE", f"price_date {pdate} is in the future", W("price_date"))
            elif max_age is not None and (as_of - datetime.date.fromisoformat(pdate)).days > max_age:
                ctx.warn("STALE_PRICE_DATE", f"{key} price is dated {pdate}, over {max_age} days old", W("price_date"))
        item = _s(rec, "item", W("item"), ctx)
        text = {k: _opt(rec, k, W(k) if k in cols else k, ctx) for k in ("category", "spec", "vendor", "source_url_or_sku", "notes")}
        if len(ctx.problems) == n0:
            out.append({"item_id": key, "category": text["category"], "item": item, "spec": text["spec"],
                        "uom": uom, "unit_price": price, "vendor": text["vendor"], "price_date": pdate,
                        "source_ref": text["source_url_or_sku"], "overage_pct": over, "notes": text["notes"]})
    return sorted(out, key=lambda m: m["item_id"])


def _roles(sheet, ctx):
    rows, _ = _table(sheet, ROLE_IN, ROLE_DERIVED, ctx)
    out, seen = [], {}
    ctx.declared_roles = set()
    for r, rec in rows:
        where = f"Roles!A{r}"
        key = _s(rec, "role_key", where, ctx)
        if key is None:
            ctx.err("ROW_WITHOUT_KEY", "row has data but no role_key", where)
            continue
        if set(rec) <= {"role_key"}:
            ctx.unused.append({"sheet": "Roles", "id": key})
            ctx.warn("TEMPLATE_LINE_UNUSED", f"role {key} is blank and excluded", where)
            continue
        if key in seen:
            ctx.err("DUPLICATE_ROLE", f"{key} appears twice", where)
        seen[key] = r
        ctx.declared_roles.add(key)
        n0 = len(ctx.problems)
        role = _s(rec, "role", f"Roles!B{r}", ctx)
        wage = _n(rec, "base_wage_per_hr", f"Roles!C{r}", ctx, positive=True, hi=1000, code="MISSING_WAGE")
        burden = _n(rec, "burden_pct", f"Roles!D{r}", ctx, lo=0, hi=2, code="MISSING_BURDEN")
        if len(ctx.problems) == n0:
            out.append({"role_key": key, "role": role, "base_wage_per_hr": wage, "burden_pct": burden})
    return out


def _crews(sheet, roles, ctx):
    ctx.declared_crews = set()
    rows, cols = _table(sheet, CREW_IN, CREW_DERIVED, ctx, optional=CREW_OPTIONAL, allow_count_cols=True)
    count_cols = {}
    for h, c in cols.items():
        m = CREW_COUNT.match(h)
        if m:
            count_cols[m.group(1)] = (h, c)
    role_keys = ctx.declared_roles
    for rk, (h, c) in count_cols.items():
        if rk not in role_keys:
            ctx.err("UNKNOWN_ROLE", f"crew column {h} refers to role {rk}, which has no rate in Roles", f"Crews!{col_letter(c)}1")
    out, seen = [], {}
    for r, rec in rows:
        where = f"Crews!A{r}"
        cid = _s(rec, "crew_id", where, ctx)
        if cid is None:
            ctx.err("ROW_WITHOUT_KEY", "row has data but no crew_id", where)
            continue
        counts_present = [k for k in rec if CREW_COUNT.match(k)]
        if not counts_present and not ({"description", "efficiency_pct"} & set(rec)):
            ctx.unused.append({"sheet": "Crews", "id": cid})
            ctx.warn("TEMPLATE_LINE_UNUSED", f"crew {cid} is blank and excluded", where)
            continue
        if cid in seen:
            ctx.err("DUPLICATE_CREW", f"{cid} appears twice", where)
        seen[cid] = r
        ctx.declared_crews.add(cid)
        n0 = len(ctx.problems)
        members = {}
        for rk, (h, c) in count_cols.items():
            v = _n(rec, h, f"Crews!{col_letter(c)}{r}", ctx, lo=0, hi=100, integer=True, code="BLANK_CREW_COUNT")
            if v:
                members[rk] = v
        if not members and len(ctx.problems) == n0:
            ctx.err("EMPTY_CREW", f"crew {cid} has no members", where)
        W = lambda h: f"Crews!{col_letter(cols[h])}{r}" if h in cols else f"Crews!{h}{r}"
        eff = _n(rec, "efficiency_pct", W("efficiency_pct"), ctx, positive=True, hi=300, code="MISSING_EFFICIENCY")
        diff = {lvl: _n(rec, f"difficulty_{lvl}", W(f"difficulty_{lvl}"), ctx, positive=True, hi=3, code="MISSING_DIFFICULTY_RESPONSE")
                for lvl in ("easy", "standard", "hard")}
        pv = _s(rec, "profile_version", W("profile_version"), ctx)
        quals = _list(rec, "qualifications", W("qualifications"), ctx)
        if len(ctx.problems) == n0:
            out.append({"crew_id": cid, "description": _opt(rec, "description", f"Crews!B{r}", ctx), "members": members,
                        "efficiency_pct": eff, "difficulty": diff, "qualifications": quals, "profile_version": pv})
    return out


def _list(rec, key, where, ctx, pattern=None):
    """Optional comma-separated list cell. Blank = empty list (nothing required / none held)."""
    raw = _opt(rec, key, where, ctx)
    items = [x.strip() for x in raw.split(",") if x.strip()]
    if pattern:
        bad = [x for x in items if not re.match(pattern, x)]
        if bad:
            ctx.err("INVALID_TEXT", f"{key} entries must look like {pattern}", where)
    if len(set(items)) != len(items):
        ctx.err("INVALID_TEXT", f"{key} lists an entry twice", where)
    return items


def _crew_options(sheet, crews, labor, ctx):
    rows, cols = _table(sheet, CREW_PRODUCTION_IN, (), ctx, optional=("notes",))
    task_ids = {t["task_id"] for t in labor}
    defaults = {(t["task_id"], t["crew_id"]) for t in labor}
    out, seen = [], set()
    for r, rec in rows:
        W = lambda h: f"Crew_Production!{col_letter(cols[h])}{r}" if h in cols else f"Crew_Production!{h}{r}"
        tid, cid = _s(rec, "task_id", W("task_id"), ctx), _s(rec, "crew_id", W("crew_id"), ctx)
        if tid is None or cid is None:
            continue
        n0 = len(ctx.problems)
        if tid not in task_ids:
            ctx.err("UNKNOWN_TASK", f"{tid} is not a task in Labor", W("task_id"))
        if cid not in ctx.declared_crews:
            ctx.err("UNKNOWN_CREW", f"crew {cid!r} is not defined in Crews", W("crew_id"))
        if (tid, cid) in seen or (tid, cid) in defaults:
            ctx.err("DUPLICATE_CREW_OPTION", f"{tid}/{cid} is already priced (the Labor row is that task's default crew)", W("task_id"))
        seen.add((tid, cid))
        rate = _n(rec, "production_rate", W("production_rate"), ctx, positive=True, hi=100000, code="MISSING_PRODUCTION_RATE")
        basis = _s(rec, "rate_basis", W("rate_basis"), ctx)
        if basis is not None and basis not in ("standard", "historical_calibrated"):
            ctx.err("INVALID_VALUE", "rate_basis must be 'standard' or 'historical_calibrated'", W("rate_basis"))
        if len(ctx.problems) == n0:
            out.append({"task_id": tid, "crew_id": cid, "production_rate": rate, "rate_basis": basis})
    return sorted(out, key=lambda o: (o["task_id"], o["crew_id"]))


def _labor(sheet, crews, ctx):
    rows, cols = _table(sheet, LABOR_IN, LABOR_DERIVED, ctx, optional=LABOR_OPTIONAL)
    crew_ids = ctx.declared_crews
    out, seen = [], {}
    for r, rec in rows:
        where = f"Labor!A{r}"
        tid = _s(rec, "task_id", where, ctx)
        if tid is None:
            ctx.err("ROW_WITHOUT_KEY", "row has data but no task_id", where)
            continue
        if tid in seen:
            ctx.err("DUPLICATE_TASK_ID", f"{tid} appears twice", where)
        seen[tid] = r
        n0 = len(ctx.problems)
        drv = _s(rec, "driver_key", f"Labor!C{r}", ctx)
        if drv is not None and drv not in vocab.DRIVERS:
            ctx.err("UNKNOWN_DRIVER", f"{drv!r} is not a labor driver key", f"Labor!C{r}")
        crew = rec.get("crew_id")
        if crew is None:
            ctx.err("MISSING_CREW", f"task {tid} has no crew", f"Labor!E{r}")
        else:
            crew = _s(rec, "crew_id", f"Labor!E{r}", ctx)
            if crew and crew not in crew_ids:
                ctx.err("UNKNOWN_CREW", f"crew {crew!r} is not defined in Crews", f"Labor!E{r}")
        prod = _n(rec, "production_rate", f"Labor!F{r}", ctx, positive=True, hi=100000, code="MISSING_PRODUCTION_RATE")
        basis = _s(rec, "rate_basis", f"Labor!{col_letter(cols['rate_basis']) if 'rate_basis' in cols else 'rate_basis'}{r}", ctx)
        if basis is not None and basis not in ("standard", "historical_calibrated"):
            ctx.err("INVALID_VALUE", "rate_basis must be 'standard' or 'historical_calibrated'", f"Labor!rate_basis{r}")
        req_roles = _list(rec, "required_roles", f"Labor!required_roles{r}", ctx, r"^R\d{1,3}$")
        req_quals = _list(rec, "required_qualifications", f"Labor!required_qualifications{r}", ctx)
        if len(ctx.problems) == n0:
            out.append({"task_id": tid, "task": _opt(rec, "task", f"Labor!B{r}", ctx), "driver_key": drv,
                        "uom": vocab.uom(drv), "crew_id": crew, "production_rate": prod, "rate_basis": basis,
                        "required_roles": req_roles, "required_qualifications": req_quals})
    return out


def _equipment(sheet, ctx):
    rows, _ = _table(sheet, EQUIP_IN, EQUIP_DERIVED, ctx)
    out, seen = [], {}
    numeric = ("rate", "days_or_units_base", "days_or_units_alt", "fuel_and_consumables_base",
               "fuel_and_consumables_alt", "delivery_pickup_each", "delivery_trips")
    for r, rec in rows:
        where = f"Equipment!A{r}"
        eid = _s(rec, "equip_id", where, ctx)
        if eid is None:
            ctx.err("ROW_WITHOUT_KEY", "row has data but no equip_id", where)
            continue
        if not any(k in rec for k in numeric + ("owned_or_rented", "basis")):
            ctx.unused.append({"sheet": "Equipment", "id": eid})
            ctx.warn("TEMPLATE_LINE_UNUSED", f"equipment {eid} has no rate or usage and is excluded", where)
            continue
        if eid in seen:
            ctx.err("DUPLICATE_EQUIPMENT", f"{eid} appears twice", where)
        seen[eid] = r
        n0 = len(ctx.problems)
        own, basis = _s(rec, "owned_or_rented", f"Equipment!C{r}", ctx), _s(rec, "basis", f"Equipment!D{r}", ctx)
        if own and own not in ("owned", "rented"):
            ctx.err("INVALID_VALUE", "owned_or_rented must be 'owned' or 'rented'", f"Equipment!C{r}")
        if basis and basis not in ("day", "hr", "week", "each"):
            ctx.err("INVALID_VALUE", "basis must be day, hr, week or each", f"Equipment!D{r}")
        vals = {}
        for i, k in enumerate(numeric):
            vals[k] = _n(rec, k, f"Equipment!{col_letter(5 + i)}{r}", ctx, lo=0, hi=1_000_000, positive=(k == "rate"))
        if len(ctx.problems) == n0:
            out.append({"equip_id": eid, "equipment": _s(rec, "equipment", f"Equipment!B{r}", ctx), "owned_or_rented": own,
                        "basis": basis, "rate": vals["rate"], "units_base": vals["days_or_units_base"],
                        "units_alt": vals["days_or_units_alt"], "fuel_base": vals["fuel_and_consumables_base"],
                        "fuel_alt": vals["fuel_and_consumables_alt"], "delivery_each": vals["delivery_pickup_each"],
                        "delivery_trips": vals["delivery_trips"]})
    return out


def _mobilization(sheet, ctx):
    rows, _ = _table(sheet, MOB_IN, MOB_DERIVED, ctx)
    out, seen = [], {}
    for r, rec in rows:
        where = f"Mobilization_Other!A{r}"
        lid = _s(rec, "line_id", where, ctx)
        if lid is None:
            ctx.err("ROW_WITHOUT_KEY", "row has data but no line_id", where)
            continue
        if not any(k in rec for k in ("unit_cost", "qty_base", "qty_alt")):
            ctx.unused.append({"sheet": "Mobilization_Other", "id": lid})
            ctx.warn("TEMPLATE_LINE_UNUSED", f"line {lid} has no cost or quantity and is excluded", where)
            continue
        if lid in seen:
            ctx.err("DUPLICATE_LINE_ID", f"{lid} appears twice", where)
        seen[lid] = r
        n0 = len(ctx.problems)
        uc = _n(rec, "unit_cost", f"Mobilization_Other!E{r}", ctx, lo=0, hi=10_000_000)
        qb = _n(rec, "qty_base", f"Mobilization_Other!F{r}", ctx, lo=0, hi=1_000_000)
        qa = _n(rec, "qty_alt", f"Mobilization_Other!G{r}", ctx, lo=0, hi=1_000_000)
        if len(ctx.problems) == n0:
            out.append({"line_id": lid, "category": _opt(rec, "category", f"Mobilization_Other!B{r}", ctx),
                        "item": _s(rec, "item", f"Mobilization_Other!C{r}", ctx), "basis": _opt(rec, "basis", f"Mobilization_Other!D{r}", ctx),
                        "unit_cost": uc, "qty_base": qb, "qty_alt": qa})
    return out


def import_workbook(data, *, as_of=None, max_price_age_days=DEFAULT_PRICE_MAX_AGE_DAYS):
    """Validate and normalize rate-book bytes. Returns {'ratebook', 'warnings', 'report'}; raises RateBookRejected."""
    as_of = as_of or datetime.date.today()
    try:
        wb = read_workbook(data)
    except WorkbookRejected as exc:
        raise RateBookRejected(exc.problems) from None
    ctx = _Ctx()
    ctx.warnings.extend(wb.warnings)
    for name, sh in wb.sheets.items():
        if name not in REQUIRED_SHEETS + OPTIONAL_SHEETS:
            ctx.err("UNEXPECTED_SHEET", f"sheet {name!r} is not part of the rate-book layout", name)
        if sh.state != "visible":
            ctx.err("HIDDEN_SHEET", f"sheet {name!r} is {sh.state}; hidden content is not accepted", name)
    missing = [n for n in REQUIRED_SHEETS if n not in wb.sheets]
    for name in missing:               # keep validating what IS present, so one upload reports every defect (e.g. a legacy book)
        ctx.err("MISSING_SHEET", f"required sheet {name!r} is missing", name)
        wb.sheets[name] = Sheet(name, "visible")
    for name in OPTIONAL_SHEETS:           # unsafe-formula scan happened in the reader; text hygiene only here
        for (r, c), cell in wb.sheets.get(name, type("E", (), {"cells": {}})).cells.items():
            bad = check_text(cell)
            if bad:
                ctx.err(bad, "unsafe text", f"{name}!{col_letter(c)}{r}")
    meta = dict.fromkeys(META_KEYS) if "Meta" in missing else _meta(wb.sheets["Meta"], ctx, as_of)
    materials = _materials(wb.sheets["Materials"], ctx, as_of, max_price_age_days)
    services = _services(wb.sheets["Services"], ctx, as_of, max_price_age_days) if "Services" in wb.sheets else []
    _takeoff(wb.sheets["Takeoff_In"], [m["item_id"] for m in materials] + [x["service_id"] for x in services], ctx)
    roles = _roles(wb.sheets["Roles"], ctx)
    crews = _crews(wb.sheets["Crews"], roles, ctx)
    labor = _labor(wb.sheets["Labor"], crews, ctx)
    crew_options = _crew_options(wb.sheets["Crew_Production"], crews, labor, ctx) if "Crew_Production" in wb.sheets else []
    equipment = _equipment(wb.sheets["Equipment"], ctx)
    mobilization = _mobilization(wb.sheets["Mobilization_Other"], ctx)
    present = {m["item_id"] for m in materials}
    for k in list(vocab.MATERIALS) + list(vocab.SERVICES):
        if k not in present and k not in {x["service_id"] for x in services}:
            ctx.warn("MISSING_MATERIAL_RATE", f"{k} ({(vocab.MATERIALS.get(k) or vocab.SERVICES[k])[1]}) has no rate in this book; any estimate that needs it will be blocked", "Materials")
    if ctx.problems:
        raise RateBookRejected(ctx.problems, ctx.warnings)
    body = {
        "schema_version": "ratebook.v1",
        "meta": {k: meta[k] for k in ("ratebook_id", "version", "effective_date", "currency", "alternate_id", "data_classification", "workday_hours")},
        "materials": materials, "services": services, "roles": roles, "crews": crews, "labor_tasks": labor, "crew_options": crew_options, "equipment": equipment,
        "mobilization": mobilization,
        "markups": {k: meta[k] for k in ("tax_materials_pct", "overhead_pct", "contingency_pct", "profit_pct")},
        "unused_template_lines": ctx.unused,
    }
    body["hashes"] = {"file_sha256": hashlib.sha256(data).hexdigest(), "content_sha256": _sha(body),
                      "labor_sha256": _sha({"roles": roles, "crews": crews, "labor_tasks": labor, "crew_options": crew_options})}
    bad = jsonschema_lite.problems(body, "ratebook.v1")
    if bad:
        raise RateBookRejected([{"code": "SCHEMA_VIOLATION", "message": m, "where": p} for p, m in bad], ctx.warnings)
    return {"ratebook": body, "warnings": ctx.warnings,
            "report": {"materials": len(materials), "roles": len(roles), "crews": len(crews), "labor_tasks": len(labor),
                       "equipment": len(equipment), "mobilization": len(mobilization), "services": len(services), "unused_template_lines": len(ctx.unused)}}


def ref(rb):
    """Identity an approval binds to: which book, which version, and the exact content."""
    m = rb["meta"]
    return {"ratebook_id": m["ratebook_id"], "version": m["version"], "effective_date": m["effective_date"],
            "content_sha256": rb["hashes"]["content_sha256"], "labor_sha256": rb["hashes"]["labor_sha256"]}


def version_tuple(v):
    return tuple(int(x) for x in v.split("."))


def check_succession(current_ref, new_rb):
    """Return a list of problems if `new_rb` may not replace the book `current_ref` describes."""
    if current_ref is None:
        return []
    n = ref(new_rb)
    if n["ratebook_id"] != current_ref["ratebook_id"]:
        return [{"code": "DIFFERENT_RATEBOOK", "message": f"book id {n['ratebook_id']} differs from the attached {current_ref['ratebook_id']}"}]
    cur, new = version_tuple(current_ref["version"]), version_tuple(n["version"])
    if new < cur:
        return [{"code": "STALE_RATEBOOK_VERSION", "message": f"version {n['version']} is older than the attached {current_ref['version']}"}]
    if new == cur and n["content_sha256"] != current_ref["content_sha256"]:
        return [{"code": "VERSION_REUSE_WITH_DIFFERENT_CONTENT", "message": "the rates changed but the version was not bumped"}]
    return []

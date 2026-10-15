"""Test-only stdlib .xlsx writer. Builds small, exact workbooks (valid or deliberately hostile) with no third-party
dependency, so importer tests can state each defect as a one-line mutation of a known-good spec.

Spec shape: {sheet_name: {"header": [...], "rows": [ {header: value, ...}, ... ], "state": "visible"}}
Values: str, int/float/Decimal, datetime.date, bool, None (blank), ("f", "FORMULA"), ("f", "FORMULA", cached), ("e", "#N/A")."""
import copy
import datetime
import zipfile
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from pricing import vocab
from pricing.xlsx_reader import col_letter

CT_MAIN = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
CT_SHEET = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"


def _serial(d):
    return (d - datetime.date(1899, 12, 30)).days


def _cell(ref, v):
    if v is None:
        return ""
    if isinstance(v, tuple):
        if v[0] == "f":
            cached = f"<v>{escape(str(v[2]))}</v>" if len(v) > 2 else ""
            return f'<c r="{ref}"><f>{escape(v[1])}</f>{cached}</c>'
        if v[0] == "fe":
            return f'<c r="{ref}" t="e"><f>{escape(v[1])}</f><v>{escape(v[2])}</v></c>'
        if v[0] == "e":
            return f'<c r="{ref}" t="e"><v>{escape(v[1])}</v></c>'
    if isinstance(v, bool):
        return f'<c r="{ref}" t="b"><v>{int(v)}</v></c>'
    if isinstance(v, datetime.date):
        return f'<c r="{ref}" s="1"><v>{_serial(v)}</v></c>'
    if isinstance(v, (int, float, Decimal)):
        return f'<c r="{ref}"><v>{v}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(str(v))}</t></is></c>'


def sheet_xml(header, rows, merges=()):
    out = ['<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
    out.append('<row r="1">' + "".join(_cell(f"{col_letter(c)}1", h) for c, h in enumerate(header, 1)) + "</row>")
    for r, row in enumerate(rows, 2):
        out.append(f'<row r="{r}">' + "".join(_cell(f"{col_letter(c)}{r}", row[h] if h in row else row.get(h.split(" (")[0])) for c, h in enumerate(header, 1)) + "</row>")
    out.append("</sheetData>")
    if merges:
        out.append(f'<mergeCells count="{len(merges)}">' + "".join(f'<mergeCell ref="{m}"/>' for m in merges) + "</mergeCells>")
    out.append("</worksheet>")
    return "".join(out)


def build(spec, *, extra_parts=None, content_types_extra="", workbook_extra="", main_ct=CT_MAIN, date1904=False,
          raw_sheet_xml=None, sheet_rels=None):
    names = list(spec)
    parts = {}
    ct = ['<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
          '<Default Extension="xml" ContentType="application/xml"/>',
          f'<Override PartName="/xl/workbook.xml" ContentType="{main_ct}"/>',
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>']
    wb = ['<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
          f'<workbookPr date1904="{str(date1904).lower()}"/><sheets>']
    rels = ['<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    for i, n in enumerate(names, 1):
        s = spec[n]
        wb.append(f'<sheet name="{escape(n)}" sheetId="{i}" state="{s.get("state", "visible")}" r:id="rId{i}"/>')
        rels.append(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>')
        ct.append(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="{CT_SHEET}"/>')
        xml = (raw_sheet_xml or {}).get(n) or sheet_xml(s["header"], s["rows"], s.get("merges", ()))
        parts[f"xl/worksheets/sheet{i}.xml"] = xml
        if sheet_rels and n in sheet_rels:
            parts[f"xl/worksheets/_rels/sheet{i}.xml.rels"] = sheet_rels[n]
    wb.append(f"</sheets>{workbook_extra}</workbook>")
    rels.append("</Relationships>")
    parts["[Content_Types].xml"] = "".join(ct) + content_types_extra + "</Types>"
    parts["xl/workbook.xml"] = "".join(wb)
    parts["xl/_rels/workbook.xml.rels"] = "".join(rels)
    parts["_rels/.rels"] = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    parts["xl/styles.xml"] = ('<?xml version="1.0"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                              '<cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>')
    parts.update(extra_parts or {})
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in parts.items():
            z.writestr(k, v)
    return buf.getvalue()


F = ("f", "1")   # trivial formula placed in computed columns

MATERIAL_HEADER = ["item_id", "category", "item", "spec", "uom", "unit_price", "vendor", "price_date", "source_url_or_sku",
                   "overage_pct", "qty_base", "qty_alt", "order_qty_base", "order_qty_alt", "ext_base", "ext_alt", "notes"]


def valid_spec(as_of=datetime.date(2026, 10, 12), crew_profiles=False):
    """A minimal, fully valid, fictional rate book: every M01-M40 priced, 4 roles, 2 crews, one task per driver used."""
    mats = []
    for i, (k, (uom, name)) in enumerate(vocab.MATERIALS.items(), 1):
        mats.append({"item_id": k, "category": "Test", "item": name, "spec": "test spec", "uom": uom, "unit_price": i + 0.5,
                     "vendor": "Test vendor", "price_date": as_of, "source_url_or_sku": "fictional", "overage_pct": 0.1 if i % 2 else 0,
                     "qty_base": F, "qty_alt": F, "order_qty_base": F, "order_qty_alt": F, "ext_base": F, "ext_alt": F, "notes": ""})
    take = [{"key": k, "description": n, "uom": u} for k, (u, n) in {**vocab.MATERIALS, **vocab.SERVICES, **vocab.DRIVERS}.items()]
    roles = [{"role_key": f"R{i}", "role": n, "base_wage_per_hr": w, "burden_pct": 0.35, "loaded_rate_per_hr": F}
             for i, (n, w) in enumerate([("Foreman", 32), ("Installer", 26), ("Laborer", 20), ("Operator", 28)], 1)]
    neutral = {"efficiency_pct": 100, "difficulty_easy": 1, "difficulty_standard": 1, "difficulty_hard": 1, "qualifications": "", "profile_version": "1"}
    crews = [{"crew_id": "CR1", "description": "Layout", "n_R1_foreman": 1, "n_R2_installer": 0, "n_R3_laborer": 1, "n_R4_operator": 1,
              "headcount": F, "loaded_rate_per_crew_hr": F, **neutral},
             {"crew_id": "CR2", "description": "Install", "n_R1_foreman": 1, "n_R2_installer": 2, "n_R3_laborer": 1, "n_R4_operator": 0,
              "headcount": F, "loaded_rate_per_crew_hr": F, **neutral}]
    options = []
    if crew_profiles:     # four comparison crews (fictional): 104% / 94% / 88% / 97%, each responding differently to difficulty
        prof = [("CR11", "Crew 1: foreman + 2 laborers", (1, 0, 2, 0), 104, (1.10, 1.0, 0.80), "A1"),
                ("CR12", "Crew 2: specialized fence crew", (1, 2, 1, 0), 94, (1.03, 1.0, 0.95), "B1"),
                ("CR13", "Crew 3: installers + operator", (0, 2, 0, 1), 88, (1.0, 1.0, 0.97), "C1"),
                ("CR14", "Crew 4: foreman, installers + operator", (1, 2, 0, 1), 97, (1.05, 1.0, 0.92), "D1")]
        for cid, desc, (a, b, c, d), eff, (ez, st, hd), pv in prof:
            crews.append({"crew_id": cid, "description": desc, "n_R1_foreman": a, "n_R2_installer": b, "n_R3_laborer": c, "n_R4_operator": d,
                          "headcount": F, "loaded_rate_per_crew_hr": F, "efficiency_pct": eff, "difficulty_easy": ez, "difficulty_standard": st,
                          "difficulty_hard": hd, "qualifications": "", "profile_version": pv})
        scale = {"CR11": 0.95, "CR12": 1.05, "CR13": 1.10, "CR14": 1.02}
        for t in range(1, 10):
            for cid in scale:
                options.append({"task_id": f"L{t:02d}", "crew_id": cid, "production_rate": round((10 + t) * scale[cid], 2), "rate_basis": "standard"})
    drivers_used = ["D12", "D04", "D03", "D06", "D08", "D07", "D11", "D09", "D10"]
    labor = [{"task_id": f"L{i:02d}", "task": f"Task {d}", "driver_key": d, "uom": F, "crew_id": "CR1" if i < 3 else "CR2",
              "production_rate": 10 + i, "rate_basis": "standard", "required_roles": "R4" if (crew_profiles and d == "D04") else "", "required_qualifications": "", "qty_base": F, "qty_alt": F, "crew_hrs_base": F, "crew_hrs_alt": F, "crew_rate_per_hr": F,
              "labor_base": F, "labor_alt": F, "per_unit_base": F, "notes": ""} for i, d in enumerate(drivers_used, 1)]
    equip = [{"equip_id": "E01", "equipment": "Skid steer", "owned_or_rented": "rented", "basis": "day", "rate": 300,
              "days_or_units_base": 2, "days_or_units_alt": 1, "fuel_and_consumables_base": 40, "fuel_and_consumables_alt": 20,
              "delivery_pickup_each": 0, "delivery_trips": 0, "ext_base": F, "ext_alt": F, "notes": ""}]
    mob = [{"line_id": "O01", "category": "Mobilization", "item": "Mobilize", "basis": "trip", "unit_cost": 250, "qty_base": 2,
            "qty_alt": 1, "ext_base": F, "ext_alt": F, "notes": ""}]
    services = [{"service_id": k, "service": n, "uom": u, "unit_cost": 40.0, "vendor": "Test vendor", "price_date": as_of, "source_url_or_sku": "fictional",
                 "qty_base": F, "qty_alt": F, "ext_base": F, "ext_alt": F, "notes": ""} for k, (u, n) in vocab.SERVICES.items()]
    meta = [{"key": "workday_hours", "value": 8}, {"key": "ratebook_id", "value": "TEST-BOOK"}, {"key": "version", "value": "1.0.0"},
            {"key": "effective_date", "value": as_of}, {"key": "currency", "value": "USD"},
            {"key": "alternate_id", "value": "ALT-A1"}, {"key": "data_classification", "value": "FICTIONAL_DEMO"},
            {"key": "tax_materials_pct", "value": 0.07}, {"key": "overhead_pct", "value": 0.1},
            {"key": "contingency_pct", "value": 0.05}, {"key": "profit_pct", "value": 0.1}]
    return {
        "Meta": {"header": ["key", "value", "notes"], "rows": meta},
        "Takeoff_In": {"header": ["key", "description", "uom", "qty_base", "qty_alt", "source_ref", "notes"], "rows": take},
        "Materials": {"header": MATERIAL_HEADER, "rows": mats},
        "Roles": {"header": ["role_key", "role", "base_wage_per_hr", "burden_pct (taxes)", "loaded_rate_per_hr"], "rows": roles},
        "Crews": {"header": ["crew_id", "description", "n_R1_foreman", "n_R2_installer", "n_R3_laborer", "n_R4_operator",
                             "headcount", "loaded_rate_per_crew_hr", "efficiency_pct", "difficulty_easy", "difficulty_standard", "difficulty_hard",
                             "qualifications", "profile_version"], "rows": crews},
        "Labor": {"header": ["task_id", "task", "driver_key", "uom", "crew_id", "production_rate (uom per crew-hr)", "rate_basis", "required_roles", "required_qualifications", "qty_base", "qty_alt",
                             "crew_hrs_base", "crew_hrs_alt", "crew_rate_per_hr", "labor_base", "labor_alt", "per_unit_base", "notes"], "rows": labor},
        "Equipment": {"header": ["equip_id", "equipment", "owned_or_rented", "basis (day/hr)", "rate", "days_or_units_base", "days_or_units_alt",
                                 "fuel_and_consumables_base", "fuel_and_consumables_alt", "delivery_pickup_each", "delivery_trips",
                                 "ext_base", "ext_alt", "notes"], "rows": equip},
        "Mobilization_Other": {"header": ["line_id", "category", "item", "basis", "unit_cost", "qty_base", "qty_alt", "ext_base", "ext_alt", "notes"],
                               "rows": mob},
        **({"Crew_Production": {"header": ["task_id", "crew_id", "production_rate", "rate_basis", "notes"], "rows": options}} if options else {}),
        "Services": {"header": ["service_id", "service", "uom", "unit_cost", "vendor", "price_date", "source_url_or_sku", "qty_base", "qty_alt",
                                "ext_base", "ext_alt", "notes"], "rows": services},
    }


def valid_bytes(**kw):
    return build(valid_spec(), **kw)


def mutated(fn):
    """Apply fn(spec) to a fresh valid spec and return workbook bytes."""
    spec = copy.deepcopy(valid_spec())
    fn(spec)
    return build(spec)


def row(spec, sheet, key_header, key):
    return next(r for r in spec[sheet]["rows"] if r[key_header] == key)

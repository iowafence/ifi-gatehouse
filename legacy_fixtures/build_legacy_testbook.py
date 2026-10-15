"""Build the FICTIONAL demonstration rate book (config/demo_ratebook.fictional.xlsx) from the pricing test builder.
Every number is invented. Crew 1/2/3 = 104% / 94% / 88%. Crew 1 has no drill operator. No company data, no answer key.
Run from the engine root: python3 legacy_fixtures/build_legacy_testbook.py"""
import datetime
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent  # engine root (imports pricing/, tests/)
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from pricing import vocab  # noqa: E402
from tests import xlsx_builder as xb  # noqa: E402

EFFECTIVE = datetime.date(2026, 10, 1)
F = xb.F
# crew_id, name, members (foreman, installer, laborer, operator), efficiency, difficulty response (easy, standard, hard), profile, quals, task scale
CREWS = [("CR1", "Crew 1", (1, 2, 1, 0), 104, (1.10, 1.0, 0.80), "A1", "", 0.95),
         ("CR2", "Crew 2", (1, 1, 1, 1), 94, (1.03, 1.0, 0.92), "B1", "drilling_operator", 1.00),
         ("CR3", "Crew 3", (1, 2, 0, 1), 88, (1.00, 1.0, 0.97), "C1", "drilling_operator", 1.10)]


def spec():
    s = xb.valid_spec(as_of=EFFECTIVE, crew_profiles=True)
    for r in s["Materials"]["rows"]:
        r["vendor"], r["source_url_or_sku"] = "Fictional demo vendor", "fictional"
    for r in s["Services"]["rows"]:
        r["vendor"] = "Fictional demo vendor"
    s["Roles"]["rows"][3]["role"] = "Drill operator"
    for r in s["Meta"]["rows"]:
        if r["key"] == "ratebook_id":
            r["value"] = "IFI-DEMO-FICTIONAL"
    crews, options = [], []
    for cid, name, (a, b, c, d), eff, (ez, st, hd), pv, quals, _ in CREWS:
        crews.append({"crew_id": cid, "description": name, "n_R1_foreman": a, "n_R2_installer": b, "n_R3_laborer": c, "n_R4_operator": d,
                      "headcount": F, "loaded_rate_per_crew_hr": F, "efficiency_pct": eff, "difficulty_easy": ez, "difficulty_standard": st,
                      "difficulty_hard": hd, "qualifications": quals, "profile_version": pv})
    s["Crews"]["rows"] = crews
    for t, lab in enumerate(s["Labor"]["rows"], 1):
        lab["crew_id"] = "CR2"
        lab["task"] = vocab.DRIVERS[lab["driver_key"]][1]
        if lab["driver_key"] == "D04":          # core drilling: needs an operator who holds the drilling qualification
            lab["required_roles"], lab["required_qualifications"] = "R4", "drilling_operator"
        for cid, _n, _m, _e, _d, _p, _q, scale in CREWS:
            if cid != "CR2":
                options.append({"task_id": lab["task_id"], "crew_id": cid, "production_rate": round(lab["production_rate"] * scale, 2), "rate_basis": "standard"})
    s["Crew_Production"]["rows"] = options
    return s


if __name__ == "__main__":
    out = HERE / "legacy_3crew_testbook.fictional.xlsx"
    out.write_bytes(xb.build(spec()))
    print("wrote", out, out.stat().st_size, "bytes")

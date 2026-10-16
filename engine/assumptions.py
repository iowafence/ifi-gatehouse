"""Named estimating assumptions, shown on the export. Nothing the engine assumes may stay silent.

Three kinds, each with an owner and a status:
  OWNER_DECIDED                 an owner decision the engine's values match (checked against the live ruleset / rate book, not assumed)
  ENGINE_DEFAULT_OWNER_PENDING  the engine uses a ruleset default because the owner's choice has not been received
  RULESET_PARAMETER             every other quantity rule the ruleset applies, with its status (draft until an estimator approves it)
Pure read: nothing here changes a price or a quantity."""
from pricing.engine import GATE_ASSEMBLY_RATE, GATE_OVERRIDE_IDS, REPLACED_GATE_MATERIALS

OWNER = "Jordan"
DECIDED_UTC = "2026-10-16"


def _p(state):
    rules = state["ruleset"]["rules"]
    return rules["params"], state["ruleset"]


def _items(state):
    P, rs = _p(state)
    ref = f"ruleset {rs['ruleset_id']} {rs['version']}"
    out = []
    stick = P.get("rail_stick_ft")
    out.append({"id": "ASM-M07-COUPLINGS", "kind": "OWNER_DECISION", "applies_to": ["M07"], "name": "Rail couplings (M07 rail sleeves)",
                "value": {"rail_stick_ft": stick, "rule": "one coupling at each joint: ceil(rail LF / stick) - 1 per rail line per run"},
                "owner": OWNER, "decided": DECIDED_UTC, "source": f"{ref} param rail_stick_ft",
                "status": "OWNER_DECIDED" if stick == 21 else "OWNER_DECISION_NOT_MATCHED",
                "prior_engine_behavior": "Unchanged. The engine already used a 21 ft stick and a coupling at each joint (ruleset parameter), but it was not shown as an assumption.",
                "export_line": f"Assumption (owner: {OWNER}): rail couplings (M07) use {stick} ft rail sticks with a coupling at each joint." +
                               ("" if stick == 21 else f" WARNING: the live ruleset uses {stick} ft, not the 21 ft the owner decided.")})
    t, l = P.get("brace_bands_terminal_side_per_brace"), P.get("brace_bands_line_side_per_brace")
    out.append({"id": "ASM-BRACE-BANDS", "kind": "OWNER_DECISION", "applies_to": ["M09", "M10"], "name": "Brace bands (M09 terminal side, M10 line-post side)",
                "value": {"terminal_side_per_assembly": t, "line_side_per_assembly": l, "per_assembly_total": (t or 0) + (l or 0)},
                "owner": OWNER, "decided": "2026-10-16 14:15 CT", "source": f"{ref} params brace_bands_terminal_side_per_brace, brace_bands_line_side_per_brace",
                "status": "OWNER_DECIDED" if (t, l) == (1, 1) else "OWNER_DECISION_NOT_MATCHED",
                "prior_engine_behavior": "Ruleset 1.2.0 priced TWO bands per side (four per brace assembly). That was wrong; corrected to one per side, two per assembly.",
                "export_line": f"Assumption (owner: {OWNER}): brace bands one per side, two per brace assembly (M09 {t}, M10 {l} per assembly)." +
                               ("" if (t, l) == (1, 1) else " WARNING: the live ruleset differs from the owner decision.")})
    out += _geometry_items(state, P, ref)
    wd = state.get("wage_determination") or {}
    for r in wd.get("rows", []):
        if isinstance(r, dict) and r.get("floor_adjustment"):
            out.append({"id": f"ASM-WAGE-FLOOR-{r['role_key']}", "kind": "ENGINE_RULE", "applies_to": [r["role_key"]], "name": f"Wage raised to the Attachment A floor ({r['role_key']})",
                        "value": {"workbook_rate_per_hr": r.get("workbook_rate_per_hr"), "priced_base_rate_per_hr": r["base_rate"], "classification": r["classification"]},
                        "owner": OWNER, "decided": "2026-10-16 14:15 CT", "source": "owner rule: workbook role rate if at or above the Attachment A floor, else the floor, flagged",
                        "status": "FLAGGED",
                        "prior_engine_behavior": "New rule.",
                        "export_line": f"Wage flag ({r['role_key']}): {r['floor_adjustment']}."})
    if wd:
        out.append({"id": "ASM-LABOR-ROUNDING", "kind": "OWNER_DECISION", "applies_to": ["L01", "L02", "L03", "L04", "L05", "L06", "L07", "L08", "L09", "L10"],
                    "name": "Labor rounding convention", "value": {"rounding": "once per labor task extension (hours x loaded rate)"},
                    "owner": OWNER, "decided": "2026-10-16 15:28 CT", "source": "owner decision 3:28 PM CT", "status": "OWNER_DECIDED",
                    "prior_engine_behavior": "Rounded wages, fringe and employer cost separately and summed them, which could differ from hours x loaded rate by a cent.",
                    "export_line": "Labor rounding: each task extension is rounded once (hours x loaded rate). Wages, fringe and burden are supporting detail and may differ from the extension by a cent."})
    adm = wd.get("certified_payroll_admin") or {}
    if wd and adm.get("basis") == "not_charged":
        out.append({"id": "ASM-CERTIFIED-PAYROLL-ZERO", "kind": "OWNER_DECISION", "applies_to": ["certified_payroll_admin"], "name": "Certified-payroll administration",
                    "value": {"amount": 0.0, "basis": "not_charged", "reason": adm.get("reason")},
                    "owner": OWNER, "decided": "2026-10-16 14:51 CT", "source": adm.get("source_ref") or "pinned workbook",
                    "status": "OWNER_DECIDED",
                    "prior_engine_behavior": "Earlier test runs charged a placeholder (per week); removed. The pinned workbook carries no certified-payroll line, so nothing is charged.",
                    "export_line": "Certified-payroll administration: $0.00; the pinned workbook carries no such line."})
    confirmed = {"R1": "Laborer, common or general", "R2": "Laborer, common or general", "R3": "Laborer, common or general", "R4": "Power equipment operator, skid steer"}
    if wd.get("rows"):
        got = {r["role_key"]: r.get("classification") for r in wd["rows"] if isinstance(r, dict)}
        names = {r["role_key"]: r["role"] for r in state["ratebook"]["roles"]}
        same = got == confirmed
        out.append({"id": "ASM-WAGE-CLASSIFICATION-MAPPING", "kind": "OWNER_DECISION", "applies_to": sorted(confirmed), "name": "Role to wage classification mapping",
                    "value": [{"role": names.get(k, k), "classification": v} for k, v in sorted(got.items())], "owner": OWNER, "decided": "2026-10-16 14:51 CT", "source": "owner confirmation 2:51 PM CT",
                    "status": "OWNER_DECIDED" if same else "OWNER_DECISION_NOT_MATCHED",
                    "prior_engine_behavior": "Unchanged: classifications are recorded by a named person; the engine never selects one.",
                    "export_line": "Wage classifications (confirmed by " + OWNER + "): Foreman, Installer and Laborer = Laborer, common or general; Equipment operator = Power equipment operator, skid steer." +
                                   ("" if same else " WARNING: the recorded classifications differ from the confirmed mapping.")})
    if (state["scope"].get("project_ref") if isinstance(state["scope"], dict) else None) == "DP-001":
        widths = {g["gate_id"]: (g["clear_width_ft"].get("value") if isinstance(g.get("clear_width_ft"), dict) else None)
                  for g in state["scope"].get("gates", []) if g.get("gate_id") in ("G1", "G2", "G3")}
        width_text = ", ".join(f"{gid} {widths.get(gid):g} ft" if isinstance(widths.get(gid), (int, float)) else f"{gid} unresolved"
                               for gid in ("G1", "G2", "G3"))
        out.append({"id": "ASM-GATE-ASSEMBLY-250", "kind": "OWNER_DECISION", "applies_to": sorted(REPLACED_GATE_MATERIALS),
                    "name": "Complete furnished gate assembly", "value": {"rate_per_clear_opening_lf": float(GATE_ASSEMBLY_RATE), "replaces": sorted(REPLACED_GATE_MATERIALS),
                    "scope_widths_ft": widths,
                    "material_tax_pct": 0}, "owner": OWNER, "decided": "2026-10-16 13:27 CT", "source": "Jordan estimating decision #4 (revised)",
                    "status": "OWNER_DECIDED",
                    "prior_engine_behavior": "Priced the individual gate material lines M21, M22, M28-M37, M43 and M44 from the pinned workbook.",
                    "export_line": f"Assumption (Jordan, decision #4 revised): complete gate assembly material furnished at ${GATE_ASSEMBLY_RATE:,.2f} per LF of scope clear-opening width per gate ({width_text}), including frame, fabric, fittings, hinges, latches and all gate hardware. Replaces M21, M22, M28–M37, M43 and M44. Gate posts, footings, install labor, mobilization and markup remain. Material tax 0%."})
        out.append({"id": "ASM-SHARED-POST-BRACING-WHOLE", "kind": "OWNER_DECISION", "applies_to": ["M06", "M08", "M09", "M10", "M12", "M14", "M16"],
                    "name": "Shared post and bracing lines", "value": "kept whole", "owner": OWNER, "decided": "2026-10-16 13:35 CT",
                    "source": "Jordan gate assembly override classification", "status": "OWNER_DECIDED",
                    "prior_engine_behavior": "M12, M14 and M16 were apportioned by post counts on the bid schedule; the complete material lines were already priced.",
                    "export_line": "Shared post and bracing lines carried whole; no gate-post share split out."})
        out.append({"id": "ASM-O15-INSURANCE", "kind": "OWNER_DECISION", "applies_to": ["O15"], "name": "Project-specific insurance (O15)",
                    "value": {"line_id": "O15", "item": "Project-specific insurance", "basis": "LS", "amount": 0.0, "carried_in": "overhead"},
                    "line": {"line_id": "O15", "item": "Project-specific insurance", "basis": "LS", "amount": 0.0, "note": "carried within overhead"},
                    "owner": OWNER, "decided": DECIDED_UTC, "source": "Section 00 0800 SC-11.1; rate book O15 is an unused template row",
                    "status": "OWNER_DECIDED",
                    "prior_engine_behavior": "Silently ignored: O15 is an unused (blank) template row in the pinned workbook, so the engine priced nothing for it and printed no qualification.",
                    "export_line": "Project insurance per SC-11.1 carried within overhead"})
    return out


def _facts(scope, path_fn):
    out = []
    fs = scope.get("footing_scope") if isinstance(scope, dict) else None
    for ri, run in enumerate((fs or {}).get("runs") or []):
        for si, side in enumerate(((run.get("layout") or {}).get("sides")) or []):
            out += path_fn(ri, si, side, run)
    return out


def _geometry_items(state, P, ref):
    """Owner decisions of 2026-10-16 4:35 PM CT on ruleset 1.2.1 behaviours and the assumptions it rests on. A fact that a document now states drops out
    of the assumption list by itself (it is then documented, not assumed). The ruleset approval itself is NOT recorded here: the owner records it in the app."""
    scope = state["scope"] if isinstance(state.get("scope"), dict) else {}
    items = []
    when = "2026-10-16 16:35 CT"
    items.append({"id": "ASM-LINE-POST-ROUNDING", "kind": "OWNER_DECISION", "applies_to": ["M02", "M04", "D03", "D04"], "name": "Line posts at the 10 ft maximum spacing round up",
                  "value": {"rounding": "up", "max_spacing_ft": 10}, "owner": OWNER, "decided": when, "source": f"{ref}; 32 31 13 3.1.B (10'-0\" on center maximum)", "status": "OWNER_DECIDED",
                  "prior_engine_behavior": "Unchanged: intervals between terminal, corner and gate posts were already rounded up.",
                  "export_line": "Assumption (owner: Jordan): line posts at the 10 ft maximum spacing are rounded up."})
    rail, gate_h = P.get("mid_rail_elevation_ft"), P.get("gate_leaf_catalog_height_in")
    stops = isinstance(rail, (int, float)) and isinstance(gate_h, (int, float)) and rail * 12 < gate_h
    items.append({"id": "ASM-MID-RAIL-STOPS-AT-GATES", "kind": "OWNER_DECISION", "applies_to": ["M06", "M07", "M11"], "name": "Mid rail stops at gates",
                  "value": {"mid_rail_elevation_ft": rail, "gate_leaf_height_in": gate_h}, "owner": OWNER, "decided": when, "source": f"{ref} params mid_rail_elevation_ft, gate_leaf_catalog_height_in",
                  "status": "OWNER_DECIDED" if stops else "OWNER_DECISION_NOT_MATCHED",
                  "prior_engine_behavior": "Unchanged: the 7 ft gate leaf occupies the 5 ft mid-rail level, so the mid rail is counted net of gate openings.",
                  "export_line": "Assumption (owner: Jordan): the Type A mid rail stops at gates (mid rail at 5 ft, gate leaf 7 ft)." + ("" if stops else " WARNING: the live ruleset heights no longer match.")})
    tr = (scope.get("global_requirements") or {}).get("top_rail_continuous_across_gate_openings")
    pend = []
    if isinstance(tr, dict) and tr.get("status") != "confirmed":
        pend.append(("ASM-TOP-RAIL-CONTINUOUS", "Top rail continuous across gate openings", ["M05", "M07", "M11", "D06"], {"value": tr.get("value")},
                     f"top rail continuous across gate openings = {tr.get('value')}"))
    stations = _facts(scope, lambda ri, si, side, run: [(g.get("gate_id"), g["station_ft"], f"/footing_scope/runs/{ri}/layout/sides/{si}/gates/{gi}/station_ft")
                                                        for gi, g in enumerate(side.get("gates") or []) if isinstance(g.get("station_ft"), dict)])
    open_st = [(gid, f, path) for gid, f, path in stations if f.get("status") != "confirmed"]
    if open_st:
        txt = ", ".join(f"{gid} {f.get('value'):g} ft" for gid, f, _ in sorted(open_st, key=lambda x: str(x[0])))
        pend.append(("ASM-GATE-STATIONS", "Gate stations (where each gate sits along its side)", ["M01", "M02", "M08", "M09", "M10", "M12", "M14", "M16", "M17", "M40", "S01"],
                     {"stations_ft": [{"gate": gid, "fact_path": path, "station_ft": f.get("value")} for gid, f, path in open_st]}, f"gate stations {txt}"))
    sides = _facts(scope, lambda ri, si, side, run: [(run.get("run_id") or ri, side["length_lf"], f"/footing_scope/runs/{ri}/layout/sides/{si}/length_lf")]
                   if isinstance(side.get("length_lf"), dict) and side["length_lf"].get("status") != "confirmed" else [])
    if sides:
        txt = ", ".join(f"{rid} side {f.get('value'):g} ft" for rid, f, _ in sides)
        pend.append(("ASM-SIDE-LENGTHS-QUALIFIED", "Type B side length", ["M03", "M04", "M13", "M15", "M18", "M20"],
                     {"sides_ft": [{"run": rid, "fact_path": path, "length_ft": f.get("value")} for rid, f, path in sides]}, txt))
    for aid, name, applies, value, text in pend:
        items.append({"id": aid, "kind": "OWNER_DECISION", "applies_to": applies, "name": name, "value": value, "owner": OWNER, "decided": when,
                      "source": "owner decision 4:35 PM CT: accepted as a qualified assumption until a document states it", "status": "OWNER_DECIDED",
                      "prior_engine_behavior": "Priced from a person's approved derivation of the plan dimensions; the export labelled the footing scope NOT BID READY and did not name this assumption.",
                      "export_line": f"Qualified assumption (owner: Jordan, until a document states it): {text}."})
    return items


def gate_assembly_lines(est):
    """The G1/G2/G3 gate assembly lines of one priced scenario: width, quantity and extension, exactly as the engine priced them."""
    rows = []
    for l in est["materials"]["lines"]:
        if l["item_id"] in GATE_OVERRIDE_IDS.values():
            rows.append({"gate_id": l["gate_id"], "bid_item": l["bid_item"], "clear_width_ft": l["clear_width_ft"], "gate_quantity": l["gate_quantity"],
                         "opening_lf": l["quantity"], "rate_per_lf": l["rate_per_lf"], "extension": l["extended"]})
    return sorted(rows, key=lambda r: r["gate_id"])


def build(state):
    """-> {"items": [...], "ruleset_parameters": {...}, "allowances": ...}. Never raises on a project without a rate book."""
    if not state.get("ratebook") or not isinstance(state.get("ruleset"), dict):
        return None
    P, rs = _p(state)
    status = "approved by " + (state.get("ruleset_approval") or {}).get("by", "") if state.get("ruleset_approval") else "DRAFT: not approved by an estimator"
    est = state.get("estimate")
    gal = {sref: gate_assembly_lines(sc) for sref, sc in est["scenarios"].items()} if est else {}
    return {"items": _items(state), "gate_assembly_lines": gal,
            "ruleset_parameters": {"ruleset_id": rs["ruleset_id"], "version": rs["version"], "sha256": rs["sha256"], "status": status,
                                   "params": [{"param": k, "value": v} for k, v in sorted(P.items())]},
            "allowances": {"amount": 0.0, "locked": True, "note": "no allowances are carried"}}


def export_lines(state):
    b = build(state)
    if not b:
        return []
    out = [i["export_line"] for i in b["items"]]
    est = state.get("estimate")
    for r in (b["gate_assembly_lines"].get(est["headline_scope_ref"]) or []) if est else []:
        out.append(f"Gate {r['gate_id']} assembly (bid item {r['bid_item']}): {r['clear_width_ft']:g} ft clear opening x gate quantity {r['gate_quantity']:g} = {r['opening_lf']:g} LF x ${r['rate_per_lf']:,.2f}/LF = ${r['extension']:,.2f}")
    return out

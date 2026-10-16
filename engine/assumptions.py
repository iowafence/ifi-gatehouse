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
    wd = state.get("wage_determination") or {}
    for r in wd.get("rows", []):
        if isinstance(r, dict) and r.get("floor_adjustment"):
            out.append({"id": f"ASM-WAGE-FLOOR-{r['role_key']}", "kind": "ENGINE_RULE", "applies_to": [r["role_key"]], "name": f"Wage raised to the Attachment A floor ({r['role_key']})",
                        "value": {"workbook_rate_per_hr": r.get("workbook_rate_per_hr"), "priced_base_rate_per_hr": r["base_rate"], "classification": r["classification"]},
                        "owner": OWNER, "decided": "2026-10-16 14:15 CT", "source": "owner rule: workbook role rate if at or above the Attachment A floor, else the floor, flagged",
                        "status": "FLAGGED",
                        "prior_engine_behavior": "New rule.",
                        "export_line": f"Wage flag ({r['role_key']}): {r['floor_adjustment']}."})
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

"""Named estimating assumptions, shown on the export. Nothing the engine assumes may stay silent.

Three kinds, each with an owner and a status:
  OWNER_DECIDED                 an owner decision the engine's values match (checked against the live ruleset / rate book, not assumed)
  ENGINE_DEFAULT_OWNER_PENDING  the engine uses a ruleset default because the owner's choice has not been received
  RULESET_PARAMETER             every other quantity rule the ruleset applies, with its status (draft until an estimator approves it)
Pure read: nothing here changes a price or a quantity."""
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
    el, te = P.get("gate_elbows_per_leaf"), P.get("gate_tees_per_leaf")
    out.append({"id": "ASM-GATE-FRAME-CORNERS", "kind": "ENGINE_DEFAULT", "applies_to": ["M29", "M30"], "name": "Gate frame corners (M29 elbows, M30 tees)",
                "value": {"corners": "FITTED", "elbows_per_leaf": el, "tees_per_leaf": te},
                "owner": OWNER, "decided": None, "source": f"{ref} params gate_elbows_per_leaf, gate_tees_per_leaf",
                "status": "ENGINE_DEFAULT_OWNER_PENDING",
                "owner_decision": "NOT RECEIVED: the instruction read \"[FITTED / WELDED]\" with the choice unfilled",
                "prior_engine_behavior": f"Silently counted FITTED corners ({el} elbows and {te} tees per leaf) from the ruleset. The documents allow either: F502 detail 3 \"WELDED OR FITTED CORNERS\"; 32 31 13 2.5.B \"welded or fitted corners\".",
                "export_line": f"Assumption (engine default; owner choice pending): gate frames priced with FITTED corners, {el} elbows and {te} tees per leaf. The documents allow welded or fitted corners (F502 detail 3; 32 31 13 2.5.B)."})
    if (state["scope"].get("project_ref") if isinstance(state["scope"], dict) else None) == "DP-001":
        out.append({"id": "ASM-O15-INSURANCE", "kind": "OWNER_DECISION", "applies_to": ["O15"], "name": "Project-specific insurance (O15)",
                    "value": {"line_id": "O15", "item": "Project-specific insurance", "basis": "LS", "amount": 0.0, "carried_in": "overhead"},
                    "line": {"line_id": "O15", "item": "Project-specific insurance", "basis": "LS", "amount": 0.0, "note": "carried within overhead"},
                    "owner": OWNER, "decided": DECIDED_UTC, "source": "Section 00 0800 SC-11.1; rate book O15 is an unused template row",
                    "status": "OWNER_DECIDED",
                    "prior_engine_behavior": "Silently ignored: O15 is an unused (blank) template row in the pinned workbook, so the engine priced nothing for it and printed no qualification.",
                    "export_line": "Project insurance per SC-11.1 carried within overhead"})
    return out


def build(state):
    """-> {"items": [...], "ruleset_parameters": {...}, "allowances": ...}. Never raises on a project without a rate book."""
    if not state.get("ratebook") or not isinstance(state.get("ruleset"), dict):
        return None
    P, rs = _p(state)
    status = "approved by " + (state.get("ruleset_approval") or {}).get("by", "") if state.get("ruleset_approval") else "DRAFT: not approved by an estimator"
    return {"items": _items(state),
            "ruleset_parameters": {"ruleset_id": rs["ruleset_id"], "version": rs["version"], "sha256": rs["sha256"], "status": status,
                                   "params": [{"param": k, "value": v} for k, v in sorted(P.items())]},
            "allowances": {"amount": 0.0, "locked": True, "note": "no allowances are carried"}}


def export_lines(state):
    b = build(state)
    return [i["export_line"] for i in b["items"]] if b else []

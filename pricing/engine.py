"""Authoritative commercial calculation: validated quantities + approved rate book -> estimate. Pure, deterministic.

Python decides every dollar. No spreadsheet is opened, no cached Excel value is read, no model is consulted.
The engine does NOT trust its callers: it re-validates the quantity payload, the rate book, the unit of every join,
the labor approval and the rate-book identity before it computes anything, and it collects EVERY blocker
(PricingBlocked.problems) rather than stopping at the first, so a person sees the whole list at once.

Arithmetic is exact Decimal. Each reported line is rounded half-up to the cent and totals foot to the lines. ROUNDUP of
order quantities is an exact decimal ceiling, so 10 x (1 + 10%) is 11, never 12 (binary floats get that wrong)."""
import datetime
import hashlib
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from . import crews, jsonschema_lite, prevailing, vocab
from .ratebook import canonical, ref as ratebook_ref

CENT = Decimal("0.01")


class PricingBlocked(Exception):
    def __init__(self, problems):
        self.problems = problems
        super().__init__("; ".join(f"{p['code']}[{p.get('ref', '')}]: {p['message']}" for p in problems[:5]) + (" ..." if len(problems) > 5 else ""))


def D(x):
    return Decimal(repr(x)) if isinstance(x, float) else Decimal(x)


def _c(x):
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def _money(x):
    return float(_c(x))


def _num(x):
    return int(x) if x == x.to_integral_value() else float(x)


def _problem(code, message, ref=None, scope_ref=None):
    p = {"code": code, "message": message}
    if ref is not None:
        p["ref"] = ref
    if scope_ref is not None:
        p["scope_ref"] = scope_ref
    return p


def used_roles(ratebook):
    """Cost-bearing roles: members of EVERY crew the book prices for a task (default or optional), so each candidate crew uses cleared wages."""
    return crews.used_roles(ratebook)


def check(payload, ratebook, *, labor_basis=None, expected_ratebook_ref=None, as_of=None, max_ratebook_age_days=None,
          require_ruleset_approval=True, expected_scope_version=None, crew_plan=None):
    """Every reason this payload cannot be priced against this rate book. Empty list = priceable."""
    out = []
    for p, name in ((payload, "quantity_payload.v1"), (ratebook, "ratebook.v1")):
        for path, msg in jsonschema_lite.problems(p, name):
            out.append(_problem("SCHEMA_VIOLATION", f"{name}{path}: {msg}", path))
    if out:
        return out
    scope_refs = {i["scope_ref"] for i in payload["items"]}
    if len(scope_refs) != 1:
        return [_problem("MIXED_SCOPE_REFS", f"one payload prices one scenario; found {sorted(scope_refs)}")]
    sref = next(iter(scope_refs))
    meta = ratebook["meta"]
    if sref != vocab.BASE and sref != meta["alternate_id"]:
        out.append(_problem("ALTERNATE_NOT_IN_RATEBOOK", f"rate book {meta['ratebook_id']} v{meta['version']} has columns for {meta['alternate_id']}, not {sref}", sref, sref))

    today = as_of or datetime.date.today()
    if meta["effective_date"] > today.isoformat():
        out.append(_problem("RATEBOOK_NOT_EFFECTIVE", f"rate book is effective {meta['effective_date']}, after {today}", meta["version"]))
    if max_ratebook_age_days is not None and (today - datetime.date.fromisoformat(meta["effective_date"])).days > max_ratebook_age_days:
        out.append(_problem("RATEBOOK_STALE", f"rate book effective {meta['effective_date']} is older than {max_ratebook_age_days} days", meta["version"]))
    if expected_ratebook_ref is not None:
        got = ratebook_ref(ratebook)
        if got["content_sha256"] != expected_ratebook_ref.get("content_sha256"):
            out.append(_problem("STALE_RATEBOOK_VERSION", f"approvals are bound to {expected_ratebook_ref.get('ratebook_id')} v{expected_ratebook_ref.get('version')}, "
                                f"but this is v{got['version']} ({got['content_sha256'][:12]})", got["version"]))

    if expected_scope_version is not None and payload["revision"]["scope_version"] != expected_scope_version:
        out.append(_problem("CONFLICTING_QUANTITY_VERSION", f"quantities were generated from scope version {payload['revision']['scope_version']} "
                            f"but scope version {expected_scope_version} is current", sref, sref))
    rs = payload["revision"]["ruleset"]
    if require_ruleset_approval and not rs["approved"]:
        out.append(_problem("RULESET_NOT_APPROVED", f"quantity ruleset {rs['ruleset_id']} v{rs['version']} has no named approval", rs["sha256"][:12]))

    seen, mats, drivers = set(), {}, {}
    for it in payload["items"]:
        key = it.get("item_id") or it.get("driver_key")
        if key in vocab.RETIRED:
            out.append(_problem("RETIRED_ITEM_ID", vocab.RETIRED[key], key))
            continue
        if key in seen:
            out.append(_problem("DUPLICATE_ITEM_ID", f"{key} appears more than once in the quantity payload", key))
            continue
        seen.add(key)
        want = vocab.uom(key)
        if want is None:
            out.append(_problem("UNKNOWN_ITEM_ID" if "item_id" in it else "UNKNOWN_DRIVER", f"{key} is not in the stable vocabulary", key))
            continue
        if ("item_id" in it) != (vocab.is_material(key) or vocab.is_service(key)):
            out.append(_problem("KEY_KIND_MISMATCH", f"{key} is used as the wrong kind of key", key))
            continue
        if it["uom"] != want:
            out.append(_problem("INCOMPATIBLE_UNIT", f"{key} is {want} in the vocabulary but the payload says {it['uom']}", key))
            continue
        if it["status"] == "unresolved":
            out.append(_problem("UNRESOLVED_QUANTITY", "; ".join(it.get("unresolved_reasons", [])) or "quantity is unresolved", key))
            continue
        if it["status"] == "provisional":
            out.append(_problem("UNAPPROVED_PROVISIONAL", "quantity rests on an inferred fact no human has approved; approval makes the fact human-resolved", key))
            continue
        if any(r["scope_version"] > payload["revision"]["scope_version"] for r in it["approved_resolutions"]):
            out.append(_problem("INVALID_RESOLUTION", "a recorded resolution claims a scope version newer than the quantities", key))
            continue
        (mats if key in vocab.MATERIALS or key in vocab.SERVICES else drivers)[key] = it

    for key in list(vocab.MATERIALS) + list(vocab.SERVICES) + ["D01", "D02"]:
        if key not in seen:
            out.append(_problem("MISSING_ITEM", f"the quantity payload has no entry for {key}; absence is not zero", key))
    rates = {m["item_id"]: m for m in ratebook["materials"]}
    services = {s["service_id"]: s for s in ratebook.get("services", [])}
    for key, it in mats.items():
        if it["quantity"] > 0:
            if key in vocab.SERVICES:
                rate, code, name = services.get(key), "MISSING_SERVICE_RATE", vocab.SERVICES[key][1]
            else:
                rate, code, name = rates.get(key), "MISSING_MATERIAL_RATE", vocab.MATERIALS[key][1]
            if rate is None:
                out.append(_problem(code, f"the rate book has no rate for {key} ({name}) but the takeoff needs {it['quantity']:g} {it['uom']}", key))
            elif rate["uom"] != it["uom"]:
                out.append(_problem("INCOMPATIBLE_UNIT", f"{key} is priced per {rate['uom']} but quantified in {it['uom']}", key))
    ex = payload["revision"].get("sales_tax_exemption", {"applies": False, "evidence_refs": []})
    if ex["applies"] and not ex["evidence_refs"]:
        out.append(_problem("TAX_EXEMPTION_UNSUPPORTED", "a sales-tax exemption is claimed without a document citation", "tax"))
    crew_by_id = {c["crew_id"]: c for c in ratebook["crews"]}
    roles = {r["role_key"] for r in ratebook["roles"]}
    for t in ratebook["labor_tasks"]:
        if t["driver_key"] not in drivers:
            if not any(p.get("ref") == t["driver_key"] for p in out):
                out.append(_problem("MISSING_DRIVER_QUANTITY", f"labor task {t['task_id']} ({t['task']}) needs driver {t['driver_key']}, which the takeoff did not supply", t["driver_key"]))
        crew = crew_by_id.get(t["crew_id"])
        if crew is None:
            out.append(_problem("UNKNOWN_CREW", f"labor task {t['task_id']} uses crew {t['crew_id']}, which the rate book does not define", t["crew_id"]))
        elif any(r not in roles for r in crew["members"]):
            out.append(_problem("UNKNOWN_ROLE", f"crew {crew['crew_id']} uses a role with no wage", crew["crew_id"]))
        if t["uom"] != vocab.uom(t["driver_key"]):
            out.append(_problem("INCOMPATIBLE_UNIT", f"labor task {t['task_id']} rate is per {t['uom']} but driver {t['driver_key']} is {vocab.uom(t['driver_key'])}", t["task_id"]))
    if ratebook["labor_tasks"]:
        if not labor_basis or labor_basis.get("status") != "decided":
            out.append(_problem("LABOR_NOT_APPROVED", "the Labor Gate has no valid approval of the labor basis", "labor"))
        elif labor_basis.get("ratebook_labor_sha256") != ratebook["hashes"]["labor_sha256"]:
            out.append(_problem("LABOR_APPROVAL_STALE", "the labor basis was approved against different labor rates than this rate book carries", "labor"))
        elif labor_basis.get("wage_basis") == "prevailing_wage":
            ev = prevailing.evaluate(labor_basis.get("wage_determination"), used_roles(ratebook), as_of)
            out += [dict(_problem(p["code"], p["message"], p.get("role_key", "labor"))) for p in prevailing.all_problems(ev)]
    if crews.plan_required(ratebook) or crew_plan:
        out += [_problem(p["code"], p["message"], p.get("ref")) for p in crews.plan_problems(crew_plan, ratebook)]
    return out


def price(payload, ratebook, *, labor_basis=None, expected_ratebook_ref=None, as_of=None, max_ratebook_age_days=None,
          require_ruleset_approval=True, expected_scope_version=None, crew_plan=None):
    """Price ONE scenario. Raises PricingBlocked(problems) unless every check passes."""
    problems = check(payload, ratebook, labor_basis=labor_basis, expected_ratebook_ref=expected_ratebook_ref, as_of=as_of,
                     max_ratebook_age_days=max_ratebook_age_days, require_ruleset_approval=require_ruleset_approval,
                     expected_scope_version=expected_scope_version, crew_plan=crew_plan)
    if problems:
        raise PricingBlocked(problems)
    sref = payload["items"][0]["scope_ref"]
    col = "base" if sref == vocab.BASE else "alt"
    qty = {(i.get("item_id") or i["driver_key"]): i for i in payload["items"]}
    rates = {m["item_id"]: m for m in ratebook["materials"]}
    mk = ratebook["markups"]

    exemption = payload["revision"].get("sales_tax_exemption", {"applies": False})["applies"]
    mat_lines, mat_total, taxable_base = [], Decimal(0), Decimal(0)
    for key in vocab.MATERIALS:
        it = qty[key]
        q = D(it["quantity"])
        if q == 0:
            continue
        r = rates[key]
        digits = Decimal("0.1") if r["uom"] == "CU YD" else Decimal("1")
        order = (q * (1 + D(r["overage_pct"]))).quantize(digits, rounding=ROUND_CEILING)
        ext = _c(order * D(r["unit_price"]))
        exempt = bool(exemption and key in vocab.INCORPORATED)      # only items incorporated into the Work; never tools, equipment or services
        mat_total += ext
        if not exempt:
            taxable_base += ext
        mat_lines.append({"item_id": key, "description": vocab.MATERIALS[key][1], "uom": r["uom"], "quantity": _num(q),
                          "overage_pct": r["overage_pct"], "order_quantity": _num(order), "unit_price": r["unit_price"],
                          "extended": _money(ext), "tax_exempt": exempt, "status": it["status"],
                          "rate": {"vendor": r["vendor"], "price_date": r["price_date"], "source_ref": r["source_ref"]},
                          "calculation_method": it["calculation_method"], "source_evidence_refs": it["source_evidence_refs"]})

    svc = {s_["service_id"]: s_ for s_ in ratebook.get("services", [])}
    svc_lines, svc_total = [], Decimal(0)
    for key in vocab.SERVICES:
        q = D(qty[key]["quantity"])
        if q == 0:
            continue
        ext = _c(q * D(svc[key]["unit_cost"]))
        svc_total += ext
        svc_lines.append({"service_id": key, "description": vocab.SERVICES[key][1], "uom": svc[key]["uom"], "quantity": _num(q),
                          "unit_cost": svc[key]["unit_cost"], "extended": _money(ext), "status": qty[key]["status"],
                          "rate": {"vendor": svc[key]["vendor"], "price_date": svc[key]["price_date"], "source_ref": svc[key]["source_ref"]},
                          "calculation_method": qty[key]["calculation_method"], "source_evidence_refs": qty[key]["source_evidence_refs"]})

    prev = labor_basis.get("wage_basis") == "prevailing_wage" if labor_basis else False
    if prev:
        ev = prevailing.evaluate(labor_basis["wage_determination"], used_roles(ratebook), as_of)
        crate = prevailing.crew_rates(ev, ratebook)
    else:
        loaded = {r["role_key"]: D(r["base_wage_per_hr"]) * (1 + D(r["burden_pct"])) for r in ratebook["roles"]}
        crate = {c["crew_id"]: sum(loaded[rk] * n for rk, n in c["members"].items()) for c in ratebook["crews"]}
    cs, workday = crews.crews_by_id(ratebook), ratebook["meta"]["workday_hours"]
    difficulty = (crew_plan or {}).get("difficulty") or {"default": "standard", "overrides": {}}
    lab_lines, lab_total, crew_hours, worker_hours = [], Decimal(0), Decimal(0), Decimal(0)
    comp = {"wages": Decimal(0), "fringe": Decimal(0), "employer_costs": Decimal(0)}
    drivers = {k: qty[k]["quantity"] for k in vocab.DRIVERS}
    for t in ratebook["labor_tasks"]:
        q = D(qty[t["driver_key"]]["quantity"])
        cid = crews.assigned_crew(crew_plan, ratebook, t)
        opt = next(o for o in crews.options(ratebook, t) if o["crew_id"] == cid)
        crew = cs[cid]
        m = crews.metrics(t, opt, crew, q, crews.level_for(difficulty, t["driver_key"]), crate[cid], workday)
        hours, cost = m["_hours"], m["_cost"]
        crew_hours += hours
        worker_hours += hours * crews.headcount(crew)
        lab_total += cost
        line = {"task_id": t["task_id"], "task": t["task"], "driver_key": t["driver_key"], "uom": t["uom"], "quantity": _num(q),
                "production_rate": t["production_rate"], "crew_id": cid, "crew_description": crew["description"], "profile_version": m["profile_version"],
                "rate_basis": m["rate_basis"], "baseline_production": m["baseline_production"], "efficiency_pct": m["efficiency_pct"],
                "efficiency_applied": m["efficiency_applied"], "difficulty_level": m["difficulty_level"], "difficulty_multiplier": m["difficulty_multiplier"],
                "effective_factor": m["effective_factor"], "effective_production": m["effective_production"], "crew_hours": m["crew_hours"],
                "worker_hours": m["worker_hours"], "duration_days": m["duration_days"], "crew_rate_per_hr": _money(D(m["crew_hourly_cost"])),
                "cost_per_unit": m["cost_per_unit"], "extended": _money(cost), "source_evidence_refs": qty[t["driver_key"]]["source_evidence_refs"]}
        if m["_parts"]:
            for k, v in m["_parts"].items():
                comp[k] += v
            line.update(wages=_money(m["_parts"]["wages"]), fringe=_money(m["_parts"]["fringe"]), employer_costs=_money(m["_parts"]["employer_costs"]))
        lab_lines.append(line)
    admin_total, admin = Decimal(0), None
    if prev:
        adm = labor_basis["wage_determination"]["certified_payroll_admin"]
        admin_total = prevailing.admin_cost(adm, crew_hours)
        admin = {"basis": adm["basis"], "unit_cost": adm.get("unit_cost"), "weeks": adm.get("weeks"), "reason": adm.get("reason"),
                 "source_ref": adm["source_ref"], "extended": _money(admin_total)}
    comparison = crews.compare(ratebook, drivers, difficulty, crate, crew_plan)

    eq_lines, eq_total = [], Decimal(0)
    for e in ratebook["equipment"]:
        ext = _c(D(e["rate"]) * D(e[f"units_{col}"]) + D(e[f"fuel_{col}"]) + D(e["delivery_each"]) * D(e["delivery_trips"]))
        eq_total += ext
        eq_lines.append({"equip_id": e["equip_id"], "equipment": e["equipment"], "basis": e["basis"], "rate": e["rate"],
                         "units": e[f"units_{col}"], "extended": _money(ext)})
    mob_lines, mob_total = [], Decimal(0)
    for m in ratebook["mobilization"]:
        ext = _c(D(m["unit_cost"]) * D(m[f"qty_{col}"]))
        mob_total += ext
        mob_lines.append({"line_id": m["line_id"], "item": m["item"], "basis": m["basis"], "unit_cost": m["unit_cost"],
                          "quantity": m[f"qty_{col}"], "extended": _money(ext)})

    tax = _c(taxable_base * D(mk["tax_materials_pct"]))
    direct = mat_total + tax + svc_total + lab_total + admin_total + eq_total + mob_total
    overhead, contingency = _c(direct * D(mk["overhead_pct"])), _c(direct * D(mk["contingency_pct"]))
    subtotal = direct + overhead + contingency
    profit = _c(subtotal * D(mk["profit_pct"]))
    total = subtotal + profit
    fence_lf = D(qty["D01"]["quantity"]) + D(qty["D02"]["quantity"])

    def _cite(ex_):
        r = next((x for x in ex_.get("evidence_refs", []) if x.get("sheet_label")), None)
        return f" Cited: {r['sheet_label']} ({r['doc_id']}" + (f", page {r['page']}" if r.get("page") else "") + ")." if r else ""
    qualifications = []
    for k, it in qty.items():
        for r in it["approved_resolutions"]:
            qualifications.append({"type": "human_resolution", "item": k, **{x: r[x] for x in ("exception_id", "by", "note", "scope_version")}})
    qualifications = [dict(t) for t in {tuple(sorted(q.items())) for q in qualifications}]
    qualifications.sort(key=lambda q: (q["exception_id"], q["item"]))
    if exemption:
        qualifications.append({"type": "owner_sales_tax_exemption", "item": "materials",
                               "note": "Owner is exempt from sales/use tax on materials incorporated into the Work; owner-furnished exemption certificates are required. "
                                       "Tools, machinery, equipment and non-incorporated supplies are not exempted." + _cite(payload["revision"]["sales_tax_exemption"])})
    if prev:
        d_ = labor_basis["wage_determination"]["determination"]
        qualifications.append({"type": "prevailing_wage_basis", "item": "labor",
                               "note": f"Labor priced at the human-verified wage decision {d_['decision_id']} modification {d_['modification']}: wages, fringe and employer costs "
                                       "shown separately; certified payroll required."})
    rs = payload["revision"]["ruleset"]
    advisories = []
    if eq_lines or mob_lines:
        advisories.append(_problem("HUMAN_DURATION_INPUTS", "equipment days, trips, mileage and allowances are fixed human inputs in the rate book; "
                                   "they do not change when quantities change, so a quantity revision needs a person to re-confirm them"))
    if ratebook["unused_template_lines"]:
        advisories.append(_problem("TEMPLATE_LINES_UNUSED", f"{len(ratebook['unused_template_lines'])} blank rate-book lines were excluded, not priced as zero: "
                                   + ", ".join(f"{u['sheet']}:{u['id']}" for u in ratebook["unused_template_lines"])))
    est = {
        "scope_ref": sref,
        "materials": {"lines": mat_lines, "subtotal": _money(mat_total)},
        "sales_tax": {"rate": mk["tax_materials_pct"], "taxable_base": _money(taxable_base), "exempt_base": _money(mat_total - taxable_base),
                      "exemption_applies": exemption, "amount": _money(tax)},
        "services": {"lines": svc_lines, "subtotal": _money(svc_total)},
        "labor": {"lines": lab_lines, "subtotal": _money(lab_total), "crew_hours": float(round(crew_hours, 6)),
                  "worker_hours": float(round(worker_hours, 6)), "crew_days": float(round(crew_hours / D(workday), 6)),
                  "calendar_duration": None, "calendar_duration_basis": "NOT_MODELED: crew_days is effort (crew-hours / workday), not elapsed project time",
                  "crew_plan": None if not crew_plan else {k: crew_plan.get(k) for k in ("plan_version", "preferred_crew", "assignments", "use_default_for_unassigned",
                                                                                     "difficulty", "approved_by", "crew_profiles")},
                  "crew_comparison": comparison,
                  "basis": "prevailing_wage" if prev else "company_rates",
                  **({"components": {k: _money(v) for k, v in comp.items()}, "certified_payroll_admin": admin,
                      "determination": labor_basis["wage_determination"]["determination"]} if prev else {})},
        "equipment": {"lines": eq_lines, "subtotal": _money(eq_total)},
        "mobilization": {"lines": mob_lines, "subtotal": _money(mob_total)},
        "direct_cost": _money(direct),
        "overhead": {"rate": mk["overhead_pct"], "amount": _money(overhead)},
        "contingency": {"rate": mk["contingency_pct"], "amount": _money(contingency)},
        "subtotal_before_profit": _money(subtotal),
        "profit": {"rate": mk["profit_pct"], "amount": _money(profit)},
        "price_total": _money(total),
        "price_per_lf": _money(total / fence_lf) if fence_lf > 0 else None,
        "fence_lf": _num(fence_lf),
        "qualifications": qualifications,
        "advisories": advisories,
        "quantity_ruleset": {"ruleset_id": rs["ruleset_id"], "version": rs["version"], "sha256": rs["sha256"], "approved_by": rs.get("approved_by")},
        "quantity_revision": payload["revision"],
    }
    return est


def price_scenarios(payloads, ratebook, **kw):
    """Price every scenario ({scope_ref: payload}) and return estimate.v1. Any blocked scenario blocks the whole
    estimate, and the error carries every scope_ref's problems, so a base bid never ships while its alternate is open."""
    out, blocked = {}, []
    versions = {p["revision"]["scope_version"] for p in payloads.values() if isinstance(p.get("revision"), dict)}
    if len(versions) > 1:
        raise PricingBlocked([_problem("CONFLICTING_QUANTITY_VERSION", f"scenarios were generated from different scope versions {sorted(versions)}")])
    for sref, payload in payloads.items():
        try:
            out[sref] = price(payload, ratebook, **kw)
        except PricingBlocked as exc:
            blocked += [dict(p, scope_ref=sref) for p in exc.problems]
    if blocked:
        raise PricingBlocked(blocked)
    if not out:
        raise PricingBlocked([_problem("NO_SCENARIO", "there is no scenario to price (the selected bid names none)")])
    est = {"schema_version": "estimate.v1", "ratebook_ref": ratebook_ref(ratebook), "scenarios": out,
           "headline_scope_ref": vocab.BASE if vocab.BASE in out else sorted(out)[0]}
    est["digest"] = hashlib.sha256(canonical(est).encode()).hexdigest()
    return est

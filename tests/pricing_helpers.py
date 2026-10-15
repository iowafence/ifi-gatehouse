"""Shared helpers for pricing tests: build a quantity payload from a {key: quantity} dict and import a stdlib-built rate book."""
import copy
import datetime

from pricing import ratebook as rb
from pricing import vocab
from tests import xlsx_builder as xb

AS_OF = datetime.date(2026, 10, 13)
RULESET = {"ruleset_id": "TEST-RULES", "version": "1.0.0", "sha256": "a" * 64, "approved": True, "approved_by": "Test Estimator"}


def book(mutate=None, profiles=False):
    """profiles=True adds three comparison crews (Crew 1/2/3 = 104% / 94% / 88%) and per-crew production options; otherwise crews are neutral."""
    spec = copy.deepcopy(xb.valid_spec(crew_profiles=profiles))
    if mutate:
        mutate(spec)
    return rb.import_workbook(xb.build(spec), as_of=AS_OF)["ratebook"]


def payload(quantities=None, *, scope_ref="BASE", ruleset=None, status=None, defaults=0):
    """Every M/D key present. Keys not listed get `defaults` (a confirmed, explicit quantity)."""
    q = quantities or {}
    items = []
    for key in list(vocab.MATERIALS) + list(vocab.SERVICES) + list(vocab.DRIVERS):
        row = {"item_id": key} if key in vocab.MATERIALS or key in vocab.SERVICES else {"driver_key": key}
        row.update({"scope_ref": scope_ref, "quantity": q.get(key, defaults), "uom": vocab.uom(key), "source_evidence_refs": [],
                    "calculation_method": "test quantity", "status": (status or {}).get(key, "confirmed"), "approved_resolutions": []})
        items.append(row)
    return {"schema_version": "quantity_payload.v1", "project_ref": "TEST",
            "revision": {"scope_version": 1, "scope_sha256": "b" * 64, "ruleset": dict(ruleset or RULESET)}, "items": items}


def labor_ok(ratebook):
    return {"status": "decided", "decision": "verified_standard", "ratebook_labor_sha256": ratebook["hashes"]["labor_sha256"], "decided_by": "Test Reviewer"}


def item(p, key):
    return next(i for i in p["items"] if (i.get("item_id") or i.get("driver_key")) == key)


def eng_plan(book, preferred=None, assignments=None, use_default=True, default="standard", overrides=None, source="human", evidence=None):
    """An approved crew plan as the engine consumes it."""
    return {"plan_version": 1, "preferred_crew": preferred, "assignments": dict(assignments or {}), "use_default_for_unassigned": use_default,
            "difficulty": {"default": default, "overrides": dict(overrides or {}), "source": source, "evidence_refs": list(evidence or [])},
            "approved_by": "Pat Estimator", "ratebook_labor_sha256": book["hashes"]["labor_sha256"],
            "crew_profiles": {c["crew_id"]: c["profile_version"] for c in book["crews"]}}

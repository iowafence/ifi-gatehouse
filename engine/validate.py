"""Structural guardrails on model output BEFORE it reaches the engine. The model may not emit money."""
from .util import walk_facts

VALID_STATUS = {"confirmed", "inferred", "unresolved", "human_resolved"}
MONEY_WORDS = ("price", "cost", "rate", "total", "cogs", "margin", "markup", "$")
REQUIRED_TOP = ("fence_runs", "gates", "bid_structure")


def _keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from _keys(v)


def validate_scope(scope):
    """Return a list of problems (empty list = acceptable)."""
    p = []
    if not isinstance(scope, dict):
        return ["scope is not an object"]
    for k in REQUIRED_TOP:
        if k not in scope:
            p.append(f"missing top-level key: {k}")
    for path, f in walk_facts(scope):
        st = f.get("status")
        if st not in VALID_STATUS:
            p.append(f"{path}: invalid status {st!r}")
        if st == "unresolved" and f.get("value") is not None:
            p.append(f"{path}: unresolved fact must have value null (model guessed)")
        if st == "inferred" and not f.get("inference_note"):
            p.append(f"{path}: inferred fact needs an inference_note")
        if st == "confirmed" and f.get("value") is None:
            p.append(f"{path}: confirmed fact has null value")
        if st == "confirmed" and not f.get("evidence"):
            p.append(f"{path}: confirmed fact has no evidence")
    for k in _keys(scope):
        kl = str(k).lower()
        if kl in ("price_affecting",):
            continue
        if any(w in kl for w in MONEY_WORDS):
            p.append(f"model emitted a money-like key: {k!r}")
    for r in scope.get("fence_runs", []):
        for req in ("run_id", "fence_type", "height_ft", "length_lf"):
            if req not in r:
                p.append(f"fence run {r.get('run_id','?')} missing {req}")
    return p

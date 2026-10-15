"""Deterministic pricing: rate-book import, quantity-to-pricing payloads, and the authoritative cost engine.

Stdlib only. Nothing in this package calls a model, and nothing in `tools/` or `evolus/` may import it
(tests enforce that), so rate-book content cannot reach an extraction model by construction.
"""
SCHEMA_VERSIONS = {
    "ratebook": "ratebook.v1",
    "quantity_payload": "quantity_payload.v1",
    "evidence": "evidence.v1",
    "estimate": "estimate.v1",
}

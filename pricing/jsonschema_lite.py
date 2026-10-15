"""Small JSON Schema subset validator (stdlib only) so the schema files in pricing/schemas are the single
source of truth for what a payload may contain. Supported: type, enum, const, required, properties,
additionalProperties, propertyNames, items, minItems, maxItems, minLength, maxLength, pattern, minimum,
maximum, exclusiveMinimum, exclusiveMaximum, oneOf, anyOf, allOf, not, $ref (local '#/$defs/...').
Unknown keywords raise: a schema that silently stops checking is worse than none."""
import json
import math
import pathlib
import re

SCHEMA_DIR = pathlib.Path(__file__).resolve().parent / "schemas"
_KNOWN = {"$schema", "$id", "$defs", "$ref", "title", "description", "type", "enum", "const", "required",
          "properties", "additionalProperties", "propertyNames", "items", "minItems", "maxItems", "minLength",
          "maxLength", "pattern", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "oneOf",
          "anyOf", "allOf", "not", "uniqueItems", "minProperties", "examples", "default"}
_cache = {}


class SchemaError(Exception):
    pass


def load(name):
    if name not in _cache:
        _cache[name] = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text())
    return _cache[name]


def _is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _type_ok(inst, t):
    if t == "object":
        return isinstance(inst, dict)
    if t == "array":
        return isinstance(inst, list)
    if t == "string":
        return isinstance(inst, str)
    if t == "boolean":
        return isinstance(inst, bool)
    if t == "null":
        return inst is None
    if t == "number":
        return _is_number(inst)
    if t == "integer":
        return isinstance(inst, int) and not isinstance(inst, bool) or (isinstance(inst, float) and math.isfinite(inst) and inst == int(inst))
    raise SchemaError(f"unsupported type {t}")


def _resolve(ref, root):
    if not ref.startswith("#/"):
        raise SchemaError(f"only local $ref supported: {ref}")
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _walk(inst, schema, root, path, out):
    unknown = set(schema) - _KNOWN
    if unknown:
        raise SchemaError(f"unsupported schema keywords at {path or '/'}: {sorted(unknown)}")
    if "$ref" in schema:
        return _walk(inst, _resolve(schema["$ref"], root), root, path, out)
    here = path or "/"
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(inst, t) for t in types):
            out.append((here, f"expected {'|'.join(types)}, got {type(inst).__name__}"))
            return
    if "const" in schema and inst != schema["const"]:
        out.append((here, f"must equal {schema['const']!r}"))
    if "enum" in schema and inst not in schema["enum"]:
        out.append((here, f"must be one of {schema['enum']}"))
    if isinstance(inst, str):
        if "minLength" in schema and len(inst) < schema["minLength"]:
            out.append((here, f"shorter than {schema['minLength']}"))
        if "maxLength" in schema and len(inst) > schema["maxLength"]:
            out.append((here, f"longer than {schema['maxLength']}"))
        if "pattern" in schema and not re.search(schema["pattern"], inst):
            out.append((here, f"does not match {schema['pattern']}"))
    if _is_number(inst):
        for kw, bad in (("minimum", lambda v, b: v < b), ("maximum", lambda v, b: v > b),
                        ("exclusiveMinimum", lambda v, b: v <= b), ("exclusiveMaximum", lambda v, b: v >= b)):
            if kw in schema and bad(inst, schema[kw]):
                out.append((here, f"violates {kw} {schema[kw]}"))
    if isinstance(inst, list):
        if "minItems" in schema and len(inst) < schema["minItems"]:
            out.append((here, f"fewer than {schema['minItems']} items"))
        if "maxItems" in schema and len(inst) > schema["maxItems"]:
            out.append((here, f"more than {schema['maxItems']} items"))
        if schema.get("uniqueItems") and len({json.dumps(i, sort_keys=True) for i in inst}) != len(inst):
            out.append((here, "items must be unique"))
        if "items" in schema:
            for i, v in enumerate(inst):
                _walk(v, schema["items"], root, f"{path}/{i}", out)
    if isinstance(inst, dict):
        if "minProperties" in schema and len(inst) < schema["minProperties"]:
            out.append((here, f"fewer than {schema['minProperties']} properties"))
        for k in schema.get("required", []):
            if k not in inst:
                out.append((here, f"missing required property {k!r}"))
        props = schema.get("properties", {})
        for k, v in inst.items():
            if "propertyNames" in schema:
                sub = []
                _walk(k, schema["propertyNames"], root, f"{path}/{k}", sub)
                if sub:
                    out.append((f"{path}/{k}", f"property name {k!r} not allowed"))
            if k in props:
                _walk(v, props[k], root, f"{path}/{k}", out)
            elif schema.get("additionalProperties") is False:
                out.append((f"{path}/{k}", "unexpected property"))
            elif isinstance(schema.get("additionalProperties"), dict):
                _walk(v, schema["additionalProperties"], root, f"{path}/{k}", out)
    for kw in ("oneOf", "anyOf"):
        if kw in schema:
            hits = 0
            for s in schema[kw]:
                sub = []
                _walk(inst, s, root, path, sub)
                hits += not sub
            if (kw == "oneOf" and hits != 1) or (kw == "anyOf" and hits < 1):
                out.append((here, f"must match {'exactly one' if kw == 'oneOf' else 'at least one'} of the {kw} alternatives (matched {hits})"))
    for s in schema.get("allOf", []):
        _walk(inst, s, root, path, out)
    if "not" in schema:
        sub = []
        _walk(inst, schema["not"], root, path, sub)
        if not sub:
            out.append((here, "matches a forbidden shape"))


def problems(instance, name):
    """List of (json_pointer, message); empty means valid."""
    schema = load(name)
    out = []
    _walk(instance, schema, schema, "", out)
    return out

import copy


def val(f, default=None):
    """Value of a fact object ({'value':..,'status':..}) or a raw value."""
    if isinstance(f, dict) and "value" in f:
        v = f["value"]
        return default if v is None else v
    return default if f is None else f


def walk_facts(node, path=""):
    """Yield (json_pointer, fact) for every fact object in the scope tree."""
    if isinstance(node, dict):
        if "value" in node and "status" in node:
            yield path, node
            return
        for k, v in node.items():
            if k in ("patch", "evidence"):
                continue
            yield from walk_facts(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk_facts(v, f"{path}/{i}")


def _parent(doc, path):
    parts = [p for p in path.split("/") if p != ""]
    cur = doc
    for p in parts[:-1]:
        cur = cur[int(p)] if isinstance(cur, list) else cur[p]
    return cur, parts[-1]


def get_ptr(doc, path):
    parent, last = _parent(doc, path)
    return parent[int(last)] if isinstance(parent, list) else parent[last]


def apply_patch(doc, patch):
    """Minimal RFC 6902 subset (add/replace/remove). Returns a new document."""
    doc = copy.deepcopy(doc)
    for op in patch:
        parent, last = _parent(doc, op["path"])
        if isinstance(parent, list):
            if op["op"] == "add" and last == "-":
                parent.append(copy.deepcopy(op["value"]))
                continue
            key = int(last)
        else:
            key = last
        if op["op"] in ("add", "replace"):
            parent[key] = copy.deepcopy(op["value"])
        elif op["op"] == "remove":
            del parent[key]
        else:
            raise ValueError(f"unsupported op {op['op']}")
    return doc

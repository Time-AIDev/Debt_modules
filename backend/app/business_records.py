"""Versioned JSON records for shared business state; never deserialize pickle.

The existing domain objects remain an adapter. Each mapping entry is a separate
record, rather than one per-user serialized copy of the entire domain state.
"""
import importlib
import json
from collections import OrderedDict
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import text

ALLOWED_TYPES = {
    "app.config.Settings", "app.config.PendingRule", "app.config.DecidedRule",
    "app.criteria.Criteria",
    "app.dictionaries.Dictionaries", "app.cases.CaseState", "app.journey.JourneyState",
    "app.collections.contact.ContactLog", "app.collections.contact.Lock",
    "app.collections.contact.ContactAttempt", "app.collections.contact.Disposition",
    "app.imports.ImportState", "app.peak_documents.DocumentState",
    "app.invoice_pipeline.PipelineState", "app.workbook_exports.ExportLog",
    "app.money.band_sets.Band",
    "app.money.models.Instalment",
}


def encode(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return {"t": "decimal", "v": str(value)}
    if isinstance(value, datetime):
        return {"t": "datetime", "v": value.isoformat()}
    if isinstance(value, date):
        return {"t": "date", "v": value.isoformat()}
    if isinstance(value, (dict, OrderedDict)):
        return {"t": "ordered" if isinstance(value, OrderedDict) else "dict",
                "v": [[encode(k), encode(v)] for k, v in value.items()]}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [encode(v) for v in value]
        if isinstance(value, (set, frozenset)):
            items.sort(key=lambda v: json.dumps(v, sort_keys=True))
        return {"t": type(value).__name__, "v": items}
    name = type(value).__module__ + "." + type(value).__name__
    if name not in ALLOWED_TYPES:
        raise ValueError("unsupported business record type")
    return {"t": name, "v": encode(vars(value))}


def decode(value):
    if not isinstance(value, dict):
        return value
    kind, raw = value["t"], value["v"]
    if kind == "decimal": return Decimal(raw)
    if kind == "datetime": return datetime.fromisoformat(raw)
    if kind == "date": return date.fromisoformat(raw)
    if kind in ("dict", "ordered"):
        return (OrderedDict if kind == "ordered" else dict)((decode(k), decode(v)) for k, v in raw)
    if kind in ("list", "tuple", "set", "frozenset"):
        return {"list": list, "tuple": tuple, "set": set, "frozenset": frozenset}[kind](decode(v) for v in raw)
    if kind not in ALLOWED_TYPES:
        raise ValueError("unsupported business record schema")
    module, name = kind.rsplit(".", 1)
    cls = getattr(importlib.import_module(module), name)
    instance = cls.__new__(cls)
    for key, item in decode(raw).items():
        object.__setattr__(instance, key, item)
    return instance


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def records(value):
    """Separate collection entries and scalar attributes into keyed rows."""
    tree = encode(value)
    rows = {}

    def split(node, path):
        if isinstance(node, dict) and node.get("t") in ("dict", "ordered"):
            pairs = []
            for key, child in node["v"]:
                child_path = path + "/" + canonical(key)
                rows[child_path] = child
                pairs.append([key, {"record": child_path}])
            return dict(node, v=pairs)
        return node

    if isinstance(tree, dict) and tree.get("t") in ALLOWED_TYPES:
        attrs = tree["v"]
        pairs = []
        for name, child in attrs["v"]:
            path = str(name)
            rows[path] = split(child, path)
            pairs.append([name, {"record": path}])
        tree = dict(tree, v=dict(attrs, v=pairs))
    else:
        tree = split(tree, "root")
    rows["@root"] = tree
    return rows


def load(conn, key):
    found = conn.execute(text("select record_key, payload, schema_version from app.business_record "
                              "where store_key=:k"), {"k": key}).fetchall()
    if not found:
        return None, False
    if any(r.schema_version != 1 for r in found):
        raise ValueError("unsupported business record schema")
    rows = {r.record_key: r.payload for r in found}

    def expand(node):
        if isinstance(node, dict):
            if set(node) == {"record"}:
                return expand(rows[node["record"]])
            return {k: expand(v) for k, v in node.items()}
        if isinstance(node, list): return [expand(v) for v in node]
        return node
    return decode(expand(rows["@root"])), True


def save(conn, key, value):
    current = records(value)
    previous = {r.record_key: canonical(r.payload) for r in conn.execute(text(
        "select record_key, payload from app.business_record where store_key=:k"), {"k": key})}
    changed = False
    for record_key, payload in current.items():
        raw = canonical(payload)
        if previous.get(record_key) == raw:
            continue
        changed = True
        conn.execute(text("insert into app.business_record (store_key, record_key, payload) "
                          "values (:s, :r, cast(:p as jsonb)) on conflict (store_key, record_key) "
                          "do update set payload=excluded.payload, version=app.business_record.version+1, updated_at=now()"),
                     {"s": key, "r": record_key, "p": raw})
    for removed in previous.keys() - current.keys():
        changed = True
        conn.execute(text("delete from app.business_record where store_key=:s and record_key=:r"),
                     {"s": key, "r": removed})
    return changed

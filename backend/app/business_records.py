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

PARTITIONED_STORES = frozenset({"cases.state", "journey.state"})


class ScopedList(list):
    """A customer-owned sequence with database identities for dirty row writes."""
    def __init__(self, values=(), identities=()):
        super().__init__(values)
        self.identities = list(identities)
        # Positions change when a domain filters, pops, inserts or sorts a list.
        # Keep references to the loaded objects so their database identity follows
        # the retained row instead of silently overwriting its former neighbour.
        self.saved_records = list(zip(self, self.identities))


def _sequence_identities(values, existing, saved_records):
    objects = {}
    for value, identity in saved_records:
        objects.setdefault(id(value), []).append((value, identity))
    by_raw, by_uid = {}, {}
    for row in existing:
        by_raw.setdefault(canonical(row.payload), []).append(row.id)
        value = decode(row.payload)
        if isinstance(value, dict) and value.get("uid") is not None:
            by_uid.setdefault(canonical(value["uid"]), []).append(row.id)
    available = {row.id for row in existing}
    # Reserve retained objects before matching rebuilt copies. A new observation
    # inserted before an identical retained row must not steal its durable ID.
    reserved = {identity for value in values for saved, identity in objects.get(id(value), ())
                if saved is value and identity in available}
    used = set()
    identities = []
    for value in values:
        identity = next((identity for saved, identity in objects.get(id(value), ())
                         if saved is value and identity in available and identity not in used), None)
        reconstructed = not isinstance(values, ScopedList)
        if reconstructed and identity is None and isinstance(value, dict) and value.get("uid") is not None:
            candidates = [candidate for candidate in by_uid.get(canonical(value["uid"]), ())
                          if candidate not in used and candidate not in reserved]
            if len(candidates) == 1:
                identity = candidates[0]
        if reconstructed and identity is None:
            identity = next((candidate for candidate in by_raw.get(canonical(encode(value)), ())
                             if candidate not in used and candidate not in reserved), None)
        identities.append(identity)
        if identity is not None:
            used.add(identity)
    return identities


def _unit():
    from .production_unit import CURRENT
    return CURRENT.get() or {}


def next_domain_id(prefix, fallback_counter=None):
    """Complete prefixed UID in a durable unit; None for prototype/test factories.

    Seed factories must keep their deterministic legacy IDs. Only an explicit
    mutation allocates from the sequence; transaction rollback can leave a gap.
    """
    unit = _unit()
    if not unit.get("capacity") or not unit.get("mutation") or unit.get("seeding"):
        return None
    value = unit["conn"].execute(text("select nextval('app.domain_identifier_seq')")).scalar_one()
    return "%s-%010d" % (prefix, value)


def _owners(value):
    """Resolve ownership from committed domain identifiers, never user claims."""
    from . import main
    by_uid = {}
    mappings = value.values() if isinstance(value, dict) else vars(value).values() if hasattr(value, "__dict__") else ()
    children = []
    for collection in mappings:
        children.extend(collection.values() if isinstance(collection, dict) else collection if isinstance(collection, list) else ())
    def owner(row, key=None):
        if not isinstance(row, dict):
            return key if key in main.BY_CUSTOMER else None
        uid = row.get("customer_uid")
        if uid:
            return str(uid)
        contract = main.BY_CONTRACT.get(row.get("contract_uid"))
        if contract:
            return contract[0].uid
        for reference in ("case_uid", "recovery_uid", "invoice_uid", "ptp_uid"):
            if row.get(reference) in by_uid:
                return by_uid[row[reference]]
        return key if key in main.BY_CUSTOMER else None
    for _ in range(3):
        for row in children:
            if isinstance(row, dict) and row.get("uid"):
                found = owner(row)
                if found:
                    by_uid[row["uid"]] = found
    return owner

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
        return {"t": "list" if isinstance(value, list) else type(value).__name__, "v": items}
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
    if _unit().get("capacity") and key in PARTITIONED_STORES:
        return _load_partitioned(conn, key)
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
    if _unit().get("capacity") and key in PARTITIONED_STORES:
        return _save_partitioned(conn, key, value)
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


def _load_partitioned(conn, key):
    unit = _unit()
    owner = unit.get("customer_uid")
    predicate = " and (customer_uid=:u or customer_uid is null)" if owner else ""
    found = conn.execute(text("select record_key,payload,schema_version,customer_uid from app.business_record "
                              "where store_key=:k" + predicate), {"k": key, "u": owner}).fetchall()
    if not found:
        return None, False
    if any(r.schema_version != 1 for r in found):
        raise ValueError("unsupported business record schema")
    rows = {r.record_key: r.payload for r in found}
    sequences = {}
    def expand(node):
        if isinstance(node, dict):
            if set(node) == {"record"}:
                return expand(rows[node["record"]])
            if node.get("t") == "mapping_records":
                attribute = node["v"]["attribute"]
                prefix = attribute + "/"
                return {"t": node["v"]["kind"], "v": [
                    [json.loads(path[len(prefix):]), expand(payload)]
                    for path, payload in rows.items() if path.startswith(prefix)]}
            if node.get("t") == "list_records":
                attribute = node["v"]
                entries = conn.execute(text(
                    "select id,payload from app.business_list_record where store_key=:k and attribute=:a" +
                    (" and (customer_uid=:u or customer_uid is null)" if owner else "") + " order by id"),
                    {"k": key, "a": attribute, "u": owner}).fetchall()
                sequences[attribute] = [row.id for row in entries]
                return {"t": "list", "v": [row.payload for row in entries]}
            return {k: expand(v) for k, v in node.items()}
        if isinstance(node, list):
            return [expand(v) for v in node]
        return node
    value = decode(expand(rows["@root"]))
    for attribute, identities in sequences.items():
        target = value if isinstance(value, dict) else vars(value)
        target[attribute] = ScopedList(target[attribute], identities)
        unit.setdefault("sequence_baselines", {}).setdefault(key, {})[attribute] = target[attribute].saved_records
    unit.setdefault("record_baselines", {})[key] = {k: canonical(v) for k, v in rows.items()}
    unit.setdefault("owner_baselines", {})[key] = {row.record_key: getattr(row, "customer_uid", None) for row in found}
    return value, True


def _save_partitioned(conn, key, value):
    unit = _unit()
    scoped = unit.get("customer_uid")
    owners = _owners(value)
    current = records(value)
    attributes = value if isinstance(value, dict) else vars(value) if hasattr(value, "__dict__") else {}
    list_values = {}
    for attribute, child in attributes.items():
        if isinstance(child, dict):
            current[attribute] = {"t": "mapping_records", "v": {
                "attribute": attribute, "kind": "ordered" if isinstance(child, OrderedDict) else "dict"}}
        elif isinstance(child, list):
            list_values[attribute] = child
            current[attribute] = {"t": "list_records", "v": attribute}
    previous = unit.get("record_baselines", {}).get(key)
    if previous is None:
        previous_rows = conn.execute(text("select record_key,payload,customer_uid from app.business_record where store_key=:k" +
            (" and (customer_uid=:u or customer_uid is null)" if scoped else "")), {"k": key, "u": scoped}).all()
        previous = {row.record_key: canonical(row.payload) for row in previous_rows}
        previous_owners = {row.record_key: row.customer_uid for row in previous_rows}
    else:
        previous_owners = unit.get("owner_baselines", {}).get(key, {})
    next_baselines, next_owners = dict(previous), dict(previous_owners)
    changed = False
    upserts = []
    for path, payload in current.items():
        # A scoped unit owns child entries only. Global manifests/counters cannot
        # be replaced with the customer's partial graph.
        if scoped and (path == "@root" or path in attributes):
            continue
        raw = canonical(payload)
        attr, _, encoded_key = path.partition("/")
        child = attributes.get(attr)
        entry_key = decode(json.loads(encoded_key)) if encoded_key else None
        row_value = child.get(entry_key) if isinstance(child, dict) else None
        customer_uid = owners(row_value, entry_key) if encoded_key else None
        if previous.get(path) == raw and previous_owners.get(path) == (customer_uid or scoped):
            continue
        if scoped and customer_uid not in (None, scoped):
            raise ValueError("record is outside the customer transaction")
        upserts.append({"s": key, "r": path, "p": raw, "u": customer_uid or scoped})
        next_baselines[path] = raw
        next_owners[path] = customer_uid or scoped
        changed = True
    if upserts:
        statement = text("insert into app.business_record(store_key,record_key,payload,customer_uid) "
            "values(:s,:r,cast(:p as jsonb),:u) on conflict(store_key,record_key) do update set "
            "payload=excluded.payload,customer_uid=excluded.customer_uid,"
            "version=app.business_record.version+1,updated_at=now()")
        for start in range(0, len(upserts), 500):
            conn.execute(statement, upserts[start:start + 500])
    for removed in previous.keys() - current.keys():
        if scoped and "/" not in removed:
            continue
        conn.execute(text("delete from app.business_record where store_key=:s and record_key=:r" +
                          (" and customer_uid=:u" if scoped else "")), {"s": key, "r": removed, "u": scoped})
        next_baselines.pop(removed, None)
        next_owners.pop(removed, None)
        changed = True
    saved_sequences = {}
    for attribute, values in list_values.items():
        existing = conn.execute(text(
            "select id,payload from app.business_list_record where store_key=:k and attribute=:a" +
            (" and (customer_uid=:u or customer_uid is null)" if scoped else "") + " order by id"),
            {"k": key, "a": attribute, "u": scoped}).fetchall()
        saved_records = values.saved_records if isinstance(values, ScopedList) else unit.get("sequence_baselines", {}).get(key, {}).get(attribute, ())
        ids = _sequence_identities(values, existing, saved_records)
        old = {row.id: canonical(row.payload) for row in existing}
        for index, row_value in enumerate(values):
            raw = canonical(encode(row_value))
            row_id = ids[index] if index < len(ids) else None
            if row_id is not None and old.get(row_id) == raw:
                continue
            customer_uid = owners(row_value) or scoped
            if scoped and customer_uid not in (None, scoped):
                raise ValueError("sequence is outside the customer transaction")
            if row_id is None:
                ids[index] = conn.execute(text("insert into app.business_list_record(store_key,attribute,customer_uid,payload) "
                                  "values(:k,:a,:u,cast(:p as jsonb)) returning id"),
                             {"k": key, "a": attribute, "u": customer_uid, "p": raw}).scalar_one()
            else:
                conn.execute(text("update app.business_list_record set payload=cast(:p as jsonb),version=version+1 "
                                  "where id=:i"), {"p": raw, "i": row_id})
            changed = True
        removed = set(old) - set(ids)
        if removed:
            conn.execute(text("delete from app.business_list_record where id=any(:ids)"), {"ids": list(removed)})
            changed = True
        saved_sequences[attribute] = (values, ids)
    # Publish in-memory bookkeeping only after every mapping/list statement
    # succeeds. A failed save can retry against the unchanged source identities.
    unit.setdefault("record_baselines", {})[key] = next_baselines
    unit.setdefault("owner_baselines", {})[key] = next_owners
    sequences = unit.setdefault("sequence_baselines", {}).setdefault(key, {})
    for attribute, (values, ids) in saved_sequences.items():
        sequence_records = list(zip(values, ids))
        sequences[attribute] = sequence_records
        if isinstance(values, ScopedList):
            values.identities = list(ids)
            values.saved_records = sequence_records
    return changed

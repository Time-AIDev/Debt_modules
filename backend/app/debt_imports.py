"""Reviewed, matched-only debt evidence and contractual supplements.

These profiles never install/retire the SHEET book. Source statuses are evidence,
not cash; contractual supplements contain no inferred paid-through balances.
"""
import copy
import hashlib
import json
import re
import threading
import uuid
from contextlib import contextmanager, nullcontext
from datetime import date
from decimal import Decimal

from sqlalchemy import text

from . import clock, db, errors, imports, request_context
from .config import settings

PROFILES = ("debt_status", "contract_supplement")
TABS = ("Done - Collection", "Done - Cash", "Repossessed 1")
LOCK = 0x44454254494D50
_MEMORY = {"previews": {}, "supplements": {}, "observations": [], "installations": {}}
_LOCK = threading.RLock()

# Integration owner includes this additive SQL in the canonical migration.
SCHEMA = """
create table if not exists records.debt_import_preview (
 uid text primary key, actor text not null, profile text not null,
 payload jsonb not null, created_at timestamptz not null default now()
);
create table if not exists records.contract_supplement (
 contract_uid text primary key, customer_uid text not null, payload jsonb not null,
 updated_at timestamptz not null default now()
);
create index if not exists contract_supplement_customer on records.contract_supplement(customer_uid);
create table if not exists records.debt_status_observation (
 sequence bigserial primary key, customer_uid text not null, preview_uid text not null,
 entry_key text not null, payload jsonb not null, created_at timestamptz not null default now(),
 unique(preview_uid,entry_key)
);
create index if not exists debt_status_customer on records.debt_status_observation(customer_uid,sequence desc);
create table if not exists records.installation_confirmation (
 contract_uid text primary key, customer_uid text not null, payload jsonb not null,
 updated_at timestamptz not null default now()
);
"""


def problem(code, message, status=422):
    return errors.Problem("debt_import_" + code, status, "Debt import refused", message,
                          message, "DEBT-IMP-%04d" % status)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    default=str).encode()).hexdigest()


def stem(value):
    return str(value or "").strip().split("_", 1)[0].upper()


def current_customers():
    from . import journey
    return list(journey.book_customers()) + list(journey.identity_customers())


def _customer_index(customers):
    result = {}
    for customer in customers:
        for value in (getattr(customer, "volt_id", None), customer.customer_no):
            if stem(value):
                holders = result.setdefault(stem(value), {})
                holders[customer.uid] = customer
    return result


def _date(value):
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (ValueError, TypeError):
        return None


def _source_date(value, day_first=False):
    parsed = imports._IMS.parse_date(str(value or ""), day_first=day_first)
    return _date(parsed)


def _amount(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except Exception:
        return None


def _profile_rows(raw):
    sheets = imports.read_xlsx(raw, selected_sheets=TABS)
    out = []
    seen_tabs = {sheet["name"].strip().lower() for sheet in sheets}
    if not {"done - collection", "done - cash"} <= seen_tabs:
        raise problem("tabs_missing", "ต้องมีแท็บ Done - Collection และ Done - Cash")
    for sheet in sheets:
        name, rows, nums = sheet["name"], sheet["rows"], sheet["row_numbers"]
        if name.strip().lower() == "repossessed 1":
            index = next((i for i, row in enumerate(rows[:30])
                          if "Customer ID" in row and "Status" in row), None)
            if index is None:
                raise problem("repossession_header", "Repossessed 1 ต้องมี Customer ID และ Status")
            header = rows[index]
            for i, row in enumerate(rows[index + 1:], index + 1):
                get = lambda key: imports._IMS.col(row, header, key)
                if not get("Customer ID"):
                    continue
                out.append({"source_ref": {"sheet": name, "row": nums[i]},
                            "volt_id": get("Customer ID"), "kind": "REPOSSESSION",
                            "source_status": get("Status"),
                            "repossession_on": _source_date(get("Repossed Date"), day_first=True)})
            continue
        kind, _hi, _header, records, _refusals, _extra = imports._classify_sheet(
            [], rows, name, [], nums)
        expected = "LEASING_BOOK" if name.strip().lower() == "done - collection" else "CASH_TAB"
        if kind != expected:
            raise problem("done_tab_unread", "อ่านหัวตารางแท็บ %s ไม่ได้" % name)
        # Keep the real source installation field, omitted by the legacy lease reader.
        hi = next(i for i, row in enumerate(rows[:30]) if "VOLT ID" in row)
        header = rows[hi]
        by_row = {nums[i]: row for i, row in enumerate(rows)}
        for rec in records:
            row = by_row[rec["source_ref"]["row"]]
            raw_install = imports._IMS.col(row, header, "Installation Month")
            is_month = bool(re.fullmatch(r"\d{2}/\d{2}", str(raw_install or "")))
            rec.update(kind=kind, source_status=rec.get("payment_status") or rec.get("status_word"),
                       installation_source={"date": _source_date(raw_install, expected == "CASH_TAB"),
                                            "precision": "MONTH" if is_month else "DAY" if raw_install else "UNKNOWN"})
            if expected == "CASH_TAB":
                rec["monthly_cells"] = []
                for column, heading in enumerate(header):
                    if not re.fullmatch(r"M\d+", str(heading)):
                        continue
                    status_heading = imports._IMS.cell(header, column + 1)
                    status = imports._IMS.cell(row, column + 1) if status_heading in (
                        "Status", "Status " + heading) else None
                    amount = imports._IMS.money(imports._IMS.cell(row, column))
                    rec["monthly_cells"].append({"month": heading, "amount": amount,
                        "status": status or None, "amount_field": heading, "status_field": status_heading,
                        "unknown": not bool(status), "missing_cached": amount is None})
            out.append(rec)
    return out


def build_entries(records, customers):
    """Pure identity/quality decisions. Ambiguity is reviewable, never last-wins."""
    index = _customer_index(customers)
    groups, result = {}, []
    for record in records:
        groups.setdefault((record["kind"], stem(record.get("volt_id"))), []).append(record)
    for (kind, _identity), rows in groups.items():
        # An exact duplicate excludes row provenance from its comparison only.
        unique = {}
        for row in rows:
            unique.setdefault(digest({k: v for k, v in row.items() if k != "source_ref"}), row)
        conflict = len(unique) > 1
        for record in unique.values():
            holders = list(index.get(stem(record.get("volt_id")), {}).values())
            customer = holders[0] if len(holders) == 1 else None
            reasons = []
            if not customer:
                reasons.append("IDENTITY_AMBIGUOUS" if holders else "OUTSIDE_CURRENT_COHORT")
            if conflict:
                reasons.append("CONFLICTING_DUPLICATE")
            product = "LEASE" if kind == "LEASING_BOOK" else "CASH" if kind == "CASH_TAB" else None
            if customer and product and getattr(customer, "product", product) != product:
                reasons.append("PRODUCT_CONFLICT")
            target = list(getattr(customer, "contracts", ()) or ()) if customer else []
            matching = [contract for contract in target if contract.product == product] if product else target
            contract_uid = matching[0].uid if len(matching) == 1 else (
                "K-%s-%s" % (customer.customer_no, "L" if product == "LEASE" else "C")
                if customer and product and not target else None)
            if customer and product and not contract_uid:
                reasons.append("CONTRACT_AMBIGUOUS")
            status = record.get("source_status")
            todo = record.get("contract_cancelled") == "Terminate Contract"
            if todo:
                reasons.append("TERMINATION_TODO")
            source = record.get("installation_source") or {}
            completed = (kind == "REPOSSESSION" and status in ("In Queue", "Re-Sold")
                         and bool(record.get("repossession_on")))
            unknown = []
            if kind == "LEASING_BOOK":
                for field in ("pmt_inc_vat", "term_original", "first_payment_date"):
                    if record.get(field) in (None, ""):
                        unknown.append(field)
            elif kind == "CASH_TAB":
                for field in ("price", "dp_inc_vat", "first_payment_date"):
                    if record.get(field) in (None, ""):
                        unknown.append(field)
            result.append({"key": digest(record), "customer_uid": customer.uid if customer else None,
                           "customer_no": str(customer.customer_no) if customer else None,
                           "contract_uid": contract_uid, "product": product,
                           "source_ref": record["source_ref"], "source_status": status,
                           "mapped_status": {"Current": "CURRENT", "Late": "LATE", "NPL": "NPL",
                               "Closed": "CLOSED", "Terminated": "TERMINATED", "Link sent": "LATE",
                               "Not Due": "CURRENT", "Not issued": "CURRENT"}.get(status),
                           "eligible": customer is not None and not reasons,
                           "review_reasons": reasons,
                           "quality": {"unknown_money_fields": unknown, "missing_cached_fields": unknown},
                           "installation": {"state": "UNCONFIRMED", "source_date": source.get("date"),
                               "precision": source.get("precision"), "requires_confirmation": True},
                           "termination_candidate": {"completed_evidence": completed, "cause": None,
                               "reason": None, "contract_uids": [contract.uid for contract in target],
                               "requires_scope_confirmation": True} if kind == "REPOSSESSION" else None,
                           "monthly_cells": record.get("monthly_cells") or [],
                           "record": record})
    return result


def _epoch():
    from . import data_epoch
    return data_epoch.current() if db.configured() else 0


@contextmanager
def transaction():
    if not db.configured():
        with _LOCK:
            previous = copy.deepcopy(_MEMORY)
            try:
                yield None
            except BaseException:
                _MEMORY.clear()
                _MEMORY.update(previous)
                raise
        return
    conn = db.connect()
    try:
        with conn.begin() if not conn.in_transaction() else nullcontext():
            conn.execute(text("select pg_advisory_xact_lock(:key)"), {"key": LOCK})
            yield conn
    finally:
        conn.close()


def _save_preview(conn, payload):
    if conn is None:
        _MEMORY["previews"][payload["uid"]] = copy.deepcopy(payload)
    else:
        conn.execute(text("insert into records.debt_import_preview(uid,actor,profile,payload) "
                          "values(:uid,:actor,:profile,cast(:payload as jsonb)) "
                          "on conflict(uid) do update set payload=excluded.payload"),
                     {**{key: payload[key] for key in ("uid", "actor", "profile")},
                      "payload": json.dumps(payload, ensure_ascii=False)})


def get_preview(uid, actor, conn=None):
    if conn is None and db.configured():
        with transaction() as active:
            return get_preview(uid, actor, active)
    payload = (conn.execute(text("select payload from records.debt_import_preview where uid=:uid"),
                            {"uid": uid}).scalar() if conn is not None
               else copy.deepcopy(_MEMORY["previews"].get(uid)))
    if payload is None or payload["actor"] != actor:
        raise problem("not_found", "ไม่พบตัวอย่างนำเข้าของผู้ใช้รายนี้", 404)
    return payload


def public_preview(payload):
    return {key: value for key, value in payload.items() if key not in ("actor", "result")} | {
        "entries": [{key: value for key, value in entry.items() if key != "record"}
                    for entry in payload["entries"]]}


def stage(raw, filename, profile, actor, customers=None):
    if profile not in PROFILES:
        raise problem("profile", "ไม่รู้จักรูปแบบนำเข้า")
    records = _profile_rows(raw)
    customers = list(customers if customers is not None else current_customers())
    entries = build_entries(records, customers)
    if profile == "contract_supplement":
        entries = [entry for entry in entries if entry["product"]]
        for entry in entries:
            if entry["quality"]["unknown_money_fields"]:
                entry["eligible"] = False
                entry["review_reasons"].append("CONTRACT_FIELDS_UNCONFIRMED")
            # Existing contracts require review, not replacement of person-owned work.
            customer = next((c for c in customers or () if c.uid == entry["customer_uid"]), None)
            if customer and getattr(customer, "contracts", ()):
                entry["eligible"] = False
                entry["review_reasons"].append("EXISTING_CONTRACT_REVIEW")
    payload = {"uid": "dimp-" + uuid.uuid4().hex, "actor": actor, "profile": profile,
               "fingerprint": hashlib.sha256(raw).hexdigest(), "filename": filename,
               "state": "STAGED", "created_at": clock.stamp(), "epoch": _epoch(), "entries": entries,
               "counts": {"rows": len(records), "entries": len(entries),
                   "matched": sum(bool(entry["customer_uid"]) for entry in entries),
                   "eligible": sum(entry["eligible"] for entry in entries),
                   "review": sum(not entry["eligible"] for entry in entries)},
               "source_as_of": None}
    payload["version"] = digest(payload)
    with transaction() as conn:
        _save_preview(conn, payload)
    return public_preview(payload)


def supplements(conn=None):
    if conn is None and db.configured():
        with transaction() as active:
            return supplements(active)
    if conn is None:
        return copy.deepcopy(_MEMORY["supplements"])
    if not conn.execute(text("select to_regclass('records.contract_supplement')")).scalar():
        return {}
    return {row["contract_uid"]: row["payload"] for row in conn.execute(text(
        "select contract_uid,payload from records.contract_supplement")).mappings()}


def observation_map(conn, customer_uids):
    if not customer_uids or not conn.execute(text(
            "select to_regclass('records.debt_status_observation')")).scalar():
        return {}
    result = {}
    rows = conn.execute(text("select distinct on(customer_uid,payload->'record'->>'kind') "
                            "customer_uid,payload from records.debt_status_observation "
                            "where customer_uid=any(:uids) order by customer_uid,payload->'record'->>'kind',sequence desc"),
                        {"uids": list(customer_uids)}).mappings()
    for row in rows:
        result.setdefault(row["customer_uid"], []).append(row["payload"])
    return result


def observations(customer_uid, conn=None):
    if conn is None and db.configured():
        with transaction() as active:
            return observations(customer_uid, active)
    if conn is None:
        return [copy.deepcopy(row) for row in _MEMORY["observations"] if row["customer_uid"] == customer_uid]
    return list(conn.execute(text("select payload from records.debt_status_observation "
                                 "where customer_uid=:uid order by sequence desc"),
                             {"uid": customer_uid}).scalars())


def _publish(conn, uids, reason):
    cache = request_context.reads()
    if cache is not None:
        cache.pop("debt.installations", None)
    if conn is None:
        return
    conn.execute(text("insert into app.data_epoch(kind) values(:kind)"), {"kind": reason})
    try:
        from . import read_projection
        read_projection.invalidate_customers(conn, sorted(uids), reason=reason)
    except ImportError:
        pass  # The integration branch supplies this module.


def apply(uid, body, actor, role):
    if str(role).upper() not in ("MANAGER", "OWNER"):
        raise problem("forbidden", "เฉพาะผู้จัดการขึ้นไปยืนยันนำเข้า", 403)
    key = str(body.get("idempotency_key") or "").strip()
    if not key or len(key) > 200:
        raise problem("idempotency", "ต้องมีรหัสคำสั่งป้องกันการบันทึกซ้ำ")
    with transaction() as conn:
        payload = get_preview(uid, actor, conn)
        signature = digest(body)
        if payload["state"] == "APPLIED":
            if payload.get("command_signature") != signature:
                raise problem("idempotency_conflict", "ตัวอย่างนี้ถูกยืนยันด้วยคำสั่งอื่นแล้ว", 409)
            return payload["result"]
        if payload["version"] != body.get("preview_version") or payload["epoch"] != _epoch():
            raise problem("preview_stale", "ข้อมูลเปลี่ยนแล้ว กรุณาตรวจตัวอย่างใหม่", 409)
        selected = body.get("selected_keys")
        if not isinstance(selected, list) or not selected or len(selected) != len(set(selected)):
            raise problem("selection", "เลือกแถวที่จะยืนยันโดยไม่ซ้ำกัน")
        entries = {entry["key"]: entry for entry in payload["entries"]}
        if any(value not in entries or not entries[value]["eligible"] for value in selected):
            raise problem("review_required", "แถวที่เลือกยังมีข้อขัดแย้ง ต้องตรวจสอบก่อน", 409)
        affected = set()
        for value in selected:
            entry = entries[value]
            if payload["profile"] == "contract_supplement":
                record = copy.deepcopy(entry["record"])
                record["financial_evidence_only"] = True
                saved = {"customer_uid": entry["customer_uid"], "customer_no": entry["customer_no"],
                         "contract_uid": entry["contract_uid"], "product": entry["product"],
                         "record": record, "preview_uid": uid, "confirmed_by": actor,
                         "confirmed_at": clock.stamp()}
                if conn is None:
                    if entry["contract_uid"] in _MEMORY["supplements"]:
                        raise problem("existing_contract", "สัญญามีข้อมูลแล้ว ต้องตรวจสอบก่อนแทนที่", 409)
                    _MEMORY["supplements"][entry["contract_uid"]] = saved
                else:
                    inserted = conn.execute(text("insert into records.contract_supplement "
                        "(contract_uid,customer_uid,payload) values(:contract,:customer,cast(:payload as jsonb)) "
                        "on conflict(contract_uid) do nothing returning contract_uid"),
                        {"contract": entry["contract_uid"], "customer": entry["customer_uid"],
                         "payload": json.dumps(saved, ensure_ascii=False)}).scalar()
                    if not inserted:
                        raise problem("existing_contract", "สัญญามีข้อมูลแล้ว ต้องตรวจสอบก่อนแทนที่", 409)
            else:
                saved = {key: copy.deepcopy(entry[key]) for key in ("customer_uid", "contract_uid", "source_ref",
                          "source_status", "mapped_status", "installation", "termination_candidate", "record")}
                saved.update(preview_uid=uid, entry_key=value, imported_by=actor, imported_at=clock.stamp())
                if conn is None:
                    _MEMORY["observations"].append(saved)
                else:
                    conn.execute(text("insert into records.debt_status_observation "
                        "(customer_uid,preview_uid,entry_key,payload) values(:customer,:preview,:key,cast(:payload as jsonb)) "
                        "on conflict(preview_uid,entry_key) do nothing"),
                        {"customer": entry["customer_uid"], "preview": uid, "key": value,
                         "payload": json.dumps(saved, ensure_ascii=False)})
            affected.add(entry["customer_uid"])
        terminated = _confirm_terminations(payload, body, actor, role, selected)
        _publish(conn, affected, "DEBT_" + payload["profile"].upper())
        result = {"preview_uid": uid, "profile": payload["profile"], "applied": len(selected),
                  "customers": len(affected), "terminated": terminated, "review_remaining":
                  len(entries) - len(selected), "affected_customer_uids": sorted(affected)}
        payload.update(state="APPLIED", applied_at=clock.stamp(), command_signature=signature, result=result)
        _save_preview(conn, payload)
    from . import book, data_epoch
    book.invalidate()
    data_epoch.reset_cache()
    return result


def _confirm_terminations(payload, body, actor, role, selected):
    confirmations = body.get("termination_confirmations") or []
    if not isinstance(confirmations, list):
        raise problem("termination", "ข้อมูลยืนยันยุติสัญญาไม่ถูกต้อง")
    entries = {entry["key"]: entry for entry in payload["entries"]}
    terminated = 0
    for confirmation in confirmations:
        entry = entries.get(confirmation.get("key"))
        if not entry or entry["key"] not in selected or not (entry.get("termination_candidate") or {}).get("completed_evidence"):
            raise problem("termination_incomplete", "ยังไม่มีหลักฐานการยึดคืนที่เสร็จสมบูรณ์", 409)
        from . import cases, journey
        customer = journey.customer_by_uid(entry["customer_uid"])
        active = [contract for contract in customer.contracts
                  if cases.contract_field_of(contract, "status") not in cases.ENDED_CONTRACT_STATUSES]
        supplied = confirmation.get("contract_uids")
        if (not active or not isinstance(supplied, list) or len(supplied) != len(set(supplied)) or
                set(supplied) != {contract.uid for contract in active} or len(active) != 1):
            raise problem("termination_scope", "ต้องยืนยันหลักฐานครบทุกสัญญา — หลายสัญญาต้องตรวจสอบแยก", 409)
        reason = cases.validate_termination_inputs(confirmation.get("cause"), confirmation.get("reason"))
        for contract in active:
            cases.record_termination(contract, confirmation["cause"], actor, reason, "DEBT_IMPORT_REVIEW",
                                     on=confirmation.get("effective_on"))
            terminated += 1
    return terminated


def installation_for(contract_uid, conn=None):
    cache = request_context.reads()
    if cache is not None and "debt.installations" in cache:
        return cache["debt.installations"].get(contract_uid)
    if conn is None and db.configured():
        with transaction() as active:
            return installation_for(contract_uid, active)
    if conn is None:
        records = copy.deepcopy(_MEMORY["installations"])
    elif not conn.execute(text("select to_regclass('records.installation_confirmation')")).scalar():
        records = {}
    else:
        records = {row["contract_uid"]: row["payload"] for row in conn.execute(text(
            "select contract_uid,payload from records.installation_confirmation")).mappings()}
    if cache is not None:
        cache["debt.installations"] = records
    return records.get(contract_uid)


def confirm_installation(contract, body, actor, role):
    if role not in ("OFFICER", "SUPERVISOR", "MANAGER", "OWNER", "OPS"):
        raise problem("forbidden", "ไม่มีสิทธิ์ยืนยันผลติดตั้ง", 403)
    completed = _date(body.get("completed_on"))
    if not completed or completed > str(settings.business_date):
        raise problem("installation_date", "ต้องระบุวันติดตั้งสำเร็จจริง ไม่เกินวันทำการปัจจุบัน")
    if not all(isinstance(body.get(key), str) and body[key].strip() for key in
               ("document_ref", "reason", "idempotency_key")):
        raise problem("installation_evidence", "ต้องมีเอกสารอ้างอิง เหตุผล และรหัสคำสั่ง")
    payload = {"contract_uid": contract.uid, "customer_uid": contract.customer_uid,
               "completed_on": completed, "document_ref": body["document_ref"].strip(),
               "reason": body["reason"].strip(), "confirmed_by": actor, "confirmed_role": role,
               "confirmed_at": clock.stamp(), "idempotency_key": body["idempotency_key"],
               "command_signature": digest(body), "state": "CONFIRMED"}
    with transaction() as conn:
        previous = installation_for(contract.uid, conn)
        if previous:
            if previous["command_signature"] != payload["command_signature"] or previous["confirmed_by"] != actor:
                raise problem("installation_exists", "มีการยืนยันแล้ว ต้องตรวจสอบก่อนแก้ไข", 409)
            return previous
        if conn is None:
            _MEMORY["installations"][contract.uid] = payload
        else:
            conn.execute(text("insert into records.installation_confirmation(contract_uid,customer_uid,payload) "
                              "values(:contract,:customer,cast(:payload as jsonb))"),
                         {"contract": contract.uid, "customer": contract.customer_uid,
                          "payload": json.dumps(payload, ensure_ascii=False)})
        _publish(conn, {contract.customer_uid}, "INSTALLATION_CONFIRMED")
    from . import data_epoch
    data_epoch.reset_cache()
    return payload


def reset():
    with _LOCK:
        for value in _MEMORY.values():
            value.clear()

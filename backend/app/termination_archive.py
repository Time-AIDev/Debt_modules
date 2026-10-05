"""Shared termination facts and immutable API-shaped snapshots.

JSON only: never pickle archive content. Configured PostgreSQL failures refuse;
SQLite is the durable developer fallback. Existing audit entries are never changed.
"""
import copy
import hashlib
import json
import os
import sqlite3
import threading
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from datetime import date, datetime, timezone
from decimal import Decimal
from functools import wraps
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from . import db, errors, request_context

_PENDING = ContextVar('termination_pending', default=None)
_BYPASS = ContextVar('termination_projection_bypass', default=False)
_LOCK = threading.RLock()
_CACHE = ContextVar('termination_request_cache', default=None)

def cache():
    return _CACHE.get() if _CACHE.get() is not None else request_context.reads()


def json_value(value):
    if isinstance(value, (Decimal, date, datetime)):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError('Unsupported archive value: %s' % type(value).__name__)


@contextmanager
def connection(write=False):
    conn = None
    try:
        if db.configured():
            conn = db.connect()
            with (conn.begin() if not conn.in_transaction() else nullcontext()):
                if write:
                    conn.execute(text('select pg_advisory_xact_lock(76203145)'))
                yield conn
        else:
            path = Path(os.environ.get('TERMINATION_ARCHIVE_PATH') or Path(__file__).parents[1] / 'var' / 'termination-archive.sqlite3')
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(path), timeout=30)
            conn.execute('CREATE TABLE IF NOT EXISTS termination_fact (uid TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS termination_archive (uid TEXT PRIMARY KEY, customer_uid TEXT NOT NULL, payload TEXT NOT NULL, dedupe_key TEXT UNIQUE)')
            cols = {r[1] for r in conn.execute('PRAGMA table_info(termination_archive)')}
            if 'dedupe_key' not in cols:
                conn.execute('ALTER TABLE termination_archive ADD COLUMN dedupe_key TEXT')
            conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS termination_archive_dedupe_idx ON termination_archive(dedupe_key)')
            if write:
                conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
    except errors.Problem:
        raise
    except Exception as exc:
        raise errors.Problem(code='termination_archive_unavailable', status=503,
                             title='Termination archive unavailable',
                             detail='The shared termination register could not be read or saved.',
                             error_id='DEBT-ARCHIVE-0503', retryable=True, message_th='ทะเบียนการยุติไม่พร้อมใช้งาน กรุณาลองใหม่') from exc
    finally:
        if conn is not None:
            conn.close()


def _query(conn, query, params=None):
    return conn.execute(text(query), params or {}) if db.configured() else conn.execute(query, params or {})


def _table(kind):
    return ('app.' if db.configured() else '') + 'termination_' + kind


def _rows(kind, summary=False):
    with connection() as conn:
        expression = "payload - 'snapshot'" if summary and db.configured() else 'payload'
        rows = [r[0] if isinstance(r[0], dict) else json.loads(r[0])
                for r in _query(conn, 'select ' + expression + ' from ' + _table(kind))]
        if summary:
            for row in rows:
                row.pop('snapshot', None)
        return rows


def records():
    reads = cache()
    if reads is not None and 'termination.records' in reads:
        return reads['termination.records']
    rows = _rows('archive', summary=True)
    if reads is not None:
        reads['termination.records'] = rows
    return rows


def facts():
    if _BYPASS.get():
        return {}
    reads = cache()
    if reads is not None and 'termination.facts' in reads:
        return reads['termination.facts']
    rows = {r['contract_uid']: r for r in _rows('fact')}
    if reads is not None:
        reads['termination.facts'] = rows
    return rows


def invalidate():
    reads = cache()
    if reads is not None:
        reads.pop('termination.records', None)
        reads.pop('termination.facts', None)


def save(contract_facts, archives, strict=False):
    with connection(write=True) as conn:
        stored_facts = [r[0] if isinstance(r[0], dict) else json.loads(r[0])
                        for r in _query(conn, 'select payload from ' + _table('fact'))]
        if strict and {r['contract_uid'] for r in stored_facts} & {r['contract_uid'] for r in contract_facts}:
            raise errors.Problem(code='termination_conflict', status=409,
                                 title='Contract already terminated', detail='Another request terminated this contract.',
                                 message_th='มีผู้ดำเนินการยุติสัญญานี้แล้ว กรุณาโหลดข้อมูลใหม่',
                                 error_id='DEBT-ARCHIVE-0409', retryable=True)
        if strict:
            # Capture under the shared SQL lock using all committed facts plus
            # this operation. Two instances ending different contracts cannot
            # both miss the transition to a fully terminated customer.
            fresh_records = [r[0] if isinstance(r[0], dict) else json.loads(r[0])
                             for r in _query(conn, 'select payload from ' + _table('archive'))]
            token = _CACHE.set({'termination.facts': {r['contract_uid']: r for r in stored_facts + contract_facts},
                                'termination.records': fresh_records})
            try:
                from . import journey
                archives = []
                for uid in dict.fromkeys(r['customer_uid'] for r in contract_facts):
                    customer = journey.customer_by_uid(uid)
                    row = capture(customer) if customer else None
                    if row:
                        archives.append(row)
            finally:
                _CACHE.reset(token)
        for kind, rows in (('fact', contract_facts), ('archive', archives)):
            for row in rows:
                uid = row['contract_uid'] if kind == 'fact' else row['archive_uid']
                fields = 'uid,payload' if kind == 'fact' else 'uid,customer_uid,payload,dedupe_key'
                values = ':uid,:payload' if kind == 'fact' else ':uid,:customer_uid,:payload,:dedupe_key'
                if db.configured():
                    values = values.replace(':payload', 'CAST(:payload AS jsonb)')
                _query(conn, 'insert into ' + _table(kind) + ' (' + fields + ') values (' + values + ') on conflict do nothing',
                       {'uid': uid, 'customer_uid': row.get('customer_uid'), 'dedupe_key': row.get('dedupe_key'), 'payload': json.dumps(json_value(row), ensure_ascii=False, allow_nan=False)})
    invalidate()
    return archives


def observe(contract, record, status):
    pending = _PENDING.get()
    if pending is None:
        # Domain callers use the same transaction wrapper as HTTP callers.
        raise RuntimeError('record_termination must run in termination operation')
    from . import audit
    entry = audit.CURRENT.get()
    pending[contract.uid] = {'audit_request_id': entry.get('request_id') if entry else None,
                             'contract_uid': contract.uid, 'customer_uid': contract.customer_uid,
                             'status': status, 'termination': copy.deepcopy(record)}


def capture(customer, capture_kind='TERMINATION'):
    from . import audit, cases
    from .routers.today import case_detail
    statuses = [cases.contract_field_of(k, 'status') for k in customer.contracts]
    if not statuses or any(s not in cases.ENDED_CONTRACT_STATUSES for s in statuses) or all(s == 'CLOSED' for s in statuses):
        return None
    terms = [{'contract_uid': k.uid, 'status': s, **(cases.contract_field_of(k, 'termination') or {})}
             for k, s in zip(customer.contracts, statuses) if s != 'CLOSED']
    terminal_uids = sorted(t['contract_uid'] for t in terms)
    existing = next((r for r in records() if r['customer_uid'] == customer.uid and sorted(t['contract_uid'] for t in r.get('terminations', [])) == terminal_uids), None)
    if existing:
        return None
    entry = audit.CURRENT.get()
    token = audit.CURRENT.set(None)
    try:
        snapshot = json_value(case_detail(customer.uid))
        from . import journey
        for event in snapshot.get('events', []):
            if event.get('kind') == 'CONTRACT_TERMINATED':
                term = next((t for t in terms if t['contract_uid'] == event.get('contract_uid')), None)
                if term:
                    event.update({k: term.get(k) for k in ('on', 'by', 'cause', 'instrument', 'origin')})
                    event['reason'] = term.get('reason') or term.get('reason_th') or term.get('reason_en')
        snapshot['recovery_cases'] = json_value([r for r in journey.for_current().recovery_cases.values() if r.get('customer_uid') == customer.uid or r.get('contract_uid') in {k.uid for k in customer.contracts}])
    finally:
        audit.CURRENT.reset(token)
    known_dates = [t['on'] for t in terms if t.get('on')]
    actors = list(dict.fromkeys(t.get('by') for t in terms if t.get('by') and t.get('by') != 'SHEET'))
    reasons = list(dict.fromkeys(t.get('reason') or t.get('reason_th') or t.get('reason_en') for t in terms))
    origins = {t.get('origin') for t in terms}
    source = next(iter(origins)) if len(origins) == 1 and None not in origins else 'MIXED' if None not in origins else 'UNKNOWN'
    dedupe_key = hashlib.sha256(json.dumps([customer.uid, terminal_uids]).encode()).hexdigest()
    return {'archive_uid': str(uuid4()), 'customer_uid': customer.uid, 'dedupe_key': dedupe_key,
            'customer_name': customer.display_name, 'customer_no': customer.customer_no,
            'volt_id': getattr(customer, 'volt_id', None),
            'terminated_on': max(known_dates) if len(known_dates) == len(terms) else None,
            'actor': ', '.join(actors) or None, 'causes': sorted(set(t.get('cause') for t in terms if t.get('cause'))),
            'source': source,
            'reason': '\n\n'.join(r for r in reasons if r) or None, 'terminations': terms,
            'captured_at': datetime.now(timezone.utc).isoformat(), 'capture_kind': capture_kind,
            'audit_request_id': entry.get('request_id') if entry and capture_kind == 'TERMINATION' else None,
            'audit_request_ids': sorted({r['audit_request_id'] for r in facts().values() if r['contract_uid'] in terminal_uids and r.get('audit_request_id')}),
            'snapshot': snapshot, 'read_only': True}


def operation(fn):
    """Commit facts + snapshots after the entire successful route, rollback on failure."""
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if _PENDING.get() is not None:
            return fn(*args, **kwargs)
        from . import audit, cases, journey
        with _LOCK:
            cs, js, overlay = cases.for_current(), journey.for_current(), cases._fee_overlay()
            backups = [copy.deepcopy(obj.__dict__ if hasattr(obj, '__dict__') else obj) for obj in (cs, js, overlay)]
            pending = {}
            token = _PENDING.set(pending)
            try:
                result = fn(*args, **kwargs)
                archives = []
                if pending:
                    try:
                        archives = save(list(pending.values()), [], strict=True)
                    except Exception as exc:
                        if isinstance(exc, errors.Problem):
                            raise
                        raise errors.Problem(code='termination_archive_unavailable', status=503, title='Termination archive unavailable', detail='Termination was not committed.', error_id='DEBT-ARCHIVE-0503', retryable=True, message_th='บันทึกการยุติไม่สำเร็จ กรุณาลองใหม่') from exc
                if archives:
                    audit.describe(detail={'archive_uid': archives[0]['archive_uid']})
                return result
            except Exception:
                for obj, backup in zip((cs, js, overlay), backups):
                    dest = obj.__dict__ if hasattr(obj, '__dict__') else obj
                    dest.clear(); dest.update(backup)
                invalidate()
                raise
            finally:
                _PENDING.reset(token)
    return wrapped


def project(state):
    from . import cases
    grouped = {}
    for fact in facts().values():
        grouped.setdefault(fact['customer_uid'], []).append(fact)
    for uid, rows in grouped.items():
        case = state.cases.get(uid)
        customer = cases.customer_by_uid(uid)
        if case and customer:
            case['payment_status_system'] = cases._payment_status_from_contracts(customer)
            case['payment_status'] = case['payment_status_system']
            case['termination'] = rows[-1]['termination']
            for row in rows:
                if not any(e.get('contract_uid') == row['contract_uid'] and e.get('kind') == 'CONTRACT_TERMINATED' for e in state.events):
                    cases.add_event(state, case, 'CONTRACT_TERMINATED', contract_uid=row['contract_uid'], **row['termination'])


def backfill_current(capture_kind="BACKFILL"):
    from . import cases, journey
    archives, contract_facts = [], []
    existing_facts = facts()
    for customer in journey.book_customers():
        for k in customer.contracts:
            status = cases.contract_field_of(k, 'status')
            if status in cases.ENDED_CONTRACT_STATUSES and status != 'CLOSED' and k.uid not in existing_facts:
                contract_facts.append({'contract_uid': k.uid, 'customer_uid': customer.uid, 'status': status,
                                       'termination': cases.contract_field_of(k, 'termination') or {}})
        row = capture(customer, capture_kind)
        if row:
            archives.append(row)
    if contract_facts or archives:
        save(contract_facts, archives)
    return len(archives)


def get(archive_uid):
    with connection() as conn:
        row = _query(conn, 'select payload from ' + _table('archive') + ' where uid=:uid', {'uid': archive_uid}).first() if db.configured() else _query(conn, 'select payload from termination_archive where uid=:uid', {'uid': archive_uid}).fetchone()
        return (row[0] if isinstance(row[0], dict) else json.loads(row[0])) if row else None

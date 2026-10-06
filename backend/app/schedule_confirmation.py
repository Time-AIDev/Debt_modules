"""Contract-reviewed first due dates, independent of replaceable import snapshots."""
from datetime import date, datetime, timezone
from threading import RLock
from uuid import uuid4

from sqlalchemy import text
from . import db, errors

_MEMORY = []
_LOCK = RLock()


def _failure():
    return errors.Problem(code='schedule_confirmation_unavailable', status=503,
                          title='Contract confirmation store unavailable',
                          detail='The contract confirmation store must be migrated and reachable',
                          message_th='ยังอ่านข้อมูลยืนยันสัญญาไม่ได้ กรุณาตรวจฐานข้อมูลและ migration',
                          error_id='DEBT-SCHEDULE-0503')


def history(contract_uid=None):
    if not db.configured():
        return [dict(row) for row in _MEMORY if contract_uid is None or row['contract_uid'] == contract_uid]
    conn = None
    own_transaction = False
    try:
        conn = db.connect()
        own_transaction = not conn.in_transaction()
        rows = conn.execute(text('select payload from app.schedule_confirmation '
                                 'where (cast(:uid as text) is null or contract_uid = :uid) order by sequence'),
                            {'uid': contract_uid}).scalars().all()
        return [dict(row) for row in rows]
    except Exception:
        raise _failure() from None
    finally:
        if conn is not None:
            if own_transaction and conn.in_transaction():
                conn.rollback()
            conn.close()


def active():
    return {row['contract_uid']: row for row in history()}


def confirm(contract, body, actor):
    try:
        first_due = date.fromisoformat(body.get('first_due')).isoformat()
    except (ValueError, TypeError):
        raise errors.validation_failed([{'pointer': '/first_due', 'code': 'invalid_date',
                                         'message': 'first_due must be an ISO calendar date'}])
    for key in ('document_ref', 'reason'):
        value = body.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 1000 or '\x00' in value:
            raise errors.validation_failed([{'pointer': '/' + key, 'code': 'required',
                                             'message': 'A document reference and review reason are required'}])
    row = {'uid': str(uuid4()), 'contract_uid': contract.uid, 'customer_uid': contract.customer_uid,
           'first_due': first_due, 'document_ref': body['document_ref'].strip(),
           'reason': body['reason'].strip(), 'confirmed_by': actor,
           'confirmed_at': datetime.now(timezone.utc).isoformat(),
           'source_first_due': str(contract.first_due)}
    if db.configured():
        import json
        conn = None
        try:
            conn = db.connect()
            with conn.begin():
                conn.execute(text('select pg_advisory_xact_lock(hashtext(:uid))'), {'uid': contract.uid})
                conn.execute(text('insert into app.schedule_confirmation (contract_uid, payload) '
                                  'values (:uid, cast(:payload as jsonb))'),
                             {'uid': contract.uid, 'payload': json.dumps(row)})
                conn.execute(text("insert into app.data_epoch (kind) values ('CONTRACT_SCHEDULE')"))
        except Exception:
            raise _failure() from None
        finally:
            if conn is not None:
                conn.close()
        from . import data_epoch
        data_epoch.reset_cache()
    else:
        with _LOCK:
            _MEMORY.append(row)
    return row

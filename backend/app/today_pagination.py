"""Compatible Today pagination over the existing complete financial response."""
import hashlib
import json

from fastapi.encoders import jsonable_encoder

from . import data_epoch, errors, session, workbook_cursor


def page(data, filters, sort, limit, cursor, business_date):
    from .production_unit import CURRENT
    from .read_projection import _problem, code_fingerprint
    if cursor and limit is None:
        raise _problem('today')
    if limit is None:
        return data
    unit = CURRENT.get() or {}
    # Shared writes increment this transaction's business version. In-memory
    # prototypes instead bind to the actual visible rows, never a process cache.
    version = unit.get('version')
    if version is None:
        version = hashlib.sha256(json.dumps(jsonable_encoder(data['items']),
            sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    query = {'kind': 'today-compatible', 'filters': filters, 'sort': sort, 'limit': limit,
             'business_date': str(business_date), 'version': version,
             'subject': unit.get('subject') or session.CURRENT.get(), 'code': code_fingerprint()}
    epoch = data_epoch.current()
    try:
        offset = workbook_cursor.decode(cursor, epoch, query) if cursor else 0
    except errors.Problem as exc:
        raise _problem('today', stale=exc.status == 409 or 'different filters' in exc.detail) from None
    rows = data['items'][offset:offset + limit]
    next_offset = offset + len(rows)
    more = next_offset < len(data['items'])
    return dict(data, items=rows, page={'limit': limit, 'returned': len(rows), 'has_more': more,
        'next_cursor': workbook_cursor.encode(next_offset, epoch, query) if more else None})

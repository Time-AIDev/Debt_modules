"""Authenticated reads use the application's existing shared read scope."""
from datetime import date
from fastapi import APIRouter, Query
from .. import audit, cases, journey, errors, termination_archive as archive
router = APIRouter()


def parse_date(value):
    if value:
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            raise errors.validation_failed([{'pointer': '/date', 'code': 'not_a_date', 'message': 'Use YYYY-MM-DD', 'message_th': 'รูปแบบวันที่ไม่ถูกต้อง'}])
    return None


@router.get('/v1/terminated-customers')
def listing(q: str = '', since: str = None, until: str = None, cause: str = None,
            actor: str = None, source: str = None, page: int = Query(1, ge=1),
            customer_uid: str = Query(default=None, min_length=1, max_length=200)):
    since, until = parse_date(since), parse_date(until)
    latest = {}
    for row in archive.records():
        previous = latest.get(row['customer_uid'])
        if not previous or row['captured_at'] > previous['captured_at']:
            latest[row['customer_uid']] = row
    all_rows = []
    for row in latest.values():
        customer = journey.customer_by_uid(row['customer_uid'])
        if customer and any(cases.contract_field_of(k, 'status') not in cases.ENDED_CONTRACT_STATUSES for k in customer.contracts):
            continue
        all_rows.append(row)
    needle = q.strip().casefold()
    rows = [r for r in all_rows if
            (not customer_uid or r['customer_uid'] == customer_uid)
            and (not needle or needle in ' '.join(str(r.get(k) or '') for k in ('customer_name', 'customer_no', 'volt_id', 'customer_uid')).casefold())
            and (not since or bool(r.get('terminated_on') and r['terminated_on'][:10] >= since))
            and (not until or bool(r.get('terminated_on') and r['terminated_on'][:10] <= until))
            and (not cause or cause in r['causes']) and (not actor or actor == r.get('actor'))
            and (not source or source == r['source'])]
    rows.sort(key=lambda r: (r.get('terminated_on') or '', r['captured_at'], r['archive_uid']), reverse=True)
    return {'entries': [{k: v for k, v in r.items() if k != 'snapshot'} for r in rows[(page-1)*50:page*50]],
            'meta': {'total': len(rows), 'page': page, 'page_size': 50,
                     'actors': sorted({r['actor'] for r in all_rows if r.get('actor')}),
                     'sources': sorted({r['source'] for r in all_rows})}}


@router.get('/v1/terminated-customers/{archive_uid}')
def detail(archive_uid: str):
    row = archive.get(archive_uid)
    if row is None:
        raise errors.not_found('terminated case')
    audit.describe(act='TERMINATED_CASE_VIEWED', subject=('customer', row['customer_uid']), detail={'archive_uid': archive_uid})
    return row

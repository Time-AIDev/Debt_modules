"""R13: every write lands a row carrying the signing role, and a named act.

In-memory path only (no DATABASE_URL); the Postgres column is covered by test_audit_store.py.
"""
import hashlib

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Route

from app import audit, audit_store
from app.main import app

client = TestClient(app)

# FIELDS as they stood before actor_role was appended.
OLD_FIELDS = audit.FIELDS[:audit.FIELDS.index("actor_role")]


def _old_hash(entry, prev):
    payload = audit.canonical({k: entry.get(k) for k in OLD_FIELDS}) + prev
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _row(**over):
    row = {"seq": 1, "at": "2026-09-17T00:00:00+00:00", "business_date": "2026-09-17",
           "actor_claimed": "nantapol", "actor_source": "HEADER", "session_id": None,
           "request_id": "r1", "verb": "POST", "route_template": "/v1/x", "act": "X",
           "subject_type": None, "subject_uid": None, "detail": {}, "outcome": "OK",
           "status": 200, "error_code": None}
    row.update(over)
    return row


def test_a_row_hashed_before_actor_role_existed_still_verifies():
    old = _row()                                  # no actor_role key at all
    old["prev_hash"] = audit.GENESIS
    old["hash"] = _old_hash(old, audit.GENESIS)
    assert audit.hash_entry(old, audit.GENESIS) == old["hash"]
    # Read back from the new column it arrives as None; still the same hash.
    assert audit.hash_entry({**old, "actor_role": None}, audit.GENESIS) == old["hash"]
    chain = audit.Chain()
    chain._entries.append(old)
    assert chain.verify()["ok"] is True


def test_a_set_actor_role_is_covered_by_the_hash():
    chain = audit.Chain()
    chain.append(**{k: v for k, v in _row(actor_role="MANAGER").items() if k not in ("seq", "at", "business_date")})
    assert chain.verify()["ok"] is True
    chain.entries()[0]["actor_role"] = "OWNER"
    assert chain.verify()["ok"] is False


def _latest():
    return audit_store.read({}, limit=1, before_seq=None)[0]


def test_a_write_records_the_header_role_and_a_named_act():
    client.put("/v1/reports/weekly/2026-09-14..2026-09-20/focus", json={"text": "x"},
               headers={"X-Volt-Role": "manager", "X-Volt-Officer": "whan"})
    row = _latest()
    assert row["actor_role"] == "MANAGER"
    assert row["act"] == "WEEKLY_FOCUS_SET"


def test_an_unknown_header_role_records_none():
    client.put("/v1/reports/weekly/2026-09-14..2026-09-20/focus", json={"text": "x"},
               headers={"X-Volt-Role": "GOD"})
    assert _latest()["actor_role"] is None


def test_a_body_role_is_never_trusted():
    client.put("/v1/reports/weekly/2026-09-14..2026-09-20/focus", json={"text": "x", "role": "OWNER"})
    assert _latest()["actor_role"] is None


# Each route names its act first thing, so even a refusal (bogus uid, no role, empty
# body) carries the act. Path params are filled with a value that exists nowhere.
NAMED_AT_ENTRY = {
    ("POST", "/v1/orders/{no}/approve"), ("POST", "/v1/orders"), ("DELETE", "/v1/orders/{no}"),
    ("POST", "/v1/feedback"), ("PUT", "/v1/criteria/default"), ("DELETE", "/v1/criteria/default"),
    ("DELETE", "/v1/board/columns/{column_id}"), ("POST", "/v1/contracts/{contract_uid}/penalty-invoices"),
    ("POST", "/v1/contracts/{contract_uid}/transactions"), ("POST", "/v1/webhooks/peak/payments"), ("POST", "/v1/webhooks/peak/{kind}"),
    ("POST", "/v1/contacts"), ("POST", "/v1/contacts/{contact_id}:retract"),
    ("POST", "/v1/config/approval-paths"), ("POST", "/v1/imports"),
    ("DELETE", "/v1/status-overrides/{ref:path}"),
    ("POST", "/v1/invoices/{uid}:issue-peak"), ("PUT", "/v1/ladder-mode"), ("POST", "/v1/ptps"),
    ("POST", "/v1/ptps/{uid}:close"), ("POST", "/v1/ptps/{uid}:cancel"), ("POST", "/v1/service-issues"),
    ("POST", "/v1/service-issues/{uid}:resolve"), ("POST", "/v1/board/moves"),
    ("POST", "/v1/cases/{uid}:advance"), ("POST", "/v1/cash-cases/{uid}:advance"),
    ("POST", "/v1/cases/{uid}/restructures"), ("POST", "/v1/restructures/{uid}:approve"),
    ("POST", "/v1/restructures/{uid}:record-miss"), ("POST", "/v1/manager-review/{uid}:decide"),
    ("POST", "/v1/arrangements/{uid}:break"), ("POST", "/v1/npl-cases/{uid}/recovery"),
    ("POST", "/v1/recovery-cases/{uid}/recoveries"), ("POST", "/v1/recovery-cases/{uid}:resolve"),
    ("POST", "/v1/repossession-lots/{uid}:count"), ("POST", "/v1/repossession-lots/{uid}:grade"),
    ("POST", "/v1/repossession-lots/{uid}:price"), ("POST", "/v1/repossession-lots/{uid}:sell"),
    ("POST", "/v1/contracts/{contract_uid}/service-billing:bill"),
    ("POST", "/v1/contracts/{contract_uid}/service-billing:decline"),
    ("POST", "/v1/invoices/{uid}:issue"), ("POST", "/v1/invoices/{uid}:send"),
    ("POST", "/v1/invoices/{uid}:review-original"), ("POST", "/v1/invoices/{uid}:link-sent"),
    ("POST", "/v1/receipts"), ("POST", "/v1/intercompany/docs"), ("POST", "/v1/cancellations"),
    ("POST", "/v1/auth/password"), ("POST", "/v1/auth/google"), ("POST", "/v1/auth/logout"),
    ("POST", "/v1/peak-documents/{uid}:resend"), ("POST", "/v1/peak-documents/{uid}:refresh"),
    ("POST", "/v1/peak-documents:refresh-all"), ("POST", "/v1/peak-documents/stub"),
    ("POST", "/v1/slips"), ("POST", "/v1/credit-notes"),
    ("POST", "/v1/pipelines/peak-report:run"), ("POST", "/v1/pipelines/peak-report:start"),
    ("POST", "/v1/pipeline/{uid}/gates/down-payment"), ("POST", "/v1/pipeline/{uid}/gates/epc-confirmed"),
    ("POST", "/v1/pipeline/{uid}:release"), ("POST", "/v1/pipeline/{uid}/delivery"),
    ("POST", "/v1/pipeline/{uid}/delivery/reply"), ("POST", "/v1/pipeline/{uid}/install-outcome"),
    ("POST", "/v1/pipeline/{uid}/reschedule"), ("POST", "/v1/pipelines/crm-lead:run"),
    ("POST", "/v1/pipelines/crm-lead:start"), ("PUT", "/v1/pipelines/crm-lead/schedule"),
    ("POST", "/v1/reports/weekly:snapshot"), ("POST", "/v1/reports/weekly/snapshots/{snapshot_uid}:rename"),
    ("PUT", "/v1/reports/weekly/{period}/targets"), ("PUT", "/v1/reports/weekly/{period}/focus"),
    ("PUT", "/v1/reports/collection/{month}/targets"),
    ("POST", "/v1/dictionaries/{name}/values"), ("POST", "/v1/dictionaries/{name}/values/{code}:deactivate"),
    ("POST", "/v1/band-sets/{code}:activate"), ("POST", "/v1/band-sets/{code}:deactivate"),
    ("POST", "/v1/band-sets"), ("POST", "/v1/customers/{uid}/assign"),
    ("POST", "/v1/today/reminders:send"), ("POST", "/v1/today/items/{uid}:done"),
    ("POST", "/v1/workbook:export"), ("POST", "/v1/cases/by-customer/{customer_uid}/next-action"),
    ("POST", "/v1/contacts/{uid}:correct"), ("POST", "/v1/case-ptps/{uid}:close"),
    ("POST", "/v1/case-ptps/{uid}:renegotiate"), ("POST", "/v1/cases/by-customer/{customer_uid}/review-requests"),
    ("POST", "/v1/reviews/{uid}:answer"), ("POST", "/v1/case-issues/{uid}:close"),
}


def _path(template):
    out = template.replace("{ref:path}", "nope")
    for name, value in (("{no}", "999999"), ("{contact_id}", "999999")):
        out = out.replace(name, value)
    import re
    return re.sub(r"\{[^}]+\}", "nope-0", out)


def test_the_list_covers_real_routes():
    routes = {(m, r.path) for r in app.routes if isinstance(r, Route) for m in (r.methods or ())}
    assert NAMED_AT_ENTRY <= routes, NAMED_AT_ENTRY - routes


@pytest.mark.parametrize("method,template", sorted(NAMED_AT_ENTRY))
def test_every_write_route_lands_a_named_act(method, template):
    raw = template in ("/v1/imports", "/v1/pipelines/crm-lead:run", "/v1/pipelines/crm-lead:start",
                       "/v1/pipelines/peak-report:run", "/v1/pipelines/peak-report:start")
    kwargs = {"content": b""} if raw else ({} if method == "DELETE" else {"json": {}})
    client.request(method, _path(template), headers={"X-Volt-Role": "OFFICER"}, **kwargs)
    row = _latest()
    assert row["route_template"] == template
    assert row["act"], "%s %s landed act=None" % (method, template)
    assert row["actor_role"] == "OFFICER"

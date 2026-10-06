"""Pure unit contracts at intake, delivery, persistence and publication boundaries.

No database, provider account or production record is used here. SQL locking and
atomicity remain covered by the separate PostgreSQL suites in coverage-map.json.
"""
import asyncio
import copy
import hashlib
from collections import OrderedDict
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app import business_records, db, errors, refresh, worker
from app.integrations import odoo
from app.pipelines import ingress, rules, runs


@pytest.mark.parametrize("result", [0, False, [], {"records": []}])
def test_odoo_rpc_keeps_valid_empty_results(monkeypatch, result):
    seen = []
    def send(url, **kwargs):
        seen.append(kwargs["json"])
        return httpx.Response(200, json={"result": result}, request=httpx.Request("POST", url))
    monkeypatch.setattr(odoo.httpx, "post", send)
    assert odoo._rpc("https://odoo.example", "object", "execute_kw", ["synthetic"]) == result
    assert seen[0]["params"]["method"] == "execute_kw"


@pytest.mark.parametrize("status", [401, 429, 503])
def test_odoo_http_refusals_cannot_become_empty_success(monkeypatch, status):
    monkeypatch.setattr(odoo.httpx, "post", lambda url, **kw: httpx.Response(
        status, json={"result": []}, request=httpx.Request("POST", url)))
    with pytest.raises(httpx.HTTPStatusError):
        odoo._rpc("https://odoo.example", "object", "execute_kw", [])


def test_odoo_application_error_is_not_data(monkeypatch):
    monkeypatch.setattr(odoo.httpx, "post", lambda url, **kw: httpx.Response(
        200, json={"error": {"data": {"message": "synthetic refusal"}}}, request=httpx.Request("POST", url)))
    with pytest.raises(odoo.OdooError):
        odoo._rpc("https://odoo.example", "object", "execute_kw", [])


@pytest.mark.parametrize("ids", [[2, 1], [1, 1], [True], ["1"], [0]])
def test_invalid_odoo_page_cannot_hang_or_retire_existing_data(monkeypatch, ids):
    monkeypatch.setattr(odoo, "_config", lambda: {})
    monkeypatch.setattr(odoo, "_login", lambda _: 1)
    calls = []
    def execute(config, uid, model, method, args, kwargs=None):
        if method == "search_count": return len(ids)
        calls.append(method)
        if len(calls) > 2: raise AssertionError("non-advancing pull was not stopped")
        return [{"id": i} for i in ids]
    with pytest.raises(odoo.OdooError):
        ingress.from_odoo(rules.load(), execute=execute)


def test_repeated_odoo_page_is_refused_before_an_infinite_refetch(monkeypatch):
    monkeypatch.setattr(odoo, "_config", lambda: {})
    monkeypatch.setattr(odoo, "_login", lambda _: 1)
    calls = []
    def execute(config, uid, model, method, args, kwargs=None):
        if method == "search_count": return 2
        calls.append(method)
        if len(calls) > 2: raise AssertionError("repeated page was not stopped")
        return [{"id": 1}]
    with pytest.raises(odoo.OdooError):
        ingress.from_odoo(rules.load(), execute=execute)
    assert len(calls) == 2


@pytest.mark.parametrize("page", [None, False, {}, ""])
def test_malformed_empty_page_is_not_a_valid_zero_record_pull(monkeypatch, page):
    monkeypatch.setattr(odoo, "_config", lambda: {})
    monkeypatch.setattr(odoo, "_login", lambda _: 1)
    def execute(config, uid, model, method, args, kwargs=None):
        return 0 if method == "search_count" else page
    with pytest.raises(odoo.OdooError): ingress.from_odoo(rules.load(), execute=execute)


def fake_lease(monkeypatch, *, attempt=1, finished=False, dead=False, acquired=True):
    lease = MagicMock()
    lease.__enter__.return_value = lease
    def execute(statement, values=None):
        result = MagicMock()
        sql = str(statement)
        result.scalar_one.return_value = acquired if "pg_try_advisory" in sql else attempt
        result.first.return_value = SimpleNamespace(finished_at=finished, dead_lettered_at=dead)
        return result
    lease.execute.side_effect = execute
    lease.in_transaction.return_value = False
    monkeypatch.setattr(db, "connect", lambda: lease)
    return lease


@pytest.mark.parametrize("finished,dead", [(True, False), (True, True)])
def test_redelivery_of_terminal_job_does_not_execute_business_twice(monkeypatch, finished, dead):
    fake_lease(monkeypatch, finished=finished, dead=dead)
    body = AsyncMock()
    monkeypatch.setattr(worker, "_execute_job_body", body)
    result = asyncio.run(worker.execute_job("synthetic-job"))
    assert result["dead_letter"] is dead
    body.assert_not_called()


def test_second_worker_does_not_execute_a_leased_job(monkeypatch):
    fake_lease(monkeypatch, acquired=False)
    body = AsyncMock()
    monkeypatch.setattr(worker, "_execute_job_body", body)
    with pytest.raises(errors.Problem) as refused:
        asyncio.run(worker.execute_job("synthetic-job"))
    assert refused.value.code == "job_already_running"
    body.assert_not_called()


@pytest.mark.parametrize("status,explicit_retry,attempt,terminal", [
    (401, False, 1, True), (409, False, 1, True), (422, False, 1, True),
    (408, False, 1, False), (429, False, 1, False), (503, False, 1, False),
    (409, True, 1, False), (503, True, 5, True),
])
def test_delivery_failure_routes_to_retry_or_dead_letter_and_releases_lock(
        monkeypatch, status, explicit_retry, attempt, terminal):
    lease = fake_lease(monkeypatch, attempt=attempt)
    monkeypatch.setenv("MAX_JOB_ATTEMPTS", "5")
    problem = errors.Problem("synthetic_failure", status, "refused", "synthetic", "ทดสอบ", "TEST",
                             retryable=explicit_retry)
    monkeypatch.setattr(worker, "_execute_job_body", AsyncMock(side_effect=problem))
    retry, dead = [], []
    monkeypatch.setattr(worker, "_retry", lambda *a: retry.append(a))
    monkeypatch.setattr(worker, "_dead_letter", lambda *a: dead.append(a))
    if terminal:
        assert asyncio.run(worker.execute_job("synthetic-job"))["dead_letter"] is True
        assert dead and not retry
    else:
        with pytest.raises(errors.Problem): asyncio.run(worker.execute_job("synthetic-job"))
        assert retry == [("synthetic-job", "synthetic_failure", 5)] and not dead
    assert any("pg_advisory_unlock" in str(c.args[0]) for c in lease.execute.call_args_list)


@pytest.mark.parametrize("value", [
    {"balance": Decimal("0.10"), "date": date(2026, 1, 1)},
    OrderedDict([(1, (Decimal("100.00"), None)), (2, frozenset({"a", "b"}))]),
    {"empty": [], "nested": {"timestamp": datetime(2026, 1, 1, 12, 30)}},
])
def test_persisted_records_round_trip_types_without_cross_request_aliases(value):
    records = business_records.records(value)
    class Conn:
        def execute(self, *_):
            return SimpleNamespace(fetchall=lambda: [SimpleNamespace(
                record_key=k, payload=copy.deepcopy(v), schema_version=1) for k, v in records.items()])
    first, found = business_records.load(Conn(), "synthetic")
    second, _ = business_records.load(Conn(), "synthetic")
    assert found and first == value and second == value and first is not second
    assert business_records.canonical(business_records.encode(first)) == business_records.canonical(business_records.encode(value))


def test_unknown_serialized_type_cannot_load_code(monkeypatch):
    imported = MagicMock()
    monkeypatch.setattr(business_records.importlib, "import_module", imported)
    with pytest.raises(ValueError):
        business_records.decode({"t": "untrusted.Customer", "v": {}})
    imported.assert_not_called()


@pytest.mark.parametrize("schema", [0, 2, None])
def test_unsupported_record_schema_is_refused_before_decode(schema):
    class Conn:
        def execute(self, *_):
            return SimpleNamespace(fetchall=lambda: [SimpleNamespace(
                record_key="@root", payload={"t": "dict", "v": []}, schema_version=schema)])
    with pytest.raises(ValueError): business_records.load(Conn(), "synthetic")


def test_epoch_write_failure_cannot_publish_or_mark_stale_data_current(monkeypatch):
    from app import data_epoch, main, import_sync
    monkeypatch.setattr(refresh, "_landing_has_a_run", lambda: True)
    monkeypatch.setattr(data_epoch, "current", lambda: 4)
    monkeypatch.setattr(data_epoch, "bump", MagicMock(side_effect=RuntimeError("synthetic private value")))
    reload = MagicMock(); mark = MagicMock()
    monkeypatch.setattr(main, "reload_book", reload)
    monkeypatch.setattr(import_sync, "note_book_epoch", mark)
    result = refresh.after_landing("odoo", 10)
    assert result["served"] is False and result["epoch"] == 4
    assert result["problem"]["code"] == "epoch_write_failed"
    assert "private value" not in str(result)
    reload.assert_not_called(); mark.assert_not_called()


def test_external_integration_dns_is_blocked_during_tests():
    import socket
    with pytest.raises(AssertionError, match="mock external integrations"):
        socket.getaddrinfo("production-odoo.example", 443)

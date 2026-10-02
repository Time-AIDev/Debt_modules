"""Staging loaded customers in 3–14 s, with 30–51 s bursts (Cloud Run logs 2026-09-21..27).

Measured on a copy of the real book: one payment-position scan per row was 64% of
today.build(), the rail and the weekly report built the book twice, FastAPI's encoder
took as long as the build on the 7–10 MB lists, and a new session's parallel requests
each seeded the same stores. Each fix must leave the served bytes unchanged.
"""
import json
import gzip
import threading
import time
from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import cases as cases_domain
from app import db, main, session as session_domain, today as today_domain
from app.routers.today import _json
from app.routers import today as today_router


@pytest.fixture
def client():
    return TestClient(main.app)


def test_rows_for_returns_the_scan_in_store_order_first_ask_or_indexed():
    rows = {n: {"uid": n, "k": "abc"[n % 3]} for n in range(30)}
    scan = lambda values: [r for r in rows.values() if r["k"] in values]   # noqa: E731
    assert main.rows_for(rows, "k", {"a"}) == scan({"a"})                   # outside a GET
    token = main._VIEW_MEMO.set({})
    try:
        for values in ({"b"}, {"b"}, {"a", "c"}, {"z"}, {"c", "a", "b"}):   # scan, then indexed
            assert main.rows_for(rows, "k", values) == scan(values)
        rows[99] = {"uid": 99, "k": "a"}                                    # the store moved
        assert main.rows_for(rows, "k", {"a"}) == scan({"a"})
        log = [{"k": "x"}, {"k": "y"}, {"k": "x"}]                          # a list store too
        assert main.rows_for(log, "k", {"x"}) == main.rows_for(log, "k", {"x"}) == [log[0], log[2]]
    finally:
        main._VIEW_MEMO.reset(token)


@pytest.mark.parametrize("path, most", [("/v1/shell/summary", 1), ("/v1/reports/weekly", 1),
                                        ("/v1/reports/bucket-flow", 1), ("/v1/today", 1)])
def test_each_summary_builds_the_book_once(client, monkeypatch, path, most):
    calls = []
    real = today_domain.build
    monkeypatch.setattr(today_domain, "build", lambda *a, **k: calls.append(1) or real(*a, **k))
    assert client.get(path).status_code == 200
    assert len(calls) == most, "%s built the book %d times" % (path, len(calls))


@pytest.mark.parametrize("path", ["/v1/today", "/v1/workbook?identities=1"])
def test_each_list_request_applies_case_overlays_once(client, monkeypatch, path):
    """A helper added inside one row must not turn one case scan into N scans."""
    calls = []
    real = cases_domain._apply_payment_claims

    def counted(state):
        calls.append(state)
        return real(state)

    monkeypatch.setattr(cases_domain, "_apply_payment_claims", counted)
    response = client.get(path)
    assert response.status_code == 200
    assert len(calls) == 1


def test_identity_search_index_builds_once_per_book_snapshot(client, monkeypatch):
    built = []
    real = today_router._identity_row

    def counted(customer, case_state=None):
        built.append(customer.uid)
        return real(customer, case_state)

    monkeypatch.setattr(today_router, "_identity_row", counted)
    first = client.get("/v1/workbook", params={"identities": 1, "limit": 2}).json()
    second = client.get("/v1/workbook", params={"identities": 1, "limit": 2}).json()
    assert first["rows"] == second["rows"]
    assert len(built) == len(main.IDENTITIES)

    main.IDENTITIES = list(main.IDENTITIES)
    client.get("/v1/workbook", params={"identities": 1, "limit": 2})
    assert len(built) == 2 * len(main.IDENTITIES)


def test_route_timing_is_structured_and_breaks_out_the_list_phases(client, monkeypatch, capsys):
    monkeypatch.setenv("ROUTE_TIMING", "1")
    response = client.get("/v1/workbook", params={"identities": 1, "limit": 2},
                          headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    records = []
    for line in capsys.readouterr().err.splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    timing = next(row for row in records if row.get("metric") == "http_server_duration_ms")
    assert timing["route"] == "/v1/workbook"
    assert timing["elapsed_ms"] >= 0
    assert set(timing["phases_ms"]) >= {
        "session_restore", "session_heal", "case_overlays", "workbook_build", "json", "gzip", "session_flush",
    }


def test_workbook_slo_logs_fast_requests_even_below_the_slow_threshold(client, monkeypatch, capsys):
    """The p95 metric needs the whole latency distribution, not only its slow tail."""
    monkeypatch.delenv("ROUTE_TIMING", raising=False)
    monkeypatch.setenv("SLOW_REQUEST_MS", "999999")
    response = client.get("/v1/workbook", params={"identities": 1, "limit": 2})
    assert response.status_code == 200
    records = []
    for line in capsys.readouterr().err.splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    timing = next(row for row in records if row.get("metric") == "http_server_duration_ms")
    assert timing["route"] == "/v1/workbook"
    assert timing["severity"] == "INFO"


def test_fifty_row_customer_page_stays_inside_the_payload_budget(client):
    response = client.get("/v1/workbook", params={"identities": 1, "limit": 50},
                          headers={"Accept-Encoding": "identity"})
    assert response.status_code == 200
    assert len(response.content) <= 500_000
    assert len(gzip.compress(response.content, compresslevel=6)) <= 100_000


def test_the_fast_body_is_the_bytes_fastapi_would_have_sent():
    payload = {"ชื่อ": "ทดสอบ", "n": 1, "x": 1.5, "none": None, "ok": True, "d": date(2026, 9, 27),
               "at": datetime(2026, 9, 27, 8, 30), "money": Decimal("1234.50"), "whole": Decimal("7"),
               "tags": {"a"}, "rows": [{"k": (1, 2)}]}
    assert _json(payload).body == JSONResponse(jsonable_encoder(payload)).body
    dated_key = {date(2026, 9, 27): 1}                      # a key json cannot hold: old path
    assert _json(dated_key).body == JSONResponse(jsonable_encoder(dated_key)).body
    assert _json(payload).media_type == "application/json"


def test_parallel_first_touches_of_one_session_seed_once(monkeypatch):
    monkeypatch.setattr(db, "configured", lambda: False)
    seeded = []

    def slow_factory():
        seeded.append(1)
        time.sleep(0.2)
        return {"seed": len(seeded)}

    store = session_domain.Store(slow_factory, key="test.first_touch")
    got = []

    def touch():
        session_domain.CURRENT.set("s-first-touch-test")
        got.append(store.for_current())

    try:
        threads = [threading.Thread(target=touch) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        session_domain.REGISTRY.remove(store)
    assert len(seeded) == 1 and all(g is got[0] for g in got)


def test_hashed_assets_are_cached_and_everything_else_is_not(client):
    # backend/static exists only after a frontend build, so the test brings its own
    # file under /assets/ — first in line, ahead of the StaticFiles mount when present.
    routes = main.app.router.routes
    routes.insert(0, APIRoute("/assets/cache-probe-1a2b.js", lambda: Response("x", media_type="text/javascript")))
    try:
        assert client.get("/assets/cache-probe-1a2b.js").headers["cache-control"] == \
            "public, max-age=31536000, immutable"
        assert client.get("/assets/missing-probe-1a2b.js").headers["cache-control"] == "no-store"
        assert client.get("/v1/today-list").headers["cache-control"] == "no-store"
    finally:
        del routes[0]

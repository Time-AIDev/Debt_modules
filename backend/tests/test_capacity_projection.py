"""Capacity changes must preserve financial rows, scope and atomic publication."""
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from app import business_records, cases, main, migrate, read_projection, session
from app.production_unit import CURRENT, case_token, customer_scope, independent_control


@pytest.fixture
def capacity(pg_conn):
    migrate.apply(pg_conn)
    pg_conn.execute(text(Path(read_projection.__file__).with_name("capacity_schema.sql").read_text()))
    pg_conn.commit()
    yield pg_conn


@contextmanager
def unit(conn, customer_uid=None, mutation=False):
    values = {"conn": conn, "capacity": True, "mutation": mutation, "subject": "synthetic-owner", "version": 0}
    if customer_uid:
        values["customer_uid"] = customer_uid
    token = CURRENT.set(values)
    sid = session.CURRENT.set("capacity-test")
    touched = session.TOUCHED.set(set())
    try:
        yield values
    finally:
        for store in session.REGISTRY:
            store._by_session.pop("capacity-test", None)
        session.TOUCHED.reset(touched)
        session.CURRENT.reset(sid)
        CURRENT.reset(token)


def state():
    first, second = main.CUSTOMERS[:2]
    value = cases.CaseState()
    value.cases = {first.uid: {"uid": "case-first", "customer_uid": first.uid, "amount": "100.00"},
                   second.uid: {"uid": "case-second", "customer_uid": second.uid, "amount": "200.00"}}
    value.events = [{"case_uid": "case-first", "text": "first"}, {"case_uid": "case-second", "text": "second"}]
    return value, first.uid, second.uid


def test_customer_load_does_not_decode_or_copy_another_customer(capacity):
    value, first, second = state()
    with unit(capacity):
        business_records.save(capacity, "cases.state", value)
    with unit(capacity, first):
        own, found = business_records.load(capacity, "cases.state")
        assert found and set(own.cases) == {first}
        assert [row["text"] for row in own.events] == ["first"]
        own.cases[first]["amount"] = "90.00"
        own.events.append({"case_uid": "case-first", "text": "added"})
        assert business_records.save(capacity, "cases.state", own)
    with unit(capacity):
        saved, _ = business_records.load(capacity, "cases.state")
        assert saved.cases[second]["amount"] == "200.00"
        assert saved.cases[first]["amount"] == "90.00"
        assert [row["text"] for row in saved.events] == ["first", "second", "added"]


def test_scoped_delete_never_removes_another_case(capacity):
    value, first, second = state()
    with unit(capacity):
        business_records.save(capacity, "cases.state", value)
    with unit(capacity, first):
        own, _ = business_records.load(capacity, "cases.state")
        own.cases.clear()
        business_records.save(capacity, "cases.state", own)
    with unit(capacity):
        saved, _ = business_records.load(capacity, "cases.state")
        assert set(saved.cases) == {second}


def test_dirty_save_changes_only_the_edited_row(capacity):
    value, first, second = state()
    with unit(capacity):
        business_records.save(capacity, "cases.state", value)
    before = dict(capacity.execute(text("select record_key,version from app.business_record where store_key='cases.state'")).all())
    with unit(capacity, first):
        own, _ = business_records.load(capacity, "cases.state")
        assert business_records.save(capacity, "cases.state", own) is False
        own.cases[first]["amount"] = "89.00"
        business_records.save(capacity, "cases.state", own)
    after = dict(capacity.execute(text("select record_key,version from app.business_record where store_key='cases.state'")).all())
    assert [key for key in before if before[key] != after[key]] == ['cases/"%s"' % first]


def test_legacy_json_records_are_upgraded_without_losing_lists(capacity):
    value, first, second = state()
    business_records.save(capacity, "cases.state", value)  # legacy format
    with unit(capacity):
        legacy, _ = business_records.load(capacity, "cases.state")
        assert legacy.cases == value.cases
        business_records.save(capacity, "cases.state", legacy)
    with unit(capacity, second):
        upgraded, _ = business_records.load(capacity, "cases.state")
        assert set(upgraded.cases) == {second}
        assert upgraded.events == [value.events[1]]


def test_ids_are_unique_across_customers_and_seed_factories_are_deterministic(capacity):
    with unit(capacity, "one", mutation=True) as context:
        first = business_records.next_domain_id("evt", 1)
        context["seeding"] = True
        assert business_records.next_domain_id("evt", 1) is None
    with unit(capacity, "two", mutation=True):
        second = business_records.next_domain_id("evt", 1)
    assert first != second and first.startswith("evt-")


def projected(uid, *, overdue=0, entity="SPV", worked=False, tier="ROUTINE", pending=False):
    payload = {"customer": {"uid": uid, "display_name": "Synthetic " + uid, "customer_no": uid},
               "case": {"sheet": {}, "payment_status": "PENDING" if pending else "LATE", "officer_uid": "synthetic"},
               "entity": entity, "aggregate_overdue": str(overdue), "aggregate_outstanding": str(overdue),
               "oldest_dpd": 91 if overdue else 0, "tier": tier, "tier_rank": 7, "contact_lock": {"state": "OPEN"}}
    current = cases.CaseState()
    row = read_projection._row(uid, payload, dict(payload, worked_today=worked), current, "2026-10-23")
    return row


def generation(conn, rows):
    metadata = {"workbook": {"meta": {"total": len(rows)}},
                "today": {"run": {}, "meta": {"officer_totals": {"synthetic": len(rows)}, "reminder_batch": []}}}
    import json
    key = conn.execute(text("insert into app.projection_generation(source_epoch,business_date,metadata) "
                            "values(0,'2026-10-23',cast(:m as jsonb)) returning id"), {"m": json.dumps(metadata)}).scalar_one()
    read_projection._save_rows(conn, key, rows)
    conn.execute(text("update app.projection_current set generation=:g,dirty=false where singleton"), {"g": key})
    return key


def test_sql_pages_keep_exact_totals_stable_ties_and_entity_filters(capacity):
    generation(capacity, [projected("a", overdue=100), projected("b", overdue=100), projected("c", overdue=90, entity="EPC")])
    with unit(capacity):
        first = read_projection.workbook({"entity": "SPV"}, limit=1)
        second = read_projection.workbook({"entity": "SPV"}, limit=1, cursor=first["page"]["next_cursor"])
        assert first["meta"]["total"] == second["meta"]["total"] == 2
        assert [first["rows"][0]["customer"]["uid"], second["rows"][0]["customer"]["uid"]] == ["a", "b"]
        assert second["page"]["has_more"] is False


def test_cursor_rejects_query_and_generation_changes(capacity):
    generation(capacity, [projected("a"), projected("b")])
    with unit(capacity):
        first = read_projection.workbook({}, limit=1)
        with pytest.raises(Exception) as bad_filter:
            read_projection.workbook({"entity": "EPC"}, limit=1, cursor=first["page"]["next_cursor"])
        assert bad_filter.value.code == "workbook_cursor_stale"
        capacity.execute(text("update app.projection_current set ordering_version=ordering_version+1 where singleton"))
        with pytest.raises(Exception) as changed:
            read_projection.workbook({}, limit=1, cursor=first["page"]["next_cursor"])
        assert changed.value.code == "workbook_cursor_stale"


def test_today_page_metadata_counts_the_full_filtered_desk(capacity):
    generation(capacity, [projected("a", overdue=100), projected("b", overdue=90, worked=True),
                          projected("c", overdue=80, pending=True), projected("d", entity="EPC")])
    with unit(capacity):
        result = read_projection.today({"entity": "SPV"}, limit=1)
        assert len(result["items"]) == 1
        assert result["meta"]["total"] == 3
        assert result["meta"]["worked_today_count"] == 1
        assert result["meta"]["pending_unworked_count"] == 1
        assert sum(result["meta"]["counts_by_tier"].values()) == 3
        assert sum(result["meta"]["unworked_tier_counts"].values()) == 1
        assert result["meta"]["officer_totals"]["synthetic"] == 3


def test_unpaged_today_preserves_all_items_for_historical_k6(capacity):
    generation(capacity, [projected("a"), projected("b"), projected("c")])
    with unit(capacity):
        result = read_projection.today({})
        assert len(result["items"]) == result["meta"]["total"] == 3
        assert "page" not in result


def test_unrecognized_mutations_keep_global_barrier_and_version_contract():
    assert customer_scope({"path": "/v1/cases/by-customer/synthetic/notes", "method": "POST"}) == "synthetic"
    assert customer_scope({"path": "/v1/cases/by-customer/synthetic/payment-status", "method": "PATCH"}) is None
    assert case_token("synthetic", 3) == "case:synthetic:3"


def test_compatible_fallback_uses_legacy_calculations_without_old_codec(monkeypatch):
    monkeypatch.setenv("VOLT_INDEXED_READS_ENABLED", "false")
    token = CURRENT.set({"capacity": True})
    try:
        assert read_projection.enabled() is False
    finally:
        CURRENT.reset(token)
    monkeypatch.setenv("VOLT_CUSTOMER_SCOPES_ENABLED", "false")
    assert customer_scope({"path": "/v1/cases/by-customer/synthetic/notes", "method": "POST"}) is None


@pytest.mark.parametrize("query,expected", [
    (b"profile=debt_status", True), (b"profile=contract_supplement", True),
    (b"profile=debt_status&profile=full", False), (b"profile=full", False),
    (b"profile=", False), (b"profile=unknown", False), (b"", False),
])
def test_only_owned_preview_profiles_bypass_publication_lock(query, expected):
    assert independent_control({"path": "/v1/imports", "method": "POST", "query_string": query}) is expected
    assert independent_control({"path": "/v1/imports/example:apply", "method": "POST", "query_string": query}) is False


def test_complete_generation_matches_legacy_financial_rows_and_filters(capacity):
    from app import request_context
    from app.routers.today import _legacy_workbook
    with unit(capacity):
        memo = main._VIEW_MEMO.set({})
        reads = request_context.begin_read()
        try:
            read_projection.rebuild(capacity)
            for filters in ({}, {"entity": "SPV"}, {"entity": "EPC"}, {"payment_status": "NPL"},
                            {"position": "unpaid"}, {"sort": "oldest_dpd", "dir": "asc"}):
                old = _legacy_workbook(**filters)
                wire_filters = {key: value for key, value in filters.items() if key not in ("sort", "dir")}
                new = read_projection.workbook(wire_filters, filters.get("sort", "aggregate_overdue"), filters.get("dir", "desc"))
                assert new["rows"] == old["rows"]
                assert new["meta"]["total"] == old["meta"]["total"]
        finally:
            request_context.end_read(reads)
            main._VIEW_MEMO.reset(memo)


def test_shadow_build_failure_never_publishes_partial_generation(capacity, monkeypatch):
    current = generation(capacity, [projected("a")])
    with unit(capacity):
        savepoint = capacity.begin_nested()
        def interrupted(*args, **kwargs):
            raise RuntimeError("synthetic projection write failure")
        monkeypatch.setattr(read_projection, "_save_rows", interrupted)
        with pytest.raises(RuntimeError):
            read_projection.rebuild(capacity)
        savepoint.rollback()
    assert capacity.execute(text("select generation from app.projection_current where singleton")).scalar_one() == current
    assert capacity.execute(text("select count(*) from app.customer_projection where generation=:g"), {"g": current}).scalar_one() == 1


def test_case_etags_allow_other_customer_edits_but_reject_same_case_stale_write(capacity, pg_url, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import db
    from app.production_unit import ProductionUnitMiddleware
    value, first, second = state()
    with unit(capacity):
        business_records.save(capacity, "cases.state", value)
    generation(capacity, [projected(first), projected(second)])
    capacity.execute(text("update app.schema_version set version=3 where singleton"))
    capacity.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setattr(read_projection, "finish_write", lambda conn: None)
    db.reset()
    app = FastAPI()
    @app.get("/v1/cases/by-customer/{uid}")
    def get_case(uid: str):
        return {"customer": {"uid": uid}, "value": cases._store.for_current().cases[uid]["amount"]}
    @app.post("/v1/cases/by-customer/{uid}/notes", status_code=201)
    def update(uid: str):
        row = cases._store.for_current().cases[uid]
        row["amount"] = str(Decimal(row["amount"]) - 1)
        return {"value": row["amount"]}
    app.add_middleware(ProductionUnitMiddleware, enabled=lambda: True)
    try:
        with TestClient(app) as client:
            a = client.get("/v1/cases/by-customer/" + first)
            b = client.get("/v1/cases/by-customer/" + second)
            assert a.status_code == b.status_code == 200
            token_a, token_b = a.headers["x-volt-case-version"], b.headers["x-volt-case-version"]
            assert client.post("/v1/cases/by-customer/" + first + "/notes", headers={"If-Match": token_a}).status_code == 201
            assert client.post("/v1/cases/by-customer/" + second + "/notes", headers={"If-Match": token_b}).status_code == 201
            assert client.post("/v1/cases/by-customer/" + first + "/notes", headers={"If-Match": token_a}).status_code == 409
    finally:
        db.reset()


def test_customer_idempotency_replay_keeps_exact_response_and_commits_once(capacity, pg_url, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import db
    from app.production_unit import ProductionUnitMiddleware
    value, first, second = state()
    with unit(capacity):
        business_records.save(capacity, "cases.state", value)
    generation(capacity, [projected(first), projected(second)])
    capacity.execute(text("update app.schema_version set version=3 where singleton"))
    capacity.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setattr(read_projection, "finish_write", lambda conn: None)
    db.reset()
    app = FastAPI()
    @app.post("/v1/cases/by-customer/{uid}/notes", status_code=201)
    def note(uid: str):
        row = cases._store.for_current().cases[uid]
        row["amount"] = str(Decimal(row["amount"]) - 1)
        return {"value": row["amount"]}
    app.add_middleware(ProductionUnitMiddleware, enabled=lambda: True)
    try:
        with TestClient(app) as client:
            headers = {"If-Match": case_token(first, 0), "Idempotency-Key": "synthetic-reliable-note"}
            one = client.post("/v1/cases/by-customer/" + first + "/notes", headers=headers, json={"text": "Synthetic"})
            replay = client.post("/v1/cases/by-customer/" + first + "/notes", headers=headers, json={"text": "Synthetic"})
            assert one.status_code == replay.status_code == 201
            assert one.content == replay.content
            assert one.headers["x-volt-case-version"] == replay.headers["x-volt-case-version"]
        assert capacity.execute(text("select version from app.customer_version where customer_uid=:u"), {"u": first}).scalar_one() == 1
    finally:
        db.reset()


def test_schema3_fallback_reads_and_mutates_new_codec_with_numeric_tokens(capacity, pg_url, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import db
    from app.production_unit import ProductionUnitMiddleware
    value, first, second = state()
    with unit(capacity):
        business_records.save(capacity, "cases.state", value)
    generation(capacity, [projected(first), projected(second)])
    capacity.execute(text("update app.schema_version set version=3 where singleton"))
    capacity.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("VOLT_INDEXED_READS_ENABLED", "false")
    monkeypatch.setenv("VOLT_CUSTOMER_SCOPES_ENABLED", "false")
    monkeypatch.setattr(read_projection, "finish_write", lambda conn: None)
    db.reset()
    app = FastAPI()
    @app.get("/v1/cases/by-customer/{uid}")
    def get_case(uid: str):
        return cases._store.for_current().cases[uid]
    @app.post("/v1/cases/by-customer/{uid}/notes", status_code=201)
    def note(uid: str):
        row = cases._store.for_current().cases[uid]
        row["note"] = "Synthetic fallback note"
        return row
    app.add_middleware(ProductionUnitMiddleware, enabled=lambda: True)
    try:
        with TestClient(app) as client:
            first_read = client.get("/v1/cases/by-customer/" + first)
            assert first_read.status_code == 200
            assert "x-volt-case-version" not in first_read.headers and "etag" not in first_read.headers
            updated = client.post("/v1/cases/by-customer/" + first + "/notes", headers={
                "If-Match": first_read.headers["x-volt-state-version"]})
            assert updated.status_code == 201
            assert "x-volt-case-version" not in updated.headers
            assert client.get("/v1/cases/by-customer/" + first).json()["note"] == "Synthetic fallback note"
            assert "note" not in client.get("/v1/cases/by-customer/" + second).json()
    finally:
        db.reset()


def test_global_publication_invalidates_every_case_token(capacity, monkeypatch):
    capacity.execute(text("insert into app.customer_version(customer_uid,version) values('a',1),('b',4)"))
    monkeypatch.setattr(read_projection, "rebuild", lambda conn: 1)
    with unit(capacity, mutation=True):
        read_projection.finish_write(capacity)
    assert dict(capacity.execute(text("select customer_uid,version from app.customer_version")).all()) == {"a": 2, "b": 5}


def test_case_note_does_not_invalidate_unrelated_collection_pages(capacity):
    from app import request_context
    with unit(capacity):
        memo = main._VIEW_MEMO.set({})
        reads = request_context.begin_read()
        try:
            read_projection.rebuild(capacity)
        finally:
            request_context.end_read(reads)
            main._VIEW_MEMO.reset(memo)
    before = capacity.execute(text("select ordering_version from app.projection_current where singleton")).scalar_one()
    uid = main.CUSTOMERS[0].uid
    with unit(capacity, uid):
        memo = main._VIEW_MEMO.set({})
        reads = request_context.begin_read()
        try:
            cs = cases.for_current()
            cs.events.append({"kind": "NOTE", "case_uid": cs.cases[uid]["uid"], "text": "Synthetic note"})
            business_records.save(capacity, "cases.state", cs)
            read_projection.refresh_customers(capacity, {uid})
        finally:
            request_context.end_read(reads)
            main._VIEW_MEMO.reset(memo)
    after = capacity.execute(text("select ordering_version from app.projection_current where singleton")).scalar_one()
    assert after == before


def test_scoped_case_preserves_related_contract_payment_status(capacity, monkeypatch):
    from types import SimpleNamespace
    from app import journey
    from app.routers.today import _related_cases
    first = SimpleNamespace(uid="a", customer_no="a", volt_id=None, display_name="Synthetic Person")
    other = SimpleNamespace(uid="b", customer_no="b", volt_id=None, display_name="Synthetic Person")
    row = projected("b")
    row["payment_status"] = "CLOSED"
    generation(capacity, [row])
    current = cases.CaseState()
    current.cases = {"a": {"payment_status": "LATE"}}
    monkeypatch.setattr(journey, "book_customers", lambda: [first, other])
    with unit(capacity, "a"):
        related = _related_cases(first, current)
    assert len(related) == 1 and related[0]["payment_status"] == "CLOSED"

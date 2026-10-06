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
    from app.customer_transactions import plan
    request = {"path": "/v1/cases/by-customer/synthetic/notes", "method": "POST"}
    request['volt_customer_plan'] = plan(request, {'text': 'Synthetic note'})
    assert customer_scope(request) == "synthetic"
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
    (b"profile=debt_status&install=false", True), (b"profile=debt_status&install=true", False),
    (b"profile=debt_status&install=false&install=true", False),
])
def test_only_owned_preview_profiles_bypass_publication_lock(query, expected):
    assert independent_control({"path": "/v1/imports", "method": "POST", "query_string": query}) is expected
    assert independent_control({"path": "/v1/imports:start", "method": "POST", "query_string": query}) is expected
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


def test_shadow_generation_publishes_new_collection_cases_before_scoped_http_reads(capacity, pg_url, monkeypatch):
    from copy import deepcopy
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import db, production_runtime
    from app.production_unit import ProductionUnitMiddleware
    from app.routers.today import case_detail
    from tests.test_enriched_collection_cases import enriched

    with unit(capacity):
        original = cases.for_current()
        old_cases = deepcopy(original.cases)
        business_records.save(capacity, "cases.state", original)
    customer = enriched()
    monkeypatch.setattr(main, "CUSTOMERS", [*main.CUSTOMERS, customer])
    monkeypatch.setattr(main, "BY_CUSTOMER", {**main.BY_CUSTOMER, customer.uid: customer})
    monkeypatch.setattr(main, "BY_CONTRACT", {**main.BY_CONTRACT, customer.contracts[0].uid: (customer, customer.contracts[0])})
    monkeypatch.setattr(production_runtime, "prepare_book", lambda **kwargs: None)
    with unit(capacity):
        assert customer.uid not in cases.for_current().cases
        key = read_projection.rebuild(capacity)
        saved, _ = business_records.load(capacity, "cases.state")
        assert customer.uid in saved.cases
        assert all(saved.cases[uid] == value for uid, value in old_cases.items())
        assert capacity.execute(text("select count(*) from app.customer_projection where generation=:g and customer_uid=:u"),
                                {"g": key, "u": customer.uid}).scalar_one() == 1
    capacity.execute(text("update app.schema_version set version=3 where singleton"))
    capacity.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    db.reset()
    application = FastAPI()
    @application.get("/v1/cases/by-customer/{uid}")
    def customer_detail(uid: str):
        return case_detail(uid)
    application.add_middleware(ProductionUnitMiddleware, enabled=lambda: True)
    try:
        with TestClient(application) as client:
            response = client.get("/v1/cases/by-customer/" + customer.uid)
        assert response.status_code == 200
        payload = response.json()
        assert payload.get("identity_only") is not True
        assert [contract["uid"] for contract in payload["contracts"]] == [customer.contracts[0].uid]
        assert "x-volt-case-version" in response.headers
    finally:
        db.reset()


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


def test_global_rebuild_reads_proof_metadata_once_and_preserves_money_rows(capacity, pg_url, monkeypatch):
    from collections import Counter
    from sqlalchemy import event
    from app import production_runtime, request_context
    from app.routers.today import _legacy_workbook

    # Imported contracts require explicit proof. Missing proof must retain their
    # money rows while excluding them from automatic NPL, with one snapshot read
    # for each complete metadata set rather than one read per eligibility call.
    for customer in main.CUSTOMERS:
        for contract in customer.contracts:
            monkeypatch.setattr(contract, "requires_installation_confirmation", True, raising=False)
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setattr(production_runtime, "prepare_book", lambda **kwargs: None)
    calls = Counter()
    def count_reads(conn, cursor, statement, parameters, context, many):
        normal = " ".join(statement.lower().split())
        for key, marker in (("installations", "select contract_uid,payload from records.installation_confirmation"),
                            ("supplements", "select contract_uid,payload from records.contract_supplement"),
                            ("pipeline", "select payload from app.business_record where store_key='invoice_pipeline.state'")):
            if normal.startswith(marker):
                calls[key] += 1
    event.listen(capacity, "before_cursor_execute", count_reads)
    try:
        with unit(capacity, mutation=True):
            assert request_context.reads() is None and main._VIEW_MEMO.get() is None
            read_projection.rebuild(capacity)
            assert request_context.reads() is None and main._VIEW_MEMO.get() is None
            assert calls == {"installations": 1, "supplements": 1, "pipeline": 1}
            indexed = read_projection.workbook({})
            memo, reads = main._VIEW_MEMO.set({}), request_context.begin_read()
            try:
                legacy = _legacy_workbook()
                assert indexed["rows"] == legacy["rows"]
                assert indexed["meta"]["total"] == legacy["meta"]["total"]
                from app import collection_eligibility
                assessments = [collection_eligibility.for_contract(contract)
                               for customer in main.CUSTOMERS for contract in customer.contracts]
                assert any(value["state"] == "UNCONFIRMED" for value in assessments)
                assert all(value["eligible"] is False for value in assessments)
            finally:
                request_context.end_read(reads)
                main._VIEW_MEMO.reset(memo)
    finally:
        event.remove(capacity, "before_cursor_execute", count_reads)


def test_rebuild_uses_own_source_writes_and_fresh_pending_cash_without_replacing_parent_cache(capacity, pg_url, monkeypatch):
    from app import payment_claims, production_runtime, request_context
    from app.routers.today import _legacy_workbook
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setattr(production_runtime, "prepare_book", lambda **kwargs: None)
    with unit(capacity, mutation=True):
        read_projection.rebuild(capacity)
        before = read_projection.workbook({})
        row = next(row for row in before["rows"] if row.get("case", {}).get("payment_status") == "LATE")
        uid, outstanding = row["customer"]["uid"], row["aggregate_outstanding"]
        memo, reads = main._VIEW_MEMO.set({"parent": "unchanged"}), request_context.begin_read()
        parent_reads = request_context.reads()
        try:
            assert payment_claims.list_all("PENDING") == []
            cached_parent = dict(parent_reads)
            capacity.execute(text("insert into records.payment_claim "
                "(uid,customer_uid,amount,paid_on,created_by,created_role,idempotency_key,state) "
                "values('rebuild-pending',:u,1,'2026-10-23','synthetic','OWNER','rebuild-cash','PENDING')"), {"u": uid})
            epoch = capacity.execute(text("insert into app.data_epoch(kind) values('synthetic-rebuild') returning id")).scalar_one()
            key = read_projection.rebuild(capacity)
            assert request_context.reads() is parent_reads and parent_reads == cached_parent
            assert main._VIEW_MEMO.get() == {"parent": "unchanged"}
            assert capacity.execute(text("select source_epoch from app.projection_generation where id=:g"), {"g": key}).scalar_one() == epoch
            published = read_projection.workbook({})
            pending = next(row for row in published["rows"] if row["customer"]["uid"] == uid)
            assert pending["case"]["payment_status"] == "PENDING"
            assert pending["case"]["payment_pending_amount"] == "1.00"
            assert pending["aggregate_outstanding"] == outstanding
            # A second source change in the same global command needs another
            # fresh derivation, even when the claim cache version did not change.
            capacity.execute(text("update records.payment_claim set state='CANCELLED' where uid='rebuild-pending'"))
            read_projection.rebuild(capacity)
            cleared = read_projection.workbook({})
            restored = next(row for row in cleared["rows"] if row["customer"]["uid"] == uid)
            assert restored["case"]["payment_status"] == "LATE"
            assert restored["aggregate_outstanding"] == outstanding
            fresh_memo, fresh_reads = main._VIEW_MEMO.set({}), request_context.begin_read()
            try:
                assert cleared["rows"] == _legacy_workbook()["rows"]
            finally:
                request_context.end_read(fresh_reads)
                main._VIEW_MEMO.reset(fresh_memo)
        finally:
            request_context.end_read(reads)
            main._VIEW_MEMO.reset(memo)


def test_failed_rebuild_restores_parent_read_caches(capacity, monkeypatch):
    from app import request_context
    from app.production_unit import CURRENT
    with unit(capacity, mutation=True):
        memo, reads = main._VIEW_MEMO.set({"parent": "unchanged"}), request_context.begin_read()
        parent_reads = request_context.reads()
        parent_reads["parent"] = "unchanged"
        try:
            def interrupted(*args, **kwargs):
                assert request_context.reads() is not parent_reads
                assert main._VIEW_MEMO.get() != {"parent": "unchanged"}
                raise RuntimeError("synthetic projection derivation failure")
            monkeypatch.setattr(read_projection, "_save_rows", interrupted)
            with pytest.raises(RuntimeError):
                read_projection.rebuild(capacity)
            assert request_context.reads() is parent_reads and parent_reads == {"parent": "unchanged"}
            assert main._VIEW_MEMO.get() == {"parent": "unchanged"}
            assert not CURRENT.get().get("seeding")
        finally:
            request_context.end_read(reads)
            main._VIEW_MEMO.reset(memo)


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
            assert client.post("/v1/cases/by-customer/" + first + "/notes", headers={"If-Match": token_a}, json={'text': 'Synthetic A'}).status_code == 201
            assert client.post("/v1/cases/by-customer/" + second + "/notes", headers={"If-Match": token_b}, json={'text': 'Synthetic B'}).status_code == 201
            assert client.post("/v1/cases/by-customer/" + first + "/notes", headers={"If-Match": token_a}, json={'text': 'Stale A'}).status_code == 409
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


@pytest.mark.parametrize("entity", ["EPC", "SPV"])
def test_workbook_entity_filter_is_preserved_by_both_csv_exports(entity):
    import csv
    import io
    from fastapi.testclient import TestClient
    with TestClient(main.app) as client:
        client.cookies.set("volt_session", "shared")
        expected = client.get("/v1/workbook", params={"entity": entity}).json()
        wanted = {row["customer"]["customer_no"] for row in expected["rows"]}
        responses = [client.get("/v1/workbook:export", params={"entity": entity}),
                     client.post("/v1/workbook:export", params={"entity": entity},
                                 json={"reason": "Synthetic entity-filter validation"})]
        for response in responses:
            assert response.status_code == 200
            body = "\n".join(line for line in response.text.lstrip("\ufeff").splitlines() if not line.startswith("#"))
            rows = list(csv.DictReader(io.StringIO(body)))
            assert {row["customer_no"] for row in rows} == wanted
            assert all(row["entity"] == entity for row in rows)
        assert "entity=" + entity in responses[1].text


def test_governed_export_rejects_nested_object_as_reason():
    from fastapi.testclient import TestClient
    with TestClient(main.app) as client:
        response = client.post("/v1/workbook:export", json={"reason": {"reason": "Synthetic audit reason"}})
    assert response.status_code == 422


def test_today_arrears_sort_is_global_across_pages_and_keeps_tier_priority(capacity):
    import json
    rows = [projected("a", overdue=10, tier="PTP_DUE_TODAY"),
            projected("b", overdue=100, tier="PTP_DUE_TODAY"),
            projected("c", overdue=1000, tier="NEXT_ACTION_DUE")]
    for row, rank, dpd in zip(rows, (1, 1, 2), (100, 1, 200)):
        row.update(tier_rank=rank, dpd=dpd)
        payload = json.loads(row["today"])
        payload.update(tier_rank=rank, oldest_dpd=dpd)
        row["today"] = json.dumps(payload)
    generation(capacity, rows)
    with unit(capacity):
        priority = read_projection.today({}, sort="priority")
        assert [row["customer"]["uid"] for row in priority["items"]] == ["a", "b", "c"]
        first = read_projection.today({}, limit=1, sort="arrears")
        second = read_projection.today({}, limit=1, sort="arrears", cursor=first["page"]["next_cursor"])
        third = read_projection.today({}, limit=1, sort="arrears", cursor=second["page"]["next_cursor"])
        assert [result["items"][0]["customer"]["uid"] for result in (first, second, third)] == ["b", "a", "c"]
        assert first["meta"]["total"] == second["meta"]["total"] == third["meta"]["total"] == 3
        assert first["meta"]["next_up"] == "b"
        with pytest.raises(Exception) as changed_sort:
            read_projection.today({}, limit=1, sort="priority", cursor=first["page"]["next_cursor"])
        assert changed_sort.value.code == "today_cursor_stale"


def test_today_board_counts_cover_unloaded_filtered_cards(capacity):
    import json
    rows = [projected("a", entity="SPV"), projected("b", entity="SPV"), projected("c", entity="EPC")]
    for row, column in zip(rows, ("col_01H8X", "col_01H8Y", "col_01H8Y")):
        payload = json.loads(row["today"])
        payload["board_column_id"] = column
        row["today"] = json.dumps(payload)
    generation(capacity, rows)
    with unit(capacity):
        result = read_projection.today({"entity": "SPV"}, limit=1)
        assert len(result["items"]) == 1
        assert result["meta"]["board_counts"]["col_01H8X"] == 1
        assert result["meta"]["board_counts"]["col_01H8Y"] == 1
        assert sum(result["meta"]["board_counts"].values()) == result["meta"]["total"] == 2


def test_legacy_today_arrears_order_and_board_counts_match_entire_queue():
    from fastapi.testclient import TestClient
    with TestClient(main.app) as client:
        client.cookies.set("volt_session", "shared")
        priority = client.get("/v1/today", params={"entity": "SPV"}).json()
        arrears = client.get("/v1/today", params={"entity": "SPV", "sort": "arrears"}).json()
        expected = sorted(priority["items"], key=lambda row: (row["tier_rank"], -Decimal(row["aggregate_overdue"]),
            -(row["oldest_dpd"] or 0), row["customer"]["display_name"], row["customer"]["uid"]))
        assert [row["customer"]["uid"] for row in arrears["items"]] == [row["customer"]["uid"] for row in expected]
        assert arrears["meta"]["total"] == priority["meta"]["total"]
        assert sum(arrears["meta"]["board_counts"].values()) == arrears["meta"]["total"]
        assert client.get("/v1/today", params={"sort": "unknown"}).status_code == 422

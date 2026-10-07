"""Dirty writes retain list identities, multiplicity and other customers."""
from copy import deepcopy

import pytest
from sqlalchemy import event, text

from app import business_records, cases, main, migrate
from tests.test_scoped_projection_refresh import request_unit


@pytest.fixture
def stored(pg_conn):
    migrate.apply(pg_conn)
    value = cases.CaseState()
    first, second = main.CUSTOMERS[:2]
    value.cases = {first.uid:{"uid":"TEST-first-case", "customer_uid":first.uid, "value":"1"},
                   second.uid:{"uid":"TEST-other-case", "customer_uid":second.uid, "value":"2"}}
    value.events = [{"uid":"TEST-a", "customer_uid":first.uid, "text":"TEST first"},
                    {"uid":"TEST-b", "customer_uid":first.uid, "text":"TEST second"},
                    {"uid":"TEST-c", "customer_uid":first.uid, "text":"TEST third"},
                    {"uid":"TEST-other", "customer_uid":second.uid, "text":"TEST unrelated"}]
    with request_unit(pg_conn):
        business_records.save(pg_conn, "cases.state", value)
    pg_conn.commit()
    return pg_conn, first.uid, second.uid


def persisted(conn):
    return {row.id: business_records.decode(row.payload) for row in conn.execute(text(
        "select id,payload from app.business_list_record where store_key='cases.state' and attribute='events' order by id"
    ))}


def test_repeated_save_is_noop_and_never_duplicates_new_rows(stored):
    conn, uid, other = stored
    with request_unit(conn, uid, mutation=True) as unit:
        value, _ = business_records.load(conn, "cases.state")
        root_before = conn.execute(text("select payload,version from app.business_record where store_key='cases.state' and record_key='@root'")).one()
        value.cases[uid]["value"] = "changed"
        value.events.append({"uid":"TEST-new", "customer_uid":uid, "text":"TEST new"})
        assert business_records.save(conn, "cases.state", value)
        after = persisted(conn)
        versions = dict(conn.execute(text("select record_key,version from app.business_record where store_key='cases.state'")).all())
        assert business_records.save(conn, "cases.state", value) is False
        assert persisted(conn) == after
        assert dict(conn.execute(text("select record_key,version from app.business_record where store_key='cases.state'")).all()) == versions
        assert conn.execute(text("select payload,version from app.business_record where store_key='cases.state' and record_key='@root'")).one() == root_before
        assert len(value.events.identities) == len(value.events)
        assert set(value.events.identities) <= set(after)
        assert sum(row.get("customer_uid") == other for row in after.values()) == 1
        assert unit["record_baselines"]["cases.state"]


@pytest.mark.parametrize("change", ["pop", "insert", "filter", "reverse", "rebuild"])
def test_list_mutation_retains_loaded_row_ids_and_unrelated_customer(stored, change):
    conn, uid, other = stored
    before = persisted(conn)
    old_ids = {row["uid"]: identity for identity,row in before.items()}
    with request_unit(conn, uid, mutation=True):
        value, _ = business_records.load(conn, "cases.state")
        if change == "pop":
            value.events.pop(1)
        elif change == "insert":
            value.events.insert(0, {"uid":"TEST-inserted", "customer_uid":uid, "text":"TEST insertion"})
        elif change == "filter":
            value.events = [row for row in value.events if row["uid"] != "TEST-b"]
        elif change == "reverse":
            value.events.reverse()
        else:
            value.events = deepcopy(list(value.events))
            value.events[0]["text"] = "TEST replaced body with same logical uid"
        business_records.save(conn, "cases.state", value)
        assert business_records.save(conn, "cases.state", value) is False
        after = persisted(conn)
        for identity,row in after.items():
            if row["uid"] in old_ids:
                assert identity == old_ids[row["uid"]]
        assert after[old_ids["TEST-other"]] == before[old_ids["TEST-other"]]
        if change in ("pop", "filter"):
            assert old_ids["TEST-b"] not in after
        # The database's established durable-id chronology is unchanged by a
        # caller's temporary reversal; retained rows never overwrite neighbours.
        assert list(after) == sorted(after)


def test_equal_new_observations_do_not_steal_retained_id_or_lose_multiplicity(stored):
    conn, uid, _other = stored
    with request_unit(conn, uid, mutation=True):
        value, _ = business_records.load(conn, "cases.state")
        retained = value.events[0]
        retained_id = value.events.identities[0]
        value.events.insert(0, deepcopy(retained))
        value.events.append(deepcopy(retained))
        assert business_records.save(conn, "cases.state", value)
        identical = [identity for identity,row in persisted(conn).items() if row == retained]
        assert len(identical) == 3 and retained_id in identical
        assert len(set(value.events.identities)) == len(value.events)
        assert value.events.identities[1] == retained_id
        assert business_records.save(conn, "cases.state", value) is False


def test_failed_save_publishes_no_ids_or_baselines_and_retry_is_complete(stored):
    conn, uid, _other = stored
    before = persisted(conn)
    with request_unit(conn, uid, mutation=True) as unit:
        value, _ = business_records.load(conn, "cases.state")
        ids = list(value.events.identities)
        baselines = deepcopy(unit["record_baselines"])
        owners = deepcopy(unit["owner_baselines"])
        value.cases[uid]["value"] = "TEST failed mapping update"
        value.events.append({"uid":"TEST-new", "customer_uid":uid, "text":"TEST first insertion"})
        value.today_items.append({"uid":"TEST-new-wait", "customer_uid":uid, "done":False})
        point = conn.begin_nested()
        inserts = []
        def fail_later(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.startswith("insert into app.business_list_record"):
                inserts.append(statement)
                if len(inserts) == 2:
                    raise RuntimeError("TEST second list write refused")
        event.listen(conn.engine, "before_cursor_execute", fail_later)
        try:
            with pytest.raises(RuntimeError, match="TEST second list"):
                business_records.save(conn, "cases.state", value)
        finally:
            event.remove(conn.engine, "before_cursor_execute", fail_later)
            point.rollback()
        assert value.events.identities == ids
        assert unit["record_baselines"] == baselines
        assert unit["owner_baselines"] == owners
        assert persisted(conn) == before
        assert business_records.save(conn, "cases.state", value)
        assert business_records.save(conn, "cases.state", value) is False
        assert sum(row["uid"] == "TEST-new" for row in persisted(conn).values()) == 1
    conn.rollback()
    assert persisted(conn) == before
    # Production discards the Unit and restored objects after an outer rollback;
    # a fresh request obtains the original committed mappings and identities.
    with request_unit(conn, uid):
        restored, _ = business_records.load(conn, "cases.state")
        assert restored.cases[uid]["value"] == "1"
        assert "TEST-new" not in {row["uid"] for row in restored.events}

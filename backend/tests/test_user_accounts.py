"""B10a (Feedback Round 1 / WP10, design F13/F14): records.user_account merged over the
AUTH_ALLOWLIST seed — the store alone, no HTTP.

Synthetic addresses only (PDPA ruling I4 of Round A): example.co.th, never a real person.
"""
import threading
import time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, OperationalError, ProgrammingError

from app import db, errors, migrate, user_accounts

SEED = {"boss@example.co.th": {"role": "OWNER", "officer": "owner"},
        "lead@example.co.th": {"role": "MANAGER", "officer": "settasak"},
        "thip@example.co.th": {"role": "OFFICER", "officer": "thip"}}
# B10b fix round 1 (M3): invite() takes each registry officer's role, not only the uids.
OFFICERS = {"owner": "OWNER", "settasak": "MANAGER", "thip": "OFFICER", "nantapol": "OFFICER", "ops": "OPS"}


@pytest.fixture(autouse=True)
def _clean():
    user_accounts.reset()
    yield
    user_accounts.reset()


def _problem(call):
    with pytest.raises(errors.Problem) as caught:
        call()
    return caught.value


def test_with_no_rows_the_seed_decides():
    assert user_accounts.allow_entry("thip@example.co.th", SEED) == ({"role": "OFFICER", "officer": "thip"}, "ACTIVE")
    assert user_accounts.allow_entry("stranger@example.co.th", SEED) == (None, None)


def test_an_invitation_adds_a_person_the_seed_never_named():
    user = user_accounts.invite(SEED, {"email": " New.Person@Example.co.th ", "role": "officer", "officer": "nantapol"},
                                "settasak", "MANAGER", OFFICERS)
    assert user["email"] == "new.person@example.co.th" and user["role"] == "OFFICER" and user["state"] == "ACTIVE"
    assert user["seeded"] is False and user["invited_by"] == "settasak" and user["invited_at"]
    assert user_accounts.allow_entry("new.person@example.co.th", SEED) == ({"role": "OFFICER", "officer": "nantapol"}, "ACTIVE")


def test_an_invitation_is_checked_field_by_field():
    problem = _problem(lambda: user_accounts.invite(SEED, {"email": "nope", "role": "KING", "officer": "ghost"},
                                                    "settasak", "MANAGER", OFFICERS))
    assert problem.status == 422
    assert [e["code"] for e in problem.errors] == ["email_invalid", "role_unknown", "officer_unknown"]
    assert all(e["message_th"] for e in problem.errors)


def test_nobody_invites_above_their_own_role():
    problem = _problem(lambda: user_accounts.invite(SEED, {"email": "x@example.co.th", "role": "OWNER", "officer": "owner"},
                                                    "settasak", "MANAGER", OFFICERS))
    assert (problem.status, problem.code) == (403, "role_above_actor")
    # an equal role is not above
    assert user_accounts.invite(SEED, {"email": "y@example.co.th", "role": "MANAGER", "officer": "settasak"},
                                "settasak", "MANAGER", OFFICERS)["role"] == "MANAGER"


def test_an_address_that_may_already_sign_in_is_not_invited_twice():
    problem = _problem(lambda: user_accounts.invite(SEED, {"email": "thip@example.co.th", "role": "OFFICER", "officer": "thip"},
                                                    "owner", "OWNER", OFFICERS))
    assert (problem.status, problem.code) == (409, "user_exists")
    assert "thip@" not in problem.detail and "thip@" not in problem.message_th


def test_a_disabled_row_wins_over_the_seed_and_an_invitation_brings_it_back():
    listed = {u["email"]: u for u in user_accounts.listed(SEED, None)}
    seed_uid = listed["thip@example.co.th"]["uid"]
    assert seed_uid.startswith("env-") and "thip" not in seed_uid
    user = user_accounts.disable(SEED, seed_uid, "settasak", "MANAGER", "lead@example.co.th")
    assert user["state"] == "DISABLED" and user["seeded"] is True and user["disabled_by"] == "settasak"
    assert user_accounts.allow_entry("thip@example.co.th", SEED) == (None, "DISABLED")
    again = user_accounts.invite(SEED, {"email": "thip@example.co.th", "role": "SUPERVISOR", "officer": "thip"},
                                 "settasak", "MANAGER", OFFICERS)
    assert again["state"] == "ACTIVE" and again["role"] == "SUPERVISOR"
    assert user_accounts.allow_entry("thip@example.co.th", SEED)[0]["role"] == "SUPERVISOR"


def test_the_seed_cannot_be_deleted_only_disabled():
    assert not [name for name in dir(user_accounts) if "delete" in name.lower() or "remove" in name.lower()]
    uid = next(u["uid"] for u in user_accounts.listed(SEED, None) if u["email"] == "boss@example.co.th")
    user_accounts.disable(SEED, uid, "owner", "OWNER", "lead@example.co.th")
    user_accounts.reset()                               # a restart with no database
    assert "boss@example.co.th" in {u["email"] for u in user_accounts.listed(SEED, None)}


def test_a_manager_cannot_disable_an_owner_or_themselves():
    rows = {u["email"]: u["uid"] for u in user_accounts.listed(SEED, None)}
    problem = _problem(lambda: user_accounts.disable(SEED, rows["boss@example.co.th"], "settasak", "MANAGER", "lead@example.co.th"))
    assert (problem.status, problem.code) == (403, "role_above_actor")
    problem = _problem(lambda: user_accounts.disable(SEED, rows["lead@example.co.th"], "settasak", "MANAGER", "lead@example.co.th"))
    assert (problem.status, problem.code) == (409, "cannot_disable_self")
    problem = _problem(lambda: user_accounts.disable(SEED, rows["boss@example.co.th"], "owner", "OWNER", "boss@example.co.th"))
    assert problem.code == "cannot_disable_self"


def test_disabling_twice_and_an_unknown_uid_are_refused():
    uid = next(u["uid"] for u in user_accounts.listed(SEED, None) if u["email"] == "thip@example.co.th")
    user_accounts.disable(SEED, uid, "owner", "OWNER", "boss@example.co.th")
    assert _problem(lambda: user_accounts.disable(SEED, uid, "owner", "OWNER", "boss@example.co.th")).code == "user_already_disabled"
    assert _problem(lambda: user_accounts.disable(SEED, "env-0000000000000000", "owner", "OWNER", "x")).status == 404
    assert _problem(lambda: user_accounts.disable(SEED, "999", "owner", "OWNER", "x")).status == 404


def test_a_session_ends_when_its_person_is_disabled_dropped_or_re_invited_differently():
    session = {"sub": "thip@example.co.th", "kind": "GOOGLE", "role": "OFFICER", "officer": "thip"}
    assert user_accounts.session_allowed(session, SEED) is True
    assert user_accounts.session_allowed(session, {}) is False                 # dropped from the seed
    uid = next(u["uid"] for u in user_accounts.listed(SEED, None) if u["email"] == "thip@example.co.th")
    user_accounts.disable(SEED, uid, "owner", "OWNER", "boss@example.co.th")
    assert user_accounts.session_allowed(session, SEED) is False
    user_accounts.invite(SEED, {"email": "thip@example.co.th", "role": "SUPERVISOR", "officer": "thip"}, "owner", "OWNER", OFFICERS)
    assert user_accounts.session_allowed(session, SEED) is False               # role changed since sign-in
    assert user_accounts.session_allowed({"sub": "manager.test", "kind": "TEST", "role": "MANAGER"}, {}) is True


def test_the_session_check_reads_a_cache_that_expires(monkeypatch):
    session = {"sub": "thip@example.co.th", "kind": "GOOGLE", "role": "OFFICER", "officer": "thip"}
    clock = [1000.0]
    monkeypatch.setattr(user_accounts, "_clock", lambda: clock[0])
    assert user_accounts.session_allowed(session, SEED) is True
    reads = []
    real = user_accounts._read_rows
    monkeypatch.setattr(user_accounts, "_read_rows", lambda: reads.append(1) or real())
    user_accounts.session_allowed(session, SEED)
    assert reads == []
    clock[0] += user_accounts.CACHE_SECONDS + 1
    user_accounts.session_allowed(session, SEED)
    assert reads == [1]


def test_a_display_name_is_set_cleared_and_checked():
    google = {"sub": "thip@example.co.th", "kind": "GOOGLE"}
    test = {"sub": "manager.test", "kind": "TEST"}
    assert user_accounts.display_name_for(google) == {"display_name": "thip", "display_name_source": "EMAIL",
                                                      "display_name_fallback": "thip"}
    assert user_accounts.display_name_for(test)["display_name_source"] == "USERNAME"
    assert user_accounts.set_profile(google, {"display_name": "  ทิพย์   อักษร "}) == "ทิพย์ อักษร"
    assert user_accounts.display_name_for(google) == {"display_name": "ทิพย์ อักษร", "display_name_source": "PROFILE",
                                                      "display_name_fallback": "thip"}
    user_accounts.set_profile(test, {"display_name": "Somchai"})
    assert user_accounts.display_name_for(test)["display_name"] == "Somchai"
    assert user_accounts.set_profile(google, {"display_name": ""}) is None
    assert user_accounts.display_name_for(google)["display_name"] == "thip"
    for bad in ("x" * 61, "a\u200bb", 42):
        assert _problem(lambda: user_accounts.set_profile(google, {"display_name": bad})).errors[0]["code"] == "display_name_invalid"
    assert _problem(lambda: user_accounts.set_profile(google, {"display_name": "x", "role": "OWNER"})).errors[0]["code"] == "not_editable"


def test_a_display_name_row_never_grants_sign_in():
    stranger = {"sub": "stranger@example.co.th", "kind": "GOOGLE"}
    user_accounts.set_profile(stranger, {"display_name": "Nobody"})
    assert user_accounts.allow_entry("stranger@example.co.th", SEED) == (None, None)
    assert "stranger@example.co.th" not in {u["email"] for u in user_accounts.listed(SEED, None)}


def test_a_configured_database_that_does_not_answer_refuses(monkeypatch):
    monkeypatch.setattr(db, "configured", lambda: True)

    def down():
        raise db.DatabaseUnreachable("no route")
    monkeypatch.setattr(db, "connect", down)
    problem = _problem(lambda: user_accounts.allow_entry("thip@example.co.th", SEED))
    assert (problem.status, problem.code, problem.retryable) == (503, "user_list_unreachable", True)


def test_the_rows_are_durable_in_postgres(pg_conn, monkeypatch):
    migrate.apply(pg_conn)
    pg_conn.commit()
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pg_conn)
    monkeypatch.setattr(pg_conn, "close", lambda: None)
    try:
        user_accounts.invite(SEED, {"email": "new@example.co.th", "role": "OFFICER", "officer": "nantapol"},
                             "settasak", "MANAGER", OFFICERS)
        uid = next(u["uid"] for u in user_accounts.listed(SEED, None) if u["email"] == "thip@example.co.th")
        user_accounts.disable(SEED, uid, "settasak", "MANAGER", "lead@example.co.th")
        user_accounts.set_profile({"sub": "manager.test", "kind": "TEST"}, {"display_name": "Somchai"})
        user_accounts.forget()
        rows = pg_conn.execute(text("select kind, email, username, role, disabled_at is not null as off, display_name "
                                    "from records.user_account order by id")).all()
        pg_conn.commit()
        # B10b controller ruling (M1 edge; this plan's own test, adapted — not a pinned
        # edit): disable() records on the row the role it saw, the seed's for seed-only
        # thip, so thip's row role None → "OFFICER".
        assert [tuple(r) for r in rows] == [("GOOGLE", "new@example.co.th", None, "OFFICER", False, None),
                                            ("GOOGLE", "thip@example.co.th", None, "OFFICER", True, None),
                                            ("TEST", None, "manager.test", None, False, "Somchai")]
        assert user_accounts.allow_entry("thip@example.co.th", SEED) == (None, "DISABLED")
        again = user_accounts.invite(SEED, {"email": "thip@example.co.th", "role": "OFFICER", "officer": "thip"},
                                     "settasak", "MANAGER", OFFICERS)
        assert again["state"] == "ACTIVE"
        assert _problem(lambda: user_accounts.invite(SEED, {"email": "new@example.co.th", "role": "OFFICER",
                                                           "officer": "nantapol"}, "settasak", "MANAGER", OFFICERS)).code == "user_exists"
    finally:
        pg_conn.rollback()
        pg_conn.execute(text("delete from records.user_account"))
        pg_conn.commit()


# --- Fix round 1 (security review, 2026-09-15): I1, I2, I3, M1-M5 ---------------------

def _leaks_nothing(problem):
    """No e-mail anywhere in the Problem, and no driver exception chained to it."""
    dump = repr(vars(problem)) + str(problem)
    assert "example.co.th" not in dump, dump
    assert problem.__cause__ is None and problem.__suppress_context__ is True


def _store_on(conn, monkeypatch):
    migrate.apply(conn)
    conn.commit()
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: conn)
    monkeypatch.setattr(conn, "close", lambda: None)


def _wipe(conn):
    conn.rollback()
    conn.execute(text("delete from records.user_account"))
    conn.commit()


def test_an_email_look_alike_is_refused_not_admitted_as_a_twin():
    """I1: ZWSP, a BOM, an RLO override, a NUL byte and a Cyrillic domain look-alike
    each used to be admitted as a distinct ACTIVE row next to the real thip@. U+2C2F and
    U+A7C0 are two of the code points Python's lower() and Postgres's lower() disagree
    on (a false user_exists); ASCII-only removes the disagreement."""
    look_alikes = [
        "thip\u200b@example.co.th",     # ZWSP inside the local part
        "\ufeffthip@example.co.th",     # BOM prefix
        "a\u202e@example.co.th",        # RLO override
        "x\x00y@example.co.th",         # NUL byte
        "thip@ex\u0430mple.co.th",      # Cyrillic a look-alike domain
        "a\u2c2fb@example.co.th",       # lower() disagreement
        "a\ua7c0b@example.co.th",       # lower() disagreement
    ]
    for email in look_alikes:
        problem = _problem(lambda e=email: user_accounts.invite(
            SEED, {"email": e, "role": "OFFICER", "officer": "thip"}, "settasak", "MANAGER", OFFICERS))
        assert (problem.status, problem.code) == (422, "validation_failed"), ascii(email)
        assert [e["code"] for e in problem.errors] == ["email_invalid"], ascii(email)
        assert problem.errors[0]["message_th"] == "อีเมลไม่ถูกต้อง"
        assert "example" not in repr(vars(problem)), ascii(email)          # nothing echoed
    # none of the look-alikes were admitted — the real thip is untouched
    assert user_accounts.allow_entry("thip@example.co.th", SEED) == ({"role": "OFFICER", "officer": "thip"}, "ACTIVE")
    assert {u["email"] for u in user_accounts.listed(SEED, None)} == set(SEED)
    # the ruling's pattern still admits an ordinary address with + and '
    user = user_accounts.invite(SEED, {"email": "O'Brien+debt@Mail.Example.co.th", "role": "OFFICER", "officer": "thip"},
                                "settasak", "MANAGER", OFFICERS)
    assert user["email"] == "o'brien+debt@mail.example.co.th"


def test_a_concurrent_forget_never_crashes_a_cached_session_check():
    """I2: _rows() read "at" and "rows" as two separate dict accesses, so a concurrent
    forget() landing between them raised TypeError (None - float) or AttributeError
    (None.get). A one-microsecond switch interval makes the interleaving certain within
    the second this runs; the fix (one snapshot under a lock) makes it impossible."""
    import sys

    session = {"sub": "thip@example.co.th", "kind": "GOOGLE", "role": "OFFICER", "officer": "thip"}
    seed = {"thip@example.co.th": {"role": "OFFICER", "officer": "thip"}}
    user_accounts.session_allowed(session, seed)          # populate the cache once
    crashes = []
    stop = time.time() + 1.0

    def checker():
        while time.time() < stop and len(crashes) < 50:
            try:
                user_accounts.session_allowed(session, seed)
            except Exception as exc:                      # noqa: BLE001 — counting every kind
                crashes.append(type(exc).__name__)

    def writer():
        while time.time() < stop and len(crashes) < 50:
            user_accounts.forget()

    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        # daemon + a join timeout (B10b ruling): a future deadlock fails this test
        # instead of hanging the suite. The threads stop on their own after 1 s.
        threads = ([threading.Thread(target=checker, daemon=True) for _ in range(2)]
                   + [threading.Thread(target=writer, daemon=True)])
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
    finally:
        sys.setswitchinterval(interval)
    assert not [t for t in threads if t.is_alive()], "a session check or forget() never returned (deadlock?)"
    assert crashes == []


def test_a_read_that_overlaps_a_write_never_puts_the_old_rows_back_in_the_cache(monkeypatch):
    """I2: a slow read that began before a disable and finished after it used to be
    stored as the cache, so the disabled person's session stayed allowed for
    CACHE_SECONDS. The read still answers its own caller; it is never saved."""
    session = {"sub": "thip@example.co.th", "kind": "GOOGLE", "role": "OFFICER", "officer": "thip"}
    uid = next(u["uid"] for u in user_accounts.listed(SEED, None) if u["email"] == "thip@example.co.th")
    user_accounts.forget()
    real = user_accounts._read_rows

    def read_then_a_disable_lands():
        before = real()                                     # the read sees thip ACTIVE
        monkeypatch.setattr(user_accounts, "_read_rows", real)
        user_accounts.disable(SEED, uid, "owner", "OWNER", "boss@example.co.th")
        return before
    monkeypatch.setattr(user_accounts, "_read_rows", read_then_a_disable_lands)
    assert user_accounts.session_allowed(session, SEED) is True      # the in-flight read's own answer
    assert user_accounts.session_allowed(session, SEED) is False     # the cache never kept it


def test_a_real_connection_killed_mid_query_is_the_retryable_503(pg_conn, pg_url, monkeypatch):
    """I3: a connection that opened and then died (terminated by the server) raised a
    raw OperationalError past the 503. Now it is the same retryable refusal as a
    connection that never opened."""
    from sqlalchemy import create_engine

    _store_on(pg_conn, monkeypatch)
    engine = create_engine(pg_url, future=True)
    victim = engine.connect()
    try:
        pid = victim.execute(text("select pg_backend_pid()")).scalar()
        victim.commit()
        assert pg_conn.execute(text("select pg_terminate_backend(:p, 5000)"), {"p": pid}).scalar() is True
        pg_conn.commit()
        monkeypatch.setattr(db, "connect", lambda: victim)
        problem = _problem(lambda: user_accounts.allow_entry("thip@example.co.th", SEED))
        assert (problem.status, problem.code, problem.retryable) == (503, "user_list_unreachable", True)
        _leaks_nothing(problem)
    finally:
        victim.close()
        engine.dispose()


def test_a_lost_connection_mid_query_is_the_same_retryable_503(pg_conn, monkeypatch):
    """I3: an OperationalError raised AFTER the connection opens must be the same 503
    as a connection that never opened."""
    _store_on(pg_conn, monkeypatch)

    def boom(*a, **k):
        raise OperationalError("select 1", {"e": "thip@example.co.th"},
                               Exception("server closed the connection unexpectedly"))
    monkeypatch.setattr(pg_conn, "execute", boom)
    problem = _problem(lambda: user_accounts.allow_entry("thip@example.co.th", SEED))
    assert (problem.status, problem.code, problem.retryable) == (503, "user_list_unreachable", True)
    _leaks_nothing(problem)


def test_a_forced_data_or_programming_error_never_leaks_an_email(pg_conn, monkeypatch):
    """I3: DataError and ProgrammingError are not connection loss — each must still
    become an opaque Problem, never the driver's text (which quotes the e-mail)."""
    _store_on(pg_conn, monkeypatch)
    for exc_cls in (DataError, ProgrammingError):
        def boom(*a, _exc=exc_cls, **k):
            raise _exc("select ... where email = %(e)s", {"e": "thip@example.co.th"},
                       Exception("invalid input syntax: thip@example.co.th"))
        monkeypatch.setattr(pg_conn, "execute", boom)
        problem = _problem(lambda: user_accounts.allow_entry("thip@example.co.th", SEED))
        assert (problem.status, problem.code) == (500, "internal_error")
        _leaks_nothing(problem)


def test_real_driver_errors_on_a_write_are_problems_without_the_email(pg_conn, monkeypatch):
    """I3, against Postgres itself: a DataError (a NUL in a bound e-mail), a
    ProgrammingError (a write to a table that is not there) and an IntegrityError in
    disable and in set_profile (the e-mail CHECK) each used to escape as the raw driver
    exception, whose text carries the bound e-mail."""
    _store_on(pg_conn, monkeypatch)
    try:
        # DataError: psycopg refuses a NUL inside a bound parameter
        problem = _problem(lambda: user_accounts.set_profile({"sub": "thip@example.co.th\x00", "kind": "GOOGLE"},
                                                             {"display_name": "Thip"}))
        assert (problem.status, problem.code) == (500, "internal_error")
        _leaks_nothing(problem)
        # IntegrityError in set_profile and in disable: an address Postgres would not
        # lower-case to itself breaks user_account_key_check
        problem = _problem(lambda: user_accounts.set_profile({"sub": "Thip@example.co.th", "kind": "GOOGLE"},
                                                             {"display_name": "Thip"}))
        assert (problem.status, problem.code) == (500, "internal_error")
        _leaks_nothing(problem)
        odd_seed = {"Thip@example.co.th": {"role": "OFFICER", "officer": "thip"}}
        uid = user_accounts.listed(odd_seed, None)[0]["uid"]
        problem = _problem(lambda: user_accounts.disable(odd_seed, uid, "owner", "OWNER", "boss@example.co.th"))
        assert (problem.status, problem.code) == (500, "internal_error")
        _leaks_nothing(problem)
        # ProgrammingError: the insert names a table that does not exist
        real_text = user_accounts.text
        monkeypatch.setattr(user_accounts, "text", lambda sql: real_text(
            sql.replace("insert into records.user_account ", "insert into records.no_such_user_account ")))
        problem = _problem(lambda: user_accounts.invite(SEED, {"email": "new@example.co.th", "role": "OFFICER",
                                                               "officer": "nantapol"}, "settasak", "MANAGER", OFFICERS))
        assert (problem.status, problem.code) == (500, "internal_error")
        _leaks_nothing(problem)
        monkeypatch.setattr(user_accounts, "text", real_text)
        assert pg_conn.execute(text("select count(*) from records.user_account")).scalar() == 0
    finally:
        _wipe(pg_conn)


def test_the_engine_never_prints_a_bound_parameter(pg_url, monkeypatch):
    """I3: db.engine() is built with hide_parameters=True, so a failed statement's text
    (what a log line or an error reporter records) names no bound value."""
    monkeypatch.setenv("DATABASE_URL", pg_url)
    db.reset()
    try:
        conn = db.connect()
        try:
            with pytest.raises(ProgrammingError) as caught:
                conn.execute(text("select 1 from records.no_such_table where email = :e"), {"e": "thip@example.co.th"})
        finally:
            conn.close()
        assert "no_such_table" in str(caught.value)
        assert "example.co.th" not in str(caught.value)
    finally:
        db.reset()


def test_re_inviting_a_disabled_person_is_bound_by_their_previous_role():
    """M1: a Manager re-inviting a disabled Owner-ranked person as MANAGER must be
    refused exactly as disabling that Owner directly would be — otherwise a Manager
    can quietly undo an Owner's disable by re-inviting at a lower role. The previous
    role is the row's when it carries one, else the seed's."""
    boss_uid = next(u["uid"] for u in user_accounts.listed(SEED, None) if u["email"] == "boss@example.co.th")
    user_accounts.disable(SEED, boss_uid, "owner", "OWNER", "lead@example.co.th")
    problem = _problem(lambda: user_accounts.invite(SEED, {"email": "boss@example.co.th", "role": "MANAGER", "officer": "owner"},
                                                    "settasak", "MANAGER", OFFICERS))
    assert (problem.status, problem.code) == (403, "role_above_actor")
    assert problem.extensions["role"] == "OWNER"
    assert user_accounts.allow_entry("boss@example.co.th", SEED) == (None, "DISABLED")     # unchanged
    # an Owner still may
    again = user_accounts.invite(SEED, {"email": "boss@example.co.th", "role": "MANAGER", "officer": "owner"},
                                 "owner", "OWNER", OFFICERS)
    assert again["state"] == "ACTIVE" and again["role"] == "MANAGER"
    # the row's role, for a person the seed never named
    user_accounts.invite(SEED, {"email": "big@example.co.th", "role": "OWNER", "officer": "owner"}, "owner", "OWNER", OFFICERS)
    big_uid = next(u["uid"] for u in user_accounts.listed(SEED, None) if u["email"] == "big@example.co.th")
    user_accounts.disable(SEED, big_uid, "owner", "OWNER", "boss@example.co.th")
    problem = _problem(lambda: user_accounts.invite(SEED, {"email": "big@example.co.th", "role": "OFFICER", "officer": "thip"},
                                                    "settasak", "MANAGER", OFFICERS))
    assert (problem.code, problem.extensions["role"]) == ("role_above_actor", "OWNER")
    # an equal previous role is not above
    lead_uid = next(u["uid"] for u in user_accounts.listed(SEED, None) if u["email"] == "lead@example.co.th")
    user_accounts.disable(SEED, lead_uid, "owner", "OWNER", "boss@example.co.th")
    assert user_accounts.invite(SEED, {"email": "lead@example.co.th", "role": "MANAGER", "officer": "settasak"},
                                "settasak", "MANAGER", OFFICERS)["state"] == "ACTIVE"


def test_a_racing_second_disable_is_refused_not_silently_overwritten(pg_conn, monkeypatch):
    """M2: two disable() calls that both passed the (stale) Python pre-check must not
    both succeed — the second overwriting the first's disabled_by silently."""
    _store_on(pg_conn, monkeypatch)
    try:
        uid = next(u["uid"] for u in user_accounts.listed(SEED, None) if u["email"] == "thip@example.co.th")
        user_accounts.disable(SEED, uid, "settasak", "MANAGER", "lead@example.co.th")
        # simulate the second racer's stale pre-check: it still believes thip is ACTIVE
        monkeypatch.setattr(user_accounts, "allow_entry",
                            lambda email, seed, fresh=True: ({"role": "OFFICER", "officer": "thip"}, "ACTIVE"))
        problem = _problem(lambda: user_accounts.disable(SEED, uid, "owner", "OWNER", "boss@example.co.th"))
        assert (problem.status, problem.code, problem.error_id) == (409, "user_already_disabled", "DEBT-AUTH-415")
        assert problem.message_th
        kept = pg_conn.execute(text("select disabled_by from records.user_account where email = 'thip@example.co.th'")).scalar()
        assert kept == "settasak"          # the first disable's value was never overwritten
    finally:
        _wipe(pg_conn)


def test_an_actor_role_outside_rank_is_refused_not_a_500():
    """M3: an actor_role this store does not rank (None, or a role that does not
    exist) used to reach RANK[actor_role] and raise a bare KeyError."""
    problem = _problem(lambda: user_accounts.invite(SEED, {"email": "z@example.co.th", "role": "OFFICER", "officer": "thip"},
                                                    "x", None, OFFICERS))
    assert (problem.status, problem.code, problem.error_id) == (403, "forbidden", "DEBT-IAM-0403")
    uid = next(u["uid"] for u in user_accounts.listed(SEED, None) if u["email"] == "thip@example.co.th")
    assert _problem(lambda: user_accounts.disable(SEED, uid, "x", None, "x")).code == "forbidden"
    assert _problem(lambda: user_accounts.disable(SEED, uid, "x", "KING", "x")).code == "forbidden"
    assert user_accounts.allow_entry("thip@example.co.th", SEED)[1] == "ACTIVE"


def test_seed_uid_is_keyed_with_the_session_secret_when_one_is_set(monkeypatch):
    """M4: an unsalted SHA-256 of the e-mail, cut to 16 hex, is reversible from a word
    list. With AUTH_SESSION_SECRET configured the id is HMAC-keyed instead, and the
    same for every instance sharing the secret, so a listed id keeps resolving."""
    import hashlib

    from app.integrations import load_env

    load_env()                      # backend/.env is read once; after this the environment alone decides
    secret = "s3cr3t-session-signing-key-at-least-32-characters-long"
    email = "thip@example.co.th"
    word_list_guess = "env-" + hashlib.sha256(email.encode("utf-8")).hexdigest()[:16]

    monkeypatch.delenv("AUTH_SESSION_SECRET", raising=False)
    assert user_accounts._seed_uid(email) == word_list_guess              # no secret (auth off): the plain digest

    monkeypatch.setenv("AUTH_SESSION_SECRET", secret)
    keyed = user_accounts._seed_uid(email)
    assert keyed.startswith("env-") and len(keyed) == 20 and keyed != word_list_guess
    listed = {u["email"]: u["uid"] for u in user_accounts.listed(SEED, None)}
    assert listed[email] == keyed
    user_accounts.reset()                                                 # another instance: no process state shared
    assert user_accounts._seed_uid(email) == keyed                        # ...derives the same id from the same secret
    assert user_accounts.disable(SEED, keyed, "owner", "OWNER", "boss@example.co.th")["state"] == "DISABLED"

    monkeypatch.setenv("AUTH_SESSION_SECRET", secret + "x")
    assert user_accounts._seed_uid(email) not in (word_list_guess, keyed)  # another secret, another id


def test_a_configured_database_that_does_not_answer_refuses_every_write_and_the_list(monkeypatch):
    """M5: the DB-down test covered only allow_entry — invite, disable, set_profile and
    listed refuse the same retryable 503, never a silent memory-mode fallback."""
    monkeypatch.setattr(db, "configured", lambda: True)

    def down():
        raise db.DatabaseUnreachable("no route")
    monkeypatch.setattr(db, "connect", down)

    checks = (
        lambda: user_accounts.invite(SEED, {"email": "z@example.co.th", "role": "OFFICER", "officer": "thip"},
                                     "settasak", "MANAGER", OFFICERS),
        lambda: user_accounts.disable(SEED, "1", "settasak", "MANAGER", "lead@example.co.th"),
        lambda: user_accounts.set_profile({"sub": "thip@example.co.th", "kind": "GOOGLE"}, {"display_name": "x"}),
        lambda: user_accounts.listed(SEED, None),
    )
    for call in checks:
        problem = _problem(call)
        assert (problem.status, problem.code, problem.retryable) == (503, "user_list_unreachable", True)
        _leaks_nothing(problem)
    assert user_accounts._MEMORY == {}


def test_the_insert_guard_catches_a_pre_check_beaten_by_a_racing_invite(pg_conn, monkeypatch):
    """M5: forces the invite() pre-check stale the way the reviewer's race_sql.py did,
    to reach the "done is None" guard that existed but was never exercised."""
    _store_on(pg_conn, monkeypatch)
    try:
        user_accounts.invite(SEED, {"email": "new@example.co.th", "role": "OFFICER", "officer": "nantapol"},
                             "settasak", "MANAGER", OFFICERS)
        monkeypatch.setattr(user_accounts, "allow_entry", lambda email, seed, fresh=True: (None, None))
        problem = _problem(lambda: user_accounts.invite(SEED, {"email": "new@example.co.th", "role": "MANAGER",
                                                               "officer": "nantapol"}, "owner", "OWNER", OFFICERS))
        assert (problem.status, problem.code) == (409, "user_exists")
        kept = pg_conn.execute(text("select role, invited_by from records.user_account where email = 'new@example.co.th'")).first()
        pg_conn.commit()
        assert tuple(kept) == ("OFFICER", "settasak")        # the winner's row stands
    finally:
        _wipe(pg_conn)


def test_a_display_name_needs_a_visible_base_character_and_bounded_marks():
    """M5: once Mn/Me marks, Cf format characters, spaces and the invisible Hangul fillers
    U+115F, U+1160, U+3164, U+FFA0 are set aside, something must be left; and no base
    character carries more than 3 combining marks."""
    google = {"sub": "thip@example.co.th", "kind": "GOOGLE"}
    invisible = (
        "\u0301\u0301",                 # two accents, no base letter
        "\u20dd",                       # an enclosing mark alone
        "\u115f\u1160\u3164\uffa0",     # the four fillers
        "\u3164 \u3164",                # fillers separated by a space
        "\u115f\u0301",                 # a mark riding on a filler
    )
    too_stacked = ("a" + "\u0301" * 4, "ท" + "\u0e34\u0e48\u0e4c\u0e47")
    for bad in invisible + too_stacked:
        problem = _problem(lambda b=bad: user_accounts.set_profile(google, {"display_name": b}))
        assert (problem.status, problem.errors[0]["code"]) == (422, "display_name_invalid"), ascii(bad)
        assert problem.errors[0]["message_th"]
    assert user_accounts.display_name_for(google)["display_name_source"] == "EMAIL"     # nothing was stored
    exactly_three = "a" + "\u0301" * 3                       # exactly at the cap: allowed
    assert user_accounts.set_profile(google, {"display_name": exactly_three}) == exactly_three
    assert user_accounts.set_profile(google, {"display_name": "ปิ่น ทิพย์ \U0001f600"}) == "ปิ่น ทิพย์ \U0001f600"


# --- B10b controller rulings (2026-09-15): the M1 edge, U+2800, the missing table ------

def test_a_disable_records_the_role_it_saw_so_a_later_seed_removal_keeps_the_rank_rule():
    """M1 edge: an Owner-ranked person known only to the seed was disabled; the row kept
    no role, so once the seed entry was removed (a redeploy) _known_role() found none and
    a Manager could re-invite that person. disable() now writes the role it saw."""
    boss_uid = next(u["uid"] for u in user_accounts.listed(SEED, None) if u["email"] == "boss@example.co.th")
    user_accounts.disable(SEED, boss_uid, "owner", "OWNER", "lead@example.co.th")
    trimmed = {email: entry for email, entry in SEED.items() if email != "boss@example.co.th"}
    problem = _problem(lambda: user_accounts.invite(trimmed, {"email": "boss@example.co.th", "role": "MANAGER",
                                                              "officer": "owner"}, "settasak", "MANAGER", OFFICERS))
    assert (problem.status, problem.code, problem.extensions["role"]) == (403, "role_above_actor", "OWNER")
    assert user_accounts.allow_entry("boss@example.co.th", trimmed) == (None, "DISABLED")
    boss = next(u for u in user_accounts.listed(trimmed, None) if u["email"] == "boss@example.co.th")
    assert (boss["state"], boss["role"], boss["officer"], boss["seeded"]) == ("DISABLED", "OWNER", "owner", False)
    # an invited row's own role is the one kept
    user_accounts.invite(SEED, {"email": "new@example.co.th", "role": "SUPERVISOR", "officer": "nantapol"},
                         "owner", "OWNER", OFFICERS)
    new_uid = next(u["uid"] for u in user_accounts.listed(SEED, None) if u["email"] == "new@example.co.th")
    assert user_accounts.disable(SEED, new_uid, "owner", "OWNER", "boss@example.co.th")["role"] == "SUPERVISOR"


def test_a_disable_on_postgres_writes_the_role_and_officer_it_saw(pg_conn, monkeypatch):
    _store_on(pg_conn, monkeypatch)
    try:
        boss_uid = next(u["uid"] for u in user_accounts.listed(SEED, None) if u["email"] == "boss@example.co.th")
        user_accounts.disable(SEED, boss_uid, "owner", "OWNER", "lead@example.co.th")
        user_accounts.invite(SEED, {"email": "new@example.co.th", "role": "SUPERVISOR", "officer": "nantapol"},
                             "owner", "OWNER", OFFICERS)
        new_uid = next(u["uid"] for u in user_accounts.listed(SEED, None) if u["email"] == "new@example.co.th")
        user_accounts.disable(SEED, new_uid, "settasak", "MANAGER", "lead@example.co.th")
        rows = pg_conn.execute(text("select email, role, officer, disabled_by from records.user_account "
                                    "order by email")).all()
        pg_conn.commit()
        assert [tuple(r) for r in rows] == [("boss@example.co.th", "OWNER", "owner", "owner"),
                                            ("new@example.co.th", "SUPERVISOR", "nantapol", "settasak")]
        trimmed = {email: entry for email, entry in SEED.items() if email != "boss@example.co.th"}
        problem = _problem(lambda: user_accounts.invite(trimmed, {"email": "boss@example.co.th", "role": "MANAGER",
                                                                  "officer": "owner"}, "settasak", "MANAGER", OFFICERS))
        assert (problem.code, problem.extensions["role"]) == ("role_above_actor", "OWNER")
    finally:
        _wipe(pg_conn)


def test_a_braille_blank_is_not_a_visible_display_name():
    """U+2800 BRAILLE PATTERN BLANK is category So, a "symbol" that renders as nothing."""
    google = {"sub": "thip@example.co.th", "kind": "GOOGLE"}
    for bad in ("\u2800", "\u2800 \u2800", "\u2800\u0301"):
        problem = _problem(lambda b=bad: user_accounts.set_profile(google, {"display_name": b}))
        assert (problem.status, problem.errors[0]["code"]) == (422, "display_name_invalid"), ascii(bad)
    assert user_accounts.set_profile(google, {"display_name": "\u2800Thip"}) == "\u2800Thip"


def test_the_email_rule_is_one_public_function():
    """B10b: the Google sign-in and auth.load_config reuse this, never a copied regex."""
    assert user_accounts.valid_email("o'brien+debt@mail.example.co.th") is True
    for bad in ("thip\u200b@example.co.th", "thip@ex\u0430mple.co.th", "Thip@example.co.th", "no", "", None, 7):
        assert user_accounts.valid_email(bad) is False, ascii(bad)


def test_a_missing_table_is_a_503_that_names_the_migration(pg_conn, monkeypatch):
    """The migration not applied: records.user_account is absent. Every read and write
    used to answer internal_error (500), which B10b's middleware would have turned into
    a 500 on every request of every Google session. It is a labelled 503 naming
    debt-migrate; a ProgrammingError on a table that DOES exist stays the opaque 500
    (test_real_driver_errors_on_a_write_are_problems_without_the_email)."""
    _store_on(pg_conn, monkeypatch)
    try:
        pg_conn.execute(text("drop table records.user_account"))
        pg_conn.commit()
        checks = (
            lambda: user_accounts.allow_entry("thip@example.co.th", SEED),
            lambda: user_accounts.session_allowed({"sub": "thip@example.co.th", "kind": "GOOGLE",
                                                   "role": "OFFICER", "officer": "thip"}, SEED),
            lambda: user_accounts.listed(SEED, None),
            lambda: user_accounts.invite(SEED, {"email": "new@example.co.th", "role": "OFFICER", "officer": "thip"},
                                         "owner", "OWNER", OFFICERS),
            lambda: user_accounts.set_profile({"sub": "thip@example.co.th", "kind": "GOOGLE"}, {"display_name": "Thip"}),
        )
        for call in checks:
            user_accounts.forget()
            problem = _problem(call)
            assert (problem.status, problem.code, problem.error_id) == (503, "user_list_not_migrated", "DEBT-AUTH-507")
            assert "debt-migrate" in problem.message_th and "debt-migrate" in problem.detail
            assert problem.retryable is False
            _leaks_nothing(problem)
            assert not pg_conn.in_transaction()
    finally:
        pg_conn.rollback()
        migrate.apply(pg_conn)
        pg_conn.commit()
        _wipe(pg_conn)


# --- B10b fix round 1 (opus review of 83c0937): I1, M1, M3 -------------------------------

def _session_at(iat, email="thip@example.co.th", role="OFFICER", officer="thip"):
    return {"sub": email, "kind": "GOOGLE", "role": role, "officer": officer, "iat": iat}


def test_a_session_signed_before_the_latest_invitation_is_not_allowed():
    """I1: a cookie from before a disable came back to life when the person was
    re-invited with the same role and officer. A row invited more than 1 s after the
    session's iat (iat is whole seconds) ends the session."""
    before = int(time.time()) - 120
    uid = next(u["uid"] for u in user_accounts.listed(SEED, None) if u["email"] == "thip@example.co.th")
    assert user_accounts.session_allowed(_session_at(before), SEED) is True        # seed only: no invitation
    user_accounts.disable(SEED, uid, "owner", "OWNER", "boss@example.co.th")
    user_accounts.invite(SEED, {"email": "thip@example.co.th", "role": "OFFICER", "officer": "thip"},
                         "owner", "OWNER", OFFICERS)
    invited = user_accounts._rows(True)[("GOOGLE", "thip@example.co.th")]["invited_at"].timestamp()
    assert user_accounts.session_allowed(_session_at(before), SEED) is False
    assert user_accounts.session_allowed(_session_at(int(invited)), SEED) is True   # the same second: allowed
    assert user_accounts.session_allowed(_session_at(int(invited) + 5), SEED) is True
    assert user_accounts.session_allowed({k: v for k, v in _session_at(before).items() if k != "iat"}, SEED) is False


def test_the_session_check_is_one_read_and_can_be_made_fresh(monkeypatch):
    """I1 keeps the check to one read of the rows; M1's fresh=True bypasses the cache."""
    reads = []
    real = user_accounts._read_rows
    monkeypatch.setattr(user_accounts, "_read_rows", lambda: reads.append(1) or real())
    session = _session_at(int(time.time()))
    assert user_accounts.session_allowed(session, SEED) is True
    assert user_accounts.session_allowed(session, SEED) is True
    assert reads == [1]                                                               # cold, then cached
    user_accounts._memory_row("GOOGLE", email="thip@example.co.th").update(
        role="OFFICER", officer="thip", disabled_at=user_accounts._now(), disabled_by="owner")
    assert user_accounts.session_allowed(session, SEED) is True                       # the stale cache
    assert user_accounts.session_allowed(session, SEED, fresh=True) is False          # a fresh read
    assert reads == [1, 1]


def test_a_session_signed_before_an_invitation_on_postgres_is_not_allowed(pg_conn, monkeypatch):
    _store_on(pg_conn, monkeypatch)
    try:
        before = int(time.time()) - 120
        user_accounts.invite(SEED, {"email": "new@example.co.th", "role": "OFFICER", "officer": "nantapol"},
                             "settasak", "MANAGER", OFFICERS)
        assert user_accounts.session_allowed(_session_at(before, "new@example.co.th", "OFFICER", "nantapol"), SEED) is False
        now = int(time.time())
        assert user_accounts.session_allowed(_session_at(now, "new@example.co.th", "OFFICER", "nantapol"), SEED) is True
    finally:
        _wipe(pg_conn)


def test_an_invitation_cannot_bind_an_officer_whose_registry_role_outranks_the_actor():
    """M3: the chosen officer's registry role is bound by the actor's rank, like the
    role handed out; an unknown officer keeps officer_unknown."""
    problem = _problem(lambda: user_accounts.invite(SEED, {"email": "new@example.co.th", "role": "MANAGER",
                                                           "officer": "owner"}, "settasak", "MANAGER", OFFICERS))
    assert (problem.status, problem.code, problem.extensions["role"]) == (403, "role_above_actor", "OWNER")
    problem = _problem(lambda: user_accounts.invite(SEED, {"email": "new@example.co.th", "role": "OFFICER",
                                                           "officer": "settasak"}, "x", "SUPERVISOR", OFFICERS))
    assert (problem.code, problem.extensions["role"]) == ("role_above_actor", "MANAGER")
    assert user_accounts.invite(SEED, {"email": "new@example.co.th", "role": "MANAGER", "officer": "settasak"},
                                "settasak", "MANAGER", OFFICERS)["officer"] == "settasak"          # equal: allowed
    assert user_accounts.invite(SEED, {"email": "big@example.co.th", "role": "MANAGER", "officer": "owner"},
                                "owner", "OWNER", OFFICERS)["officer"] == "owner"
    problem = _problem(lambda: user_accounts.invite(SEED, {"email": "z@example.co.th", "role": "OFFICER",
                                                           "officer": "ghost"}, "owner", "OWNER", OFFICERS))
    assert [e["code"] for e in problem.errors] == ["officer_unknown"]

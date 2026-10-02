from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_the_log_reads_back_newest_first_and_says_whether_it_is_persisted():
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    client.post("/v1/cases/by-customer/%s/dc-status" % uid,
                json={"code": "CONTACT_BACK", "reason": "เหตุผล"},
                headers={"X-Volt-Officer": "nantapol"})
    body = client.get("/v1/audit").json()
    assert body["entries"], "the act just taken must be in the log"
    seqs = [e["seq"] for e in body["entries"]]
    assert seqs == sorted(seqs, reverse=True)
    assert "persisted" in body["meta"]


def test_the_log_filters_by_the_name_that_was_claimed():
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    client.post("/v1/cases/by-customer/%s/dc-status" % uid,
                json={"code": "UNREACHABLE", "reason": "ไม่รับสาย"},
                headers={"X-Volt-Officer": "thip"})
    body = client.get("/v1/audit", params={"actor": "thip"}).json()
    assert body["entries"]
    assert all(e["actor_claimed"] == "thip" for e in body["entries"])


def test_verify_reports_a_clean_chain():
    body = client.get("/v1/audit/verify").json()
    assert body["ok"] is True
    assert body["broken_at"] is None
    assert body["verified"] >= 1


def test_since_actually_filters_instead_of_being_silently_ignored():
    # Final-review finding 3: audit_store._matches never applied `since` on the
    # in-memory path — the API accepted the parameter and returned every row
    # regardless, with nothing on the response to say the filter did nothing.
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    client.post("/v1/cases/by-customer/%s/dc-status" % uid,
                json={"code": "CONTACT_BACK", "reason": "เหตุผล"},
                headers={"X-Volt-Officer": "since-test"})
    # A `since` far in the future must exclude everything — the old code could
    # never make this assertion fail, because it never looked at `since` at all.
    future = client.get("/v1/audit", params={"since": "2099-01-01", "actor": "since-test"}).json()
    assert future["entries"] == []
    # A `since` well before anything in the log must still return the row.
    past = client.get("/v1/audit", params={"since": "2000-01-01", "actor": "since-test"}).json()
    assert past["entries"]


def test_an_unparseable_since_is_refused_not_a_500():
    # On the DB path this used to bind the raw string straight into `at >= :since`
    # and let Postgres raise — an unhandled 500 for a client typo. Refused through
    # the project's normal Problem shape instead, at the router, before either
    # storage path ever sees it.
    resp = client.get("/v1/audit", params={"since": "not-a-date"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "validation_failed"
    assert body["message_th"]
    assert any(e["pointer"] == "/since" for e in body["errors"])


def test_the_log_cannot_be_changed_through_the_api():
    # Not guarded — ABSENT. There is no route to refuse.
    for verb in ("put", "patch", "delete"):
        response = getattr(client, verb)("/v1/audit/1")
        assert response.status_code in (404, 405), verb


# --- Delta-100 AL2: the "91% from sign-in" strip, over the WHOLE log ----------------

def test_the_signing_source_strip_counts_the_stored_rows_not_the_page():
    from app import audit_store
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    client.post("/v1/cases/by-customer/%s/dc-status" % uid,
                json={"code": "CONTACT_BACK", "reason": "r"},
                headers={"X-Volt-Officer": "strip-check"})
    body = client.get("/v1/audit").json()
    strip = body["meta"]["signing_source"]
    counts = audit_store.actor_source_counts()
    for key in ("total", "from_session", "from_test_account", "claimed", "session_pct"):
        assert strip[key] == counts[key], key
    # The statistic is over the whole log, never the page just read.
    assert strip["total"] >= body["meta"]["count"]
    if strip["total"]:
        assert strip["value_th"].endswith("จากการเข้าสู่ระบบ")
        assert strip["value_en"] and strip["note_th"] and strip["note_en"]


def test_the_signing_source_is_computed_from_the_rows_it_reports():
    """A claimed header name is not a session name; the percentage is arithmetic on
    actor_source, not a stored literal."""
    from app import audit_store
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    client.post("/v1/cases/by-customer/%s/dc-status" % uid,
                json={"code": "CONTACT_BACK", "reason": "r"},
                headers={"X-Volt-Officer": "claimed-check"})
    counts = audit_store.actor_source_counts()
    entries = audit_store.read({}, limit=10000, before_seq=None)
    session = sum(1 for e in entries if e.get("actor_source") == "SESSION")
    assert counts["from_session"] == session
    assert counts["total"] == len(entries)
    assert counts["claimed"] == sum(1 for e in entries if e.get("actor_source") in ("HEADER", "BODY", "NONE"))

"""F13: the three NOTICE_* acts are audited, by construction and for real.

A new file, not an edit to the pinned tests/test_audit_coverage.py (that file's own
coverage sweep does not enumerate the calendar router — this one closes that gap for
notices specifically, the way C2b's controller ruling asks).
"""
from fastapi.testclient import TestClient
from starlette.routing import Route

from app import audit, audit_store, notices
from app.main import app

client = TestClient(app)
NANTAPOL = {"X-Volt-Officer": "nantapol", "X-Volt-Role": "OFFICER"}


def _act_routes():
    out = []
    for route in app.routes:
        if not isinstance(route, Route):
            continue
        for method in (route.methods or set()) & {"POST", "PUT", "DELETE"}:
            out.append((method, route.path))
    return sorted(set(out))


def test_the_notice_routes_are_registered_act_routes_and_logged_by_construction():
    routes = _act_routes()
    for method, path in (("POST", "/v1/calendar/notices"),
                         ("PUT", "/v1/calendar/notices/{uid}"),
                         ("DELETE", "/v1/calendar/notices/{uid}")):
        assert (method, path) in routes, "%s %s is not a registered route" % (method, path)
        assert audit.is_logged(method, path)


def test_a_created_an_edited_and_a_deleted_notice_each_land_in_the_log():
    notices.reset()
    # Fix round 1 / M4 (tighten): distinctive words, not the trivial "x" — a substring
    # search across the WHOLE row proves the words are absent everywhere, not merely
    # missing from the two keys "title"/"text".
    secret_title, secret_text, secret_edit = "ความลับเดือนกันยายน7788", "รายละเอียดลับ9900", "แก้ไขลับ1122"
    try:
        r = client.post("/v1/calendar/notices",
                        json={"title": secret_title, "on": "2026-10-26", "text": secret_text}, headers=NANTAPOL)
        assert r.status_code == 201, r.json()
        uid = r.json()["notice"]["uid"]
        assert client.put("/v1/calendar/notices/%s" % uid, json={"done": True, "title": secret_edit},
                          headers=NANTAPOL).status_code == 200
        assert client.delete("/v1/calendar/notices/%s" % uid, headers=NANTAPOL).status_code == 200

        entries = audit_store.read({}, limit=1000, before_seq=None)
        by_act = {e["act"]: e for e in entries if e.get("subject_type") == "notice" and e.get("subject_uid") == uid}
        assert set(by_act) == {"NOTICE_CREATED", "NOTICE_UPDATED", "NOTICE_DELETED"}
        for act, path in (("NOTICE_CREATED", "/v1/calendar/notices"),
                          ("NOTICE_UPDATED", "/v1/calendar/notices/{uid}"),
                          ("NOTICE_DELETED", "/v1/calendar/notices/{uid}")):
            assert by_act[act]["route_template"] == path
            # PDPA / F13: an audited act never carries the notice's own words — the
            # WHOLE row, not just the "detail" dict (a mutant could as easily have
            # leaked a word into "detail" under a different key, or anywhere else).
            dump = str(by_act[act])
            assert secret_title not in dump and secret_text not in dump and secret_edit not in dump
            assert "title" not in by_act[act]["detail"] and "text" not in by_act[act]["detail"]
    finally:
        notices.reset()

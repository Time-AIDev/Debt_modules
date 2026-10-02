"""Fix round 1, Finding 2: the filter selects on the audit screen must offer a
name that is somewhere in the whole log, not only in the page currently loaded.
`GET /v1/audit`'s `meta.actors` / `meta.acts` must carry every distinct value ever
recorded, so a name that has fallen off the first page is still selectable."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_meta_actors_and_acts_include_names_not_on_the_first_page():
    uids = [r["customer"]["uid"] for r in client.get("/v1/workbook").json()["rows"][:3]]
    officers = ["nantapol", "thip", "somchai"]
    for uid, officer in zip(uids, officers):
        response = client.post(
            "/v1/cases/by-customer/%s/dc-status" % uid,
            json={"code": "CONTACT_BACK", "reason": "เหตุผล"},
            headers={"X-Volt-Officer": officer},
        )
        assert response.status_code == 200, response.text

    # A page of one holds only the newest entry -- "somchai" -- so "nantapol" and
    # "thip" are, by construction, not present in `entries` on this page.
    body = client.get("/v1/audit", params={"limit": 1}).json()
    assert len(body["entries"]) == 1
    assert body["entries"][0]["actor_claimed"] == "somchai"
    page_actors = {e["actor_claimed"] for e in body["entries"]}
    assert "nantapol" not in page_actors
    assert "thip" not in page_actors

    # Yet the log-wide list in meta must still carry them.
    assert "nantapol" in body["meta"]["actors"]
    assert "thip" in body["meta"]["actors"]
    assert "somchai" in body["meta"]["actors"]
    assert "DC_STATUS_SET" in body["meta"]["acts"]
    # Sorted, and with no null/empty slipped in.
    assert body["meta"]["actors"] == sorted(body["meta"]["actors"])
    assert all(a for a in body["meta"]["actors"])
    assert all(a for a in body["meta"]["acts"])

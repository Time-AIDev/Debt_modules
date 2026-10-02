"""F10b/F10c / R-C — the portfolio split (feedback-r2 TASK-116).

A manager picks a bucket, ticks the officers, sees a served preview, and the
system deals the bucket's unassigned accounts equally at random. The same seed
reproduces a deal; a dry run writes nothing. Every test here is an ADDITION.
"""
import pytest
from fastapi.testclient import TestClient

from app import cases as cases_domain
from app import officers
from app.main import app
from app.routers.settings import deal_bucket


@pytest.fixture
def client():
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}
OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nantapol"}


def _officers(n):
    return [r["uid"] for r in officers.registry() if r["role"] == "OFFICER"][:n]


def _buckets(client):
    response = client.get("/v1/customers:assign-split/buckets", headers=MANAGER)
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list) and body
    return body


def _split(client, bucket, uids, **over):
    body = {"bucket": bucket, "officer_uids": uids, **over}
    return client.post("/v1/customers:assign-split", headers=MANAGER, json=body)


def test_the_buckets_carry_served_counts_and_an_unassigned_number(client):
    buckets = _buckets(client)
    assert all(set(b) >= {"code", "label_th", "label_en", "count", "unassigned"} for b in buckets)
    assert any(b["code"] == "NPL" for b in buckets)
    assert all(_thai(b["label_th"]) for b in buckets if b["code"] != "NPL")
    total = sum(b["count"] for b in buckets)
    # Every open book row sits in exactly one bucket (NPL rows carry NPL_CONFIRMED,
    # which is not a band of the active set).
    assert total == client.get("/v1/today").json()["meta"]["total"]
    assert all(b["unassigned"] == 0 for b in buckets)


def _thai(text):
    return any("฀" <= ch <= "๿" for ch in (text or ""))


def test_a_dry_run_previews_the_split_and_writes_nothing(client):
    bucket = next(b for b in _buckets(client) if b["count"] >= 2)
    crew = _officers(2)
    cs = cases_domain.for_current()
    before = {uid: case["officer_uid"] for uid, case in cs.cases.items()}
    preview = _split(client, bucket["code"], crew, include_assigned=True, dry_run=True)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["dry_run"] is True and body["seed"]
    assert body["total"] == bucket["count"]
    assert sum(p["count"] for p in body["per_officer"]) == bucket["count"]
    assert max(p["count"] for p in body["per_officer"]) - min(p["count"] for p in body["per_officer"]) <= 1
    assert {uid: case["officer_uid"] for uid, case in cs.cases.items()} == before


def test_the_split_deals_the_bucket_and_keeps_its_seed_in_the_audit(client):
    bucket = next(b for b in _buckets(client) if b["count"] >= 3)
    crew = _officers(3)
    run = _split(client, bucket["code"], crew, include_assigned=True)
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["assigned"] and len(body["assigned"]) == body["total"] == bucket["count"]
    # The counts served before the write are the counts the book now carries.
    cs = cases_domain.for_current()
    for row in body["per_officer"]:
        assert sum(1 for uid in body["assigned"] if cs.cases[uid]["officer_uid"] == row["officer_uid"]) == row["count"]
    entry = next(e for e in client.get("/v1/audit").json()["entries"] if e["act"] == "CUSTOMERS_SPLIT")
    assert entry["subject_uid"] == bucket["code"]
    assert entry["detail"]["seed"] and entry["detail"]["per_officer"] == body["per_officer"]
    assert entry["detail"]["include_assigned"] is True


def test_assigned_rows_are_left_alone_unless_asked(client):
    bucket = next(b for b in _buckets(client) if b["count"] >= 2)
    preview = _split(client, bucket["code"], _officers(2)).json()
    assert preview["total"] == 0 and all(p["count"] == 0 for p in preview["per_officer"])
    run = _split(client, bucket["code"], _officers(2)).json()
    assert run["assigned"] == []


def test_an_officer_may_not_split_and_an_unknown_bucket_is_refused(client):
    assert client.post("/v1/customers:assign-split", headers=OFFICER,
                       json={"bucket": "NPL", "officer_uids": _officers(1)}).status_code == 403
    refused = _split(client, "NOT_A_BUCKET", _officers(1))
    assert refused.status_code == 422
    assert refused.json()["errors"][0]["pointer"] == "/bucket"


def test_a_selection_is_dealt_equally_at_random_from_the_today_ticks(client):
    """Build round 3: the same deal takes `customer_uids` — the manager's own ticks —
    instead of a bucket, and still previews, seeds and audits."""
    rows = client.get("/v1/today").json()["items"][:4]
    uids = [r["customer"]["uid"] for r in rows]
    assert len(uids) == 4
    crew = _officers(2)
    preview = client.post("/v1/customers:assign-split", headers=MANAGER,
                          json={"customer_uids": uids, "officer_uids": crew, "dry_run": True})
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["total"] == 4 and body["seed"]
    assert sorted(p["count"] for p in body["per_officer"]) == [2, 2]
    run = client.post("/v1/customers:assign-split", headers=MANAGER,
                      json={"customer_uids": uids, "officer_uids": crew})
    assert run.status_code == 200, run.text
    dealt = run.json()
    assert sorted(dealt["assigned"]) == sorted(uids)
    cs = cases_domain.for_current()
    for row in dealt["per_officer"]:
        assert sum(1 for uid in dealt["assigned"] if cs.cases[uid]["officer_uid"] == row["officer_uid"]) == row["count"]
    entry = next(e for e in client.get("/v1/audit").json()["entries"] if e["act"] == "CUSTOMERS_SPLIT")
    assert entry["subject_type"] == "selection"
    assert entry["subject_uid"] == "4 rows"
    assert entry["detail"]["count"] == 4
    refused = client.post("/v1/customers:assign-split", headers=MANAGER,
                          json={"customer_uids": ["no-such-uid"], "officer_uids": crew})
    assert refused.status_code == 422


def test_the_deal_is_reproducible_from_its_seed(client):
    uids = ["u-%02d" % n for n in range(10)]
    first_shuffle, first = deal_bucket(uids, ["a", "b", "c"], "2026-10-23-deadbeef")
    second_shuffle, second = deal_bucket(uids, ["a", "b", "c"], "2026-10-23-deadbeef")
    assert first_shuffle == second_shuffle and first == second
    assert sorted(len(v) for v in first.values()) == [3, 3, 4]
    # exactly the same officers are dealt to, differently, under a different seed —
    # the counts stay within one of each other.
    shuffled, other = deal_bucket(uids, ["a", "b", "c"], "2026-10-23-cafebabe")
    assert sorted(shuffled) == sorted(uids)
    assert sorted(len(v) for v in other.values()) == [3, 3, 4]

"""B8 (Feedback Round 1 / WP10): every config row says who changed it last, and when.

Each test uses its own TestClient, so its own volt_session cookie and its own
per-session Settings and change stamps — nothing here leaks into another test's
session, and no test has to put a value back.
"""
from fastapi.testclient import TestClient

from app import audit_store
from app.main import app

MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}
OWNER = {"X-Volt-Role": "OWNER", "X-Volt-Officer": "owner"}


def _rows(client, headers=MANAGER):
    return client.get("/v1/config", headers=headers).json()["config"]


def test_a_key_nobody_changed_says_so_with_nulls():
    row = _rows(TestClient(app))["pipeline_lookahead_days"]
    assert (row["changed_by"], row["changed_by_role"], row["changed_at"]) == (None, None, None)


def test_a_save_stamps_the_signer_the_role_and_the_business_clock():
    client = TestClient(app)
    r = client.put("/v1/config", json={"pipeline_lookahead_days": 5}, headers=MANAGER)
    assert r.status_code == 200, r.json()
    row = r.json()["config"]["pipeline_lookahead_days"]
    assert row["value"] == "5"
    assert row["changed_by"] == "settasak" and row["changed_by_role"] == "MANAGER"
    assert row["changed_at"].startswith("2026-10-23T")
    assert _rows(client)["pipeline_lookahead_days"]["changed_by"] == "settasak"
    assert _rows(client)["review_sla_hours"]["changed_by"] is None


def test_an_officer_identity_pressing_manager_is_signed_by_the_role_default():
    """officers.sign (S2-04): an identity the registry knows as an OFFICER cannot sign a
    Manager act, so the stamp names the role's default identity, never nantapol."""
    client = TestClient(app)
    r = client.put("/v1/config", json={"pipeline_lookahead_days": 4},
                   headers={"X-Volt-Role": "MANAGER", "X-Volt-Officer": "nantapol"})
    assert r.json()["config"]["pipeline_lookahead_days"]["changed_by"] == "settasak"


def test_saving_the_value_it_already_holds_is_not_a_change():
    client = TestClient(app)
    current = _rows(client)["review_sla_hours"]["value"]
    r = client.put("/v1/config", json={"review_sla_hours": current}, headers=MANAGER)
    assert r.status_code == 200 and r.json()["config"]["review_sla_hours"]["changed_by"] is None


def test_a_refused_key_writes_nothing_not_even_the_valid_key_before_it():
    client = TestClient(app)
    before = _rows(client)["pipeline_lookahead_days"]["value"]
    r = client.put("/v1/config", json={"pipeline_lookahead_days": 9, "reminder_offsets_days": "x"}, headers=MANAGER)
    assert r.status_code == 422
    row = _rows(client)["pipeline_lookahead_days"]
    assert row["value"] == before and row["changed_by"] is None


def test_the_stamp_is_per_session_like_the_value():
    first, second = TestClient(app), TestClient(app)
    first.put("/v1/config", json={"pipeline_lookahead_days": 6}, headers=OWNER)
    assert _rows(first)["pipeline_lookahead_days"]["changed_by"] == "owner"
    assert _rows(second)["pipeline_lookahead_days"]["changed_by"] is None


def test_the_change_is_audited_with_its_keys_and_values():
    client = TestClient(app)
    client.put("/v1/config", json={"pipeline_lookahead_days": 7}, headers=MANAGER)
    entry = audit_store.read({}, limit=1, before_seq=None)[0]
    assert entry["act"] == "CONFIG_SET" and entry["subject_type"] == "config"
    assert entry["subject_uid"] == "pipeline_lookahead_days"
    assert entry["detail"]["keys"]["pipeline_lookahead_days"]["to"] == "7"

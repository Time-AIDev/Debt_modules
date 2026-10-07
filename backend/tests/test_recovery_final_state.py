"""Authenticated requests must respect the final-state locks used by the UI."""
from copy import deepcopy
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app import auth
from app.main import app


@pytest.fixture
def manager(tmp_path):
    accounts = {"final-state.manager": {
        "hash": auth.hash_password("fixture-password", rounds=1000),
        "role": "MANAGER", "officer": "settasak",
    }}
    auth.set_config(auth.load_config({
        "AUTH_MODE": "on", "AUTH_SESSION_SECRET": "s" * 40,
        "AUTH_COOKIE_SECURE": "false", "AUTH_ALLOW_TEST_ACCOUNTS": "true",
        "AUTH_TEST_ACCOUNTS": json.dumps(accounts),
    }, env_file=tmp_path / "none"))
    try:
        with TestClient(app) as client:
            login = client.post("/v1/auth/password", json={
                "username": "final-state.manager", "password": "fixture-password",
            })
            assert login.status_code == 200, login.text
            assert login.json()["role"] == "MANAGER" and login.json()["can_switch"] is False
            yield client
    finally:
        auth.reset()


def post(client, path, body, key=None):
    return client.post(path, json=body, headers={"Idempotency-Key": key or uuid4().hex})


def open_recovery(client):
    npl = next(row for row in client.get("/v1/npl-cases").json()["npl_cases"]
               if not row.get("recovery_uid"))
    opened = post(client, "/v1/npl-cases/%s/recovery" % npl["uid"], {"strategy": "LEGAL"})
    assert opened.status_code == 201, opened.text
    return opened.json()["recovery"]["uid"]


def read_recovery(client, uid):
    return next(row for row in client.get("/v1/recovery-cases").json()["recovery_cases"] if row["uid"] == uid)


def finish_recovery(client, uid, final_state):
    if final_state == "RESOLVED":
        response = post(client, "/v1/recovery-cases/%s:resolve" % uid, {"outcome": "PARTIAL"})
    else:
        response = post(client, "/v1/recovery-cases/%s:change-strategy" % uid,
                        {"strategy": "REPOSSESSION", "reason": "Fixture approved strategy change"})
    assert response.status_code == 200, response.text
    assert read_recovery(client, uid)["status"] == final_state


@pytest.mark.parametrize("final_state", ["RESOLVED", "SUPERSEDED"])
@pytest.mark.parametrize("operation", ["cash", "resolve"])
def test_new_requests_cannot_add_money_or_replace_a_final_outcome(manager, final_state, operation):
    uid = open_recovery(manager)
    money = post(manager, "/v1/recovery-cases/%s/recoveries" % uid,
                 {"amount": "25.00", "source": "LEGAL"})
    assert money.status_code == 201, money.text
    finish_recovery(manager, uid, final_state)
    before = deepcopy(read_recovery(manager, uid))
    if operation == "cash":
        response = post(manager, "/v1/recovery-cases/%s/recoveries" % uid,
                        {"amount": "50.00", "source": "LEGAL"})
    else:
        response = post(manager, "/v1/recovery-cases/%s:resolve" % uid, {"outcome": "FULL"})
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "recovery_not_open"
    assert ("ยอดรับคืน" if operation == "cash" else "ผลการเรียกคืน") in response.json()["message_th"]
    after = read_recovery(manager, uid)
    assert after == before
    assert after["recovered_total"] == "25.00" and len(after["recoveries"]) == 1


def test_an_open_recovery_keeps_its_existing_money_and_resolution_workflow(manager):
    uid = open_recovery(manager)
    for amount in ("25.00", "50.00"):
        response = post(manager, "/v1/recovery-cases/%s/recoveries" % uid,
                        {"amount": amount, "source": "LEGAL"})
        assert response.status_code == 201, response.text
    row = read_recovery(manager, uid)
    assert row["status"] == "IN_PROGRESS" and row["recovered_total"] == "75.00"
    finish_recovery(manager, uid, "RESOLVED")
    assert read_recovery(manager, uid)["recovered_total"] == "75.00"

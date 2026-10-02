"""Round-three blind findings, from the pass that finally reached the contact surface.

All ten Act-compliance rules were confirmed holding. These four are what it found beyond them.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def a_customer(client, index=0):
    return client.get("/v1/today-list").json()["items"][index]["customer"]["uid"]


def contact(client, uid, at, **extra):
    payload = {"customer_uid": uid, "channel": "PHONE", "direction": "OUTBOUND",
               "disposition": "ANS_DISCUSSED", "at": at, "officer": "noon", "role": "OFFICER"}
    payload.update(extra)
    return client.post("/v1/contacts", json=payload)


class TestZuluTimestampsAreAccepted:
    """`Z` IS an explicit offset — RFC 3339 §5.6 defines it as exactly +00:00.

    Rejecting it locks out every JavaScript client, because `Date.toISOString()` emits
    `Z` by default. Python 3.9's `fromisoformat` does not parse it, which is a language
    limitation the API must absorb rather than pass on to callers.
    """

    def test_a_zulu_timestamp_is_accepted(self, client):
        assert contact(client, a_customer(client, 0), "2027-09-09T02:00:00Z").status_code == 201

    def test_zulu_and_plus_zero_are_the_same_instant(self, client):
        """The proof it is parsed, not merely tolerated: the two spellings must collide
        on the same Bangkok day and the second must be refused."""
        uid = a_customer(client, 1)
        assert contact(client, uid, "2027-09-09T02:00:00Z").status_code == 201
        assert contact(client, uid, "2027-09-09T02:00:00+00:00").status_code == 409

    def test_a_zulu_timestamp_resolves_to_the_bangkok_day_not_the_utc_one(self, client):
        """18:00Z is 01:00 the NEXT day in Bangkok. Getting this wrong would put two
        contacts on what the Act counts as one day."""
        uid = a_customer(client, 2)
        assert contact(client, uid, "2027-09-10T18:00:00Z").status_code == 201
        # Same Bangkok day (2027-09-11), so this must be refused.
        assert contact(client, uid, "2027-09-11T09:00:00+07:00").status_code == 409


class TestOverrideAllowedTellsTheTruth:
    """§5.9 has the client "offer the override button only when `override_allowed`".

    Hardcoding it false means a spec-conformant UI never shows a Manager the control
    they actually hold — the permission exists and is unreachable.
    """

    def _take_the_slot(self, client, uid):
        contact(client, uid, "2027-10-01T09:00:00+07:00")

    @pytest.mark.parametrize("role,expected", [
        ("OFFICER", False), ("SUPERVISOR", False), ("MANAGER", True), ("OWNER", True),
    ])
    def test_override_allowed_reflects_the_asking_role(self, client, role, expected):
        uid = a_customer(client, 3)
        self._take_the_slot(client, uid)
        refused = contact(client, uid, "2027-10-01T15:00:00+07:00", role=role, officer="x")

        assert refused.status_code == 409
        assert refused.json()["extensions"]["override_allowed"] is expected

    def test_the_flag_agrees_with_what_the_override_actually_does(self, client):
        """The flag and the behaviour must not disagree — that is the whole defect."""
        uid = a_customer(client, 4)
        self._take_the_slot(client, uid)
        refused = contact(client, uid, "2027-10-01T15:00:00+07:00", role="MANAGER", officer="mana")
        assert refused.json()["extensions"]["override_allowed"] is True

        allowed = contact(client, uid, "2027-10-01T15:05:00+07:00", role="MANAGER", officer="mana",
                          override=True, override_reason="Customer called back for a settlement figure")
        assert allowed.status_code == 201


def test_a_blank_override_reason_is_not_a_logged_reason(client):
    """§7.4 permits an override ONLY with a logged reason. Whitespace is not one, and it
    is the first thing anyone types to get past a required field."""
    uid = a_customer(client, 5)
    contact(client, uid, "2027-11-01T09:00:00+07:00")

    for blank in ("   ", "", "\t\n"):
        response = contact(client, uid, "2027-11-01T15:00:00+07:00", role="MANAGER",
                           officer="mana", override=True, override_reason=blank)
        assert response.status_code == 422, repr(blank)


def test_the_retraction_error_id_does_not_collide_with_override_reason_required(client):
    """DEBT-COL-0423 is assigned to override_reason_required. Two different conditions
    behind one error_id sends two different investigations to the same place."""
    uid = a_customer(client, 0)
    created = contact(client, uid, "2027-12-01T09:00:00+07:00").json()
    late = client.post("/v1/contacts/%s:retract" % created["contact_id"],
                       json={"at": "2027-12-01T09:05:00+07:00"})

    assert late.json()["code"] == "retraction_window_closed"
    assert late.json()["error_id"] != "DEBT-COL-0423"

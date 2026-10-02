"""F09 — one officer's row from the same computation `/v1/reports/team` serves
(feedback-r2 TASK-105). The case overview's scoreboard reads this and prints the
six served figures; nothing is recomputed on the screen.
"""
from fastapi.testclient import TestClient

from app.main import app


def _client():
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


def test_the_officer_row_equals_the_team_payloads_own_row():
    """Every row, not a sample: the one-officer endpoint computes narrowly
    (team_performance.officer, 2026-09-29) and must stay byte-identical to the
    team payload's own row for each officer, comparators included."""
    c = _client()
    team = c.get("/v1/reports/team").json()
    assert team["officers"], "the team payload must carry at least one officer"
    for row in team["officers"]:
        body = c.get("/v1/reports/officers/%s" % row["officer_uid"]).json()
        assert body["officer"] == row
        assert body["note_th"] and body["note_en"]
        for key in ("queue_done", "queue_today", "cases", "arrears",
                    "contact_rate", "ptp_kept_rate", "receipts_month",
                    "receipts_share", "contact_rate_vs_team", "ptp_kept_vs_team"):
            assert key in body["officer"]


def test_an_unknown_officer_uid_is_a_named_404():
    c = _client()
    response = c.get("/v1/reports/officers/nobody-here")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"

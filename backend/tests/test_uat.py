"""The UAT task script and feedback capture.

The facts under test are the ones that decide whether a feedback round is worth
running: an entry that carries no information is refused, answers are never shown to
the tester before they attempt the task, and feedback is NOT hidden per session the
way tester state is.
"""
import pytest
from fastapi.testclient import TestClient

from app import feedback as feedback_domain
from app import orders as orders_domain
from app.main import app
from app.uat_tasks import TASKS

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean():
    feedback_domain.reset()
    orders_domain.reset()
    yield
    feedback_domain.reset()
    orders_domain.reset()


# --- the task script -----------------------------------------------------------

def test_the_script_ships_the_tasks_the_limitations_and_the_ratings():
    body = client.get("/v1/uat/tasks").json()
    assert len(body["tasks"]) == len(TASKS)
    assert body["limitations"], "a tester who has not been told the limits reports the wrong things"
    assert set(body["ratings"]) == set(feedback_domain.RATINGS)


def test_every_task_says_what_to_do_and_what_we_want_to_learn():
    for task in client.get("/v1/uat/tasks").json()["tasks"]:
        assert task["do"].strip(), task["id"]
        assert task["learn"].strip(), task["id"]
        assert task["route"].startswith("/"), task["id"]


# A tester who is shown the answer is no longer testing anything.
def test_the_answers_are_never_sent_to_the_tester():
    body = client.get("/v1/uat/tasks").json()
    assert all("answer" not in task for task in body["tasks"])
    # They exist for whoever reads the feedback afterwards.
    assert all(task.get("answer") for task in TASKS)


def test_the_limitations_name_the_decided_rate_and_the_peak_gap():
    """Ruling 87 (Arina, 2026-09-09) decided the penalty rate at 0.03 %/day. The
    limitations must say the rate is decided, not unagreed, and must still warn that
    PEAK bills ten times higher (0.3 %/day) until AR moves PEAK's own setting."""
    limits = " ".join(client.get("/v1/uat/tasks").json()["limitations"])
    assert "Arina decided on 2026-09-09" in limits and "ruling" not in limits
    assert "0.03" in limits and "0.3 %/day" in limits
    assert "tenth" in limits and "AR moves" in limits
    assert "CF1" not in limits
    assert "unagreed" not in limits.lower() and "not agreed" not in limits.lower()


# --- feedback ------------------------------------------------------------------

def test_feedback_records_the_context_the_tester_should_not_have_to_describe():
    entry = client.post("/v1/feedback", json={
        "tester": "Nok", "rating": "confusing", "comment": "Could not find approve",
        "screen": "orders", "task_id": "T1", "lang": "th", "theme": "dark",
    }).json()["feedback"]
    assert entry["tester"] == "Nok"
    assert entry["screen"] == "orders"
    assert entry["task_id"] == "T1"
    # "The number is cut off" is a different bug in Thai than in English.
    assert entry["lang"] == "th"
    assert entry["theme"] == "dark"
    assert entry["id"].startswith("fb-")


def test_an_entry_with_neither_a_rating_nor_a_comment_is_refused():
    response = client.post("/v1/feedback", json={"tester": "Nok", "screen": "orders"})
    assert response.status_code == 422
    assert response.json()["code"] == "feedback_empty"
    assert client.get("/v1/feedback").json()["summary"]["total"] == 0


def test_a_rating_alone_is_enough_and_so_is_a_comment_alone():
    assert client.post("/v1/feedback", json={"rating": "blocked"}).status_code == 201
    assert client.post("/v1/feedback", json={"comment": "the table scrolls oddly"}).status_code == 201
    assert client.get("/v1/feedback").json()["summary"]["total"] == 2


def test_an_unknown_rating_is_refused_rather_than_stored_as_free_text():
    response = client.post("/v1/feedback", json={"rating": "lovely", "comment": "x"})
    assert response.status_code == 422
    assert response.json()["code"] == "feedback_rating_unknown"
    # A rating nobody can count is not a rating.
    assert "blocked" in response.json()["extensions"]["known_ratings"]


def test_an_unbounded_comment_is_refused():
    response = client.post("/v1/feedback", json={"comment": "x" * (feedback_domain.MAX_COMMENT + 1)})
    assert response.status_code == 422
    assert response.json()["code"] == "feedback_too_long"


# The distinction that matters: tester STATE is private, tester FEEDBACK is shared.
def test_feedback_is_visible_across_sessions_even_though_state_is_not():
    a, b = TestClient(app), TestClient(app)
    a.post("/v1/orders/1/approve", json={"by": "Nok"})
    a.post("/v1/feedback", json={"tester": "Nok", "rating": "works", "screen": "orders"})

    # State stays private...
    assert b.get("/v1/orders").json()["counts"]["done"] == 0
    # ...and feedback does not, because it is the output of the round.
    assert b.get("/v1/feedback").json()["summary"]["total"] == 1
    assert b.get("/v1/feedback").json()["entries"][0]["tester"] == "Nok"


def test_the_summary_counts_by_rating_and_by_screen_for_triage():
    client.post("/v1/feedback", json={"tester": "Nok", "rating": "blocked", "screen": "orders"})
    client.post("/v1/feedback", json={"tester": "Whan", "rating": "blocked", "screen": "overview"})
    client.post("/v1/feedback", json={"tester": "Whan", "rating": "works", "screen": "orders"})
    summary = client.get("/v1/feedback").json()["summary"]
    assert summary["total"] == 3
    assert summary["by_rating"]["blocked"] == 2
    assert summary["by_screen"]["orders"] == 2
    assert summary["testers"] == ["Nok", "Whan"]
    # If this ever goes false, a redeploy loses everything not yet exported.
    assert "all_written_to_disk" in summary

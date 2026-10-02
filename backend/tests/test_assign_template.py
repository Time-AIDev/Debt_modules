"""F10b / R-D — the assignment template (feedback-r2 TASK-117).

The template downloads from the app; a filled file assigns all its rows or the whole
file is refused with every bad row named — all-or-nothing, like Q5. Every test here is
an ADDITION.
"""
import pytest
from fastapi.testclient import TestClient

from app import cases as cases_domain
from app import officers
from app.main import app

MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}
OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nantapol"}


@pytest.fixture
def client():
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


def _officer():
    return next(r for r in officers.registry() if r["role"] == "OFFICER" and r["uid"] != "nantapol")


def _book_rows(client, n=3):
    rows = client.get("/v1/workbook").json()["rows"]
    out = [r for r in rows if (r["customer"].get("volt_id") or "")]
    assert len(out) >= n
    return out[:n]


def _line(row, officer_key):
    c = row["customer"]
    return "%s,%s,%s" % (c.get("volt_id") or "", c.get("customer_no") or "", officer_key)


def _upload(client, text, name="assignments.csv", headers=MANAGER):
    return client.post("/v1/imports/assignments", content=text.encode("utf-8"),
                       headers={**headers, "X-Volt-Filename": name, "Content-Type": "text/csv"})


def test_the_template_downloads_with_its_header_and_one_example(client):
    response = client.get("/v1/imports/assignments:template", headers=MANAGER)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert "assignments-template.csv" in response.headers.get("content-disposition", "")
    lines = response.text.strip().splitlines()
    assert lines[0] == "volt_id,customer_no,officer"
    assert len(lines) == 2


def test_an_officer_may_not_download_the_template(client):
    assert client.get("/v1/imports/assignments:template", headers=OFFICER).status_code == 403


def test_a_good_file_assigns_every_row_in_one_request(client):
    target = _officer()
    rows = _book_rows(client, 3)
    text = "volt_id,customer_no,officer\n" + "\n".join(_line(r, target["uid"]) for r in rows) + "\n"
    response = _upload(client, text)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 3 and len(body["assigned"]) == 3
    assert body["officer_uids"] == [target["uid"]]
    cs = cases_domain.for_current()
    for uid in body["assigned"]:
        assert cs.cases[uid]["officer_uid"] == target["uid"]
    entry = next(e for e in client.get("/v1/audit").json()["entries"] if e["act"] == "CUSTOMERS_ASSIGNED")
    assert entry["subject_type"] == "import" and entry["detail"]["mode"] == "template"
    assert entry["detail"]["count"] == 3


def test_display_names_are_accepted_for_the_officer_column(client):
    target = _officer()
    rows = _book_rows(client, 1)
    text = "volt_id,customer_no,officer\n" + _line(rows[0], target["display_name_th"]) + "\n"
    response = _upload(client, text)
    assert response.status_code == 200, response.text
    assert cases_domain.for_current().cases[rows[0]["customer"]["uid"]]["officer_uid"] == target["uid"]


def test_one_unknown_officer_refuses_the_whole_file_and_names_row_two(client):
    target = _officer()
    rows = _book_rows(client, 2)
    cs = cases_domain.for_current()
    before = {r["customer"]["uid"]: cs.cases[r["customer"]["uid"]]["officer_uid"] for r in rows}
    text = ("volt_id,customer_no,officer\n"
            + _line(rows[0], target["uid"]) + "\n"
            + _line(rows[1], "nobody-at-all") + "\n")
    response = _upload(client, text)
    assert response.status_code == 422
    errors = response.json()["errors"]
    assert [e["pointer"] for e in errors] == ["/rows/3"] and errors[0]["code"] == "officer_unknown"
    assert {r["customer"]["uid"]: cs.cases[r["customer"]["uid"]]["officer_uid"] for r in rows} == before


def test_an_unknown_customer_and_a_duplicate_key_are_both_refused_by_row(client):
    target = _officer()
    rows = _book_rows(client, 1)
    bad = _upload(client, "volt_id,customer_no,officer\nno-such-key,,%s\n" % target["uid"])
    assert bad.status_code == 422 and bad.json()["errors"][0]["pointer"] == "/rows/2"
    assert bad.json()["errors"][0]["code"] == "customer_unknown"
    duplicate = _upload(client, "volt_id,customer_no,officer\n"
                        + _line(rows[0], target["uid"]) + "\n"
                        + _line(rows[0], target["uid"]) + "\n")
    assert duplicate.status_code == 422 and duplicate.json()["errors"][0]["pointer"] == "/rows/3"
    assert duplicate.json()["errors"][0]["code"] == "duplicate"


def test_an_empty_file_and_a_wrong_header_are_refused(client):
    assert _upload(client, "").status_code == 422
    wrong = _upload(client, "name,number,officer\nA,B,C\n")
    assert wrong.status_code == 422 and wrong.json()["errors"][0]["pointer"] == "/header"

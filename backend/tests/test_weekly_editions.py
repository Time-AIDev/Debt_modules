"""Weekly report editions — the draft, the published copy, the archive and the Excel file.

The live report is always the draft. Publishing freezes it as edition N of its week;
a later edition of the same week supersedes the earlier one, and nothing is deleted.
"""
import pytest
from fastapi.testclient import TestClient

from app import audit_store, errors, imports, reports
from app.config import settings
from app.main import app

BD = settings.business_date
MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}
OWNER = {"X-Volt-Role": "OWNER", "X-Volt-Officer": "jo"}
OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "thip"}


@pytest.fixture
def client():
    return TestClient(app)


def test_the_live_report_is_the_draft_and_names_its_iso_week(client):
    body = client.get("/v1/reports/weekly").json()
    year, week, _ = BD.isocalendar()
    assert body["period"]["week"] == week and body["period"]["week_year"] == year
    assert body["edition"]["status"] == "DRAFT"
    assert body["edition"]["published_count"] == 0 and body["edition"]["latest"] is None
    assert body["edition"]["note_th"]


def test_only_a_manager_or_owner_publishes(client):
    r = client.post("/v1/reports/weekly:publish", headers=OFFICER)
    assert r.status_code == 403 and r.json()["message_th"]
    assert client.get("/v1/reports/weekly/editions").json()["editions"] == []


def test_publishing_freezes_numbered_editions_and_supersedes_the_earlier_one(client):
    first = client.post("/v1/reports/weekly:publish", headers=MANAGER)
    assert first.status_code == 201
    one = first.json()["edition"]
    assert one["number"] == 1 and one["status"] == "PUBLISHED" and one["published_by"] == "settasak"
    assert one["published_at"].startswith(str(BD))
    assert one["payload"]["period"]["label"] == one["period"]
    assert "edition" not in one["payload"], "a frozen copy must not carry the draft stamp"

    two = client.post("/v1/reports/weekly:publish", headers=OWNER).json()["edition"]
    assert two["number"] == 2 and two["published_by"] == "jo"

    listed = client.get("/v1/reports/weekly/editions").json()
    assert [e["edition_uid"] for e in listed["editions"]] == [two["edition_uid"], one["edition_uid"]]
    assert all("payload" not in e for e in listed["editions"])
    older = listed["editions"][1]
    assert older["status"] == "SUPERSEDED" and older["superseded_by"] == two["edition_uid"]

    state = client.get("/v1/reports/weekly").json()["edition"]
    assert state["status"] == "DRAFT" and state["published_count"] == 2
    assert state["latest"]["edition_uid"] == two["edition_uid"] and "payload" not in state["latest"]

    opened = client.get("/v1/reports/weekly/editions/%s" % one["edition_uid"]).json()["edition"]
    assert opened["payload"]["portfolio"] == one["payload"]["portfolio"]
    assert client.get("/v1/reports/weekly/editions/wke-99999").status_code == 404


def test_publishing_is_in_the_action_log(client):
    edition = client.post("/v1/reports/weekly:publish", headers=MANAGER).json()["edition"]
    rows = [e for e in audit_store.read({}, limit=1000, before_seq=None)
            if e.get("act") == "WEEKLY_EDITION_PUBLISHED"]
    assert rows and rows[-1]["subject_uid"] == edition["edition_uid"]


def test_the_draft_exports_as_a_readable_xlsx_with_the_served_figures(client):
    weekly = client.get("/v1/reports/weekly").json()
    r = client.post("/v1/reports/weekly:export", json={"reason": "weekly review", "lang": "th"}, headers=OFFICER)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert "-draft.xlsx" in r.headers["content-disposition"]
    sheets = imports.read_xlsx(r.content)
    assert [s["name"] for s in sheets] == ["สรุป", "การเปลี่ยนประเภท NPL", "ลำดับความสำคัญ"]
    summary = sheets[0]["rows"]
    flat = {row[0]: row[1:] for row in summary if row and row[0]}
    assert flat["สถานะ"][0].startswith("ฉบับร่าง")
    assert flat["ล่าช้า"][0] == str(weekly["portfolio"]["late"])
    assert flat["สัดส่วนล่าช้า"][0] == "%s%%" % weekly["portfolio"]["ratio_late_pct"]
    total = flat["รวม"]
    assert total[0] == weekly["management_summary"]["cash_in"]["total"]
    assert total[1] == "ไม่มีเป้า", "no target saved means no target figure, never a zero"
    rows = [e for e in audit_store.read({}, limit=1000, before_seq=None) if e.get("act") == "WEEKLY_REPORT_EXPORTED"]
    assert rows and rows[-1]["detail"]["format"] == "xlsx"


def test_an_edition_exports_its_frozen_copy_in_english(client):
    edition = client.post("/v1/reports/weekly:publish", headers=MANAGER).json()["edition"]
    r = client.post("/v1/reports/weekly:export", json={"reason": "weekly review", "edition_uid": edition["edition_uid"], "lang": "en"})
    assert r.status_code == 200
    assert "-edition-1.xlsx" in r.headers["content-disposition"]
    summary = imports.read_xlsx(r.content)[0]["rows"]
    status = next(row for row in summary if row and row[0] == "Status")
    assert status[1].startswith("Edition 1, published") and "settasak" in status[1]
    assert client.post("/v1/reports/weekly:export", json={"reason": "weekly review", "edition_uid": "wke-99999"}).status_code == 404


# --- B14 (Feedback Round 1, WP12): the export writes the five served figures -------------

from decimal import Decimal

from app import cases, weekly_export

FIVE = ("mom", "paying_customers", "npl_movement", "arrears_split", "status_changes")
FAKE_PHONE, FAKE_ID = "081-234-5678", "1-2345-67890-12-3"


def _summary(content):
    return imports.read_xlsx(content)[0]["rows"]


def _first(rows, label):
    return next(r for r in rows if r and r[0] == label)


def _dec(cell):
    return Decimal(str(cell))


def _pct(value):
    return "%s%%" % value if value is not None else "—"


def test_the_draft_export_writes_the_five_served_figures_with_their_definitions(client):
    weekly = client.get("/v1/reports/weekly").json()
    rows = _summary(client.post("/v1/reports/weekly:export", json={"reason": "weekly review", "lang": "th"}).content)
    mom = weekly["mom"]
    for key, label in (("instalment", "MoM · ค่างวด (SPV)"), ("cash_or_project", "MoM · เงินสดหรือโครงการ (EPC)"),
                       ("total", "MoM · รวมทุกหมวด")):
        row = _first(rows, label)
        assert _dec(row[1]) == Decimal(mom["this_month"][key]) and _dec(row[2]) == Decimal(mom["last_month"][key])
        assert _dec(row[3]) == Decimal(mom["change"][key]) and row[4] == _pct(mom["change_pct"][key])
    paying = weekly["paying_customers"]
    row = _first(rows, "ลูกค้าที่จ่าย (ราย)")
    assert int(row[1]) == paying["this_period"]["customers"] and int(row[2]) == paying["prior_period"]["customers"]
    assert int(row[3]) == paying["change"] and row[4] == _pct(paying["change_pct"])
    npl = weekly["npl_movement"]
    assert int(_first(rows, "เข้า NPL")[1]) == npl["entered"]["customers"]
    assert int(_first(rows, "ออกจาก NPL")[1]) == npl["left"]["customers"]
    split = weekly["arrears_split"]
    for side, label in (("true", "ค้างจริง"), ("held", "พักไว้ฝั่งบริษัท"), ("total", "ยอดค้างทั้งหมด")):
        row = _first(rows, label)
        assert [_dec(c) for c in row[1:5]] == [Decimal(split[side][k]) for k in ("instalment", "cash_or_project", "unrouted", "total")]
        assert int(row[5]) == split[side]["customers"]
    for key in FIVE:
        block = weekly[key]
        assert any(block["definition_th"] in r for r in rows), key
        assert not any(block["definition"] in r for r in rows), key
        for note in block["notes"]:
            assert any(note["th"] in r for r in rows), (key, note["code"])


@pytest.mark.parametrize("lang,label,other", [
    ("th", "ลูกค้าที่จ่าย (ราย)", "Paying customers"),
    ("en", "Paying customers", "ลูกค้าที่จ่าย (ราย)"),
])
def test_weekly_xlsx_language_variants_keep_the_api_totals(client, lang, label, other):
    payload = client.get("/v1/reports/weekly").json()
    rows = _summary(client.post("/v1/reports/weekly:export",
                                json={"reason": "weekly parity", "lang": lang}).content)
    row = _first(rows, label)
    paying = payload["paying_customers"]
    assert [int(row[i]) for i in (1, 2, 3)] == [
        paying["this_period"]["customers"], paying["prior_period"]["customers"], paying["change"]]
    assert not any(r and r[0] == other for r in rows)


def test_the_pinned_summary_labels_still_name_exactly_one_row_each(client):
    rows = _summary(client.post("/v1/reports/weekly:export", json={"reason": "weekly review", "lang": "th"}).content)
    firsts = [r[0] for r in rows if r and r[0]]
    for label in ("สถานะ", "ล่าช้า", "สัดส่วนล่าช้า", "รวม"):
        assert firsts.count(label) == 1, label


def test_a_status_change_is_written_with_who_and_why_and_no_typed_number_reaches_the_file():
    shared = TestClient(app)
    shared.cookies.set("volt_session", "shared")        # the session cases.for_current() reads outside a request
    late = next(c for c in cases.for_current().cases.values() if c["payment_status"] == "LATE")
    r = shared.post("/v1/cases/by-customer/%s/payment-status" % late["customer_uid"],
                    json={"code": "NPL", "reason": "ผิดนัด โทร %s บัตร %s" % (FAKE_PHONE, FAKE_ID)},
                    # AUTHORISED TEST EDIT 43 (R-B): Manager-only manual status.
                    headers={"X-Volt-Role": "MANAGER", "X-Volt-Officer": "nantapol"})
    assert r.status_code == 200
    served = shared.get("/v1/reports/weekly").json()["status_changes"]["rows"][0]
    sheets = imports.read_xlsx(shared.post("/v1/reports/weekly:export", json={"reason": "weekly review", "lang": "th"}).content)
    row = next(r for r in sheets[0]["rows"] if "nantapol" in r and served["reason"] in r)
    assert "LATE" in row and "NPL" in row
    for sheet in sheets:
        for cells in sheet["rows"]:
            for cell in cells:
                assert FAKE_PHONE not in str(cell) and FAKE_ID not in str(cell)


def test_an_edition_frozen_before_the_figures_says_not_sent_and_the_writer_never_sums(client):
    payload = client.get("/v1/reports/weekly").json()
    payload.pop("edition", None)
    frozen = {k: v for k, v in payload.items() if k not in FIVE}
    rows = _summary(weekly_export.build(frozen, None, lang="en"))
    titles = ("Month on month: instalments / cash", "Paying customers this week · WoW",
              "Into / out of NPL this week", "True arrears vs held on the company side", "Payment-status changes (Late/NPL)")
    for title in titles:
        assert _first(rows, title)[1] == "Not sent by the API yet", title

    made_up = dict(frozen, mom={
        "this_month": {"start": "2026-10-01", "end": "2026-10-23", "instalment": "5.00", "cash_or_project": "7.00", "total": "1.00"},
        "last_month": {"start": "2026-09-01", "end": "2026-09-23", "instalment": "0.00", "cash_or_project": "0.00", "total": "0.00"},
        "change": {"instalment": "9.99", "cash_or_project": "7.00", "total": "1.00"},
        "change_pct": {"instalment": None, "cash_or_project": None, "total": None},
        "indicative": True, "definition": "def EN", "definition_th": "นิยาม",
        "notes": [{"code": "X", "en": "note EN", "th": "โน้ต"}]})
    rows = _summary(weekly_export.build(made_up, None, lang="en"))
    assert _first(rows, "Month on month: instalments / cash")[1] == "Indicative figure"
    assert _dec(_first(rows, "MoM · All lines")[1]) == Decimal("1.00")          # served 1.00, never 5 + 7
    assert _dec(_first(rows, "MoM · Instalments (SPV)")[3]) == Decimal("9.99")
    assert _first(rows, "MoM · Instalments (SPV)")[4] == "—"
    assert any("def EN" in r for r in rows) and any("note EN" in r for r in rows)
    assert not any("นิยาม" in r for r in rows) and not any("โน้ต" in r for r in rows)


# --- Fix round 2 (review findings I2 and M3) ---------------------------------------
#
# The gate is audit-before-raise: the act is named before anything that can throw, so a
# failure is legible in the action log. Before the fix these two routes described
# themselves only after the store work had already succeeded, and a failed publish or
# export landed in the log with verb, route and actor but a blank act and subject.


def _last_row_for(route_suffix):
    rows = [e for e in audit_store.read({}, limit=1000, before_seq=None)
            if (e.get("route_template") or "").endswith(route_suffix)]
    assert rows, "the middleware logged nothing for %s" % route_suffix
    return rows[0]          # audit_store.read is newest first (seq DESC)


def test_a_failed_publish_is_logged_with_the_act_it_attempted(client, monkeypatch):
    def boom(*a, **k):
        raise errors.internal_error()
    monkeypatch.setattr(reports, "publish_edition", boom)
    r = client.post("/v1/reports/weekly:publish", headers=MANAGER)
    assert r.status_code == 500
    row = _last_row_for("weekly:publish")
    assert row["status"] == 500
    assert row["act"] == "WEEKLY_EDITION_PUBLISHED", \
        "a publish that blew up must still say in the log that a publish was what failed"


def test_a_failed_export_is_logged_with_the_act_and_the_edition_it_attempted(client, monkeypatch):
    edition = client.post("/v1/reports/weekly:publish", headers=MANAGER).json()["edition"]

    def boom(*a, **k):
        raise errors.internal_error()
    monkeypatch.setattr(reports, "edition", boom)
    r = client.post("/v1/reports/weekly:export", json={"reason": "weekly review", "edition_uid": edition["edition_uid"]})
    assert r.status_code == 500
    row = _last_row_for("weekly:export")
    assert row["act"] == "WEEKLY_REPORT_EXPORTED"
    assert row["subject_uid"] == edition["edition_uid"], \
        "the uid came off the body and was known before the read — the log must carry it"
    assert row["detail"]["format"] == "xlsx"


def test_a_failed_draft_export_is_logged_with_its_act(client, monkeypatch):
    def boom(*a, **k):
        raise errors.internal_error()
    monkeypatch.setattr(reports, "weekly", boom)
    assert client.post("/v1/reports/weekly:export", json={"reason": "weekly review"}).status_code == 500
    assert _last_row_for("weekly:export")["act"] == "WEEKLY_REPORT_EXPORTED"


@pytest.mark.parametrize("uid", [123, ["a"], {"x": 1}, True, 0.5])
def test_a_non_string_edition_uid_is_the_404_refusal_not_a_crash(client, uid):
    r = client.post("/v1/reports/weekly:export", json={"reason": "weekly review", "edition_uid": uid})
    assert r.status_code == 404, "a junk edition_uid is an unknown edition, not a server fault"
    assert r.json()["message_th"]


def test_r16_an_export_without_a_reason_is_refused_and_the_reason_is_logged(client):
    for body in ({}, {"reason": "   "}, {"reason": 7}):
        r = client.post("/v1/reports/weekly:export", json=body)
        assert r.status_code == 422 and r.json()["message_th"]
        assert _last_row_for("weekly:export")["act"] == "WEEKLY_REPORT_EXPORTED"
    assert client.post("/v1/reports/weekly:export", json={"reason": " board pack "}).status_code == 200
    assert _last_row_for("weekly:export")["detail"]["reason"] == "board pack"

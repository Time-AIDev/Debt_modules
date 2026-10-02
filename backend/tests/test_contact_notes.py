"""More than one note per contact, and a note that is not a contact at all."""
from fastapi.testclient import TestClient

from app.main import app
from tests.test_attachments_guard import _png

client = TestClient(app)
OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nantapol"}


def _late_customer():
    return next(i for i in client.get("/v1/today", headers=OFFICER).json()["items"]
                if i["case"]["payment_status"] == "LATE" and i["contact_lock"]["state"] == "OPEN")["customer"]["uid"]


def _attachment():
    return client.post("/v1/attachments", content=_png(), headers={**OFFICER, "X-Volt-Filename": "slip.png",
                                                                     "Content-Type": "application/octet-stream"}).json()["attachment"]["uid"]


def _attachment_attached_to(target):
    """Task 24's dialog uploads a note's files pre-attached, X-Volt-Attach-To beside
    the body (routers/attachments.py:81)."""
    return client.post("/v1/attachments", content=_png(),
                       headers={**OFFICER, "X-Volt-Filename": "slip.png", "Content-Type": "application/octet-stream",
                                "X-Volt-Attach-To": target}).json()["attachment"]["uid"]


def _saved_contact(uid):
    return client.post("/v1/cases/by-customer/%s/contacts" % uid, headers=OFFICER, json={
        "result": "REACHED_ANSWERED", "channel": "PHONE", "counted": True, "next_action": "CALL",
        "next_action_on": "2026-10-24"}).json()["contact"]


def test_a_contact_may_carry_several_notes_each_with_its_files():
    uid = _late_customer()
    a1, a2 = _attachment(), _attachment()
    r = client.post("/v1/cases/by-customer/%s/contacts" % uid, headers=OFFICER, json={
        "result": "REACHED_ANSWERED", "channel": "PHONE", "counted": True, "next_action": "CALL", "next_action_on": "2026-10-24",
        "notes": [{"text": "ลูกค้าแจ้งว่าจะโอนพรุ่งนี้", "attachment_uids": [a1]}, {"text": "ส่งลิงก์แล้ว", "attachment_uids": [a2]}]})
    assert r.status_code == 201, r.json()
    row = r.json()["contact"]
    assert [n["text"] for n in row["notes"]] == ["ลูกค้าแจ้งว่าจะโอนพรุ่งนี้", "ส่งลิงก์แล้ว"]
    assert row["note"] == "ลูกค้าแจ้งว่าจะโอนพรุ่งนี้"
    assert row["notes"][0]["attachments"][0]["uid"] == a1 and row["notes"][0]["attachments"][0]["attached_to"] == "contact:%s" % row["uid"]


def test_a_note_can_be_added_to_a_saved_contact_later():
    uid = _late_customer()
    row = client.post("/v1/cases/by-customer/%s/contacts" % uid, headers=OFFICER, json={
        "result": "REACHED_ANSWERED", "channel": "PHONE", "counted": True, "next_action": "CALL", "next_action_on": "2026-10-24"}).json()["contact"]
    r = client.post("/v1/contacts/%s/notes" % row["uid"], headers=OFFICER, json={"text": "เพิ่มเติม"})
    assert r.status_code == 201 and r.json()["note"]["text"] == "เพิ่มเติม"
    detail = client.get("/v1/cases/by-customer/%s" % uid, headers=OFFICER).json()
    assert [n["text"] for n in next(c for c in detail["contact_log"] if c["uid"] == row["uid"])["notes"]] == ["เพิ่มเติม"]


def test_a_case_note_is_an_event_not_a_contact_and_spends_no_slot():
    uid = _late_customer()
    before = client.get("/v1/cases/by-customer/%s" % uid, headers=OFFICER).json()
    r = client.post("/v1/cases/by-customer/%s/notes" % uid, headers=OFFICER, json={"text": "บันทึกเฉย ๆ"})
    assert r.status_code == 201 and r.json()["event"]["kind"] == "NOTE_ADDED"
    after = client.get("/v1/cases/by-customer/%s" % uid, headers=OFFICER).json()
    assert len(after["contact_log"]) == len(before["contact_log"])
    assert after["work_item"]["contact_lock"]["state"] == "OPEN"
    assert any(e["kind"] == "NOTE_ADDED" and e["text"] == "บันทึกเฉย ๆ" for e in after["events"])


def test_an_empty_note_and_too_many_files_are_refused():
    uid = _late_customer()
    assert client.post("/v1/cases/by-customer/%s/notes" % uid, headers=OFFICER, json={"text": "  "}).status_code == 422
    r = client.post("/v1/cases/by-customer/%s/notes" % uid, headers=OFFICER,
                    json={"text": "x", "attachment_uids": ["a"] * 6})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "too_many_attachments"


def test_an_unknown_attachment_uid_on_a_case_note_is_refused_and_writes_no_event():
    """Controller ruling: pre-flight refuses BEFORE any write — an unknown or
    already-attached uid must never silently drop out of the note (the brief's
    own `if rec:` would have done exactly that)."""
    uid = _late_customer()
    before = client.get("/v1/cases/by-customer/%s" % uid, headers=OFFICER).json()
    r = client.post("/v1/cases/by-customer/%s/notes" % uid, headers=OFFICER,
                    json={"text": "x", "attachment_uids": ["att-does-not-exist"]})
    assert r.status_code == 422
    assert r.json()["errors"][0]["code"] == "attachment_unknown"
    after = client.get("/v1/cases/by-customer/%s" % uid, headers=OFFICER).json()
    assert len(after["events"]) == len(before["events"])
    assert not any(e["kind"] == "NOTE_ADDED" for e in after["events"])


def test_log_contact_with_a_second_empty_note_is_refused_and_writes_nothing():
    """Controller ruling: every note in `log_contact` is checked in the pre-flight
    block, before the ptp/issue block — a refused note leaves no half-written
    contact, PTP or issue, and the contact_log length must not move."""
    uid = _late_customer()
    before = client.get("/v1/cases/by-customer/%s" % uid, headers=OFFICER).json()
    r = client.post("/v1/cases/by-customer/%s/contacts" % uid, headers=OFFICER, json={
        "result": "REACHED_ANSWERED", "channel": "PHONE", "counted": True, "next_action": "CALL", "next_action_on": "2026-10-24",
        "notes": [{"text": "ok"}, {"text": "  "}]})
    assert r.status_code == 422
    after = client.get("/v1/cases/by-customer/%s" % uid, headers=OFFICER).json()
    assert len(after["contact_log"]) == len(before["contact_log"])


def test_a_file_already_attached_to_this_contact_is_accepted():
    """Controller amendment: Task 24's dialog uploads a saved contact's evidence
    files already attached to this note's own target (contact:<uid>) — that file
    must be accepted, not refused as 'already attached'."""
    uid = _late_customer()
    row = _saved_contact(uid)
    att = _attachment_attached_to("contact:%s" % row["uid"])
    r = client.post("/v1/contacts/%s/notes" % row["uid"], headers=OFFICER, json={"text": "หลักฐาน", "attachment_uids": [att]})
    assert r.status_code == 201, r.json()
    assert r.json()["note"]["attachments"][0]["uid"] == att


def test_a_file_attached_to_a_different_contact_is_refused():
    """The same pre-attached file offered to a DIFFERENT contact's notes route is
    still refused — attached_to must equal THIS note's own target, not just be set."""
    row_a = _saved_contact(_late_customer())
    row_b = _saved_contact(_late_customer())
    att = _attachment_attached_to("contact:%s" % row_a["uid"])
    r = client.post("/v1/contacts/%s/notes" % row_b["uid"], headers=OFFICER, json={"text": "x", "attachment_uids": [att]})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "attachment_unknown"

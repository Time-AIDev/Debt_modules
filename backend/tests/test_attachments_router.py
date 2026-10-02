import urllib.parse

from fastapi.testclient import TestClient

from app.attachments import scanner
from app.main import app
from tests.test_attachments_guard import _png

client = TestClient(app)
OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nantapol"}
OTHER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "thip"}
MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}


def _upload(raw=None, name="site.png", headers=OFFICER, attach_to=None):
    h = {**headers, "X-Volt-Filename": name, "Content-Type": "application/octet-stream"}
    if attach_to:
        h["X-Volt-Attach-To"] = attach_to
    return client.post("/v1/attachments", content=raw if raw is not None else _png(), headers=h)


def test_a_clean_file_is_stored_and_answers_without_its_bytes():
    r = _upload(attach_to="contact:ct-1")
    assert r.status_code == 201, r.json()
    att = r.json()["attachment"]
    assert att["kind"] == "PNG" and att["scan_state"] == "RULES_ONLY" and "bytes" not in att
    assert att["attached_to"] == "contact:ct-1" and att["durable"] in (True, False)


def test_a_refused_file_names_the_rule_in_thai():
    r = _upload(raw=b"%PDF-1.4\n/JavaScript\n%%EOF", name="a.pdf")
    assert r.status_code == 422
    body = r.json()
    assert body["errors"][0]["code"] == "pdf_active_content" and body["errors"][0]["message_th"]


def test_the_download_is_a_post_with_attachment_disposition_and_nosniff():
    uid = _upload().json()["attachment"]["uid"]
    r = client.post("/v1/attachments/%s:download" % uid, headers=OFFICER)
    assert r.status_code == 200 and r.content == _png()
    assert r.headers["content-type"].startswith("image/png")
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_only_the_uploader_or_a_manager_may_delete():
    uid = _upload().json()["attachment"]["uid"]
    assert client.post("/v1/attachments/%s:delete" % uid, headers=OTHER).status_code == 403
    assert client.post("/v1/attachments/%s:delete" % uid, headers=MANAGER).status_code == 200
    assert client.post("/v1/attachments/%s:download" % uid, headers=OFFICER).status_code == 404


def test_an_infected_or_unreachable_scanner_is_never_a_stored_file(monkeypatch):
    monkeypatch.setattr(scanner, "scan", lambda raw: (_ for _ in ()).throw(scanner.Infected("Eicar")))
    r = _upload()
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "file_infected"
    monkeypatch.setattr(scanner, "scan", lambda raw: (_ for _ in ()).throw(scanner.ScannerUnavailable("down")))
    r = _upload()
    assert r.status_code == 503 and r.json()["code"] == "scanner_unavailable"


def test_the_list_for_a_target_carries_metadata_only():
    _upload(attach_to="note:ev-9")
    r = client.get("/v1/attachments", params={"attached_to": "note:ev-9"}, headers=OFFICER)
    assert r.status_code == 200 and r.json()["attachments"][0]["filename"] == "site.png"


def test_a_percent_encoded_thai_name_is_stored_and_served_decoded():
    """Task 25a: the browser sends X-Volt-Filename: encodeURIComponent(file.name) —
    the router must decode it before the guard sanitises, so a Thai file name is
    stored (and served back) as the real name, not hex."""
    name = "สลิปโอนเงิน.png"
    r = _upload(name=urllib.parse.quote(name))
    assert r.status_code == 201, r.json()
    assert r.json()["attachment"]["filename"] == name

"""Language pass: every Thai display string the Settings / Data sources / PEAK / users
surfaces serve has a plain-English twin — non-empty, no Thai script, no internal codes."""
import re

from fastapi.testclient import TestClient

from app import dictionaries, imports, user_accounts
from app.main import app
from app.money import band_sets
from app.routers import peak_pipeline

THAI = re.compile(r"[฀-฾เ-๿]")
CODE = re.compile(r"\b(CF1|C3|C5|R12|OD-\d+|OQ-\d+|SVC-\d+|REQ-[A-Z]+-\d+|DEBT-[A-Z]+-\d+|W10|S12)\b|[Rr]uling \d+|band_set_code")
MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}


def english(text):
    assert text and not THAI.search(text) and not CODE.search(text), text


def test_dictionary_contact_reasons_have_english():
    for row in dictionaries.SEED["CONTACT_RESULT"]:
        english(row["counts_reason_en"])


def test_band_sets_and_chooser_serve_english():
    body = TestClient(app).get("/v1/band-sets", headers=MANAGER).json()
    english(body["edit_refusal_en"])
    for bs in body["band_sets"]:
        english(bs["label_en"])
        english(bs["reason_en"])
        for band in bs["bands"]:
            english(band["label_en"])
    for row in body["chooser"]:
        english(row["label_en"])
    assert band_sets.label_for("OPERATIONAL", "RISK_REVIEW", "en") == "30+ days overdue"
    english(band_sets.label_for("OPERATIONAL", "NPL_CONFIRMED", "en"))


def test_import_run_and_peak_notes_have_english():
    source = open(imports.__file__, encoding="utf-8").read()
    assert source.count('"reason_en"') >= 3 and '"installed_note_en"' in source
    for text in [user_accounts.NOT_DURABLE_EN, peak_pipeline._AFTER_APPLY_FAILED_EN,
                 *peak_pipeline._REFUSED_TITLE.values()]:
        english(text)

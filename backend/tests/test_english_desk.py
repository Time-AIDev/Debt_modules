"""Language pass (README step 7) — the desk's served display strings carry an English
twin: present, non-empty, no Thai script and no internal codes."""
import re

from fastapi.testclient import TestClient

from app import today as today_domain
from app.main import app
from app.routers import today as today_router

THAI = re.compile(r"[฀-฾เ-๿]")   # ฿ is a currency sign, not Thai prose
CODE = re.compile(r"\b(CF1|C3|C5|R12|OD-\d+|OQ-\d+|SVC-\d+|REQ-[A-Z]+-\d+|DEBT-[A-Z]+-\d+|W10|S12|J\d-\d+)\b|[Rr]uling \d+")


def english(text):
    assert isinstance(text, str) and text.strip(), repr(text)
    assert not THAI.search(text), text
    assert not CODE.search(text), text


def test_today_rows_and_meta_carry_english_twins():
    body = TestClient(app).get("/v1/today").json()
    meta = body["meta"]
    english(meta["counts_note_en"])
    english(meta["officer_totals_note_en"])
    for code, label in {**meta["tier_labels_en"], **meta["tier_labels_en_cash"]}.items():
        english(label)
    assert body["items"]
    for item in body["items"]:
        english(item["tier_label_en"])
        english(item["tier_reason_en"])
        english(item["missed_count_label_en"])
        english(item["aging_bucket_label_en"]) if item.get("aging_bucket") else None
        assert (item["missed_basis_th"] is None) == (item["missed_basis_en"] is None)
        if item["missed_basis_en"]:
            english(item["missed_basis_en"])
        tiering = item["next_action_tiering"]
        assert (tiering["reason_th"] is None) == (tiering["reason_en"] is None)
        if tiering["reason_en"]:
            english(tiering["reason_en"])
        for step in item["ladder"]["steps"]:
            english(step["act_en"])


def test_prose_constants_are_english():
    for text in (today_domain.PTP_HISTORY_NOTE_EN, today_domain.OFFICER_TOTALS_NOTE_EN, today_domain.COUNTS_NOTE_EN,
                 today_router.PAYMENT_LINK_NONE_EN, today_router.ALLOCATION_NOTE_STANDING_EN):
        english(text)


def test_reminders_and_officers_notes_are_english():
    client = TestClient(app)
    meta = client.get("/v1/today/reminders").json()["meta"]
    english(meta["note_en"])
    english(meta["offsets_conflict"]["note_en"])
    english(client.get("/v1/officers").json()["meta"]["note_en"])


def test_case_page_notes_from_the_desk_router_are_english():
    client = TestClient(app)
    uid = client.get("/v1/today").json()["items"][0]["customer"]["uid"]
    case = client.get("/v1/cases/by-customer/%s" % uid).json()
    english(case["allocation_note_standing_en"])
    english(case["sheet_reconciliation"]["note_en"])
    for inv in case["invoices"]:
        english(inv["payment_link_note_en"])


def test_tier_reasons_name_setters_and_next_actions_in_words_not_codes():
    raw = re.compile(r"\b(SEED|SYSTEM|MAPLOG_IMPORT|CALL|FOLLOW_PTP|AWAIT_\w+)\b")
    case = {"next_action_on": "2026-01-01", "next_action_set_by": "SEED", "next_action": "CALL"}
    for reason in today_domain.next_action_tiering(case, "ROUTINE")["reason_th"], \
            today_domain.next_action_tiering(case, "ROUTINE")["reason_en"]:
        assert not raw.search(reason), reason
    body = TestClient(app).get("/v1/today").json()
    for item in body["items"]:
        for text in (item["tier_reason_th"], item["tier_reason_en"],
                     item["next_action_tiering"]["reason_th"] or "", item["next_action_tiering"]["reason_en"] or ""):
            assert not raw.search(text), text
    assert today_domain.next_action_label("CALL", "en") != "CALL"

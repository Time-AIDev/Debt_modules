"""Language pass: every case-page display sentence served in Thai has a plain-English
`_en` twin — non-empty, no Thai script (฿ allowed), no internal codes."""
import re

import pytest
from fastapi.testclient import TestClient

from app import cases as cases_domain
from app import payment_position, peak_documents
from app.main import app

THAI = re.compile(r"[฀-฾เ-๿]")
CODE = re.compile(r"\b(CF1|C3|C5|R12|OD-\d+|OQ-\d+|SVC-\d+|REQ-[A-Z]+-\d+|DEBT-[A-Z]+-\d+|W10|S12)\b|[Rr]uling \d+")
BASES = ("dc_status_reason", "note", "penalty_formula", "peak_state_note", "link_sent_note",
         "state_note", "question", "lineage_note", "fee_clock_note")


def _walk(node, found):
    if isinstance(node, dict):
        for base in BASES:
            if node.get(base + "_th") and (base + "_en") in node:
                found.setdefault(base, []).append(node[base + "_en"])
        for value in node.values():
            _walk(value, found)
    elif isinstance(node, list):
        for value in node:
            _walk(value, found)


ID = re.compile(r"\d{8,}_.*?_[A-Z]{2,}\b")    # a VOLT id carries the customer's name; ids are not translated


def _english(text):
    from app import main
    assert text and text.strip(), "empty English twin"
    bare = ID.sub("", text)
    for customer in main.CUSTOMERS:              # nor are customer names
        if customer.display_name:
            bare = bare.replace(customer.display_name, "")
    assert not THAI.search(bare), text
    assert not CODE.search(text), text


@pytest.fixture
def client():
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


def test_case_detail_and_reviews_carry_english_twins(client):
    found = {}
    uids = [c["customer_uid"] for c in list(cases_domain.for_current().cases.values())[:40]]
    for uid in uids:
        _walk(client.get("/v1/cases/by-customer/%s" % uid).json(), found)
    _walk(client.get("/v1/reviews").json(), found)
    for base in ("dc_status_reason", "note", "penalty_formula", "peak_state_note", "link_sent_note", "question"):
        assert found.get(base), "no %s_en served" % base
    for texts in found.values():
        for text in texts:
            _english(text)


def test_composed_twins_in_both_languages():
    for label in cases_domain.POWER_STATE_LABEL_EN.values():
        _english(label)
    for state in ("UNSENT", "PENDING", "DRAFT_CREATED", "APPROVED_IN_PEAK"):
        _english(peak_documents.annotate({"state": state})["state_note_en"])
    for text in (*payment_position.NOTE_RECEIPT_EN.values(), payment_position.NOTE_UNKNOWN_EN):
        _english(text)
    run = cases_domain.unreachable_run(cases_domain.for_current(), "nobody")
    _english(run["note_en"])


def test_a_pre_install_case_never_puts_thai_in_its_english_reason():
    state = cases_domain.CaseState()
    case = cases_domain.open_pre_install_case(state, "cu-x", "C-X", "name", None, "thip",
                                              reason_th="เหตุผลภาษาไทย")
    assert case["opened_reason_th"] == "เหตุผลภาษาไทย"
    assert not THAI.search(case["opened_reason_en"])

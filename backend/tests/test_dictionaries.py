"""REQ-CFG-020 — governed dictionaries seeded from the sheet's own vocabulary."""
import pytest

from app import dictionaries
from app.dictionaries import DictionaryError


@pytest.fixture(autouse=True)
def fresh():
    dictionaries.reset()
    yield
    dictionaries.reset()


def test_dc_status_is_the_sheets_dropdown_in_order():
    codes = [v["code"] for v in dictionaries.for_current().list("DC_STATUS")]
    assert codes[:12] == [
        "NO_ACTION", "UNREACHABLE", "EXTEND_PAYMENT_TO", "CONTACT_BACK", "TECH_ISSUE",
        "POWER_CUTOFF", "POWER_BILL_ISSUE", "RESTRUCTURE_LOAN", "LEGAL_LETTER",
        "RETRIEVE_ASSET", "VISIT_CUSTOMER", "TERMINATE_CONTRACT",
    ]


def test_sheet_spellings_resolve_to_codes():
    d = dictionaries.for_current()
    assert d.resolve("DC_STATUS", "Power Cutoff") == "POWER_CUTOFF"
    assert d.resolve("DC_STATUS", "POWER_CUTOFF") == "POWER_CUTOFF"
    assert d.resolve("NPL_TYPE", "NPL 2 - Cooperative - Decommission") == "NPL_2_COOPERATIVE_DECOMMISSION"
    assert d.resolve("DC_STATUS", None) is None


def test_unknown_value_refuses():
    with pytest.raises(DictionaryError):
        dictionaries.for_current().resolve("DC_STATUS", "Made Up")


def test_contact_results_carry_the_act_counting_flag():
    rows = {v["code"]: v for v in dictionaries.for_current().list("CONTACT_RESULT")}
    assert rows["REACHED_ANSWERED"]["counts"] is True
    assert rows["UNREACHABLE_NO_ANSWER"]["counts"] is False
    assert rows["INBOUND"]["counts"] is False
    assert rows["REFUSED_PAY"]["flag"] is True


def test_deactivate_never_deletes():
    d = dictionaries.for_current()
    d.deactivate("DC_STATUS", "VISIT_CUSTOMER", by="manager")
    assert "VISIT_CUSTOMER" not in [v["code"] for v in d.list("DC_STATUS")]
    assert d.get("DC_STATUS", "VISIT_CUSTOMER")["active"] is False
    assert d.label("DC_STATUS", "VISIT_CUSTOMER", "th") == "ลงพื้นที่พบลูกค้า"
    assert d.history[-1]["act"] == "DEACTIVATE"


def test_add_refuses_duplicates_and_records_who():
    d = dictionaries.for_current()
    row = d.add("NEXT_ACTION", "MEET_AT_OFFICE", "นัดพบที่สำนักงาน", "Meet at the office", by="manager")
    assert row["created_by"] == "manager"
    with pytest.raises(ValueError):
        d.add("NEXT_ACTION", "MEET_AT_OFFICE", "x", "y", by="manager")


def test_every_value_has_both_labels():
    d = dictionaries.for_current()
    for name in dictionaries.DICTIONARIES:
        for v in d.list(name, include_inactive=True):
            assert v["label_th"] and v["label_en"], (name, v["code"])

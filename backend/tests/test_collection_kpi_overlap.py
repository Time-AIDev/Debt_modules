"""B13 fix round 2 (controller ruling): the monthly KPI's cash_received and the weekly
report's mom are both labelled `cash_received`, so one payment on record twice — a
receipt recorded here and the PEAK report receipt for the same invoice — must read the
same in both: counted once, through weekly_figures.counted_receipts, badged and noted.

A new file on purpose: test_round5_kpi.py is pinned and is not edited.
"""
from datetime import timedelta

from fastapi.testclient import TestClient

from app import collection_kpi, journey
from app.main import app

from tests.test_weekly_figures import (BD, _apply_peak, _codes, _customer, _peak_lease_customer, _peak_row,  # noqa: F401
                                       _record_then_peak_says_paid, client)

OCTOBER = {"measure": "cash_received", "month": "2026-10"}


def test_the_monthly_kpi_counts_a_payment_on_record_twice_once_and_says_so(client):
    before = client.get("/v1/reports/collection", params=OCTOBER).json()["indicator"]
    assert (before["actual"], before["receipts"], before["indicative"]) == ("0.00", 0, False)
    _record_then_peak_says_paid(client, ["8399.00"])
    ind = client.get("/v1/reports/collection", params=OCTOBER).json()["indicator"]
    assert (ind["actual"], ind["receipts"]) == ("8399.00", 1)
    assert before["overlap_note"] is None and before["overlap_note_th"] is None
    # the same label, the same figure: weekly mom's October reads the same payment once
    mom = client.get("/v1/reports/weekly").json()["mom"]["this_month"]
    assert (ind["actual"], ind["receipts"]) == (mom["total"], mom["receipts"])
    # seed: 20,000.00 + 399.00 on two receipts; the folded payment adds one, once
    assert (ind["receipts_all_time"], ind["receipts_all_time_amount"]) == (3, "28798.00")
    # PEAK's side is allocated (peak_report_allocates), so the one payment is not an OD-02 exception
    assert (ind["unallocated_receipts"], ind["unallocated_pending_decision"]) == (0, None)
    assert ind["indicative"] is True
    assert ind["overlap_note"].startswith("1 payment(s) are on record twice") and "16798.00" in ind["overlap_note"]
    assert "(counted 8399.00)" in ind["overlap_note"]
    assert ind["overlap_note_th"].startswith("การชำระ 1 รายการมีบันทึกซ้ำ") and "(นับ 8399.00)" in ind["overlap_note_th"]
    assert collection_kpi.cash_received("2026-10")["indicator"]["actual"] == "8399.00"


def test_a_month_the_overlap_does_not_touch_is_not_badged(client):
    _record_then_peak_says_paid(client, ["8399.00"])
    september = client.get("/v1/reports/collection", params={"measure": "cash_received", "month": "2026-09"}).json()
    ind = september["indicator"]
    assert (ind["actual"], ind["indicative"]) == ("20000.00", False)
    assert (ind["overlap_note"], ind["overlap_note_th"]) == (None, None)


def test_a_flagged_receipt_in_the_month_badges_the_kpi_and_is_named_like_weekly_mom(client):
    """B13b: a receipt flagged invoice_moved_to_other_customer, beside another
    customer's PEAK receipt for the same money, is counted as recorded (so the month
    may hold one payment twice) — the KPI says so, as weekly mom already does."""
    customer = _peak_lease_customer()
    _apply_peak(customer, _peak_row("PAID", paid_on="2026-10-20"), as_of=str(BD))
    journey.reset()
    other = _customer("CASH", 0).contracts[0]
    moved = journey.make_receipt(journey.for_current(), other.uid, other.entity, "8399.00", BD - timedelta(days=1),
                                 invoice_uid="inv-pk-IVT-9", matched="FULL")
    moved["invoice_moved_to_other_customer"] = True
    ind = client.get("/v1/reports/collection", params=OCTOBER).json()["indicator"]
    assert (ind["actual"], ind["receipts"]) == ("16798.00", 2)
    assert ind["indicative"] is True
    assert ind["flagged_note"].startswith("1 receipt(s) from 2026-10-01 to 2026-10-31, 8399.00 in all")
    assert ind["flagged_note_th"].startswith("ใบเสร็จ 1 ใบช่วง 2026-10-01 ถึง 2026-10-31 รวม 8399.00")
    assert ind["overlap_note"] is None
    mom = client.get("/v1/reports/weekly").json()["mom"]
    assert mom["indicative"] is True and "FLAGGED_RECEIPTS_IN_SPAN" in _codes(mom)
    september = client.get("/v1/reports/collection", params={"measure": "cash_received", "month": "2026-09"}).json()
    assert (september["indicator"]["indicative"], september["indicator"]["flagged_note"],
            september["indicator"]["flagged_note_th"]) == (False, None, None)


# === Final fix F-R2 ========================================================================
#
# cash_received is the monthly twin of weekly mom, reading the same counted_receipts — so a
# session that has not reseeded since a later apply must badge it the same way mom is badged
# (test_weekly_figures.py's own F-R2 test): indicative, with a PEAK_REPORT_NOT_IN_SESSION
# note naming the book's date, and its OWN date served, not the book's.

def test_the_monthly_kpi_badges_a_report_this_session_has_not_reseeded_since(client):
    from app import session as session_domain

    session_b = TestClient(app)
    session_b.cookies.set("volt_session", "fr2-kpi-session-b")
    before = session_b.get("/v1/reports/collection", params=OCTOBER).json()["indicator"]
    assert before["peak_report_as_of"] is None

    customer = _peak_lease_customer()
    _apply_peak(customer, _peak_row("PAID", paid_on=str(BD), paid="8399.00"), as_of=str(BD))
    token = session_domain.CURRENT.set("shared")
    try:
        journey.reseed_peak(journey.for_current(), BD)
    finally:
        session_domain.CURRENT.reset(token)

    ind_a = client.get("/v1/reports/collection", params=OCTOBER).json()["indicator"]
    ind_b = session_b.get("/v1/reports/collection", params=OCTOBER).json()["indicator"]
    session_c = TestClient(app)
    session_c.cookies.set("volt_session", "fr2-kpi-session-c")
    ind_c = session_c.get("/v1/reports/collection", params=OCTOBER).json()["indicator"]

    # A reseeded for itself: no gap note, its own date is the one just applied.
    assert ind_a["peak_report_not_in_session_note"] is None
    assert ind_a["peak_report_not_in_session_note_th"] is None
    assert ind_a["peak_report_as_of"] == str(BD)

    # B never reset or reseeded: still reads its OWN (missing) report, badged.
    assert ind_b["indicative"] is True
    assert ind_b["peak_report_as_of"] is None
    assert ind_b["peak_report_not_in_session_note"].startswith(
        "The PEAK report dated %s was applied after this session loaded" % BD)
    assert "payments are not counted here" in ind_b["peak_report_not_in_session_note"]
    assert ("รายงาน PEAK ลงวันที่ %s ถูกใช้งานหลังจากเซสชันนี้โหลดข้อมูลไปแล้ว" % BD) in \
        ind_b["peak_report_not_in_session_note_th"]

    # C: created AFTER the apply — its first seed already carries the newer report.
    assert ind_c["peak_report_not_in_session_note"] is None
    assert ind_c["peak_report_not_in_session_note_th"] is None
    assert ind_c["peak_report_as_of"] == str(BD)

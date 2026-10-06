"""Feedback Round 1, WP12 (design F15): the five weekly figures the API did not send.

Every block is served by reports.weekly() beside the keys it already served, with its
definition line in Thai and English, and notes that say when its source is empty or
the figure is indicative — never a silent 0.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import cases, journey, main, reports, weekly_figures
from app import today as today_domain
from app.book import SHEET
from app.config import settings
from app.main import app

BD = settings.business_date                       # 2026-10-23; the period is 10-17..10-23
OWNER = {"X-Volt-Role": "OWNER", "X-Volt-Officer": "owner"}
FIVE = ("mom", "paying_customers", "npl_movement", "arrears_split", "status_changes")
SERVED_BEFORE = {"period", "management_summary", "portfolio", "promises", "npl_changes", "power_actions",
                 "service_issues_open", "reviews_open", "next_week_focus", "counts_by_tier", "reconciliation"}


def _thai(text):
    return any("฀" <= ch <= "๿" for ch in (text or ""))


def _codes(block):
    return [n["code"] for n in block["notes"]]


@pytest.fixture
def client():
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")        # the session reports.weekly() reads outside a request
    return c


def _customer(product, nth=0):
    rows = [c for c in journey.book_customers() if c.contracts and c.contracts[0].product == product]
    return rows[nth]


def _receipt(customer, amount, on, source=None):
    contract = customer.contracts[0]
    rcp = journey.make_receipt(journey.for_current(), contract.uid, contract.entity, amount, on)
    if source:
        rcp["source"] = source
    return rcp


# --- the shape ----------------------------------------------------------------------

def test_the_five_figures_are_served_beside_every_key_served_before(client):
    body = client.get("/v1/reports/weekly").json()
    assert SERVED_BEFORE <= set(body)
    for key in FIVE:
        block = body[key]
        assert block["definition"] and _thai(block["definition_th"]) and block["source"], key
        assert isinstance(block["notes"], list), key
        for note in block["notes"]:
            assert note["code"] and note["en"] and _thai(note["th"]), (key, note)


def test_a_snapshot_freezes_the_five_figures_too(client):
    snap = client.post("/v1/reports/weekly:snapshot", headers=OWNER).json()["snapshot"]
    assert set(FIVE) <= set(snap["payload"])


# --- MoM ------------------------------------------------------------------------------

def test_the_month_spans_stop_on_the_same_day_and_clip_to_a_short_month():
    assert weekly_figures.month_spans(date(2026, 10, 23)) == (
        (date(2026, 10, 1), date(2026, 10, 23)), (date(2026, 9, 1), date(2026, 9, 23)))
    assert weekly_figures.month_spans(date(2026, 3, 31)) == (
        (date(2026, 3, 1), date(2026, 3, 31)), (date(2026, 2, 1), date(2026, 2, 28)))
    assert weekly_figures.month_spans(date(2026, 1, 15)) == (
        (date(2026, 1, 1), date(2026, 1, 15)), (date(2025, 12, 1), date(2025, 12, 15)))


def test_at_seed_this_month_is_an_empty_span_said_in_words_not_a_bare_zero():
    mom = reports.weekly()["mom"]
    assert mom["this_month"] == {"start": "2026-10-01", "end": "2026-10-23", "instalment": "0.00",
                                 "cash_or_project": "0.00", "total": "0.00", "receipts": 0, "peak_receipts": 0}
    # the seed's C-002001 deposit (2026-09-10, EPC 20,000) is inside 1-23 Sep; 2026-08-28 is not
    assert mom["last_month"]["cash_or_project"] == "20000.00" and mom["last_month"]["receipts"] == 1
    assert mom["change"] == {"instalment": "0.00", "cash_or_project": "-20000.00", "total": "-20000.00"}
    assert mom["change_pct"] == {"instalment": None, "cash_or_project": "-100.0", "total": "-100.0"}
    assert mom["latest_receipt_on"] == "2026-09-10" and mom["empty"] is False
    codes = _codes(mom)
    assert "NO_RECEIPTS_IN_SPAN" in codes and "NO_BASE_FOR_PERCENT" in codes
    empty = next(n for n in mom["notes"] if n["code"] == "NO_RECEIPTS_IN_SPAN")
    assert "2026-10-01" in empty["th"] and "2026-09-10" in empty["th"]
    # the fixture book has no applied PEAK report, so the month is partial and says so
    assert mom["peak_report_as_of"] is None and mom["indicative"] is True and "NO_PEAK_REPORT" in codes


def test_mom_splits_spv_from_epc_and_serves_every_change():
    lease, cash = _customer("LEASE"), _customer("CASH")
    _receipt(lease, "8399.00", BD - timedelta(days=3))
    _receipt(lease, "100.50", date(2026, 9, 2))
    _receipt(cash, "5000.00", date(2026, 10, 1))
    _receipt(cash, "999.00", date(2026, 9, 24))              # the day after last month's span: not counted
    mom = reports.weekly()["mom"]
    assert (mom["this_month"]["instalment"], mom["this_month"]["cash_or_project"], mom["this_month"]["total"]) == \
        ("8399.00", "5000.00", "13399.00")
    assert (mom["last_month"]["instalment"], mom["last_month"]["cash_or_project"], mom["last_month"]["total"]) == \
        ("100.50", "20000.00", "20100.50")
    assert mom["change"] == {"instalment": "8298.50", "cash_or_project": "-15000.00", "total": "-6701.50"}
    assert mom["change_pct"] == {"instalment": "8257.2", "cash_or_project": "-75.0", "total": "-33.3"}
    assert "NO_RECEIPTS_IN_SPAN" not in _codes(mom) and "NO_BASE_FOR_PERCENT" not in _codes(mom)


def test_a_peak_receipt_counts_and_an_older_report_badges_the_month_indicative():
    customer = next(c for c in journey.book_customers()
                    if c.data_source == SHEET and len(c.contracts) == 1 and c.contracts[0].product == "LEASE"
                    and cases.contract_field_of(c.contracts[0], "status") == "PAST_DUE")
    paid = {"doc_no": "IVT-9", "doc_kind": "IVT", "issued_on": "2026-10-01", "due_on": "2026-10-05", "status": "PAID",
            "cycle": {"n": 9, "of": 48}, "product_group": "Solar Leasing", "amount_total": "8399.00",
            "amount_due": "8399.00", "amount_awaiting": "0.00",
            "payment": {"on": "2026-10-08", "channel": "Beam", "amount": "8399.00", "receipt_no": "RE-9"},
            "contact_code": "VC1", "rule": "CUSTOMER_NO"}
    customer.sheet = dict(customer.sheet, peak={"report_as_of": "2026-10-10", "run_id": 1, "invoices": [paid]})
    journey.reset()
    mom = reports.weekly()["mom"]
    assert mom["this_month"]["instalment"] == "8399.00" and mom["this_month"]["peak_receipts"] == 1
    assert mom["peak_report_as_of"] == "2026-10-10" and mom["indicative"] is True
    older = next(n for n in mom["notes"] if n["code"] == "PEAK_REPORT_OLDER_THAN_SPAN")
    assert "2026-10-10" in older["th"] and "NO_PEAK_REPORT" not in _codes(mom)


# --- paying customers, WoW ------------------------------------------------------------

def test_paying_customers_count_each_customer_once_against_the_seven_days_before():
    a, b, c = _customer("LEASE", 0), _customer("CASH", 0), _customer("CASH", 1)
    _receipt(a, "100.00", BD)
    _receipt(a, "100.00", BD - timedelta(days=6))           # 10-17, the first day of the period
    _receipt(b, "100.00", BD - timedelta(days=2))
    _receipt(c, "100.00", BD - timedelta(days=7))           # 10-16, the last day of the prior period
    journey.make_receipt(journey.for_current(), "K-NOT-IN-BOOK", "EPC", "50.00", BD - timedelta(days=1))
    paying = reports.weekly()["paying_customers"]
    assert paying["this_period"] == {"start": "2026-10-17", "end": "2026-10-23", "customers": 2, "receipts": 4,
                                     "unresolved_receipts": 1}
    assert paying["prior_period"] == {"start": "2026-10-10", "end": "2026-10-16", "customers": 1, "receipts": 1,
                                      "unresolved_receipts": 0}
    assert paying["change"] == 1 and paying["change_pct"] == "100.0"
    assert "UNRESOLVED_RECEIPTS" in _codes(paying) and "NO_RECEIPTS_IN_SPAN" not in _codes(paying)


def test_with_no_receipt_in_either_week_the_zero_says_why():
    payload = reports.weekly()
    paying = payload["paying_customers"]
    assert paying["this_period"]["start"] == payload["period"]["start"]
    assert (paying["this_period"]["customers"], paying["prior_period"]["customers"]) == (0, 0)
    assert paying["change"] == 0 and paying["change_pct"] is None and paying["empty"] is True
    assert _codes(paying).count("NO_RECEIPTS_IN_SPAN") == 2 and "NO_BASE_FOR_PERCENT" in _codes(paying)


def test_with_no_receipt_on_record_at_all_the_note_says_that_instead():
    journey.for_current().receipts.clear()
    paying = reports.weekly()["paying_customers"]
    assert paying["latest_receipt_on"] is None
    assert "NO_RECEIPTS_ON_RECORD" in _codes(paying) and "NO_RECEIPTS_IN_SPAN" not in _codes(paying)


# --- NPL in / out -----------------------------------------------------------------------

def _journey_case_of(client, customer_no):
    # Touch the case store BEFORE declaring. Measured: when the store is first created
    # inside the declaration, it seeds the case already NPL (the contract overlay is
    # written first), so the system has nothing to follow and writes no event. A real
    # session has always opened Today before a declaration.
    cases.for_current()
    return next(c for c in client.get("/v1/cases").json()["cases"]
                if main.BY_CUSTOMER[c["customer_uid"]].customer_no == customer_no)


def test_at_seed_the_one_declaration_inside_the_period_is_counted_by_its_basis():
    npl = reports.weekly()["npl_movement"]
    # C-002033 was declared 2026-10-19 (inside); C-002034 on 2026-09-14 (outside)
    assert npl["entered"] == {"by_status_change": 0, "by_declaration": 1, "customers": 1}
    assert npl["left"] == {"by_status_change": 0, "customers": 0}
    [row] = npl["rows"]
    assert (row["direction"], row["basis"], row["on"], row["to"]) == ("ENTERED", "DECLARATION", "2026-10-19", "NPL")
    assert main.BY_CUSTOMER[row["customer_uid"]].customer_no == "C-002033" and row["npl_uid"]
    assert "EVENT_LOG_FROM_SYSTEM_START" in _codes(npl) and "NO_NPL_EXIT_RECORD" in _codes(npl)


def test_a_declaration_counts_twice_by_basis_once_by_customer_and_a_person_moving_out_counts_as_left(client):
    declared = client.post("/v1/cases/%s:advance" % _journey_case_of(client, "C-002032")["uid"],
                           json={"to_stage": "NPL_DECLARED_90", "role": "OWNER", "by": "Owner"})
    assert declared.status_code == 200
    back = next(c for c in cases.for_current().cases.values() if c["customer_no"] == "C-002034")
    moved = client.post("/v1/cases/by-customer/%s/payment-status" % back["customer_uid"],
                        json={"code": "LATE", "reason": "ลูกค้าเริ่มชำระตามแผน"},
                        headers={"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"})
    assert moved.status_code == 200
    npl = client.get("/v1/reports/weekly").json()["npl_movement"]
    assert npl["entered"] == {"by_status_change": 1, "by_declaration": 2, "customers": 2}
    assert npl["left"] == {"by_status_change": 1, "customers": 1}
    both = next(n for n in npl["notes"] if n["code"] == "DECLARATION_ALSO_STATUS_CHANGE")
    # B13 fix round 1 (minor): the formatted count itself, not any "1" anywhere in the sentence
    assert both["en"].startswith("1 customer(s) entered NPL") and both["th"].startswith("ลูกค้า 1 รายเข้า NPL")
    left = next(r for r in npl["rows"] if r["direction"] == "LEFT")
    assert (left["from"], left["to"], left["by"], left["reason"]) == ("NPL", "LATE", "settasak", "ลูกค้าเริ่มชำระตามแผน")


# --- true vs held arrears -----------------------------------------------------------------

def _late_with_arrears(state, skip=()):
    for case in state.cases.values():
        if case["payment_status"] != "LATE" or case["customer_uid"] in skip or case["open_issue_uid"]:
            continue
        if cases.case_arrears(case) > 0 and not journey.open_issue_for(journey.for_current(), case["customer_uid"]):
            return case
    raise AssertionError("no LATE case with arrears and no open issue")


def test_the_split_reconciles_to_the_items_arrears_line_by_line():
    payload = reports.weekly()
    split = payload["arrears_split"]
    items = today_domain.build()["items"]
    assert Decimal(split["total"]["total"]) == sum((Decimal(i["aggregate_overdue"]) for i in items), Decimal("0"))
    for side in ("true", "held", "total"):
        block = split[side]
        assert Decimal(block["total"]) == Decimal(block["instalment"]) + Decimal(block["cash_or_project"]) + Decimal(block["unrouted"])
    for line in ("instalment", "cash_or_project", "unrouted", "total"):
        assert Decimal(split["total"][line]) == Decimal(split["true"][line]) + Decimal(split["held"][line])
    assert split["total"]["customers"] == split["true"]["customers"] + split["held"]["customers"]
    assert split["as_of"] == str(BD) and _thai(split["unit_th"])


def test_an_od02_hold_and_an_open_issue_move_a_customer_from_true_to_held_and_say_why():
    state = cases.for_current()
    before = reports.weekly()["arrears_split"]
    held = _late_with_arrears(state)
    cases.set_allocation_hold(held, cases.case_arrears(held))
    ticket = _late_with_arrears(state, skip={held["customer_uid"]})
    cases.log_contact(state, ticket, {"result": "SERVICE_ISSUE", "counted": True, "amount_stated": True,
                                      "issue": {"summary": "อินเวอร์เตอร์ดับ", "responsible_team": "O_AND_M"}},
                      by="nantapol")
    split = reports.weekly()["arrears_split"]
    assert split["held"]["customers"] == before["held"]["customers"] + 2
    assert split["true"]["customers"] == before["true"]["customers"] - 2
    rows = {r["customer_uid"]: r for r in split["held_rows"]}
    assert rows[held["customer_uid"]]["reasons"] == ["OD02_CASE_HOLD"]
    assert rows[ticket["customer_uid"]]["reasons"] == ["SERVICE_ISSUE_CASE"]
    assert split["held_by"]["od02_allocation"] >= 1 and split["held_by"]["service_issue"] >= 1
    assert split["indicative"] is True and split["pending_decision"] == "OD-02"
    assert {"OD02_OPEN", "TWO_ISSUE_REGISTERS"} <= set(_codes(split))


def test_a_receipt_in_the_period_on_a_late_case_is_held_by_the_same_rule_as_the_portfolio_caveat():
    state = cases.for_current()
    case = _late_with_arrears(state)
    contract = main.BY_CUSTOMER[case["customer_uid"]].contracts[0]
    journey.make_receipt(journey.for_current(), contract.uid, contract.entity, "100.00", BD)
    payload = reports.weekly()
    row = next(r for r in payload["arrears_split"]["held_rows"] if r["customer_uid"] == case["customer_uid"])
    assert "OD02_RECEIPT_IN_PERIOD" in row["reasons"]
    assert payload["portfolio"]["allocation_hold_customers"] >= 1


# --- every status change ----------------------------------------------------------------

def test_every_payment_status_change_in_the_period_is_listed_newest_first_with_who_and_why(client):
    state = cases.for_current()
    first, second = [c for c in state.cases.values() if c["payment_status"] == "LATE"][:2]
    client.post("/v1/cases/by-customer/%s/payment-status" % first["customer_uid"],
                json={"code": "CURRENT", "reason": "โอนครบแล้ว รอ PEAK"},
                headers={"X-Volt-Role": "MANAGER", "X-Volt-Officer": "thip"})
    client.post("/v1/cases/by-customer/%s/payment-status" % second["customer_uid"],
                json={"code": "NPL", "reason": "ผิดนัดสามงวด"},
                headers={"X-Volt-Role": "MANAGER", "X-Volt-Officer": "nantapol"})
    changes = client.get("/v1/reports/weekly").json()["status_changes"]
    assert changes["count"] == 2 and changes["by_person"] == 2 and changes["by_system"] == 0
    newest, older = changes["rows"]
    assert (newest["from"], newest["to"], newest["by"], newest["reason"]) == ("LATE", "NPL", "nantapol", "ผิดนัดสามงวด")
    assert (older["from"], older["to"], older["by"]) == ("LATE", "CURRENT", "thip")
    assert newest["system"] == "LATE" and newest["on"] == str(BD) and newest["display_name"]
    assert changes["order"] == "newest first" and changes["empty"] is False


def test_a_status_the_system_followed_is_listed_as_the_systems(client):
    client.post("/v1/cases/%s:advance" % _journey_case_of(client, "C-002032")["uid"],
                json={"to_stage": "NPL_DECLARED_90", "role": "OWNER", "by": "Owner"})
    changes = client.get("/v1/reports/weekly").json()["status_changes"]
    [row] = changes["rows"]
    assert row["by"] == "SYSTEM" and row["by_system"] is True and row["reason"] is None
    assert changes["by_system"] == 1


def test_with_no_change_in_the_period_the_list_is_empty_and_says_so():
    changes = reports.weekly()["status_changes"]
    assert changes["rows"] == [] and changes["count"] == 0 and changes["empty"] is True
    assert "NO_STATUS_CHANGES_IN_PERIOD" in _codes(changes)


# === B13 fix round 1 ======================================================================
#
# (1) one payment counted once; (2) flagged receipts named in their span; (3) the OD-02
# hold's 7-day window said in words; (4) paying_customers badged like mom; and the minor
# findings (both spans checked, spans of different lengths, one customer key for NPL
# rows, a declaration with no system event, the unrouted arrears line).

def _peak_lease_customer():
    return next(c for c in journey.book_customers()
                if c.data_source == SHEET and len(c.contracts) == 1 and c.contracts[0].product == "LEASE"
                and cases.contract_field_of(c.contracts[0], "status") == "PAST_DUE")


def _peak_row(status, paid_on=None, paid="8399.00"):
    row = {"doc_no": "IVT-9", "doc_kind": "IVT", "issued_on": "2026-10-01", "due_on": "2026-10-05", "status": status,
           "cycle": {"n": 9, "of": 48}, "product_group": "Solar Leasing", "amount_total": "8399.00",
           "amount_due": "8399.00", "amount_awaiting": "0.00" if paid_on else "8399.00",
           "contact_code": "VC1", "rule": "CUSTOMER_NO"}
    if paid_on:
        row["payment"] = {"on": paid_on, "channel": "Beam", "amount": paid, "receipt_no": "RE-9"}
    return row


def _apply_peak(customer, row, as_of):
    customer.sheet = dict(customer.sheet, peak={"report_as_of": as_of, "run_id": 1, "invoices": [row]})


def _record_then_peak_says_paid(client, amounts, paid="8399.00", source=None):
    """The probe: an officer records receipt(s) against a PEAK invoice (POST /v1/receipts),
    then a PEAK report applied later shows the same invoice paid on 2026-10-20.
    `source` names who said so when it is not the invoice report (fix-all P1)."""
    customer = _peak_lease_customer()
    contract = customer.contracts[0]
    _apply_peak(customer, _peak_row("AWAITING"), as_of="2026-10-10")
    journey.reset()
    for amount in amounts:
        posted = client.post("/v1/receipts", json={"contract_uid": contract.uid, "invoice_uid": "inv-pk-IVT-9",
                                                   "amount": amount})
        assert posted.status_code == 201, posted.json()
    row = _peak_row("PAID", paid_on="2026-10-20", paid=paid)
    if source:
        row["payment_source"] = source
    _apply_peak(customer, row, as_of=str(BD))
    journey.reseed_peak(journey.for_current(), BD)
    return customer


def test_a_payment_recorded_here_and_shown_paid_by_a_later_peak_report_counts_once(client):
    _record_then_peak_says_paid(client, ["8399.00"])
    held = sorted((r.get("source") or "", r["amount"]) for r in journey.for_current().receipts.values()
                  if r.get("invoice_uid") == "inv-pk-IVT-9")
    assert held == [("", "8399.00"), ("PEAK_REPORT", "8399.00")]      # the store holds both rows
    body = client.get("/v1/reports/weekly").json()
    mom, paying, summary = body["mom"], body["paying_customers"], body["management_summary"]
    assert (mom["this_month"]["instalment"], mom["this_month"]["total"]) == ("8399.00", "8399.00")
    assert (mom["this_month"]["receipts"], mom["this_month"]["peak_receipts"]) == (1, 1)
    assert (paying["this_period"]["customers"], paying["this_period"]["receipts"]) == (1, 1)
    assert (summary["cash_in"]["instalment"], summary["cash_in"]["total"]) == ("8399.00", "8399.00")
    # the report is as of the business date, so nothing but the overlap badges these figures
    assert "PEAK_REPORT_OLDER_THAN_SPAN" not in _codes(mom) and "NO_PEAK_REPORT" not in _codes(mom)
    assert mom["indicative"] is True and paying["indicative"] is True and summary["cash_in_indicative"] is True
    for notes in (mom["notes"], paying["notes"], summary["cash_in_notes"]):
        [note] = [n for n in notes if n["code"] == "PEAK_AND_SLIP_OVERLAP"]
        assert note["en"].startswith("1 payment(s) are on record twice") and "16798.00" in note["en"]
        assert note["th"].startswith("การชำระ 1 รายการมีบันทึกซ้ำ") and "16798.00" in note["th"]
        assert "(counted 8399.00)" in note["en"] and "(นับ 8399.00)" in note["th"]
    assert [n["code"] for n in summary["cash_in_notes"]] == ["PEAK_AND_SLIP_OVERLAP"]


def test_a_payment_recorded_here_and_settled_by_the_receipt_run_counts_once_heal_after_heal(client):
    """Fix-all P1: the receipt run's money (PEAK_RECEIPT) folds against a person's receipt
    exactly like the report's own paid columns, and a second heal adds nothing."""
    _record_then_peak_says_paid(client, ["8399.00"], source="PEAK_RECEIPT")
    journey.reseed_peak(journey.for_current(), BD)
    held = sorted((r.get("source") or "", r["amount"]) for r in journey.for_current().receipts.values()
                  if r.get("invoice_uid") == "inv-pk-IVT-9")
    assert held == [("", "8399.00"), ("PEAK_RECEIPT", "8399.00")]
    [unit] = [u for u in weekly_figures.counted_receipts(journey.for_current()) if u["overlap"]]
    assert unit["source"] == weekly_figures.PEAK_SOURCE and unit["amount"] == Decimal("8399.00")
    body = client.get("/v1/reports/weekly").json()
    mom, summary = body["mom"], body["management_summary"]
    assert (mom["this_month"]["total"], mom["this_month"]["receipts"], mom["this_month"]["peak_receipts"]) == \
        ("8399.00", 1, 1)
    assert summary["cash_in"]["total"] == "8399.00"


def test_each_part_payment_peak_shows_counts_on_its_own_date_when_a_slip_folds_in():
    """Fix-all P6 (audit): the fold dated every PEAK receipt of an invoice on the latest,
    so an earlier part payment moved into a later week. Each counts on its own date; the
    person's receipt folds into the latest, and the invoice still counts once."""
    customer = _peak_lease_customer()
    early = {"on": "2026-09-10", "channel": "Beam", "amount": "3000.00", "receipt_no": "RE-91"}
    late = {"on": "2026-10-20", "channel": "Beam", "amount": "5399.00", "receipt_no": "RE-92"}
    _apply_peak(customer, dict(_peak_row("PAID", paid_on="2026-10-20"), payment_source="PEAK_RECEIPT",
                               payment=late, payments=[early, late]), as_of=str(BD))
    journey.reset()
    jstate = journey.for_current()
    contract = customer.contracts[0]
    journey.make_receipt(jstate, contract.uid, contract.entity, "3000.00", date(2026, 9, 11),
                         invoice_uid="inv-pk-IVT-9")
    units = {u["uid"]: u for u in weekly_figures.counted_receipts(jstate)}
    assert (units["rcp-pk-RE-91"]["amount"], units["rcp-pk-RE-91"]["received_on"],
            units["rcp-pk-RE-91"]["overlap"]) == (Decimal("3000.00"), "2026-09-10", None)
    folded = units["rcp-pk-RE-92"]
    assert (folded["amount"], folded["received_on"]) == (Decimal("5399.00"), "2026-10-20")
    assert folded["overlap"] == {"peak": Decimal("8399.00"), "recorded": Decimal("3000.00")}
    assert len(folded["members"]) == 2
    note = weekly_figures.overlap_note(list(units.values()), ({"start": "2026-09-01", "end": "2026-10-23"},))
    assert "11399.00 on record in all" in note["en"] and "(counted 8399.00)" in note["en"]


def test_the_overlap_counts_the_larger_of_the_peak_amount_and_the_receipts_recorded_here(client):
    customer = _record_then_peak_says_paid(client, ["3000.00", "2000.00"], paid="8399.00")
    [unit] = [u for u in weekly_figures.counted_receipts(journey.for_current()) if u["overlap"]]
    assert unit["amount"] == Decimal("8399.00") and unit["received_on"] == "2026-10-20"
    assert unit["overlap"] == {"peak": Decimal("8399.00"), "recorded": Decimal("5000.00")} and len(unit["members"]) == 3
    # the other way round: PEAK shows less than was recorded here
    _apply_peak(customer, _peak_row("PAID", paid_on="2026-10-20", paid="4000.00"), as_of=str(BD))
    journey.reseed_peak(journey.for_current(), BD)
    [unit] = [u for u in weekly_figures.counted_receipts(journey.for_current()) if u["overlap"]]
    assert unit["amount"] == Decimal("5000.00")
    assert reports.weekly()["management_summary"]["cash_in"]["total"] == "5000.00"


def test_a_receipt_that_names_another_customers_invoice_is_not_folded_in_and_is_named_in_its_span():
    customer = _peak_lease_customer()
    _apply_peak(customer, _peak_row("PAID", paid_on="2026-10-20"), as_of=str(BD))
    journey.reset()
    jstate = journey.for_current()
    other = _customer("CASH", 0).contracts[0]
    moved = journey.make_receipt(jstate, other.uid, other.entity, "1200.00", BD - timedelta(days=1),
                                 invoice_uid="inv-pk-IVT-9", matched="FULL")
    moved["invoice_moved_to_other_customer"] = True
    unknown = journey.make_receipt(jstate, "K-NOT-IN-BOOK", "EPC", "300.00", date(2026, 9, 15),
                                   invoice_uid="inv-pk-IVT-9", matched="FULL")
    unknown["invoice_owner_unknown"] = True
    assert not [u for u in weekly_figures.counted_receipts(jstate) if u["overlap"]]
    body = reports.weekly()
    mom, paying = body["mom"], body["paying_customers"]
    # both receipts still count as recorded, each as itself
    assert (mom["this_month"]["instalment"], mom["this_month"]["cash_or_project"]) == ("8399.00", "1200.00")
    assert mom["last_month"]["cash_or_project"] == "20300.00"
    flagged = [n for n in mom["notes"] if n["code"] == "FLAGGED_RECEIPTS_IN_SPAN"]
    assert [(n["en"].startswith("1 receipt(s) from 2026-10-01 to 2026-10-23, 1200.00 in all"),
             n["en"].startswith("1 receipt(s) from 2026-09-01 to 2026-09-23, 300.00 in all")) for n in flagged] == \
        [(True, False), (False, True)]
    assert flagged[0]["th"].startswith("ใบเสร็จ 1 ใบช่วง 2026-10-01 ถึง 2026-10-23 รวม 1200.00")
    [week] = [n for n in paying["notes"] if n["code"] == "FLAGGED_RECEIPTS_IN_SPAN"]
    assert week["en"].startswith("1 receipt(s) from 2026-10-17 to 2026-10-23, 1200.00 in all")
    assert "PEAK_AND_SLIP_OVERLAP" not in _codes(mom) and "PEAK_AND_SLIP_OVERLAP" not in _codes(paying)


def test_the_od02_hold_names_its_seven_day_window_in_the_definition_the_unit_and_the_note():
    state = cases.for_current()
    case = _late_with_arrears(state)
    contract = main.BY_CUSTOMER[case["customer_uid"]].contracts[0]
    journey.make_receipt(journey.for_current(), contract.uid, contract.entity, "100.00", BD)
    split = reports.weekly()["arrears_split"]
    assert "7-day" in split["definition"] and "8th day" in split["definition"]
    assert "7 วัน" in split["definition_th"] and "วันที่ 8" in split["definition_th"]
    for text in (split["unit"], split["unit_th"]):
        assert "2026-10-17" in text and "2026-10-23" in text
    assert "7-day" in split["unit"] and "7 วัน" in split["unit_th"]
    od02 = next(n for n in split["notes"] if n["code"] == "OD02_OPEN")
    for text in (od02["en"], od02["th"]):
        assert "2026-10-17" in text and "2026-10-23" in text
    assert "7-day" in od02["en"] and "7 วัน" in od02["th"]


def test_paying_customers_carries_the_same_peak_badge_as_mom_checked_against_the_period_end():
    paying = reports.weekly()["paying_customers"]
    assert paying["peak_report_as_of"] is None and paying["indicative"] is True and "NO_PEAK_REPORT" in _codes(paying)
    customer = _peak_lease_customer()
    _apply_peak(customer, _peak_row("PAID", paid_on="2026-10-18"), as_of="2026-10-20")
    journey.reset()
    paying = reports.weekly()["paying_customers"]
    [older] = [n for n in paying["notes"] if n["code"] == "PEAK_REPORT_OLDER_THAN_SPAN"]
    assert paying["peak_report_as_of"] == "2026-10-20" and paying["indicative"] is True
    assert "2026-10-20" in older["th"] and "2026-10-23" in older["th"] and "NO_PEAK_REPORT" not in _codes(paying)
    _apply_peak(customer, _peak_row("PAID", paid_on="2026-10-18"), as_of=str(BD))
    journey.reset()
    paying = reports.weekly()["paying_customers"]
    assert paying["indicative"] is False
    assert not {"NO_PEAK_REPORT", "PEAK_REPORT_OLDER_THAN_SPAN"} & set(_codes(paying))


def test_mom_checks_both_spans_for_partial_peak_data():
    customer = _peak_lease_customer()
    _apply_peak(customer, _peak_row("PAID", paid_on="2026-09-02"), as_of="2026-09-15")
    journey.reset()
    mom = reports.weekly()["mom"]
    older = [n for n in mom["notes"] if n["code"] == "PEAK_REPORT_OLDER_THAN_SPAN"]
    assert [("2026-10-23" in n["th"], "2026-09-23" in n["th"]) for n in older] == [(True, False), (False, True)]
    assert all("2026-09-15" in n["en"] for n in older) and mom["indicative"] is True


def test_a_31_day_month_against_a_30_day_month_says_the_spans_differ_in_length():
    assert weekly_figures.month_spans(date(2026, 10, 31)) == (
        (date(2026, 10, 1), date(2026, 10, 31)), (date(2026, 9, 1), date(2026, 9, 30)))
    mom = weekly_figures.mom(date(2026, 10, 31), weekly_figures.counted_receipts(journey.for_current()))
    [differ] = [n for n in mom["notes"] if n["code"] == "SPANS_DIFFER_IN_LENGTH"]
    assert "31 day(s)" in differ["en"] and "30 day(s)" in differ["en"]
    assert "31 วัน" in differ["th"] and "30 วัน" in differ["th"] and "2026-09-30" in differ["th"]
    assert "SPANS_DIFFER_IN_LENGTH" not in _codes(reports.weekly()["mom"])      # 23 Oct against 23 Sep


def test_with_no_receipt_on_record_at_all_mom_says_that_too():
    journey.for_current().receipts.clear()
    mom = reports.weekly()["mom"]
    assert mom["latest_receipt_on"] is None and mom["empty"] is True
    assert mom["this_month"]["total"] == "0.00" and mom["last_month"]["total"] == "0.00"
    assert "NO_RECEIPTS_ON_RECORD" in _codes(mom) and "NO_RECEIPTS_IN_SPAN" not in _codes(mom)


def test_a_contract_with_no_entity_lands_on_the_unrouted_line_and_still_reconciles():
    before = reports.weekly()["arrears_split"]
    item = next(i for i in today_domain.build()["items"]
                if len(main.BY_CUSTOMER[i["customer"]["uid"]].contracts) == 1 and Decimal(i["aggregate_overdue"]) > 0)
    contract = main.BY_CUSTOMER[item["customer"]["uid"]].contracts[0]
    line = weekly_figures.LINE_OF_ENTITY[contract.entity]
    contract.entity = None
    after = reports.weekly()["arrears_split"]
    owed = Decimal(item["aggregate_overdue"])
    assert Decimal(after["total"]["unrouted"]) == owed and before["total"]["unrouted"] == "0.00"
    assert Decimal(after["total"][line]) == Decimal(before["total"][line]) - owed
    assert after["total"]["total"] == before["total"]["total"]
    assert Decimal(after["true"]["unrouted"]) + Decimal(after["held"]["unrouted"]) == owed


def test_an_npl_row_whose_customer_does_not_resolve_is_left_out_with_a_note_never_keyed_by_its_case():
    journey.make_npl_case(journey.for_current(), "case-not-in-journey", "K-NOT-IN-BOOK", BD, "Owner")
    cases.for_current().events.append({"kind": "PAYMENT_STATUS_SET", "case_uid": "case-not-in-cases",
                                       "from": "LATE", "code": "NPL", "system": "NPL", "by": "SYSTEM",
                                       "reason": None, "on": str(BD), "ended": None})
    npl = reports.weekly()["npl_movement"]
    assert npl["entered"] == {"by_status_change": 0, "by_declaration": 1, "customers": 1}      # the seed's C-002033 only
    assert [r["customer_uid"] is not None for r in npl["rows"]] == [True]
    [skipped] = [n for n in npl["notes"] if n["code"] == "NPL_ROWS_UNRESOLVED"]
    assert skipped["en"].startswith("2 NPL row(s)") and skipped["th"].startswith("รายการ NPL 2 รายการ")


def test_a_customer_who_entered_and_left_npl_in_the_period_is_named_in_a_note(client):
    case = _journey_case_of(client, "C-002032")
    declared = client.post("/v1/cases/%s:advance" % case["uid"],
                           json={"to_stage": "NPL_DECLARED_90", "role": "OWNER", "by": "Owner"})
    assert declared.status_code == 200
    moved = client.post("/v1/cases/by-customer/%s/payment-status" % case["customer_uid"],
                        json={"code": "LATE", "reason": "ชำระครบตามแผนแล้ว"},
                        headers={"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"})
    assert moved.status_code == 200
    npl = client.get("/v1/reports/weekly").json()["npl_movement"]
    assert npl["left"] == {"by_status_change": 1, "customers": 1}
    [both] = [n for n in npl["notes"] if n["code"] == "ENTERED_AND_LEFT"]
    assert both["en"].startswith("1 customer(s) both entered and left NPL") and both["th"].startswith("ลูกค้า 1 ราย")


def test_a_declaration_in_the_period_with_no_system_status_event_is_named_on_the_status_list(client):
    # C-002033 was declared 2026-10-19 and seeded already NPL: no status event exists for it
    [note] = [n for n in reports.weekly()["status_changes"]["notes"] if n["code"] == "DECLARATION_WITHOUT_EVENT"]
    assert note["en"].startswith("1 NPL declaration(s)") and note["th"].startswith("การประกาศ NPL 1 รายการ")
    client.post("/v1/cases/%s:advance" % _journey_case_of(client, "C-002032")["uid"],
                json={"to_stage": "NPL_DECLARED_90", "role": "OWNER", "by": "Owner"})
    changes = client.get("/v1/reports/weekly").json()["status_changes"]
    assert changes["by_system"] == 1                   # C-002032's declaration wrote its SYSTEM event
    [note] = [n for n in changes["notes"] if n["code"] == "DECLARATION_WITHOUT_EVENT"]
    assert note["en"].startswith("1 NPL declaration(s)")


# === B13 fix round 2 ======================================================================
#
# (c) the OD-02 hold reads the same counted units as cash_in; the minor findings: an
# empty span never calls a folded slip "nothing recorded", the overlap note names the
# date the payment is counted on, and a flagged receipt badges every figure it is in.

def _peak_side_and_slip():
    rows = [r for r in journey.for_current().receipts.values() if r.get("invoice_uid") == "inv-pk-IVT-9"]
    return ([r for r in rows if r.get("source") == "PEAK_REPORT"], [r for r in rows if r.get("source") != "PEAK_REPORT"])


def test_a_slip_folded_into_an_allocated_peak_payment_holds_nobody_exactly_like_peak_alone(client):
    customer = _peak_lease_customer()
    assert cases.for_current().cases[customer.uid]["payment_status"] in ("LATE", "NPL")
    _apply_peak(customer, _peak_row("PAID", paid_on="2026-10-20"), as_of=str(BD))
    journey.reset()
    peak_only = client.get("/v1/reports/weekly").json()
    _record_then_peak_says_paid(client, ["8399.00"])
    [peak], [slip] = _peak_side_and_slip()
    assert peak["is_allocated"] is True and slip["is_allocated"] is False      # the probe's two rows
    both = client.get("/v1/reports/weekly").json()
    for body in (peak_only, both):
        assert (body["portfolio"]["allocation_hold_customers"], body["portfolio"]["allocation_hold_receipts"]) == (0, 0)
        assert body["management_summary"]["allocation_hold_note_th"] is None
        assert customer.uid not in {r["customer_uid"] for r in body["arrears_split"]["held_rows"]}
    for side in ("true", "held", "total"):
        assert both["arrears_split"][side] == peak_only["arrears_split"][side], side


def test_a_lone_unallocated_slip_still_holds_and_an_unallocated_folded_payment_holds_once(client, monkeypatch):
    customer = _peak_lease_customer()
    _apply_peak(customer, dict(_peak_row("AWAITING"), cycle=None), as_of="2026-10-10")
    journey.reset()
    posted = client.post("/v1/receipts", json={"contract_uid": customer.contracts[0].uid,
                                               "invoice_uid": "inv-pk-IVT-9", "amount": "8399.00"})
    assert posted.status_code == 201
    lone = client.get("/v1/reports/weekly").json()
    assert (lone["portfolio"]["allocation_hold_customers"], lone["portfolio"]["allocation_hold_receipts"]) == (1, 1)
    row = next(r for r in lone["arrears_split"]["held_rows"] if r["customer_uid"] == customer.uid)
    assert "OD02_RECEIPT_IN_PERIOD" in row["reasons"]
    # PEAK's side not allocated either: the folded payment still holds, and counts as ONE receipt
    monkeypatch.setattr(settings, "peak_report_allocates", False)
    _apply_peak(customer, dict(_peak_row("PAID", paid_on="2026-10-20"), cycle=None), as_of=str(BD))
    journey.reseed_peak(journey.for_current(), BD)
    [peak], [slip] = _peak_side_and_slip()
    assert peak["is_allocated"] is False and slip["is_allocated"] is False
    folded = client.get("/v1/reports/weekly").json()
    assert (folded["portfolio"]["allocation_hold_customers"], folded["portfolio"]["allocation_hold_receipts"]) == (1, 1)


def test_a_payment_peak_dates_last_week_is_never_called_unrecorded_this_week(client):
    customer = _record_then_peak_says_paid(client, ["8399.00"])            # the slip is recorded 2026-10-23
    _apply_peak(customer, _peak_row("PAID", paid_on="2026-10-12"), as_of=str(BD))
    journey.reseed_peak(journey.for_current(), BD)
    body = client.get("/v1/reports/weekly").json()
    paying, summary = body["paying_customers"], body["management_summary"]
    assert (paying["this_period"]["receipts"], paying["prior_period"]["receipts"]) == (0, 1)
    assert paying["latest_receipt_on"] == "2026-10-12"                     # the date the payment is counted on
    assert "NO_RECEIPTS_IN_SPAN" not in _codes(paying)
    [elsewhere] = [n for n in paying["notes"] if n["code"] == "FOLDED_RECEIPTS_COUNTED_ELSEWHERE"]
    assert elsewhere["en"].startswith("Nothing is counted from 2026-10-17 to 2026-10-23, but 1 receipt(s)")
    assert "2026-10-12" in elsewhere["en"] and "nothing was recorded" not in elsewhere["en"]
    assert elsewhere["th"].startswith("ไม่มียอดที่นับในช่วง 2026-10-17 ถึง 2026-10-23 แต่มีใบเสร็จ 1 ใบ")
    assert "2026-10-12" in elsewhere["th"] and "ไม่มีบันทึกการรับเงิน" not in elsewhere["th"]
    assert summary["cash_in"]["total"] == "0" and summary["cash_in_indicative"] is True
    [overlap] = [n for n in summary["cash_in_notes"] if n["code"] == "PEAK_AND_SLIP_OVERLAP"]
    assert "8399.00 counted on 2026-10-12, outside 2026-10-17 to 2026-10-23" in overlap["en"]
    assert "8399.00 นับวันที่ 2026-10-12 อยู่นอกช่วง 2026-10-17 ถึง 2026-10-23" in overlap["th"]
    [inside] = [n for n in paying["notes"] if n["code"] == "PEAK_AND_SLIP_OVERLAP"]
    assert "8399.00 counted on 2026-10-12, inside 2026-10-10 to 2026-10-16" in inside["en"]
    assert "8399.00 นับวันที่ 2026-10-12 อยู่ในช่วง 2026-10-10 ถึง 2026-10-16" in inside["th"]


def test_a_flagged_receipt_counted_in_a_span_badges_mom_paying_and_cash_in():
    customer = _peak_lease_customer()
    _apply_peak(customer, _peak_row("PAID", paid_on="2026-10-20"), as_of=str(BD))     # PEAK itself is complete
    journey.reset()
    clean = reports.weekly()
    assert (clean["mom"]["indicative"], clean["paying_customers"]["indicative"],
            clean["management_summary"]["cash_in_indicative"]) == (False, False, False)
    other = _customer("CASH", 0).contracts[0]
    moved = journey.make_receipt(journey.for_current(), other.uid, other.entity, "1200.00", BD - timedelta(days=1),
                                 invoice_uid="inv-pk-IVT-9", matched="FULL")
    moved["invoice_moved_to_other_customer"] = True
    body = reports.weekly()
    summary = body["management_summary"]
    assert (body["mom"]["indicative"], body["paying_customers"]["indicative"], summary["cash_in_indicative"]) == \
        (True, True, True)
    assert summary["cash_in"]["cash_or_project"] == "1200.00"
    [note] = [n for n in summary["cash_in_notes"] if n["code"] == "FLAGGED_RECEIPTS_IN_SPAN"]
    assert note["en"].startswith("1 receipt(s) from 2026-10-17 to 2026-10-23, 1200.00 in all")
    assert note["th"].startswith("ใบเสร็จ 1 ใบช่วง 2026-10-17 ถึง 2026-10-23 รวม 1200.00")


# === B13b =================================================================================
#
# (1) a number typed into a reason never leaves the weekly payload or its snapshot;
# (3) once-counted receipts group by invoice owner in linear time, by the same rule as
# journey.invoice_receipts. (2), the monthly KPI's flagged note, is in
# test_collection_kpi_overlap.py.

FAKE_PHONE, FAKE_ID = "081-234-5678", "1-2345-67890-12-3"        # both fake
TYPED = "โทรกลับ %s บัตร %s" % (FAKE_PHONE, FAKE_ID)
MARKER = "[ตัดเบอร์ออก]"
BANJERD = "sheet-99999000073"
MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}


def _without_typed_numbers(text):
    flat = "".join(ch for ch in text if ch.isdigit())
    return FAKE_PHONE not in text and FAKE_ID not in text and "0812345678" not in flat and "1234567890123" not in flat


def _redacted(value, words):
    return MARKER in value and _without_typed_numbers(value) and words in value


def test_typed_numbers_never_leave_the_weekly_reasons_nor_a_stored_snapshot(client, evidence_for_power):
    evidence_for_power(BANJERD)
    import json
    case = _journey_case_of(client, "C-002032")
    person = client.post("/v1/cases/by-customer/%s/payment-status" % case["customer_uid"],
                         json={"code": "NPL", "reason": "ผิดนัด " + TYPED},
                         headers={"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"})
    assert person.status_code == 200
    # the declaration's own typed note, and the system's follow that ends the person's change
    declared = client.post("/v1/cases/%s:advance" % case["uid"],
                           json={"to_stage": "NPL_DECLARED_90", "role": "OWNER", "by": "Owner",
                                 "note": "ประกาศ NPL " + TYPED})
    assert declared.status_code == 200
    npl_type = client.post("/v1/cases/by-customer/%s/npl-type" % case["customer_uid"], headers=MANAGER,
                           json={"code": "NPL_2_COOPERATIVE_DECOMMISSION", "reason": "ประเภท NPL " + TYPED})
    assert npl_type.status_code == 200
    power = client.post("/v1/cases/by-customer/%s/power-restriction" % BANJERD, json={"reason": "ขอตัดไฟ " + TYPED},
                        headers={"X-Volt-Officer": "nantapol"})
    assert power.status_code == 201
    period = client.get("/v1/reports/weekly").json()["period"]["label"]
    assert client.put("/v1/reports/weekly/%s/focus" % period, json={"text": "สัปดาห์หน้า " + TYPED}).status_code == 200

    body = client.get("/v1/reports/weekly").json()
    rows = body["status_changes"]["rows"]
    by_person = next(r for r in rows if r["by"] == "settasak")
    by_system = next(r for r in rows if r["by"] == "SYSTEM")
    assert _redacted(by_person["reason"], "ผิดนัด")
    assert _redacted(by_system["ended"]["reason"], "ผิดนัด") and by_system["ended"]["by"] == "settasak"
    entered = next(r for r in body["npl_movement"]["rows"] if r["basis"] == "STATUS_CHANGE")
    assert _redacted(entered["reason"], "ผิดนัด")
    typed = next(e for e in body["npl_changes"] if e["case_uid"] == npl_type.json()["case"]["uid"])
    assert _redacted(typed["reason"], "ประเภท NPL")
    requested = next(a for a in body["power_actions"] if a["kind"] == "POWER_REQUESTED")
    assert _redacted(requested["reason"], "ขอตัดไฟ")
    assert _redacted(body["next_week_focus"], "สัปดาห์หน้า")
    assert _without_typed_numbers(json.dumps(body, ensure_ascii=False))
    # the snapshot freezes the redacted payload, in the response and in the store
    snap = client.post("/v1/reports/weekly:snapshot", headers=OWNER).json()["snapshot"]
    assert _without_typed_numbers(json.dumps(snap, ensure_ascii=False))
    assert _without_typed_numbers(json.dumps(reports.snapshots()[0]["payload"], ensure_ascii=False))


def test_a_snapshot_name_keeps_no_typed_number_taken_listed_read_renamed_or_stored(client):
    """B13b fix round 1: a snapshot's name is stored, served on four routes, and becomes
    part of the download filename the Reports screen builds — a typed number is cut
    before it is stored, so every one of them follows."""
    import json
    taken = client.post("/v1/reports/weekly:snapshot", headers=OWNER,
                        json={"name": "n x %s y %s" % (FAKE_PHONE, FAKE_ID)})
    assert taken.status_code == 201
    uid = taken.json()["snapshot"]["snapshot_uid"]
    assert _redacted(taken.json()["snapshot"]["name"], "n x")
    [listed] = [s for s in client.get("/v1/reports/weekly/snapshots").json()["snapshots"] if s["snapshot_uid"] == uid]
    assert _redacted(listed["name"], "n x")
    assert _redacted(client.get("/v1/reports/weekly/snapshots/%s" % uid).json()["snapshot"]["name"], "n x")
    renamed = client.post("/v1/reports/weekly/snapshots/%s:rename" % uid, headers=OWNER,
                          json={"name": "หลังปิดยอด " + TYPED})
    assert renamed.status_code == 200 and _redacted(renamed.json()["snapshot"]["name"], "หลังปิดยอด")
    stored = reports.snapshot(uid)
    assert _redacted(stored["name"], "หลังปิดยอด") and _without_typed_numbers(json.dumps(stored, ensure_ascii=False))
    assert _redacted(client.get("/v1/reports/weekly/snapshots/%s" % uid).json()["snapshot"]["name"], "หลังปิดยอด")


def test_receipts_grouped_by_invoice_owner_equal_journey_invoice_receipts_for_every_invoice(client):
    customer = _record_then_peak_says_paid(client, ["8399.00"])              # owner-matched: slip + PEAK
    jstate = journey.for_current()
    own, b, c = customer.contracts[0], _customer("CASH", 0).contracts[0], _customer("CASH", 1).contracts[0]
    moved = journey.make_receipt(jstate, b.uid, b.entity, "1200.00", BD, invoice_uid="inv-pk-IVT-9", matched="FULL")
    moved["invoice_moved_to_other_customer"] = True
    unknown = journey.make_receipt(jstate, "K-NOT-IN-BOOK", "EPC", "300.00", BD, invoice_uid="inv-pk-IVT-9")
    unknown["invoice_owner_unknown"] = True
    journey.make_receipt(jstate, own.uid, own.entity, "50.00", BD)                                  # no invoice
    shared = journey.make_invoice(jstate, b.uid, b.entity, "DEPOSIT", "1000", BD, "SENT", scenario="B13b")
    journey.make_receipt(jstate, b.uid, b.entity, "600.00", BD, invoice_uid=shared["uid"])        # two customers,
    journey.make_receipt(jstate, c.uid, c.entity, "400.00", BD, invoice_uid=shared["uid"])        # one invoice
    orphan = journey.make_invoice(jstate, "K-ORPHAN", "EPC", "DEPOSIT", "10", BD, "SENT", scenario="B13b")
    journey.make_receipt(jstate, "K-ORPHAN-TOO", "EPC", "10.00", BD, invoice_uid=orphan["uid"])   # None == None
    # B13b fix round 1: ownership is the CUSTOMER's, not the contract's — a receipt posted on
    # the invoice customer's OTHER contract still counts toward the invoice.
    two = next(k for k in journey.book_customers() if len(k.contracts) >= 2)
    first, second = two.contracts[0], two.contracts[1]
    across = journey.make_invoice(jstate, first.uid, first.entity, "DEPOSIT", "900", BD, "SENT", scenario="B13b")
    journey.make_receipt(jstate, first.uid, first.entity, "500.00", BD, invoice_uid=across["uid"])
    journey.make_receipt(jstate, second.uid, second.entity, "400.00", BD, invoice_uid=across["uid"])
    grouped = weekly_figures.receipts_by_invoice_owner(jstate)
    for invoice in jstate.invoices.values():
        assert [r["uid"] for r in grouped.get(invoice["uid"], [])] == \
            [r["uid"] for r in journey.invoice_receipts(jstate, invoice)], invoice["uid"]
    assert len(grouped["inv-pk-IVT-9"]) == 2 and len(grouped[shared["uid"]]) == 1
    assert not grouped.get(orphan["uid"])
    assert len(grouped[across["uid"]]) == 2


def test_counted_receipts_folds_4000_overlapping_invoices_inside_300_ms():
    import time
    from types import SimpleNamespace
    contracts = [k for customer in journey.book_customers() for k in customer.contracts]
    receipts, invoices = {}, {}
    for n in range(4000):
        contract = contracts[n % len(contracts)]
        invoices["inv-t-%d" % n] = {"uid": "inv-t-%d" % n, "contract_uid": contract.uid}
        for kind, source in (("pk", "PEAK_REPORT"), ("sl", None)):
            uid = "rcp-%s-%d" % (kind, n)
            receipts[uid] = {"uid": uid, "contract_uid": contract.uid, "entity": "SPV", "amount": "100.00",
                             "received_on": "2026-10-20", "invoice_uid": "inv-t-%d" % n, "source": source,
                             "is_allocated": source is not None}
    state = SimpleNamespace(receipts=receipts, invoices=invoices)
    timings, units = [], None
    for _ in range(3):
        started = time.perf_counter()
        units = weekly_figures.counted_receipts(state)
        timings.append(time.perf_counter() - started)
    assert sum(1 for u in units if u["overlap"]) == 4000 and len(units) == 4000
    assert min(timings) < 0.300, timings


# === Final fix F-R2 ========================================================================
#
# An apply is reseeded only for the session that made it (routers/peak_pipeline.py's
# _after_apply). Every OTHER session keeps counting whatever report it was last seeded or
# reseeded with, indefinitely, until it resets or reseeds itself. Reading mom, paying_customers
# or cash_in from such a session must not read the book's newer report as if its payments
# were already counted — a silent, complete-looking 0.

def test_a_session_that_has_not_reseeded_badges_a_later_report_as_not_in_session(client):
    """Session B reads before session A applies a PEAK report (and reseeds only itself,
    the same thing a real apply does for its caller). B never resets or reseeds, so its
    own report date stays behind the book's. mom, paying_customers and cash_in must each
    say so — indicative, with PEAK_REPORT_NOT_IN_SESSION in EN and TH, serving B's own
    (missing) date rather than the book's newer one. Session A, reseeded for itself, and
    a brand-new session C created AFTER the apply, carry no such note."""
    from app import session as session_domain

    session_b = TestClient(app)
    session_b.cookies.set("volt_session", "fr2-session-b")
    before = session_b.get("/v1/reports/weekly").json()
    assert before["mom"]["peak_report_as_of"] is None        # nothing applied yet, book-wide

    # Session A (the `client` fixture, cookie "shared") applies a PEAK report and
    # reseeds for ITSELF only.
    customer = _peak_lease_customer()
    _apply_peak(customer, _peak_row("PAID", paid_on=str(BD), paid="8399.00"), as_of=str(BD))
    token = session_domain.CURRENT.set("shared")
    try:
        journey.reseed_peak(journey.for_current(), BD)
    finally:
        session_domain.CURRENT.reset(token)

    body_a = client.get("/v1/reports/weekly").json()
    body_b = session_b.get("/v1/reports/weekly").json()
    session_c = TestClient(app)
    session_c.cookies.set("volt_session", "fr2-session-c")
    body_c = session_c.get("/v1/reports/weekly").json()      # C's first read, AFTER the apply

    # A: reseeded for itself, no gap, its own date is the one just applied.
    for block in (body_a["mom"], body_a["paying_customers"]):
        assert "PEAK_REPORT_NOT_IN_SESSION" not in _codes(block)
        assert block["peak_report_as_of"] == str(BD)
    summary_a = body_a["management_summary"]
    assert "PEAK_REPORT_NOT_IN_SESSION" not in [n["code"] for n in summary_a["cash_in_notes"]]
    assert summary_a["peak_report_as_of"] == str(BD)

    # B: never reset or reseeded — still reads its OWN (missing) report, badged.
    for block in (body_b["mom"], body_b["paying_customers"]):
        assert block["indicative"] is True
        [note] = [n for n in block["notes"] if n["code"] == "PEAK_REPORT_NOT_IN_SESSION"]
        assert note["en"].startswith("The PEAK report dated %s was applied after this session loaded" % BD)
        assert "payments are not counted here" in note["en"] and "Reloading the book counts them" in note["en"]
        assert ("รายงาน PEAK ลงวันที่ %s ถูกใช้งานหลังจากเซสชันนี้โหลดข้อมูลไปแล้ว" % BD) in note["th"]
        assert block["peak_report_as_of"] is None
    summary_b = body_b["management_summary"]
    assert summary_b["cash_in_indicative"] is True
    [note] = [n for n in summary_b["cash_in_notes"] if n["code"] == "PEAK_REPORT_NOT_IN_SESSION"]
    assert note["en"].startswith("The PEAK report dated %s was applied after this session loaded" % BD)
    assert ("รายงาน PEAK ลงวันที่ %s ถูกใช้งานหลังจากเซสชันนี้โหลดข้อมูลไปแล้ว" % BD) in note["th"]
    assert summary_b["peak_report_as_of"] is None

    # C: created AFTER the apply — its very first seed already carries the newer report.
    for block in (body_c["mom"], body_c["paying_customers"]):
        assert "PEAK_REPORT_NOT_IN_SESSION" not in _codes(block)
        assert block["peak_report_as_of"] == str(BD)
    summary_c = body_c["management_summary"]
    assert "PEAK_REPORT_NOT_IN_SESSION" not in [n["code"] for n in summary_c["cash_in_notes"]]
    assert summary_c["peak_report_as_of"] == str(BD)

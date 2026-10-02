"""DAY-002 (Today tiers), PIP-001..005 (the invoice pipeline), PKD-008 (slips),
and the no-approve-route assertion, at the HTTP surface."""
from datetime import timedelta
import csv
import io

import pytest
from fastapi.testclient import TestClient

from app import cases as cases_domain
from app import peak_documents as pkd
from app.config import settings
from app.main import app

BD = settings.business_date


@pytest.fixture
def client():
    # Round 3, R3-F04 / ruling 32 (Arina, 2026-09-04): `config.py` moved `settings`
    # off a process-wide singleton onto the same per-session `session.Store` the other
    # seven mutable domains already use (`cases.py:87` et al.), closing the sandbox
    # leak leg F demonstrated live (206/212 WorkBook rows re-bucketed across sessions,
    # R3-F15). `test_pip_005_ar_owner_config_blocks_an_officer` below monkeypatches
    # `settings.invoice_owner_role` directly in Python — outside any request, so it
    # lands in the SHARED slot (`session.CURRENT`'s default) — then asserts against a
    # response from this fixture's own client. Without pinning the cookie, that
    # client's first call is handed its own fresh session by the isolation middleware
    # (`main.py:130`) and never sees the monkeypatch. Pinning to `shared` here matches
    # the pattern already established for the same reason in `test_round2.py`,
    # `test_round3.py`, `test_round4.py`, `test_round2_gaps.py` and
    # `test_ux_round1.py`, wherever a file's fixtures mutate session-scoped domain
    # state directly rather than through the client. No other test in this file
    # compares two distinct sessions, so pinning the whole fixture changes nothing
    # else here.
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


@pytest.fixture
def stub():
    pkd.TRANSPORT_OVERRIDE = pkd.StubTransport()
    return pkd.TRANSPORT_OVERRIDE


def test_day_002_today_orders_by_tier_and_counts_reconcile(client):
    body = client.get("/v1/today").json()
    items = body["items"]
    assert items, "the migrated book puts customers on Today"
    ranks = [i["tier_rank"] for i in items]
    assert ranks == sorted(ranks)
    # Round-3 J3-04: the chips PARTITION the list — counts_by_tier sums to meta.total.
    # An answer waiting under a higher tier is named in answers_waiting_elsewhere
    # (round-2 S2-08's substance kept: it is reported, never hidden).
    counts = body["meta"]["tier_partition"]
    assert sum(counts.values()) == len(items) == body["meta"]["total"]
    assert sum(body["meta"]["counts_by_tier"].values()) == body["meta"]["total"]
    assert body["meta"]["counts_by_tier"]["ANSWER_WAITING"] + body["meta"]["answers_waiting_elsewhere"] \
        == body["meta"]["answers_waiting"]
    for i in items:
        assert i["tier"] in body["meta"]["tiers"] and i["priority_reason"] == i["tier"]
        assert i["case"]["next_action"] and i["case"]["next_action_on"]
        assert "band_set_code" in i and "aging_bucket" in i
    # a person-set callback due today lands in tier 2 above a routine case
    routine = next(i for i in items if i["tier"] == "ROUTINE")
    uid = routine["customer"]["uid"]
    r = client.post("/v1/cases/by-customer/%s/next-action" % uid,
                    json={"next_action": "CALLBACK", "next_action_on": str(BD), "by": "thip"})
    assert r.status_code == 200
    again = client.get("/v1/today").json()["items"]
    moved = next(i for i in again if i["customer"]["uid"] == uid)
    assert moved["tier"] == "NEXT_ACTION_DUE"


def test_contact_route_refuses_without_next_action(client):
    item = next(i for i in client.get("/v1/today").json()["items"] if i["case"]["open_ptp"] is None)
    uid = item["customer"]["uid"]
    r = client.post("/v1/cases/by-customer/%s/contacts" % uid, json={"result": "REACHED_ANSWERED", "counted": True, "by": "thip"})
    assert r.status_code == 422 and r.json()["code"] == "next_action_required"
    assert r.json()["message_th"]
    r = client.post("/v1/cases/by-customer/%s/contacts" % uid, json={
        "result": "REACHED_PTP", "counted": True, "amount_stated": True, "by": "thip",
        "ptp": {"amount": "3199.00", "date": str(BD + timedelta(days=2))}})
    assert r.status_code == 201 and r.json()["ptp"]["status"] == "OPEN"
    detail = client.get("/v1/cases/by-customer/%s" % uid).json()
    assert detail["contact_log"][0]["ptp_uid"] == r.json()["ptp"]["uid"]
    assert detail["case"]["next_action"] == "FOLLOW_PTP"


def _first_pipeline_item(client):
    items = client.get("/v1/pipeline?all=true").json()["items"]
    return next(i for i in items if i["entity"] and i["amount_due"])


def test_pip_001_release_refuses_while_a_gate_is_open(client, stub):
    item = _first_pipeline_item(client)
    r = client.post("/v1/pipeline/%s:release" % item["uid"], json={"by": "thip"})
    assert r.status_code == 422 and r.json()["code"] == "gate_not_passed"
    # Delta-100 D2h: release gates on the prototype's three conditions. This row
    # already resolves its entity, so the open ones are contract and down payment;
    # the EPC date is still recorded but no longer gates (the after-release card
    # reads it).
    assert set(r.json()["extensions"]["gates"]) == {"contract_signed", "down_payment"}
    r = client.post("/v1/pipeline/%s/gates/down-payment" % item["uid"], json={"by": "thip"})
    assert r.status_code == 422 and r.json()["code"] == "gate_evidence_required"   # PC1


def test_pip_002_005_release_creates_a_draft_delivery_waits_for_approval_reschedule_forces_a_choice(client, stub):
    item = _first_pipeline_item(client)
    uid = item["uid"]
    assert client.post("/v1/pipeline/%s/gates/down-payment" % uid, json={"slip_ref": "slip-001", "by": "thip"}).status_code == 200
    assert client.post("/v1/pipeline/%s/gates/epc-confirmed" % uid, json={"confirmed_on": str(BD + timedelta(days=2)), "source": "ODOO"}).status_code == 200
    assert client.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % uid,
                       json={"note": "สำเนาสัญญาที่ลงนามทั้งสองฝ่าย", "by": "thip"}).status_code == 201
    r = client.post("/v1/pipeline/%s:release" % uid, json={"by": "thip"})
    assert r.status_code == 201, r.json()
    body = r.json()
    assert body["peak_document"]["state"] == "DRAFT_CREATED" and body["peak_document"]["intent"] == "INVOICE_CREATE"
    assert body["invoice"]["entity"] == item["entity"] and body["invoice"]["company_id"]
    assert body["invoice"]["qr_payload"] is None
    # PIP-003: no link until AR approves in PEAK
    r = client.post("/v1/pipeline/%s/delivery" % uid, json={"channel": "LINE", "by": "thip"})
    assert r.status_code == 422 and r.json()["code"] == "invoice_not_approved"
    doc_uid = body["peak_document"]["uid"]
    assert client.post("/v1/peak-documents/%s:refresh" % doc_uid).json()["document"]["state"] == "APPROVED_IN_PEAK"
    r = client.post("/v1/pipeline/%s/delivery" % uid, json={"channel": "LINE", "by": "thip"})
    assert r.status_code == 200 and r.json()["item"]["delivery"]["qr_payload"]
    # PIP-004: a reschedule is one of three, with a reason
    r = client.post("/v1/pipeline/%s/reschedule" % uid, json={"decision": "LATER", "reason": "x"})
    assert r.status_code == 422 and r.json()["code"] == "decision_unknown"
    r = client.post("/v1/pipeline/%s/reschedule" % uid, json={"decision": "AMEND_DUE_DATE", "reason": "EPC moved the crew", "new_due": str(BD + timedelta(days=9))})
    assert r.status_code == 200 and r.json()["peak_documents"][0]["intent"] == "INVOICE_AMEND_DUE_DATE"
    r = client.post("/v1/pipeline/%s/reschedule" % uid, json={"decision": "STAND", "reason": "customer agreed"})
    assert r.status_code == 200 and r.json()["peak_documents"] == []
    # releasing twice refuses
    assert client.post("/v1/pipeline/%s:release" % uid, json={"by": "thip"}).status_code == 409


def test_pip_005_ar_owner_config_blocks_an_officer(client, stub, monkeypatch):
    item = _first_pipeline_item(client)
    uid = item["uid"]
    client.post("/v1/pipeline/%s/gates/down-payment" % uid, json={"slip_ref": "slip-002", "by": "thip"})
    client.post("/v1/pipeline/%s/gates/epc-confirmed" % uid, json={"confirmed_on": str(BD), "source": "ODOO"})
    client.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % uid,
                json={"note": "สำเนาสัญญาที่ลงนามทั้งสองฝ่าย", "by": "thip"})
    monkeypatch.setattr(settings, "invoice_owner_role", "AR")
    r = client.post("/v1/pipeline/%s:release" % uid, json={"by": "thip"}, headers={"X-Volt-Role": "OFFICER"})
    assert r.status_code == 403
    r = client.post("/v1/pipeline/%s:release" % uid, json={"by": "ar"}, headers={"X-Volt-Role": "MANAGER"})
    assert r.status_code == 201


def test_pkd_008_a_confirmed_slip_creates_a_draft_receipt_and_keeps_the_promise(client, stub):
    invoices = client.get("/v1/ar/pipeline").json()["invoices"]
    invoice = next(i for i in invoices if i["state"] in ("SENT", "OVERDUE"))
    r = client.post("/v1/slips", json={"invoice_uid": invoice["uid"], "amount": invoice["amount"], "slip_ref": "line-slip-7", "by": "thip"})
    assert r.status_code == 201, r.json()
    assert r.json()["peak_document"]["intent"] == "RECEIPT_FULL" and r.json()["peak_document"]["state"] == "DRAFT_CREATED"
    assert r.json()["receipt"]["is_allocated"] is False          # OD-02 still refuses component allocation
    partial = client.post("/v1/slips", json={"invoice_uid": invoice["uid"], "amount": "1.00", "slip_ref": "line-slip-8", "by": "thip"})
    assert partial.json()["peak_document"]["intent"] == "RECEIPT_PARTIAL"


def test_no_route_approves_a_peak_document(client):
    paths = [r.path for r in app.routes]
    assert not any("approve" in p and "peak" in p for p in paths), paths
    r = client.post("/v1/peak-documents/pkd-00001:approve")
    assert r.status_code in (404, 405)


def test_rejection_returns_to_the_officer_as_a_today_item(client):
    pkd.TRANSPORT_OVERRIDE = pkd.StubTransport()
    item = _first_pipeline_item(client)
    uid = item["uid"]
    client.post("/v1/pipeline/%s/gates/down-payment" % uid, json={"slip_ref": "s", "by": "thip"})
    client.post("/v1/pipeline/%s/gates/epc-confirmed" % uid, json={"confirmed_on": str(BD), "source": "ODOO"})
    client.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % uid,
                json={"note": "สำเนาสัญญาที่ลงนามทั้งสองฝ่าย", "by": "thip"})
    doc = client.post("/v1/pipeline/%s:release" % uid, json={"by": "thip"}).json()["peak_document"]
    pkd.TRANSPORT_OVERRIDE = pkd.StubTransport(reject_reason="wrong customer on the draft")
    r = client.post("/v1/peak-documents/%s:refresh" % doc["uid"]).json()["document"]
    assert r["state"] == "REJECTED"
    cs = cases_domain.for_current()
    assert any(t["kind"] == "PEAK_REJECTED" and t["ref"] == doc["uid"] for t in cs.today_items) or item["customer_uid"] not in cs.cases


def test_settings_lock_and_dictionaries(client):
    r = client.put("/v1/config", json={"peak_write_mode": "FULL"}, headers={"X-Volt-Role": "MANAGER"})
    assert r.status_code == 422 and r.json()["code"] == "config_locked"
    r = client.put("/v1/config", json={"npl_review_dpd": 90}, headers={"X-Volt-Role": "OFFICER"})
    assert r.status_code == 403
    r = client.post("/v1/dictionaries/DC_STATUS/values", json={"code": "HOME_VISIT_DONE", "label_th": "ลงพื้นที่แล้ว", "label_en": "Visited"}, headers={"X-Volt-Role": "MANAGER"})
    assert r.status_code == 201
    r = client.post("/v1/dictionaries/DC_STATUS/values/HOME_VISIT_DONE:deactivate", headers={"X-Volt-Role": "MANAGER"})
    assert r.status_code == 200 and r.json()["value"]["active"] is False
    sets = client.get("/v1/band-sets").json()["band_sets"]
    assert {s["code"] for s in sets} >= {"OPERATIONAL", "LEGACY_LDR", "SOP_30_60_90", "LEGACY_SHEET"}


def test_migration_report_is_honest_about_truncation(client):
    body = client.get("/v1/migration/report").json()
    assert body["run"]["reconciled"] is False
    assert any(r["note"] == "export truncated per tab" for r in body["reconciliation"])
    assert body["counts"]["engine_book"] > 100


def test_workbook_export_is_csv_with_every_row(client):
    """Judge J-16: the export returned 500 because the route called the route."""
    book = client.get("/v1/workbook").json()
    r = client.get("/v1/workbook:export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    lines = [l for l in r.text.lstrip("﻿").splitlines() if l]
    assert lines[0].startswith("volt_id,display_name")
    assert len(lines) - 1 == book["meta"]["total"]
    filtered = client.get("/v1/workbook:export?payment_status=NPL").text.lstrip("﻿").splitlines()
    assert 1 < len(filtered) < len(lines)


def test_workbook_csv_keeps_api_filters_order_and_displayed_values(client):
    params = {"payment_status": "NPL", "sort": "display_name", "dir": "asc"}
    payload = client.get("/v1/workbook", params=params).json()
    response = client.get("/v1/workbook:export", params=params)
    exported = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert list(exported[0]) == payload["meta"]["columns"]
    assert [row["volt_id"] for row in exported] == [(row["case"]["volt_id"] or "") for row in payload["rows"]]
    assert [row["display_name"] for row in exported] == [(row["customer"]["display_name"] or "") for row in payload["rows"]]
    assert [row["payment_status"] for row in exported] == [(row["case"]["payment_status"] or "") for row in payload["rows"]]
    assert [row["aggregate_outstanding"] for row in exported] == [str(row["aggregate_outstanding"]) for row in payload["rows"]]


def test_workbook_cursor_pages_are_complete_stable_and_keep_legacy_shape(client):
    legacy = client.get("/v1/workbook", params={"identities": 1}).json()
    assert "page" not in legacy
    assert legacy["meta"]["total"] == len(legacy["rows"])

    query = {"identities": 1, "limit": 2, "sort": "display_name", "dir": "asc"}
    first = client.get("/v1/workbook", params=query)
    assert first.status_code == 200
    first = first.json()
    assert len(first["rows"]) == 2
    assert first["page"] == {
        "limit": 2,
        "returned": 2,
        "has_more": True,
        "next_cursor": first["page"]["next_cursor"],
    }
    assert first["page"]["next_cursor"]
    assert first["meta"]["total"] > len(first["rows"])

    second = client.get("/v1/workbook", params={**query, "cursor": first["page"]["next_cursor"]})
    assert second.status_code == 200
    second = second.json()
    first_uids = [row["customer"]["uid"] for row in first["rows"]]
    second_uids = [row["customer"]["uid"] for row in second["rows"]]
    assert not set(first_uids) & set(second_uids)
    combined = first_uids + second_uids
    pairs = [(row["customer"]["display_name"] or "", row["customer"]["uid"])
             for row in first["rows"] + second["rows"]]
    assert pairs == sorted(pairs)


@pytest.mark.parametrize("sort", [
    "aggregate_overdue", "aggregate_outstanding", "oldest_dpd", "risk_score",
    "display_name", "next_action_on", "tier", "oldest_unpaid",
])
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_workbook_cursor_walk_has_no_missing_or_duplicate_rows(client, sort, direction):
    # Identity rows deliberately create large null/tie groups for every money/date
    # sort, exercising the customer-uid tie-breaker across page boundaries.
    query = {"identities": 1, "limit": 200, "sort": sort, "dir": direction}
    cursor = None
    seen = []
    total = None
    while True:
        response = client.get("/v1/workbook", params={**query, **({"cursor": cursor} if cursor else {})})
        assert response.status_code == 200
        body = response.json()
        total = body["meta"]["total"] if total is None else total
        assert body["meta"]["total"] == total
        seen.extend(row["customer"]["uid"] for row in body["rows"])
        if not body["page"]["has_more"]:
            assert body["page"]["next_cursor"] is None
            break
        cursor = body["page"]["next_cursor"]
    assert len(seen) == total
    assert len(set(seen)) == total


def test_workbook_filtered_and_searched_cursor_walk_matches_the_legacy_result(client):
    unfiltered = client.get("/v1/workbook").json()["rows"]
    sample = next(row for row in unfiltered if row["case"]["officer_uid"])
    candidates = [
        {"product": "LEASE" if sample["entity"] == "SPV" else "CASH"},
        {"payment_status": sample["case"]["payment_status"]},
        {"dc_status": sample["case"]["dc_status"]},
        {"officer": sample["case"]["officer_uid"]},
        {"tier": sample["tier"]},
        {"q": sample["customer"]["customer_no"][-4:]},
    ]
    for filters in candidates:
        if next(iter(filters.values())) is None:
            continue
        expected = client.get("/v1/workbook", params=filters).json()["rows"]
        cursor = None
        actual = []
        while True:
            params = {**filters, "limit": 200, **({"cursor": cursor} if cursor else {})}
            response = client.get("/v1/workbook", params=params)
            assert response.status_code == 200, filters
            body = response.json()
            actual.extend(row["customer"]["uid"] for row in body["rows"])
            if not body["page"]["has_more"]:
                break
            cursor = body["page"]["next_cursor"]
        expected_uids = [row["customer"]["uid"] for row in expected]
        assert actual == expected_uids, filters
        assert len(actual) == len(set(actual)), filters


def test_workbook_cursor_rejects_malformed_and_different_query(client):
    malformed = client.get("/v1/workbook", params={"identities": 1, "limit": 2, "cursor": "not-a-cursor"})
    assert malformed.status_code == 422
    assert malformed.json()["code"] == "workbook_cursor_invalid"

    first = client.get("/v1/workbook", params={"identities": 1, "limit": 2, "sort": "display_name"}).json()
    mismatch = client.get("/v1/workbook", params={
        "identities": 1, "limit": 2, "sort": "oldest_dpd", "cursor": first["page"]["next_cursor"],
    })
    assert mismatch.status_code == 422
    assert mismatch.json()["code"] == "workbook_cursor_invalid"


def test_workbook_cursor_rejects_a_stale_data_epoch(client, monkeypatch):
    from app import data_epoch

    monkeypatch.setattr(data_epoch, "current", lambda: 7)
    first = client.get("/v1/workbook", params={"identities": 1, "limit": 2}).json()
    monkeypatch.setattr(data_epoch, "current", lambda: 8)
    stale = client.get("/v1/workbook", params={
        "identities": 1, "limit": 2, "cursor": first["page"]["next_cursor"],
    })
    assert stale.status_code == 409
    assert stale.json()["code"] == "workbook_cursor_stale"


@pytest.mark.parametrize("limit", [0, 201])
def test_workbook_page_limit_is_bounded(client, limit):
    assert client.get("/v1/workbook", params={"limit": limit}).status_code == 422


def test_money_position_names_the_penalty_share(client):
    """Judge J-31 / J-07: aggregate_overdue = instalments + accrued penalty, and the
    case says which figure to ask the customer for and what the sheet recorded."""
    from decimal import Decimal
    rows = client.get("/v1/workbook").json()["rows"]
    with_penalty = [r for r in rows if Decimal(r["money_position"]["penalty_accrued_unbilled"]) > 0]
    assert with_penalty, "the demo book carries at least one accruing contract"
    for r in rows:
        mp = r["money_position"]
        assert mp["reconciles"] is True
        # the penalty sits beside the arrears, never inside them (thip T2-01)
        assert Decimal(mp["instalments_overdue"]) == Decimal(r["aggregate_overdue"])
        assert mp["aggregate_overdue_includes_penalty"] is False
        assert mp["amount_to_ask"] == mp["instalments_overdue"]
        assert mp["penalty_invoicing_enabled"] is True
        # ruling 87 decided the rate; note_th says so in words and cites no code
        assert "อัตราที่ตัดสินแล้ว" in mp["note_th"] and "ruling" not in mp["note_th"] and "CF1" not in mp["note_th"]
    sheet_fee = [r for r in rows if r["money_position"]["sheet_late_fees"]]
    assert sheet_fee and "ชีตบันทึกค่าปรับ" in sheet_fee[0]["money_position"]["note_th"]


def test_month_grid_labels_amounts_that_differ_from_pmt(client):
    """Judge J-03: 3,199 on a 2,999 contract carries the difference and its provenance."""
    rows = client.get("/v1/workbook?q=99999000112").json()["rows"]
    assert rows
    detail = client.get("/v1/cases/by-customer/%s" % rows[0]["customer"]["uid"]).json()
    odd = [m for m in detail["month_grid"] if m.get("diff_from_pmt")]
    assert odd and odd[0]["diff_from_pmt"] == "200.00" and "ชีตไม่ระบุ" in odd[0]["note_th"]
    plain = [m for m in detail["month_grid"] if m.get("amount") and not m.get("diff_from_pmt")]
    assert plain, "cells equal to PMT carry no note"


def test_reports_reconcile_their_units(client):
    """Judge J-43: weekly counts customers in collection, officers/buckets count book rows; they add up."""
    weekly = client.get("/v1/reports/weekly").json()
    officers = client.get("/v1/reports/officers").json()
    buckets = client.get("/v1/reports/bucket-flow").json()
    rec = weekly["reconciliation"]
    assert rec["in_collection"] == weekly["portfolio"]["in_collection"]
    assert officers["meta"]["total_caseload"] == rec["book_rows"]
    assert rec["in_collection"] + rec["excluded_from_collection"] == rec["book_rows"]
    assert sum(rec["by_payment_status"].values()) == rec["book_rows"]
    assert officers["meta"]["unit"] and buckets["unit"] and weekly["portfolio"]["unit"]
    assert buckets["total"] == sum(buckets["counts"].values())


def test_cash_customer_arrears_equal_the_sheet_invoice(client):
    """Round-2 thip T2-01 (P1): 99999000297 has one sheet invoice, 588,500 fully
    outstanding; the case must show that figure, not an invented 80% balance."""
    from decimal import Decimal
    rows = client.get("/v1/workbook?q=99999000297").json()["rows"]
    assert rows
    r = rows[0]
    detail = client.get("/v1/cases/by-customer/%s" % r["customer"]["uid"]).json()
    invoices = [i for i in detail["invoices"] if i["state"] in ("OVERDUE", "PARTIALLY_PAID")]
    assert invoices
    assert Decimal(r["aggregate_overdue"]) == sum(Decimal(i["amount"]) for i in invoices)
    assert r["money_position"]["amount_to_ask"] == r["aggregate_overdue"]
    assert detail["contracts"][0]["derivation"]["deposit"].startswith("paid so far")


def test_migration_report_carries_the_import_time_or_says_it_has_none(client):
    """Final v2 (prototype 2363): the registry note names when the import ran, read
    off import_run.finished_at. The held fixture predates every run, so the keys exist
    and are None — the screen then shows no note rather than a date nobody recorded."""
    body = client.get("/v1/migration/report").json()
    assert "imported_at" in body["run"] and body["run"]["imported_at"] is None
    assert "import_started_at" in body["run"] and body["run"]["import_started_at"] is None
    assert body["run"]["captured_on"] is None


# --- Delta-100 DS1: the four-rung inbound source chain ------------------------------

def test_migration_report_serves_the_four_ranked_source_rungs(client):
    body = client.get("/v1/migration/report").json()
    chain = body["source_chain"]
    assert chain["serving_code"] == "SHEET"
    assert chain["serving_name"] == "New Order Master"
    rungs = chain["rungs"]
    assert [r["rank"] for r in rungs] == [1, 2, 3, 4]
    # 2026-09-23 (build round 3): Odoo crm.lead is the default source at rank 1; the
    # sheet keeps its real state beside it and reads "สำรอง" when it is not serving.
    assert [r["code"] for r in rungs] == ["ODOO_CRM_LEAD", "SHEET", "MANUAL_FILE", "STALE_SYSTEM"]
    assert rungs[1]["serving"] is True
    assert rungs[1]["name"] == "New Order Master (SHEET)"
    assert rungs[1]["state_th"] == "ให้บริการอยู่" and rungs[1]["state_en"] == "Serving"
    # Rung 3 is the manual-import store's real state: empty in this session, and says so.
    assert rungs[2]["state_th"] == "ยังไม่มีไฟล์"
    # Rung 4 is the stale-system rung, present and honest about an unknown date.
    assert rungs[3]["state_th"] == "ทางเลือกสุดท้าย"
    for rung in rungs:
        assert rung["note_th"] and rung["note_en"]
        assert rung["state_en"] and rung["tone"]
        assert rung["name_th"] and rung["name_en"]


def test_the_manual_file_rung_moves_to_fallback_once_a_file_is_imported(client):
    body = client.get("/v1/migration/report").json()["source_chain"]["rungs"]
    assert body[2]["state_th"] == "ยังไม่มีไฟล์"
    # A file some tab of which the importer knows (fix-all leg S: an unrecognised one is 422).
    r = client.post("/v1/imports", content=b'VOLT ID,Payment Status,"Term, Original"\nVC00001_Aa_Bb_,Late,60\n',
                    headers={"X-Volt-Filename": "manual.csv"})
    assert r.status_code in (200, 201), r.text
    rung = client.get("/v1/migration/report").json()["source_chain"]["rungs"][2]
    assert rung["state_th"] == "สำรอง"
    assert "ครั้งล่าสุด" in rung["note_th"]


# --- Delta-100 T-07/T-15/B-01: the served risk score, allowance and source ----------

def test_today_and_case_serve_the_risk_score_from_their_own_snapshot(client):
    """D2a/T-07: the rows and the record read one served 0..100 score, computed from
    the arrears/outstanding/DPD the same payload carries and the case's own
    broken-PTP and last-contact facts — never a number the screen re-derives."""
    from datetime import date as _date
    from decimal import Decimal as _Decimal

    from app import risk

    item = client.get("/v1/today").json()["items"][0]
    last = item["case"]["last_contact_at"]
    days = max(0, (BD - _date.fromisoformat(str(last)[:10])).days) if last else None
    assert item["risk_score"] == risk.score(
        dpd=item["oldest_dpd"], arrears=_Decimal(item["aggregate_overdue"]),
        outstanding=_Decimal(item["aggregate_outstanding"]),
        broken_ptps=item["case"]["broken_ptp_count"], days_since_contact=days)
    assert isinstance(item["risk_score"], int) and 0 <= item["risk_score"] <= 100
    assert item["customer"]["risk_score"] == item["risk_score"]

    detail = client.get("/v1/cases/by-customer/%s" % item["customer"]["uid"]).json()
    assert detail["work_item"]["risk_score"] == item["risk_score"]
    assert detail["work_item"]["customer"]["risk_score"] == item["risk_score"]
    assert detail["risk_score"] == item["risk_score"]
    assert detail["customer"]["risk_score"] == item["risk_score"]
    assert detail["case"]["risk_score"] == item["risk_score"]

    # The closed case's own resource serves the same number from the same engine.
    for row in client.get("/v1/cases").json()["cases"]:
        assert row["risk_score"] is None or (isinstance(row["risk_score"], int) and 0 <= row["risk_score"] <= 100)
    assert any(isinstance(row["risk_score"], int) for row in client.get("/v1/cases").json()["cases"])


def test_case_serves_the_weekly_contact_allowance_cap_and_used(client):
    """D2b/T-15: `cap` is the Settings limit and `used` counts the customer's own
    COUNTED contacts since Monday of the business week. A counted contact moves the
    served number by one; a last week's row never does."""
    from datetime import date as _date

    def _on(row):
        try:
            return _date.fromisoformat(str(row.get("occurred_at") or "")[:10])
        except ValueError:
            return None

    cs = cases_domain.for_current()
    case = next(c for c in cs.cases.values() if c["payment_status"] != "CLOSED")
    uid = case["customer_uid"]
    served = client.get("/v1/cases/by-customer/%s" % uid).json()["contact_allowance"]
    assert served["cap"] == settings.daily_contact_limit_per_customer
    monday = BD - timedelta(days=BD.weekday())
    counted_this_week = [
        r for r in cs.contact_log
        if r["customer_uid"] == uid and r.get("counted")
        and _on(r) is not None and monday <= _on(r) <= BD
    ]
    assert served["used"] == len(counted_this_week)

    # A counted row from last week is outside the window, however it is stamped.
    cs.contact_log.append({"uid": "ct-week-0", "customer_uid": uid,
                           "occurred_at": "%sT09:00:00" % (monday - timedelta(days=7)),
                           "counted": True})
    assert client.get("/v1/cases/by-customer/%s" % uid).json()["contact_allowance"]["used"] \
        == len(counted_this_week)

    # A contact logged today counts, and appears in the served pair.
    item = next(i for i in client.get("/v1/today").json()["items"] if i["case"]["open_ptp"] is None)
    uid = item["customer"]["uid"]
    before = client.get("/v1/cases/by-customer/%s" % uid).json()["contact_allowance"]["used"]
    r = client.post("/v1/cases/by-customer/%s/contacts" % uid, json={
        "result": "REACHED_PTP", "counted": True, "amount_stated": True, "by": "thip",
        "ptp": {"amount": "3199.00", "date": str(BD + timedelta(days=2))}})
    assert r.status_code == 201, r.json()
    after = client.get("/v1/cases/by-customer/%s" % uid).json()["contact_allowance"]
    assert after["used"] == before + 1 and after["cap"] == served["cap"]


def test_workbook_meta_names_the_serving_source_registry(client):
    """B-01/D2f: the pane's sub line reads a served label, and label and name are
    exactly the ones the Data sources chain serves for the rung serving the book."""
    meta = client.get("/v1/workbook").json()["meta"]
    chain = client.get("/v1/migration/report").json()["source_chain"]
    serving = next(r for r in chain["rungs"] if r["serving"])
    assert meta["source_name"] == chain["serving_name"] == "New Order Master"
    assert meta["source_label"] == serving["name"] == "New Order Master (SHEET)"

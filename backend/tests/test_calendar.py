"""WP6 — one dated list from the stores that already hold dates (vault note 10 §3, F16)."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app import cases as cases_domain
from app import journey
from app.config import settings
from app.main import app

BD = settings.business_date
HEAD = {"X-Volt-Officer": "nantapol", "X-Volt-Role": "OFFICER"}


def _client():
    # Pinned to the shared session so direct store reads see what the route served
    # (test_audit_enrichment.py's _shared_client does the same).
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


def _get(c, **params):
    return c.get("/v1/calendar", params=params, headers=HEAD)


def test_with_no_range_it_serves_the_six_week_grid_around_the_business_date_and_says_so():
    body = _get(_client()).json()
    meta = body["meta"]
    assert meta["defaulted"] is True and meta["business_date"] == str(BD) and meta["max_span_days"] == 366
    start, end = date.fromisoformat(meta["from"]), date.fromisoformat(meta["to"])
    assert start.weekday() == 0 and (end - start).days + 1 == 42
    assert start <= BD.replace(day=1) and BD <= end
    assert [d["on"] for d in body["days"]] == [(start + timedelta(days=i)).isoformat() for i in range(42)]


def test_every_item_names_its_store_and_the_served_totals_agree_with_the_items():
    body = _get(_client()).json()
    assert body["items"]
    for item in body["items"]:
        assert item["kind"] and item["source"] and item["on"]
    per_day = {}
    for item in body["items"]:
        per_day[item["on"]] = per_day.get(item["on"], 0) + 1
    assert {d["on"]: d["total"] for d in body["days"] if d["total"]} == per_day
    assert body["meta"]["total"] == len(body["items"]) == sum(d["total"] for d in body["days"])


def test_every_next_action_on_the_business_date_is_served_none_truncated():
    c = _client()
    body = _get(c).json()
    cs = cases_domain.for_current()
    expected = sorted(uid for uid, k in cs.cases.items()
                      if k["next_action_on"] == str(BD) and k["next_action"] not in ("SEND_REMINDER", "NONE_CLOSED"))
    served = sorted(i["customer_uid"] for i in body["items"] if i["kind"] == "NEXT_ACTION" and i["on"] == str(BD))
    assert served == expected and len(served) > 3
    assert all(i["movable"] and i["source"] == "cases.next_action" for i in body["items"] if i["kind"] == "NEXT_ACTION")


def test_a_send_reminder_next_action_is_served_as_a_batch_with_the_reminders_endpoints_own_label():
    c = _client()
    body = _get(c).json()
    batches = [i for i in body["items"] if i["kind"] == "REMINDER_BATCH"]
    rows = c.get("/v1/today/reminders", params={"days": 60}).json()["reminders"]
    in_range = [r for r in rows if body["meta"]["from"] <= r["due_on"] <= body["meta"]["to"]]
    assert sum(b["facts"]["count"] for b in batches) == len(in_range) > 0
    labels = ("D0", "D-%d" % cases_domain.reminder_offsets()[0])
    assert all(b["source"] == "today.reminders" and b["facts"]["label"] in labels for b in batches)
    assert not any(i["kind"] == "NEXT_ACTION" and i["facts"]["action"] == "SEND_REMINDER" for i in body["items"])


def test_an_open_promise_is_served_once_although_both_registers_hold_it():
    body = _get(_client()).json()
    keys = [(i["customer_uid"], i["on"]) for i in body["items"] if i["kind"] == "PTP_DUE"]
    assert len(keys) == len(set(keys))
    open_journey = [p for p in journey.for_current().ptps.values() if p["status"] == "OPEN"
                    and body["meta"]["from"] <= p["promise_date"] <= body["meta"]["to"]]
    assert all((p["customer_uid"], p["promise_date"]) in set(keys) for p in open_journey)
    assert body["meta"]["journey_ptps_mirrored"] >= 1


def test_review_deadlines_come_from_both_registers_and_each_says_how_precise_it_is():
    body = _get(_client()).json()
    reviews = [i for i in body["items"] if i["kind"] == "REVIEW_SLA"]
    assert {i["source"] for i in reviews} == {"cases.review", "journey.review"}
    case_review = next(i for i in reviews if i["source"] == "cases.review")
    assert case_review["facts"]["precision"] == "hour" and case_review["time"]
    assert case_review["facts"]["sla_hours"] == settings.review_sla_hours
    journey_review = next(i for i in reviews if i["source"] == "journey.review")
    assert journey_review["facts"]["precision"] == "day" and journey_review["time"] is None


def test_a_ticket_deadline_is_the_tickets_own_date_and_an_undated_issue_is_counted_not_placed():
    c = _client()
    cs = cases_domain.for_current()
    uid = next(u for u, k in cs.cases.items() if k["payment_status"] == "LATE" and not k["open_issue_uid"])
    issue = cases_domain._make_issue(cs, cs.cases[uid], {"summary": "Inverter fault", "deadline": "2026-10-30",
                                                         "opened_by": "nantapol"})
    body = _get(c).json()
    row = next(i for i in body["items"] if i["kind"] == "ISSUE_DEADLINE" and i["facts"]["issue_uid"] == issue["uid"])
    assert row["on"] == "2026-10-30" and row["source"] == "cases.issue" and row["customer_uid"] == uid
    assert body["meta"]["not_dated"]["journey.issue"] >= 1


def test_restructure_settlement_and_buyback_dates_are_read_from_the_journey_store():
    body = _get(_client(), **{"from": "2026-09-28", "to": "2026-11-08"}).json()
    phases = {(i["kind"], i["facts"].get("phase")) for i in body["items"]}
    assert ("RESTRUCTURE", "PROPOSED") in phases and ("RESTRUCTURE", "FIRST_DUE") in phases
    assert ("SETTLEMENT", "PLAN_OFFERED") in phases
    buyback = next(i for i in body["items"] if i["kind"] == "NPL_BUYBACK")
    assert buyback["on"] == "2026-10-14" and buyback["source"] == "journey.npl_case"
    assert buyback["facts"]["indicative"] is True and buyback["facts"]["amount"]


def test_a_bad_range_is_refused_with_a_pointer_never_ignored():
    c = _client()

    def err(**params):
        r = _get(c, **params)
        assert r.status_code == 422, r.json()
        return r.json()["errors"][0]
    assert err(**{"from": "2026-10-01"})["pointer"] == "/to"
    assert err(**{"from": "01/10/2026", "to": "2026-10-31"})["code"] == "date_invalid"
    assert err(**{"from": "2026-10-31", "to": "2026-10-01"})["code"] == "range_reversed"
    # 2026-09-21: the cap is 366 days so the year view is one request; a range past
    # that is still refused by name.
    too_long = err(**{"from": "2026-01-01", "to": "2027-06-01"})
    assert too_long["code"] == "range_too_long" and too_long["max_days"] == 366
    unknown = err(officer="nobody")
    assert unknown["code"] == "value_unknown" and unknown["known"] == sorted(unknown["known"])
    # F9 (controller ruling): officer= is validated against
    # today_domain.known_officers(cs, acting=x_volt_officer) — registry ∪ case-assigned
    # uids ∪ the acting identity — NOT officers.registry() alone, the same widening
    # GET /v1/today applies (backend/app/today.py:69). A uid a lead has assigned a case
    # to, even though the registry never listed it, is accepted here exactly as there.
    cs = cases_domain.for_current()
    uid = next(iter(cs.cases))
    original_officer = cs.cases[uid]["officer_uid"]
    cs.cases[uid]["officer_uid"] = "somchai_temp"
    try:
        ok = _get(c, officer="somchai_temp")
        assert ok.status_code == 200, ok.json()
        assert ok.json()["meta"]["officer"] == "somchai_temp"
    finally:
        cs.cases[uid]["officer_uid"] = original_officer


def test_the_officer_filter_scopes_every_case_item_to_that_officers_cases():
    body = _get(_client(), officer="nantapol").json()
    assert body["meta"]["officer"] == "nantapol" and body["items"]
    for item in body["items"]:
        if item["kind"] == "REMINDER_BATCH":
            assert all(x["officer_uid"] == "nantapol" for x in item["facts"]["customers"])
        else:
            assert item["officer_uid"] == "nantapol"
    assert {"nantapol", "thip"} <= {o["uid"] for o in body["meta"]["officers"]}


def test_a_year_range_serves_every_month_with_its_own_totals():
    """2026-09-21: the year view asks for Jan 1 - Dec 31 in ONE request, and the
    screen renders `by_month` as served — twelve months, zero months included, each
    total reconciling to the items it counts."""
    c = _client()
    body = _get(c, **{"from": "2026-01-01", "to": "2026-12-31"}).json()
    meta, items = body["meta"], body["items"]
    assert meta["from"] == "2026-01-01" and meta["to"] == "2026-12-31"
    assert len(body["days"]) == 365
    months = meta["by_month"]
    assert [m["month"] for m in months] == ["2026-%02d" % i for i in range(1, 13)]
    assert sum(m["total"] for m in months) == meta["total"] == len(items)
    for m in months:
        assert m["total"] == sum(1 for it in items if it["on"][:7] == m["month"])
        kinds = {}
        for it in items:
            if it["on"][:7] == m["month"]:
                kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
        assert m["by_kind"] == kinds


def test_a_week_range_serves_exactly_its_seven_days():
    body = _get(_client(), **{"from": "2026-10-19", "to": "2026-10-25"}).json()
    assert [d["on"] for d in body["days"]][0] == "2026-10-19" and len(body["days"]) == 7
    assert body["meta"]["defaulted"] is False
    assert all("2026-10-19" <= i["on"] <= "2026-10-25" for i in body["items"])


def test_the_header_strip_reads_the_reminder_batchs_own_label_and_open_conflict():
    # The calendar header's reminder cell prints the batch label and, while the
    # configured offsets and the SOP disagree, that conflict — all from the SAME
    # today.reminders result the item list already built. Meta serves the batch's
    # own label verbatim (never re-derived) beside its offsets and conflict.
    c = _client()
    meta = _get(c).json()["meta"]
    days = (date.fromisoformat(meta["to"]) - date.fromisoformat(meta["business_date"])).days
    served = c.get("/v1/today/reminders", params={"days": days}, headers=HEAD).json()["meta"]
    reminders = meta["reminders"]
    assert reminders["batch_label"] == served["batch_label"]
    assert reminders["offsets"] == served["offsets"]
    assert reminders["offsets_conflict"] == served["offsets_conflict"]
    assert reminders["note_th"] == served["note_th"] and reminders["note_en"] == served["note_en"]

"""Redesign v2 PR 8 — GET /v1/reports/team, the Overview's team performance."""
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app import team_performance
from app import cases as cases_domain
from app.config import settings
from app.main import app
from tests.test_no_codes_in_prose import CODE

MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}


def _client(name):
    c = TestClient(app)
    c.cookies.set("volt_session", name)
    return c


def _notes(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            if "note" in k and isinstance(v, str):
                yield path + k, v
            yield from _notes(v, path + k + ".")
    elif isinstance(node, list):
        for v in node:
            yield from _notes(v, path)


def test_shape_and_every_signed_role_reads_it():
    for role in ("OFFICER", "SUPERVISOR", "MANAGER", "OWNER", "OPS"):
        r = _client("team-shape").get("/v1/reports/team", headers={"X-Volt-Role": role})
        assert r.status_code == 200, r.json()
    body = r.json()
    assert set(body) >= {"period", "team", "receipts_by_month", "npl_roll", "aging_bands", "officers",
                         "officers_total", "queues"}
    assert body["period"]["officers"] == len(body["officers"]) > 0
    assert set(body["queues"]) == {"reviews_open", "pipeline", "peak_not_approved", "npl_cases"}
    for key in ("rolled_in", "rolled_out", "still_npl"):
        assert set(body["npl_roll"][key]) == {"customers", "amount"}
    assert set(body["team"]["receipts"]) == {"instalment", "cash_or_project", "total"}


def test_the_total_row_is_the_sum_of_the_officer_rows():
    body = _client("team-sum").get("/v1/reports/team").json()
    rows, total = body["officers"], body["officers_total"]
    for key in ("queue_today", "cases", "contacts", "reached_contacts", "ptps_kept", "ptps_decided", "npl_count"):
        assert total[key] == sum(r[key] for r in rows), key
    for key in ("arrears", "receipts_month"):
        assert Decimal(total[key]) == sum(Decimal(r[key]) for r in rows), key
    team = body["team"]
    assert team["arrears_total"] == total["arrears"] and team["queue_today"] == total["queue_today"]
    assert team["contact_success_rate"] == total["contact_rate"]
    if total["contacts"]:
        pct = (Decimal(total["reached_contacts"]) / total["contacts"] * 100).quantize(Decimal("0.1"))
        assert team["contact_success_rate"] == "%s%%" % pct
    bands = body["aging_bands"]
    assert [b["code"] for b in bands][:5] == ["CURRENT", "UNDER_30", "UNDER_60", "UNDER_90", "OVER_90"]
    assert all(b["label_th"] and b["label_en"] for b in bands)


def test_no_target_means_no_attainment_and_a_saved_target_serves_one():
    c = _client("team-target")
    team = c.get("/v1/reports/team").json()["team"]
    assert team["target_month"] is None and team["attainment"] is None and team["attainment_note_th"]
    assert team["receipts"]["instalment"]["attainment"] is None
    month = c.get("/v1/reports/team").json()["period"]["month"]
    assert c.put("/v1/reports/collection/%s/targets" % month, json={"cash_received:portfolio": "1000"},
                 headers=MANAGER).status_code == 200
    team = c.get("/v1/reports/team").json()["team"]
    expected = (Decimal(team["receipts_month"]) / 1000 * 100).quantize(Decimal("0.1"))
    assert team["target_month"] == "1000.00" and team["attainment"] == "%s%%" % expected
    assert team["attainment_note_th"] is None and team["receipts"]["total"]["attainment"] == team["attainment"]


def test_dso_is_null_on_the_fixture_book_and_served_when_the_book_can_carry_it():
    team = _client("team-dso").get("/v1/reports/team").json()["team"]
    assert team["dso_days"] is None and team["dso_note_th"] and team["dso_note_en"]
    bd = date(2026, 10, 23)
    invoices = [{"amount": "9000", "issued_on": "2026-09-01"}, {"amount": "5000", "issued_on": "2026-01-01"}]
    units = [{"received_on": "2026-07-01"}]
    # 3000 overdue ÷ (9000 ÷ 90) = 30 days
    assert team_performance.dso_days(invoices, units, Decimal("3000"), bd) == (30, None)
    assert team_performance.dso_days(invoices, [{"received_on": "2026-09-01"}], Decimal("3000"), bd)[0] is None
    assert team_performance.dso_days([{"amount": None, "issued_on": "2026-09-01"}], units, Decimal("1"), bd)[0] is None
    assert team_performance.dso_days([{"amount": "1", "issued_on": "2026-01-01"}], units, Decimal("1"), bd)[0] is None


def test_receipts_by_month_are_five_months_to_the_same_day_with_one_current():
    months = _client("team-months").get("/v1/reports/team").json()["receipts_by_month"]
    assert len(months) == 5 and [m["current"] for m in months] == [False, False, False, False, True]
    assert len({m["end"][8:] for m in months}) == 1
    assert team_performance.month_span(date(2026, 3, 31), 1) == (date(2026, 2, 1), date(2026, 2, 28))
    assert team_performance.month_span(date(2026, 2, 15), 4) == (date(2025, 10, 1), date(2025, 10, 15))


def test_comparison_flags_follow_the_served_rates():
    body = _client("team-flags").get("/v1/reports/team").json()
    team_contact = body["officers_total"]["contact_rate"]
    team_kept = body["officers_total"]["ptp_kept_rate"]

    def expect(mine, team):
        if mine is None or team is None:
            return None
        a, b = Decimal(mine[:-1]), Decimal(team[:-1])
        return "above" if a > b else "below" if a < b else "equal"

    for r in body["officers"]:
        assert r["contact_rate_vs_team"] == expect(r["contact_rate"], team_contact)
        assert r["ptp_kept_vs_team"] == expect(r["ptp_kept_rate"], team_kept)
        assert 0 <= r["receipts_share"] <= 1
    assert body["officers_total"]["contact_rate_vs_team"] is None


def test_no_internal_codes_in_any_served_note():
    body = _client("team-notes").get("/v1/reports/team").json()
    notes = list(_notes(body)) + [(k, t) for pair in team_performance.NOTES.values() for k, t in enumerate(pair)]
    assert notes
    for where, text in notes:
        assert not CODE.search(text), (where, text)


def test_an_officer_missing_from_the_registry_is_named_by_uid(monkeypatch):
    # REDESIGN V2 PR 8 — the uid is the handle officers.registry() and role.jsx's roster
    # already fall back to, so the Overview shows the same, never a blank name.
    real = team_performance.officer_registry.registry()
    uids = [r["uid"] for r in real if r["role"] == "OFFICER"]
    assert len(uids) >= 2
    kept = [r for r in real if r["uid"] != uids[0]]
    kept = [dict(r, display_name_th="") if r["uid"] == uids[1] else r for r in kept]
    monkeypatch.setattr(team_performance.officer_registry, "registry", lambda: kept)
    rows = {r["officer_uid"]: r for r in _client("team-registry").get("/v1/reports/team").json()["officers"]}
    for uid in uids[:2]:
        assert rows[uid]["display_name"] == uid and rows[uid]["display_name_en"] == uid


def test_in_scope_counts_the_stated_collection_unit_over_the_same_case_store():
    # The strip's scope note is served from two counts: in_scope is the stated
    # collection unit reports.reconciliation() names — "customers in collection
    # (closed and not-installed contracts excluded)" (reports.py:198) — and
    # cases_total is every case on the work book. Read on the shared session, the
    # same store the request used (test_calendar.py's direct reads do the same).
    c = _client("shared")
    team = c.get("/v1/reports/team").json()["team"]
    cs = cases_domain.for_current()
    book = [case for case in cs.cases.values() if cases_domain.is_book_case(case)]
    assert team["cases_total"] == len(book) > 0
    assert team["in_scope"] == sum(1 for case in book
                                   if case["payment_status"] not in ("CLOSED", "TERMINATED", "NOT_INSTALLED"))
    assert 0 < team["in_scope"] <= team["cases_total"]


# --- Delta-100 D2b: queue done-of-total ----------------------------------------------
#
# "done" = a case in the officer's Today queue (today.officer_totals' own two gates)
# that already has at least one counted contact on cases.contact_log dated the
# business date. The predicate lives in team_performance.queue_done_totals; these
# pin its behaviour end to end.

def _row(body, uid):
    return next(r for r in body["officers"] if r["officer_uid"] == uid)


def _log(uid, result, counted):
    cs = cases_domain.for_current()
    case = cs.cases[uid]
    return cases_domain.log_contact(
        cs, case,
        {"result": result, "counted": counted, "next_action": "CALL",
         "next_action_on": str(settings.business_date)},
        by=case["officer_uid"])


def test_queue_done_counts_a_case_with_a_counted_contact_on_the_business_date():
    c = _client("shared")
    before = c.get("/v1/reports/team").json()
    cs = cases_domain.for_current()
    case = next(case for case in cs.cases.values()
                if case["payment_status"] not in ("CLOSED", "NOT_INSTALLED") and case["officer_uid"])
    uid, officer = case["customer_uid"], case["officer_uid"]
    assert _row(before, officer)["queue_done"] == 0

    _log(uid, "REACHED_ANSWERED", counted=True)
    after = c.get("/v1/reports/team").json()
    assert _row(after, officer)["queue_done"] == 1
    assert after["team"]["queue_done"] == before["team"]["queue_done"] + 1
    assert after["officers_total"]["queue_done"] == sum(r["queue_done"] for r in after["officers"])
    # The queue total is unchanged: work done today stays on the desk.
    assert _row(after, officer)["queue_today"] == _row(before, officer)["queue_today"]

    # A not-counted call on another case is logged but never "done".
    other = next(case for case in cs.cases.values()
                 if case["customer_uid"] != uid and case["payment_status"] not in ("CLOSED", "NOT_INSTALLED")
                 and case["officer_uid"])
    _log(other["customer_uid"], "UNREACHABLE_NO_ANSWER", counted=False)
    after2 = c.get("/v1/reports/team").json()
    assert _row(after2, other["officer_uid"])["queue_done"] == _row(after, other["officer_uid"])["queue_done"]
    assert after2["team"]["queue_done"] == after["team"]["queue_done"]
    assert all(0 <= r["queue_done"] <= r["queue_today"] for r in after2["officers"])


# --- Delta-100 D2e: comparison figures, monthly targets, KPI targets ------------------

def test_comparison_figures_are_served_or_honestly_none():
    team = _client("team-compare").get("/v1/reports/team").json()["team"]
    # The contact-scope count is the same in-scope head-count the strip already serves.
    assert team["contact_scope"] == team["in_scope"]
    assert team["contact_scope_note_th"] and team["contact_scope_note_en"]
    # The weekly edition block names the live week; with nothing published it is None.
    edition = team["weekly_edition"]
    assert edition["period"] and edition["week_label"].startswith("WK-")
    assert edition["edition"] is None and edition["edition_label"] is None
    assert all(key in team for key in ("ptp_kept_rate_week", "ptp_kept_rate_prior_week",
                                       "ptp_kept_rate_delta_pts", "ptp_kept_rate_vs_prior_week",
                                       "dso_prior_month_days", "dso_delta_days", "dso_vs_prior_month"))
    # A delta is served only against a served prior figure — never against a guess.
    if team["ptp_kept_rate_prior_week"] is None:
        assert team["ptp_kept_rate_delta_pts"] is None and team["ptp_kept_rate_vs_prior_week"] is None
    else:
        expected = (Decimal(team["ptp_kept_rate_week"][:-1])
                    - Decimal(team["ptp_kept_rate_prior_week"][:-1]))
        assert Decimal(team["ptp_kept_rate_delta_pts"]) == expected
    if team["dso_prior_month_days"] is None:
        assert team["dso_delta_days"] is None and team["dso_vs_prior_month"] is None
    else:
        assert team["dso_delta_days"] == team["dso_days"] - team["dso_prior_month_days"]


def test_the_weekly_edition_label_follows_the_published_edition():
    c = _client("team-edition")
    c.post("/v1/reports/weekly:publish", headers=MANAGER)
    edition = c.get("/v1/reports/team").json()["team"]["weekly_edition"]
    assert edition["edition"]["number"] == 1 and edition["edition"]["status"] == "PUBLISHED"
    assert edition["edition_label"] == edition["week_label"]
    assert edition["edition_label"] == "WK-%02d/%d" % (edition["edition"]["week"], edition["edition"]["week_year"])


def test_monthly_bars_carry_a_stored_target_and_none_for_the_rest():
    c = _client("team-month-target")
    month = c.get("/v1/reports/team").json()["period"]["month"]
    before = c.get("/v1/reports/team").json()["receipts_by_month"]
    assert before[-1]["target"] is None and before[-1]["attainment"] is None
    assert before[-1]["attainment_note_th"] and before[-1]["attainment_note_en"]
    assert all(m["target"] is None for m in before)

    c.put("/v1/reports/collection/%s/targets" % month, json={"cash_received:portfolio": "1000"},
          headers=MANAGER)
    bar = c.get("/v1/reports/team").json()["receipts_by_month"][-1]
    assert bar["target"] == "1000.00"
    expected = (Decimal(bar["total"]) / 1000 * 100).quantize(Decimal("0.1"))
    assert bar["attainment"] == "%s%%" % expected and bar["attainment_note_th"] is None
    assert bar["attainment_bar_pct"] is not None


def test_kpi_targets_come_from_settings_with_none_defaults_and_clear_again():
    c = _client("team-kpi-targets")
    team = c.get("/v1/reports/team").json()["team"]
    for key in ("ptp_kept_target_pct", "contact_target_pct", "dso_target_days", "receipts_monthly_target"):
        assert team[key] is None, key
    assert team["ptp_kept_attainment"] is None and team["ptp_kept_attainment_note_th"]

    r = c.put("/v1/config", json={"ptp_kept_target_pct": "50", "contact_target_pct": "60",
                                  "dso_target_days": 30, "receipts_monthly_target": "5000"}, headers=MANAGER)
    assert r.status_code == 200, r.json()
    team = c.get("/v1/reports/team").json()["team"]
    assert team["ptp_kept_target_pct"] == "50" and team["contact_target_pct"] == "60"
    assert team["dso_target_days"] == 30 and team["receipts_monthly_target"] == "5000.00"
    if team["ptp_kept_rate"]:
        expected = (Decimal(team["ptp_kept_rate"][:-1]) / 50 * 100).quantize(Decimal("0.1"))
        assert team["ptp_kept_attainment"] == "%s%%" % expected
    if team["contact_success_rate"]:
        expected = (Decimal(team["contact_success_rate"][:-1]) / 60 * 100).quantize(Decimal("0.1"))
        assert team["contact_attainment"] == "%s%%" % expected
    # With no monthly target saved, the config fallback is the month's target.
    assert team["target_month"] == "5000.00" and team["target_month_source"] == "CONFIG_DEFAULT"
    bar = c.get("/v1/reports/team").json()["receipts_by_month"][-1]
    assert bar["target"] == "5000.00" and bar["attainment"] is not None

    # A nonsense percentage is refused by name; null clears back to "nobody set one".
    bad = c.put("/v1/config", json={"ptp_kept_target_pct": "150"}, headers=MANAGER)
    assert bad.status_code == 422 and bad.json()["errors"][0]["code"] == "out_of_range"
    assert c.put("/v1/config", json={"ptp_kept_target_pct": None}, headers=MANAGER).status_code == 200
    assert c.get("/v1/reports/team").json()["team"]["ptp_kept_target_pct"] is None


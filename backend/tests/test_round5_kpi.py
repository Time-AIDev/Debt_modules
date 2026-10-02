"""Round 5, KPI — rulings 78-83: the two collected-amount indicators and the four
shortfall bands (REQ-KPI-017 / REQ-KPI-007 / D7).

Every test is new, in a new file — zero assertions moved from any existing test,
matching this round's authorised-edit budget (16 of 17 spent; edit 17 is
committed elsewhere and is not this file's to spend).

Leg F built and drove both indicators in a scratch copy before this file existed
(docs/design/round-5/kpi/F-api.md); this suite pins leg C's build of it, adjusted
by rulings 81-83 (band 2 is null with its reason, never the badged proxy leg F
specified; portfolio and officer only, no team).

Three defects (C-1, C-2, C-4) were found live by a concurrent design leg driving
this endpoint mid-round, each reproduced independently before its fix and pinned
below so none can come back: a null or comma-formatted target value used to
persist as an unparseable string and crash every later read (C-4); the
attainment percentage was unbounded, which would draw an off-scale bar (C-1);
and the unworked band's only caveat was English-only (C-2).

Every test goes through the HTTP surface with the session cookie the middleware
issues, matching the rest of this suite's convention (test_round4.py's own note).
"""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}
OFFICER = {"X-Volt-Officer": "nantapol"}


def _thai(text):
    return any("฀" <= ch <= "๿" for ch in (text or ""))


@pytest.fixture
def client():
    return TestClient(app)


def _bands(payload):
    return {b["code"]: b for b in payload["shortfall"]["bands"]}


# --- T1/T2: the no-default error, and the framework trap it must not fall into ---

def test_t1_no_measure_is_refused_not_defaulted(client):
    r = client.get("/v1/reports/collection")
    assert r.status_code == 422
    body = r.json()
    # Ruling 51 permits a DECLARED code (leg F's E-2, taken this round): a caller
    # omitting the measure is a deliberate refusal to pick, not invalid input, the
    # same shape population_filter_unset already carries.
    assert body["code"] == "collection_measure_unset"
    assert body["errors"][0]["pointer"] == "/measure"
    assert _thai(body["message_th"])


def test_t2_the_refusal_is_not_the_frameworks_generic_field_message(client):
    """The trap: declaring `measure` as a required Query(...) would route the
    omission through main.py's RequestValidationError handler, whose per-field
    message_th is the hardcoded generic below — destroying the reason REQ-KPI-017
    exists for. `measure` must be declared optional and raised by hand."""
    r = client.get("/v1/reports/collection")
    assert r.json()["message_th"] != "ข้อมูลในฟิลด์นี้ไม่ถูกต้อง"
    assert r.json()["errors"][0]["message_th"] != "ข้อมูลในฟิลด์นี้ไม่ถูกต้อง"


def test_t3_unknown_measure_is_refused_with_the_known_list(client):
    r = client.get("/v1/reports/collection", params={"measure": "bogus"})
    assert r.status_code == 422
    assert r.json()["code"] == "validation_failed"
    assert r.json()["errors"][0]["pointer"] == "/measure"
    assert r.json()["errors"][0]["code"] == "unknown"
    assert "cash_received" in r.json()["errors"][0]["message"] and "due_month" in r.json()["errors"][0]["message"]


def test_malformed_month_is_refused_on_its_own_pointer(client):
    r = client.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-10-17..2026-10-23"})
    assert r.status_code == 422 and r.json()["errors"][0]["pointer"] == "/month"


# --- T4/T5/T19/T20: the bands, ruling 83 ------------------------------------------

def test_t4_the_two_computed_in_denominator_bands_tie_out_to_the_shortfall(client):
    """Ruling 83 changes leg F's own T4: band 2 cannot be summed (it is null), so
    the tie-out is over the bands that ARE computed — promised + unworked — which
    must still sum EXACTLY to indicator.shortfall. held is OUT of the denominator
    (D7) and does not enter this sum at all (T5 below)."""
    r = client.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-10"}).json()
    bands = _bands(r)
    total = Decimal(bands["promised"]["amount"]) + Decimal(bands["unworked"]["amount"])
    assert total == Decimal(r["indicator"]["shortfall"])


def test_t5_held_is_outside_the_denominator_and_still_present(client):
    r = client.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-10"}).json()
    bands = _bands(r)
    held = bands["held"]
    assert Decimal(held["amount"]) > 0 and held["contracts"] >= 1
    # D7: excluded but not hidden — held is not folded into shortfall/scheduled.
    total_with_held = Decimal(held["amount"]) + Decimal(bands["promised"]["amount"]) + Decimal(bands["unworked"]["amount"])
    assert total_with_held != Decimal(r["indicator"]["shortfall"])


def test_ruling83_band2_is_null_with_its_reason_never_zero(client):
    r = client.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-10"}).json()
    closing = _bands(r)["closing"]
    assert closing["amount"] is None
    assert closing["contracts"] is None
    assert closing["note_th"] and _thai(closing["note_th"])
    # The register that cannot be joined is still named as a fact, not invented as a figure.
    assert r["shortfall"]["orphan_cancellations"] >= 1


def test_ruling83_badged_proxy_is_not_served(client):
    """Leg F's own F-api.md §5.2 specified a badged proxy (recovery_cases /
    dc_status) worth ฿6,580.00 on 1 contract. Ruling 83 refused it by name. It
    must not reappear anywhere on the closing band."""
    r = client.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-10"}).json()
    closing = _bands(r)["closing"]
    assert closing["amount"] is None and closing["contracts"] is None


def test_unworked_always_carries_contracts_beside_amount(client):
    """Ruling 83 build law #2, driven across all four officer desks plus the
    portfolio — an integer every time amount is present, never dropped."""
    r = client.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-10"}).json()
    unworked = _bands(r)["unworked"]
    assert unworked["amount"] is not None
    assert isinstance(unworked["contracts"], int)
    for officer in ("nantapol", "noon", "ploy", "thip"):
        row = client.get("/v1/reports/collection",
                         params={"measure": "due_month", "month": "2026-10", "officer": officer}).json()
        u = _bands(row)["unworked"]
        if u["amount"] is not None:
            assert isinstance(u["contracts"], int)


# --- T6: no target, never a confident 0.0% ----------------------------------------

def test_t6_no_target_means_no_attainment_figure_ever(client):
    r = client.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-10"}).json()
    assert r["indicator"]["target"] is None
    assert r["indicator"]["attainment_pct"] is None
    assert _thai(r["indicator"]["attainment_note_th"])


# --- T7 / SH-1: officer= narrows the ACTUAL, not just the echo -------------------

def test_t7_sh1_officer_narrows_the_actual_not_only_the_scope_label(client):
    """SH-1 (F-api.md §9): leg F's own first draft echoed `scope: "officer"` and
    resolved the officer's TARGET while never filtering the ACTUAL — a 3.3-point
    lie wearing the officer's name. This pins that the actual genuinely differs
    per officer and none of the four equals the portfolio total by accident."""
    portfolio = client.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-10"}).json()
    seen = set()
    for officer in ("nantapol", "noon", "ploy", "thip"):
        row = client.get("/v1/reports/collection",
                         params={"measure": "due_month", "month": "2026-10", "officer": officer}).json()
        assert row["indicator"]["scope"] == "officer"
        assert row["indicator"]["officer_uid"] == officer
        assert row["indicator"]["actual"] != portfolio["indicator"]["actual"]
        seen.add(row["indicator"]["actual"])
    assert len(seen) > 1     # the four desks are not all reading the same figure either


def test_t7_sibling_officer_narrows_cash_received_too(client):
    portfolio = client.get("/v1/reports/collection", params={"measure": "cash_received", "month": "2026-09"}).json()
    row = client.get("/v1/reports/collection",
                     params={"measure": "cash_received", "month": "2026-09", "officer": "thip"}).json()
    assert row["indicator"]["actual"] != portfolio["indicator"]["actual"]


def test_thip_desk_is_the_largest_wholly_unattributed_shortfall(client):
    """The figure named explicitly in ruling 83's own carried item: thip's desk,
    never rendered by any leg before this round."""
    r = client.get("/v1/reports/collection",
                   params={"measure": "due_month", "month": "2026-10", "officer": "thip"}).json()
    ind = r["indicator"]
    assert ind["contracts"] == 74
    assert ind["scheduled"] == "525437.00"
    assert ind["actual"] == "0.00"
    assert ind["shortfall"] == "525437.00"
    bands = _bands(r)
    assert bands["unworked"]["amount"] == "525437.00"
    assert bands["held"]["amount"] == "0.00" and bands["promised"]["amount"] == "0.00"


# --- T8: two definitions, not one -------------------------------------------------

def test_t8_due_month_and_cash_received_disagree_by_design(client):
    """2026-08: both non-zero, and they must NOT agree — they read different
    stores on different date fields (R79-D)."""
    cash = client.get("/v1/reports/collection", params={"measure": "cash_received", "month": "2026-08"}).json()
    due = client.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-08"}).json()
    assert Decimal(cash["indicator"]["actual"]) > 0 and Decimal(due["indicator"]["actual"]) > 0
    assert cash["indicator"]["actual"] != due["indicator"]["actual"]
    assert cash["indicator"]["basis"] == "journey.receipts.received_on"
    assert due["indicator"]["basis"] == "contract.instalments.due_date"


def test_all_time_totals_measured_confirm_leg_f(client):
    """Leg F measured ฿20,399.00 on 2 receipts against ฿22,610,811.25 on 1,873
    lines. Confirmed here at the store level, independent of any month window."""
    from app import journey
    from app import cases as cases_domain
    jstate = journey.for_current()
    assert len(jstate.receipts) == 2
    assert sum(Decimal(str(r["amount"])) for r in jstate.receipts.values()) == Decimal("20399.00")
    cs = cases_domain.for_current()
    n_lines = n_paid = 0
    paid_sum = Decimal("0.00")
    for customer in journey.book_customers():
        for contract in customer.contracts:
            for ln in cases_domain.contract_field_of(contract, "instalments"):
                n_lines += 1
                paid = ln.paid_principal + ln.paid_interest + ln.paid_fee
                if paid > 0:
                    n_paid += 1
                    paid_sum += paid
    assert n_lines == 7054
    assert n_paid == 1873
    assert paid_sum == Decimal("22610811.25")


def test_due_month_excludes_a_superseded_restructured_line():
    """A restructure REPLACES its old lines (schedule_status SUPERSEDED); a due-
    month figure that still counted them would double-count money already carried
    into the addendum's principal (ruling 49's class). K-2035-1 (customer
    C-002035, officer ploy) carries a SUPERSEDED ฿3,060.00 line due 2026-10-01
    alongside its ACTIVE addendum — this pins that only the active line's month
    is counted, which is where this leg's driven ฿823,253.33 October portfolio
    shortfall diverges from leg F's stated ฿826,313.33 by exactly that one line."""
    from app import collection_kpi
    from app.main import BY_CONTRACT
    from app import cases as cases_domain
    _customer, contract = BY_CONTRACT["K-2035-1"]
    lines = cases_domain.contract_field_of(contract, "instalments")
    october = [ln for ln in lines if ln.due_date.year == 2026 and ln.due_date.month == 10]
    assert len(october) == 1 and october[0].schedule_status == "SUPERSEDED"
    assert collection_kpi._month_lines(contract, 2026, 10) == []       # excluded, not counted


# --- T9: contact rate is a denominator concept, never a target -------------------

def test_t9_contact_rate_target_is_refused_with_its_own_pointer(client):
    r = client.put("/v1/reports/collection/2026-10/targets",
                   json={"contact_rate:portfolio": "80"}, headers=MANAGER)
    assert r.status_code == 422
    assert r.json()["errors"][0]["pointer"] == "/contact_rate:portfolio"


def test_ruling82_a_team_target_key_is_refused_by_name_not_silently_accepted(client):
    """R5-F09's class, on the sibling weekly route: `PUT …/weekly/{period}/targets`
    accepts ANY key with 200 and resolves nothing for it, forever, silently. This
    route refuses `team` BY NAME (ruling 82: carried, not silently accepted and
    not silently dropped)."""
    r = client.put("/v1/reports/collection/2026-10/targets",
                   json={"due_month:team:lease": "300000"}, headers=MANAGER)
    assert r.status_code == 422
    assert r.json()["errors"][0]["pointer"] == "/due_month:team:lease"
    assert r.json()["errors"][0]["code"] == "team_not_supported"


def test_ruling82_an_unknown_key_is_refused_not_accepted_with_200(client):
    """The exact input R5-F09 drove to a 200 on the OLD route (`banana`)."""
    r = client.put("/v1/reports/collection/2026-10/targets", json={"banana": "1"}, headers=MANAGER)
    assert r.status_code == 422


def test_ruling82_team_is_named_on_the_face_of_every_response(client):
    """Carried as absent, the way ruling 72's two-factor half is: a manager reads
    it on the payload without having to guess a query parameter and get refused."""
    r = client.get("/v1/reports/collection", params={"measure": "due_month"}).json()
    assert r["meta"]["scopes_available"] == ["portfolio", "officer"]
    assert "team" not in r["meta"]["scopes_available"]
    assert _thai(r["meta"]["team_note_th"])
    assert "ทีม" in r["meta"]["team_note_th"] and "REQ-KPI" not in r["meta"]["team_note_th"]


def test_ruling82_product_is_not_used_as_a_team_proxy(client):
    """LEASE/CASH must not appear as a grouping anywhere in the served shape —
    the coincidence leg F refused by name."""
    r = client.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-10"}).json()
    assert r["indicator"]["scope"] in ("portfolio", "officer")
    for row in (r, client.get("/v1/reports/collection", params={"measure": "cash_received"}).json()):
        assert "LEASE" not in str(row) and "product" not in row["meta"]


# --- T10: manager-only ------------------------------------------------------------

def test_t10_officer_cannot_set_a_target(client):
    r = client.put("/v1/reports/collection/2026-10/targets",
                   json={"due_month:portfolio": "1000000"}, headers=OFFICER)
    assert r.status_code == 403
    assert r.json()["message_th"] == "เฉพาะผู้จัดการตั้งเป้าได้"    # the server's own string, reused verbatim


def test_owner_may_also_set_a_target(client):
    r = client.put("/v1/reports/collection/2026-10/targets",
                   json={"due_month:portfolio": "1000000"},
                   headers={"X-Volt-Role": "OWNER", "X-Volt-Officer": "owner"})
    assert r.status_code == 200


# --- T11: session isolation, the full four-part demonstration --------------------

def test_t11_session_isolation_full_demonstration():
    a = TestClient(app)
    b = TestClient(app)
    put = a.put("/v1/reports/collection/2026-10/targets", json={"due_month:portfolio": "999999"}, headers=MANAGER)
    assert put.status_code == 200
    assert a.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-10"}
                ).json()["indicator"]["target"] == "999999.00"
    assert b.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-10"}
                ).json()["indicator"]["target"] is None
    c = TestClient(app)     # created AFTER A's mutation
    assert c.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-10"}
                ).json()["indicator"]["target"] is None
    # A still sees its own write — a fix that isolates by losing the write is not a fix.
    assert a.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-10"}
                ).json()["indicator"]["target"] == "999999.00"
    # No new mechanism: this route writes into `reports.TARGETS`, ruling 43's own
    # remedy — confirmed still a session.Store, not a regression to a bare dict
    # (the B/C reads above could not both be None while A's stays "999999" if it
    # were one shared object).
    from app import reports as reports_domain
    from app import session as session_domain
    assert isinstance(reports_domain._targets_store, session_domain.Store)


# --- T12/T13: the closing note, and the stamp surviving a freeze -----------------

def test_t12_closing_note_names_the_orphan_count(client):
    r = client.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-10"}).json()
    assert str(r["shortfall"]["orphan_cancellations"]) in r["shortfall"]["bands"][1]["note_th"] \
        or "ยกเลิก" in r["shortfall"]["bands"][1]["note_th"]     # named, not merely a bare null


def test_t13_the_stamp_is_on_both_the_meta_and_the_indicator_body(client):
    """`meta` alone would not survive a snapshot freeze (reports.py:78,86 freezes
    weekly()'s PAYLOAD) — the stamp must be inside the indicator body too."""
    r = client.get("/v1/reports/collection", params={"measure": "due_month"}).json()
    assert r["meta"]["measure"] == r["indicator"]["measure"] == "due_month"
    w = client.get("/v1/reports/weekly").json()
    assert w["management_summary"]["measure"] == "cash_received"
    snap = client.post("/v1/reports/weekly:snapshot", headers=MANAGER).json()["snapshot"]
    assert snap["payload"]["management_summary"]["measure"] == "cash_received"


# --- T14: cash_received's own §1a coverage ----------------------------------------

def test_t14_cash_received_serves_receipts_beside_a_zero_actual(client):
    r = client.get("/v1/reports/collection", params={"measure": "cash_received", "month": "2026-10"}).json()
    assert r["indicator"]["actual"] == "0.00"
    assert r["indicator"]["receipts"] == 0
    assert r["indicator"]["receipts_all_time"] == 2          # never conflated with the month's zero
    assert r["shortfall"] is None                             # R79-D: nothing to decompose


def test_due_month_carries_the_scheduled_amount_cash_received_never_does(client):
    due = client.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-10"}).json()
    cash = client.get("/v1/reports/collection", params={"measure": "cash_received", "month": "2026-10"}).json()
    assert "scheduled" in due["indicator"] and Decimal(due["indicator"]["scheduled"]) > 0
    assert "scheduled" not in cash["indicator"]


# --- L4: indicative, and its basis -------------------------------------------------

def test_l4_due_month_is_always_indicative_with_a_provenance_note(client):
    """R5-F16: `book.py:145`'s paid_through is the sheet's LATE-cell statement
    walked back, not a record of cash. Badged on every response, not merely on
    months where it happens to matter."""
    for m in ("2026-08", "2026-09", "2026-10"):
        r = client.get("/v1/reports/collection", params={"measure": "due_month", "month": m}).json()
        assert r["indicator"]["indicative"] is True
        assert _thai(r["indicator"]["provenance_th"])


def test_cash_received_is_not_marked_indicative(client):
    """OD-02 qualifies cash_received's ALLOCATION, not its provenance — it reads
    the receipt record directly, not a derivation. A leg copying the indicative
    badge across both figures would be stating a refusal that does not apply."""
    r = client.get("/v1/reports/collection", params={"measure": "cash_received"}).json()
    assert r["indicator"]["indicative"] is False


def test_od02_stated_on_cash_received_when_true(client):
    r = client.get("/v1/reports/collection", params={"measure": "cash_received", "month": "2026-09"}).json()
    assert r["indicator"]["receipts"] == 1
    assert r["indicator"]["unallocated_receipts"] == 1
    assert r["indicator"]["unallocated_pending_decision"] == "OD-02"


def test_bank_reconciled_is_null_with_its_reason_never_implied(client):
    r = client.get("/v1/reports/collection", params={"measure": "cash_received"}).json()
    assert r["indicator"]["bank_reconciled"] is None
    assert _thai(r["indicator"]["bank_reconciliation_note_th"])


# --- the five refusals, untouched --------------------------------------------------

def test_the_five_refusals_are_unaffected(client):
    """Ruling 101: rulings 87 and 88 closed CF1 and OD-31 into config.DECIDED, so the
    register this test pins shrank from seven refusals to five. Design contract §3a
    lets a later ruling narrow an earlier one only when it names what it narrows;
    ruling 101 does, so the count changes here rather than being raised as a finding.
    What remains untouched is OD-02, OD-03, OD-04, OQ-31 and SVC-37 — decisions this
    prototype still refuses to make on its own behalf."""
    r = client.get("/v1/config/pending")
    assert {p["decision"] for p in r.json()["pending"]} == {"OD-02", "OD-03", "OD-04", "OQ-31", "SVC-37"}


# --- C-1/C-2/C-4: found live by a concurrent design leg driving this endpoint,
# reproduced independently before each fix, pinned here so none can come back ---

def test_c4_a_null_target_value_is_refused_not_stored(client):
    """Before the fix: `{"due_month:portfolio": null}` -> 200, stored the
    literal string "None", and the NEXT GET raised decimal.InvalidOperation — a
    500 that PERSISTED in the session store. Refused now, on its own pointer,
    and nothing is written."""
    r = client.put("/v1/reports/collection/2026-10/targets",
                   json={"due_month:portfolio": None}, headers=MANAGER)
    assert r.status_code == 422
    assert r.json()["errors"][0]["pointer"] == "/due_month:portfolio"
    assert r.json()["errors"][0]["code"] == "not_a_number"
    # And the store was never touched — the next GET is healthy, not a 500.
    after = client.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-10"})
    assert after.status_code == 200
    assert after.json()["indicator"]["target"] is None


def test_c4_a_comma_formatted_value_is_refused_the_exact_input_a_manager_types(client):
    r = client.put("/v1/reports/collection/2026-10/targets",
                   json={"due_month:portfolio": "400,000"}, headers=MANAGER)
    assert r.status_code == 422
    assert r.json()["errors"][0]["pointer"] == "/due_month:portfolio"
    after = client.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-10"})
    assert after.status_code == 200 and after.json()["indicator"]["target"] is None


def test_c4_the_clear_transition_still_works_after_the_fix(client):
    """The empty string is not a value to refuse — it is the CLEAR transition
    and must keep removing the key, exactly as it did before C-4's fix."""
    client.put("/v1/reports/collection/2026-10/targets", json={"due_month:portfolio": "300000"}, headers=MANAGER)
    set_r = client.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-10"}).json()
    assert set_r["indicator"]["target"] == "300000.00"
    r = client.put("/v1/reports/collection/2026-10/targets", json={"due_month:portfolio": ""}, headers=MANAGER)
    assert r.status_code == 200
    assert "due_month:portfolio" not in r.json()["targets"]
    cleared = client.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-10"}).json()
    assert cleared["indicator"]["target"] is None
    assert cleared["indicator"]["attainment_pct"] is None


def test_c4_a_valid_value_is_normalized_and_stored(client):
    r = client.put("/v1/reports/collection/2026-10/targets",
                   json={"due_month:portfolio": "400000"}, headers=MANAGER)
    assert r.status_code == 200
    assert r.json()["targets"]["due_month:portfolio"] == "400000.00"


def test_c1_attainment_pct_is_unbounded_but_the_bar_pct_is_capped(client):
    """Driven before the fix: attainment_pct came back "280498.0" against a
    target of 100 — an uncapped fill would be a 2,805-track-wide box. The true
    figure still travels (a manager overshooting a target should see the real
    number); the bar width is served separately, already safe to draw."""
    client.put("/v1/reports/collection/2026-10/targets", json={"due_month:portfolio": "100"}, headers=MANAGER)
    r = client.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-10"}).json()
    assert Decimal(r["indicator"]["attainment_pct"]) > 100
    assert r["indicator"]["attainment_bar_pct"] == "100.0"


def test_c1_band_bar_pct_present_and_scaled_to_the_largest_band(client):
    r = client.get("/v1/reports/collection",
                   params={"measure": "due_month", "month": "2026-10", "officer": "thip"}).json()
    bands = _bands(r)
    assert bands["unworked"]["bar_pct"] == "100.0"     # thip's largest band, by construction
    assert bands["closing"]["bar_pct"] is None          # never a width for an unmeasured band
    for code in ("held", "promised", "unworked"):
        assert bands[code]["bar_pct"] is not None


def test_c2_the_unworked_band_carries_its_caveat_in_thai(client):
    r = client.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-10"}).json()
    note = _bands(r)["unworked"]["note_th"]
    assert note and _thai(note)


def test_held_band_also_carries_its_out_of_denominator_note_in_thai(client):
    r = client.get("/v1/reports/collection",
                   params={"measure": "due_month", "month": "2026-10", "officer": "ploy"}).json()
    note = _bands(r)["held"]["note_th"]
    assert note and _thai(note)


def test_month_progress_and_contracts_unit_notes_are_served(client):
    r = client.get("/v1/reports/collection", params={"measure": "due_month", "month": "2026-10"}).json()
    assert _thai(r["meta"]["month_progress_note_th"])
    assert _thai(r["meta"]["contracts_note_th"])


def test_esc3_indicator_contracts_and_band_contracts_are_different_denominators(client):
    """The pairing ruling 83 illustrated with ("74 contracts", "฿525,437.00")
    reads as one number's own count. It is not: `indicator.contracts` is the
    whole desk (74); the money sits on a narrower set of contracts within the
    unworked band. This pins that the two must never be equal by construction
    and a reader must go to `bands[].contracts` for the band's own count."""
    r = client.get("/v1/reports/collection",
                   params={"measure": "due_month", "month": "2026-10", "officer": "thip"}).json()
    assert r["indicator"]["contracts"] == 74
    unworked = _bands(r)["unworked"]
    assert unworked["amount"] == "525437.00"
    assert unworked["contracts"] != r["indicator"]["contracts"]
    assert unworked["contracts"] == 5

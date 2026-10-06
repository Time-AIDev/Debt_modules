from datetime import date
from types import SimpleNamespace

import pytest

from app import book, collection_eligibility, debt_imports, errors, xlsx_writer
from app.config import settings
from app.npl_assessment import assess
from app.money.models import Instalment


VID = "99999009999_Synthetic_Customer_VOLT"
LEASE_HEADER = ["VOLT ID", "Term, Original", "Status", "Rate,  inc VAT", "First Payment Date",
                "Contract Canceled?", "Installation Month"]
CASH_HEADER = ["Status", "VOLT ID", "Price", "DC Status", "DP  incl VAT", "First Payment Date", "M1", "Status M1"]


@pytest.fixture(autouse=True)
def clean():
    debt_imports.reset()
    yield
    debt_imports.reset()


def customer(vid=VID, product="LEASE", contracts=()):
    return SimpleNamespace(uid="sheet-" + debt_imports.stem(vid), customer_no=debt_imports.stem(vid),
                           volt_id=vid, product=product, contracts=list(contracts))


def workbook(lease=None, cash=None, repo=None):
    return xlsx_writer.workbook([
        {"name": "Done - Collection", "rows": [LEASE_HEADER] + (lease or [])},
        {"name": "Done - Cash", "rows": [CASH_HEADER] + (cash or [])},
        {"name": "Repossessed 1", "rows": [["Customer ID", "Repossed Date", "Status"]] + (repo or [])},
    ])


def lease(status="Current", todo="", vid=VID):
    return [vid, "60", status, "3199", "2026-01-10", todo, "2026-01-01"]


def staged(profile="debt_status", **kwargs):
    return debt_imports.stage(workbook(**kwargs), "synthetic.xlsx", profile, "Manager", [customer()])


def apply(preview, **over):
    body = {"preview_version": preview["version"], "idempotency_key": "synthetic-command",
            "selected_keys": [entry["key"] for entry in preview["entries"] if entry["eligible"]]}
    body.update(over)
    return debt_imports.apply(preview["uid"], body, "Manager", "MANAGER")


@pytest.mark.parametrize("word,kind", [("Paid", "PAID"), ("Late", "LATE"), ("Partial", "PARTIAL"),
                                      ("Not Due", "UPCOMING"), ("Not issued", "UNISSUED"), ("", "UNCONFIRMED")])
def test_cash_explicit_cycle_status_controls_amount_evidence(word, kind):
    cell, _due, _owed = debt_imports.imports._IMS.cash_instalment(
        ["1000", word], ["M1", "Status M1"], 0)
    assert cell["kind"] == kind
    if word != "Paid":
        assert cell["kind"] != "PAID"


def test_only_exact_current_cohort_matches_are_eligible():
    preview = staged(lease=[lease(), lease(vid="99999008888_Outside_Customer_VOLT")])
    assert preview["counts"]["matched"] == 1
    assert preview["counts"]["review"] == 1
    assert any("OUTSIDE_CURRENT_COHORT" in entry["review_reasons"] for entry in preview["entries"])
    assert "record" not in preview["entries"][0]


def test_closed_with_termination_todo_is_quarantined():
    preview = staged(lease=[lease("Closed", "Terminate Contract")])
    assert preview["entries"][0]["eligible"] is False
    assert "TERMINATION_TODO" in preview["entries"][0]["review_reasons"]
    with pytest.raises(errors.Problem):
        apply(preview, selected_keys=[preview["entries"][0]["key"]])
    assert debt_imports.observations(customer().uid) == []


def test_exact_duplicate_collapses_and_conflicting_duplicate_requires_review():
    preview = staged(lease=[lease(), lease()])
    assert preview["counts"]["rows"] == 2 and preview["counts"]["entries"] == 1
    preview = staged(lease=[lease(), lease("Late")])
    assert preview["counts"]["entries"] == 2
    assert all("CONFLICTING_DUPLICATE" in entry["review_reasons"] for entry in preview["entries"])


def test_apply_is_actor_owned_idempotent_and_does_not_create_a_contract_for_status():
    preview = staged(lease=[lease()])
    first = apply(preview)
    assert apply(preview) == first
    assert len(debt_imports.observations(customer().uid)) == 1
    assert debt_imports.supplements() == {}
    with pytest.raises(errors.Problem) as failure:
        debt_imports.get_preview(preview["uid"], "Other")
    assert failure.value.status == 404


def test_unknown_contract_amount_is_not_assumed_zero():
    row = lease()
    row[3] = ""
    preview = staged("contract_supplement", lease=[row])
    assert preview["entries"][0]["quality"]["unknown_money_fields"] == ["pmt_inc_vat"]
    assert not preview["entries"][0]["eligible"]


def test_supplement_preserves_face_schedule_without_inferred_cash():
    preview = staged("contract_supplement", lease=[lease("Closed")])
    apply(preview)
    stored = next(iter(debt_imports.supplements().values()))
    contract, _reason = book._lease_contract(stored["contract_uid"], stored["customer_uid"],
                                           stored["record"], date(2026, 10, 7))
    assert contract.status == "ACTIVE" and contract.paid_through == 0
    assert all(line.total_amount == line.outstanding_amount for line in contract.instalments)
    assert contract.requires_installation_confirmation


def test_source_installation_day_does_not_bypass_additional_confirmation():
    contract = SimpleNamespace(uid="K-proof", customer_uid="sheet-proof", status="ACTIVE",
                               requires_installation_confirmation=True)
    assert not collection_eligibility.for_contract(contract)["eligible"]
    body = {"completed_on": str(settings.business_date), "document_ref": "QC-TEST", "reason": "Checked QC",
            "idempotency_key": "qc-command"}
    first = debt_imports.confirm_installation(contract, body, "Operator", "OPS")
    assert debt_imports.confirm_installation(contract, body, "Operator", "OPS") == first
    assert collection_eligibility.for_contract(contract)["eligible"]


def test_old_ended_contract_dpd_does_not_make_an_active_case_npl():
    old = SimpleNamespace(uid="ended", status="TERMINATED", instalments=[Instalment(
        due_date=date(2025, 1, 1), category="REGULAR", principal_amount=1000, interest_amount=0)])
    active = SimpleNamespace(uid="active", status="ACTIVE", instalments=[Instalment(
        due_date=date(2026, 10, 1), category="REGULAR", principal_amount=1000, interest_amount=0)])
    result = assess([old, active], as_of=date(2026, 10, 7))
    assert result.actual_dpd > 90 and not result.automatic_npl
    assert result.eligible_contracts == 1


def test_repossession_evidence_does_not_invent_a_cause_or_terminate():
    preview = staged(lease=[lease()], repo=[[VID, "2026-09-23", "In Queue"]])
    candidate = next(entry for entry in preview["entries"] if entry["termination_candidate"])
    assert candidate["termination_candidate"]["completed_evidence"]
    assert candidate["termination_candidate"]["cause"] is None
    result = apply(preview)
    assert result["terminated"] == 0


def test_failed_termination_confirmation_rolls_back_evidence_import():
    preview = staged(lease=[lease()], repo=[[VID, "", "Repossession In Progress"]])
    candidate = next(entry for entry in preview["entries"] if entry["termination_candidate"])
    with pytest.raises(errors.Problem):
        apply(preview, termination_confirmations=[{"key": candidate["key"], "cause": "DEFAULT", "reason": "x"}])
    assert debt_imports.observations(customer().uid) == []


def test_profile_reader_ignores_unselected_old_tabs():
    raw = xlsx_writer.workbook([{"name": "Old", "rows": [["secret"]]},
                               {"name": "Done - Cash", "rows": [CASH_HEADER]}])
    parsed = debt_imports.imports.read_xlsx(raw, selected_sheets=["Done - Cash"])
    assert [sheet["name"] for sheet in parsed] == ["Done - Cash"]

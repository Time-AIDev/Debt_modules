"""Unconfirmed quotes remain readable without manufacturing zero recovery money."""
import pytest
from app import confirmed_cash, errors, journey
from app.routers import journey as routes


def test_unconfirmed_evidence_keeps_strategy_list_and_quotes_unknown(monkeypatch):
    monkeypatch.setattr(journey, "remaining_npv", lambda contract: (_ for _ in ()).throw(
        confirmed_cash.pending("The schedule must be independently confirmed")))
    result = routes._recovery_paths_for(object())
    assert result["remaining_npv"] is None
    assert result["quote_problem"]["code"] == "npv_payment_evidence_unconfirmed"
    assert result["paths"]
    assert all(row["expected_recovery"] is None for row in result["paths"])


def test_missing_allocation_policy_is_a_visible_read_refusal(monkeypatch):
    monkeypatch.setattr(journey, "remaining_npv", lambda contract: (_ for _ in ()).throw(
        errors.allocation_rule_pending()))
    value, problem = routes._npv_for_read(object())
    assert value is None
    assert problem["code"] == "allocation_rule_pending"
    assert problem["message_th"]


def test_unexpected_quote_failure_is_not_hidden(monkeypatch):
    monkeypatch.setattr(journey, "remaining_npv", lambda contract: (_ for _ in ()).throw(RuntimeError("broken engine")))
    with pytest.raises(RuntimeError, match="broken engine"):
        routes._npv_for_read(object())

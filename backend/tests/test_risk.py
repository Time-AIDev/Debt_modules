"""The record's risk score: bounded, monotone, and weight-driven (Delta-100 D2a)."""
from app import config, risk


def setup_function():
    config.reset()


def teardown_function():
    config.reset()


def test_clean_case_scores_zero():
    assert risk.score(dpd=0, arrears=0, outstanding=100000, broken_ptps=0, days_since_contact=0) == 0


def test_worst_case_scores_one_hundred():
    assert risk.score(dpd=999, arrears=100000, outstanding=100000, broken_ptps=9, days_since_contact=99) == 100


def test_unknown_contact_history_counts_as_stale_not_dropped():
    assert risk.score() == config.settings.risk_weight_recency
    assert risk.score(days_since_contact=None) == risk.score(days_since_contact=99)


def test_monotone_in_dpd_and_broken_promises():
    low = risk.score(dpd=10, arrears=0, outstanding=100, broken_ptps=0, days_since_contact=0)
    high = risk.score(dpd=60, arrears=0, outstanding=100, broken_ptps=0, days_since_contact=0)
    assert high > low
    one = risk.score(dpd=0, arrears=0, outstanding=100, broken_ptps=1, days_since_contact=0)
    three = risk.score(dpd=0, arrears=0, outstanding=100, broken_ptps=3, days_since_contact=0)
    assert three > one


def test_weights_are_settings():
    config.settings.risk_weight_dpd = 0
    config.settings.risk_weight_broken_ptp = 0
    config.settings.risk_weight_recency = 0
    assert risk.score(dpd=120, arrears=100, outstanding=100, broken_ptps=3, days_since_contact=14) == \
        config.settings.risk_weight_arrears


def test_arrears_share_is_capped_at_outstanding():
    full = risk.score(dpd=0, arrears=100, outstanding=100, broken_ptps=0, days_since_contact=0)
    over = risk.score(dpd=0, arrears=500, outstanding=100, broken_ptps=0, days_since_contact=0)
    assert full == over == config.settings.risk_weight_arrears

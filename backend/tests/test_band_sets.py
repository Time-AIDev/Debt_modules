"""API Surface v2.1 §2.2 — "the single most important reading rule in this document".

    "Any response carrying aging_bucket also carries band_set_code. The two together
     identify a band; the bucket code alone no longer does, because the same code
     exists in more than one set."

This is absent from the local v1.0 repo — a grep for `band_set_code` there returns
nothing. It is current authority all the same, and it is the single easiest thing to
get silently wrong: a client that branches on the bucket code alone keeps working
until the day a second set is introduced, and then misreads every row.
"""
import pytest

from app.money.band_sets import BAND_SETS, BandSetUnknown, assert_band_pair_present, resolve_band

DEFAULT_SET = "OPERATIONAL"


def test_a_band_is_a_pair_never_a_bare_code():
    band = resolve_band("PAST_DUE", 22, band_set_code=DEFAULT_SET)

    assert band.code == "MID_OVERDUE"
    assert band.band_set_code == DEFAULT_SET


def test_the_status_override_still_wins_and_still_carries_a_set():
    band = resolve_band("NON_PERFORMING", 45, band_set_code=DEFAULT_SET)

    assert band.code == "NPL_CONFIRMED"
    assert band.band_set_code == DEFAULT_SET


def test_a_null_bucket_is_still_a_pair_so_the_reader_knows_which_set_answered():
    band = resolve_band("PRE_COLLECTION", None, band_set_code=DEFAULT_SET)

    assert band.code is None
    assert band.band_set_code == DEFAULT_SET


def test_an_unknown_band_set_is_refused():
    """422 band_set_unknown (DEBT-CFG). Falling back to a default set would produce a
    number that looks right and means something else."""
    with pytest.raises(BandSetUnknown) as exc:
        resolve_band("PAST_DUE", 22, band_set_code="WHATEVER_V9")

    assert exc.value.code == "band_set_unknown"


def test_more_than_one_set_exists_which_is_why_the_code_alone_is_not_enough():
    assert len(BAND_SETS) >= 2
    assert "LEGACY_LDR" in BAND_SETS


def test_the_portfolio_at_risk_set_bands_differently_from_the_default_set():
    """The reporting-only bands of Spec §20.2, indicators 11-13. At DPD 45 the default
    set says RISK_REVIEW and the legacy set says LDR_45 — the same contract, two
    different answers, which is precisely why the set has to travel with the code."""
    assert resolve_band("PAST_DUE", 45, band_set_code="OPERATIONAL").code == "RISK_REVIEW"
    assert resolve_band("PAST_DUE", 45, band_set_code="LEGACY_LDR").code == "LDR_45"


@pytest.mark.parametrize(("dpd", "expected"), [
    (0, "CURRENT"),
    (1, "COLLECTION_1_30"),
    (30, "COLLECTION_1_30"),
    (31, "COLLECTION_31_60"),
    (60, "COLLECTION_31_60"),
    (61, "COLLECTION_61_89"),
    (89, "COLLECTION_61_89"),
    (90, "COLLECTION_90_PLUS"),
])
def test_collection_status_v1_has_the_feedback_boundaries(dpd, expected):
    band = resolve_band("PAST_DUE", dpd, band_set_code="COLLECTION_STATUS_V1")

    assert band.code == expected
    assert band.band_set_code == "COLLECTION_STATUS_V1"


def test_a_payload_carrying_an_aging_bucket_without_a_band_set_is_rejected():
    """The guard that stops the rule being forgotten at a response boundary."""
    assert_band_pair_present({"aging_bucket": "MID_OVERDUE", "band_set_code": "OPERATIONAL"})

    with pytest.raises(AssertionError):
        assert_band_pair_present({"aging_bucket": "MID_OVERDUE"})


def test_the_guard_walks_nested_payloads():
    ok = {"items": [{"summary": {"aging_bucket": "CURRENT", "band_set_code": "OPERATIONAL"}}]}
    assert_band_pair_present(ok)

    bad = {"items": [{"summary": {"aging_bucket": "CURRENT"}}]}
    with pytest.raises(AssertionError):
        assert_band_pair_present(bad)

"""Two defects found by tracing the API rather than the modules.

Both are the same species as the one the 25-08 audit found: the rule is stated
correctly everywhere and a number still disobeys it.
"""
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.money.fee_states import stops_fee


class TestFeeStateHasAStartDate:
    """A fee state pauses the fee FROM THE DAY IT STARTS, not retrospectively.

    REQ-MNY-032 item 4: "The fee shall not be recomputed for a paused day at any later
    time, whatever the eventual outcome of the state." The converse has to hold too, or
    the rule is only half implemented: a day BEFORE the pause keeps the fee it earned.

    Without a start date, opening a permit hold today silently erases every baht that
    accrued before it — the customer's arrears history changes retroactively.
    """

    def test_a_hold_does_not_erase_fee_that_accrued_before_it_opened(self):
        from app.money.penalty import accrue_range

        # Due 2026-09-15, grace 14, so the fee starts 2026-09-30.
        # The permit hold opens on 2026-10-10, leaving 10 chargeable days before it.
        period = accrue_range(
            due_date=date(2026, 9, 15),
            arrears_on=lambda day: Decimal("5580.00"),
            through=date(2026, 10, 23),
            rate=Decimal("0.003"),
            grace_days=14,
            state_on=lambda day: "PERMIT_HOLD" if day >= date(2026, 10, 10) else None,
        )

        accrued_days = [d for d in period.days if not d.paused_by_state]
        assert len(accrued_days) == 10
        assert period.cumulative_amount == Decimal("167.40")

    def test_the_api_reports_a_permit_hold_with_the_fee_it_earned_before_the_hold(self):
        client = TestClient(app)
        rows = client.get("/v1/dashboards/exceptions",
                          params={"population_filter": "ALL_OPEN"}).json()["rows"]
        held = [r for r in rows if r["fee_state"] == "PERMIT_HOLD"]
        assert held, "the fixture set must contain a permit-held contract"

        row = held[0]
        # The clock ran the whole time — this is the number a previous audit found
        # drawn as 0 on two screens.
        assert row["days_past_due"] > 0
        assert row["fee_paused"] is True

        summary = client.get("/v1/contracts/%s/summary" % row["contract_uid"]).json()
        penalty = summary["accrued_penalty"]

        # Some fee accrued before the hold opened, and it survives.
        assert Decimal(penalty["accrued"]) > Decimal("0.00")
        # And the paused days are reported separately, by state, never netted away.
        assert Decimal(penalty["not_accrued_by_state"]["PERMIT_HOLD"]) > Decimal("0.00")

    def test_a_state_that_does_not_stop_the_fee_never_pauses_a_day(self):
        assert stops_fee("DISPUTE_UNDER_REVIEW") is False


SEVERITY = {
    None: -1, "CLOSED": 0, "RESOLVED": 0, "CURRENT": 1,
    "EARLY_OVERDUE": 2, "MID_OVERDUE": 3, "RISK_REVIEW": 4, "NPL_CONFIRMED": 5,
    "COLLECTION_1_30": 2, "COLLECTION_31_60": 3,
    "COLLECTION_61_89": 4, "COLLECTION_90_PLUS": 5,
}


class TestTheCustomerBandMatchesTheCustomerDpd:
    """A customer's aging band and their DPD must describe the SAME contract.

    oldest_dpd is the MAX across a customer's contracts. If the band is taken from
    whichever contract happens to sit first in the list, an officer reads a DPD from
    one contract beside a band from another — and the two can disagree about whether
    the customer is in Risk Review at all.
    """

    def test_the_band_follows_the_worst_contract_not_the_first_one(self):
        """The fixture set deliberately gives one customer a SECOND contract that is
        worse than their first, so taking the band from contracts[0] is visibly wrong."""
        client = TestClient(app)
        items = client.get("/v1/today-list").json()["items"]
        multi = [i for i in items if i["customer"]["contract_count"] > 1]
        assert multi, "the fixture set must contain a multi-contract customer"

        for item in multi:
            contracts = client.get(
                "/v1/customers/%s/contracts" % item["customer"]["uid"]
            ).json()["contracts"]
            worst = max(contracts, key=lambda c: c["days_past_due"] or -1)
            assert item["oldest_dpd"] == worst["days_past_due"]

            # The real invariant: the customer's band is at least as severe as every
            # contract they hold. Taking it from contracts[0] breaks this silently the
            # moment a customer's second contract is the worse one.
            assert item["aging_bucket"] in {c["aging_bucket"] for c in contracts}
            assert SEVERITY[item["aging_bucket"]] == max(
                SEVERITY[c["aging_bucket"]] for c in contracts
            ), "the customer's band is less severe than a contract they hold"

    def test_a_non_performing_contract_drags_the_customer_band_even_when_listed_second(self):
        """Status wins over the number, and it must win at the customer level too —
        otherwise a customer with one NPL contract reads as merely overdue."""
        from app.money.band_sets import resolve_band
        from app.main import _customer_band

        band = _customer_band(
            [("PAST_DUE", 12), ("NON_PERFORMING", 45)], band_set_code="OPERATIONAL"
        )
        assert band.code == "NPL_CONFIRMED"
        assert band.band_set_code == "OPERATIONAL"
        assert resolve_band("NON_PERFORMING", 45, "OPERATIONAL").code == band.code

"""Step 0 of the fix-all round: the shared date/money parser, and the business date
that follows the real calendar only when a database is configured."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app import clock, config, db
from app.config import settings
from app.parsing import day_first_date, money_amount


@pytest.mark.parametrize("raw, expected", [
    ("05/09/2026", date(2026, 9, 5)),          # day first, never 9 May
    ("5/9/26", date(2026, 9, 5)),
    ("18/7/2569", date(2026, 7, 18)),          # Buddhist era
    ("2569-07-18", date(2026, 7, 18)),
    ("2026-06-30 14:58:58", date(2026, 6, 30)),
    ("31.12.2026", date(2026, 12, 31)),
    (datetime(2026, 1, 2, 3, 4), date(2026, 1, 2)),
    ("", None), ("  ", None), ("-", None), (None, None), (False, None),
])
def test_day_first_dates(raw, expected):
    assert day_first_date(raw) == expected


@pytest.mark.parametrize("raw", ["31/02/2026", "07/18/2026", "13/13/2026", "soon", "2026/13/01"])
def test_an_impossible_or_unreadable_date_raises(raw):
    with pytest.raises(ValueError):
        day_first_date(raw)


@pytest.mark.parametrize("raw, expected", [
    ("฿1,000.00", Decimal("1000.00")),
    ("1,000.00 บาท", Decimal("1000.00")),
    ("(500.00)", Decimal("-500.00")),
    (" 12 345.5 ", Decimal("12345.5")),
    (1500, Decimal("1500")),
    (1500.25, Decimal("1500.25")),
    ("", None), ("-", None), (None, None),
])
def test_money_amounts(raw, expected):
    assert money_amount(raw) == expected


@pytest.mark.parametrize("raw", ["abc", "1.2.3", "NaN", "Infinity"])
def test_an_unreadable_amount_raises(raw):
    with pytest.raises(ValueError):
        money_amount(raw)


def test_the_pin_wins(monkeypatch):
    monkeypatch.setenv("VOLT_BUSINESS_DATE", "2026-01-15")
    assert settings.business_date == date(2026, 1, 15)
    assert not config.business_date_is_live()


def test_no_database_keeps_the_demo_date(monkeypatch):
    monkeypatch.delenv("VOLT_BUSINESS_DATE", raising=False)
    monkeypatch.setattr(db, "configured", lambda: False)
    assert settings.business_date == config.DEMO_BUSINESS_DATE


def test_a_database_runs_on_today_in_bangkok_with_the_wall_clock(monkeypatch):
    monkeypatch.delenv("VOLT_BUSINESS_DATE", raising=False)
    monkeypatch.setattr(db, "configured", lambda: True)
    config._today_cache["at"] = -60.0
    today = datetime.now(timezone(timedelta(hours=7))).date()
    assert settings.business_date == today
    assert config.business_date_is_live()
    assert clock.business_now().date() == today
    # a record for another day still uses the synthetic day clock
    assert clock.business_now(date(2026, 10, 23)).date() == date(2026, 10, 23)


def test_an_explicit_set_wins_and_never_touches_the_stored_default():
    saved = settings.business_date
    settings.business_date = date(2026, 11, 1)
    try:
        assert settings.business_date == date(2026, 11, 1)
        assert config.for_current().business_date == config.DEMO_BUSINESS_DATE
    finally:
        settings.business_date = saved

"""Day-first dates and money amounts from PEAK and Odoo files (fix-all Step 0).

One parser, so no import door keeps its own. The New Order Master sheet is NOT a
user of this module: its leasing tabs write four-digit-year dates month-first (its
cash tab day-first), and it keeps scripts/import_master_sheet.parse_date.
"""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})")
_DMY = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})$")
_MONEY_NOISE = re.compile(r"฿|บาท|THB|,|\s", re.IGNORECASE)


def day_first_date(value):
    """d/m/y (also d.m.y and d-m-y) → date. A two-digit year is 20yy, a Buddhist-era
    year (above 2400) loses 543, ISO passes through. Blank → None. A non-empty value
    that is not a real calendar date raises ValueError, so the caller can refuse that
    row by number instead of landing a wrong date or failing the whole file."""
    if value is None or value is False:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text == "-":
        return None
    match = _ISO.match(text)
    if match:
        year, month, day = (int(part) for part in match.groups())
    else:
        match = _DMY.match(text)
        if not match:
            raise ValueError("not a date: %r" % text)
        day, month, year = (int(part) for part in match.groups())
        if year < 100:
            year += 2000
    if year > 2400:
        year -= 543
    return date(year, month, day)          # ValueError for 31/02 or month 13


def money_amount(value):
    """"฿1,000.00", "1,000.00 บาท", "(500.00)" → Decimal (the last is −500.00).
    Blank or "-" → None. Anything else that is not a finite number raises ValueError —
    an unreadable amount must never read as "nothing owed"."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, Decimal)):
        amount = Decimal(value)
    elif isinstance(value, float):
        amount = Decimal(str(value))
    else:
        text = str(value).strip()
        if not text or text == "-":
            return None
        negative = text.startswith("(") and text.endswith(")")
        cleaned = _MONEY_NOISE.sub("", text[1:-1] if negative else text)
        try:
            amount = Decimal(cleaned)
        except InvalidOperation:
            raise ValueError("not an amount: %r" % text) from None
        if negative:
            amount = -amount
    if not amount.is_finite():
        raise ValueError("not an amount: %r" % value)
    return amount

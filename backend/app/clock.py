"""One clock (round-3 J3-19).

Every stamp the app wrote combined `settings.business_date` with the MACHINE's live
time of day, so work done at 00:36 real time was recorded as 2026-10-23T00:36 and the
history read out of order against anything stamped from the business day itself (the
personas' rows landed at 23:59, 00:10, 00:14, 00:22).

This module is the only place a "now" is made. It is a business clock: it opens at the
working day's opening hour and advances one second per stamp, so stamps are monotonic,
ordered as they were written, and never read 23:59 or 00:09 of whatever the real day
happens to be. It is deliberately NOT the wall clock — the app runs on a fixed demo
business date, and two clocks were the defect.

It also formats a moment for an officer to read (round-3 J3-15): the BUSINESS day in
Bangkok local time, never a raw UTC wall clock.
"""
from datetime import datetime, time, timedelta, timezone

from . import config
from .config import settings

DAY_OPENS = time(9, 0, 0)
DAY_CLOSES = time(23, 59, 59)
BANGKOK = timezone(timedelta(hours=7))

_state = {"tick": 0}


def reset():
    """Test seam: the day opens again at 09:00:00."""
    _state["tick"] = 0


def _wall(business_date):
    """Bangkok wall time when the business date follows the real calendar (2026-09-24:
    real data runs on today) and the caller asked for today; else None. The demo world
    and every pinned run keep the synthetic clock below."""
    if not config.business_date_is_live():
        return None
    now = datetime.now(BANGKOK).replace(tzinfo=None)
    return now if business_date in (None, now.date()) else None


def business_now(business_date=None) -> datetime:
    """The business date at the next second of the working day."""
    wall = _wall(business_date)
    if wall is not None:
        return wall
    bd = business_date or settings.business_date
    moment = datetime.combine(bd, DAY_OPENS) + timedelta(seconds=_state["tick"])
    _state["tick"] += 1
    closes = datetime.combine(bd, DAY_CLOSES)
    return moment if moment <= closes else closes


def stamp(business_date=None) -> str:
    return business_now(business_date).isoformat(timespec="seconds")


def peek(business_date=None) -> datetime:
    """The clock without spending a tick — for age arithmetic, never for a record."""
    wall = _wall(business_date)
    if wall is not None:
        return wall
    bd = business_date or settings.business_date
    moment = datetime.combine(bd, DAY_OPENS) + timedelta(seconds=_state["tick"])
    return min(moment, datetime.combine(bd, DAY_CLOSES))


def to_local(moment):
    """A moment as Bangkok local time. A tz-aware value is converted; a naive one is
    already local (this app writes naive local stamps)."""
    if isinstance(moment, str):
        try:
            moment = datetime.fromisoformat(moment.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(moment, datetime):
        return None
    return moment.astimezone(BANGKOK).replace(tzinfo=None) if moment.tzinfo else moment


def local_stamp_en(moment, business_date=None) -> str:
    """English twin of local_stamp_th: "23/10/2026 at 09:12"."""
    bd = business_date or settings.business_date
    local = to_local(moment)
    return "%02d/%02d/%d%s" % (bd.day, bd.month, bd.year, (" at %s" % local.strftime("%H:%M")) if local else "")


def local_stamp_th(moment, business_date=None) -> str:
    """Round-3 J3-15: a refusal quotes the BUSINESS day in Bangkok local time — never
    the server's raw UTC wall clock ("2026-09-02 17:42:30+00:00" in front of an officer
    working 23/10/2026). Returns "23/10/2026 เวลา 09:12 น.".
    """
    bd = business_date or settings.business_date
    local = to_local(moment)
    return "%02d/%02d/%d%s" % (bd.day, bd.month, bd.year,
                               (" เวลา %s น." % local.strftime("%H:%M")) if local else "")

"""Ruling/policy codes live in code, structured fields and the action log — never in display prose."""
import re

from app import cases, collection_kpi, uat_tasks
from app.routers import settings as settings_router
from app.routers import today

CODE = re.compile(r"\b(CF1|C3|C5|R12|OD-\d+|OQ-\d+|SVC-\d+|REQ-[A-Z]+-\d+|DEBT-[A-Z]+-\d+|W10|S12)\b|[Rr]uling \d+")


def test_prose_constants_carry_no_codes():
    prose = [cases.ALLOCATION_HOLD_TH, cases.ALLOCATION_HOLD_EN, today.ALLOCATION_NOTE_STANDING_TH,
             collection_kpi.TEAM_NOTE_TH, *uat_tasks.LIMITATIONS, *settings_router.OPEN.values(),
              *(t for pair in settings_router.LOCK_NOTE.values() for t in pair)]
    for text in prose:
        assert not CODE.search(text), text

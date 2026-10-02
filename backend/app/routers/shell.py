"""The shell's one summary — GET /v1/shell/summary (Delta-100 D2b / SH1 / SH2 / SH4).

The rail reads three things here: the workload footer (prototype 131-138), the
per-row badge counts (1235-1252), and the KPI strip under the wordmark (103-106,
1410). Every figure is the one an existing helper already serves — today.build()
for the Today badge, team_performance.scope_counts/queues for the rest and
reports.weekly() for the cash-in strip — so the rail and the screens behind it
cannot drift apart, and nothing is computed a second time in this file.
"""
from fastapi import APIRouter, Header, Query

from .. import cases as cases_domain
from .. import errors
from .. import reports
from .. import team_performance
from .. import today as today_domain
from ..config import settings
from .settings import REGISTER as SETTINGS_REGISTER

router = APIRouter()


@router.get("/v1/shell/summary")
def shell_summary(officer: str = Query(default=None), x_volt_officer: str = Header(default=None)):
    cs = cases_domain.for_current()
    # The same sweep /v1/today runs before build(), so the Today badge is exactly the
    # number that page shows — a promise that broke today has already broken.
    cases_domain.detect_broken_ptps(cs, settings.business_date)
    officer = (officer or "").strip() or None
    known = today_domain.known_officers(cs, acting=(x_volt_officer or "").strip() or None)
    if officer and officer not in known:
        raise errors.validation_failed([{
            "pointer": "/officer", "code": "unknown",
            "message": "%r is not an officer on this work book." % officer,
            "message_th": "ไม่รู้จักเจ้าหน้าที่ที่ระบุ กรุณาเลือกจากรายชื่อทีม",
        }])
    # ONE build of the desk. The badge is scoped to the officer afterwards — the same
    # set the officer-filtered build would produce, because that filter is the same
    # case comparison and no other filter is applied here. The unfiltered build is
    # also what reports.weekly() needs, so the shell no longer builds the whole book
    # twice (measured 2026-09-20: ~1s of the summary's cost was the second build).
    data = today_domain.build()
    items = data["items"]
    scoped = items if not officer else [i for i in items if i["case"]["officer_uid"] == officer]
    today_total = len(scoped)
    today_routine = sum(1 for i in scoped if i["tier"] == "ROUTINE")
    cases_total, _in_scope = team_performance.scope_counts(cs)
    queue = team_performance.queues(cs)

    # The strip's cash-in against the target a Manager saved, read from the same
    # weekly payload GET /v1/reports/weekly serves (management_summary.cash_in /
    # targets / achievement). No target saved means target and achieved are both
    # None — REQ-KPI-020, never a made-up bar.
    payload = reports.weekly(data=data)
    management = payload.get("management_summary") or {}
    cash_in = (management.get("cash_in") or {}).get("total")
    targets = management.get("targets") or {}
    achievement = management.get("achievement") or {}
    period = payload.get("period") or {}
    week, week_year = period.get("week"), period.get("week_year")

    return {
        "business_date": str(settings.business_date),
        "workload": {**team_performance.workload(cs), "officer": officer},
        "badges": {
            # The prototype's rail counts, each the number its own screen serves:
            # Today's desk total, the work book's rows, the four queues, and the
            # register's own seven rows (routers/settings.py REGISTER).
            "today": today_total,
            # The badge the rail carried before T2-05 (items due now, routine
            # excluded) is served beside the total so neither reading is lost.
            "today_due": today_total - today_routine,
            "book": cases_total,
            "reviews": queue["reviews_open"],
            "pipeline": queue["pipeline"],
            "payments": queue["peak_not_approved"],
            "recovery": queue["npl_cases"],
            "settings": len(SETTINGS_REGISTER),
        },
        "kpi": {
            "value": cash_in,
            "target": targets.get("total"),
            "achieved": achievement.get("total"),
            "period": period.get("label"),
            "week_label": ("WK-%02d/%d" % (week, week_year)) if week and week_year else None,
        },
    }

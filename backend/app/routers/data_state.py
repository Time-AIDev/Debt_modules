"""The import epoch a screen reads and the session's own catch-up button.

`GET /v1/data-state` answers three questions without touching a store: which epoch
the process serves, which epoch THIS session last seeded from, and whether that
makes the session stale. `POST /v1/session:refresh-imports` runs the same heal the
per-request hook runs, on demand — the button on the stale banner, for a person who
would rather not wait for the next navigation (sync audit, 2026-09-20).
"""
from fastapi import APIRouter

from .. import data_epoch, import_sync
from .. import book_source

router = APIRouter()


def _source():
    try:
        return book_source.source_summary()
    except Exception:                                  # noqa: BLE001 — a state read never 500s
        return None


_PEAK = {"key": None, "value": None}


def _peak_as_of():
    """The applied PEAK report's date, read from the served book.

    Today fetched `/v1/pipelines/peak-report/last-run` just to print "ข้อมูล ณ …";
    the fact is already on every customer's PEAK block, so it travels with the
    freshness state instead. Cached per import epoch: applying a report moves the
    epoch, so the loop runs once per import, not once per screen."""
    key = data_epoch.current()
    if _PEAK["key"] == key:
        return _PEAK["value"]
    from .. import main
    dates = []
    for customer in main.CUSTOMERS:
        peak = (getattr(customer, "sheet", None) or {}).get("peak") or {}
        if peak.get("report_as_of"):
            dates.append(str(peak["report_as_of"]))
    _PEAK.update(key=key, value=max(dates) if dates else None)
    return _PEAK["value"]


def _state():
    epoch = data_epoch.current()
    seen = import_sync.seen_epoch()
    # No `last_lead_run` here: the freshness line reads the serving block and the
    # PEAK date; the crm card reads the run from the overview. It cost a query per
    # screen mount for a field no screen rendered.
    return {"epoch": epoch, "seen_epoch": seen, "stale": seen < epoch,
            "serving": _source(), "peak_as_of": _peak_as_of()}


@router.get("/v1/data-state")
def data_state():
    return _state()


@router.get("/v1/data-sources/overview")
def data_sources_overview():
    """Everything the Data sources screen shows, in one request.

    The screen mounted with seven GETs (migration report, integration status, crm
    last-run + schedule, peak last-run + doors, plus the freshness state); the
    pipeline is the same on each, so the composition lives here. The individual
    endpoints stay for every other caller and for tests."""
    from . import integrations as integrations_router
    from . import migration as migration_router
    from . import peak_pipeline as peak_router
    from . import pipelines as pipelines_router
    return {
        "migration": migration_router.report(),
        "integrations": integrations_router.integrations_status(),
        "crm": {
            "last": pipelines_router.last_run(),
            "schedule": pipelines_router.get_schedule(),
            "runs": pipelines_router.recent_runs(),
        },
        "peak": {
            "last": peak_router.last_run(),
            "doors": peak_router.doors(),
            # Q6 / TASK-205: the frequent upload's own last run, beside the invoice one.
            "receipt": {"last": peak_router.receipt_last_run()},
        },
    }


@router.post("/v1/session:refresh-imports")
def refresh_imports():
    """Heals this session from the live landing reads and returns what moved.

    No role gate: it changes nothing but the caller's own sandbox, and the officer
    whose queue is stale is exactly who needs it."""
    summary = import_sync.ensure_current(force=True)
    return {"refreshed": bool(summary), "summary": summary or {}, **_state()}

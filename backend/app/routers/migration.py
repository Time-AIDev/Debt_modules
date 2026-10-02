"""Migration and data sources — API Surface v2.3 §8."""
from fastapi import APIRouter

from .. import migration

router = APIRouter()


@router.get("/v1/migration/report")
def report():
    return migration.run_report()


@router.get("/v1/migration/gap-list")
def gap_list():
    rows = migration.gap_list()
    return {"gap_list": rows, "meta": {"total": len(rows), "owner": "Operations (Dan)",
                                      "rule": "installed per EPC end date, not Order - Done in the sheet (⚠ I-12)"}}

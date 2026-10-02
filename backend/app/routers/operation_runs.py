"""One progress/cancellation surface for every long-running intake operation."""
from fastapi import APIRouter

from .. import audit, errors
from ..pipelines import runs

router = APIRouter()


@router.get("/v1/operation-runs/{uid}")
def get_operation_run(uid: str):
    run = runs.get(uid)
    if run is None:
        raise errors.not_found("operation run")
    return run


@router.post("/v1/operation-runs/{uid}:cancel")
def cancel_operation_run(uid: str):
    audit.describe(act="OPERATION_RUN_CANCEL_REQUESTED", subject=("operation_run", uid))
    try:
        run = runs.cancel(uid)
    except runs.RunNotCancellable:
        raise errors.Problem(
            code="run_not_cancellable",
            status=409,
            title="This operation can no longer be cancelled",
            detail="The operation has committed or already ended.",
            message_th="งานนี้บันทึกผลแล้วหรือจบแล้ว จึงยกเลิกไม่ได้",
            error_id="DEBT-RUN-0409",
        )
    if run is None:
        raise errors.not_found("operation run")
    return run

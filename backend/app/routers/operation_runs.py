"""One progress/cancellation surface for every long-running intake operation."""
from fastapi import APIRouter, Request

from .. import audit, auth, errors
from ..pipelines import runs

router = APIRouter()


@router.get("/v1/operation-runs/{uid}")
def get_operation_run(uid: str):
    run = runs.get(uid)
    if run is None:
        raise errors.not_found("operation run")
    return run


@router.post("/v1/operation-runs/{uid}:cancel")
def cancel_operation_run(uid: str, request: Request):
    run = runs.get(uid)
    if run is None:
        raise errors.not_found("operation run")
    if auth.current_config().on:
        actor = auth.ACTOR.get() or auth.resolve_session(request.scope)
        if not actor:
            raise auth.auth_required()
        if actor["role"] not in ("MANAGER", "OWNER", "OPS") and run.get("initiated_by") != auth.actor_key(actor):
            raise errors.Problem("run_owner_required", 403, "Operation owner required",
                                 "Only its initiator or an operational administrator may cancel this run.",
                                 "ยกเลิกได้เฉพาะงานของตัวเองหรือผู้ดูแลระบบ", "DEBT-RUN-0403")
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

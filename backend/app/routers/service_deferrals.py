"""Officers confirm service deferrals; accounting review is tracked separately."""
from fastapi import APIRouter, Body, Header, Query

from .. import audit, officers, service_deferrals as domain

router = APIRouter(prefix="/v1/contracts/{contract_uid}/service-deferrals")
queue_router = APIRouter()
ROLES = ("OFFICER", "SUPERVISOR", "MANAGER", "OWNER")


def actor(role, officer, accounting=False):
    role = (role or "OFFICER").upper()
    if role not in ROLES and not (accounting and role == "OPS"):
        raise domain.problem("forbidden", "เฉพาะเจ้าหน้าที่ Debt ขึ้นไปจึงจัดการการเลื่อนงวดได้", 403)
    return officers.sign({}, officer, role)[0], role


@router.get("")
def listing(contract_uid: str):
    domain._contract(contract_uid, active=False)
    return {"deferrals": domain.list_for_contract(contract_uid)}


@router.post("/preview")
def preview(contract_uid: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER"),
            x_volt_officer: str = Header(default=None)):
    actor(x_volt_role, x_volt_officer)
    return domain.preview(contract_uid, body)


@router.post("")
def confirm(contract_uid: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER"),
            x_volt_officer: str = Header(default=None)):
    by, role = actor(x_volt_role, x_volt_officer)
    audit.describe(act="SERVICE_INSTALMENTS_DEFERRED", subject=("contract", contract_uid))
    return {"deferral": domain.confirm(contract_uid, body, by, role)}


@router.post("/{uid}/reverse-preview")
def reverse_preview(contract_uid: str, uid: str, body: dict = Body(...),
                    x_volt_role: str = Header(default="OFFICER"), x_volt_officer: str = Header(default=None)):
    actor(x_volt_role, x_volt_officer)
    return domain.reverse_preview(contract_uid, uid, body.get("reason"))


@router.post("/{uid}/reverse")
def reverse(contract_uid: str, uid: str, body: dict = Body(...),
            x_volt_role: str = Header(default="OFFICER"), x_volt_officer: str = Header(default=None)):
    by, role = actor(x_volt_role, x_volt_officer)
    audit.describe(act="SERVICE_DEFERRAL_REVERSED", subject=("contract", contract_uid))
    return {"deferral": domain.reverse(contract_uid, uid, body, by, role)}


@router.post("/{uid}/accounting-review")
def accounting(contract_uid: str, uid: str, body: dict = Body(...),
               x_volt_role: str = Header(default="OFFICER"), x_volt_officer: str = Header(default=None)):
    by, role = actor(x_volt_role, x_volt_officer, accounting=True)
    audit.describe(act="SERVICE_DEFERRAL_ACCOUNTING_REVIEWED", subject=("contract", contract_uid))
    return {"deferral": domain.accounting_update(contract_uid, uid, body, by, role)}


@queue_router.get("/v1/service-deferrals")
def accounting_queue(accounting_status: str = Query(default=None)):
    if accounting_status not in (None, "PENDING_REVIEW", "REVIEWED"):
        raise domain.problem("accounting_invalid", "สถานะตรวจสอบของบัญชีไม่ถูกต้อง")
    return {"deferrals": [r for r in domain.records()
                          if not accounting_status or r["accounting"]["status"] == accounting_status]}

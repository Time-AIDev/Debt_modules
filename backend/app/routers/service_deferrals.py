"""Officers confirm service deferrals; accounting review is tracked separately."""
from copy import deepcopy
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Header, Query

from .. import audit, journey, officers, payment_claims, service_deferrals as domain

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
    result = domain.confirm(contract_uid, body, by, role)
    reconciliation = payment_claims.reconcile_current("service_deferral_confirmed")
    audit.describe(detail={"reconciliation": reconciliation})
    return {"deferral": result, "reconciliation": reconciliation}


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
    result = domain.reverse(contract_uid, uid, body, by, role)
    reconciliation = payment_claims.reconcile_current("service_deferral_reversed")
    audit.describe(detail={"reconciliation": reconciliation})
    return {"deferral": result, "reconciliation": reconciliation}


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


def _history_time(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.replace(tzinfo=ZoneInfo("Asia/Bangkok")) if result.tzinfo is None else result
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


@queue_router.get("/v1/service-deferrals/history")
def accounting_history(
    customer_uid: str = Query(default=None, min_length=1, max_length=200),
    contract_uid: str = Query(default=None, min_length=1, max_length=200),
    deferral_uid: str = Query(default=None, min_length=1, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    """Return recorded findings without replacing them with today's latest finding.

    History reads share the existing authenticated portfolio scope. Exact UIDs,
    including those of archived cases, filter the stored evidence independently
    of whether the customer is still in the currently served book.
    """
    entries = []
    customers = {}
    for row in domain.records():
        if ((customer_uid and row.get("customer_uid") != customer_uid)
                or (contract_uid and row.get("contract_uid") != contract_uid)
                or (deferral_uid and row.get("uid") != deferral_uid)):
            continue
        customer_key = row.get("customer_uid")
        if customer_key not in customers:
            customers[customer_key] = journey.customer_by_uid(customer_key)
        customer = customers[customer_key]
        for index, finding in enumerate((row.get("accounting") or {}).get("history") or []):
            entries.append({
                "uid": "%s:accounting:%d" % (row["uid"], index + 1),
                "customer_uid": customer_key,
                "customer_no": row.get("customer_no"),
                "customer_name": getattr(customer, "display_name", None) or row.get("customer_name"),
                "volt_id": getattr(customer, "volt_id", None) or row.get("volt_id"),
                "contract_uid": row.get("contract_uid"),
                "deferral_uid": row["uid"],
                "deferral_status": row.get("status"),
                "moves": deepcopy(row.get("moves") or []),
                "at": finding.get("at"), "by": finding.get("by"),
                "role": finding.get("role"), "status": finding.get("status"),
                "note": finding.get("note"),
                "document_refs": list(finding.get("document_refs") or []),
                "ordinal": index + 1,
            })
    entries.sort(key=lambda row: (_history_time(row["at"]), row["deferral_uid"], row["ordinal"]),
                 reverse=True)
    offset = (page - 1) * page_size
    return {"entries": entries[offset:offset + page_size],
            "meta": {"total": len(entries), "page": page, "page_size": page_size}}

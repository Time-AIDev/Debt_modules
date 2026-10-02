"""Public API for provisional payment claims and their reconciliation queue."""
from fastapi import APIRouter, Body, Header, Query
from fastapi.responses import JSONResponse

from .. import audit, errors, officers, payment_claims

router = APIRouter()
ROLES = ("OFFICER", "SUPERVISOR", "MANAGER", "OWNER")


def _identity(body, officer, role):
    role = (role or "OFFICER").upper()
    if role not in ROLES:
        raise errors.Problem(
            code="forbidden", status=403, title="Not this role's act",
            detail="payment claims require an operational collection role",
            message_th="บทบาทนี้ไม่มีสิทธิ์แจ้งหรือจัดการยอดชำระ",
            error_id="DEBT-IAM-0403")
    by, _governed = officers.sign(body or {}, officer, role)
    return by, role


@router.post("/v1/customers/{customer_uid}/payment-claims:preview")
def preview_claim(customer_uid: str, body: dict = Body(...),
                  x_volt_role: str = Header(default="OFFICER"),
                  x_volt_officer: str = Header(default=None)):
    _identity(body, x_volt_officer, x_volt_role)
    return payment_claims.preview(customer_uid, body.get("amount"), body.get("paid_on"),
                                  reference=body.get("reference"),
                                  evidence_uid=body.get("evidence_uid"))


@router.post("/v1/customers/{customer_uid}/payment-claims")
def create_claim(customer_uid: str, body: dict = Body(...),
                 x_volt_role: str = Header(default="OFFICER"),
                 x_volt_officer: str = Header(default=None)):
    by, role = _identity(body, x_volt_officer, x_volt_role)
    claim, created = payment_claims.create(
        customer_uid, body.get("amount"), body.get("paid_on"), by=by, role=role,
        idempotency_key=body.get("idempotency_key"), preview_version=body.get("preview_version"),
        note=body.get("note"), evidence_uid=body.get("evidence_uid"), reference=body.get("reference"))
    audit.describe(act="PAYMENT_CLAIM_CREATED" if created else "PAYMENT_CLAIM_REPLAYED",
                   subject=("customer", customer_uid),
                   detail={"claim_uid": claim["uid"], "amount": claim["amount"], "paid_on": claim["paid_on"]})
    return JSONResponse(status_code=201 if created else 200, content={"claim": claim})


@router.get("/v1/customers/{customer_uid}/payment-claims")
def list_claims(customer_uid: str):
    return {"claims": payment_claims.list_for_customer(customer_uid)}


@router.get("/v1/payment-claims")
def list_payment_claims(state: str = Query(default="PENDING")):
    rows = payment_claims.list_all(state=state or None)
    return {"claims": rows, "total": len(rows), "state": state or None}


@router.post("/v1/payment-claims/{claim_uid}:cancel")
def cancel_claim(claim_uid: str, body: dict = Body(default=None),
                 x_volt_role: str = Header(default="OFFICER"),
                 x_volt_officer: str = Header(default=None)):
    body = body or {}
    by, role = _identity(body, x_volt_officer, x_volt_role)
    claim = payment_claims.cancel(claim_uid, by=by, role=role)
    audit.describe(act="PAYMENT_CLAIM_CANCELLED", subject=("customer", claim["customer_uid"]),
                   detail={"claim_uid": claim_uid})
    return {"claim": claim}


@router.get("/v1/payment-reconciliation/exceptions")
def reconciliation_exceptions():
    rows = payment_claims.reconciliation_exceptions()
    return {"exceptions": rows, "total": len(rows)}


@router.get("/v1/customers/{customer_uid}/payment-reminders:preview")
def preview_reminder(customer_uid: str, month: str = Query(default=None)):
    return payment_claims.reminder_preview(customer_uid, month)


@router.post("/v1/customers/{customer_uid}/payment-reminders")
def send_reminder(customer_uid: str, body: dict = Body(default=None),
                  x_volt_role: str = Header(default="OFFICER"),
                  x_volt_officer: str = Header(default=None)):
    body = body or {}
    by, _role = _identity(body, x_volt_officer, x_volt_role)
    reminder, created = payment_claims.send_reminder(
        customer_uid, body.get("month"), by=by, channel=body.get("channel"))
    audit.describe(act="PAYMENT_REMINDER_SENT" if created else "PAYMENT_REMINDER_REPLAYED",
                   subject=("customer", customer_uid),
                   detail={"month": reminder["month"], "channel": reminder.get("channel")})
    return JSONResponse(status_code=201 if created else 200,
                        content={"reminder": reminder, "already_sent": not created})

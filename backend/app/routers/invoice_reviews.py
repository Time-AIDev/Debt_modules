from fastapi import APIRouter, Body, Header
from .. import invoice_reviews as domain

router = APIRouter(prefix="/v1/cases/by-customer/{customer_uid}/invoice-reviews")


@router.post("/preview")
def preview(customer_uid: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER"),
            x_volt_officer: str = Header(default=None)):
    customer = domain.authorize(customer_uid, x_volt_role.upper(), x_volt_officer)
    return domain.preview(customer, body)


@router.post("")
def confirm(customer_uid: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER"),
            x_volt_officer: str = Header(default=None)):
    role = x_volt_role.upper()
    customer = domain.authorize(customer_uid, role, x_volt_officer)
    return domain.confirm(customer, body, x_volt_officer, role)

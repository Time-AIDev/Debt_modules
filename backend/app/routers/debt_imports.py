"""Matched import apply and independent completion confirmation."""
from fastapi import APIRouter, Body, Header
from .. import audit, debt_imports as domain, journey

router = APIRouter()


@router.get("/v1/imports/previews/{uid}")
def preview(uid: str, x_volt_officer: str = Header(default=None)):
    return {"preview": domain.public_preview(domain.get_preview(uid, x_volt_officer or "officer"))}


@router.post("/v1/imports/previews/{uid}:apply")
def apply(uid: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER"),
          x_volt_officer: str = Header(default=None)):
    audit.describe(act="DEBT_IMPORT_APPLIED", subject=("import_preview", uid))
    result = domain.apply(uid, body, x_volt_officer or "officer", x_volt_role.upper())
    audit.describe(detail={key: result[key] for key in ("profile", "applied", "customers", "terminated")}
                   | {"forced_state": bool(result.get("forced")),
                      **({"force_reason": body.get("reason")} if result.get("forced") else {})})
    return {"apply": result}


@router.post("/v1/contracts/{contract_uid}/installation-confirmation")
def installation(contract_uid: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER"),
                 x_volt_officer: str = Header(default=None)):
    found = journey.contract_by_uid(contract_uid)
    if not found:
        raise domain.problem("not_found", "ไม่พบสัญญา", 404)
    audit.describe(act="INSTALLATION_CONFIRMED", subject=("contract", contract_uid))
    return {"confirmation": domain.confirm_installation(found[1], body, x_volt_officer or "officer",
                                                        x_volt_role.upper())}


@router.get("/v1/contracts/{contract_uid}/installation-confirmation")
def installation_status(contract_uid: str):
    from .. import cases, collection_eligibility
    found = journey.contract_by_uid(contract_uid)
    if not found:
        raise domain.problem("not_found", "ไม่พบสัญญา", 404)
    return {"confirmation": domain.installation_for(contract_uid) or domain.pipeline_installation_for(found[1]),
            "eligibility": collection_eligibility.for_contract(found[1], cases.contract_field_of)}

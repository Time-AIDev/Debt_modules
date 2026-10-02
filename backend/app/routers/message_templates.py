"""Durable personal message templates, isolated by authenticated principal."""
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text

from .. import audit, db, errors

router = APIRouter()


class TemplateCreate(BaseModel):
    channel: Literal["LINE", "FACEBOOK"]
    name: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1, max_length=4000)

    @field_validator("name", "body")
    @classmethod
    def not_blank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class TemplateUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1, max_length=4000)

    @field_validator("name", "body")
    @classmethod
    def not_blank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


def _owner(request, header):
    session = request.scope.get("volt_auth")
    owner = session.get("sub") if session else header
    if not owner:
        raise errors.Problem(code="auth_required", status=401, title="Sign in required",
                             detail="message templates require an authenticated principal",
                             message_th="กรุณาเข้าสู่ระบบก่อนใช้ข้อความส่วนตัว",
                             error_id="DEBT-IAM-0401")
    return str(owner)[:320]


def _view(row):
    return {key: (value.isoformat() if hasattr(value, "isoformat") else value)
            for key, value in dict(row).items() if key != "owner"}


@router.get("/v1/message-templates")
def list_templates(request: Request, channel: Optional[Literal["LINE", "FACEBOOK"]] = Query(None),
                   x_volt_officer: str = Header(default=None)):
    owner = _owner(request, x_volt_officer)
    conn = db.connect()
    try:
        where = "where owner=:owner" + (" and channel=:channel" if channel else "")
        rows = conn.execute(text(
            "select uid, owner, channel, name, body, created_at, updated_at "
            "from records.message_template %s "
            "order by channel, updated_at desc, uid" % where),
            {"owner": owner, "channel": channel}).mappings().all()
        return {"items": [_view(row) for row in rows]}
    finally:
        conn.close()


@router.post("/v1/message-templates", status_code=201)
def create_template(body: TemplateCreate, request: Request,
                    x_volt_officer: str = Header(default=None)):
    owner = _owner(request, x_volt_officer)
    uid = "mt-" + uuid.uuid4().hex[:16]
    conn = db.connect()
    try:
        with conn.begin():
            row = conn.execute(text(
                "insert into records.message_template (uid, owner, channel, name, body) "
                "values (:uid,:owner,:channel,:name,:body) "
                "returning uid, owner, channel, name, body, created_at, updated_at"),
                {"uid": uid, "owner": owner, **body.model_dump()}).mappings().one()
    finally:
        conn.close()
    audit.describe(act="MESSAGE_TEMPLATE_CREATED", subject=("message_template", uid),
                   detail={"channel": body.channel})
    return {"template": _view(row)}


@router.put("/v1/message-templates/{uid}")
def update_template(uid: str, body: TemplateUpdate, request: Request,
                    x_volt_officer: str = Header(default=None)):
    owner = _owner(request, x_volt_officer)
    conn = db.connect()
    try:
        with conn.begin():
            row = conn.execute(text(
                "update records.message_template set name=:name, body=:body, updated_at=now() "
                "where uid=:uid and owner=:owner "
                "returning uid, owner, channel, name, body, created_at, updated_at"),
                {"uid": uid, "owner": owner, **body.model_dump()}).mappings().first()
    finally:
        conn.close()
    if row is None:
        raise errors.not_found("message_template")
    audit.describe(act="MESSAGE_TEMPLATE_UPDATED", subject=("message_template", uid), detail={})
    return {"template": _view(row)}


@router.delete("/v1/message-templates/{uid}")
def delete_template(uid: str, request: Request,
                    x_volt_officer: str = Header(default=None)):
    owner = _owner(request, x_volt_officer)
    conn = db.connect()
    try:
        with conn.begin():
            row = conn.execute(text(
                "delete from records.message_template where uid=:uid and owner=:owner "
                "returning uid, channel"), {"uid": uid, "owner": owner}).mappings().first()
    finally:
        conn.close()
    if row is None:
        raise errors.not_found("message_template")
    audit.describe(act="MESSAGE_TEMPLATE_DELETED", subject=("message_template", uid),
                   detail={"channel": row["channel"]})
    return {"deleted": True, "uid": uid}

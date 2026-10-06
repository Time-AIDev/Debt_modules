"""Opaque, revocable tab credentials. No token or credential payload is logged."""
import hashlib
import json
import re
import secrets

from sqlalchemy import text

from . import db, errors


def unavailable():
    return errors.Problem("session_store_unavailable", 503, "Session store unavailable",
                          "A durable session store is required.",
                          "ตรวจสอบการเข้าสู่ระบบไม่ได้ กรุณาลองอีกครั้ง", "DEBT-AUTH-503", retryable=True)


def _hash(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def issue(payload):
    payload = with_expiry(payload)
    token = secrets.token_urlsafe(32)
    try:
        if not db.configured():
            raise unavailable()
        with db.connect() as conn, conn.begin():
            conn.execute(text(
                "insert into app.auth_session (token_hash, subject, payload) "
                "values (:h, :s, cast(:p as jsonb))"),
                {"h": _hash(token), "s": payload["sub"], "p": json.dumps(payload)})
    except Exception:
        raise unavailable() from None
    return token


def with_expiry(payload):
    """New credentials opt into TTL; existing credentials are never silently changed."""
    from . import auth
    payload = dict(payload)
    ttl = auth.current_config().tab_absolute_seconds
    if ttl:
        payload["expires_at"] = payload["iat"] + ttl
    return payload


def read(token):
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        return None
    try:
        if not db.configured():
            raise unavailable()
        with db.connect() as conn:
            row = conn.execute(text(
                "select payload from app.auth_session where token_hash=:h and revoked_at is null"),
                {"h": _hash(token)}).scalar()
            if row:
                from . import auth
                expires = row.get("expires_at")
                if expires is not None and auth._now() >= expires:
                    return None
                return dict(row, session_policy="tab")
            return None
    except Exception:
        raise unavailable() from None


def revoke(token):
    if not token or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        return
    try:
        with db.connect() as conn, conn.begin():
            conn.execute(text("update app.auth_session set revoked_at=now() where token_hash=:h"),
                         {"h": _hash(token)})
    except Exception:
        raise unavailable() from None


def revoke_subject(subject):
    try:
        with db.connect() as conn, conn.begin():
            conn.execute(text("update app.auth_session set revoked_at=now() "
                              "where subject=:s and revoked_at is null"), {"s": subject})
    except Exception:
        raise unavailable() from None

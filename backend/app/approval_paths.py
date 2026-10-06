"""Approval path definitions persist in the same store in every environment."""
import uuid
from . import session, errors

STORE = session.Store(dict, key="approval.paths")


def create(action, roles):
    if not isinstance(action, str) or not action.strip() or len(action) > 120:
        raise errors.validation_failed([{"pointer": "/action", "code": "invalid",
                                         "message": "action is a non-empty string of at most 120 characters"}])
    if not roles or any(role not in {"OFFICER", "SUPERVISOR", "MANAGER", "OWNER", "OPS"} for role in roles):
        raise errors.validation_failed([{"pointer": "/role", "code": "invalid",
                                         "message": "roles must name supported approval roles"}])
    uid = "approval-" + uuid.uuid4().hex
    row = {"uid": uid, "action": action.strip(), "roles": list(dict.fromkeys(roles))}
    STORE.for_current()[uid] = row
    return dict(row)


def list_all():
    return list(STORE.for_current().values())

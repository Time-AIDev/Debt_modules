"""Assignment checks use the authenticated identity and committed case state."""
import json
from starlette.routing import Match
from . import errors


def require_assignment(actor, assigned_officer):
    if actor.get("role") == "OFFICER" and (
            not assigned_officer or actor.get("officer") != assigned_officer):
        raise errors.Problem(
            "assignment_required", 403, "Case assignment required",
            "The authenticated officer is not assigned to this case",
            "คุณไม่มีสิทธิ์แก้ไขเคสที่ไม่ได้รับมอบหมาย", "DEBT-AUTH-0403")


def enforce(scope, actor, raw):
    if actor.get("role") != "OFFICER":
        return
    from . import cases, main
    fields = {}
    template = ""
    for route in main.app.routes:
        match, child = route.matches(scope)
        if match == Match.FULL:
            template = getattr(route, "path", "")
            fields.update(child.get("path_params", {}))
            break
    try:
        body = json.loads(raw)
        if isinstance(body, dict):
            for key, value in body.items():
                fields.setdefault(key, value)
    except (ValueError, TypeError, UnicodeDecodeError):
        pass
    # Only known domain identifiers are interpreted; malformed/unknown records
    # keep the route's existing validation and not-found response.
    uids = set()
    if isinstance(fields.get("customer_uid"), str):
        uids.add(fields["customer_uid"])
    if isinstance(fields.get("customer_uids"), list):
        uids.update(uid for uid in fields["customer_uids"] if isinstance(uid, str))
    contract = main.BY_CONTRACT.get(fields.get("contract_uid")) if isinstance(fields.get("contract_uid"), str) else None
    if contract:
        uids.add(contract[0].uid)
    children = {"/v1/case-ptps/": "ptps", "/v1/reviews/": "reviews",
                "/v1/case-issues/": "issues", "/v1/power-restrictions/": "power",
                "/v1/contacts/": "contact_log", "/v1/today/items/": "today_items"}
    collection = next((name for prefix, name in children.items() if template.startswith(prefix)), None)
    state = cases.for_current() if uids or fields.get("case_uid") or collection else None
    if collection and fields.get("uid"):
        records = getattr(state, collection)
        record = records.get(fields["uid"]) if isinstance(records, dict) else next(
            (row for row in records if row.get("uid") == fields["uid"]), None)
        if record and record.get("customer_uid"):
            uids.add(record["customer_uid"])
    if template == "/v1/contacts/{contact_id}:retract":
        record = main._retractable().get(("production", fields["contact_id"]))
        if record:
            uids.update(customer.uid for customer in main.BY_CUSTOMER.values()
                        if customer.identity_key == record["customer_key"])
            state = cases.for_current()
    if state and fields.get("case_uid"):
        uids.update(case["customer_uid"] for case in state.cases.values()
                    if case["uid"] == fields["case_uid"])
    for uid in uids:
        case = state.cases.get(uid)
        customer = main.BY_CUSTOMER.get(uid)
        if case or customer:
            require_assignment(actor, case.get("officer_uid") if case else customer.officer)

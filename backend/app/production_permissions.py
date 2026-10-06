"""Mutation permissions follow committed identifiers, including legacy API aliases.

Portfolio reads remain shared. These checks constrain writes; route-specific
business approval rules still apply after this central boundary.
"""
import json
from starlette.routing import Match
from . import auth, errors

SUPERVISORY = frozenset({"SUPERVISOR", "MANAGER", "OWNER"})
ADMIN = frozenset({"MANAGER", "OWNER"})
OPERATIONS = frozenset({"MANAGER", "OWNER", "OPS"})


def require_assignment(actor, assigned_officer):
    if actor.get("role") == "OFFICER" and (
            not assigned_officer or actor.get("officer") != assigned_officer):
        raise errors.Problem("assignment_required", 403, "Case assignment required",
                             "The authenticated officer is not assigned to this case",
                             "คุณไม่มีสิทธิ์แก้ไขเคสที่ไม่ได้รับมอบหมาย", "DEBT-AUTH-0403")


def role_required(actor, allowed):
    if actor.get("role") not in allowed:
        raise errors.Problem("role_required", 403, "Role permission required",
                             "This role cannot perform the requested operation.",
                             "บทบาทของคุณไม่มีสิทธิ์ดำเนินการนี้", "DEBT-AUTH-0404")


def _record(records, uid):
    if isinstance(records, dict):
        return records.get(uid)
    return next((row for row in records or [] if row.get("uid") == uid), None)


def _role_gate(template, actor, fields):
    role = actor.get("role")
    privileged = template.startswith(("/v1/config", "/v1/ladder-mode", "/v1/intercompany/"))
    privileged = privileged or template in ("/v1/orders/{no}/approve", "/v1/orders/{no}")
    privileged = privileged or (template.startswith("/v1/restructures/") and template.endswith(":approve"))
    privileged = privileged or template.startswith("/v1/manager-review/")
    if privileged:
        role_required(actor, ADMIN)
    elif template == "/v1/orders":
        role_required(actor, SUPERVISORY)
    elif template.startswith(("/v1/pipelines/", "/v1/imports/assignments", "/v1/peak-documents/stub")):
        role_required(actor, OPERATIONS)
    if template == "/v1/pipeline/{uid}/gates/down-payment":
        role_required(actor, SUPERVISORY)
    # OPS is operational access, not a supervisory collection role. Service ticket,
    # installation and power execution routes remain available for O&M duties.
    financial_action = template.startswith(("/v1/ptps", "/v1/case-ptps", "/v1/cash-cases/",
                                              "/v1/payment-claims", "/v1/restructures", "/v1/arrangements",
                                              "/v1/recovery-cases", "/v1/npl-cases", "/v1/receipts", "/v1/credit-notes"))
    financial_action = financial_action or any(part in template for part in (
        "/payment-claims", "/payment-reminders", "/payment-status", ":advance", ":set-stage", ":terminate"))
    financial_action = financial_action or (
        template == "/v1/cases/by-customer/{customer_uid}/contacts" and bool(fields.get("ptp")))
    if role == "OPS" and financial_action:
        role_required(actor, SUPERVISORY | {"OFFICER"})
    if auth.current_config().reauth_seconds and privileged:
        if auth._now() - actor.get("iat", 0) > auth.current_config().reauth_seconds:
            raise errors.Problem("reauth_required", 401, "Sign in again",
                                 "A recent sign-in is required for this sensitive operation.",
                                 "กรุณาเข้าสู่ระบบใหม่ก่อนดำเนินการสำคัญ", "DEBT-AUTH-0410")


def enforce(scope, actor, raw):
    if scope.get("method") not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    from . import cases, journey, main
    fields, template = {}, ""
    for route in getattr(scope.get("app"), "routes", None) or main.app.routes:
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
    _role_gate(template, actor, fields)
    if actor.get("role") != "OFFICER":
        return
    uids = set()
    for key in ("customer_uid",):
        if isinstance(fields.get(key), str):
            uids.add(fields[key])
    if isinstance(fields.get("customer_uids"), list):
        uids.update(uid for uid in fields["customer_uids"] if isinstance(uid, str))
    if template.startswith("/v1/customers/{uid}"):
        uids.add(fields["uid"])
    domain_prefixes = ("/v1/cases/", "/v1/case-ptps/", "/v1/ptps/", "/v1/service-issues/",
                       "/v1/case-issues/", "/v1/reviews/", "/v1/power-restrictions/", "/v1/contacts/",
                       "/v1/today/items/", "/v1/cash-cases/", "/v1/restructures/", "/v1/manager-review/",
                       "/v1/npl-cases/", "/v1/recovery-cases/", "/v1/repossession-lots/",
                       "/v1/arrangements/", "/v1/invoices/", "/v1/pipeline/", "/v1/peak-documents/",
                       "/v1/attachments/")
    identifiers = ("contract_uid", "case_uid", "invoice_uid", "receipt_uid", "claim_uid", "attached_to")
    if not (uids or any(fields.get(key) for key in identifiers)
            or auth._header(scope, b"x-volt-attach-to") or template.startswith(domain_prefixes)):
        return
    state = cases.for_current()
    journey_state = None

    def add(row):
        nonlocal journey_state
        if not row:
            return
        if row.get("customer_uid"):
            uids.add(row["customer_uid"])
        contract = main.BY_CONTRACT.get(row.get("contract_uid"))
        if contract:
            uids.add(contract[0].uid)
        if row.get("case_uid") or row.get("recovery_uid"):
            journey_state = journey_state or journey.for_current()
            case = journey_state.cases.get(row.get("case_uid")) or journey_state.cash_cases.get(row.get("case_uid"))
            recovery = journey_state.recovery_cases.get(row.get("recovery_uid"))
            if case:
                add(case)
            if recovery:
                add(recovery)

    add(fields)
    targets = [auth._header(scope, b"x-volt-attach-to"), fields.get("attached_to")]
    if template.startswith("/v1/attachments/") and fields.get("uid") and not template.endswith(":download"):
        from .attachments import store
        meta = store.metadata(fields["uid"])
        if meta:
            targets.append(meta.get("attached_to"))
    for target in targets:
        if not isinstance(target, str) or ":" not in target:
            continue
        kind, uid = target.split(":", 1)
        uid = uid.split(":", 1)[0]
        if kind in ("case", "customer"):
            if uid in main.BY_CUSTOMER or uid in state.cases:
                uids.add(uid)
            else:
                add(next((r for r in state.cases.values() if r["uid"] == uid), None))
        elif kind == "contract":
            add({"contract_uid": uid})
        elif kind == "contact":
            add(_record(getattr(state, "contact_log", []), uid))
        elif kind == "note":
            add(_record(getattr(state, "events", []), uid))
        elif kind == "pipeline":
            from . import invoice_pipeline
            add(invoice_pipeline.for_current().items.get(uid))
    current_children = {"/v1/case-ptps/": "ptps", "/v1/reviews/": "reviews",
                        "/v1/case-issues/": "issues", "/v1/power-restrictions/": "power",
                        "/v1/contacts/": "contact_log", "/v1/today/items/": "today_items"}
    legacy_children = {"/v1/ptps/": "ptps", "/v1/service-issues/": "issues", "/v1/cases/{uid}": "cases",
                       "/v1/cash-cases/": "cash_cases", "/v1/restructures/": "restructures",
                       "/v1/manager-review/": "reviews", "/v1/npl-cases/": "npl_cases",
                       "/v1/recovery-cases/": "recovery_cases", "/v1/repossession-lots/": "lots",
                       "/v1/arrangements/": "arrangements", "/v1/invoices/": "invoices"}
    for prefix, collection in current_children.items():
        if template.startswith(prefix) and fields.get("uid"):
            add(_record(getattr(state, collection, {}), fields["uid"]))
    for prefix, collection in legacy_children.items():
        if template.startswith(prefix) and fields.get("uid"):
            journey_state = journey_state or journey.for_current()
            add(_record(getattr(journey_state, collection, {}), fields["uid"]))
    for key in ("invoice_uid", "receipt_uid", "case_uid"):
        if isinstance(fields.get(key), str):
            journey_state = journey_state or journey.for_current()
            collection = {"invoice_uid": "invoices", "receipt_uid": "receipts", "case_uid": "cases"}[key]
            add(_record(getattr(journey_state, collection, {}), fields[key]))
    if template.startswith("/v1/pipeline/") and fields.get("uid"):
        from . import invoice_pipeline
        add(invoice_pipeline.for_current().items.get(fields["uid"]))
    if template.startswith("/v1/peak-documents/") and fields.get("uid"):
        from . import invoice_pipeline, peak_documents
        document = peak_documents.for_current().documents.get(fields["uid"])
        if document:
            add(document.get("payload", {}))
            reference = document.get("source_ref")
            add({"contract_uid": reference})
            journey_state = journey_state or journey.for_current()
            add(journey_state.invoices.get(reference))
            add(invoice_pipeline.for_current().items.get(reference))
    if fields.get("claim_uid"):
        from . import payment_claims
        add(next((r for r in payment_claims.list_all() if r["uid"] == fields["claim_uid"]), None))
    if template == "/v1/contacts/{contact_id}:retract":
        record = main._retractable().get(("production", fields["contact_id"]))
        if record:
            uids.update(customer.uid for customer in main.BY_CUSTOMER.values()
                        if customer.identity_key == record["customer_key"])
    if fields.get("case_uid"):
        uids.update(case["customer_uid"] for case in state.cases.values()
                    if case["uid"] == fields["case_uid"])
    for uid in uids:
        case = state.cases.get(uid)
        customer = main.BY_CUSTOMER.get(uid)
        if case or customer:
            require_assignment(actor, case.get("officer_uid") if case else customer.officer)

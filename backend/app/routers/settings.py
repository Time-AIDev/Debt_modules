"""Settings, dictionaries, band sets, assignment — API Surface v2.3 §7."""
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Body, Header

from .. import audit, clock, customer_search, dictionaries, errors, journey
from ..config import DECIDED, PENDING, changed_for_current, settings
from ..money import band_sets
from .today import who

router = APIRouter()

LOCKED = ("peak_write_mode",)
OPEN = {
    "invoice_owner_role": "Owner",                      # OQ-42
    "npl_review_dpd": "Owner, Whan",                     # OD-04 extended
    "npl_review_missed_no_contact": "Owner, Whan",       # OD-04 extended
    "power_restriction_approver": "Owner",               # OQ-44
}
EDITABLE = ("invoice_owner_role", "pipeline_lookahead_days", "npl_review_dpd", "npl_review_missed_no_contact",
            "power_restriction_approver", "power_restriction_min_missed", "power_restriction_require_broken_ptp",
            "review_sla_hours", "uninstall_fee_thb_per_watt", "band_set_code", "late_payment_grace_days",
            "late_payment_daily_rate", "reminder_offsets_days",
            # Delta-100 SE3: the prototype's "สิทธิ์ติดต่อรายวันต่อลูกหนี้" row was in
            # Settings but reachable by no route — it is a manager value like the rest.
            "daily_contact_limit_per_customer",
            # Delta-100 D2e: the KPI targets that have no store of their own. They are
            # config-tunable (None default), NOT part of the prototype's flat 7-row
            # register — see REGISTER below — so the register keeps its shape.
            "ptp_kept_target_pct", "contact_target_pct", "dso_target_days",
            "receipts_monthly_target", "caseload_cap")

# Delta-100 D2e/SE1: the prototype's flat register (Final v2 733-759; its SETTINGS
# rows 1383-1389) draws exactly these seven keys. The API serves each as an ordinary
# config row and this tuple is the register's shape — the KPI targets above and the
# KPI-only keys stay out of it, so adding a target never grows the register. The
# shell's settings badge counts len(REGISTER), the same number the screen draws.
REGISTER = ("late_payment_daily_rate", "allocation_component_order", "npl_dpd_threshold_days",
            "late_payment_grace_days", "reminder_offsets_days",
            "daily_contact_limit_per_customer", "service_month37_decline_allowed")

# A config key whose default is None has no Python type for `type(current)` to cast
# with; these are the types PUT builds the value as. Kept beside EDITABLE so a new
# optional key cannot be added without its type.
CONFIG_CASTS = {
    "ptp_kept_target_pct": Decimal, "contact_target_pct": Decimal,
    "dso_target_days": int, "receipts_monthly_target": Decimal, "caseload_cap": int,
}
# The keys null / "" clears back to None (the missing-target state) rather than parsing
# as a number — the same transition PUT /v1/reports/collection/{month}/targets uses.
OPTIONAL_KEYS = frozenset(CONFIG_CASTS)
# (min, max, message_th, message_en) for the keys a nonsense value would otherwise
# reach the screen from. Percentages are shares of 100; the counts and days are
# non-negative. A value outside its range is refused before anything is written.
CONFIG_RANGES = {
    "ptp_kept_target_pct": (Decimal("0"), Decimal("100"),
                            "เป้าอัตรารักษานัดต้องอยู่ระหว่าง 0 ถึง 100",
                            "The kept-rate target must be between 0 and 100"),
    "contact_target_pct": (Decimal("0"), Decimal("100"),
                           "เป้าอัตราการติดต่อต้องอยู่ระหว่าง 0 ถึง 100",
                           "The contact-rate target must be between 0 and 100"),
    "dso_target_days": (0, 3650, "เป้าวันเก็บเงินเฉลี่ยต้องไม่ติดลบ",
                        "The DSO target cannot be negative"),
    "receipts_monthly_target": (Decimal("0"), None, "เป้ารับเงินรายเดือนต้องไม่ติดลบ",
                                "The monthly receipts target cannot be negative"),
    "caseload_cap": (1, 100000, "เพดานงานต้องมีค่าตั้งแต่ 1 ขึ้นไป",
                     "The caseload cap must be at least 1"),
    "daily_contact_limit_per_customer": (1, 100, "สิทธิ์ติดต่อรายวันต้องมีค่าตั้งแต่ 1 ขึ้นไป",
                                         "The daily contact limit must be at least 1"),
}
# Redesign v2 ruling R7: an OPEN value (a decision nobody has closed) is read-only at
# every role, the Owner included — a ruling is made by decision, not by typing a value.
# Round 6 ruling 100: a DECIDED value stays Owner-only — Arina ruled these
# configurable by the Owner, not by anyone with a Manager token.
OWNER_ONLY = tuple(k for k in EDITABLE if k in DECIDED)
LOCK_NOTE = {
    "locked": ("ค่านี้ล็อกไว้ ยังรอการตัดสินใจหรือถูกกำหนดตามการตัดสินใจแล้ว แก้ไขที่นี่ไม่ได้",
               "Locked: awaiting a ruling or fixed by a standing decision; it cannot be changed here"),
    "owner_only": ("ตัดสินใจแล้ว แก้ไขได้เฉพาะเจ้าของระบบ", "Decided: only the Owner may change it"),
    "manager": ("ผู้จัดการหรือเจ้าของระบบแก้ไขได้", "A Manager or the Owner may change it"),
}

# Final v2 (prototype 1384-1389, 2605-2606): an enumerated setting is chosen from
# its options, never typed. These are declared presets, not a computation — the SOP
# handed the officer D-1/D0 and the interview said D-3/D0, so the Manager picks one.
REMINDER_OFFSET_PRESETS = (
    {"value": "3,0", "label_th": "D-3 / D0", "label_en": "D-3 / D0"},
    {"value": "1,0", "label_th": "D-1 / D0", "label_en": "D-1 / D0"},
    {"value": "7,1,0", "label_th": "D-7 / D-1 / D0", "label_en": "D-7 / D-1 / D0"},
)

# The design draws od02, svc37 and od04 in the register (prototype 1384-1389). They
# are decisions nobody has closed, so the rows are read-only at every role (R7) and
# carry, where the design draws a select, the values a ruling would choose between.
PENDING_OPTIONS = {
    "allocation_component_order": [
        {"value": "", "label_th": "ยังไม่ตัดสิน", "label_en": "Not yet decided"},
        {"value": "PENALTY_FIRST", "label_th": "ตัดค่าปรับก่อน", "label_en": "Penalty first"},
        {"value": "INSTALMENT_FIRST", "label_th": "ตัดค่างวดก่อน", "label_en": "Instalment first"},
    ],
    "service_month37_decline_allowed": [
        {"value": "UNDECIDED_BILLED_EITHER_WAY", "label_th": "ออกบิลตามแนวทางที่ใช้อยู่",
         "label_en": "Billed as today — declining changes nothing"},
        {"value": "CUSTOMER_MAY_DECLINE", "label_th": "ให้ลูกค้าปฏิเสธได้", "label_en": "The customer may decline"},
    ],
}
DESIGN_PENDING = ("allocation_component_order", "service_month37_decline_allowed", "npl_dpd_threshold_days")


def _lock(key):
    if key in LOCKED or key in OPEN or key not in EDITABLE:
        return "locked"
    return "owner_only" if key in OWNER_ONLY else "manager"


def _editable_by(key):
    if key in LOCKED or key in OPEN or key not in EDITABLE:
        return None
    return "OWNER" if key in OWNER_ONLY else "MANAGER"


def _may_edit(key, role):
    by = _editable_by(key)
    if by is None:
        return False
    return role == "OWNER" or (by == "MANAGER" and role in ("MANAGER", "OWNER"))


def _role(header):
    return (header or "OFFICER").upper()


@router.get("/v1/dictionaries")
def list_dictionaries():
    d = dictionaries.for_current()
    return {"dictionaries": {name: d.list(name, include_inactive=True) for name in dictionaries.DICTIONARIES},
            "history": d.history}


@router.get("/v1/dictionaries/{name}")
def get_dictionary(name: str):
    d = dictionaries.for_current()
    try:
        return {"name": name, "values": d.list(name, include_inactive=True)}
    except dictionaries.DictionaryError:
        raise errors.not_found("dictionary")


@router.post("/v1/dictionaries/{name}/values", status_code=201)
def add_value(name: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER")):
    audit.describe(act="DICTIONARY_VALUE_ADDED", subject=("dictionary", name), detail={"code": (body or {}).get("code")})
    if _role(x_volt_role) not in ("MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Manager only", detail="Only a Manager edits a dictionary",
                             message_th="เฉพาะผู้จัดการแก้ไขรายการได้", error_id="DEBT-IAM-0403")
    d = dictionaries.for_current()
    try:
        row = d.add(name, body["code"], body["label_th"], body["label_en"], by=body.get("by", "manager"))
    except dictionaries.DictionaryError:
        raise errors.not_found("dictionary")
    except (KeyError, ValueError) as exc:
        raise errors.validation_failed([{"pointer": "/code", "code": "invalid", "message": str(exc), "message_th": "ข้อมูลไม่ครบหรือซ้ำ"}])
    return {"value": row}


@router.post("/v1/dictionaries/{name}/values/{code}:deactivate")
def deactivate_value(name: str, code: str, body: dict = Body(default={}), x_volt_role: str = Header(default="OFFICER")):
    audit.describe(act="DICTIONARY_VALUE_DEACTIVATED", subject=("dictionary", name), detail={"code": code})
    if _role(x_volt_role) not in ("MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Manager only", detail="Only a Manager edits a dictionary",
                             message_th="เฉพาะผู้จัดการแก้ไขรายการได้", error_id="DEBT-IAM-0403")
    d = dictionaries.for_current()
    try:
        return {"value": d.deactivate(name, code, by=body.get("by", "manager"))}
    except dictionaries.DictionaryError:
        raise errors.not_found("value")


@router.get("/v1/config")
def get_config(x_volt_role: str = Header(default="OFFICER")):
    return _config_rows(_role(x_volt_role))


def _config_rows(role):
    """Plain function behind GET /v1/config so PUT can return the same rows.
    Round-2 UAT (thip T2-07): PUT called the route and received a Header object."""
    keys = {}
    stamps = changed_for_current()
    for key in EDITABLE + LOCKED + ("penalty_invoicing_enabled", "power_restriction_enabled"):
        value = _shown(getattr(settings, key, None))
        decided = DECIDED.get(key)
        stamp = stamps.get(key)
        keys[key] = {"value": value,
                     "state": "LOCKED" if key in LOCKED else (
                         "OPEN" if key in OPEN else ("DECIDED" if decided else "SET")),
                     "owner": OPEN.get(key),
                     # J-53: `editable` is answered for the CALLER's role; `editable_by` names the floor.
                     "editable": _may_edit(key, role), "editable_by": _editable_by(key),
                     # R7: one plain word for the lock, and a short sentence saying it.
                     "lock": _lock(key), "note_th": LOCK_NOTE[_lock(key)][0], "note_en": LOCK_NOTE[_lock(key)][1],
                     # B8: who changed it last in this session's store, and when (None = never).
                     "changed_by": stamp["by"] if stamp else None,
                     "changed_by_role": stamp["role"] if stamp else None,
                     "changed_at": stamp["at"] if stamp else None}
        if decided:
            # Ruling 100: a decided value carries who decided it, when, and on what —
            # so the screen can stop calling it undecided without going silent instead.
            keys[key].update({"decision": decided.decision, "decided_by": decided.decided_by,
                              "decided_on": decided.decided_on.isoformat(),
                              "ruling": decided.ruling, "basis": decided.basis})
    # Final v2 (prototype 2605-2606): the enumerated rows carry their options so the
    # screen draws a select. Only values the API would accept are offered — a retired
    # band set is not one of them (PUT /v1/config refuses it, so it is never shown).
    keys["band_set_code"]["options"] = [
        {"value": row["code"], "label_th": row["label_th"], "label_en": row["label_en"]}
        for row in band_sets.describe() if row["active"]]
    keys["reminder_offsets_days"]["options"] = [dict(option) for option in REMINDER_OFFSET_PRESETS]
    # The pending keys the design draws in the register (prototype 1384-1389): a
    # read-only row whose state is the open ruling, with the options a ruling would
    # choose between. They stay out of EDITABLE, so PUT refuses them by name — a
    # ruling is made by decision, not by typing a value (R7).
    for key in DESIGN_PENDING:
        rule = PENDING[key]
        keys[key] = {"value": _shown(getattr(settings, key, None)),
                     "state": "OPEN", "owner": rule.owner,
                     "editable": False, "editable_by": None,
                     "lock": "locked", "note_th": LOCK_NOTE["locked"][0], "note_en": LOCK_NOTE["locked"][1],
                     "changed_by": None, "changed_by_role": None, "changed_at": None,
                     "options": [dict(option) for option in PENDING_OPTIONS.get(key, [])]}
    from .. import cases as cases_domain
    return {"config": keys, "role": role,
            # Round-3 J3-07/J3-21: every value in POWER_STATES carries its Thai label,
            # served once so no screen has to invent one.
            "power_states": [{"code": c, "label_th": cases_domain.POWER_STATE_LABEL_TH[c]}
                             for c in cases_domain.POWER_STATES],
            "role_labels_th": dict(cases_domain.ROLE_LABEL_TH),
            "pending": {k: {"decision": r.decision, "owner": r.owner, "state": r.state} for k, r in PENDING.items()}}


def _shown(value):
    """A config value as the rows serve it: None stays None; a tuple reads "3,0"."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return ",".join(str(v) for v in value)          # N2-13: "3,0", not "(3, 0)"
    return str(value)


@router.put("/v1/config")
def put_config(body: dict = Body(...), x_volt_role: str = Header(default="OFFICER"),
               x_volt_officer: str = Header(default=None)):
    role = _role(x_volt_role)
    if role not in ("MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Manager only", detail="Only a Manager edits configuration",
                             message_th="เฉพาะผู้จัดการแก้ไขการตั้งค่าได้", error_id="DEBT-IAM-0403")
    staged = []
    for key, value in body.items():
        if key in LOCKED:
            raise errors.Problem(code="config_locked", status=422, title="Locked by decision",
                                 detail="%s is locked by a standing decision" % key, message_th="ค่านี้ถูกล็อกไว้ตามการตัดสินใจที่มีผลอยู่แล้ว",
                                 error_id="DEBT-CFG-0425", extensions={"key": key})
        if key in OPEN:
            raise errors.Problem(code="config_awaiting_ruling", status=422, title="Awaiting a ruling",
                                 detail="This setting is awaiting a ruling — it cannot be changed here",
                                 message_th="ค่านี้ยังรอการตัดสินใจ แก้ไขที่นี่ไม่ได้",
                                 error_id="DEBT-CFG-0426", extensions={"key": key})
        if key not in EDITABLE:
            raise errors.validation_failed([{"pointer": "/" + key, "code": "not_editable", "message": "not editable here", "message_th": "แก้ไขค่านี้ที่นี่ไม่ได้"}])
        if not _may_edit(key, role):
            decided = DECIDED.get(key)
            detail = "%s was decided by %s and stays Owner-tunable; only the Owner may change it" % (key, decided.decided_by)
            raise errors.Problem(code="forbidden", status=403, title="Owner only", detail=detail,
                                 message_th="ค่านี้แก้ไขได้เฉพาะเจ้าของระบบ",
                                 error_id="DEBT-IAM-0403",
                                 extensions={"key": key, "editable_by": "OWNER"})
        if key == "band_set_code":
            # Round-2 UAT outage: an unknown code here made every band lookup raise for
            # every session until a person set it back. Validate at the gate.
            known = {row["code"]: row for row in band_sets.describe()}
            if str(value) not in known:
                raise errors.validation_failed([{"pointer": "/band_set_code", "code": "band_set_unknown",
                                                 "message": "no band set with code %s" % value,
                                                 "message_th": "ไม่มีชุดบัคเก็ตรหัสนี้ เลือกจากรายการชุดที่มี",
                                                 "known": sorted(known)}])
            if not known[str(value)]["active"]:
                raise errors.validation_failed([{"pointer": "/band_set_code", "code": "band_set_inactive",
                                                 "message": "band set %s is deactivated" % value,
                                                 "message_th": "ชุดบัคเก็ตนี้ถูกปิดใช้งานแล้ว"}])
        current = getattr(settings, key)
        try:
            if key in OPTIONAL_KEYS and (value is None or value == ""):
                # Delta-100 D2e: the clear transition for a target that has no store
                # default — null / "" returns it to "nobody set one", never to 0.
                new = None
            elif key == "reminder_offsets_days":
                new = _offsets(value)
            else:
                cast = CONFIG_CASTS.get(key, type(current))
                new = (str(value).lower() == "true") if cast is bool else cast(value)
            if isinstance(new, Decimal) and not new.is_finite():
                raise ValueError(value)
            if new is not None and key in CONFIG_RANGES:
                lo, hi, msg_th, msg_en = CONFIG_RANGES[key]
                if new < lo or (hi is not None and new > hi):
                    raise errors.validation_failed([{
                        "pointer": "/" + key, "code": "out_of_range",
                        "message": msg_en, "message_th": msg_th}])
        except (InvalidOperation, TypeError, ValueError):
            raise errors.validation_failed([{"pointer": "/" + key, "code": "invalid", "message": "bad value", "message_th": "ค่าไม่ถูกต้อง"}])
        staged.append((key, current, new))
    # B8: every key is checked before any is written, so a refused second key no longer
    # leaves the first one changed, and the stamp names only what really moved.
    moved = [(key, old, new) for key, old, new in staged if new != old]
    if moved:
        by = who({}, x_volt_officer, role=role)
        audit.describe(act="CONFIG_SET", subject=("config", ",".join(key for key, _o, _n in moved)),
                       detail={"keys": {key: {"from": _shown(old), "to": _shown(new)} for key, old, new in moved}})
        stamps = changed_for_current()
        at = clock.stamp()
        for key, _old, new in moved:
            setattr(settings, key, new)
            stamps[key] = {"by": by, "role": role, "at": at}
    return _config_rows(role)


def _offsets(value):
    """N2-13: a list, or a string like "1,0" / "D-1/D0"; days before the due date, distinct, descending."""
    import re
    if isinstance(value, (list, tuple)):
        raw = [int(v) for v in value]
    else:
        raw = [int(x) for x in re.findall(r"-?\d+", str(value))]
        raw = [abs(x) for x in raw]
    if not raw or any(x < 0 or x > 31 for x in raw):
        raise ValueError("offsets must be 0..31 days")
    return tuple(sorted(set(raw), reverse=True))


@router.get("/v1/band-sets")
def list_band_sets():
    rows = band_sets.describe()
    return {"band_sets": rows, "active": settings.band_set_code,
            # Round-3 J3-11: the report's band chooser reads THIS list. A deactivated set
            # is still offered (figures labelled with it must resolve) but is marked, so
            # nobody reports on a retired set without being told.
            # Round-4 J4-13: the chooser reads the set's own Thai name, not its code.
            "chooser": [{"code": r["code"], "active": r["active"],
                         "label_th": r["label_th"] + ("" if r["active"] else " (ปิดใช้งานแล้ว)"),
                         "label_en": r["label_en"] + ("" if r["active"] else " (deactivated)"),
                         "note_th": None if r["active"] else "ชุดนี้ถูกปิดใช้งานแล้ว — ใช้ดูตัวเลขเก่าได้ แต่ไม่ควรใช้รายงานใหม่",
                         "note_en": None if r["active"] else "This set is deactivated — old figures still read, but do not use it for new reports"}
                        for r in rows],
            "editable": False, "edit_refusal_th": band_sets.EDIT_REFUSAL_TH,
            "edit_refusal_en": band_sets.EDIT_REFUSAL_EN}


@router.post("/v1/band-sets/{code}:activate")
def activate_band_set(code: str, body: dict = Body(default={}), x_volt_role: str = Header(default="OFFICER")):
    """Round-3 J3-38: deactivation was one click with no way back from the screen."""
    audit.describe(act="BAND_SET_ACTIVATED", subject=("band_set", code))
    if _role(x_volt_role) not in ("MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Manager only", detail="Only a Manager re-activates a band set",
                             message_th="เฉพาะผู้จัดการเปิดใช้ชุดช่วงอายุหนี้ได้", error_id="DEBT-IAM-0403")
    try:
        return {"band_set": band_sets.activate(code, by=(body or {}).get("by", "manager"))}
    except band_sets.BandSetUnknown:
        raise errors.not_found("band_set")


@router.post("/v1/band-sets/{code}:deactivate")
def deactivate_band_set(code: str, body: dict = Body(default={}), x_volt_role: str = Header(default="OFFICER")):
    """Judge J-54: a set is deactivated, never deleted; the set in use cannot be."""
    audit.describe(act="BAND_SET_DEACTIVATED", subject=("band_set", code))
    if _role(x_volt_role) not in ("MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Manager only", detail="Only a Manager deactivates a band set",
                             message_th="เฉพาะผู้จัดการปิดใช้ชุดช่วงอายุหนี้ได้", error_id="DEBT-IAM-0403")
    if code == settings.band_set_code:
        raise errors.Problem(code="band_set_in_use", status=409, title="Band set in use",
                             detail="%s is the active band_set_code; switch the setting first" % code,
                             message_th="ชุดนี้กำลังใช้งานอยู่ (band_set_code) เปลี่ยนชุดที่ใช้งานก่อนจึงปิดได้",
                             error_id="DEBT-CFG-0409", extensions={"code": code, "band_set_code": settings.band_set_code})
    try:
        return {"band_set": band_sets.deactivate(code, by=(body or {}).get("by", "manager"))}
    except band_sets.BandSetUnknown:
        raise errors.not_found("band_set")


@router.post("/v1/band-sets", status_code=201)
def add_band_set(body: dict = Body(...), x_volt_role: str = Header(default="OFFICER")):
    audit.describe(act="BAND_SET_ADDED")
    if _role(x_volt_role) not in ("MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Manager only", detail="Only a Manager adds a band set",
                             message_th="เฉพาะผู้จัดการเพิ่มชุดช่วงอายุหนี้ได้", error_id="DEBT-IAM-0403")
    try:
        return {"band_set": band_sets.register(body.get("code"), body.get("bands"),
                                               by=body.get("by", "manager"),
                                               label_th=body.get("label_th"))}
    except band_sets.BandSetInvalid as exc:
        # Round-4 J4-14: a blank set code or band code is refused BY NAME, not accepted
        # as a set nothing can render and no route can reach.
        raise errors.validation_failed([{"pointer": exc.pointer, "code": "band_set_invalid",
                                         "message": exc.message, "message_th": exc.message_th}])
    except (KeyError, TypeError, ValueError) as exc:
        raise errors.validation_failed([{"pointer": "/bands", "code": "invalid", "message": str(exc), "message_th": "ช่วงไม่ถูกต้อง"}])


@router.post("/v1/customers/{uid}/assign")
def assign_customer(uid: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER")):
    audit.describe(act="CUSTOMER_ASSIGNED", subject=("customer", uid), detail={"officer_uid": (body or {}).get("officer_uid")})
    if _role(x_volt_role) not in ("SUPERVISOR", "MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Supervisor or above", detail="Assignment is a Supervisor's act",
                             message_th="เฉพาะหัวหน้างานขึ้นไปมอบหมายงานได้", error_id="DEBT-IAM-0403")
    customer = journey.customer_by_uid(uid)
    if customer is None:
        raise errors.not_found("customer")
    from .. import cases as cases_domain
    cs = cases_domain.for_current()
    # Ruling 40: the customer-level fact lives in the per-session overlay (mirrors
    # officer_overlay/recovery_overlay in journey.py) — never written onto the shared
    # Customer fixture (customer.officer), which the old line 242 did and which
    # outlives every session, not merely leaks across ones that are concurrent.
    journey.for_current().officer_overlay[uid] = body["officer_uid"]
    customer_search.assign_officer(uid, body["officer_uid"])
    if uid in cs.cases:
        cs.cases[uid]["officer_uid"] = body["officer_uid"]
    return {"customer_uid": uid, "officer_uid": body["officer_uid"]}


# --- feedback round 2: bulk assignment and the portfolio split (TASK-107/116) -------
# Q5's gate for the row-level act is SUPERVISOR+; R-C puts the portfolio split (and
# its template) in a manager's hands.

def require_manager(x_volt_role, detail, th):
    if _role(x_volt_role) not in ("MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Manager or above", detail=detail,
                             message_th=th, error_id="DEBT-IAM-0403")


def _assign_many(customer_uids, officer_uid):
    """The two writes assign_customer performs, once per uid, in one pass. Callers
    validate first — this helper performs no checks of its own (ruling 40's overlay
    is the served fact; the case row follows it)."""
    from .. import cases as cases_domain
    js = journey.for_current()
    cs = cases_domain.for_current()
    for uid in customer_uids:
        js.officer_overlay[uid] = officer_uid
        customer_search.assign_officer(uid, officer_uid)
        if uid in cs.cases:
            cs.cases[uid]["officer_uid"] = officer_uid


def _assignable():
    """The collectable rows a split may touch — today_domain.build's own rows, so the
    bucket counts and the split select from one computation (never a second one)."""
    from .. import today as today_domain
    return today_domain.build()["items"]


def _bucket_codes():
    """The manager's buckets (R-C): the active band set's own codes, plus NPL."""
    set_code = settings.band_set_code
    rows = [{"code": code,
             "label_th": band_sets.label_for(set_code, code) or code,
             "label_en": band_sets.label_for(set_code, code, "en") or code}
            for _lo, _hi, code in band_sets.BAND_SETS.get(set_code, ())]
    rows.append({"code": "NPL",
                 "label_th": band_sets.STATUS_LABEL_TH.get("NPL_CONFIRMED", "NPL"),
                 "label_en": band_sets.STATUS_LABEL_EN.get("NPL_CONFIRMED", "NPL")})
    return rows


def _in_bucket(item, bucket):
    # An NPL case sits in the NPL bucket only — also when its contract is still banded
    # (the sheet's "NPL - …" category, or a manager's manual NPL), never in two.
    npl = (item.get("case") or {}).get("payment_status") == "NPL"
    return npl if bucket == "NPL" else (not npl and item.get("aging_bucket") == bucket)


@router.post("/v1/customers:assign")
def assign_customers(body: dict = Body(...), x_volt_role: str = Header(default="OFFICER")):
    """Q5 (TASK-107): one request assigns a set of customers to one officer,
    all-or-nothing. Every uid is validated before the first write; one audit entry
    names every uid (audit.describe is one row per request by design)."""
    if _role(x_volt_role) not in ("SUPERVISOR", "MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Supervisor or above", detail="Assignment is a Supervisor's act",
                             message_th="เฉพาะหัวหน้างานขึ้นไปมอบหมายงานได้", error_id="DEBT-IAM-0403")
    uids = body.get("customer_uids")
    if (not isinstance(uids, list) or not uids or len(uids) > 200
            or any(not isinstance(u, str) or not u.strip() for u in uids)
            or len(set(uids)) != len(uids)):
        raise errors.validation_failed([{
            "pointer": "/customer_uids", "code": "invalid",
            "message": "customer_uids must be 1-200 distinct, non-blank strings.",
            "message_th": "ต้องเลือกอย่างน้อย 1 รายการ และไม่เกิน 200 รายการ ไม่ซ้ำกัน"}])
    officer_uid = body.get("officer_uid")
    from .. import officers
    known = {row["uid"] for row in officers.registry()}
    if officer_uid not in known:
        raise errors.officer_unknown(officer_uid or "")
    missing = [u for u in uids if journey.customer_by_uid(u) is None]
    if missing:
        raise errors.customer_unknown(missing)
    audit.describe(act="CUSTOMERS_ASSIGNED", subject=("officer", officer_uid),
                   detail={"customer_uids": list(uids), "count": len(uids), "reason": body.get("reason")})
    _assign_many(uids, officer_uid)
    return {"officer_uid": officer_uid, "assigned": list(uids), "count": len(uids)}


@router.get("/v1/customers:assign-split/buckets")
def assign_split_buckets(x_volt_role: str = Header(default="OFFICER")):
    """R-C (TASK-116): the buckets a manager may split, with served counts from the
    same rows GET /v1/today serves."""
    require_manager(x_volt_role, "The portfolio split is a manager's act",
                    "เฉพาะผู้จัดการขึ้นไปแบ่งพอร์ตได้")
    items = _assignable()
    out = []
    for bucket in _bucket_codes():
        mine = [i for i in items if _in_bucket(i, bucket["code"])]
        out.append({**bucket, "count": len(mine),
                    "unassigned": sum(1 for i in mine if not (i.get("case") or {}).get("officer_uid"))})
    return out


def deal_bucket(uids, officer_uids, seed):
    """The pure deal (R-C): shuffle a copy with the run's seed, then hand the uids
    out round-robin, so the per-officer counts differ by at most one. Returns
    (shuffled_uids, {officer_uid: [uids]})."""
    import random
    shuffled = list(uids)
    random.Random(seed).shuffle(shuffled)
    per = {o: [] for o in officer_uids}
    for n, uid in enumerate(shuffled):
        per[officer_uids[n % len(officer_uids)]].append(uid)
    return shuffled, per


@router.post("/v1/customers:assign-split")
def assign_split(body: dict = Body(...), x_volt_role: str = Header(default="OFFICER")):
    """F10c / R-C (TASK-116): split one bucket's unassigned accounts equally at
    random among the named officers. A dry run serves the same preview and writes
    nothing; a run keeps its seed and per-officer counts in the audit entry.

    2026-09-23 (build round 3): the same deal also takes an explicit selection —
    `customer_uids` from the Today list's own ticks — so a manager can assign the
    rows in front of them equally at random instead of a whole bucket."""
    require_manager(x_volt_role, "The portfolio split is a manager's act",
                    "เฉพาะผู้จัดการขึ้นไปแบ่งพอร์ตได้")
    from .. import officers
    known = {row["uid"] for row in officers.registry()}
    officer_uids = body.get("officer_uids")
    if not isinstance(officer_uids, list) or not officer_uids:
        raise errors.validation_failed([{
            "pointer": "/officer_uids", "code": "required",
            "message": "Name at least one officer to deal the bucket to.",
            "message_th": "เลือกพนักงานอย่างน้อย 1 คนที่จะรับผิดชอบกลุ่มนี้"}])
    if len(set(officer_uids)) != len(officer_uids):
        raise errors.validation_failed([{
            "pointer": "/officer_uids", "code": "duplicate",
            "message": "The same officer is named twice.",
            "message_th": "มีชื่อพนักงานซ้ำในรายการ"}])
    bad = [o for o in officer_uids if o not in known]
    if bad:
        raise errors.officer_unknown(bad)

    selection = body.get("customer_uids")
    if selection is not None:
        if (not isinstance(selection, list) or not selection or len(selection) > 200
                or any(not isinstance(u, str) or not u.strip() for u in selection)
                or len(set(selection)) != len(selection)):
            raise errors.validation_failed([{
                "pointer": "/customer_uids", "code": "invalid",
                "message": "customer_uids must be 1-200 distinct, non-blank strings.",
                "message_th": "ต้องเลือกอย่างน้อย 1 รายการ และไม่เกิน 200 รายการ ไม่ซ้ำกัน"}])
        missing = [u for u in selection if journey.customer_by_uid(u) is None]
        if missing:
            raise errors.customer_unknown(missing)
        uids = list(selection)
        subject = ("selection", "%d rows" % len(uids))
    else:
        codes = {b["code"] for b in _bucket_codes()}
        bucket = (body.get("bucket") or "").strip()
        if bucket not in codes:
            raise errors.validation_failed([{
                "pointer": "/bucket", "code": "unknown",
                "message": "%r is not a bucket of the active band set." % bucket,
                "message_th": "ไม่รู้จักกลุ่มลูกหนี้ที่ระบุ กรุณาเลือกจากรายการที่กำหนด"}])
        # The roles above are checked before the bucket, so an unknown officer is an
        # officer problem even when the bucket is wrong too.
        include_assigned = bool(body.get("include_assigned"))
        items = [i for i in _assignable() if _in_bucket(i, bucket)]
        if not include_assigned:
            items = [i for i in items if not (i.get("case") or {}).get("officer_uid")]
        uids = [i["customer"]["uid"] for i in items]
        subject = ("bucket", bucket)

    dry_run = bool(body.get("dry_run"))
    import uuid
    # R-C: every run keeps its seed. The seed is served so a run can be reproduced
    # and audited; the deal is round-robin, so the counts differ by at most one.
    seed = "%s-%s" % (settings.business_date, uuid.uuid4().hex[:8])
    shuffled, per = deal_bucket(uids, officer_uids, seed)
    per_officer = [{"officer_uid": o, "count": len(per[o])} for o in officer_uids]
    result = {"seed": seed, "total": len(uids), "per_officer": per_officer, "dry_run": dry_run}
    if dry_run:
        return result
    audit.describe(act="CUSTOMERS_SPLIT", subject=subject,
                   detail={"seed": seed, "officer_uids": list(officer_uids), "per_officer": per_officer,
                           "include_assigned": bool(body.get("include_assigned")), "count": len(uids)})
    for officer_uid, mine in per.items():
        if mine:
            _assign_many(mine, officer_uid)
    return {**result, "assigned": shuffled}

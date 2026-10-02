"""D05 / Q6 (feedback-r2 TASK-221): a receipt that landed before an open promise's date.

Run in every session's import heal (import_sync.heal_session, fix-all F2) and once at
API start. For every OPEN promise it looks at the customer's served invoices —
the book's own block, the same one the case page and payment_summary read — and when a
receipt is dated on or before the promise date it stamps `paid_before_due` once, writes
a case event, and drops a calendar notice on the case owner so the officer closes the
promise ("นัดชำระ -> ชำระแล้ว"). Idempotent: the stamp is the guard, so a second apply
never re-notices; and the notice uid is derived from owner, customer and receipt, so
the other sessions healing on the same import never notify the officer twice.
"""
from . import notices

TITLE_TH = "เงินเข้าก่อนนัด · %s"
TEXT_TH = "ใบเสร็จ %s · %s บาท · นัดวันที่ %s — ยืนยันปิดนัดชำระ"
TITLE_EN = "Payment before the promise · %s"
TEXT_EN = "Receipt %s · %s baht · promised for %s — confirm closing the promise"


def _created_on(cs, ptp):
    """The day the promise was recorded, from its own contact row — None for a
    seeded promise whose history predates the app."""
    for row in cs.contact_log:
        if row.get("ptp_uid") == ptp["uid"]:
            return str(row.get("occurred_at") or "")[:10] or None
    return None


def _paid_before(invoices, promise_date, created_on):
    """The first receipt paid on or before the promise date (and not before the
    promise was made), or None."""
    for inv in invoices or ():
        # fix-all P2: an invoice serves every payment it carries, in date order
        for payment in inv.get("payments") or [inv.get("payment") or {}]:
            on = str(payment.get("on") or "")[:10]
            if not on or not payment.get("amount"):
                continue
            if on <= str(promise_date) and (created_on is None or on >= created_on):
                return {"receipt_no": payment.get("receipt_no") or inv.get("doc_no"),
                        "on": on, "amount": str(payment.get("amount"))}
    return None


def notice_early_payments(state, cs, business_date, by="SYSTEM"):
    """Returns the promise uids noticed on this pass."""
    from . import audit, journey
    noticed = []
    for ptp in list(cs.ptps.values()):
        if ptp.get("status") != "OPEN" or ptp.get("paid_before_due") is not None:
            continue
        customer = journey.customer_by_uid(ptp["customer_uid"])
        if customer is None:
            continue
        peak = (getattr(customer, "sheet", {}) or {}).get("peak") or {}
        found = _paid_before(peak.get("invoices"), ptp.get("promise_date"), _created_on(cs, ptp))
        if found is None:
            continue
        ptp["paid_before_due"] = found
        cs.events.append({
            "kind": "PTP_PAYMENT_NOTICED", "uid": cs.uid("ev"), "case_uid": ptp["case_uid"],
            "ptp_uid": ptp["uid"], "receipt_no": found["receipt_no"], "paid_on": found["on"],
            "amount": found["amount"], "by": by, "on": str(business_date),
        })
        case = cs.cases.get(ptp["customer_uid"]) or {}
        owner = case.get("officer_uid")
        if owner:
            display = getattr(customer, "display_name", None) or ptp["customer_uid"]
            try:
                fields = notices.clean({
                    "title": TITLE_TH % display,
                    "on": str(business_date),
                    "text": TEXT_TH % (found["receipt_no"], found["amount"], ptp["promise_date"]),
                    "customer_uid": ptp["customer_uid"],
                }, partial=False)
            except notices.NoticeRefused:
                fields = None
            if fields is not None:
                notices.create(owner, fields, notices.uid_for(owner, ptp["customer_uid"], found["receipt_no"]))
        audit.describe(act="PTP_PAYMENT_NOTICED", subject=("ptp", ptp["uid"]),
                       detail={"receipt_no": found["receipt_no"], "on": found["on"],
                               "amount": found["amount"]})
        noticed.append(ptp["uid"])
    return noticed

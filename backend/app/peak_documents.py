"""PEAK documents — REQ-ACC-030..034 (Requirements Amendment v2.6), decision C3.

Every document Debt originates for the books is one record here:
  intent (one of the 23 outcomes), entity + company_id, the payload as sent, an
  idempotency key STORED BEFORE the call, and a state:
      PENDING -> DRAFT_CREATED -> APPROVED_IN_PEAK | REJECTED
                     \\-> UNSENT (transport failure; re-sendable)

The client is app/integrations/peak.py and has two verbs. This module has no
approve/post/update/delete either, and a test reflects on both.

A `transport` can be injected (tests, the stub on the Data sources screen) so the
contract is provable without credentials; the real client is the default.
"""
import hashlib
from datetime import datetime

from . import clock
from .config import settings
from .entities import entity_fields
from .integrations import peak as peak_client
from .session import Store

INTENTS = (
    "INVOICE_CREATE", "INVOICE_AMEND_DUE_DATE", "INVOICE_CANCEL_REISSUE", "RECEIPT_FULL",
    "RECEIPT_PARTIAL", "RECEIPT_MULTI_CONTRACT", "RECEIPT_UNAPPLIED", "RECEIPT_NET_OF_WHT",
    "WHT_WRITE_OFF", "RESTRUCTURE_VOID_SERIES", "RESTRUCTURE_MODIFICATION_LOSS",
    "SETTLEMENT_RECEIPT", "BUYBACK_DEED_AND_PAYMENT", "UNINSTALL_FEE_INVOICE", "SERVICE_INVOICE",
    "CANCELLATION_CREDIT_OR_REFUND", "CLOSE_LOST_FULL_REFUND", "WRITE_OFF_DERECOGNITION",
    "PENALTY_INVOICE", "PROJECT_SALE_INVOICE", "SERVICE_BULK_INVOICE", "ACCOUNTING_FEE_50000",
    "CREDIT_NOTE_STANDALONE",
)
# Which instance receives the draft. "BOTH" raises one document per instance.
INSTANCE_RULE = {
    "INVOICE_CREATE": "BY_ENTITY", "INVOICE_AMEND_DUE_DATE": "BY_ENTITY", "INVOICE_CANCEL_REISSUE": "BY_ENTITY",
    "RECEIPT_FULL": "BY_ENTITY", "RECEIPT_PARTIAL": "BY_ENTITY", "RECEIPT_MULTI_CONTRACT": "BY_ENTITY",
    "RECEIPT_UNAPPLIED": "NONE", "RECEIPT_NET_OF_WHT": "EPC", "WHT_WRITE_OFF": "EPC",
    "RESTRUCTURE_VOID_SERIES": "SPV", "RESTRUCTURE_MODIFICATION_LOSS": "SPV", "SETTLEMENT_RECEIPT": "BY_ENTITY",
    "BUYBACK_DEED_AND_PAYMENT": "BOTH", "UNINSTALL_FEE_INVOICE": "EPC", "SERVICE_INVOICE": "EPC",
    "CANCELLATION_CREDIT_OR_REFUND": "BY_ENTITY", "CLOSE_LOST_FULL_REFUND": "BY_ENTITY",
    "WRITE_OFF_DERECOGNITION": "EPC", "PENALTY_INVOICE": "BY_ENTITY", "PROJECT_SALE_INVOICE": "EPC",
    "SERVICE_BULK_INVOICE": "NONE", "ACCOUNTING_FEE_50000": "NONE", "CREDIT_NOTE_STANDALONE": "BY_ENTITY",
}
STATES = ("PENDING", "DRAFT_CREATED", "APPROVED_IN_PEAK", "REJECTED", "UNSENT")
NEVER_POSTS = ("RECEIPT_UNAPPLIED", "SERVICE_BULK_INVOICE", "ACCOUNTING_FEE_50000")

# Process-wide transport seam (tests and the no-credential demo). Per-session state
# cannot hold it: a test's shared session and the request's cookie session differ.
TRANSPORT_OVERRIDE = None


def transport_for(state):
    return state.transport or TRANSPORT_OVERRIDE or peak_client


class PeakDocumentError(Exception):
    def __init__(self, code, detail, **extra):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.extra = extra


class DocumentState:
    def __init__(self):
        self.documents = {}      # uid -> record
        self.by_key = {}         # idempotency_key -> uid
        self.transport = None    # injected stub; None means the real client
        self._counter = 0

    def uid(self):
        self._counter += 1
        return "pkd-%05d" % self._counter


_store = Store(DocumentState, key="peak_documents.state")


def for_current() -> DocumentState:
    return _store.for_current()


def reconcile(state, jstate):
    """Flag documents whose source invoice/receipt is no longer in this session.

    A reseed mints PEAK invoices on stable uids, so a document normally keeps its
    source; when a report's content changed enough that the source is gone, the
    document must say so rather than render beside a vanished reference (sync
    audit, 2026-09-20). Resolution only — never calls PEAK, never changes state."""
    flagged = cleared = 0
    for doc in state.documents.values():
        ref = doc.get("source_ref")
        if not ref:
            continue
        alive = ref in jstate.invoices or ref in jstate.receipts
        was = bool(doc.get("source_missing"))
        doc["source_missing"] = not alive
        if not alive and not was:
            flagged += 1
        elif alive and was:
            cleared += 1
    return {"flagged": flagged, "cleared": cleared}


def reset():
    global TRANSPORT_OVERRIDE
    _store.reset()
    TRANSPORT_OVERRIDE = None


def idempotency_key(intent, source_ref, entity, amount=None, seq=1):
    raw = "|".join(str(x) for x in (intent, source_ref, entity, amount, seq))
    return "debt-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _penalty_divergence_note_th():
    """A5 §2b: PEAK's own import format carries a หมายเหตุ column (column R) capped at
    500 characters; that is the limit applied here regardless of which transport a
    draft travels by. Ruling 87 decided OUR rate; PEAK's own rate setting is a separate
    switch inside PEAK that only an AR officer can change, and nothing in this codebase
    changes it for her — this note exists so Aynaz, who approves these drafts, is told
    the two disagree on the document itself, rather than left to discover it against
    the customer's own tax invoice.

    Reached only once something calls raise_document with PENALTY_INVOICE. As of
    ruling 104, nothing in production does — POST /v1/contracts/{uid}/penalty-invoices
    (main.py) is a flag-gated stub that creates no PEAK document; only tests call this
    path today. This note activates the moment that endpoint is wired to raise_document,
    which is a separate, not-yet-authorised change. Nothing here claims otherwise.
    """
    rate_pct_day = str((settings.late_payment_daily_rate * 100).normalize())
    note = (
        "ค่าปรับในร่างนี้คำนวณที่อัตราที่ตัดสินแล้ว %s%%/วัน แต่ PEAK ยังตั้งค่า"
        "อัตราค่าปรับไว้ที่ 0.3%%/วัน และยังไม่ได้แก้ไขให้ตรงกัน ยอดในร่างนี้จึงต่ำกว่าใบแจ้งหนี้เดิม"
        "ที่ลูกค้าได้รับจาก PEAK กรุณาตรวจสอบและปรับอัตราใน PEAK ก่อนอนุมัติเอกสารนี้"
    ) % rate_pct_day
    return note[:500]


def raise_document(state, intent, source_ref, entity, payload, by, customer_name=None, seq=1):
    """Record the intent, store the key, THEN call PEAK. Returns the record(s).

    settings.peak_write_mode is LOCKED to DRAFT_ONLY; anything else refuses here so
    a mis-set config can never make this layer post."""
    if settings.peak_write_mode != "DRAFT_ONLY":
        raise PeakDocumentError("peak_draft_only", "peak_write_mode is LOCKED to DRAFT_ONLY")
    if intent not in INTENTS:
        raise PeakDocumentError("intent_unknown", "Unknown intent %s" % intent)
    if intent == "PENALTY_INVOICE" and not settings.penalty_invoicing_enabled:
        raise PeakDocumentError("feature_disabled",
                                "Penalty invoicing is disabled by configuration (penalty_invoicing_enabled)")
    if intent == "PENALTY_INVOICE":
        # Ruling 104: named consistently as "note_th" through this record's payload,
        # _send's outbound document, and the PEAK API body — see _penalty_divergence_note_th.
        payload = dict(payload)
        payload["note_th"] = _penalty_divergence_note_th()
    rule = INSTANCE_RULE[intent]
    if rule == "NONE":
        raise PeakDocumentError("manual_outside_erp" if intent != "RECEIPT_UNAPPLIED" else "receipt_unapplied",
                                "%s never reaches PEAK" % intent)
    instances = ["EPC", "SPV"] if rule == "BOTH" else ([rule] if rule in ("EPC", "SPV") else [entity])
    if any(i not in ("EPC", "SPV") for i in instances):
        raise PeakDocumentError("entity_unresolved", "No instance for entity %r — creation refused, not guessed (S03)" % entity)
    records = []
    for n, instance in enumerate(instances, start=1):
        key = idempotency_key(intent, source_ref, instance, payload.get("amount"), seq * 10 + n)
        if key in state.by_key:
            existing = state.documents[state.by_key[key]]
            if existing["state"] == "UNSENT":
                _send(state, existing, customer_name)   # it never reached PEAK: a retry, not a second create
            records.append(existing)                     # replay — never a second create
            continue
        record = {
            "uid": state.uid(), "intent": intent, "source_ref": source_ref,
            **entity_fields(instance), "instance": instance,
            "payload": dict(payload), "idempotency_key": key, "state": "PENDING",
            "peak_ref": None, "peak_number": None, "qr_payload": None, "rejection_reason": None,
            "created_by": by, "created_at": clock.stamp(),      # J3-19: one clock
            "state_read_at": None, "attempts": 0, "last_error": None, "customer_name": customer_name,
            "state_note_th": None,
        }
        state.documents[record["uid"]] = record
        state.by_key[key] = record["uid"]          # stored BEFORE the call (REQ-ACC-030)
        _send(state, record, customer_name)
        records.append(record)
    return records


def _outbound(record, customer_name=None):
    """The document as the transport receives it. One builder, so a resubmit
    (PAY-12) sends byte-for-byte what a first send would."""
    return {
        "intent": record["intent"], "idempotency_key": record["idempotency_key"],
        "reference": "%s:%s" % (record["source_ref"], record["uid"]),
        "customer_name": customer_name, "amount": record["payload"].get("amount"),
        "due_date": record["payload"].get("due_date"), "lines": record["payload"].get("lines"),
        "vat": record["payload"].get("vat", True), "wht_rate": record["payload"].get("wht_rate"),
        "note_th": record["payload"].get("note_th"),   # ruling 104 — None for every intent but PENALTY_INVOICE
    }


def _send(state, record, customer_name=None):
    record["attempts"] += 1
    document = _outbound(record, customer_name)
    transport = transport_for(state)
    try:
        result = transport.create_draft(document, instance=record["instance"])
    except peak_client.NotConfigured as exc:
        record["state"], record["last_error"] = "UNSENT", "not configured: %s" % ", ".join(exc.missing)
        return annotate(record)
    except peak_client.PeakError as exc:
        record["state"], record["last_error"] = "UNSENT", str(exc)
        return annotate(record)
    except ValueError:
        # Fix-all P10d (M9): a 2xx whose body is not JSON (a proxy page) raised out of
        # here and left the draft PENDING for ever — replay, refresh and resend all
        # refused. It is a send that did not land, like any other: UNSENT, resendable.
        record["state"], record["last_error"] = "UNSENT", "PEAK answered without a readable body"
        return annotate(record)
    record["state"] = "DRAFT_CREATED"
    record["peak_ref"] = result.get("peak_ref")
    record["peak_number"] = result.get("peak_number")
    record["last_error"] = None
    return annotate(record)


UNSENT_NOTE_TH = "ยังไม่ส่ง: ไม่มีการเชื่อมต่อ PEAK (ตั้งค่า PEAK_UAT_* หรือเปิดตัวจำลอง)"
UNSENT_NOTE_EN = "Not sent: no PEAK connection (configure the PEAK test credentials or turn on the simulator)"
STATE_NOTE_EN = {
    "PENDING": "Sending to PEAK",
    "DRAFT_CREATED": "Drafted in PEAK, waiting for AR approval in PEAK",
    "APPROVED_IN_PEAK": "Approved in PEAK",
    "REJECTED": "PEAK rejected the document",
}
STATE_NOTE_TH = {
    "PENDING": "กำลังส่งไป PEAK",
    "DRAFT_CREATED": "ร่างใน PEAK แล้ว รอ AR อนุมัติใน PEAK",
    "APPROVED_IN_PEAK": "อนุมัติใน PEAK แล้ว",
    "REJECTED": "PEAK ปฏิเสธเอกสาร",
}
# Delta-100 PAY-6: the prototype's payNeed sentence — what this document needs
# NEXT, distinct from state_note_* (which says what its state MEANS). One entry
# per state, served as state_need_th/en on every document.
STATE_NEED_EN = {
    "PENDING": "Sending — waiting for PEAK",
    "UNSENT": "Not in PEAK yet — check the connection and send again",
    "DRAFT_CREATED": "Waiting for AR approval in PEAK",
    "APPROVED_IN_PEAK": "Waiting for the allocation order",
    "REJECTED": "Fix the document and resubmit",
}
STATE_NEED_TH = {
    "PENDING": "กำลังส่งไป PEAK",
    "UNSENT": "ยังไม่ถึง PEAK — ตรวจการเชื่อมต่อแล้วส่งใหม่",
    "DRAFT_CREATED": "รอ AR อนุมัติใน PEAK",
    "APPROVED_IN_PEAK": "รอลำดับการจัดสรร",
    "REJECTED": "แก้เอกสารแล้วส่งใหม่",
}


def annotate(record):
    """Round-2 thip T2-02: the record says in Thai what its state means. UNSENT is the
    normal state without credentials or the stub — never an error. Delta-100 PAY-6:
    it also says what the document needs next (state_need_*), the prototype's payNeed."""
    record["state_need_th"] = STATE_NEED_TH.get(record["state"])
    record["state_need_en"] = STATE_NEED_EN.get(record["state"])
    if record["state"] == "UNSENT":
        record["state_note_th"], record["state_note_en"] = UNSENT_NOTE_TH, UNSENT_NOTE_EN
    elif record["state"] == "REJECTED":
        record["state_note_th"] = "%s: %s" % (STATE_NOTE_TH["REJECTED"], record.get("rejection_reason") or "-")
        record["state_note_en"] = "%s: %s" % (STATE_NOTE_EN["REJECTED"], record.get("rejection_reason") or "-")
    else:
        record["state_note_th"] = STATE_NOTE_TH.get(record["state"])
        record["state_note_en"] = STATE_NOTE_EN.get(record["state"])
    return record


def resend(state, uid, customer_name=None):
    record = state.documents.get(uid)
    if record is None:
        raise PeakDocumentError("not_found", "No document %s" % uid)
    if record["state"] != "UNSENT":
        raise PeakDocumentError("document_state_conflict", "Only an UNSENT document is re-sent; %s is %s" % (uid, record["state"]))
    return _send(state, record, customer_name or record.get("customer_name"))


def resubmit(state, uid, by=None):
    """PAY-12: fix-and-resubmit a REFUSED document, and only a refused one.

    The act is a CLAIM that the fix has been made and a draft now stands in PEAK,
    so it must not be made without a transport answering. Unlike `resend` (which
    answers 200 with UNSENT when PEAK is absent — a resend of an already-recorded
    attempt), a resubmit that cannot reach PEAK raises with the transport's own
    reason and leaves the record REJECTED: the router turns that into a refusal,
    never a silent "fixed" that no PEAK ever saw. The idempotency key is unchanged
    (the same intent, corrected in PEAK by AR), so a real PEAK treats this as the
    same document, not a second create.
    """
    record = state.documents.get(uid)
    if record is None:
        raise PeakDocumentError("not_found", "No document %s" % uid)
    if record["state"] != "REJECTED":
        raise PeakDocumentError("document_state_conflict",
                                "Only a REJECTED document is fixed and resubmitted; %s is %s" % (uid, record["state"]))
    record["attempts"] += 1
    transport = transport_for(state)
    document = _outbound(record, record.get("customer_name"))
    try:
        result = transport.create_draft(document, instance=record["instance"])
    except peak_client.NotConfigured as exc:
        record["last_error"] = "not configured: %s" % ", ".join(exc.missing)
        raise PeakDocumentError("resubmit_transport_unavailable", record["last_error"])
    except peak_client.PeakError as exc:
        record["last_error"] = str(exc)
        raise PeakDocumentError("resubmit_transport_failed", str(exc))
    record["state"] = "DRAFT_CREATED"
    record["peak_ref"] = result.get("peak_ref") or record.get("peak_ref")
    record["peak_number"] = result.get("peak_number") or record.get("peak_number")
    record["rejection_reason"] = None
    record["last_error"] = None
    record["state_read_at"] = None
    record["resubmitted_by"] = by
    record["resubmitted_at"] = clock.stamp()
    return annotate(record)


def refresh(state, uid):
    """Read the state back. APPROVED carries the number and the QR; REJECTED the reason.
    Round-2 thip T2-02: an UNSENT document is re-sent once and, if PEAK is still not
    there, answered 200 with state UNSENT and its note — a 409 was the wrong answer to
    the normal no-credential case."""
    record = state.documents.get(uid)
    if record is None:
        raise PeakDocumentError("not_found", "No document %s" % uid)
    if record["state"] == "UNSENT":
        _send(state, record, record.get("customer_name"))
        if record["state"] == "UNSENT":
            return annotate(record)
    if record["state"] == "PENDING" or not record["peak_ref"]:
        return annotate(record)
    transport = transport_for(state)
    try:
        answer = transport.read_state(record["peak_ref"], instance=record["instance"])
    except peak_client.PeakError as exc:
        record["last_error"] = str(exc)
        return annotate(record)
    record["state_read_at"] = clock.stamp()       # J3-19: one clock
    if answer["state"] in ("APPROVED_IN_PEAK", "REJECTED"):
        record["state"] = answer["state"]
    record["peak_number"] = answer.get("peak_number") or record["peak_number"]
    if answer["state"] == "APPROVED_IN_PEAK":
        record["qr_payload"] = answer.get("qr_payload")
    if answer["state"] == "REJECTED":
        record["rejection_reason"] = answer.get("reason") or "rejected in PEAK"
    return annotate(record)


def list_documents(state, doc_state=None, source_ref=None):
    rows = [annotate(r) for r in state.documents.values()]
    if doc_state:
        rows = [r for r in rows if r["state"] == doc_state]
    if source_ref:
        rows = [r for r in rows if r["source_ref"] == source_ref]
    return rows


class StubTransport:
    """A PEAK that answers without a network. Tests and the no-credential demo use
    it. It models both INT-05 outcomes: read-back supported (default) or UNKNOWN."""

    def __init__(self, fail_create=False, approve_on_read=True, reject_reason=None, read_unknown=False):
        self.fail_create = fail_create
        self.approve_on_read = approve_on_read
        self.reject_reason = reject_reason
        self.read_unknown = read_unknown
        self.creates = []
        self.reads = []

    def create_draft(self, document, instance="EPC"):
        self.creates.append((document["idempotency_key"], instance, document))   # widened to witness the outbound document (ruling 104)
        if self.fail_create:
            raise peak_client.PeakError("stub: transport failure")
        n = len(self.creates)
        return {"peak_ref": "peak-%s-%04d" % (instance.lower(), n), "peak_number": None}

    def read_state(self, peak_ref, instance="EPC"):
        self.reads.append(peak_ref)
        if self.read_unknown:
            return {"state": "UNKNOWN", "peak_number": None, "qr_payload": None, "reason": None}
        if self.reject_reason:
            return {"state": "REJECTED", "peak_number": None, "qr_payload": None, "reason": self.reject_reason}
        if self.approve_on_read:
            return {"state": "APPROVED_IN_PEAK", "peak_number": "IV-2026090%04d" % len(self.reads),
                    "qr_payload": "QR:%s" % peak_ref, "reason": None}
        return {"state": "DRAFT_CREATED", "peak_number": None, "qr_payload": None, "reason": None}

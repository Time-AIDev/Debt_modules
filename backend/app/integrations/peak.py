"""PEAK integration — DRAFT ONLY (decision C3, PEAK Integration v1.2).

Two verbs, no third: create a draft, read a document's state. Debt never approves,
posts, updates or deletes a PEAK document; a person does that inside PEAK. The test
suite reflects on this module and fails if a public function whose name suggests
any of those verbs appears (PKD-001).

Honesty rules kept from v1.1:
  - The local record is the record; PEAK's answer decorates it. A transport or
    mapping failure leaves the document UNSENT — re-sendable, never lost.
  - Credentials live in backend/.env; names appear here, values nowhere.
  - The UAT surface is probed at runtime (PEAK_UAT_BASE_URL overridable). Whether
    the API exposes draft state for read-back is INT-05; until confirmed, read_state
    returns "UNKNOWN" rather than guessing, and the screen says "check PEAK".
"""
import httpx

from . import env

REQUIRED_ENV = ("PEAK_UAT_CONNECT_ID", "PEAK_UAT_PASSWORD", "PEAK_UAT_USER_TOKEN")
OPTIONAL_SPV_ENV = ("PEAK_UAT_CONNECT_ID_SPV", "PEAK_UAT_PASSWORD_SPV", "PEAK_UAT_USER_TOKEN_SPV")

DEFAULT_BASE = "https://openapi.peakaccount.com"
TIMEOUT = 10.0
MODE = "DRAFT_ONLY"

# Which PEAK document family each intent lands in. The instance is decided by the
# caller from company_id (REQ-ENT-001) and passed in; this table never chooses one.
DOCUMENT_FAMILY = {
    "INVOICE_CREATE": "invoice", "INVOICE_AMEND_DUE_DATE": "invoice-amendment",
    "INVOICE_CANCEL_REISSUE": "credit-note+invoice", "RECEIPT_FULL": "receipt",
    "RECEIPT_PARTIAL": "receipt", "RECEIPT_MULTI_CONTRACT": "receipt",
    "RECEIPT_UNAPPLIED": None, "RECEIPT_NET_OF_WHT": "receipt+wht-receivable",
    "WHT_WRITE_OFF": "journal", "RESTRUCTURE_VOID_SERIES": "credit-note",
    "RESTRUCTURE_MODIFICATION_LOSS": "journal", "SETTLEMENT_RECEIPT": "receipt",
    "BUYBACK_DEED_AND_PAYMENT": "journal", "UNINSTALL_FEE_INVOICE": "invoice",
    "SERVICE_INVOICE": "invoice", "CANCELLATION_CREDIT_OR_REFUND": "credit-note",
    "CLOSE_LOST_FULL_REFUND": "credit-note", "WRITE_OFF_DERECOGNITION": "journal",
    "PENALTY_INVOICE": "invoice", "PROJECT_SALE_INVOICE": "invoice",
    "SERVICE_BULK_INVOICE": None, "ACCOUNTING_FEE_50000": None,
    "CREDIT_NOTE_STANDALONE": "credit-note",
}


class PeakError(Exception):
    pass


class NotConfigured(PeakError):
    def __init__(self, instance="EPC"):
        super().__init__("PEAK UAT credentials are not configured for %s" % instance)
        self.missing = [k for k in REQUIRED_ENV if not env(k)]


def _config(instance="EPC"):
    if env("ENV") == "prd":
        from ..errors import Problem
        raise Problem("feature_disabled", 503, "PEAK outbound is disabled",
                      "Production uses PEAK file imports only.", "ใช้การนำเข้าไฟล์ PEAK ในรอบนี้", "DEBT-PEAK-OFF")
    missing = [k for k in REQUIRED_ENV if not env(k)]
    if missing:
        raise NotConfigured(instance)
    suffix = "_SPV" if instance == "SPV" and env("PEAK_UAT_CONNECT_ID_SPV") else ""
    return {
        "base": env("PEAK_UAT_BASE_URL", DEFAULT_BASE).rstrip("/"),
        "connect_id": env("PEAK_UAT_CONNECT_ID" + suffix),
        "password": env("PEAK_UAT_PASSWORD" + suffix),
        "user_token": env("PEAK_UAT_USER_TOKEN" + suffix),
        "instance": instance,
    }


def _headers(config):
    return {
        "Content-Type": "application/json",
        "Client-Id": config["connect_id"],
        "User-Token": config["user_token"],
    }


def probe():
    """A cheap reachability check for /readyz and the data-sources panel."""
    config = _config()
    try:
        response = httpx.get(config["base"], timeout=5.0)
        return {"reachable": True, "http_status": response.status_code}
    except httpx.HTTPError as exc:
        raise PeakError("PEAK UAT is not reachable: %s" % exc.__class__.__name__)


def create_draft(document, instance="EPC"):
    if env("ENV") == "prd":
        from ..errors import Problem
        raise Problem("feature_disabled", 503, "PEAK outbound is disabled",
                      "Production uses PEAK file imports only.", "ใช้การนำเข้าไฟล์ PEAK ในรอบนี้", "DEBT-PEAK-OFF")
    """POST one document into PEAK as a DRAFT. Returns {peak_ref, peak_number}.

    `document` is the peak_document payload (intent, idempotency_key, amount,
    due_date, customer_name, reference, lines). The idempotency key is sent as a
    header so a retry that reaches PEAK twice still creates once. Raises PeakError
    on any refusal or transport failure — the caller marks the record UNSENT.
    """
    config = _config(instance)
    family = DOCUMENT_FAMILY.get(document["intent"])
    if family is None:
        raise PeakError("intent %s never reaches PEAK" % document["intent"])
    payload = {
        "document": {
            "family": family,
            "status": "draft",                         # C3 — never "approved"
            "reference": document["reference"],
            "customerName": document.get("customer_name"),
            "amount": document.get("amount"),
            "dueDate": document.get("due_date"),
            "lines": document.get("lines") or [],
            "vat": document.get("vat", True),
            "wht_rate": document.get("wht_rate"),
            "paymentChannel": "QR",
            # Ruling 104: PEAK's own field name for a free-text note on this JSON API is
            # unconfirmed (A5 documents หมายเหตุ, 500 chars, only for the separate Excel
            # import path) — sent under our own key rather than guess a vendor spelling.
            "note_th": document.get("note_th"),
        }
    }
    headers = dict(_headers(config), **{"Idempotency-Key": document["idempotency_key"]})
    try:
        response = httpx.post(config["base"] + "/api/v1/documents",
                              json=payload, headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        raise PeakError("transport failure: %s" % exc.__class__.__name__)
    if response.status_code >= 400:
        raise PeakError("PEAK answered %d: %s" % (response.status_code, response.text[:300]))
    body = response.json() if response.content else {}
    return {
        "peak_ref": body.get("id") or body.get("documentId") or body.get("reference"),
        "peak_number": body.get("number") or body.get("documentNumber"),
    }


def read_state(peak_ref, instance="EPC"):
    """GET a document's state. Returns {state, peak_number, qr_payload, reason}
    with state in DRAFT_CREATED | APPROVED_IN_PEAK | REJECTED | UNKNOWN."""
    config = _config(instance)
    try:
        response = httpx.get(config["base"] + "/api/v1/documents/%s" % peak_ref,
                             headers=_headers(config), timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        raise PeakError("transport failure: %s" % exc.__class__.__name__)
    if response.status_code >= 400:
        raise PeakError("PEAK answered %d: %s" % (response.status_code, response.text[:300]))
    body = response.json() if response.content else {}
    raw = (body.get("status") or "").lower()
    state = {"draft": "DRAFT_CREATED", "approved": "APPROVED_IN_PEAK", "issued": "APPROVED_IN_PEAK",
             "rejected": "REJECTED", "void": "REJECTED"}.get(raw, "UNKNOWN")
    return {
        "state": state,
        "peak_number": body.get("number") or body.get("documentNumber"),
        "qr_payload": body.get("qrCode") or body.get("qr") or body.get("paymentUrl"),
        "reason": body.get("rejectReason") or body.get("reason"),
    }


def status():
    missing = [k for k in REQUIRED_ENV if not env(k)]
    return {
        "integration": "PEAK UAT",
        "configured": not missing,
        "missing_env": missing,   # names only
        "second_instance_configured": bool(env("PEAK_UAT_CONNECT_ID_SPV")),
        "mode": "DRAFT_ONLY — create-draft + read-state; approval happens inside PEAK",
    }

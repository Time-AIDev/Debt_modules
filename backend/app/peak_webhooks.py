"""PEAK webhooks, Stage A: prove it is PEAK, keep the body, answer fast.

PEAK calls POST /v1/webhooks/peak/{contact,invoice,receipt} (the registration sheet
"PEAK : Webhook Registration (Volt)", Sandbox tab, 2026-09-23). Nothing here acts on an
event yet — Stage B does, once PEAK's real bodies have been seen. Until then the one
job is that no event is lost and no stranger's event is kept.

  - The caller must send x-api-key equal to $PEAK_WEBHOOK_KEY (Secret Manager
    `peak-webhook-key-uat`). Unset key = 503, never "accept everyone".
  - The body is kept as bytes (landing.peak_webhook_event), so a shape we did not
    expect is still stored rather than refused — an empty one too, and one over
    MAX_BYTES is kept cut, flagged `truncated` with its real size (fix-all P7).
  - A body PEAK sends twice is stored once: kind + an HMAC-SHA256 of the RAW body,
    keyed with the webhook key, taken before the mask. Two events that differ only
    in a masked run (an epoch-millisecond timestamp) stay two events, and the stored
    key cannot be tested against a guessed id without the webhook key.
  - 503 when the event cannot be stored for ANY reason, so PEAK retries instead of
    hearing "ok" for an event that was never written. When the database is down the
    PEAK report upload is the backstop for what was missed.

PDPA / ruling F5: a PEAK contact carries the 13-digit citizen id, and invoices and
receipts may echo it. Every run of exactly 13 digits, bare or written x-xxxx-xxxxx-xx-x,
is masked BEFORE storage.
"""
import hashlib
import hmac
import logging
import re

from sqlalchemy import text

from . import db, errors
from .integrations import env

KINDS = ("contact", "invoice", "receipt")
MAX_BYTES = 1_000_000
# ponytail: masks ANY 13-digit run, so a 13-digit non-id number is masked too; name the
# exact PEAK fields instead once Stage B has seen real bodies.
THIRTEEN_DIGITS = re.compile(rb"(?<!\d)(?:\d{13}|\d-\d{4}-\d{5}-\d{2}-\d)(?!\d)")
log = logging.getLogger(__name__)

_MEMORY = {}  # (kind, keyed digest) -> masked body; only when no database is configured


def reset():
    _MEMORY.clear()


def _problem(code, status, title, message_th, retryable=False):
    return errors.Problem(code=code, status=status, title=title, detail=title,
                          message_th=message_th, error_id="DEBT-INT-%d" % status,
                          retryable=retryable)


def check_key(given):
    expected = env("PEAK_WEBHOOK_KEY")
    if not expected:
        raise _problem("webhook_not_configured", 503, "PEAK_WEBHOOK_KEY is not set",
                       "ยังไม่ได้ตั้งค่าคีย์ webhook ของ PEAK", retryable=True)
    if not given or not hmac.compare_digest(given.encode(), expected.encode()):
        raise _problem("webhook_key_invalid", 401, "x-api-key is missing or wrong",
                       "คีย์ x-api-key ไม่ถูกต้อง")


def mask(body):
    return THIRTEEN_DIGITS.sub(b"#" * 13, body)


def record(kind, body, content_type=None):
    """Store one event. Returns True when new, False when this exact body was seen."""
    try:
        digest = hmac.new((env("PEAK_WEBHOOK_KEY") or "").encode(), body, hashlib.sha256).hexdigest()
        stored = mask(body)[:MAX_BYTES]
        if not db.configured():
            # ponytail: in-process only, lost on restart — the no-database path (tests, laptop).
            new = (kind, digest) not in _MEMORY
            _MEMORY.setdefault((kind, digest), stored)
            return new
        with db.connect() as conn, conn.begin():
            row = conn.execute(text(
                "INSERT INTO landing.peak_webhook_event "
                "(kind, body_sha256, body, content_type, truncated, size_bytes) "
                "VALUES (:kind, :digest, :body, :ctype, :truncated, :size) "
                "ON CONFLICT (kind, body_sha256) DO NOTHING RETURNING id"),
                {"kind": kind, "digest": digest, "body": stored, "ctype": content_type,
                 "truncated": len(body) > MAX_BYTES, "size": len(body)}).first()
        return row is not None
    except Exception as exc:                  # noqa: BLE001 — database or not: PEAK must retry
        # Never the text: it can quote the body.
        log.error("PEAK webhook event not stored (%s)", exc.__class__.__name__)
        raise _problem("webhook_store_unreachable", 503, "The event could not be stored",
                       "บันทึกข้อมูลจาก PEAK ไม่ได้ในขณะนี้", retryable=True) from None

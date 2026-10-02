"""Opaque, PII-free cursors for the interactive customer workbook."""
import base64
import hashlib
import json

from . import errors


VERSION = 1


def query_hash(query):
    raw = json.dumps(query, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def encode(offset, epoch, query):
    payload = {
        "v": VERSION,
        "offset": int(offset),
        "epoch": int(epoch),
        "query_hash": query_hash(query),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode(token, epoch, query):
    try:
        if not token or not isinstance(token, str):
            raise ValueError("empty")
        padded = token + "=" * (-len(token) % 4)
        payload = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
        if set(payload) != {"v", "offset", "epoch", "query_hash"}:
            raise ValueError("shape")
        if payload["v"] != VERSION or type(payload["offset"]) is not int or payload["offset"] < 0:
            raise ValueError("value")
        if type(payload["epoch"]) is not int or not isinstance(payload["query_hash"], str):
            raise ValueError("type")
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise errors.workbook_cursor_invalid("The cursor is malformed") from None
    if payload["epoch"] != int(epoch):
        raise errors.workbook_cursor_stale(payload["epoch"], int(epoch))
    if payload["query_hash"] != query_hash(query):
        raise errors.workbook_cursor_invalid("The cursor belongs to different filters or sorting")
    return payload["offset"]

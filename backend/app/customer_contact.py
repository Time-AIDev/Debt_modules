"""A phone number a person enters for a customer — Feedback Round 1 / WP9 (design F9 (a)).

The sheet import masked every real number (C5 / REQ-INT-030), so `phone_e164` is null
on 206 of 212 customers and the dial buttons never dial. F9 (a), approved 2026-09-15:
any officer may store a real number, with a reason, audited. Staging is in Singapore;
the PDPA flag stands, so this module is the ONE place a person-entered number lives:

  - records.customer_contact when a database is configured (durable, survives a
    deploy); a process dict labelled not-durable when it is not — the same three-state
    seam db.py and attachments/store.py state. Configured but unreachable is the
    retryable 503 `_phone_unreachable()` — never caught to fall back.
  - never in a log line, never in an audit detail (that says "set" or "cleared"),
    never in a case event, never in a CSV export. A reason that quotes a number has
    the number cut out of the AUDIT copy and out of every SERVED copy; the records
    row (and the in-memory history) keeps the reason as typed.

Reads are served per request: `active_for` loads every active row ONCE per request
(one SELECT, memoised in a ContextVar that dies with the request) because
routers/journey._work_item calls it per row — 212 times on /v1/today.

Reveal (2026-09-20, after the pipeline stopped masking at import): `phone_fields`
serves `phone_revealable` and NEVER the number; `reveal_phone` is the one door that
answers `phone_e164`/`phone_display`, and it writes PHONE_REVEALED (source and kind,
no digits) before it answers. Before this, the full number rode every work item and
case detail response — "hidden" broke in the Network tab. The pipeline now keeps the
sheet's own number (`scripts/import_master_sheet.py`), so both sources reveal.

Fix round 1 (opus review of f8e357d) — each of these is load-bearing too:
  - I1: a SQL failure used to become a bare `RuntimeError` — an unhandled 500
    text/plain, and `db.connect()` sat outside any try, so `DatabaseUnreachable`
    escaped raw too. `_connect()`/`_transaction()` copy user_accounts.py's pattern:
    connection lost (or never reached) is the retryable 503 `_phone_unreachable()`;
    anything else is `errors.internal_error()`. Both `from None` — no chained
    traceback, no `e.orig` logged.
  - I2: `\\d` matches any Unicode digit, so a mixed-Thai-digit string passed the
    shape check and the CHECK constraint failure put the number in Postgres's own
    server log (application code cannot redact that). `_MOBILE`/`_LANDLINE` are
    `re.ASCII` now. Every column reaching SQL is validated first — `by` a non-empty
    str, `kind` from the enum — so a row that carries a number can never fail a
    constraint.
  - I3: `_without_numbers` only joined digits across the four separators it listed
    literally. `_DIGIT_RUN` now joins across any short run (<=3) of punctuation or
    underscore — `/`, `,`, `_`, en/em dash, "space-hyphen-space" all count as one
    run, and Thai digits (๐-๙) count as digits, because stripping too much is the
    safe direction here.
  - M1: the served `phone_override.reason` — list rows and case detail alike, since
    they all build it through `_public` — is redacted the same way and capped at
    200 characters with "…". Only the STORED row keeps the reason exactly as typed.
  - M2: "+66 (0)81 234 5678" / "+660812345678" — a redundant national 0 kept after
    the country code — used to fail the shape check. One leading 0 after +66 is
    dropped before it.

Fix round 2 (opus re-review of c8332ae; I1-I3/M1-M3 verified at runtime by a 400,000
-input fuzz, load-bearing but not repeated here) — one Important, five Minor:
  - R1: a lone surrogate (what JSON.stringify sends for a string cut mid-emoji) or a
    NUL in `phone`/`reason`/`by` used to reach the store unchecked — on Postgres the
    driver's `UnicodeEncodeError` (a `UnicodeError`, never a `SQLAlchemyError`) passed
    straight through as a text/plain 500 with no audit row; with no database the row
    was SAVED and every later read failed rendering it. `_DANGEROUS_RE` refuses all
    three fields with 422 `text_invalid` before anything else runs — the same remedy
    the controller ruled for C2b fix 1 I1 (notices.py's `DANGEROUS_RE`) — and
    `_transaction`/`_load_active` catch `UnicodeError` too, as a backstop.
  - M4: a separator run of 4+ characters ("081 -- 234", "081  -  234") broke the
    9-digit chain instead of joining it. `_DIGIT_RUN`'s separator now counts RUNS,
    not characters — a run of whitespace, or a run of the SAME repeated punctuation
    character, is one unit toward the `{0,3}` bound.
  - M5: a non-`str` reason (e.g. `{"a": 1}`) was silently `str()`'d into the stored
    row. Refused now, `reason_required`, like a blank one.
  - M6: a configured database missing the table (migration never ran) answered the
    opaque `internal_error()`. `_table_missing` (copied from user_accounts.py's own
    B10b check) answers the labelled, retryable `phone_store_not_migrated` instead.
  - M7: `audit.describe` used to run after `active_for`'s "changes nothing" read, so
    an unreachable database on that read left the audit row's `act` at `None` — the
    request-level default for a write in main.py's `audit_trail` middleware. It now
    runs first, right after every field is validated and before the first store read.
  - M8: `by` made only of whitespace and Unicode Cf (format) characters — a
    zero-width space among them — passed `str.strip()`'s emptiness check, since Cf
    is not whitespace. `_has_visible_actor` strips both before deciding.

Fix round 3 (opus re-review of 686da50) — one CRITICAL, six Minor:
  - CRITICAL: the widened `_DIGIT_RUN` (fix round 2 / M4) backtracks
    catastrophically — `(?:\\s+|([\\W_])\\1*){0,3}` lets the engine try every way to
    split a long separator run across the alternation when no digit ever follows,
    and a digit + 800 spaces + a letter took 26.9 s. One saved reason stalled
    `/v1/today`, the workbook and every case detail for every user, durably.
    `_without_numbers` is now a hand-written, single-pass SCANNER — no regex over
    the separator runs at all, so there is nothing left to backtrack. It walks the
    string once; a maximal run of whitespace (or an invisible/format character —
    `unicodedata.category(ch) == "Cf"`, the same class the old pattern folded into
    "not a word char") counts as one token toward the "at most 3 tokens between
    digits" budget, and a maximal run of the SAME repeated punctuation character
    also counts as one token (mirroring what the backreference `\1*` used to do,
    just without the backtracking) — every character is visited O(1) amortised
    times, so the whole function is linear in the input length by construction.
    A 500-character write-side cap (`REASON_MAX`, `reason_too_long`) is a second,
    independent line of defence: even a bug in the scanner could only ever be
    linear in at most 500 characters for anything actually stored.
  - M9: the R1 guard's ORDER (before `audit.describe`, before any store call) had
    no test pinning it — a mutant moving it after `active_for` passed everything.
  - M10: the M6 write-path branch (the missing-table check inside `_transaction`)
    had no test forcing it specifically on a POST.
  - M12: `_load_active`'s comment blamed "Postgres's aborted-transaction state" for
    why the pre-fix `_table_missing` probe failed — the real mechanism is
    SQLAlchemy's own `InvalidRequestError` on a second `begin()` after autobegin,
    which `_table_missing`'s `except SQLAlchemyError` silently swallowed. Corrected.
  - M13: `_has_visible_actor` only excluded whitespace and Cf — U+3164 (a Hangul
    filler, category Lo — a LETTER, not a mark or format character) and U+2800
    (BRAILLE PATTERN BLANK, category So, a SYMBOL) both rendered invisible but
    passed. Now the exact rule `user_accounts._shaped_like_a_name` (B10a / fix
    round 1 M5) uses for a display name — copied, not imported (that helper is
    module-private).

Fix round 4 (opus re-review of e534ffc) — Minor only:
  - M10: the write path's missing-table branch is pinned by a POST whose read is
    stubbed, so its 503 can only come from `_transaction` (test only).
  - Item 2: M13's copy of the display-name rule skipped the two steps
    user_accounts._clean_name runs before it, so a `by` of only tab/LF/VT/FF/
    U+001C-U+001F/NEL answered 200 and stored set_by = ''. `_clean_actor` runs all
    three: collapse whitespace, refuse category C, then the visible-base rule.
  - Item 3: the scanner counts a digit only when `str.isdecimal()` (category Nd) —
    `str.isdigit()` also took superscripts, subscripts and circled digits.
  - Item 5: `phone_actor_invalid` has its own error id, DEBT-COL-0469, in
    routers/today.py's `problem_from` mapping.
"""
import re
import unicodedata
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.exc import DisconnectionError, InterfaceError, OperationalError, SQLAlchemyError

from . import db, errors
from .cases import CaseError

NOT_DURABLE_EN = "No database — this number is held in memory and is lost on restart"
NOT_DURABLE_TH = "ไม่มีฐานข้อมูล — เบอร์นี้อยู่ในหน่วยความจำและหายเมื่อรีสตาร์ท"
KINDS = ("MOBILE", "LANDLINE")
REASON_SERVED_MAX = 200
# Fix round 3 / Critical (2): defence in depth for the scanner below — even a bug
# in it could only ever be linear in at most this many characters for anything
# actually written.
REASON_MAX = 500

_MEMORY = {}          # customer_uid -> the active row (no database configured)
_HISTORY = []         # every set/cleared row, oldest first (no database configured)
_ACTIVE = ContextVar("customer_contact_active", default=None)

_SEPARATORS = re.compile(r"[\s\-.()]")
# Fix round 1 / I2: ASCII only — \d with no flag matches any Unicode decimal digit
# (Thai digits included), which let a mixed-script number pass the shape check and
# then fail the database CHECK constraint, putting the number in Postgres's own
# server log on the way.
_MOBILE = re.compile(r"^0[689]\d{8}$", re.ASCII)
_LANDLINE = re.compile(r"^0[2-57]\d{7}$", re.ASCII)
# Fix round 2 / R1: a NUL, and a lone surrogate (U+D800-U+DFFF — what a string cut
# mid-emoji decodes to from JSON, since json.loads does not require surrogates to
# pair) — not a literal string, so \x00 and \ud800-\udfff are Python escapes decoded
# once here, not regex escapes re-interpreted by the engine. The same remedy the
# controller ruled for C2b fix 1 I1 (notices.py's DANGEROUS_RE).
_DANGEROUS_RE = re.compile("[\x00\ud800-\udfff]")
INVALID_TH = "เบอร์ต้องเป็นมือถือไทย 10 หลัก (ขึ้นต้น 06 08 09) หรือเบอร์บ้าน 9 หลัก (ขึ้นต้น 02–07) จะใส่ +66 นำหน้าก็ได้"
ACTOR_REQUIRED_TH = "ต้องระบุผู้บันทึก"
TEXT_INVALID_TH = "มีอักขระที่บันทึกไม่ได้ในช่องนี้"
REASON_TOO_LONG_TH = "เหตุผลยาวเกิน 500 ตัวอักษร"

_REDACTED_MARKER = "[ตัดเบอร์ออก]"


def reset():
    """Test isolation (tests/conftest.py): the memory store is per process."""
    _MEMORY.clear()
    del _HISTORY[:]
    _ACTIVE.set(None)


# --- _without_numbers: a linear-time, hand-written scanner (fix round 3) -----------------
#
# Fix round 2 / M4's widened pattern, `\+?\d(?:(?:\s+|([\W_])\1*){0,3}\d)+`, backtracks
# catastrophically when a separator run is never followed by a digit — the regex engine
# tries every way to split the run across the `{0,3}` alternation before giving up (a
# digit + 800 spaces + a letter took 26.9 s; C2c's move route calls this same function
# on its reason, so the stall was not this route's alone). No regex runs over a
# separator run any more; the scanner below walks the string exactly once, so there is
# nothing left to backtrack — every character is visited an O(1) amortised number of
# times regardless of input shape, by construction, not by getting lucky on which forms
# happen to get tested.

def _is_ws_like(ch):
    """Whitespace, or an invisible/format character (Unicode category Cf — ZWSP,
    ZWNJ, the word joiner, a BOM) — the same class the old pattern folded into "not
    a word char". NBSP (`\u00a0`) is `str.isspace()`-true already."""
    return ch.isspace() or unicodedata.category(ch) == "Cf"


def _token_end(value, j):
    """One separator TOKEN starting at `value[j]` (neither a letter nor a digit):
    a maximal run of whitespace-or-invisible-format characters, or else a maximal
    run of the SAME repeated character (mirrors what fix round 2's `([\\W_])\\1*`
    backreference did — "081 -- 234" is one token of "--", not two of "-")."""
    n = len(value)
    if _is_ws_like(value[j]):
        k = j + 1
        while k < n and _is_ws_like(value[k]):
            k += 1
        return k
    ch = value[j]
    k = j + 1
    while k < n and value[k] == ch:
        k += 1
    return k


def _run_extent(value, start):
    """`value[start]` is '+' or a digit. Returns `(end, digit_count)` for the
    maximal run beginning there: DIGIT+ (TOKEN{0,3} DIGIT+)*, keeping a leading '+'.
    Every index visited here only ever moves forward — `i`/`j`/`k` are monotonic
    non-decreasing across the whole call — which is what makes the function linear:
    nothing is ever re-scanned from an earlier position."""
    n = len(value)
    i = start
    if value[i] == "+":
        i += 1
    if i >= n or not value[i].isdecimal():
        return start, 0
    digit_count = 0
    while i < n and value[i].isdecimal():
        digit_count += 1
        i += 1
    while True:
        j = i
        tokens = 0
        while tokens < 3 and j < n and not value[j].isalpha() and not value[j].isdecimal():
            j = _token_end(value, j)
            tokens += 1
        if j < n and value[j].isdecimal():
            i = j
            while i < n and value[i].isdecimal():
                digit_count += 1
                i += 1
            continue
        break
    return i, digit_count


def _without_numbers(value):
    """The audit copy (and, fix round 1 / M1, the SERVED copy) of a reason: any run
    of nine or more digits — ASCII, Thai ๐-๙, fullwidth ０-９ and any other
    decimal digit (Unicode category Nd, `str.isdecimal()` — fix round 4: not
    `str.isdigit()`, which also takes superscripts, subscripts and circled digits and
    so stripped forms the old `\\d` never matched), joined across up to three
    separator TOKENS at a time (a whitespace-or-invisible-format run, or a
    same-character punctuation run, each count as one — fix round 2 / M4, made
    linear-time in fix round 3) — is cut out.
    This also cuts a 13-digit id or a large amount that happens to run that long;
    over-stripping is accepted, because a confident redaction beats a missed phone
    number. Linear in `len(value)` by construction (see `_run_extent`'s docstring),
    not merely on the forms that happen to be tested."""
    n = len(value)
    out = []
    i = 0
    while i < n:
        ch = value[i]
        if ch.isdecimal() or (ch == "+" and i + 1 < n and value[i + 1].isdecimal()):
            end, digit_count = _run_extent(value, i)
            out.append(_REDACTED_MARKER if digit_count >= 9 else value[i:end])
            i = end
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _served_reason(reason):
    """Fix round 1 / M1: every SERVED reason — a list row's or the case detail's
    `phone_override.reason` — goes through the same redaction as the audit copy,
    then a 200-character cap with "…". The stored row (records.customer_contact,
    or `_HISTORY`/`_MEMORY` with no database) keeps the reason exactly as typed;
    only what `_public` hands to a reader is touched."""
    redacted = _without_numbers(reason)
    if len(redacted) > REASON_SERVED_MAX:
        return redacted[:REASON_SERVED_MAX] + "…"
    return redacted


# Fix round 3 / M13: the exact rule user_accounts.py's `_shaped_like_a_name` (B10a /
# fix round 1 M5) uses for a display name, copied here rather than imported — that
# helper is module-private (a leading underscore) and this module does not import
# user_accounts.py. Unlike a display name, `by` has no combining-mark-run cap: any
# ONE visible base character is enough.
_MARK_CATEGORIES = ("Mn", "Me")
# Escapes, not literal invisible characters (fix round 3 / M11's own rule, applied
# here too): U+115F/U+1160 (Hangul Choseong/Jungseong fillers), U+3164 (Hangul
# filler), U+FFA0 (halfwidth Hangul filler), U+2800 (Braille pattern blank).
_INVISIBLE_FILLERS = ("\u115f", "\u1160", "\u3164", "\uffa0", "\u2800")


def _has_visible_actor(value):
    """Fix round 2 / M8, widened fix round 3 / M13: whitespace, combining marks
    (Mn/Me), Unicode Cf (format) characters and the fillers above do not make an
    actor's name visible — a zero-width space, U+3164 (a Hangul filler — a LETTER,
    category Lo, not a mark or format character) or U+2800 (BRAILLE PATTERN BLANK, a
    SYMBOL) among them all render blank on a screen but none of them is whitespace
    or Cf alone."""
    for ch in value:
        category = unicodedata.category(ch)
        if category in _MARK_CATEGORIES or category == "Cf" or category.startswith("Z") or ch in _INVISIBLE_FILLERS:
            continue
        return True
    return False


def _clean_actor(by):
    """Fix round 4 / item 2: `by` as it is stored, else CaseError phone_actor_invalid.

    The three steps user_accounts._clean_name takes for a display name, in its order:
    whitespace collapsed and trimmed with " ".join(by.split()) — which also removes
    tab, LF, CR, VT, FF, U+001C-U+001F and NEL, all `str.isspace()`-true — then any
    Unicode category C character still there (Cc, Cf, Co, Cn; a surrogate never gets
    this far, R1 refused it) refused, then the visible-base-character rule above.
    M13's copy of that rule skipped the first two steps, and a Cc character is none of
    Z*, Mn/Me, Cf or a filler, so a `by` of only control whitespace passed it and
    Postgres stored set_by = ''."""
    if isinstance(by, str):
        by = " ".join(by.split())
        if not any(unicodedata.category(ch).startswith("C") for ch in by) and _has_visible_actor(by):
            return by
    raise CaseError("phone_actor_invalid", "The acting person is required",
                    message_th=ACTOR_REQUIRED_TH, pointer="/by")


def normalise(raw):
    """(e164, kind) for a Thai mobile or landline number, else CaseError phone_invalid.

    Accepts 0812345678, 081-234-5678, +66 81 234 5678, 66812345678, (02) 123-4567,
    and — fix round 1 / M2 — the redundant "+66 (0)81 234 5678" / "+660812345678"
    forms: one leading 0 kept after the country code is dropped before the shape
    check. The refusal never echoes what was typed.
    """
    compact = _SEPARATORS.sub("", str(raw or ""))
    if compact.startswith("+66"):
        remainder = compact[3:]
        if remainder.startswith("0"):
            remainder = remainder[1:]
        national = "0" + remainder
    elif compact.startswith("66") and len(compact) in (10, 11):
        national = "0" + compact[2:]
    else:
        national = compact
    if _MOBILE.match(national):
        kind = "MOBILE"
    elif _LANDLINE.match(national):
        kind = "LANDLINE"
    else:
        raise CaseError("phone_invalid", "Not a Thai mobile (06/08/09, 10 digits) or landline (02-07, 9 digits) number",
                        message_th=INVALID_TH, pointer="/phone")
    return "+66" + national[1:], kind


def display(e164, kind):
    """The number as an officer reads it aloud: 081-234-5678, 02-123-4567, 053-123-456."""
    national = "0" + e164[3:]
    if kind == "MOBILE":
        return "%s-%s-%s" % (national[:3], national[3:6], national[6:])
    if national.startswith("02"):
        return "%s-%s-%s" % (national[:2], national[2:5], national[5:])
    return "%s-%s-%s" % (national[:3], national[3:6], national[6:])


def _public(row, durable):
    at = row.get("set_at")
    rec = {"phone_e164": row["phone_e164"], "display": display(row["phone_e164"], row["kind"]),
           "kind": row["kind"], "set_by": row["set_by"],
           "set_at": at.isoformat() if hasattr(at, "isoformat") else at,
           "reason": _served_reason(row["reason"]), "durable": durable}
    if not durable:
        rec["note_th"] = NOT_DURABLE_TH
        rec["note_en"] = NOT_DURABLE_EN
    return rec


def served_override(override):
    """`active_for`'s record minus the number itself. Every SERVED customer object
    carries this shape: `phone_e164` and `display` never travel on a list or a case
    detail any more (2026-09-20): the full number is one audited `reveal_phone` call
    away, so "hidden" is the server's answer and not a CSS promise the Network tab
    can break. The stored row and `_public` keep the number — internal callers
    (`set_phone`'s "changes nothing" check) still compare it."""
    if not override:
        return None
    return {key: value for key, value in override.items()
            if key not in ("phone_e164", "display")}


def _dial_parts(raw):
    """(e164, display, kind) for a number off the BOOK — it was never person-validated,
    so a shape the validator refuses still gets a dialable/as-typed answer instead of a
    refusal. The digits (leading + kept) are what a `tel:` link needs; the as-typed
    string is what the screen shows. Imported Odoo numbers arrive as typed by Odoo
    ("0925423597", "+66 84 138 5770"), so both forms are ordinary here."""
    as_typed = str(raw or "").strip()
    try:
        e164, kind = normalise(as_typed)
        return e164, display(e164, kind), kind
    except CaseError:
        digits = "".join(ch for ch in as_typed if ch.isascii() and ch.isdigit())
        if as_typed.startswith("+"):
            digits = "+" + digits
        return (digits or as_typed), as_typed, None


def reveal_phone(customer_uid, customer=None):
    """The ONE read of a full number. A person-entered override wins over the book;
    otherwise the imported `phone_e164` (Odoo/crm.lead and, after the 2026-09-20
    pipeline fix, the sheet) is answered. The act is audited as PHONE_REVEALED with
    its source and kind and never the digits — the same rule PHONE_SET follows — so
    a data-subject complaint can name every time a number was put on a screen."""
    override = active_for(customer_uid)
    from . import audit
    if override and override.get("phone_e164"):
        audit.describe(act="PHONE_REVEALED", subject=("customer", customer_uid),
                       detail={"kind": override.get("kind"), "source": "OVERRIDE"})
        return {"phone_e164": override["phone_e164"], "phone_display": override["display"],
                "kind": override.get("kind"), "source": "OVERRIDE"}
    raw = getattr(customer, "phone_e164", None) if customer is not None else None
    if not raw:
        raise CaseError("phone_not_on_file", "No full number is on file for this customer",
                        message_th="ยังไม่มีเบอร์เต็มในระบบสำหรับลูกค้ารายนี้")
    e164, shown, kind = _dial_parts(raw)
    audit.describe(act="PHONE_REVEALED", subject=("customer", customer_uid),
                   detail={"kind": kind, "source": "IMPORT"})
    return {"phone_e164": e164, "phone_display": shown, "kind": kind, "source": "IMPORT"}


# --- refusals (RFC 9457) — fix round 1 / I1, fix round 2 / M6 --------------------------

def _phone_unreachable():
    return errors.Problem(
        code="phone_store_unreachable", status=503,
        title="The phone number cannot be read or saved right now",
        detail="A database is configured and did not answer.",
        message_th="อ่านหรือบันทึกเบอร์โทรไม่ได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง",
        error_id="DEBT-COL-0465", retryable=True)


def _phone_store_not_migrated():
    # Fix round 2 / M6: the database answers but records.customer_contact is not
    # there. Not retryable by the person in the ordinary sense — it stays this way
    # until debt-migrate runs — but marked retryable=True per the controller's
    # ruling, since the CALLER cannot otherwise distinguish it from a transient 503
    # and this module's other 503 already sets the precedent.
    return errors.Problem(
        code="phone_store_not_migrated", status=503,
        title="The phone number table is missing",
        detail="records.customer_contact does not exist on the configured database. "
               "Run the debt-migrate job (schema.sql), then try again.",
        message_th="ฐานข้อมูลยังไม่มีตารางเบอร์โทรลูกค้า (records.customer_contact) "
                    "กรุณาให้ผู้ดูแลระบบรัน debt-migrate ก่อน แล้วลองใหม่อีกครั้ง",
        error_id="DEBT-COL-0467", retryable=True)


def _connect():
    try:
        return db.connect()
    except db.DatabaseUnreachable:
        raise _phone_unreachable() from None


def _connection_lost(exc):
    return (isinstance(exc, (OperationalError, InterfaceError, DisconnectionError))
            or bool(getattr(exc, "connection_invalidated", False)))


def _table_missing(conn):
    """Fix round 2 / M6: true only when records.customer_contact itself is absent —
    the migration never ran. Asked on the failure path alone, in a transaction of its
    own after the failed one rolled back, and by NAME — never by reading the driver
    exception, whose text can quote a bound value (a phone number). Copies
    user_accounts.py's own `_table_missing` (B10b ruling)."""
    try:
        with conn.begin():
            return conn.execute(text("select to_regclass('records.customer_contact') is null")).scalar() is True
    except SQLAlchemyError:
        return False


@contextmanager
def _transaction():
    """One write connection, closed either way. Fix round 1 / I1, copying
    user_accounts._transaction(): a connection lost mid-query is the same retryable
    503 as one that never opened; a missing table (fix round 2 / M6) is the labelled
    503 `phone_store_not_migrated`; anything else is an opaque Problem. All raised
    `from None` (no chained traceback for a log to carry the number in).

    Fix round 2 / R1 backstop: `set_phone` already refuses a NUL or a lone surrogate
    before it is ever bound, but a `UnicodeEncodeError` the driver itself raises (a
    lone surrogate reaching psycopg's UTF-8 encode) is a `UnicodeError`, never a
    `SQLAlchemyError` — so it is caught here too, same answer, same reason. This is
    what makes "no driver exception ever leaves here" true instead of aspirational.
    """
    conn = _connect()
    try:
        with conn.begin():
            yield conn
    except (SQLAlchemyError, UnicodeError) as exc:
        if _connection_lost(exc):
            raise _phone_unreachable() from None
        if _table_missing(conn):
            raise _phone_store_not_migrated() from None
        raise errors.internal_error() from None
    finally:
        try:
            conn.close()
        except SQLAlchemyError:
            pass          # a dead connection's close; the answer above already stands


def _load_active():
    conn = _connect()
    try:
        # Fix round 2 / M6, comment corrected fix round 3 / M12: wrapped in its own
        # transaction (previously a bare execute()) so a failure here leaves
        # conn.begin()'s own __exit__ to roll back. Without that, the real failure
        # was SQLAlchemy's own InvalidRequestError on a second begin() after
        # autobegin — not Postgres's aborted-transaction state — and
        # _table_missing's `except SQLAlchemyError` silently swallowed it, so its
        # follow-up query on this same connection always reported "table exists".
        with conn.begin():
            rows = conn.execute(text(
                "select customer_uid, phone_e164, kind, set_by, set_at, reason "
                "from records.customer_contact where active")).mappings().all()
    except (SQLAlchemyError, UnicodeError) as exc:
        if _connection_lost(exc):
            raise _phone_unreachable() from None
        if _table_missing(conn):
            raise _phone_store_not_migrated() from None
        raise errors.internal_error() from None
    finally:
        try:
            conn.close()
        except SQLAlchemyError:
            pass
    return {r["customer_uid"]: _public(dict(r), True) for r in rows}


def active_for(customer_uid):
    """The customer's active override as served, or None."""
    if not db.configured():
        row = _MEMORY.get(customer_uid)
        return _public(row, False) if row else None
    active = _ACTIVE.get()
    if active is None:
        active = _load_active()
        _ACTIVE.set(active)
    return active.get(customer_uid)


def phone_fields(customer_uid, customer=None):
    """The phone keys every customer object serves — one definition for the work item,
    the case detail and the phone route. `phone_masked` is never touched
    (test_journey_rebuild.py:63). `phone_on_sheet` keeps the import's own answer
    (R5-F01); `phone_on_file` becomes true when a person entered a number.
    `phone_revealable` (2026-09-20) replaces the number itself: the full value is one
    audited `reveal_phone` call away and never rides a list, a work item or a case
    detail, so hiding survives devtools."""
    override = active_for(customer_uid)
    on_sheet = bool(getattr(customer, "phone_on_file", False)) if customer is not None else False
    revealable = bool(override and override.get("phone_e164")) or bool(
        getattr(customer, "phone_e164", None) if customer is not None else None)
    return {
        "phone_masked": getattr(customer, "phone_masked", None) if customer is not None else None,
        "phone_on_sheet": on_sheet,
        "phone_on_file": bool(override) or on_sheet,
        "phone_revealable": revealable,
        "phone_override": served_override(override),
    }


def set_phone(customer_uid, raw, by, reason):
    """Set (raw is a number) or clear (raw is None or blank) the customer's number.

    Order (fix round 2 adds the first two steps, fix round 3 the third): dangerous
    characters (R1), then reason a real non-blank str at most 500 characters (M5,
    fix round 3 Critical (3)), then shape (the number, then WHO — fix round 1 / I2,
    M8/M13, fix round 4 item 2), then "changes nothing" — all before the audit line
    and the first store read (M7), so a refusal writes nothing, no malformed column
    ever reaches SQL carrying a number, and a store failure on the READ still leaves
    an audit row that names the act it was attempting. Returns the new override, or
    None when cleared.
    """
    # R1 (fix round 2): before ANYTHING else — a NUL or a lone surrogate in any
    # string field of the body reaches neither a log line, a driver error, nor a
    # stored row that would fail every later read.
    for pointer, value in (("/phone", raw), ("/reason", reason), ("/by", by)):
        if isinstance(value, str) and _DANGEROUS_RE.search(value):
            raise CaseError("text_invalid", "This field carries a character that cannot be stored",
                            message_th=TEXT_INVALID_TH, pointer=pointer)
    # M5 (fix round 2): a non-str reason (a dict, a list) used to be silently str()'d
    # into the stored row instead of refused.
    if not isinstance(reason, str) or not reason.strip():
        raise CaseError("reason_required", "Changing a phone number needs a reason",
                        message_th="ต้องระบุเหตุผลในการแก้ไขเบอร์โทร", pointer="/reason")
    reason = reason.strip()
    # Fix round 3 / Critical (3): defence in depth, independent of the scanner above
    # — even a bug there could only ever be linear in at most REASON_MAX characters
    # for anything actually written. Before audit.describe, like every other check.
    if len(reason) > REASON_MAX:
        raise CaseError("reason_too_long", "A reason is at most %d characters" % REASON_MAX,
                        message_th=REASON_TOO_LONG_TH, pointer="/reason")
    clearing = raw is None or not str(raw).strip()
    e164, kind = (None, None) if clearing else normalise(raw)
    # Fix round 1 / I2, widened fix round 2 / M8, fix round 3 / M13 and fix round 4 /
    # item 2: validated (and normalised) before anything is written, so a CHECK
    # constraint can never fail on a row that carries a number, and no blank set_by
    # is ever stored.
    by = _clean_actor(by)
    if kind is not None and kind not in KINDS:
        raise CaseError("phone_invalid", "Not a Thai mobile or landline number",
                        message_th=INVALID_TH, pointer="/phone")
    # M7 (fix round 2): audit.describe runs before the FIRST store read (active_for,
    # next), not only before the write — a database unreachable on that read used to
    # leave the request's audit row at act=None (main.py's audit_trail middleware
    # default for a write), silently losing the one clue that a PHONE_SET was even
    # attempted.
    from . import audit
    audit.describe(act="PHONE_SET", subject=("customer", customer_uid),
                   detail={"phone": "cleared" if clearing else "set", "kind": kind,
                           "reason": _without_numbers(reason)})
    current = active_for(customer_uid)
    if (clearing and current is None) or (current is not None and current["phone_e164"] == e164):
        raise CaseError("phone_unchanged", "The customer's number already reads that",
                        message_th="เบอร์ของลูกค้าเป็นแบบนี้อยู่แล้ว", pointer="/phone")
    if not db.configured():
        row = {"customer_uid": customer_uid, "phone_e164": e164, "kind": kind, "set_by": by,
               "set_at": datetime.now(timezone.utc), "reason": reason, "active": not clearing}
        previous = _MEMORY.pop(customer_uid, None)
        if previous is not None:
            previous["active"] = False
        _HISTORY.append(row)
        if not clearing:
            _MEMORY[customer_uid] = row
        return active_for(customer_uid)
    with _transaction() as conn:
        # One writer per customer at a time: two officers saving at once would
        # otherwise both deactivate nothing and both insert an active row.
        conn.execute(text("select pg_advisory_xact_lock(hashtext(:u))"), {"u": customer_uid})
        conn.execute(text("update records.customer_contact set active = false "
                          "where customer_uid = :u and active"), {"u": customer_uid})
        conn.execute(text("insert into records.customer_contact "
                          "(customer_uid, phone_e164, kind, set_by, reason, active) "
                          "values (:u, :p, :k, :b, :r, :a)"),
                     {"u": customer_uid, "p": e164, "k": kind, "b": by, "r": reason, "a": not clearing})
    _ACTIVE.set(None)
    return active_for(customer_uid)

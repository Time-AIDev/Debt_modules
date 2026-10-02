"""Band sets — API Surface v2.1 §2.2.

    "Any response carrying aging_bucket also carries band_set_code. The two together
     identify a band; the bucket code alone no longer does, because the same code
     exists in more than one set."

Client obligation, logged upstream as open issue API-01.

`ref.aging_band_set` seeds exactly two, and these are their real names — an invented
code would not join:
  OPERATIONAL — the design bands the queue uses (0 / 1-7 / 8-29 / 30+).
  LEGACY_LDR  — the boundaries the existing reporting uses (30 / 45 / 60 / 75 / 90),
                kept for as long as figures are compared across the cut-over.

The two sets OVERLAP BY CONSTRUCTION. That is why the bucket table is keyed on
(code, band_set_code) and the non-overlap constraint is scoped WITHIN a set — a global
constraint would reject the legacy set outright. This is the one structural change in
v2.1 that is not additive.
"""
import re
from dataclasses import dataclass
from typing import Optional

from .dpd import STATUS_OVERRIDE
from ..session import Store


class BandSetUnknown(Exception):
    """422 band_set_unknown. Falling back to a default set would produce a number that
    looks right and means something else."""

    code = "band_set_unknown"

    def __init__(self, band_set_code):
        super().__init__(
            "unknown band_set_code %r; known sets are %s" % (band_set_code, sorted(BAND_SETS))
        )
        self.band_set_code = band_set_code


class BandSetInvalid(Exception):
    """422 — round-4 J4-14. A blank set code or a blank band code used to be accepted:
    the set was invisible on screen and unreachable by its own `:deactivate` route, so
    it could never be deactivated, reactivated or removed. The refusal names the field."""

    code = "band_set_invalid"

    def __init__(self, pointer, message, message_th):
        super().__init__(message)
        self.pointer = pointer
        self.message = message
        self.message_th = message_th


# A code is a path segment on its own routes (`/v1/band-sets/{code}:deactivate`), so it
# must be spellable in one: no blanks, no spaces, no slashes or colons.
CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")
CODE_RULE_TH = "รหัสต้องเป็นตัวอักษรอังกฤษ ตัวเลข _ - หรือ . ยาวไม่เกิน 40 ตัว และห้ามเว้นว่าง"


def _check_code(raw, pointer, what_th):
    text = "" if raw is None else str(raw).strip()
    if not text:
        raise BandSetInvalid(pointer, "%s is required" % pointer.lstrip("/"),
                             "ต้องระบุ%s" % what_th)
    if not CODE_PATTERN.match(text):
        raise BandSetInvalid(pointer, "%r is not a usable code" % text,
                             "%sไม่ถูกต้อง — %s" % (what_th, CODE_RULE_TH))
    return text


@dataclass(frozen=True)
class Band:
    code: Optional[str]
    band_set_code: str


# The seeded sets. Immutable, module-level, shared by every session on purpose —
# this is the reference book (same status as CUSTOMERS/BY_CUSTOMER, ruling 39/40's
# reasoning), never written after import.
_SEEDED_BAND_SETS = {
    "OPERATIONAL": (
        (0, 0, "CURRENT"),
        (1, 7, "EARLY_OVERDUE"),
        (8, 29, "MID_OVERDUE"),
        (30, None, "RISK_REVIEW"),
    ),
    # October feedback / Amendment v2.6. This is the collection-facing ladder.
    # Historical/reporting sets below stay byte-for-byte compatible.
    "COLLECTION_STATUS_V1": (
        (0, 0, "CURRENT"),
        (1, 30, "COLLECTION_1_30"),
        (31, 60, "COLLECTION_31_60"),
        (61, 89, "COLLECTION_61_89"),
        (90, None, "COLLECTION_90_PLUS"),
    ),
    "LEGACY_LDR": (
        (0, 29, "LDR_CURRENT"),
        (30, 44, "LDR_30"),
        (45, 59, "LDR_45"),
        (60, 74, "LDR_60"),
        (75, 89, "LDR_75"),
        (90, None, "LDR_90"),
    ),
    # 2026-09-02 (REQ-CFG-021): the buckets the team said it works with —
    # "30, 60, 90 is enough" — and the sheet's own "Bucket - Weeks Late" column.
    "SOP_30_60_90": (
        (0, 0, "CURRENT"),
        (1, 29, "UNDER_30"),
        (30, 59, "UNDER_60"),
        (60, 89, "UNDER_90"),
        (90, None, "OVER_90"),
    ),
    "LEGACY_SHEET": (
        (0, 0, "CURRENT"),
        (1, 29, "SHEET_LT30"),
        (30, 44, "SHEET_LT45"),
        (45, 59, "SHEET_LT60"),
        (60, 74, "SHEET_LT75"),
        (75, 89, "SHEET_LT90"),
        (90, None, "SHEET_GT90"),
    ),
}


# Ruling 43, R4-F02 (MAJOR): `register`/`activate`/`deactivate` used to write straight
# onto these six names as process-wide module globals — one tester registering or
# deactivating a band set changed the catalogue every other tester's aging column is
# defined against, and SET_HISTORY merged every session's provenance into one log with
# no way to tell whose act was whose. Same defect class as ruling 32's `config.settings`
# (a module-wide mutable, not a per-object field), fixed the same way: a `session.Store`
# holding one registry per session, with each of the six names replaced by a thin proxy
# that forwards the dict/set/list protocol to `_registry().for_current()`. Every read
# and write site in this module (and the one direct-attribute test seam,
# `tests/conftest.py:40`'s `INACTIVE_SETS.clear()`) keeps the same name and the same
# call shape — the indirection is invisible, same guarantee ruling 32 made for
# `settings` and ruling 39 made for `BOARD_COLUMNS`.
def _default_registry():
    return {
        "BAND_SETS": dict(_SEEDED_BAND_SETS),
        "CUSTOM_SETS": {},
        "SET_HISTORY": [],
        "INACTIVE_SETS": set(),
        "CUSTOM_SET_LABELS": {},
        "CUSTOM_BAND_LABELS": {},
    }


_registry_store = Store(_default_registry, key="money.band_sets.registry")


def reset():
    """Test seam, matching the sibling domains' idiom — clears EVERY session's
    registry, not just the current one."""
    _registry_store.reset()


def _registry():
    return _registry_store.for_current()


class _DictProxy:
    """dict-shaped stand-in for a module-level registry key. Delegates every dict
    operation to the current session's slot."""

    def __init__(self, key):
        self._key = key

    def _d(self):
        return _registry()[self._key]

    def __getitem__(self, k):
        return self._d()[k]

    def __setitem__(self, k, v):
        self._d()[k] = v

    def __delitem__(self, k):
        del self._d()[k]

    def __contains__(self, k):
        return k in self._d()

    def __iter__(self):
        return iter(self._d())

    def __len__(self):
        return len(self._d())

    def get(self, k, default=None):
        return self._d().get(k, default)

    def items(self):
        return self._d().items()

    def values(self):
        return self._d().values()

    def keys(self):
        return self._d().keys()

    def update(self, *a, **kw):
        return self._d().update(*a, **kw)


class _SetProxy:
    """set-shaped stand-in, same delegation."""

    def __init__(self, key):
        self._key = key

    def _s(self):
        return _registry()[self._key]

    def add(self, x):
        self._s().add(x)

    def discard(self, x):
        self._s().discard(x)

    def clear(self):
        self._s().clear()

    def __contains__(self, x):
        return x in self._s()

    def __iter__(self):
        return iter(self._s())

    def __len__(self):
        return len(self._s())


class _ListProxy:
    """list-shaped stand-in, same delegation."""

    def __init__(self, key):
        self._key = key

    def _l(self):
        return _registry()[self._key]

    def append(self, x):
        self._l().append(x)

    def __iter__(self):
        return iter(self._l())

    def __len__(self):
        return len(self._l())

    def __getitem__(self, i):
        return self._l()[i]

    def clear(self):
        self._l().clear()


# Sets a Manager adds at runtime (REQ-CFG-021). Seeded sets are never edited.
BAND_SETS = _DictProxy("BAND_SETS")
CUSTOM_SETS = _DictProxy("CUSTOM_SETS")
SET_HISTORY = _ListProxy("SET_HISTORY")


# Judge J-54: a set is deactivated, never deleted — figures already labelled with its
# code must still resolve. Membership here only hides it from new selections.
INACTIVE_SETS = _SetProxy("INACTIVE_SETS")

# Round-3 J3-11: the one sentence the screen prints where an edit control would be.
EDIT_REFUSAL_TH = "แก้ไขไม่ได้ — สร้างชุดใหม่แล้วเปลี่ยนชุดที่ใช้"
EDIT_REFUSAL_EN = "Cannot be edited — create a new set, then switch to it"

# Round-4 J4-13: a band set carries its own Thai labels. The seeded sets' words are the
# ones already on the officers' screens; anything else — a set a Manager authored, a
# legacy code with no wording of its own — is described from its OWN boundaries, so a
# column can never print a raw code like S4_MID at a desk again.
SEEDED_BAND_LABEL_TH = {
    "CURRENT": "ปกติ",
    "EARLY_OVERDUE": "ค้าง 1–7 วัน",
    "MID_OVERDUE": "ค้าง 8–29 วัน",
    "RISK_REVIEW": "ค้าง 30 วันขึ้นไป",
    "UNDER_30": "ค้างไม่ถึง 30 วัน",
    "UNDER_60": "ค้าง 30–59 วัน",
    "UNDER_90": "ค้าง 60–89 วัน",
    "OVER_90": "ค้าง 90 วันขึ้นไป",
    "COLLECTION_1_30": "ค้าง 1–30 วัน",
    "COLLECTION_31_60": "ค้าง 31–60 วัน",
    "COLLECTION_61_89": "ค้าง 2–3 เดือน (61–89 วัน)",
    "COLLECTION_90_PLUS": "ค้าง 90 วันขึ้นไป",
}
SEEDED_BAND_LABEL_EN = {
    "CURRENT": "Current",
    "EARLY_OVERDUE": "1–7 days overdue",
    "MID_OVERDUE": "8–29 days overdue",
    "RISK_REVIEW": "30+ days overdue",
    "UNDER_30": "Under 30 days overdue",
    "UNDER_60": "30–59 days overdue",
    "UNDER_90": "60–89 days overdue",
    "OVER_90": "90+ days overdue",
    "COLLECTION_1_30": "1–30 days overdue",
    "COLLECTION_31_60": "31–60 days overdue",
    "COLLECTION_61_89": "2–3 months overdue (61–89 days)",
    "COLLECTION_90_PLUS": "90+ days overdue",
}

# The seeded sets' own names, from this module's docstring — the chooser printed the
# raw code (J4-13). A set a Manager authors keeps its code as its name unless they type
# one; nothing here is invented for a set the app did not seed.
SEEDED_SET_LABEL_TH = {
    "OPERATIONAL": "ชุดปฏิบัติงาน (0 / 1–7 / 8–29 / 30+ วัน)",
    "LEGACY_LDR": "ชุดรายงานเดิม LDR (30 / 45 / 60 / 75 / 90 วัน)",
    "SOP_30_60_90": "ชุดตาม SOP (30 / 60 / 90 วัน)",
    "LEGACY_SHEET": "ชุดตามชีตเดิม",
    "COLLECTION_STATUS_V1": "สถานะติดตามหนี้ (0 / 1–30 / 31–60 / 61–89 / 90+ วัน)",
}
SEEDED_SET_LABEL_EN = {
    "OPERATIONAL": "Operational set (0 / 1–7 / 8–29 / 30+ days)",
    "LEGACY_LDR": "Legacy LDR report set (30 / 45 / 60 / 75 / 90 days)",
    "SOP_30_60_90": "SOP set (30 / 60 / 90 days)",
    "LEGACY_SHEET": "Legacy sheet set",
    "COLLECTION_STATUS_V1": "Collection status (0 / 1–30 / 31–60 / 61–89 / 90+ days)",
}

# A label a Manager typed, per (set code, band code). Never invented, never guessed.
# Ruling 43 / R4-F02: per-session proxies, same registry as BAND_SETS above.
CUSTOM_BAND_LABELS = _DictProxy("CUSTOM_BAND_LABELS")
CUSTOM_SET_LABELS = _DictProxy("CUSTOM_SET_LABELS")


def band_label_th(set_code, band_code, low, high):
    """The band's own Thai words: the author's, then the seeded wording, then the
    boundaries said in Thai. A raw code is never the answer."""
    typed = CUSTOM_BAND_LABELS.get((set_code, band_code))
    if typed:
        return typed
    if band_code in SEEDED_BAND_LABEL_TH:
        return SEEDED_BAND_LABEL_TH[band_code]
    if low in (0, "0") and (high == 0):
        return "ปกติ (ไม่ค้าง)"
    if high is None:
        return "ค้าง %s วันขึ้นไป" % low
    if low == high:
        return "ค้าง %s วัน" % low
    return "ค้าง %s–%s วัน" % (low, high)


def band_label_en(set_code, band_code, low, high):
    """English twin of band_label_th. A label a Manager typed is their own text and
    is served as typed in both languages."""
    typed = CUSTOM_BAND_LABELS.get((set_code, band_code))
    if typed:
        return typed
    if band_code in SEEDED_BAND_LABEL_EN:
        return SEEDED_BAND_LABEL_EN[band_code]
    if low in (0, "0") and (high == 0):
        return "Current (not overdue)"
    if high is None:
        return "%s+ days overdue" % low
    if low == high:
        return "%s days overdue" % low
    return "%s–%s days overdue" % (low, high)


def set_label_th(code):
    return CUSTOM_SET_LABELS.get(code) or SEEDED_SET_LABEL_TH.get(code) or code


def set_label_en(code):
    return CUSTOM_SET_LABELS.get(code) or SEEDED_SET_LABEL_EN.get(code) or code


def label_for(band_set_code, band_code, lang="th"):
    """The words for one band of one set — what a ช่วงอายุหนี้ column prints.
    Round-4 J4-13: a screen must never have to translate a code it has never seen."""
    if not band_code:
        return None
    label = band_label_en if lang == "en" else band_label_th
    for lo, hi, c in BAND_SETS.get(band_set_code, ()):
        if c == band_code:
            return label(band_set_code, c, lo, hi)
    # A status override (NPL_CONFIRMED, RESOLVED, CLOSED) is not a dpd band.
    if lang == "en":
        return SEEDED_BAND_LABEL_EN.get(band_code) or STATUS_LABEL_EN.get(band_code)
    return SEEDED_BAND_LABEL_TH.get(band_code) or STATUS_LABEL_TH.get(band_code)


STATUS_LABEL_TH = {
    "NPL_CONFIRMED": "NPL ยืนยันแล้ว",
    "RESOLVED": "ปิดแล้ว",
    "CLOSED": "ปิดสัญญา",
    # 2026-09-20: the band label for an ended contract. The contract-status value
    # travels beside it; this is the ladder's own word for "no longer climbing".
    "TERMINATED": "ยุติสัญญา",
}
STATUS_LABEL_EN = {
    "NPL_CONFIRMED": "NPL confirmed",
    "RESOLVED": "Resolved",
    "CLOSED": "Contract closed",
    "TERMINATED": "Contract terminated",
}


def _band_rows(set_code, bands):
    return [{"low": lo, "high": hi, "code": c,
             "label_th": band_label_th(set_code, c, lo, hi),
             "label_en": band_label_en(set_code, c, lo, hi)} for lo, hi, c in bands]


def describe():
    out = []
    seen = set()
    for code, bands in list(BAND_SETS.items()) + list(CUSTOM_SETS.items()):
        if code in seen:
            continue
        seen.add(code)
        out.append({"code": code, "seeded": code in BAND_SETS and code not in CUSTOM_SETS,
                    "active": code not in INACTIVE_SETS,
                    "label_th": set_label_th(code), "label_en": set_label_en(code),
                    # J4-14: every set that exists is reachable by its own routes. The
                    # path is served rather than assembled on a screen, because a code
                    # that cannot be put in one is refused at creation now.
                    "deactivate_path": "/v1/band-sets/%s:deactivate" % code,
                    "activate_path": "/v1/band-sets/%s:activate" % code,
                    # Round-3 J3-11: a boundary CANNOT be moved on a set that is already
                    # in use — figures already labelled with the set would silently change
                    # meaning. The API says so plainly instead of showing no control.
                    "editable": False,
                    "reason_th": EDIT_REFUSAL_TH,
                    "reason_en": EDIT_REFUSAL_EN,
                    "bands": _band_rows(code, bands)})
    return out


def activate(code, by):
    """Round-3 J3-38: deactivation was one click with no way back from the screen."""
    if code not in BAND_SETS:
        raise BandSetUnknown(code)
    INACTIVE_SETS.discard(code)
    SET_HISTORY.append({"code": code, "by": by, "act": "ACTIVATE"})
    return next(row for row in describe() if row["code"] == code)


def deactivate(code, by):
    if code not in BAND_SETS:
        raise BandSetUnknown(code)
    INACTIVE_SETS.add(code)
    SET_HISTORY.append({"code": code, "by": by, "act": "DEACTIVATE"})
    return next(row for row in describe() if row["code"] == code)


def register(code, bands, by, label_th=None):
    """bands: [{"low": int, "high": int|None, "code": str, "label_th": str}], contiguous,
    non-overlapping WITHIN the set. The set name must be new.

    Round-4 J4-14: the code and every band code are validated BEFORE anything is
    written. Round-4 J4-13: each band carries its own Thai label.
    """
    code = _check_code(code, "/code", "รหัสชุดช่วงอายุหนี้")
    if code in BAND_SETS or code in CUSTOM_SETS:
        raise ValueError("band set %s exists" % code)
    if not isinstance(bands, (list, tuple)) or not bands:
        raise BandSetInvalid("/bands", "at least one band is required",
                             "ต้องมีอย่างน้อยหนึ่งช่วง")
    labels = {}
    parsed = []
    expected_low = 0
    for index, b in enumerate(bands):
        if not isinstance(b, dict):
            raise BandSetInvalid("/bands/%d" % index, "a band is an object", "รูปแบบช่วงไม่ถูกต้อง")
        c = _check_code(b.get("code"), "/bands/%d/code" % index, "รหัสช่วง")
        try:
            lo = int(b["low"])
            hi = None if b.get("high") in (None, "") else int(b["high"])
        except (KeyError, TypeError, ValueError):
            raise BandSetInvalid("/bands/%d/low" % index, "low and high must be whole numbers",
                                 "จาก/ถึง ต้องเป็นตัวเลขจำนวนเต็ม")
        typed = (b.get("label_th") or "").strip()
        if typed:
            labels[(code, c)] = typed
        if lo != expected_low:
            raise ValueError("bands must be contiguous from 0; gap before %d" % lo)
        if hi is not None and hi < lo:
            raise ValueError("high below low in %s" % c)
        parsed.append((lo, hi, c))
        expected_low = None if hi is None else hi + 1
    if expected_low is not None:
        raise ValueError("the last band must be open-ended")
    CUSTOM_SETS[code] = tuple(parsed)
    BAND_SETS[code] = tuple(parsed)
    CUSTOM_BAND_LABELS.update(labels)
    if (label_th or "").strip():
        CUSTOM_SET_LABELS[code] = label_th.strip()
    SET_HISTORY.append({"code": code, "by": by})
    return {"code": code, "seeded": False, "active": True, "label_th": set_label_th(code),
            "label_en": set_label_en(code),
            "deactivate_path": "/v1/band-sets/%s:deactivate" % code,
            "activate_path": "/v1/band-sets/%s:activate" % code,
            "bands": _band_rows(code, parsed)}


def resolve_band(status, dpd, band_set_code) -> Band:
    if band_set_code not in BAND_SETS:
        raise BandSetUnknown(band_set_code)

    # Status still wins over the number, and the set still travels with the answer.
    if status in STATUS_OVERRIDE:
        return Band(STATUS_OVERRIDE[status], band_set_code)
    if dpd is None:
        return Band(None, band_set_code)

    for low, high, code in BAND_SETS[band_set_code]:
        if dpd >= low and (high is None or dpd <= high):
            return Band(code, band_set_code)
    return Band(None, band_set_code)


def assert_band_pair_present(payload):
    """Walk a response payload and fail if any object carries `aging_bucket` without
    `band_set_code` beside it. Used as a response-boundary guard in the tests so the
    rule cannot be quietly dropped by a new endpoint."""
    if isinstance(payload, dict):
        if "aging_bucket" in payload:
            assert "band_set_code" in payload, (
                "aging_bucket present without band_set_code — the bucket code alone "
                "does not identify a band (API Surface v2.1 §2.2)"
            )
        for value in payload.values():
            assert_band_pair_present(value)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            assert_band_pair_present(item)

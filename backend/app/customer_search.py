"""Small, epoch-bound customer identity index for the command palette.

The palette needs identity lookup, not the debt workbook's calculated balances.
Keeping normalized immutable fields here avoids building every work item for each
keystroke. Session overlays are applied after matching by the HTTP route.
"""
import threading
import unicodedata

from .session import Store


_LOCK = threading.Lock()
_CACHE = (None, None, None, ())
_OFFICER_OVERRIDES = Store(dict, key="customer.search.officer_overlay")
_FIELDS = ("volt_id", "customer_no", "display_name", "name_roman", "phone_masked", "email_masked")
_IDENTIFIERS = frozenset(("volt_id", "customer_no"))
_PREFIX_FIELDS = _IDENTIFIERS | frozenset(("display_name", "name_roman"))


def _normalized(value):
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def _document(customer):
    values = {field: getattr(customer, field, None) for field in _FIELDS}
    return {
        "customer_uid": customer.uid,
        "display_name": customer.display_name,
        "name_roman": values["name_roman"],
        "volt_id": values["volt_id"],
        "customer_no": customer.customer_no,
        "phone_masked": values["phone_masked"],
        "email_masked": values["email_masked"],
        "officer": getattr(customer, "officer", None),
        "search": {field: _normalized(values[field]) for field in _FIELDS},
    }


def _documents(customers, identities, epoch):
    global _CACHE
    customer_source, identity_source, cached_epoch, documents = _CACHE
    if customer_source is customers and identity_source is identities and cached_epoch == epoch:
        return documents
    with _LOCK:
        customer_source, identity_source, cached_epoch, documents = _CACHE
        if customer_source is not customers or identity_source is not identities or cached_epoch != epoch:
            documents = tuple(_document(customer) for customer in customers + identities)
            _CACHE = (customers, identities, epoch, documents)
    return documents


def _match(document, needle):
    best = None
    for order, field in enumerate(_FIELDS):
        value = document["search"][field]
        if not value or needle not in value:
            continue
        if field in _IDENTIFIERS and value == needle:
            rank = 0
        elif field in _PREFIX_FIELDS and value.startswith(needle):
            rank = 1
        else:
            rank = 2
        candidate = (rank, order, field)
        if best is None or candidate < best:
            best = candidate
    return best


def search(customers, identities, epoch, query, limit, officer_overrides=None):
    needle = _normalized(query)
    if not needle:
        return []
    matches = []
    for document in _documents(customers, identities, epoch):
        hit = _match(document, needle)
        if hit is not None:
            matches.append((hit, _normalized(document["display_name"]), document["customer_uid"], document))
    matches.sort(key=lambda item: (item[0], item[1], item[2]))
    overrides = officer_overrides or {}
    items = []
    for hit, _name, _uid, document in matches[:limit]:
        item = {key: value for key, value in document.items() if key != "search"}
        item["officer"] = overrides.get(item["customer_uid"], item["officer"])
        item["matched_on"] = hit[2]
        items.append(item)
    return items


def officer_overrides():
    """The palette's small persisted overlay, without restoring JourneyState.

    JourneyState contains invoices, receipts, PTPs and every other collection
    workflow object. Restoring all of that just to decorate six search hits made a
    first palette keystroke miss its latency budget on Cloud Run. Assignment writes
    mirror the one customer->officer fact into this tiny session store instead.
    """
    return _OFFICER_OVERRIDES.for_current()


def assign_officer(customer_uid, officer_uid):
    officer_overrides()[customer_uid] = officer_uid


def remember_officer_overrides(overrides):
    """Carry forward overlays restored from a pre-index JourneyState session."""
    if overrides:
        officer_overrides().update(overrides)


def invalidate():
    global _CACHE
    with _LOCK:
        _CACHE = (None, None, None, ())


def reset():
    invalidate()
    _OFFICER_OVERRIDES.reset()

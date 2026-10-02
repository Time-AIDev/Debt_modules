"""Process-level lightweight rows for contract-less customer identities.

These fields come from the immutable served book, not session overlays.  The cache
is tied to both the book list object and its data epoch; `reload_book()` also clears
it explicitly.  Callers copy only rows that enter a response, keeping the 25k-row
directory useful for filtering and sorting without rebuilding 25k dictionaries on
every request.
"""
import threading


_LOCK = threading.Lock()
_CACHE = (None, None, ())


def rows_for(customers, epoch, builder):
    global _CACHE
    source, cached_epoch, rows = _CACHE
    if source is customers and cached_epoch == epoch:
        return rows
    with _LOCK:
        source, cached_epoch, rows = _CACHE
        if source is not customers or cached_epoch != epoch:
            rows = tuple(builder(customer) for customer in customers)
            # Publish source, epoch and rows atomically so a concurrent request can
            # never observe the new key beside the previous snapshot's rows.
            _CACHE = (customers, epoch, rows)
    return rows


def invalidate():
    global _CACHE
    with _LOCK:
        _CACHE = (None, None, ())

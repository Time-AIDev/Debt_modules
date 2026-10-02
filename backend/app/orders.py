"""Order intake and the loan book.

Source of truth is the New Order Master sheet, imported by
`scripts/import_order_master.py` into `fixtures_orders.json`. Two facts about
that data drive everything below.

1. Every row in tab 'x' already reads "Order - Done". A queue with nothing
   pending demonstrates nothing, so the prototype SEEDS each imported order at
   "Order - EPC Installation" and lets a person move it to "Order - Done". The
   sheet's own value is kept beside it as `sheet_order_status` so the two are
   never mistaken for each other.

2. The 48 orders in 'x' and the 80 entries in 'Loan Book' share NO customer id.
   They are consecutive cohorts, not a lookup. Approving an order therefore
   APPENDS a new loan-book entry; it never updates an existing one.

State is process-local and resets on restart. Nothing here writes to the sheet.
"""
import json
from decimal import Decimal
from pathlib import Path

from .session import Store

STATUS_PENDING = "Order - EPC Installation"
STATUS_DONE = "Order - Done"

_DATA = json.loads((Path(__file__).parent / "fixtures_orders.json").read_text())

# All three are PER TESTER, not per process. Two people sharing a deployment must
# not see each other's approvals — see session.py.
#   _approved: approvals made in this session, keyed by order number
#   _added:    orders this session created
#   _removed:  sheet rows this session hid. The sheet is read-only, so a removal is
#              a local overlay and says so rather than pretending to write back.
_approved_store = Store(dict, key="orders.approved")
_added_store = Store(list, key="orders.added")
_removed_store = Store(set, key="orders.removed")

REQUIRED = ("first_name", "last_name", "crm_id")


def _key(order):
    """Stable identity for an overlay.

    The numeric `no` is a POSITION: an Odoo pull numbers its rows 9000+n in the
    order the API returned them (integrations/odoo.py), so keying an approval or a
    removal by `no` re-pointed it at another physical order after a re-sync that
    reordered or shortened the list (sync audit, 2026-09-20). Every sheet and Odoo
    row carries a volt_id; a session-created row gets one in add().
    """
    return str(order.get("volt_id") or order.get("crm_id") or order.get("no"))


def _upgrade_overlay_keys():
    """Rows persisted before the key change hold positional ints. Fold them onto the
    stable key once, using the live rows, instead of dropping a tester's approvals."""
    approved = _approved_store.for_current()
    removed = _removed_store.for_current()
    needs = any(not isinstance(k, str) for k in approved) or any(not isinstance(k, str) for k in removed)
    if not needs:
        return
    lookup = {}
    for order in _source_rows() + _added_store.for_current():
        lookup.setdefault(order.get("no"), _key(order))
    if any(not isinstance(k, str) for k in approved):
        moved = {}
        for k, v in approved.items():
            moved[str(k) if isinstance(k, str) else lookup.get(k, str(k))] = v
        approved.clear()
        approved.update(moved)
    if any(not isinstance(k, str) for k in removed):
        for k in list(removed):
            if not isinstance(k, str):
                removed.discard(k)
                removed.add(lookup.get(k, str(k)))


def reset():
    """Test seam, across every session. The prototype holds one run; tests must not
    inherit another's."""
    _approved_store.reset()
    _added_store.reset()
    _removed_store.reset()


def _source_rows():
    return _DATA["orders"]


def _all_rows():
    _upgrade_overlay_keys()
    added = _added_store.for_current()
    removed = _removed_store.for_current()
    return [o for o in _source_rows() + added if _key(o) not in removed]


def next_no():
    return max((o["no"] for o in _source_rows() + _added_store.for_current()), default=0) + 1


def add(payload, by):
    """Create an order in this run. Returns (order, error_code)."""
    payload = payload or {}
    missing = [f for f in REQUIRED if not str(payload.get(f) or "").strip()]
    if missing:
        return None, "missing:" + ",".join(missing)

    crm_id = str(payload["crm_id"]).strip()
    if any(str(o.get("crm_id")) == crm_id for o in _all_rows()):
        return None, "crm_id_taken"

    order_type = (payload.get("order_type") or "Leasing").strip()
    # A term is meaningless on a cash order and the sheet writes the word "Cash"
    # in that column, so the same convention is kept rather than inventing 0.
    cash = order_type.lower() == "cash"
    row = {
        "no": next_no(),
        "crm_id": crm_id,
        "volt_id": payload.get("volt_id") or "%s_%s_VOLT" % (crm_id, payload["first_name"]),
        "first_name": str(payload["first_name"]).strip(),
        "last_name": str(payload["last_name"]).strip(),
        "thai_name": payload.get("thai_name") or None,
        "sales_lead": payload.get("sales_lead") or by,
        "order_type": order_type,
        # An order created here has never been in the sheet. Saying "Order - Done"
        # would be a claim about a document this run cannot see.
        "sheet_order_status": None,
        "loan_status": payload.get("loan_status") or ("Cash" if cash else "Approved"),
        "contract_purchase": None, "contract_service": None,
        "submit_date": payload.get("submit_date") or None,
        "contract_signed_date": None,
        "inverter_brand": payload.get("inverter_brand") or None,
        "inverter_type": payload.get("inverter_type") or None,
        "monthly_rate_incl_vat": payload.get("monthly_rate_incl_vat") or None,
        "term_months": "Cash" if cash else (payload.get("term_months") or None),
        "project_type": payload.get("project_type") or "Resi",
        "energy_bill": None,
        "watt": payload.get("watt") or None,
        "phase": payload.get("phase") or None,
        "epc": payload.get("epc") or None,
        "epc_start_date": None, "epc_end_date": None,
        "province": payload.get("province") or None,
        "postal_code": payload.get("postal_code") or None,
        "address_masked": payload.get("address_masked") or None,
        "phone_masked": payload.get("phone_masked") or None,
        "email_masked": payload.get("email_masked") or None,
        "com_status": None,
        "origin": "added",
        "added_by": by,
    }
    _added_store.for_current().append(row)
    return _view(row), None


def remove(no):
    """Returns (removed_order, error_code)."""
    order = get(no)
    if order is None:
        return None, "not_found"
    key = _key(order)
    if key in _approved_store.for_current():
        # The lease is already in the book. Deleting the order under it would leave
        # a lease whose origin cannot be traced, which is worse than refusing.
        return None, "in_loan_book"
    added = _added_store.for_current()
    for i, row in enumerate(added):
        if _key(row) == key:
            added.pop(i)
            return order, None
    _removed_store.for_current().add(key)
    return order, None


def _view(order):
    approval = _approved_store.for_current().get(_key(order))
    out = {
        **order,
        "origin": order.get("origin", "sheet"),
        "order_status": STATUS_DONE if approval else STATUS_PENDING,
        "approved_by": approval["by"] if approval else None,
        "approved_at": approval["at"] if approval else None,
    }
    # 2026-09-20: the Odoo sync row carries phone_e164 (raw, by design) into
    # landing."order".extra, and `{**order}` spread it onto /v1/orders. The full
    # number is served only by the case's audited phone:reveal route now, so the
    # spread gets one key removed rather than the list growing a mask of its own.
    out.pop("phone_e164", None)
    return out


def orders():
    return [_view(o) for o in _all_rows()]


def get(no):
    for order in _all_rows():
        if order["no"] == no:
            return _view(order)
    return None


def kwp(watt):
    """Panel watts to kWp. A unit change, not a money calculation."""
    if not watt:
        return None
    return f"{Decimal(str(watt)) / 1000:.2f}"


def total_lease(monthly, tenor):
    """monthly x tenor, the same arithmetic the sheet's own column performs.

    Verified against Loan Book row 1: 6,882.00 x 60 = 412,920.00, which is the
    figure the sheet carries. Computed here rather than left blank because the
    rule is reproducible; the fields BELOW that are not derivable stay null.
    """
    if not monthly or not tenor:
        return None
    return f"{Decimal(str(monthly)) * int(tenor):.2f}"


def as_loan_book_entry(order, no):
    """Map an approved order onto the loan book's schema.

    Four of the loan book's columns have no counterpart in tab 'x' — the original
    system cost, the book value in loan currency, the commencement date and the
    age. They are returned as null and rendered as "not carried". Filling them
    with a plausible number would put a figure in a lender's book that nobody
    supplied.
    """
    return {
        "no": no,
        "lessee": order["volt_id"],
        "customer_id": order["crm_id"],
        "province": order["province"],
        "address_masked": order["address_masked"],
        "installer": order["epc"],
        "system_size_kwp": kwp(order["watt"]),
        "original_cost_thb": None,
        "book_value_usd": None,
        "commencement_date": None,
        "tenor_months": order["term_months"],
        "monthly_excl_vat_thb": None,
        "monthly_incl_vat_thb": order["monthly_rate_incl_vat"],
        "total_lease_incl_vat_thb": total_lease(
            order["monthly_rate_incl_vat"], order["term_months"]
        ),
        "age_years": None,
        "origin": "approved",
    }


def loan_book():
    """The sheet's cohort first, then anything approved in this run, renumbered
    so the list reads as one book rather than two.

    An approval whose order is no longer served is skipped, never dereferenced:
    the old positional keys could point at a row a re-sync removed, and a 500 on
    the loan book is not an honest way to say "this lease has no order"."""
    entries = [dict(e) for e in _DATA["loan_book"]]
    nxt = max((e["no"] for e in entries), default=0)
    lookup = {_key(o): o for o in _all_rows()}
    skipped = []
    for key in sorted(_approved_store.for_current()):
        order = lookup.get(key)
        if order is None:
            skipped.append(key)
            continue
        nxt += 1
        entries.append(as_loan_book_entry(order, nxt))
    _loan_book["skipped"] = skipped
    return entries


def loan_book_skipped():
    """Approvals the book could not render — served so a screen can say why."""
    return list(_loan_book.get("skipped") or [])


_loan_book = {}


def approve(no, by):
    """Move an order to Done. Returns (entry, error_code)."""
    order = get(no)
    if order is None:
        return None, "not_found"
    key = _key(order)
    approved = _approved_store.for_current()
    if key in approved:
        return None, "already_approved"
    # An order whose loan was declined has no business entering a lease book.
    if (order.get("loan_status") or "").lower() not in {"approved", "cash"}:
        return None, "loan_not_approved"
    approved[key] = {"by": by, "at": _DATA["source"].get("as_of", "this run")}
    return get(no), None


def sheet_source():
    """The sheet rung, named as itself. `source()` answers "which rung is serving the
    ORDERS list"; a caller whose rows come from the sheet whatever the orders rung is
    doing must ask this instead, or it will print a system that supplied none of them.
    """
    return {**_DATA["source"], "data_source": "SHEET"}


def source():
    """The orders rung — the sheet, since the Odoo sale.order rows went (2026-09-25)."""
    return sheet_source()

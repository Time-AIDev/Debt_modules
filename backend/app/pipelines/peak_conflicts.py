"""D02 / Q7 (feedback-r2 TASK-206): where PEAK and the crm.lead record disagree.

Pure: an invoice row and the served identity in, one row per comparable field out.
A field either side does not carry is SKIPPED, never guessed; a field both carry the
same value is `same: True`. The compare is only ever read — nothing writes to Odoo.
"""
import re
from decimal import Decimal, InvalidOperation

from .. import orders
from . import peak_match

FIELDS = ("customer_name", "volt_id", "product", "system_size_kwp")

# PEAK writes the system size inside the product's own name ("… _6.25kWp").
_KWP = re.compile(r"(\d+(?:\.\d+)?)\s*k[Ww]p?")


def _product_of(group):
    text = str(group or "").strip().lower()
    if "cash" in text:
        return "CASH"
    if "leas" in text:
        return "LEASE"
    return None


def _kwp(text):
    m = _KWP.search(str(text or ""))
    if not m:
        return None
    try:
        return str(Decimal(m.group(1)).quantize(Decimal("0.01")))
    except InvalidOperation:
        return None


def _head(value):
    """The identifying head of a volt id or a customer number, or None. A served
    volt id is composite ("VL0010158_Name_…_VOLT"), so the first underscore's token
    is the head; the code ladder's own repairs apply after that."""
    text = str(value or "").strip()
    if not text:
        return None
    token = text.split("_")[0].strip()
    parts = peak_match.code_parts(token)
    return parts[0] if parts else token.upper()


def _same_name(peak_name, identity):
    if not peak_name:
        return None
    want = peak_match.normalise_name(peak_name)
    for mine in (identity.get("name_th"), identity.get("name_roman")):
        if mine and peak_match.normalise_name(mine) == want:
            return True
    return False


def compare(invoice, identity):
    """One row per comparable field, in FIELDS order:
    {"field", "odoo_value", "peak_value", "same"}."""
    identity = identity or {}
    out = []

    peak_name = invoice.get("customer_name")
    if peak_name is not None and (identity.get("name_th") or identity.get("name_roman")):
        same = _same_name(peak_name, identity)
        out.append({"field": "customer_name", "odoo_value": identity.get("name_th") or identity.get("name_roman"),
                    "peak_value": peak_name, "same": bool(same)})

    peak_code = _head(invoice.get("contact_code") or invoice.get("reference"))
    if peak_code:
        mine = {_head(identity.get("volt_id")), str(identity.get("customer_no") or "").strip() or None}
        out.append({"field": "volt_id", "odoo_value": identity.get("volt_id") or identity.get("customer_no"),
                    "peak_value": peak_code, "same": peak_code in mine})

    group = str(invoice.get("product_group") or "").strip().lower()
    peak_product = _product_of(group)
    if peak_product and identity.get("product"):
        out.append({"field": "product", "odoo_value": identity.get("product"),
                    "peak_value": peak_product, "same": peak_product == str(identity.get("product")).upper()})

    peak_kwp = _kwp(invoice.get("product_name"))
    order = identity.get("order") or {}
    odoo_kwp = orders.kwp(order.get("watt"))
    if peak_kwp and odoo_kwp:
        out.append({"field": "system_size_kwp", "odoo_value": odoo_kwp,
                    "peak_value": peak_kwp, "same": peak_kwp == odoo_kwp})
    return out

"""crm.lead rows into book-shaped records. Pure: no clock, no network, no database.

Everything this module decides comes from the Rules object it is handed. When a rule
is missing it says so in the verdict rather than choosing for itself — an unmapped
value that lands quietly is indistinguishable from one somebody wrote a rule for.
"""
import re
from decimal import Decimal, InvalidOperation

from .. import parsing
from ..crm_policy import won_only

MONTHS = {m.lower(): i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _text(value):
    """Odoo's JSON-RPC types as the text these helpers expect.

    An empty value comes back as the boolean False, not as "" or None, and a
    numeric field as a float. Every helper below took a string until the first live
    run died on `re.sub` with a float — so the coercion happens once, here, rather
    than at seven call sites that would each have to remember.
    """
    if value is None or value is False:
        return ""
    if value is True:
        return "true"
    return str(value)


def as_date(value):
    """A date cell as YYYY-MM-DD, or None when blank — DAY FIRST, through the one
    shared parser (parsing.day_first_date). A value that is not a real calendar date
    raises ValueError: normalise refuses that lead by its Odoo id rather than landing
    an impossible date that fails the whole run."""
    parsed = parsing.day_first_date(_text(value))
    return parsed.isoformat() if parsed else None


def as_month(value):
    v = _text(value).strip()
    if not v:
        return None
    m = re.match(r"^(\d{4})-(\d{2})$", v)
    if m:
        return "%s-%s" % m.groups()
    m = re.match(r"^(\d{1,2})/(\d{2})$", v)
    if m:
        return "%04d-%02d" % (int(m.group(2)) + 2000, int(m.group(1)))
    m = re.match(r"^([A-Za-z]{3})[a-z]* (\d{4})$", v)
    if m and m.group(1).lower() in MONTHS:
        return "%s-%02d" % (m.group(2), MONTHS[m.group(1).lower()])
    return None


def phone_key(value):
    """Last nine digits: 0925423597 and +66 92 542 3597 are one number."""
    d = re.sub(r"\D", "", _text(value))
    return d[-9:] if len(d) >= 9 else ""


def lead_phone(row):
    """The first of phone / mobile that is a real number, or None — a "-" in phone
    must not hide a good mobile."""
    for value in (row.get("phone"), row.get("mobile")):
        if phone_key(value):
            return value
    return None


def as_money(value):
    m = re.sub(r"[^\d.]", "", _text(value))
    try:
        return Decimal(m).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def translate(field, value, rules):
    """(translated, was_mapped). An unmapped value is passed through — title-cased
    when it is snake_case — and `was_mapped=False` puts it in the run report.

    The flag is raised for ANY value the table does not list, not only snake_case
    ones. The first live run reported zero unmapped values across 34,336 leads,
    which looked like complete coverage and was actually a hole: a plain-word stage
    such as "Qualified" fell out of the snake_case branch and was reported as
    though somebody had written a rule for it. A field with no rows in the table at
    all is not a missing rule — nothing claims to translate it.
    """
    if value in (None, "", False):
        return value, True
    mapped = rules.vocab_for(field, value)
    if mapped is not None:
        return mapped, True
    if not any(row["Field"] == field for row in rules.vocab):
        return value, True
    if "_" in str(value):
        return " ".join(w.capitalize() for w in str(value).split("_")), False
    return value, False


# The shapes Odoo and the sheet actually hold, counted over 26,110 real volt_ids on
# 2026-09-11: VL/VC (2,171), VRL/VRC (62), the bare 11-digit CRM id (363), and the
# sheet's own <crm id>_<name>_<epc> long form.
VOLT_SHEET_SHAPE = re.compile(r"^\d{6,}(_|$)")
VOLT_ODOO_SHAPE = re.compile(r"^V[A-Z]{1,2}\d{4,}$", re.I)

# Odoo writes the literal "New" into volt_id until an id is minted — 23,514 of the
# 34,338 leads on the first live run. It is a placeholder, not a bad id, so it is
# treated as NO id: the lead still lands if it has a phone, and is refused for
# having no identity at all if it does not. Rejecting it as unshaped threw away 70%
# of the book over a value that was never an identifier.
PLACEHOLDER_VOLT_IDS = {"new", "false", "-", "n/a"}


def clean_volt_id(value):
    """The volt_id, or "" when what is there is a placeholder rather than an id."""
    text = _text(value).strip()
    return "" if text.lower() in PLACEHOLDER_VOLT_IDS else text


def volt_stem(volt_id):
    """The identifying head: 99999000032 out of 99999000032_Thitipawee_.._IPW, and
    VL0000143 out of itself. crm.lead.volt_id holds BOTH shapes, so an exact match
    finds far fewer rows than exist — 0 of 58 against this key's 58 of 58."""
    return _text(volt_id).strip().split("_")[0].strip().upper()


def rejection_for(row, seen, rules):
    """The §5 rule that refuses this row, or None. `seen` holds the volt_stems already
    taken in this run; a repeat is named duplicate_volt_id, and normalise() then keeps
    the NEWER lead (rules file §5: later row wins, earlier reported).

    A lead with no volt_id needs a phone to be anyone, and its Odoo id to be keyed —
    never its phone number (2026-09-25)."""
    volt_id = clean_volt_id(row.get("volt_id"))
    if not volt_id and not (lead_phone(row) and _text(row.get("id")).strip()):
        return "no_identity"
    if volt_id and not (VOLT_SHEET_SHAPE.match(volt_id) or VOLT_ODOO_SHAPE.match(volt_id)):
        return "unshaped_volt_id"
    if volt_id and volt_stem(volt_id) in seen:
        return "duplicate_volt_id"
    return None


def eligibility_rejection(row):
    """Defensive copy of the Odoo domain filter.

    The source filter keeps the transfer small; this check makes a file replay or a
    misconfigured integration unable to land a lead outside the approved book.
    Reasons are mutually exclusive so the run receipt counts reconcile.
    """
    if _text(row.get("stage_name")).strip() != "Won":
        return "not_won"
    if won_only():
        return None
    if not _text(row.get("epc_start_date")).strip():
        return "install_start_missing"
    if not _text(row.get("epc_end_date")).strip():
        return "install_end_missing"
    return None


# The §2 rows whose Odoo value needs a shape change on the way in. Everything else is
# copied across as the rules file's field_map says.
DATE_FIELDS = ("submitted_date", "contract_signed_date", "epc_start_date", "epc_end_date")
MONTH_FIELDS = ("epc_start_month_year",)
VOCAB_FIELDS = ("stage_name", "connection_type", "com_status")
WATT_SCALE = 1000            # §2: Odoo writes kW where the sheet writes W


def _label(value):
    """A many2one arrives as "70|North - Piyabud"; the label is what a person reads."""
    if isinstance(value, (list, tuple)):
        # A raw JSON-RPC many2one is [id, label]; the CSV door renders it "id|label".
        return str(value[1]).strip() if len(value) > 1 and value[1] else ""
    text = _text(value)
    return text.split("|", 1)[1].strip() if "|" in text else text


def mask_phone(phone):
    digits = re.sub(r"\D", "", _text(phone))
    if len(digits) < 4:
        return "xxx" if digits else None
    return "%sx-xxx-%s" % (digits[:2], digits[-4:])


def mask_email(email):
    email = _text(email)
    if "@" not in email:
        return None
    local, _, domain = email.partition("@")
    return "%s•••@%s" % (local[:1], domain)


def normalise(rows, rules):
    """(records, verdicts). Pure — `rows` is never mutated.

    A record is the landing.customer shape plus `reason` and a nested `order`. Every
    record carries reason "no money row in Odoo": crm.lead holds a sales quote at most
    (dp_amount, dp_percent, and monthly_rate — which is the term in months), so those
    ride as odoo_* keys to read, never as a number anybody bills.

    Every verdict names its lead's Odoo id (`odoo_id`); a landed verdict carries the
    record's key. Two leads on one volt_stem: the pull is ordered by Odoo id, so the
    later one is the newer lead and takes the earlier one's place — the earlier is
    reported `duplicate_volt_id` under its own Odoo id.
    """
    records, verdicts, seen = [], [], {}      # seen: stem -> (record index, verdict index)
    for row in rows:
        volt_id = clean_volt_id(row.get("volt_id"))
        odoo_id = row.get("id")
        rule = eligibility_rejection(row) or rejection_for(row, seen, rules)
        if rule in (None, "duplicate_volt_id"):
            try:
                dates = {field: as_date(row.get(field)) for field in DATE_FIELDS}
            except ValueError:
                rule = "date_unreadable"
        if rule and rule != "duplicate_volt_id":
            verdicts.append({"volt_id": volt_id, "verdict": "rejected",
                             "rule": rule, "unmapped": [], "odoo_id": odoo_id})
            continue
        unmapped = []
        translated = {}
        for field in VOCAB_FIELDS:
            value, was_mapped = translate(field, row.get(field), rules)
            translated[field] = value
            if not was_mapped:
                unmapped.append([field, row.get(field)])

        phone = lead_phone(row)
        name = _label(row.get("contact_name"))
        watt = as_money(row.get("inverter_kw"))
        order = {
            "crm_id": odoo_id,
            "odoo_lead_name": _text(row.get("name")).strip() or None,
            "order_type": "Leasing" if _text(row.get("order_type")).lower() == "leasing" else "Cash",
            "order_status": translated["stage_name"],
            "crm_status": _text(row.get("stage_name")).strip(),
            "loan_status": None,
            "phase": translated["connection_type"],
            "com_status": translated["com_status"],
            "epc": _text(row.get("epc")) or None,
            "watt": int(watt * WATT_SCALE) if watt else None,
            "province": _text(row.get("install_province")) or None,
            "postal_code": _text(row.get("zip")) or None,
            "sales_lead": _label(row.get("user_id")) or None,
            # The quote the lead carries, for reading only (2026-09-25): odoo_* keys,
            # never the sheet's own dp_amount/term, which the invoice pipeline bills
            # from. Odoo's `monthly_rate` is the term in months (60, 48 …), not baht.
            "odoo_dp_amount": str(dp) if (dp := as_money(row.get("dp_amount"))) else None,
            "odoo_dp_pct": str(pct) if (pct := as_money(row.get("dp_percent"))) else None,
            "odoo_term": int(term) if (term := as_money(row.get("monthly_rate"))) else None,
            "source_ref": [],
            "data_source": "ODOO",
        }
        order.update(dates)
        for field in MONTH_FIELDS:
            order[field] = as_month(row.get(field))
        order["submit_date"] = order.pop("submitted_date")

        key = volt_id or "lead-%s" % _text(odoo_id).strip()
        record = {
            "volt_id": key,
            "customer_no": volt_stem(volt_id) or None,
            "name_roman": None,
            "name_th": name or None,
            "epc": _text(row.get("epc")) or None,
            "product": "LEASE" if order["order_type"] == "Leasing" else "CASH",
            "sales_lead": order["sales_lead"],
            "phone_masked": mask_phone(phone),
            "phone_e164": phone,
            "email_masked": mask_email(row.get("email_from")),
            "line_id": _text(row.get("line_id")).strip() or None,
            "meta_id": _text(row.get("meta_id")).strip() or None,
            "source_refs": [],
            "reason": "no money row in Odoo",
            "order": order,
        }
        if rule == "duplicate_volt_id":
            at, earlier = seen[volt_stem(volt_id)]
            verdicts[earlier] = dict(verdicts[earlier], verdict="rejected",
                                     rule="duplicate_volt_id", unmapped=[])
            records[at] = record
        else:
            at = len(records)
            records.append(record)
        verdicts.append({"volt_id": key, "verdict": "landed", "rule": None,
                         "unmapped": unmapped, "odoo_id": odoo_id})
        if volt_id:
            seen[volt_stem(volt_id)] = (at, len(verdicts) - 1)
    return records, verdicts

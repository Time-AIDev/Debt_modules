#!/usr/bin/env python3
"""Pull the nine debt-relevant model groups out of Odoo UAT as CSV.

Read-only, and deliberately not part of the app: this is a bench tool for looking
at what Odoo actually holds (the 2026-09-11 census), not a second ingest path. The
app's own Odoo rung is app/integrations/odoo.py and stays the only thing that
writes into the landing schema.

Three rules the shape of the output follows:

  masking     phone, mobile, fax and email go through the SAME masks the importer
              uses (C5/R12: "phone, email masked; names, VOLT IDs, amounts,
              statuses and notes kept"). Everything else lands as Odoo returns it,
              which is why data/odoo is gitignored — addresses and tax ids are in
              there in the clear.
              UNMASKED_MODELS is the deliberate exception: crm.lead and sale.order
              land raw, because the point of those two files is matching Odoo's
              contacts against the sheet's own rows, and a masked number matches
              nothing. Those two files therefore hold real phone numbers and real
              email addresses. data/odoo is gitignored; keep it that way, and do
              not copy those two files out of it.
  binaries    dropped. meter_picture and customer.document.file are base64 blobs
              that would each dwarf the whole rest of the file.
  relations   a many2one becomes "id|label" in one column, an x2many a space-
              separated id list. One column per Odoo field, so the CSV header is
              the model's schema and nothing is silently flattened away.

Models over the FULL_FIELD_CAP get a curated field list instead of all of them:
res.partner has ~150 fields and 128k rows, and the product of those two is a file
nobody opens twice.

    ./scripts/pull_odoo_csv.py                 # everything, into data/odoo/
    ./scripts/pull_odoo_csv.py res.partner     # just these models
"""
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.integrations import odoo  # noqa: E402
from app.pipelines.crm_lead import mask_email, mask_phone  # noqa: E402

OUT = ROOT / "data" / "odoo"
PAGE = 500
FULL_FIELD_CAP = 5000      # rows above this take a curated field list

# The nine rows of the census table. Order is the order they are written.
MODELS = [
    "renewable.energy.order",
    "invoice.installment.line",
    "customer.document",
    "account.move",
    "account.move.line",
    "account.bank.statement.line",
    "res.partner",
    "crm.lead",
    "volt.lease.payment",
    "volt.lease.line",
    "sale.order",
]

# Only consulted for models past FULL_FIELD_CAP. Names are intersected with what
# the instance actually declares, so a field missing on this Odoo is skipped
# rather than failing the pull.
CURATED = {
    "res.partner": ["name", "display_name", "ref", "vat", "is_company", "parent_id",
                    "company_type", "phone", "mobile", "email", "street", "street2",
                    "city", "state_id", "zip", "country_id", "category_id", "user_id",
                    "customer_rank", "supplier_rank", "active", "create_date", "write_date"],
    # Widened 2026-09-11 from a generic lead list to the sheet's own "x" tab: 33 of
    # its 47 columns exist on crm.lead, and a field list that omitted them made the
    # two files impossible to compare. renewable_energy_order_id is in here because
    # it is the link from a lead to the 87-row order book.
    "crm.lead": ["name", "volt_id", "partner_id", "contact_name", "last_name",
                 "partner_name", "email_from", "phone", "mobile", "type", "stage_id",
                 "stage_name", "ren_stage", "user_id", "team_id", "source_id", "referred",
                 "order_type", "submitted_date", "contract_signed_date", "description",
                 "inverter_brand", "inverter_type", "inverter_kw", "battery_watt",
                 "dp_percent", "dp_amount", "monthly_rate", "monthly_electric_bill",
                 "payment_term_installment_id", "installment_period_id", "g_drive",
                 "energy_bill", "panel_watt", "connection_type", "epc", "epc_start_date",
                 "epc_start_month_year", "epc_end_date", "install_province",
                 "install_province_id", "zip", "street", "city", "state_id", "country_id",
                 "meter_owner", "com_status", "cosigner_id", "site_coordinates",
                 "renewable_energy_order_id", "expected_revenue", "probability",
                 "date_deadline", "date_closed", "won_status", "lost_reason_id",
                 "priority", "active", "create_date", "write_date"],
}

SKIP_TYPES = {"binary"}
# Chatter plumbing: present on almost every model, interesting on none of them.
SKIP_PREFIX = ("message_", "activity_", "rating_", "website_message", "my_activity",
               "access_", "__last_update")


def fields_for(cfg, uid, model, count):
    declared = odoo._execute(cfg, uid, model, "fields_get", [],
                             {"attributes": ["string", "type", "store"]})
    if count > FULL_FIELD_CAP and model in CURATED:
        names = [f for f in CURATED[model] if f in declared]
    else:
        names = [f for f, meta in declared.items()
                 if meta.get("type") not in SKIP_TYPES and not f.startswith(SKIP_PREFIX)]
    if "id" not in names:
        names.insert(0, "id")
    dropped = [f for f, meta in declared.items() if meta.get("type") in SKIP_TYPES]
    return sorted(names, key=lambda f: (f != "id", f)), declared, dropped


# The two files whose whole job is matching against the sheet. See the docstring.
UNMASKED_MODELS = {"crm.lead", "sale.order"}


def render(model, field, value):
    """One Odoo value as one CSV cell. See the module docstring's `relations` rule."""
    if value is False or value is None:
        return ""
    if model not in UNMASKED_MODELS:
        if "email" in field:
            return mask_email(value) or ""
        if any(k in field for k in ("phone", "mobile", "fax")):
            return mask_phone(value) or ""
    if isinstance(value, (list, tuple)):
        if len(value) == 2 and isinstance(value[0], int) and isinstance(value[1], str):
            return "%d|%s" % (value[0], value[1])        # many2one
        return " ".join(str(v) for v in value)            # x2many ids
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return value


PROBE_CAP = 2000       # above this, a field-by-field probe costs more than it is worth


def usable_fields(cfg, uid, model, names, count):
    """Which of `names` Odoo will actually read, one field at a time.

    A custom computed field can raise on a multi-record read while every other
    field is fine — sale.order on this instance answers "Expected singleton:
    sale.order(100, 101, 102, 103, 104)". Dropping the whole model over one broken
    compute would lose the readable schema with it, and hand-guessing a field list
    would silently decide what matters. So the offender is named and the rest lands.
    """
    good, bad = [], {}
    for field in names:
        try:
            odoo._execute(cfg, uid, model, "search_read", [[]],
                          {"fields": [field], "limit": min(count, PAGE), "order": "id"})
            good.append(field)
        except Exception as exc:
            bad[field] = str(exc).splitlines()[0][:120]
    return good, bad


def pull(cfg, uid, model):
    count = odoo._execute(cfg, uid, model, "search_count", [[]])
    names, declared, dropped = fields_for(cfg, uid, model, count)
    unreadable = {}
    rows, offset = [], 0
    while offset < count:
        try:
            page = odoo._execute(cfg, uid, model, "search_read", [[]],
                                 {"fields": names, "limit": PAGE, "offset": offset,
                                  "order": "id"})
        except Exception:
            if unreadable or count > PROBE_CAP:
                raise
            print("    probing %d fields one by one" % len(names), file=sys.stderr, flush=True)
            names, unreadable = usable_fields(cfg, uid, model, names, count)
            print("    %d readable, %d refused: %s" % (
                len(names), len(unreadable), ", ".join(unreadable) or "-"),
                file=sys.stderr, flush=True)
            continue
        if not page:
            break
        rows.extend(page)
        offset += len(page)
        print("    %s %d/%d" % (model, len(rows), count), file=sys.stderr, flush=True)
    path = OUT / ("%s.csv" % model)
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(names)
        for row in rows:
            writer.writerow([render(model, f, row.get(f)) for f in names])
    return {"model": model, "label": declared.get("id", {}).get("string", ""),
            "records_in_odoo": count, "rows_written": len(rows),
            "columns": len(names), "curated_fields": model in CURATED and count > FULL_FIELD_CAP,
            "binary_fields_dropped": dropped, "unreadable_fields": unreadable,
            "file": path.name,
            "bytes": path.stat().st_size}


def main(argv):
    wanted = argv[1:] or MODELS
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = odoo._config()
    uid = odoo._login(cfg)
    manifest = {"source": {"system": "Odoo UAT", "url_env": "ODOO_URL", "db_env": "ODOO_DB",
                           "login_uid": uid,
                           "pulled_at": datetime.now(timezone.utc).isoformat()},
                "pii": "phone, mobile, fax and email masked at pull EXCEPT in %s, "
                       "which are raw; names, ids, addresses, tax ids and amounts as "
                       "Odoo returned them" % ", ".join(sorted(UNMASKED_MODELS)),
                "unmasked_models": sorted(UNMASKED_MODELS),
                "models": []}
    for model in wanted:
        print("  %s" % model, flush=True)
        try:
            manifest["models"].append(pull(cfg, uid, model))
        except Exception as exc:
            print("    REFUSED: %s" % str(exc).splitlines()[0][:80], file=sys.stderr)
            manifest["models"].append({"model": model, "error": str(exc).splitlines()[0][:200]})
    # A partial run describes only the models it pulled. Overwriting would leave the
    # manifest claiming the folder holds three CSVs when it holds eleven, so an
    # earlier run's entries are kept and only the re-pulled ones replaced.
    previous = {}
    if (OUT / "manifest.json").is_file():
        try:
            previous = {m["model"]: m for m in
                        json.loads((OUT / "manifest.json").read_text())["models"]}
        except (ValueError, KeyError, OSError):
            previous = {}
    previous.update({m["model"]: m for m in manifest["models"]})
    manifest["models"] = [previous[m] for m in MODELS if m in previous]
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    total = sum(m.get("rows_written", 0) for m in manifest["models"])
    print("\n%d models, %d rows, into %s" % (len(manifest["models"]), total, OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

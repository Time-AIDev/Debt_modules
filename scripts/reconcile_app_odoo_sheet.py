#!/usr/bin/env python3
"""Three-way customer consistency check: app book vs Odoo crm.lead vs the sheet.

Reads the served book (Today and the workbook directory) from the landing schema,
the live Odoo crm.lead census (or the landed ODOO rows with --from-landing), and the
authorised master sheet export, then classifies every served customer by the first
key that matches:

    LINK_OK          the app already serves a working Odoo deep link
    LINK_WRONG       the app serves an Odoo link whose id is not in the census
    MATCHED_NO_LINK  an active lead matches on a strong key (volt id / customer no /
                     phone) but the served row carries no Odoo link — the merge gap
    ARCHIVED_NO_LINK the lead that matches is archived in Odoo, so the active-only
                     pull can neither land nor link it
    AMBIGUOUS        several active leads share the only strong key
    NAME_CANDIDATE   only a name (or name-prefix) matches; never auto-merged,
                     listed for a human (Odoo has leads whose name and volt_id
                     disagree about the VOLT id)
    APP_ONLY         no lead found by any key

Cherry-pick (2026-10-01, Jessada Nonmaha): Odoo crm.lead 163354 is active and holds
volt_id 28005118095; the served SHEET row must report LINK_OK with that id once the
crm.lead merge has recorded the link. A LINK_WRONG or a missing link for that case is
a regression.

Read-only against Odoo. The report goes to backend/var/reconciliation/ (gitignored —
it carries customer names and phones).

    backend/.venv/bin/python scripts/reconcile_app_odoo_sheet.py
    backend/.venv/bin/python scripts/reconcile_app_odoo_sheet.py --from-landing --limit 200
    backend/.venv/bin/python scripts/reconcile_app_odoo_sheet.py --case jessada
"""
import argparse
import importlib.util
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

OUT_DIR = ROOT / "backend" / "var" / "reconciliation"
SHEET = ROOT / "backend" / "var" / "master_sheet.txt"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sheet_module():
    return _load("compare_crm_to_sheet", ROOT / "scripts" / "compare_crm_to_sheet.py")


def stem(value):
    """The identifying head of a VOLT id: 28005118095 out of 28005118095_Jessada_….VOLT."""
    head = (value or "").strip().split("_")[0].strip().upper()
    return head if head else ""


def phone9(value):
    digits = re.sub(r"\D", "", value or "")
    return digits[-9:] if len(digits) >= 9 else ""


def norm_name(value):
    return re.sub(r"\s+", " ", (value or "").replace("_", " ").strip().lower())


# --- Odoo census ---------------------------------------------------------------

ODOO_FIELDS = ("id", "name", "volt_id", "contact_name", "last_name", "partner_name",
               "phone", "mobile", "stage_name", "active", "com_status")


def odoo_live():
    from app.integrations import odoo
    config = odoo._config()
    uid = odoo._login(config)
    leads, last_id = [], 0
    while True:
        page = odoo._execute(config, uid, "crm.lead", "search_read",
                             [[("id", ">", last_id)]],
                             {"fields": list(ODOO_FIELDS), "limit": 500, "order": "id",
                              "context": {"active_test": False}})
        if not page:
            break
        leads.extend(page)
        last_id = page[-1]["id"]
        if len(page) < 500:
            break
    return leads


def odoo_from_landing():
    """The last pull's ODOO rows, retired included — a census of what Odoo returned
    the last time the app looked, without a network call. The pull only sees active
    leads, so `active` is unknown here (None), never guessed from retirement (a row
    retires because the SHEET took the customer over, not because Odoo archived it)."""
    from app import db
    from sqlalchemy import text
    with db.engine().connect() as conn:
        rows = conn.execute(text(
            "select o.crm_id, c.volt_id, c.name_th, c.name_roman, c.phone_e164 "
            "from landing.customer c "
            "join landing.\"order\" o on o.volt_id = c.volt_id and o.data_source = 'ODOO' "
            "where c.data_source = 'ODOO'")).mappings().all()
    leads, seen = [], set()
    for row in rows:
        raw_id = str(row["crm_id"] or "")
        if not raw_id.isdigit() or int(raw_id) in seen:
            continue
        seen.add(int(raw_id))
        leads.append({"id": int(raw_id), "name": row["name_th"] or row["name_roman"],
                      "volt_id": row["volt_id"], "contact_name": row["name_th"],
                      "last_name": None, "partner_name": None, "phone": row["phone_e164"],
                      "mobile": None, "stage_name": None,
                      "active": None, "com_status": None})
    return leads


def index_leads(leads):
    """Buckets per key. `stem`/`volt`/`phone` are strong keys; a name that merely
    starts with the sheet's VOLT id is a candidate, not a match (Odoo carries leads
    whose `name` holds one VOLT id and whose `volt_id` field holds another — the
    reconciliation must show that conflict, not silently pick a side)."""
    by_id, by_volt, by_stem, by_phone, by_name, by_name_stem = {}, {}, {}, {}, {}, {}
    for lead in leads:
        by_id[lead["id"]] = lead
        volt = str(lead.get("volt_id") or "").strip()
        if volt and volt.lower() not in ("new", "false"):
            by_volt.setdefault(volt.upper(), []).append(lead)
            by_stem.setdefault(stem(volt), []).append(lead)
        key = stem(lead.get("name"))
        if key:
            by_name_stem.setdefault(key, []).append(lead)
        p = phone9(lead.get("phone") or lead.get("mobile"))
        if p:
            by_phone.setdefault(p, []).append(lead)
        for value in (lead.get("name"), lead.get("contact_name"), lead.get("last_name"),
                      lead.get("partner_name")):
            key = norm_name(value)
            if key:
                by_name.setdefault(key, []).append(lead)
    return {"id": by_id, "volt": by_volt, "stem": by_stem, "phone": by_phone,
            "name_stem": by_name_stem, "name": by_name}


def _pick(bucket):
    """(lead, ambiguous) preferring the one active lead — an archived duplicate of a
    live lead must not make the customer ambiguous."""
    active = [l for l in bucket if l.get("active")]
    if len(active) == 1:
        return active[0], False
    if len(active) > 1:
        return active[0], True
    if len(bucket) == 1:
        return bucket[0], False
    return bucket[0], True


def match_lead(index, customer):
    """(lead, matched_by, ambiguous, weak). Weak means a name-only candidate: worth a
    human look, never a merge."""
    strong = (("VOLT_ID", index["volt"].get((customer["volt_id"] or "").upper())),
              ("STEM", index["stem"].get(stem(customer["volt_id"]) or
                                         stem(customer["customer_no"]))),
              ("PHONE", index["phone"].get(phone9(customer["phone_e164"]))))
    for key, bucket in strong:
        if bucket:
            lead, ambiguous = _pick(bucket)
            return lead, key, ambiguous, False
    for key, bucket in (("NAME_STEM", index["name_stem"].get(
                            stem(customer["volt_id"]) or stem(customer["customer_no"]))),
                        ("NAME", index["name"].get(norm_name(customer["display_name"])))):
        if bucket:
            lead, ambiguous = _pick(bucket)
            return lead, key, ambiguous, True
    return None, None, False, False


# --- sheet census --------------------------------------------------------------

def sheet_index():
    if not SHEET.is_file():
        return None
    compare = _sheet_module()
    _header, rows = compare.sheet_rows()
    by_stem, by_phone, by_name = {}, {}, {}
    for row in rows:
        for key in (stem(row.get("Volt ID")), stem(row.get("Odoo ID"))):
            if key:
                by_stem.setdefault(key, row)
        p = phone9(row.get("Phone") or row.get("Secondary Phone"))
        if p:
            by_phone.setdefault(p, row)
        key = norm_name(" ".join(x for x in (row.get("First Name"), row.get("Last Name")) if x))
        if key:
            by_name.setdefault(key, row)
    return {"stem": by_stem, "phone": by_phone, "name": by_name, "rows": len(rows)}


def sheet_match(index, customer):
    if not index:
        return None
    for key, bucket in (("STEM", index["stem"].get(stem(customer["volt_id"]) or
                                                  stem(customer["customer_no"]))),
                        ("PHONE", index["phone"].get(phone9(customer["phone_e164"]))),
                        ("NAME", index["name"].get(norm_name(customer["display_name"])))):
        if bucket:
            return key
    return None


# --- app census ----------------------------------------------------------------

def app_customers():
    """Every customer the two screens list, once."""
    from app import journey
    from app.routers.today import _customer_odoo_crm
    from app import today as today_domain

    today_uids = {item["customer"]["uid"] for item in today_domain.build()["items"]}
    rows, seen = [], set()
    for customer in journey.book_customers() + journey.identity_customers():
        if customer.uid in seen:
            continue
        seen.add(customer.uid)
        source = getattr(customer, "data_source", None) or {}
        identity = source.get("identity") if isinstance(source, dict) else source
        link = _customer_odoo_crm(customer)
        rows.append({
            "uid": customer.uid,
            "screens": (["today"] if customer.uid in today_uids else []) + ["workbook"],
            "customer_no": getattr(customer, "customer_no", None),
            "volt_id": getattr(customer, "volt_id", None),
            "display_name": getattr(customer, "display_name", None),
            "phone_e164": getattr(customer, "phone_e164", None),
            "identity": identity,
            "odoo_crm": link,
        })
    return rows, len(today_uids)


def classify(customer, leads, sheet):
    lead, matched_by, ambiguous, weak = match_lead(leads, customer)
    link_id = (customer.get("odoo_crm") or {}).get("record_id")
    if link_id and link_id not in leads["id"]:
        klass = "LINK_WRONG"
    elif link_id:
        klass = "LINK_OK"
    elif lead and weak:
        klass = "NAME_CANDIDATE"
    elif lead and ambiguous:
        klass = "AMBIGUOUS"
    elif lead and lead.get("active") is False:
        # The app's pull reads active leads only, so an archived lead cannot link:
        # the customer still exists in Odoo, it is simply closed there.
        klass = "ARCHIVED_NO_LINK"
    elif lead:
        klass = "MATCHED_NO_LINK"
    else:
        klass = "APP_ONLY"
    return {
        **customer,
        "class": klass,
        "matched_by": matched_by or ("LINK" if link_id else None),
        "odoo_lead_id": link_id or (lead["id"] if lead else None),
        "odoo_stage": (lead or {}).get("stage_name"),
        "odoo_active": (lead or {}).get("active"),
        "sheet_match": sheet_match(sheet, customer),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-landing", action="store_true",
                        help="use the last pull's landed ODOO rows, no network")
    parser.add_argument("--limit", type=int, default=None,
                        help="sample this many Today rows (workbook identities follow)")
    parser.add_argument("--case", default="jessada",
                        help="name fragment to print in full (default: jessada)")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    from app import db
    if not db.configured():
        print("DATABASE_URL is not set — the reconciler reads the served book from "
              "the landing schema", file=sys.stderr)
        return 2

    leads = odoo_from_landing() if args.from_landing else odoo_live()
    index = index_leads(leads)
    sheet = sheet_index()
    customers, today_total = app_customers()
    if args.limit:
        today_kept = [c for c in customers if "today" in c["screens"]][:args.limit]
        kept_uids = {c["uid"] for c in today_kept}
        customers = [c for c in customers
                     if "today" not in c["screens"] or c["uid"] in kept_uids]

    rows = [classify(c, index, sheet) for c in customers]
    classes = Counter(r["class"] for r in rows)
    sheets = Counter("SHEET_" + (r["sheet_match"] or "MISSING") for r in rows)

    needle = (args.case or "").strip().lower()
    cherry = [r for r in rows if needle and needle in (r["display_name"] or "").lower()]

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "odoo_source": "landing" if args.from_landing else "live",
        "counts": {
            "today": today_total,
            "served_customers": len(rows),
            "odoo_leads": len(leads),
            "sheet_rows": (sheet or {}).get("rows", 0),
        },
        "classes": dict(classes),
        "sheet": dict(sheets),
        "version": "2026-10-01",
        "rows": rows,
        "cherry_pick": cherry,
    }
    path = Path(args.out) if args.out else OUT_DIR / ("app_odoo_sheet_%s.json"
                                                      % datetime.now().strftime("%Y%m%d-%H%M%S"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print("sources: Odoo %s (%d leads) · sheet %d rows · served %d (%d Today)"
          % (report["odoo_source"], len(leads), (sheet or {}).get("rows", 0),
             len(rows), today_total))
    for klass, count in sorted(classes.items(), key=lambda kv: (-kv[1], kv[0])):
        print("  %-14s %5d" % (klass, count))
    for klass, count in sorted(sheets.items(), key=lambda kv: (-kv[1], kv[0])):
        print("  %-14s %5d" % (klass, count))
    for row in cherry:
        print("\ncase: %s | %s | %s" % (row["display_name"], row["uid"], row["class"]))
        print("  volt_id=%s customer_no=%s identity=%s" % (row["volt_id"], row["customer_no"], row["identity"]))
        print("  odoo link=%s matched_by=%s lead=%s active=%s"
              % (row["odoo_crm"], row["matched_by"], row["odoo_lead_id"], row["odoo_active"]))
        print("  sheet=%s" % (row["sheet_match"] or "MISSING"))
    print("\nreport: %s" % path)

    if classes.get("LINK_WRONG"):
        print("\nFAIL: %d row(s) serve an Odoo deep link whose lead is not in the census"
              % classes["LINK_WRONG"], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

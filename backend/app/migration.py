"""Migration — REQ-INT-030..032. The run report and the gap list.

The book is built by app/book.py at seed time; this module reports on it: counts
by tab, reconciliation against the sheet's own pivots, the warnings, the rows
that could not become contracts (with the reason), and the gap list of orders
installed per their EPC dates but never flipped to Order-Done (⚠ I-12).

The export is truncated per tab, so the report says so rather than pretending a
sample is the book: `reconciled` is False whenever the imported count is short of
the sheet's own summary, and `truncated` names the blocks that hit the size cap.
"""
from datetime import date

from . import book
from . import imports as imports_domain
from .config import settings
from .integrations import odoo as odoo_client

TRUNCATION_ROW_CAP = 20  # a block cut at ~20 KB shows as very few rows for a wide tab


def _source_chain(report):
    """Delta-100 DS1: the four inbound rungs, ranked, each with its REAL state.

    Prototype 1020-1035 draws: 1 the sheet, 2 the manual file import, 3 Odoo
    crm.lead, 4 stale system data. Rungs 2 and 4 were previously omitted; they are
    served here from their own stores — the manual uploads in this session
    (imports.list_current) and the book's own capture date (book_source's
    captured_on, the same fact payment_position marks stale), never invented. The
    rung serving the work book is named by the book source's own name and marked
    `serving`.
    """
    source = report.get("source") or {}
    run = report.get("run") or {}
    serving_code = source.get("serving_code") or "SHEET"
    serving_name = source.get("serving_name") or source.get("spreadsheet") or "New Order Master"

    # 2 — the manual file import store (this session's own uploads).
    manual_runs = imports_domain.list_current()
    if manual_runs:
        last = manual_runs[-1]["run"]
        manual_state = ("สำรอง", "Fallback")
        manual_note_th = "ใช้เมื่อชีตหลักอ่านไม่ได้ · ครั้งล่าสุด %s" % (last.get("taken_at") or "—")
        manual_note_en = "Used when the main sheet is unreadable · last %s" % (last.get("taken_at") or "—")
    else:
        manual_state = ("ยังไม่มีไฟล์", "No file yet")
        manual_note_th = "ยังไม่มีการนำเข้าไฟล์ด้วยมือในเซสชันนี้"
        manual_note_en = "No manual file has been imported in this session"

    # 3 — Odoo crm.lead. The 2026-09-19 ruling made it the served book; the note
    # states the served slice and the standing fact that Odoo still carries no money,
    # so the money lenses show nothing rather than figures nobody billed.
    odoo = odoo_client.status()
    snapshot = odoo.get("snapshot") or {}
    serving_odoo = serving_code == "ODOO"
    if serving_odoo:
        odoo_state = ("ให้บริการอยู่", "Serving")
        odoo_note_th = "สมุดงานมาจาก Odoo crm.lead · แสดง %s จาก %s ราย (ที่เหลือยังไม่มี VOLT ID) · Odoo ไม่มียอดเงิน" % (
            source.get("served_customers", "—"), source.get("landed_customers", "—"))
        odoo_note_en = "The book is served from Odoo crm.lead · %s of %s rows (the rest have no VOLT id yet) · Odoo carries no money" % (
            source.get("served_customers", "—"), source.get("landed_customers", "—"))
    else:
        odoo_state = ("อ่านได้เท่านั้น", "Read-only") if odoo["configured"] else ("ยังไม่เชื่อมต่อ", "Not connected")
        odoo_note_th = "ไม่มียอดเงิน ไม่ถึงเคส · ใช้เทียบชื่อเท่านั้น"
        odoo_note_en = "No money amounts, not case-level · name matching only"
        if snapshot.get("synced_at"):
            odoo_note_th += " · ข้อมูลล่าสุด %s" % snapshot["synced_at"]
            odoo_note_en += " · last synced %s" % snapshot["synced_at"]

    # 4 — stale system data: the book's own capture date, judged by the same window
    # payment_position uses. A held fixture has no capture date, and that is served
    # as unknown — never as fresh and never as stale.
    captured_on = run.get("captured_on")
    stale = None
    if captured_on:
        try:
            stale = (settings.business_date - date.fromisoformat(str(captured_on)[:10])).days > settings.payment_position_stale_days
        except (TypeError, ValueError):
            stale = None
    if captured_on:
        stale_note_th = "หน้าจอจะแจ้งวันที่ของข้อมูล · ข้อมูล ณ %s" % captured_on
        stale_note_en = "The screen shows the data's date · data as of %s" % captured_on
    else:
        stale_note_th = "ไม่ทราบวันที่ของข้อมูลที่ค้างในระบบ — หน้าจอจะไม่แสดงวันที่ที่ไม่มีใครบันทึก"
        stale_note_en = "The age of the stale data is unknown — no date is shown that nobody recorded"

    def rung(rank, code, name, note_th, note_en, state_th, state_en, tone, serving,
             name_th=None, name_en=None):
        return {"rank": rank, "code": code, "name": name,
                "name_th": name_th or name, "name_en": name_en or name,
                "note_th": note_th, "note_en": note_en,
                "state_th": state_th, "state_en": state_en,
                "tone": tone, "serving": serving}

    return {
        "serving_code": serving_code,
        "serving_name": serving_name,
        # 2026-09-23 (build round 3): the Odoo import is the default source — it is the
        # served book since the 2026-09-19 ruling and the refetch runs on its own. The
        # sheet keeps its real state at rank 2 and reads "สำรอง" when it does not serve.
        "rungs": [
            rung(1, "ODOO_CRM_LEAD", "Odoo crm.lead", odoo_note_th, odoo_note_en,
                 odoo_state[0], odoo_state[1],
                 "current" if serving_odoo else "held", serving_odoo,
                 name_th="Odoo crm.lead", name_en="Odoo crm.lead"),
            rung(2, "SHEET", "%s (SHEET)" % serving_name if serving_code == "SHEET" else "New Order Master (SHEET)",
                 "ชีตหลักที่ทีมกรอกเอง" if serving_name else "ชีตหลัก",
                 "The team's own master sheet",
                 ("ให้บริการอยู่" if serving_code == "SHEET" else "สำรอง"),
                 ("Serving" if serving_code == "SHEET" else "Reserve"),
                 "current" if serving_code == "SHEET" else "pending", serving_code == "SHEET"),
            rung(3, "MANUAL_FILE", "ไฟล์ที่นำเข้าด้วยมือ", manual_note_th, manual_note_en,
                 manual_state[0], manual_state[1], "pending", serving_code == "MANUAL_FILE",
                 name_en="Manual file import"),
            rung(4, "STALE_SYSTEM", "ข้อมูลที่ค้างในระบบ", stale_note_th, stale_note_en,
                 "ทางเลือกสุดท้าย", "Last resort",
                 "overdue" if stale else "held", serving_code == "STALE_SYSTEM",
                 name_th="ข้อมูลที่ค้างในระบบ", name_en="Stale system data"),
        ],
    }


def run_report():
    customers, report = book.build()
    pivots = report.get("pivots") or {}
    counts = report.get("counts") or {}
    source = report.get("source") or {}
    imported_by_status = {
        "CURRENT": counts.get("LEASE/Current", 0), "LATE": counts.get("LEASE/Late", 0),
        "NPL": counts.get("LEASE/NPL", 0), "CLOSED": counts.get("LEASE/Closed", 0),
        "NOT_INSTALLED": counts.get("LEASE/Not Installed", 0),
    }
    sheet_by_status = {}
    for row in pivots.get("payment_status") or []:
        name = (row.get("payment_status") or "").replace(" Total", "").strip()
        if name in ("Current", "Late", "NPL", "Closed") and row.get("npl_type") is None and row["count"]:
            sheet_by_status[name.upper()] = max(sheet_by_status.get(name.upper(), 0), row["count"])
    reconciliation = []
    odoo_serving = source.get("serving_code") == "ODOO"
    if odoo_serving and not (pivots.get("payment_status") or []):
        # The sheet's pivots are the comparison base, and Odoo carries no money
        # pivots at all. Saying "differs" four times would read as a mismatch found;
        # the honest answer is that there is nothing to compare against.
        for key in ("CURRENT", "LATE", "NPL", "CLOSED"):
            reconciliation.append({"payment_status": key, "sheet": None,
                                   "imported": imported_by_status.get(key, 0),
                                   "matches": None, "note": "odoo_no_money_pivots"})
        reconciled = None
        cash_total = None
        cash_imported = 0
    else:
        for key in ("CURRENT", "LATE", "NPL", "CLOSED"):
            expected = sheet_by_status.get(key)
            actual = imported_by_status.get(key, 0)
            reconciliation.append({"payment_status": key, "sheet": expected, "imported": actual,
                                   "matches": expected is not None and expected == actual,
                                   "note": "export truncated per tab" if expected and actual < expected else None})
        cash_summary = pivots.get("cash_invoices") or []
        cash_total = next((r for r in cash_summary if r.get("dc_status") == "Total"), None)
        cash_imported = sum(len(getattr(c, "sheet", {}).get("cash_invoices") or []) for c in customers)
        reconciled = all(r["matches"] for r in reconciliation) and (cash_total is None or cash_imported >= cash_total["invoices"])
    return {
        "run": {"source": "New Order Master (Drive export)", "business_date": str(settings.business_date),
                "reconciled": reconciled,
                # Final v2 (prototype 2363): when the import actually ran. Read off the
                # import run's own finished_at (book_source.py), or None on the held
                # fixture — the screen then shows no note rather than inventing a time.
                "imported_at": source.get("imported_at"),
                "import_started_at": source.get("import_started_at"),
                "captured_on": source.get("captured_on"),
                "truncated_blocks": [b for b in report.get("blocks", []) if b["kind"] in ("LEASING_BOOK", "COLLECTION_TRACKING") and b["rows"] <= TRUNCATION_ROW_CAP + 10]},
        # Served first: that is the number the debt team reads. On the sheet rung the
        # slice keys are absent, so served/landed fall back to what the book holds.
        "counts": {"served": source.get("served_customers") or (len(customers) + len(report.get("registry") or [])),
                   "landed": source.get("landed_customers") or source.get("served_customers") or len(customers),
                   "registry": len(report.get("registry", [])),
                   "skipped": len(report.get("skipped", [])),
                   "engine_book": len(customers), "by_status": imported_by_status},
        "reconciliation": reconciliation,
        "cash": {"sheet_overdue_invoices": cash_total["invoices"] if cash_total else None,
                 "sheet_outstanding": cash_total["outstanding"] if cash_total else None,
                 "imported_invoices": cash_imported},
        "collection_tracking_summary": pivots.get("collection_tracking"),
        "skipped": report.get("skipped", []),
        "warnings": report.get("warnings", []),
        "blocks": report.get("blocks", []),
        "gap_list": gap_list(customers, report),
        # Delta-100 DS1: the ranked inbound chain, rungs 2 and 4 from their real
        # stores. The existing Odoo `fallback_chain` (integrations/odoo.py) is a
        # different question and is untouched.
        "source_chain": _source_chain(report),
    }


def gap_list(customers=None, report=None):
    """Installed per EPC dates, not Order-Done per status (⚠ I-12, MC5)."""
    if customers is None:
        customers, report = book.build()
    rows = []
    bd = settings.business_date
    for customer in list(customers) + list(report.get("registry", [])):
        sheet = getattr(customer, "sheet", {}) or {}
        order = sheet.get("order") or {}
        status = order.get("order_status") or (sheet.get("leasing") or {}).get("order_status")
        end = order.get("epc_end_date")
        if end and status and status != "Order - Done":
            try:
                days = (bd - date.fromisoformat(end)).days
            except ValueError:
                days = None
            rows.append({"volt_id": getattr(customer, "volt_id", None), "display_name": customer.display_name,
                         "order_status": status, "epc_end_date": end, "days_since_install": days,
                         "epc": order.get("epc"), "owner": "Operations (Dan)", "source_ref": order.get("source_ref")})
    rows.sort(key=lambda r: -(r["days_since_install"] or 0))
    return rows


def sheet_vs_engine(customer, engine_dpd, engine_fee):
    """MC4 — both figures on the case during migration, the method named."""
    sheet = (getattr(customer, "sheet", {}) or {}).get("leasing") or {}
    return {
        "sheet": {"days_late": sheet.get("days_late"), "late_fees": sheet.get("late_fees"),
                  "method": "cumulative balance in monthly blocks at 0.3%/day (Late Fee Logic tab)"},
        "engine": {"dpd": engine_dpd, "penalty_indicative": str(engine_fee) if engine_fee is not None else None,
                   "method": "each instalment aged separately, simple, %s%%/day after %d days grace — decided"
                             % (settings.late_payment_daily_rate * 100, settings.late_payment_grace_days)},
    }

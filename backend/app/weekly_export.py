"""The weekly report as an Excel file — the live draft or one published edition.

Every figure is read out of the report payload exactly as `reports.weekly()` served
it; nothing is recomputed here. A money string becomes a number cell so the reader
can sum it in Excel, and a ratio stays the served string ("58.3%") because the
report, not the spreadsheet, owns how it was measured. Since B14 (Feedback Round 1,
WP12) the Summary sheet also carries the five WP12 figures (MoM, paying customers,
NPL in/out, the true/held arrears split and payment-status changes); a payload frozen
before they existed — an edition or snapshot from before B13 — says "not sent".
"""
from decimal import Decimal, InvalidOperation

from . import xlsx_writer
from .xlsx_writer import Bold

CATS = ("instalment", "cash_or_project", "total")

LABELS = {
    "th": {
        "sheet_summary": "สรุป", "sheet_npl": "การเปลี่ยนประเภท NPL", "sheet_tiers": "ลำดับความสำคัญ",
        "title": "รายงานประจำสัปดาห์", "period": "รอบ", "week": "สัปดาห์ที่ (ISO)", "business_date": "วันทำการ",
        "status": "สถานะ", "draft": "ฉบับร่าง — ตัวเลขสดจากระบบ ยังไม่ได้เผยแพร่",
        "published": "ฉบับที่ %(number)s เผยแพร่ %(at)s โดย %(by)s",
        "superseded": "ฉบับที่ %(number)s เผยแพร่ %(at)s โดย %(by)s (มีฉบับใหม่กว่าแทนแล้ว)",
        "cash_in": "เงินเข้า", "category": "หมวด", "actual": "ยอดจริง", "target": "เป้า", "achievement": "ผลสำเร็จ",
        "no_target": "ไม่มีเป้า",
        "cat.instalment": "ค่างวด (SPV)", "cat.cash_or_project": "เงินสดหรือโครงการ (EPC)", "cat.total": "รวม",
        "portfolio": "พอร์ต", "current": "ปกติ", "late": "ล่าช้า", "npl": "NPL", "in_collection": "อยู่ในการติดตาม",
        "ratio_late": "สัดส่วนล่าช้า", "unit": "หน่วย",
        "promises": "นัดชำระ", "kept": "รักษานัด", "broken": "ผิดนัด", "open": "เปิดอยู่", "kept_rate": "อัตรารักษานัด",
        "issues_open": "ปัญหาระบบที่เปิดอยู่", "reviews_open": "รอผู้จัดการตอบ", "focus": "จุดเน้นสัปดาห์หน้า",
        "contract": "สัญญา", "customer": "ลูกค้า", "npl_type": "ประเภท NPL", "reason": "เหตุผลจากบันทึกเคส",
        "on": "วันที่", "by": "โดย", "none": "ไม่มีการกำหนดประเภท NPL ในรอบนี้", "no_reason": "ไม่มีเหตุผลบันทึกไว้",
        "tier": "ลำดับ", "count": "จำนวน",
        # B14 (Feedback Round 1, WP12). First-cell labels never equal "สถานะ", "ล่าช้า",
        # "สัดส่วนล่าช้า" or "รวม": test_weekly_editions reads the summary as
        # {first cell: row}, and the last row with a label wins.
        "not_sent": "API ยังไม่ส่งตัวเลขนี้", "indicative": "ตัวเลขชี้แนะ",
        "mom": "MoM ค่างวด / เงินสด", "mom.head": "หมวด (MoM)",
        "mom.this": "เดือนนี้ %(start)s – %(end)s", "mom.last": "ช่วงเดียวกันเดือนก่อน %(start)s – %(end)s",
        "mom.instalment": "MoM · ค่างวด (SPV)", "mom.cash_or_project": "MoM · เงินสดหรือโครงการ (EPC)",
        "mom.total": "MoM · รวมทุกหมวด", "change": "เปลี่ยน", "change_pct": "เปลี่ยน %",
        "paying": "ลูกค้าที่จ่ายสัปดาห์นี้ · WoW", "span.this": "ช่วงนี้ %(start)s – %(end)s",
        "span.prior": "7 วันก่อนหน้า %(start)s – %(end)s",
        "paying.customers": "ลูกค้าที่จ่าย (ราย)", "paying.receipts": "ใบเสร็จ (ใบ)",
        "npl_move": "เข้า NPL / ออกจาก NPL สัปดาห์นี้", "customers": "ลูกค้า (ราย)",
        "by_status_change": "จากการเปลี่ยนสถานะ", "by_declaration": "จากการประกาศ NPL",
        "entered": "เข้า NPL", "left": "ออกจาก NPL", "npl_rows.contract": "สัญญา (เข้า/ออก NPL)",
        "direction": "ทิศทาง", "basis": "นับจาก", "from": "จาก", "to": "เป็น",
        "split": "หนี้ค้างจริง vs พักไว้ฝั่งบริษัท", "side": "ฝั่ง",
        "side.true": "ค้างจริง", "side.held": "พักไว้ฝั่งบริษัท", "side.total": "ยอดค้างทั้งหมด",
        "arrears.instalment": "ค่างวด (SPV)", "arrears.cash_or_project": "เงินสดหรือโครงการ (EPC)",
        "arrears.unrouted": "ยังไม่แยกหมวด", "arrears.total": "รวมยอดค้าง",
        "held.contract": "สัญญา (พักไว้)", "held.why": "เหตุที่พักไว้",
        "status_changes": "การเปลี่ยนกลุ่ม Late/NPL", "status.contract": "สัญญา (เปลี่ยนสถานะ)",
        "status.count": "%(count)s รายการ · คนเปลี่ยน %(by_person)s · ระบบปรับ %(by_system)s",
        "status.none": "ไม่มีการเปลี่ยนสถานะการชำระในช่วงนี้", "system": "ระบบ",
    },
    "en": {
        "sheet_summary": "Summary", "sheet_npl": "NPL type changes", "sheet_tiers": "Tiers",
        "title": "Weekly report", "period": "Period", "week": "Week (ISO)", "business_date": "Business date",
        "status": "Status", "draft": "Draft — live figures, not published",
        "published": "Edition %(number)s, published %(at)s by %(by)s",
        "superseded": "Edition %(number)s, published %(at)s by %(by)s (superseded by a later edition)",
        "cash_in": "Cash in", "category": "Category", "actual": "Actual", "target": "Target", "achievement": "Achievement",
        "no_target": "No target",
        "cat.instalment": "Instalments (SPV)", "cat.cash_or_project": "Cash or project (EPC)", "cat.total": "Total",
        "portfolio": "Portfolio", "current": "Current", "late": "Late", "npl": "NPL", "in_collection": "In collection",
        "ratio_late": "Late ratio", "unit": "Unit",
        "promises": "Promises", "kept": "Kept", "broken": "Broken", "open": "Open", "kept_rate": "Kept rate",
        "issues_open": "Service issues open", "reviews_open": "Reviews open", "focus": "Next week's focus",
        "contract": "Contract", "customer": "Customer", "npl_type": "NPL type", "reason": "Reason from case record",
        "on": "On", "by": "By", "none": "No NPL type was set this period.", "no_reason": "no reason recorded",
        "tier": "Tier", "count": "Count",
        "not_sent": "Not sent by the API yet", "indicative": "Indicative figure",
        "mom": "Month on month: instalments / cash", "mom.head": "Line (MoM)",
        "mom.this": "This month %(start)s – %(end)s", "mom.last": "Same span last month %(start)s – %(end)s",
        "mom.instalment": "MoM · Instalments (SPV)", "mom.cash_or_project": "MoM · Cash or project (EPC)",
        "mom.total": "MoM · All lines", "change": "Change", "change_pct": "Change %",
        "paying": "Paying customers this week · WoW", "span.this": "This period %(start)s – %(end)s",
        "span.prior": "7 days before %(start)s – %(end)s",
        "paying.customers": "Paying customers", "paying.receipts": "Receipts",
        "npl_move": "Into / out of NPL this week", "customers": "Customers",
        "by_status_change": "By status change", "by_declaration": "By declaration",
        "entered": "Entered NPL", "left": "Left NPL", "npl_rows.contract": "Contract (into/out of NPL)",
        "direction": "Direction", "basis": "Counted by", "from": "From", "to": "To",
        "split": "True arrears vs held on the company side", "side": "Side",
        "side.true": "True arrears", "side.held": "Held on the company side", "side.total": "All arrears",
        "arrears.instalment": "Instalments (SPV)", "arrears.cash_or_project": "Cash or project (EPC)",
        "arrears.unrouted": "Not routed to a line", "arrears.total": "Arrears in all",
        "held.contract": "Contract (held)", "held.why": "Why held",
        "status_changes": "Payment-status changes (Late/NPL)", "status.contract": "Contract (status change)",
        "status.count": "%(count)s changes · %(by_person)s by a person · %(by_system)s by the system",
        "status.none": "No payment-status change in this period.", "system": "System",
    },
}


def _money(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return str(value)


def _pick(lang, th, en):
    """The Thai twin for a Thai file, the English sentence for an English one."""
    if lang == "en":
        return en or th
    return th or en


def _status_line(L, edition):
    if not edition:
        return L["draft"]
    key = "superseded" if edition.get("status") == "SUPERSEDED" else "published"
    return L[key] % {"number": edition.get("number"), "at": edition.get("published_at") or "—",
                     "by": edition.get("published_by") or "—"}


LINES = ("instalment", "cash_or_project")
ARREARS = ("instalment", "cash_or_project", "unrouted", "total")


def _pct(value):
    """A served percentage string, or a dash when the server sent none (no base)."""
    return "%s%%" % value if value not in (None, "") else "—"


def _figure(rows, L, key, block):
    """B14: the title row of one served figure, marked indicative when the server says
    so. A payload without the key — an edition or snapshot frozen before B13 — gets a
    title that says the API did not send it, and False, so nothing is guessed below it."""
    rows.append([])
    if not isinstance(block, dict):
        rows.append([Bold(L[key]), L["not_sent"]])
        return False
    rows.append([Bold(L[key]), L["indicative"] if block.get("indicative") is True else None])
    return True


def _explain(rows, lang, block):
    """The definition line and every note, in the file's language."""
    definition = _pick(lang, block.get("definition_th"), block.get("definition"))
    if definition:
        rows.append(["", definition])
    for note in block.get("notes") or []:
        text = _pick(lang, note.get("th"), note.get("en"))
        if text:
            rows.append(["", text])


def _served_figures(rows, L, lang, payload):
    """The five figures reports.weekly() serves since Feedback Round 1 (WP12), written as
    served: money strings become number cells, counts stay ints, nothing is summed or
    differenced here. `reason` arrives with typed numbers already cut (B13b)."""
    mom = payload.get("mom")
    if _figure(rows, L, "mom", mom):
        this, last = mom.get("this_month") or {}, mom.get("last_month") or {}
        change, pct = mom.get("change") or {}, mom.get("change_pct") or {}
        rows.append([Bold(L["mom.head"]), Bold(L["mom.this"] % this), Bold(L["mom.last"] % last),
                     Bold(L["change"]), Bold(L["change_pct"])])
        for key in LINES + ("total",):
            rows.append([L["mom.%s" % key], _money(this.get(key)), _money(last.get(key)),
                         _money(change.get(key)), _pct(pct.get(key))])
        _explain(rows, lang, mom)

    paying = payload.get("paying_customers")
    if _figure(rows, L, "paying", paying):
        this, prior = paying.get("this_period") or {}, paying.get("prior_period") or {}
        rows.append(["", Bold(L["span.this"] % this), Bold(L["span.prior"] % prior),
                     Bold(L["change"]), Bold(L["change_pct"])])
        rows.append([L["paying.customers"], this.get("customers"), prior.get("customers"),
                     paying.get("change"), _pct(paying.get("change_pct"))])
        rows.append([L["paying.receipts"], this.get("receipts"), prior.get("receipts")])
        _explain(rows, lang, paying)

    npl = payload.get("npl_movement")
    if _figure(rows, L, "npl_move", npl):
        entered, left = npl.get("entered") or {}, npl.get("left") or {}
        rows.append(["", Bold(L["customers"]), Bold(L["by_status_change"]), Bold(L["by_declaration"])])
        rows.append([L["entered"], entered.get("customers"), entered.get("by_status_change"), entered.get("by_declaration")])
        rows.append([L["left"], left.get("customers"), left.get("by_status_change")])
        if npl.get("rows"):
            rows.append([Bold(L["npl_rows.contract"]), Bold(L["customer"]), Bold(L["direction"]), Bold(L["basis"]),
                         Bold(L["from"]), Bold(L["to"]), Bold(L["by"]), Bold(L["on"])])
            for r in npl["rows"]:
                rows.append([r.get("volt_id") or "—", r.get("display_name") or "—",
                             L["left"] if r.get("direction") == "LEFT" else L["entered"], r.get("basis") or "—",
                             r.get("from") or "—", r.get("to") or "—", r.get("by") or "—", r.get("on") or "—"])
        _explain(rows, lang, npl)

    split = payload.get("arrears_split")
    if _figure(rows, L, "split", split):
        rows.append([Bold(L["side"])] + [Bold(L["arrears.%s" % k]) for k in ARREARS] + [Bold(L["customers"])])
        for side in ("true", "held", "total"):
            line = split.get(side) or {}
            rows.append([L["side.%s" % side]] + [_money(line.get(k)) for k in ARREARS] + [line.get("customers")])
        unit = _pick(lang, split.get("unit_th"), split.get("unit"))
        if unit:
            rows.append(["", unit])
        if split.get("held_rows"):
            rows.append([Bold(L["held.contract"]), Bold(L["customer"]), Bold(L["held.why"])]
                        + [Bold(L["arrears.%s" % k]) for k in ARREARS])
            for r in split["held_rows"]:
                rows.append([r.get("volt_id") or "—", r.get("display_name") or "—",
                             " · ".join(r.get("reasons") or []) or "—"] + [_money(r.get(k)) for k in ARREARS])
        _explain(rows, lang, split)

    status = payload.get("status_changes")
    if _figure(rows, L, "status_changes", status):
        if status.get("rows"):
            rows.append(["", L["status.count"] % {"count": status.get("count"), "by_person": status.get("by_person"),
                                                  "by_system": status.get("by_system")}])
            rows.append([Bold(L["status.contract"]), Bold(L["customer"]), Bold(L["from"]), Bold(L["to"]),
                         Bold(L["by"]), Bold(L["reason"]), Bold(L["on"])])
            for r in status["rows"]:
                rows.append([r.get("volt_id") or "—", r.get("display_name") or r.get("case_uid") or "—",
                             r.get("from") or "—", r.get("to") or "—",
                             L["system"] if r.get("by_system") is True else (r.get("by") or "—"),
                             r.get("reason") or L["no_reason"], r.get("on") or "—"])
        else:
            rows.append(["", L["status.none"]])
        _explain(rows, lang, status)


def filename(payload, edition=None):
    period = payload.get("period") or {}
    base = "volt-weekly-report-%s" % (period.get("label") or "report").replace("..", "_to_")
    if edition:
        return "%s-edition-%s.xlsx" % (base, edition.get("number"))
    return "%s-draft.xlsx" % base


def build(payload, edition=None, lang="th"):
    lang = "en" if lang == "en" else "th"
    L = LABELS[lang]
    period = payload.get("period") or {}
    ms = payload.get("management_summary") or {}
    pf = payload.get("portfolio") or {}
    pr = payload.get("promises") or {}
    targets = ms.get("targets") or {}
    achievement = ms.get("achievement") or {}
    cash_in = ms.get("cash_in") or {}

    rows = [
        [Bold(L["title"])],
        [L["period"], "%s – %s" % (period.get("start", "—"), period.get("end", "—"))],
        [L["week"], period.get("week")],
        [L["business_date"], period.get("generated_at")],
        [L["status"], _status_line(L, edition)],
        [],
        [Bold(L["cash_in"])],
        [Bold(L["category"]), Bold(L["actual"]), Bold(L["target"]), Bold(L["achievement"])],
    ]
    for c in CATS:
        target = targets.get(c)
        rows.append([L["cat.%s" % c], _money(cash_in.get(c)),
                     _money(target) if target not in (None, "") else L["no_target"],
                     achievement.get(c) or "—"])
    if ms.get("measure_label_th"):
        rows.append([ms["measure_label_th"]])
    note = _pick(lang, ms.get("note_th"), ms.get("note"))
    if note:
        rows.append([note])
    if ms.get("allocation_hold_note_th"):
        rows.append([ms["allocation_hold_note_th"]])

    # B14 carry: cash_in's own indicative mark and every note (B13 fix 1/2, F-R2).
    if ms.get("cash_in_indicative") is True:
        rows.append(["", L["indicative"]])
    for n in ms.get("cash_in_notes") or []:
        text = _pick(lang, n.get("th"), n.get("en"))
        if text:
            rows.append(["", text])

    rows += [
        [],
        [Bold(L["portfolio"])],
        [L["current"], pf.get("current")],
        [L["late"], pf.get("late")],
        [L["npl"], pf.get("npl")],
        [L["in_collection"], pf.get("in_collection")],
        [L["ratio_late"], "%s%%" % pf["ratio_late_pct"] if pf.get("ratio_late_pct") is not None else "—",
         _pick(lang, pf.get("period_of_ratio_th"), pf.get("period_of_ratio"))],
    ]
    definition = _pick(lang, pf.get("ratio_definition_th"), pf.get("ratio_definition"))
    if definition:
        rows.append(["", definition])
    unit = _pick(lang, pf.get("unit_th"), pf.get("unit"))
    if unit:
        rows.append([L["unit"], unit])

    rows += [
        [],
        [Bold(L["promises"])],
        [L["kept"], pr.get("kept")],
        [L["broken"], pr.get("broken")],
        [L["open"], pr.get("open")],
        [L["kept_rate"], "%s%%" % pr["kept_rate_pct"] if pr.get("kept_rate_pct") is not None else "—",
         _pick(lang, pr.get("period_of_ratio_th"), pr.get("period_of_ratio"))],
        [],
        [L["issues_open"], payload.get("service_issues_open")],
        [L["reviews_open"], payload.get("reviews_open")],
        [L["focus"], payload.get("next_week_focus") or "—"],
    ]

    _served_figures(rows, L, lang, payload)

    changes = payload.get("npl_changes") or []
    npl_rows = [[Bold(L["contract"]), Bold(L["customer"]), Bold(L["npl_type"]), Bold(L["reason"]),
                 Bold(L["on"]), Bold(L["by"])]]
    for e in changes:
        npl_rows.append([e.get("volt_id") or "—", e.get("display_name") or e.get("case_uid") or "—",
                         e.get("code") or "—", e.get("reason") or L["no_reason"], e.get("on") or "—",
                         e.get("by") or "—"])
    if not changes:
        npl_rows.append([L["none"]])

    tiers = payload.get("counts_by_tier") or {}
    tier_rows = [[Bold(L["tier"]), Bold(L["count"])]] + [[k, v] for k, v in tiers.items()]

    return xlsx_writer.workbook([
        {"name": L["sheet_summary"], "rows": rows, "widths": [34, 18, 44, 16, 16, 16, 12, 14]},
        {"name": L["sheet_npl"], "rows": npl_rows, "widths": [18, 32, 34, 48, 12, 14]},
        {"name": L["sheet_tiers"], "rows": tier_rows, "widths": [26, 10]},
    ])

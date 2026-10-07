"""Today — REQ-COL-071, the seven tiers in sequence.

Built per officer at 02:30 and on demand, grouped by customer. Every item names the
tier that won (priority_reason) so the officer can see why a customer is where
they are. The money on each item comes from the engine through the journey
router's _work_item (arrears large, outstanding small, the band pair); nothing here
does arithmetic on money.

Tier 1  PTP due today
Tier 2  next action due today or overdue
Tier 3  broken PTP not yet renegotiated
Tier 4  two or more instalments missed, no open PTP
Tier 5  DPD 1-3, no contact yet
Tier 6  answers and closures waiting (review answered, ticket closed, PEAK draft rejected)
Tier 7  everyone else, arrears descending
"""
from datetime import date, timedelta
from decimal import Decimal

from . import cases as cases_domain
from . import dictionaries
from . import journey
from . import ladder as ladder_mod
from . import peak_documents as pkd
from .config import settings

TIERS = ("PTP_DUE_TODAY", "NEXT_ACTION_DUE", "BROKEN_PTP", "AT_RISK_TWO_MISSED",
         "NEW_ARREARS", "ANSWER_WAITING", "ROUTINE")
TIER_RANK = {t: i + 1 for i, t in enumerate(TIERS)}


TIER_LABEL_TH = {
    "PTP_DUE_TODAY": "นัดชำระถึงกำหนดวันนี้", "NEXT_ACTION_DUE": "งานถัดไปถึงกำหนด",
    "BROKEN_PTP": "ผิดนัด PTP ยังไม่ได้เจรจาใหม่", "AT_RISK_TWO_MISSED": "ค้างสองงวดขึ้นไป ไม่มีนัดชำระ",
    "NEW_ARREARS": "ค้างชำระใหม่ ยังไม่เคยติดต่อ", "ANSWER_WAITING": "มีคำตอบหรือการปิดงานรออยู่",
    "ROUTINE": "ติดตามตามรอบ",
}

# Round-4 J4-29: the same tier, named for a book with no monthly schedule. วิชัย's cash
# contract is ONE handover balance 339 days late — "ค้างสองงวดขึ้นไป" is a sentence about
# instalments it never had. `missed_basis_th` already says so in the small print; this is
# the chip an officer reads first.
TIER_LABEL_TH_CASH = {
    "AT_RISK_TWO_MISSED": "ค้างนานเทียบเท่าสองงวดขึ้นไป ไม่มีนัดชำระ (สัญญาเงินสด)",
}

# Language pass: the English twins, served beside the Thai.
TIER_LABEL_EN = {
    "PTP_DUE_TODAY": "Promise to pay due today", "NEXT_ACTION_DUE": "Next action due",
    "BROKEN_PTP": "Broken promise, not renegotiated", "AT_RISK_TWO_MISSED": "Two or more instalments missed, no promise",
    "NEW_ARREARS": "New arrears, never contacted", "ANSWER_WAITING": "An answer or closure is waiting",
    "ROUTINE": "Routine follow-up",
}
TIER_LABEL_EN_CASH = {
    "AT_RISK_TWO_MISSED": "Late the equivalent of two or more instalments, no promise (cash contract)",
}

# Round-4 F1-BE2: the desk's own caption for why kept_ptp_count reads 0 across the
# book — the sheet records a promise's amount and date, never its outcome, so a
# promise past its date shows BROKEN until an officer closes it from the case page
# (cases.py's _seed / close_ptp). Fires only when the filtered desk actually carries
# promise history (a broken or an open PTP) AND none of it shows as kept — never a
# claim about a desk with no promise history to explain (§1a).
PTP_HISTORY_NOTE_TH = ("ยังไม่มีนัดที่บันทึกว่าชำระตามนัดในระบบ — ชีตบันทึกเฉพาะยอดและวันนัด "
                       "ไม่ได้บันทึกผล นัดที่เลยวันจึงขึ้นเป็นผิดนัดจนกว่าจะปิดนัดจากหน้าเคส")

# Feedback Round 1, WP7 (B2): Today's filter bar. The product rule is the Work Book's
# own (routers/today.py `_workbook`): a case with sheet facts on an SPV contract is a
# lease, any other case with sheet facts is cash, a case with none has no product.
PRODUCTS = ("LEASE", "CASH")
PTP_HISTORY_NOTE_EN = ("No promise is recorded as kept yet — the sheet records only a promise's amount and date, "
                       "not its outcome, so a promise past its date shows as broken until it is closed from the case page")
OFFICER_TOTALS_NOTE_EN = ("Each officer's whole list today for the selected EPC/SPV, regardless of the other filters — "
                          "the same number that officer sees on their own Today page")
COUNTS_NOTE_EN = ("The tier chips add up to the total. A row with an answer waiting that sits in a higher tier "
                  "is counted in that tier and named under the Answers waiting chip")
OFFICER_TOTALS_NOTE_TH = ("จำนวนรายการในลิสต์วันนี้ของเจ้าหน้าที่แต่ละคนตาม EPC/SPV ที่เลือก ไม่ขึ้นกับตัวกรองอื่น "
                          "— ตัวเลขเดียวกับที่เจ้าหน้าที่คนนั้นเห็นเมื่อเปิดหน้าวันนี้ของตัวเอง")


def product_of(item, case):
    if not case.get("sheet"):
        return None
    return "LEASE" if item.get("entity") == "SPV" else "CASH"


def known_officers(cs, acting=None):
    """Every officer uid /v1/today may be filtered by, in registry order: the registry
    (the seed's officers, then the fixed Manager, Owner and OPS seats), then any uid a
    lead has assigned a case to since — POST /v1/customers/{uid}/assign takes the uid
    as given, so a desk can exist for a name the registry never listed — then the
    acting person's own identity (X-Volt-Officer): a new officer with nothing assigned
    yet opens an empty desk, never a refusal."""
    from . import officers
    known = [row["uid"] for row in officers.registry()]
    seen = set(known)
    for uid in [case.get("officer_uid") for case in cs.cases.values()] + [acting]:
        if uid and uid not in seen:
            seen.add(uid)
            known.append(uid)
    return known


def officer_totals(cs, known, entity=None):
    """B2: the team-workload numbers, served once instead of the screen calling
    /v1/today once per officer (J4-17 / J5-11). Each officer's whole list today —
    exactly `meta.total` of /v1/today?officer=<uid>&entity=<entity> with no other filter, because it
    applies build()'s own two gates (a case on a book customer, not CLOSED or
    TERMINATED). Zero for
    an officer with nothing today, so a lead still sees the empty desk."""
    totals = {uid: 0 for uid in known}
    for customer in journey.book_customers():
        if entity and (customer.contracts[0].entity if customer.contracts else None) != entity:
            continue
        case = cs.cases.get(customer.uid)
        if case is None or case["payment_status"] in ("CLOSED", "TERMINATED") or not case["officer_uid"]:
            continue
        totals[case["officer_uid"]] = totals.get(case["officer_uid"], 0) + 1
    return totals


def unassigned_total(cs, entity=None):
    """F10 / feedback-r2 TASK-108: how many collectable rows carry no officer at
    all — the same two gates officer_totals applies above, counting the complement.
    Computed over the selected entity's whole book, never the officer-filtered desk."""
    total = 0
    for customer in journey.book_customers():
        if entity and (customer.contracts[0].entity if customer.contracts else None) != entity:
            continue
        case = cs.cases.get(customer.uid)
        if case is None or case["payment_status"] in ("CLOSED", "TERMINATED") or case["officer_uid"]:
            continue
        total += 1
    return total


def annotate_worked(items, business_date):
    """F17 / TASK-118 (R-A): the served "worked today" facts, added by GET /v1/today
    alone. build()'s rows are shared with the workbook (whose normal-vs-CLOSED key
    set is pinned at seven, test_round4.py:782), so the flags never live in build()."""
    bd = str(business_date)
    for item in items:
        case = item.get("case") or {}
        touched = case.get("last_contact_at") or (item.get("session_last_contact") or {}).get("at")
        item["worked_at"] = str(touched) if touched else None
        item["worked_today"] = bool(touched) and str(touched)[:10] == bd
    return items


def daily_summary(items, cs, business_date):
    """F17 / feedback-r2 TASK-118 (R-A): the per-officer daily figures the summary
    strip prints — to follow, worked, promises made today and their amount, and the
    unreachable contacts. Every number counted from the rows and the day's own
    contact log; the client prints them and computes nothing. Keyed by officer uid,
    plus "*" for the whole (filtered) list."""
    bd = str(business_date)
    ptp_count, ptp_amount, unreachable = {}, {}, {}
    for row in cs.contact_log:
        if str(row.get("occurred_at") or "")[:10] != bd:
            continue
        uid = row.get("officer_uid") or "*"
        ptp = cs.ptps.get(row["ptp_uid"]) if row.get("ptp_uid") else None
        if ptp:
            ptp_count[uid] = ptp_count.get(uid, 0) + 1
            ptp_amount[uid] = ptp_amount.get(uid, Decimal("0")) + Decimal(ptp["promised_amount"])
        if row.get("result") in cases_domain.UNREACHABLE_RESULTS:
            unreachable[uid] = unreachable.get(uid, 0) + 1

    def entry(mine, uid):
        return {
            "total": len(mine),
            "worked": sum(1 for i in mine if i["worked_today"]),
            "not_yet": sum(1 for i in mine if not i["worked_today"]),
            "ptp_count": ptp_count.get(uid, 0),
            "ptp_amount": str(ptp_amount.get(uid, Decimal("0")).quantize(Decimal("0.01"))),
            "unreachable": unreachable.get(uid, 0),
        }

    out = {}
    for uid in sorted({(i["case"].get("officer_uid") or "*") for i in items}):
        out[uid] = entry([i for i in items if (i["case"].get("officer_uid") or "*") == uid], uid)
    out["*"] = {
        "total": len(items),
        "worked": sum(1 for i in items if i["worked_today"]),
        "not_yet": sum(1 for i in items if not i["worked_today"]),
        "ptp_count": sum(ptp_count.values()),
        "ptp_amount": str(sum(ptp_amount.values(), Decimal("0")).quantize(Decimal("0.01"))),
        "unreachable": sum(unreachable.values()),
    }
    return out


def missed_equivalent(customer, item, missed):
    """Round-3 J3-05: the ladder was instalment-shaped. A cash book is ONE
    HANDOVER_BALANCE invoice, so it can never reach two missed instalments however old
    it is — 548,000.00 at DPD 270 fell to ROUTINE under a 5,580.00 three-day arrear.
    A book with no monthly schedule to miss counts one missed month per 30 days late.
    Returns (missed, basis_th, basis_en) — the basis is printed in the tier reason."""
    dpd = item.get("oldest_dpd") or 0
    if any(getattr(k, "product", None) == "LEASE" for k in customer.contracts):
        return missed, None, None
    if dpd < 30 or Decimal(item["aggregate_overdue"]) <= 0:
        return missed, None, None
    equivalent = max(missed, dpd // 30)
    return (equivalent, "ค้างชำระ %d วัน = %d งวดเทียบเท่า (สัญญาเงินสด ไม่มีงวดรายเดือนให้ขาด)" % (dpd, equivalent),
            "%d days late = %d equivalent instalments (cash contract, no monthly instalments to miss)" % (dpd, equivalent))


def routine_reason(case, item, missed, ptp_open):
    """Round-3 J3-05: every routine row says WHY it is routine, naming the rungs it
    failed, so a big old cash book at the bottom of the list is explainable.
    Returns (th, en), each composed in its own language."""
    dpd = item.get("oldest_dpd")
    th, en = [], []
    th.append("ไม่มีนัดชำระที่เปิดอยู่" if not ptp_open else "นัดชำระยังไม่ถึงกำหนดวันนี้")
    en.append("no open promise" if not ptp_open else "the promise is not due today")
    if case["next_action_on"]:
        th.append("งานถัดไป %s (%s) ยังไม่ใช่งานที่คนตั้ง" % (case["next_action_on"], setter_label(case["next_action_set_by"], "th")))
        en.append("next action %s (%s) was not set by a person" % (case["next_action_on"], setter_label(case["next_action_set_by"], "en")))
    else:
        th.append("ไม่มีงานถัดไปที่ถึงกำหนด")
        en.append("no next action due")
    th.append("ค้าง %d งวด (ยังไม่ถึงสองงวด)" % missed if missed < 2 else "ค้าง %d งวด" % missed)
    en.append("%d instalments missed (fewer than two)" % missed if missed < 2 else "%d instalments missed" % missed)
    th.append("ค้างชำระ %s วัน" % dpd if dpd is not None else "ยังไม่เลยกำหนด")
    en.append("%s days late" % dpd if dpd is not None else "not yet past due")
    th.append("ยอดค้าง %s บาท" % item["aggregate_overdue"])
    en.append("arrears ฿%s" % item["aggregate_overdue"])
    return "ติดตามตามรอบ — " + " · ".join(th), "Routine follow-up — " + " · ".join(en)


SEEDED_SETTERS = ("SEED", "SYSTEM", "MAPLOG_IMPORT", "SERVICE_DEFERRAL", None)

# Language pass: a reason names who set the next action in words, never the setter
# code. The same plain labels the case page uses (i18n `case.setBy.*`); a person's uid
# stands as their name.
SETTER_LABEL = {
    "SEED": ("ระบบตอนย้ายข้อมูล", "the system, at migration"),
    "SYSTEM": ("ระบบ", "the system"),
    "SERVICE_DEFERRAL": ("ระบบหลังเลื่อนงวด", "the system after a service deferral"),
    "MAPLOG_IMPORT": ("บันทึกการโทรในชีต", "the sheet's call log"),
    None: ("ไม่ระบุ", "not named"),
}


def setter_label(setter, lang):
    pair = SETTER_LABEL.get(setter)
    return pair[lang == "en"] if pair else setter


def next_action_label(code, lang):
    return dictionaries.for_current().label("NEXT_ACTION", code, lang)


def next_action_tiering(case, tier, business_date=None):
    """Round-3 J3-16: the card printed "งานถัดไป : โทรติดตาม 23/10/2026" while the
    รอทำงานถัดไป chip read 0, and nothing said why. The rule is right — a placeholder the
    seed wrote is not a person's next action, and a broken promise outranks tier 2
    anyway — so the card now carries the reason instead of leaving the officer to guess."""
    setter = case.get("next_action_set_by")
    counted = tier == "NEXT_ACTION_DUE"

    def out(th, en):
        return {"counts_as_tier": counted, "reason_th": th, "reason_en": en, "set_by": setter}
    if counted:
        return out(None, None)
    on = case.get("next_action_on")
    if not on:
        return out("ยังไม่มีงานถัดไปที่ถึงกำหนด", "No next action is due yet")
    higher = ("มีเงื่อนไขขั้นสูงกว่าอยู่ (%s) งานถัดไปจึงไม่ใช่เหตุผลที่จัดขั้นนี้" % TIER_LABEL_TH.get(tier, tier),
              "A higher tier applies (%s), so the next action is not why the row sits here" % TIER_LABEL_EN.get(tier, tier))
    bd = business_date or settings.business_date
    if setter == "MAPLOG_IMPORT":
        if on < str(bd - timedelta(days=30)):
            return out("ชีตบันทึกให้โทรกลับ %s ซึ่งเกิน 30 วันแล้ว ถือว่าเก่าเกินไป จึงไม่นับเป็นขั้น \"งานถัดไปถึงกำหนด\"" % on,
                       "The sheet asked for a call back on %s, more than 30 days ago — too old to count as \"Next action due\"" % on)
        if TIER_RANK.get(tier, 99) < TIER_RANK["NEXT_ACTION_DUE"]:
            return out(*higher)
        return out("ชีตบันทึกให้โทรกลับ %s ยังไม่ถึงวันนี้ จึงยังไม่นับเป็นขั้น \"งานถัดไปถึงกำหนด\"" % on,
                   "The sheet asked for a call back on %s, not yet today, so it does not count as \"Next action due\"" % on)
    if setter in SEEDED_SETTERS:
        return out("งานถัดไปนี้ระบบตั้งไว้เป็นค่าเริ่มต้น (%s) ไม่ใช่งานที่เจ้าหน้าที่ตั้งเอง จึงไม่นับเป็นขั้น \"งานถัดไปถึงกำหนด\""
                   % setter_label(setter, "th"),
                   "This next action is a system default (%s), not one an officer set, so it does not count as \"Next action due\""
                   % setter_label(setter, "en"))
    if TIER_RANK.get(tier, 99) < TIER_RANK["NEXT_ACTION_DUE"]:
        return out(*higher)
    return out("งานถัดไปกำหนด %s ยังไม่ถึงวันนี้ จึงยังไม่นับเป็นขั้น \"งานถัดไปถึงกำหนด\"" % on,
               "The next action is set for %s, not yet today, so it does not count as \"Next action due\"" % on)


def tier_for(case, item, missed, business_date, waiting, missed_basis=None, customer=None):
    """Returns (tier, reason_th, reason_en). Round-2 nantapol N2-08: a broken promise with no
    successor keeps the customer in BROKEN_PTP whatever next action a person set — the
    next action shows inside the row. Round-2 settasak S2-07: a broken promise on a
    customer who owes nothing is not collection work; it is named, not tiered.
    `missed_basis` is the (th, en) pair from missed_equivalent, or None."""
    bd = str(business_date)
    ptp = case.get("open_ptp_uid")
    cs = cases_domain.for_current()
    if ptp and cs.ptps[ptp]["promise_date"] == bd:
        return "PTP_DUE_TODAY", "นัดชำระ %s ถึงกำหนดวันนี้" % ptp, "Promise %s is due today" % ptp
    unhandled = _last_broken_unhandled(cs, case) if (case["broken_ptp_count"] > 0 and not ptp) else None
    if unhandled and (Decimal(item["aggregate_overdue"]) > 0 or
                      (item.get("money_position") or {}).get("review_required")):
        # Round-4 J4-03: one date for one event — the day it BROKE, said as such, beside
        # the day it was promised for.
        broke = (unhandled["uid"], unhandled["closed_on"] or unhandled["promise_date"], unhandled["promise_date"])
        return ("BROKEN_PTP", "ผิดนัด %s เมื่อ %s (นัด %s) ยังไม่มีนัดใหม่ การเจรจาใหม่ หรือคำตอบผู้จัดการ" % broke,
                "Promise %s broke on %s (promised for %s); no new promise, renegotiation or Manager answer yet" % broke)
    # A next action a PERSON set (or the customer asked for) is tier 2. The seed's
    # placeholder and the system's "call after a broken promise" are not — they
    # would flood tier 2 and hide tiers 3 to 5, which is what the sheet does today.
    person_set = case["next_action_set_by"] not in SEEDED_SETTERS
    waiting_kinds = ("NONE_CLOSED", "FOLLOW_PTP", "AWAIT_TICKET", "AWAIT_REVIEW", "AWAIT_PEAK")
    if case["next_action_on"] and case["next_action_on"] <= bd and case["next_action"] not in waiting_kinds and person_set:
        on, by = case["next_action_on"], case["next_action_set_by"]
        return ("NEXT_ACTION_DUE",
                "งานถัดไป %s ถึงกำหนด %s ตั้งโดย %s" % (next_action_label(case["next_action"], "th"), on, by),
                "Next action %s due %s, set by %s" % (next_action_label(case["next_action"], "en"), on, by))
    # A callback the sheet's call log recorded counts for thirty days; after that it is
    # stale and must not outrank real arrears (round-1 lead finding).
    stale_floor = str(business_date - timedelta(days=30))
    if case["next_action_set_by"] == "MAPLOG_IMPORT" and case["next_action_on"] and stale_floor <= case["next_action_on"] <= bd and not ptp:
        return ("NEXT_ACTION_DUE", "ชีตบันทึกให้โทรกลับ %s" % case["next_action_on"],
                "The sheet asked for a call back on %s" % case["next_action_on"])
    if missed >= 2 and not ptp and Decimal(item["aggregate_overdue"]) > 0:
        if missed_basis:
            return ("AT_RISK_TWO_MISSED", missed_basis[0] + " ไม่มีนัดชำระที่เปิดอยู่",
                    missed_basis[1] + ", no open promise")
        return ("AT_RISK_TWO_MISSED", "ค้าง %d งวด ไม่มีนัดชำระที่เปิดอยู่" % missed,
                "%d instalments missed, no open promise" % missed)
    dpd = item.get("oldest_dpd")
    if dpd is not None and 1 <= dpd <= 3 and case["last_contact_at"] is None:
        return "NEW_ARREARS", "ค้างชำระ %d วัน ยังไม่เคยติดต่อ" % dpd, "%d days late, never contacted" % dpd
    if waiting:
        return ("ANSWER_WAITING", "มี %d รายการรอเจ้าหน้าที่รับทราบ" % len(waiting),
                "%d items waiting for the officer to acknowledge" % len(waiting))
    if unhandled:
        pair = (unhandled["uid"], unhandled["promise_date"])
        return ("ROUTINE", "ผิดนัด %s (นัด %s) แต่ไม่มียอดค้าง จึงไม่อยู่ในขั้นผิดนัด PTP" % pair,
                "Promise %s (for %s) broke, but nothing is owed, so it is not in the broken-promise tier" % pair)
    return ("ROUTINE",) + routine_reason(case, item, missed, bool(ptp))


def _last_broken_unhandled(cs, case):
    """The latest BROKEN promise, if nothing succeeded it: no later promise on the case
    (a renegotiation or a new one), and no Manager answer after it. A contact row
    alone — a call not answered — is not a successor (N2-08). Returns the ptp or None."""
    mine = [p for p in cs.ptps.values() if p["customer_uid"] == case["customer_uid"]]
    broken = [p for p in mine if p["status"] == "BROKEN"]
    if not broken:
        return None
    order = {uid: n for n, uid in enumerate(cs.ptps)}
    last = max(broken, key=lambda p: order[p["uid"]])
    if any(order[p["uid"]] > order[last["uid"]] for p in mine):
        return None
    if last.get("renegotiated_to"):
        return None
    detected = last.get("broken_detected_at") or last.get("closed_on") or ""
    answered = [r for r in cs.reviews.values() if r["customer_uid"] == case["customer_uid"]
                and r["status"] == "ANSWERED" and (r.get("answered_at") or "") >= detected]
    if answered:
        return None
    return last


def build(officer=None, business_date=None, ladder_indicative=None, only_tier=None,
          payment_status=None, dc_status=None, product=None, entity=None, q=None, unassigned=False,
          _customers=None, _rows_only=False, _peak_waiting=None):
    """Returns {items, meta}. Items carry the journey work item plus the case.

    Round-4 F2-CR-1: ladder_indicative narrows to the rung named — filtered here,
    before tiering, so counts_by_tier, total and next_up all follow the narrowed
    set rather than being computed against the whole book and then sliced.

    Feedback Round 1, WP7 (B2): only_tier, payment_status, dc_status, product and q
    narrow the desk the same way, before next_up, the partition and the total. The
    route validates every value first (routers/today.py); build() trusts its input.
    `meta.tier_counts` counts under every filter EXCEPT only_tier, so the tier filter's
    own options can say what each tier would show (with no tier filter it equals
    counts_by_tier). `meta.officer_totals` is each officer's whole list today.

    Feedback round 2 (TASK-108 / TASK-118): `unassigned` keeps only rows with no
    officer; every item carries `worked_today` / `worked_at` and `meta` carries
    `worked_today_count`, `unassigned_total` and the per-officer `daily_summary`."""
    from .routers.journey import _work_item, _aggregate
    business_date = business_date or settings.business_date
    jstate = journey.for_current()
    cs = cases_domain.for_current()
    offsets = cases_domain.reminder_offsets()
    waiting_by_customer = {}
    for it in cs.today_items:
        if not it["done"]:
            waiting_by_customer.setdefault(it["customer_uid"], []).append(it)
    if _peak_waiting is None:
        for rec in pkd.for_current().documents.values():
            if rec["state"] == "REJECTED":
                waiting_by_customer.setdefault(rec.get("customer_uid") or "", []).append(
                    {"kind": "PEAK_REJECTED", "ref": rec["uid"], "text": rec.get("rejection_reason")})
    else:
        for uid, entries in _peak_waiting.items():
            waiting_by_customer.setdefault(uid, []).extend(entries)
    items = []
    reminders = []
    needle = (q or "").strip().lower() or None
    tier_counts = {t: 0 for t in TIERS}
    # The 2026-09-19 ruling serves crm.lead identities beside the book. They carry no
    # contract, so they are not queue work; meta.identities says how many stand in
    # the Book, and the screen prints that sentence rather than listing them here.
    identities = 0 if _rows_only else len(journey.identity_customers())
    for customer in journey.book_customers() if _customers is None else _customers:
        case = cs.cases.get(customer.uid)
        if case is None:
            continue
        if entity and (customer.contracts[0].entity if customer.contracts else None) != entity:
            continue
        if officer and case["officer_uid"] != officer:
            continue
        if unassigned and case["officer_uid"]:
            continue
        if case["payment_status"] in ("CLOSED", "TERMINATED"):
            continue
        # B2: the case-level filters, before the work item is built — they need no money.
        # The search matches what the Work Book's search matches: name, VOLT ID, customer no.
        if payment_status and case["payment_status"] != payment_status:
            continue
        if dc_status and case["dc_status"] != dc_status:
            continue
        if needle and not (needle in (customer.display_name or "").lower()
                           or needle in (case["volt_id"] or "").lower()
                           or needle in (customer.customer_no or "").lower()):
            continue
        item = _work_item(jstate, customer, business_date, case_state=cs)
        # Round-4 F2-CR-1: filtered BEFORE tiering, so everything downstream (missed,
        # tier_for, the sort, the partition, elsewhere, unlocked, next_up) sees only
        # the narrowed set — never a screen headed "filtered" over an unfiltered total.
        if ladder_indicative and (item.get("ladder") or {}).get("indicative") != ladder_indicative:
            continue
        if product and product_of(item, case) != product:
            continue
        missed = max((journey.missed_count(k) for k in customer.contracts), default=0)
        missed, missed_basis_th, missed_basis_en = missed_equivalent(customer, item, missed)
        waiting = waiting_by_customer.get(customer.uid, [])
        tier, reason_th, reason_en = tier_for(case, item, missed, business_date, waiting,
                                              missed_basis=(missed_basis_th, missed_basis_en) if missed_basis_th else None,
                                              customer=customer)
        # B2: counted before the tier filter — these are the tier options' own numbers.
        tier_counts[tier] += 1
        if only_tier and tier != only_tier:
            continue
        item["tier"] = tier
        item["tier_rank"] = TIER_RANK[tier]
        # Round-4 J4-29: a cash book has no monthly instalments to miss, so the chip an
        # officer reads first must not tell it that it missed eleven of them. The tier is
        # the same tier; its NAME follows the book it is describing.
        item["missed_basis"] = "CASH_EQUIVALENT" if missed_basis_th else "INSTALMENT"
        item["missed_count_label_th"] = ("%d งวดเทียบเท่า" % missed) if missed_basis_th else ("%d งวด" % missed)
        item["missed_count_label_en"] = ("%d equivalent instalments" % missed) if missed_basis_th else ("%d instalments" % missed)
        item["tier_label_th"] = TIER_LABEL_TH_CASH.get(tier, TIER_LABEL_TH[tier]) if missed_basis_th \
            else TIER_LABEL_TH[tier]
        item["tier_label_en"] = TIER_LABEL_EN_CASH.get(tier, TIER_LABEL_EN[tier]) if missed_basis_th \
            else TIER_LABEL_EN[tier]
        item["tier_reason_th"] = reason_th
        item["tier_reason_en"] = reason_en
        item["priority_reason"] = tier
        item["case"] = _case_summary(case, cs)
        item["waiting"] = waiting
        item["answers_waiting"] = len(waiting)
        item["missed_count"] = missed
        item["missed_basis_th"] = missed_basis_th
        item["missed_basis_en"] = missed_basis_en
        item["next_action_tiering"] = next_action_tiering(case, tier, business_date)
        # Round-4 F3 BE-1 / J4-32: the same count the case page and the review card
        # already carry, so a row need not be opened to see a repeat failure.
        item["unreachable_run"] = cases_domain.unreachable_run(cs, customer.uid)
        items.append(item)
        if (case["payment_status"] != "PENDING" and case["next_action"] == "SEND_REMINDER"
                and case["next_action_on"] <= str(business_date)):
            reminders.append({"customer_uid": customer.uid, "display_name": customer.display_name,
                              "due_on": case["next_action_on"],
                              "kind": "D-%d" % offsets[0] if case["payment_status"] == "CURRENT" else "D0"})
    # Projection refresh derives selected rows through this same financial/tier
    # engine. Its caller keeps the generation's portfolio metadata and never
    # needs to count, sort or scan the unrelated collection queue.
    if _rows_only:
        return {"items": items}
    # Round-2 settasak S2-07: inside a tier the oldest debt comes first (DPD desc), then
    # the biggest arrears — an NPL at DPD 74 sits above a DPD-13 single instalment.
    items.sort(key=lambda i: (i["tier_rank"], -(i["oldest_dpd"] or 0), -Decimal(i["aggregate_overdue"]), i["customer"]["display_name"]))
    partition = {t: sum(1 for i in items if i["tier"] == t) for t in TIERS}
    answers_waiting = sum(1 for i in items if i["waiting"])
    # Round-3 J3-04: the chips must PARTITION the list. counts_by_tier is now the
    # partition and sums to meta.total; the answers that sit in a HIGHER tier are
    # reported separately as answers_waiting_elsewhere, with the sentence the screen
    # prints beside the รอคำตอบ chip. (S2-08 kept: no answer is hidden, it is named.)
    counts = dict(partition)
    elsewhere = answers_waiting - partition["ANSWER_WAITING"]
    unlocked = [i for i in items if i["contact_lock"]["state"] == "OPEN" and i["tier"] != "ROUTINE"] \
        or [i for i in items if i["contact_lock"]["state"] == "OPEN"]
    # Round-4 F1-BE2: computed off `items`, already carrying `item["case"]` — no extra
    # pass, no extra store read. Fires only when THIS filtered set actually carries
    # promise history and none of it shows as kept (see PTP_HISTORY_NOTE_TH above).
    _hist = any((i["case"]["broken_ptp_count"] or 0) > 0 or i["case"]["open_ptp"] for i in items)
    _none_kept = all((i["case"]["kept_ptp_count"] or 0) == 0 for i in items)
    return {
        "run": {"business_date": str(business_date), "job": "today", "officer": officer,
                "ordering": "PTP due today · broken PTP · next action due · two missed · new arrears · answers waiting · routine (REQ-COL-071); within a tier oldest DPD then largest arrears"},
        "items": items,
        "meta": {"total": len(items), "counts_by_tier": counts, "tier_partition": partition,
                 "identities": identities,
                 "identities_note_th": ("อีก %d รายมาจาก Odoo และยังไม่มียอดเงิน — อยู่ในสมุดงาน (ลูกค้า)" % identities) if identities else None,
                 "identities_note_en": ("%d more come from Odoo with no money row yet — they are in the Book" % identities) if identities else None,
                 "answers_waiting": answers_waiting,
                 "answers_waiting_elsewhere": elsewhere,
                 "answers_waiting_elsewhere_note_th": ("รวมอยู่ในขั้นอื่น %d" % elsewhere) if elsewhere else None,
                 "answers_waiting_elsewhere_note_en": ("%d counted in other tiers" % elsewhere) if elsewhere else None,
                 # Round-5 N5-05: a field name is not Thai. The sentence says the fact in words.
                 "counts_note_th": ("ชิปแต่ละขั้นรวมกันได้เท่ากับจำนวนรายการทั้งหมด "
                                    "รายการที่มีคำตอบรออยู่แต่ถูกจัดในขั้นที่สูงกว่า จะนับไว้ในขั้นนั้นและบอกไว้ใต้ชิป รอคำตอบ"),
                 "counts_note_en": COUNTS_NOTE_EN,
                 "next_up": unlocked[0]["customer"]["uid"] if unlocked else None,
                 "reminder_batch": reminders, "reminder_offsets": offsets, "tiers": list(TIERS),
                 "tier_labels_th": dict(TIER_LABEL_TH), "tier_labels_en": dict(TIER_LABEL_EN),
                 # J4-29: the row's own tier_label_th already carries this; the map is
                 # here so a chip can say it too when every row under it is a cash book.
                 "tier_labels_th_cash": dict(TIER_LABEL_TH_CASH), "tier_labels_en_cash": dict(TIER_LABEL_EN_CASH),
                 # Round-4 F1-BE2: null, never an empty string, when the condition
                 # does not hold — a client tells "no note" from "old server".
                 "ptp_history_note_th": PTP_HISTORY_NOTE_TH if (_hist and _none_kept) else None,
                 "ptp_history_note_en": PTP_HISTORY_NOTE_EN if (_hist and _none_kept) else None,
                 # Round-4 F2-CR-1: the deck's calendar, not this desk's data — always
                 # 6, never varies by officer/session/band set. Echoed so a client can
                 # assert the filter it sent is the filter that ran (R4-F56's class).
                 "ladder_rungs": ladder_mod.ladder_rungs(),
                 "ladder_indicative": ladder_indicative,
                 # Feedback Round 1, WP7 (B2): the filter bar's served numbers and the
                 # filters that actually ran, echoed the way ladder_indicative is above.
                 "tier_counts": tier_counts,
                 "officer_totals": officer_totals(cs, known_officers(cs), entity),
                 "officer_totals_note_th": OFFICER_TOTALS_NOTE_TH,
                 "officer_totals_note_en": OFFICER_TOTALS_NOTE_EN,
                 # Feedback round 2 (TASK-108): the unassigned count over the whole
                 # book. The worked flags and daily summary are added by GET
                 # /v1/today alone (annotate_worked below): build()'s rows are shared
                 # with the workbook, whose key set is pinned (test_round4.py:782).
                 "unassigned_total": unassigned_total(cs, entity),
                 "filters": {"officer": officer, "tier": only_tier, "payment_status": payment_status,
                             "dc_status": dc_status, "product": product, "entity": entity, "q": needle}},
    }


def _case_summary(case, cs):
    ptp = cs.ptps.get(case["open_ptp_uid"]) if case["open_ptp_uid"] else None
    issue = cs.issues.get(case["open_issue_uid"]) if case["open_issue_uid"] else None
    return {
        "uid": case["uid"], "payment_status": case["payment_status"], "dc_status": case["dc_status"],
        "payment_status_confirmed": case.get("payment_status_confirmed"),
        "payment_pending_since": case.get("payment_pending_since"),
        "payment_pending_count": case.get("payment_pending_count", 0),
        "payment_pending_amount": case.get("payment_pending_amount", "0.00"),
        "payment_pending_uids": list(case.get("payment_pending_uids") or []),
        "npl_type": case["npl_type"],
        # Round-4 J4-12: who classified this customer and why, on the row itself.
        "npl_type_set_by": case.get("npl_type_set_by"), "npl_type_reason": case.get("npl_type_reason"),
        "npl_type_set_by_role": case.get("npl_type_set_by_role"), "npl_type_set_on": case.get("npl_type_set_on"),
        # Round-4 J4-07: the ticket's deadline travels beside the officer's next action.
        "ticket_deadline": case.get("ticket_deadline"), "ticket_deadline_note_th": case.get("ticket_deadline_note_th"), "ticket_deadline_note_en": case.get("ticket_deadline_note_en"),
        "next_action": case["next_action"], "next_action_on": case["next_action_on"],
        "next_action_set_by": case["next_action_set_by"], "last_contact_at": case["last_contact_at"],
        "last_contact_by": case["last_contact_by"], "last_result": case["last_result"],
        "broken_ptp_count": case["broken_ptp_count"], "kept_ptp_count": case["kept_ptp_count"],
        "renegotiation_count": case["renegotiation_count"], "power_state": case["power_state"],
        "review_uid": case["review_uid"], "open_ptp": ptp, "open_issue": issue,
        "sheet": case["sheet"], "volt_id": case["volt_id"], "officer_uid": case["officer_uid"],
        "dc_status_set_by": case.get("dc_status_set_by"), "dc_status_reason_th": case.get("dc_status_reason_th"), "dc_status_reason_en": case.get("dc_status_reason_en"),
        "power_state_label_th": cases_domain.POWER_STATE_LABEL_TH.get(case["power_state"], case["power_state"]),
        # Language pass: the English twin, when cases.py serves one.
        "power_state_label_en": cases_domain.POWER_STATE_LABEL_EN.get(case["power_state"], case["power_state"]),
    }

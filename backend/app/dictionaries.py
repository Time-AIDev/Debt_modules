"""Governed dictionaries — REQ-CFG-020 (Requirements Amendment v2.6).

Six business lists, seeded verbatim from the New Order Master's own vocabulary so
the officers see the words they already use. A value is never hard-deleted: it is
deactivated and stays readable on history. Codes are stable; labels are what change.

The DC_STATUS list is exactly the sheet's dropdown, in the sheet's order. The
CONTACT_RESULT list starts with the three values the LINE tooling writes into the
MapLog string, because those are the ones the migration will import.
"""
from collections import OrderedDict

from .session import Store

DICTIONARIES = ("DC_STATUS", "CONTACT_RESULT", "NEXT_ACTION", "REVIEW_REASON",
                "NPL_TYPE", "DELAY_CAUSE", "REVIEW_DECISION", "TERMINATION_CAUSE")


def _v(code, th, en, **extra):
    row = OrderedDict(code=code, label_th=th, label_en=en, active=True)
    row.update(extra)
    return row


SEED = {
    "DC_STATUS": [
        _v("NO_ACTION", "ยังไม่ดำเนินการ", "No Action"),
        _v("UNREACHABLE", "ติดต่อไม่ได้", "Unreachable"),
        _v("EXTEND_PAYMENT_TO", "ขอเลื่อนชำระ", "Extend Payment To"),
        _v("CONTACT_BACK", "ให้ติดต่อกลับ", "Contact Back"),
        _v("TECH_ISSUE", "ปัญหาระบบ", "Tech Issue"),
        _v("POWER_CUTOFF", "ตัดระบบไฟ", "Power Cutoff"),
        _v("POWER_BILL_ISSUE", "ปัญหาบิลค่าไฟ", "Power Bill Issue"),
        _v("RESTRUCTURE_LOAN", "ปรับโครงสร้างหนี้", "Restructure Loan"),
        _v("LEGAL_LETTER", "ส่งหนังสือทนาย", "Legal Letter"),
        _v("RETRIEVE_ASSET", "ยึดคืนอุปกรณ์", "Retrieve Asset"),
        _v("VISIT_CUSTOMER", "ลงพื้นที่พบลูกค้า", "Visit Customer"),
        _v("TERMINATE_CONTRACT", "บอกเลิกสัญญา", "Terminate Contract"),
        _v("PTP", "นัดชำระ", "PTP"),
        _v("PAID", "ชำระแล้ว", "Paid"),
    ],
    # Round-3 J3-31: every result already said whether it spends the day's slot; what was
    # missing is WHY an answered call can be "ไม่นับ". The Act's one-contact-a-day slot is
    # spent by DISCUSSING the debt, not by the phone being picked up — so each value
    # carries counts_reason_th, printed beside its ไม่นับ / นับ label.
    "CONTACT_RESULT": [
        _v("REACHED_ANSWERED", "ติดต่อได้ - รับสาย", "Reached, answered", counts=True,
           counts_reason_th="ได้คุยเรื่องหนี้กับลูกค้า จึงใช้สิทธิ์ติดต่อของวันนี้",
           counts_reason_en="The debt was discussed with the customer, so today's contact is used"),
        _v("UNREACHABLE_NO_ANSWER", "ติดต่อไม่ได้ - ไม่รับสาย", "Unreachable, no answer", counts=False,
           counts_reason_th="ไม่ได้คุยกับลูกค้า จึงยังไม่ใช้สิทธิ์ติดต่อของวันนี้",
           counts_reason_en="No conversation with the customer, so today's contact is not used yet"),
        _v("REACHED_PTP", "ติดต่อได้ (โทรศัพท์) - นัดชำระ", "Reached by phone — PTP", counts=True,
           counts_reason_th="ได้คุยและตกลงนัดชำระ จึงใช้สิทธิ์ติดต่อของวันนี้",
           counts_reason_en="A payment appointment was agreed, so today's contact is used"),
        _v("PROMISED", "ติดต่อได้ (LINE) - นัดชำระ", "Reached on LINE — PTP", counts=True,
           counts_reason_th="ได้คุยเรื่องหนี้และลูกค้ารับปาก จึงใช้สิทธิ์ติดต่อของวันนี้",
           counts_reason_en="The debt was discussed and the customer promised, so today's contact is used"),
        _v("SERVICE_ISSUE", "แจ้งปัญหาระบบ", "Reported a service issue", counts=True,
           counts_reason_th="ได้คุยกับลูกค้าแล้ว จึงใช้สิทธิ์ติดต่อของวันนี้",
           counts_reason_en="The customer was spoken to, so today's contact is used"),
        _v("REFUSED_PAY", "ปฏิเสธชำระ", "Refused to pay", counts=True, flag=True,
           counts_reason_th="ได้คุยเรื่องหนี้แล้ว แม้ลูกค้าปฏิเสธ ก็ใช้สิทธิ์ติดต่อของวันนี้",
           counts_reason_en="The debt was discussed; even though the customer refused, today's contact is used"),
        _v("INCONVENIENT", "ไม่สะดวกคุย", "Inconvenient, retry", counts=False,
           counts_reason_th="รับสายแต่ยังไม่ได้คุยเรื่องหนี้ กฎหมายนับ 1 ครั้งต่อวันจากการทวงถาม ไม่ใช่จากการรับสาย",
           counts_reason_en="The call was answered but the debt was not discussed; the law counts one collection conversation a day, not an answered call"),
        _v("CALLBACK_REQUESTED", "ขอให้โทรกลับ", "Asked for a callback", counts=False,
           counts_reason_th="รับสายแต่ขอให้โทรกลับ ยังไม่ได้ทวงถาม จึงยังไม่ใช้สิทธิ์ติดต่อของวันนี้",
           counts_reason_en="Answered but asked for a callback; nothing was collected, so today's contact is not used yet"),
        _v("LINE_READ", "ส่ง LINE แล้ว อ่านแล้ว", "LINE sent and read", counts=True,
           counts_reason_th="ลูกค้าอ่านข้อความทวงถามแล้ว จึงใช้สิทธิ์ติดต่อของวันนี้",
           counts_reason_en="The customer read the reminder message, so today's contact is used"),
        _v("LINE_SENT_UNREAD", "ส่ง LINE แล้ว ยังไม่อ่าน", "LINE sent, unread", counts=False,
           counts_reason_th="ลูกค้ายังไม่อ่าน จึงยังไม่ถือว่าติดต่อได้",
           counts_reason_en="The customer has not read it, so this does not count as reached"),
        _v("INBOUND", "ลูกค้าติดต่อเข้ามา", "Inbound from the customer", counts=False,
           counts_reason_th="ลูกค้าเป็นฝ่ายติดต่อเข้ามา ไม่ใช่การทวงถามของเรา จึงไม่ใช้สิทธิ์ของวันนี้",
           counts_reason_en="The customer contacted us, not a collection call, so today's contact is not used"),
    ],
    "NEXT_ACTION": [
        _v("CALL", "โทรติดตาม", "Call"),
        _v("CALLBACK", "โทรกลับตามที่ลูกค้าขอ", "Call back as asked"),
        _v("LINE_FOLLOW_UP", "ติดตามทาง LINE", "Follow up on LINE"),
        _v("FOLLOW_PTP", "ตรวจสอบยอดตามนัด", "Check payment on the promise date"),
        _v("SEND_REMINDER", "ส่งแจ้งเตือน", "Send a reminder"),
        _v("SEND_INVOICE_LINK", "ส่งลิงก์ใบแจ้งหนี้", "Send the invoice link"),
        _v("CONFIRM_SLIP", "ตรวจสลิป", "Confirm the slip"),
        _v("AWAIT_TICKET", "รอทีมแก้ปัญหา", "Await the ticket"),
        _v("AWAIT_REVIEW", "รอผู้จัดการตอบ", "Await the review answer"),
        _v("AWAIT_PEAK", "รอ AR อนุมัติใน PEAK", "Await PEAK approval"),
        _v("VISIT", "ลงพื้นที่", "Visit"),
        _v("ESCALATE", "ส่งต่อผู้จัดการ", "Escalate"),
        _v("NONE_CLOSED", "ปิดเคส ไม่มีงานต่อ", "Closed, nothing further"),
    ],
    "REVIEW_REASON": [
        _v("NO_COMMITMENT", "ลูกค้าไม่ให้คำตอบ", "No commitment"),
        _v("REPEATED_BROKEN_PTP", "ผิดนัดซ้ำ", "Repeated broken PTP"),
        _v("UNREACHABLE", "ติดต่อไม่ได้ต่อเนื่อง", "Unreachable"),
        _v("DISPUTE", "ลูกค้าโต้แย้ง", "Dispute"),
        _v("RESTRUCTURE_ASK", "ขอปรับโครงสร้าง", "Restructure request"),
        _v("POWER_CUTOFF_ASK", "ขออนุมัติตัดระบบ", "Power cut-off approval"),
        _v("NPL_TYPE_ASK", "ขอกำหนดประเภท NPL", "NPL type decision"),
        _v("NPL_REVIEW", "ตรวจทบทวนเกณฑ์ NPL", "NPL threshold review"),
        _v("BOARD_MOVE_ASK", "ขออนุมัติย้ายคอลัมน์", "Board move approval"),
        _v("OTHER", "อื่น ๆ", "Other"),
    ],
    "REVIEW_DECISION": [
        _v("CONTINUE", "ติดตามต่อ", "Continue follow-up"),
        _v("ARRANGEMENT", "ตกลงแผนผ่อนค้าง", "Arrangement on arrears"),
        _v("RESTRUCTURE_PROPOSE", "เสนอปรับโครงสร้าง", "Propose a restructure"),
        _v("POWER_CUTOFF_APPROVE", "อนุมัติตัดระบบ", "Approve power cut-off"),
        # Round-3 J3-06: a cut-off request is DECIDED — approve or reject — never
        # "answered" with ติดตามต่อ while the request stays unapproved.
        _v("POWER_CUTOFF_REJECT", "ปฏิเสธการตัดระบบ", "Reject the power cut-off"),
        # Spec 2026-09-09: their own pair, never the POWER_CUTOFF_* codes — cutting a
        # customer's power must not be selectable as the answer to a board request.
        _v("BOARD_MOVE_APPROVE", "อนุมัติย้ายคอลัมน์", "Approve the board move"),
        _v("BOARD_MOVE_REJECT", "ปฏิเสธการย้ายคอลัมน์", "Reject the board move"),
        _v("NPL_TYPE_SET", "กำหนดประเภท NPL", "Set the NPL type"),
        _v("LEGAL_REFER", "ส่งฝ่ายกฎหมาย", "Refer to Legal"),
        _v("OTHER", "อื่น ๆ", "Other"),
    ],
    "NPL_TYPE": [
        _v("NPL_1_RESTRUCTURE", "NPL 1 - ปรับโครงสร้าง", "NPL 1 - Restructure"),
        _v("NPL_2_COOPERATIVE_DECOMMISSION", "NPL 2 - ให้ความร่วมมือ ถอดระบบ", "NPL 2 - Cooperative - Decommission"),
        _v("NPL_3_UNCOOPERATIVE_LEGAL", "NPL 3 - ไม่ให้ความร่วมมือ ดำเนินคดี", "NPL 3 - Uncooperative - Legal action"),
    ],
    # 2026-09-20 (Closed/Terminated ruling): why a contract ended. The two scenarios
    # the business runs, named the way the sheet's categories name them.
    "TERMINATION_CAUSE": [
        _v("DEFAULT", "ผิดสัญญา / ยึดคืน", "Default — VOLT ends it"),
        _v("CUSTOMER_REQUEST", "ลูกค้าขอยุติ", "Customer request"),
    ],
    "DELAY_CAUSE": [
        _v("CUSTOMER_CASHFLOW", "ลูกค้าขาดสภาพคล่อง", "Customer cash flow", group="CUSTOMER"),
        _v("CUSTOMER_FORGOT", "ลูกค้าลืม", "Customer forgot", group="CUSTOMER"),
        _v("CUSTOMER_DISPUTE", "ลูกค้าโต้แย้ง", "Customer dispute", group="CUSTOMER"),
        _v("VOLT_SERVICE_ISSUE", "ระบบมีปัญหา รอแก้", "Service issue at VOLT", group="VOLT"),
        _v("VOLT_INVOICE_ERROR", "ใบแจ้งหนี้ผิด", "Invoice error", group="VOLT"),
        _v("VOLT_PERMIT", "รอใบอนุญาต การไฟฟ้า", "Permit or utility delay", group="VOLT"),
        _v("EXTERNAL_BANK", "ธนาคาร/ช่องทางชำระ", "Bank or channel", group="EXTERNAL"),
        _v("UNASSESSED", "ยังไม่ประเมิน", "Not yet assessed", group="UNASSESSED"),
    ],
}

# Sheet spellings -> codes, so migration and the API accept what the team types.
ALIASES = {
    "DC_STATUS": {
        "No Action": "NO_ACTION", "Unreachable": "UNREACHABLE", "Extend Payment To": "EXTEND_PAYMENT_TO",
        "Contact Back": "CONTACT_BACK", "Tech Issue": "TECH_ISSUE", "Technical Issue": "TECH_ISSUE",
        "Power Cutoff": "POWER_CUTOFF", "Power Bill Issue": "POWER_BILL_ISSUE",
        "Restructure Loan": "RESTRUCTURE_LOAN", "Legal Letter": "LEGAL_LETTER",
        "Retrieve Asset": "RETRIEVE_ASSET", "Visit Customer": "VISIT_CUSTOMER",
        "Terminate Contract": "TERMINATE_CONTRACT", "PTP": "PTP", "Paid": "PAID",
        "1st Notice": "NO_ACTION", "3rd Notice": "NO_ACTION", "NPL - Collect": "RETRIEVE_ASSET",
    },
    "TERMINATION_CAUSE": {
        "Terminated - Default": "DEFAULT", "Default": "DEFAULT",
        "Terminated - Customer request": "CUSTOMER_REQUEST", "Customer Request": "CUSTOMER_REQUEST",
    },
    "NPL_TYPE": {
        "NPL 1 - Restructure": "NPL_1_RESTRUCTURE",
        "NPL 2 - Cooperative - Decommission": "NPL_2_COOPERATIVE_DECOMMISSION",
        "NPL 2- Payment Arrangement": "NPL_2_COOPERATIVE_DECOMMISSION",
        "NPL 3 - Uncooperative - Legal action": "NPL_3_UNCOOPERATIVE_LEGAL",
        "NPL 4 - Uncooperative - Legal action": "NPL_3_UNCOOPERATIVE_LEGAL",
    },
}


class DictionaryError(Exception):
    def __init__(self, dictionary, code):
        super().__init__("%s has no value %r" % (dictionary, code))
        self.dictionary = dictionary
        self.code = code


class Dictionaries:
    """Per-session copy of the seed so a tester's edits never leak to another."""

    def __init__(self):
        self.values = {name: [dict(v) for v in rows] for name, rows in SEED.items()}
        self.history = []

    def list(self, name, include_inactive=False):
        if name not in self.values:
            raise DictionaryError(name, None)
        rows = self.values[name]
        return [r for r in rows if include_inactive or r["active"]]

    def get(self, name, code):
        for r in self.values.get(name, []):
            if r["code"] == code:
                return r
        return None

    def resolve(self, name, raw):
        """Accept a code or a sheet spelling. Returns the code or raises."""
        if raw is None or raw == "":
            return None
        if self.get(name, raw) is not None:
            return raw
        alias = ALIASES.get(name, {}).get(raw)
        if alias and self.get(name, alias) is not None:
            return alias
        raise DictionaryError(name, raw)

    def label(self, name, code, lang="th"):
        row = self.get(name, code)
        if row is None:
            return code
        return row["label_th"] if lang == "th" else row["label_en"]

    def add(self, name, code, label_th, label_en, by):
        if name not in self.values:
            raise DictionaryError(name, None)
        if self.get(name, code) is not None:
            raise ValueError("duplicate code %s" % code)
        row = _v(code, label_th, label_en)
        row["created_by"] = by
        self.values[name].append(row)
        self.history.append({"dictionary": name, "code": code, "act": "ADD", "by": by})
        return row

    def deactivate(self, name, code, by):
        row = self.get(name, code)
        if row is None:
            raise DictionaryError(name, code)
        row["active"] = False
        row["deactivated_by"] = by
        self.history.append({"dictionary": name, "code": code, "act": "DEACTIVATE", "by": by})
        return row


_store = Store(Dictionaries, key="dictionaries.state")


def for_current() -> Dictionaries:
    return _store.for_current()


def reset():
    _store.reset()

"""The seventeen-step SOP, as a position a case can stand on.

The team's own SOP — the docx, the four flowcharts in `docs/assets/SOP/`, and the
seventeen-step workflow — is **rank 2 on the authority ladder** (Requirements
Amendment v2.6 §1), second only to the 2026-09-01 interview and above the PRD, the
API surface and every amendment below v2.6. It has existed on disk since the rebuild
and **nowhere in the product**: the officer carries the seventeen steps in her head.

This module says which step a case stands on, the one act that moves it, and the
branches the flowcharts draw from that point. It is the answer to SOP §10, the
Minimum Recording Standard, whose closing line is the whole reason this file exists:

    Principle: No case without Next Action.

Three boundaries, each of which a reviewer should be able to check mechanically:

1. **It states a step; it never operates a gate.** SOP §6's open decision D26 — "is
   pre-installation invoicing (steps 1–8) Debt's work, AR's, or split, and should the
   module operate the gate the team already runs by hand?" — is the Owner's and holds
   up eight of the seventeen. Those eight are marked `operated_by: "TEAM"` and carry
   the open decision with them. Every `control` this module names is a route that
   already exists; it mints none. `test_sop_walkthrough.py` enforces that product-wide.

2. **It never answers a deliberate refusal.** It carries no money at all — one integer,
   the step index — so OD-02 (allocation order) and OD-03 (payoff) cannot be answered
   by arithmetic that is not here. Step 16 is placed only from human-set state, never
   from DPD or from a ladder rung, so OD-04 (the NPL policy value) stays open: the
   ladder is carried as an *indicative hint* and is never a placement input.

3. **It does not guess.** Where the served state does not determine a step the answer
   is `UNPLACED` with the candidates it considered and why each did not match. There
   is no default step and step 1 is never a fallback. Contract §1a: a binding that
   renders a confident wrong value is graded ABOVE one that renders a visible blank,
   and a wrong step number is exactly that failure.

The one caller is `routers/today.py` — `case_detail` and `_pre_install_case_detail`.
It is deliberately NOT on `_work_item` or the workbook row: `test_round4.py:775`
asserts exactly seven keys differ between a normal and a CLOSED workbook row, and a
key added there would make the septet an eight and fail it.
"""

# The seventeen, in the SOP's own order (Collection Workflow Alignment v3.0 §2).
# `placeable` is False where no case can ever *stand* on the step — see the notes.
# Order is pinned by a test: contract §3 forbids a UX change reordering a workflow step.
STEPS = (
    {"step": 1, "code": "CHECK_INSTALL_PLAN", "lane": "COLLECTION", "placeable": True,
     "name_th": "ตรวจแผนติดตั้ง", "name_en": "Check the installation plan",
     "gate_rule": "pipeline_lookahead_days",
     "gate_rule_th": "ออร์เดอร์ที่จะติดตั้งในสามวันข้างหน้าขึ้นมาพร้อมชนิดสัญญาและยอดที่ต้องเก็บ",
     "gate_rule_en": "Orders installing in the next three days come up with the contract type and the amount to collect",
     "screens": ("PIPELINE",)},
    {"step": 2, "code": "PREPARE_INVOICE_DATA", "lane": "COLLECTION_AR", "placeable": True,
     "name_th": "เตรียมข้อมูลใบแจ้งหนี้", "name_en": "Prepare the invoice data",
     "gate_rule": "gate 1 down payment received; gate 2 EPC confirmed date",
     "gate_rule_th": "ด่าน 1 ได้รับเงินดาวน์ · ด่าน 2 EPC ยืนยันวันติดตั้ง — ขาดอย่างใดอย่างหนึ่งปล่อยใบแจ้งหนี้ไม่ได้",
     "gate_rule_en": "Gate 1 down payment received · gate 2 EPC confirmed the install date — without both the invoice cannot be released",
     "screens": ("PIPELINE",)},
    {"step": 3, "code": "ISSUE_INVOICE", "lane": "INVOICE_OWNER", "placeable": True,
     "name_th": "ออกใบแจ้งหนี้", "name_en": "Issue the invoice",
     "gate_rule": "REQ-INV-003, REQ-ACC-030",
     "gate_rule_th": "การปล่อยประทับชื่อนิติบุคคล สร้างร่างใบแจ้งหนี้ใน PEAK แล้ว AR เป็นผู้อนุมัติใน PEAK",
     "gate_rule_en": "Release stamps the legal entity and creates a draft invoice in PEAK; AR approves it in PEAK",
     "screens": ("PIPELINE", "PAYMENTS")},
    {"step": 4, "code": "DELIVER_INVOICE", "lane": "COLLECTION", "placeable": True,
     "name_th": "ส่งใบแจ้งหนี้ให้ลูกค้า", "name_en": "Deliver the invoice",
     "gate_rule": "REQ-INV-004",
     "gate_rule_th": "ส่งลิงก์ทาง LINE หรืออีเมล บันทึกช่องทาง เวลา และผู้ส่ง",
     "gate_rule_en": "Send the link by LINE or email; record the channel, the time and the sender",
     "screens": ("PIPELINE", "CUSTOMER_CASE")},
    {"step": 5, "code": "CHECK_INSTALL_DAY", "lane": "COLLECTION", "placeable": True,
     "name_th": "ตรวจวันติดตั้ง", "name_en": "Check on installation day",
     "gate_rule": "REQ-INV-005",
     "gate_rule_th": "ติดตั้ง เลื่อน หรือยกเลิก — การเลื่อนหลังออกใบแจ้งหนี้บังคับให้เลือกคงไว้ แก้ไข หรือยกเลิกแล้วออกใหม่",
     "gate_rule_en": "Installed, postponed or cancelled — a postponement after invoicing requires choosing to keep, amend, or cancel and reissue",
     "screens": ("PIPELINE",)},
    {"step": 6, "code": "RECEIPT_AND_MATCHING", "lane": "AR_COLLECTION", "placeable": True,
     "name_th": "รับเงินและจับคู่ใบเสร็จ", "name_en": "Receipt and matching",
     "gate_rule": "REQ-ACC-034",
     "gate_rule_th": "สลิปที่ยืนยันแล้วสร้างร่างใบเสร็จ AR อนุมัติ เคสอ่านสถานะที่อนุมัติแล้ว",
     "gate_rule_en": "A confirmed slip creates a draft receipt; AR approves it; the case reads the approved state",
     "screens": ("PAYMENTS",)},
    # Not placeable: the month's instalments already exist in PEAK and delivery is
    # recorded per month there. The app serves `link_sent_cells` as the SHEET's history,
    # not a live per-month delivery state — no served field says whether THIS month's
    # link went out, so no case can be placed here without inventing one.
    {"step": 7, "code": "MONTHLY_INVOICES", "lane": "COLLECTION", "placeable": False,
     "name_th": "ใบแจ้งหนี้รายเดือน", "name_en": "Monthly invoices",
     "gate_rule": "REQ-INV-004",
     "gate_rule_th": "งวดของเดือนนั้นมีอยู่ใน PEAK แล้ว การส่งบันทึกเป็นรายเดือน",
     "gate_rule_en": "The month's instalments already exist in PEAK; delivery is recorded per month",
     "not_placeable_th": "การส่งรายเดือนอยู่ใน PEAK แอปเก็บเพียงประวัติจากชีต ไม่มีสถานะรายเดือนที่เชื่อถือได้",
     "not_placeable_en": "Monthly delivery lives in PEAK; the app keeps only the sheet's history, with no reliable monthly state",
     "screens": ("CUSTOMER_CASE",)},
    {"step": 8, "code": "REMIND_BEFORE_DUE", "lane": "COLLECTION", "placeable": True,
     "name_th": "เตือนก่อนและวันครบกำหนด", "name_en": "Remind before and on the due date",
     "gate_rule": "Executive Brief stage 3",
     "gate_rule_th": "เตือน D-3 และ D0 จากเทมเพลต — เป็นการแจ้งเตือน ไม่นับเป็นการทวงถามตามกฎหมาย",
     "gate_rule_en": "Remind three days before and on the due date from the template — a notice, not a collection contact under the law",
     "screens": ("TODAY", "CUSTOMER_CASE")},
    # Not placeable: lane SYSTEM, the 02:30 batch. Every case in the book is an OUTPUT
    # of step 9; none stands on it.
    {"step": 9, "code": "BUILD_ARREARS_LIST", "lane": "SYSTEM", "placeable": False,
     "name_th": "สร้างรายการค้างชำระ", "name_en": "Build the arrears list",
     "gate_rule": "REQ-COL-071",
     "gate_rule_th": "เวลา 02:30 น. และเมื่อสั่ง แยกตามเจ้าหน้าที่ รวมตามลูกค้า จัดเป็นเจ็ดขั้น",
     "gate_rule_en": "At 02:30 and on demand, per officer, grouped by customer, sorted into seven tiers",
     "not_placeable_th": "ขั้นนี้เป็นงานของระบบ ทุกเคสเป็นผลลัพธ์ของมัน ไม่มีเคสใดยืนอยู่บนขั้นนี้",
     "not_placeable_en": "This step is the system's work; every case is its output and no case stands on it",
     "screens": ("TODAY", "WORKBOOK")},
    {"step": 10, "code": "CONTACT_AND_RECORD", "lane": "COLLECTION", "placeable": True,
     "name_th": "ติดต่อและบันทึกผล", "name_en": "Contact and record",
     "gate_rule": "REQ-COL-072, REQ-COL-070",
     "gate_rule_th": "หนึ่งการทวงถามที่นับได้ต่อลูกค้าต่อวัน ทุกช่องทางรวมกัน · ทุกเคสต้องมีงานถัดไป",
     "gate_rule_en": "One counting contact per customer per day across all channels · every case must have a next action",
     "screens": ("TODAY", "CONTACT_DRAWER")},
    {"step": 11, "code": "RECORD_AND_TRACK_PTP", "lane": "COLLECTION", "placeable": True,
     "name_th": "บันทึกและติดตามนัดชำระ (PTP)", "name_en": "Record and track PTP",
     "gate_rule": "REQ-COL-073",
     "gate_rule_th": "วันและยอดอยู่บนเคส ระบบตัดเป็นผิดนัดเองเมื่อถึงวัน เจรจาใหม่ได้สองครั้ง ครั้งที่สามส่งผู้จัดการ",
     "gate_rule_en": "The date and amount sit on the case; the system marks it broken on the day; two renegotiations allowed, the third goes to the manager",
     "screens": ("CONTACT_DRAWER", "TODAY")},
    {"step": 12, "code": "SERVICE_COMPLAINT", "lane": "COLLECTION_CS", "placeable": True,
     "name_th": "แจ้งปัญหาบริการ", "name_en": "Service complaint",
     "gate_rule": "REQ-COL-076",
     "gate_rule_th": "ใบแจ้งปัญหามีลิงก์ ทีมผู้รับผิดชอบ และกำหนดเสร็จ · นาฬิกาค่าปรับหยุดเดิน · ปิดงานแล้วกลับมาที่เจ้าหน้าที่",
     "gate_rule_en": "The ticket has a link, an owning team and a due date · the late-fee clock stops · when closed it returns to the officer",
     "screens": ("CONTACT_DRAWER", "CUSTOMER_CASE")},
    {"step": 13, "code": "CANNOT_BE_REACHED", "lane": "COLLECTION", "placeable": True,
     "name_th": "ติดต่อไม่ได้", "name_en": "Cannot be reached",
     "gate_rule": "REQ-COL-072",
     "gate_rule_th": "บันทึกจำนวนครั้ง วันที่ และช่องทางที่พยายามติดต่อ · ประสานเซลหรือทีมพื้นที่ · ติดต่อไม่ได้ต่อเนื่องส่งผู้จัดการ",
     "gate_rule_en": "Record the attempts, dates and channels · involve sales or the field team · repeated failures go to the manager",
     "screens": ("CONTACT_DRAWER", "TODAY")},
    {"step": 14, "code": "MANAGER_REVIEW", "lane": "MANAGER", "placeable": True,
     "name_th": "ส่งผู้จัดการตรวจ", "name_en": "Manager review",
     "gate_rule": "REQ-COL-074",
     "gate_rule_th": "คำขอพร้อมเหตุผลและคำถาม คำตอบพร้อมคำวินิจฉัยกลับไปหาเจ้าหน้าที่",
     "gate_rule_en": "A request with a reason and a question; the answer with a decision returns to the officer",
     "screens": ("REVIEW_QUEUE", "TODAY")},
    {"step": 15, "code": "ARRANGEMENT_OR_RESTRUCTURE", "lane": "MANAGER", "placeable": True,
     "name_th": "ผ่อนผันหรือปรับโครงสร้างหนี้", "name_en": "Arrangement or restructure",
     "gate_rule": "REQ-RST-001",
     "gate_rule_th": "การผ่อนผันไม่แตะตารางชำระ การปรับโครงสร้างต้องผ่านด่านและมีตัวเลขครบ แล้วจึงยกเลิกร่าง PEAK และลงบัญชี",
     "gate_rule_en": "An arrangement leaves the schedule untouched; a restructure passes its gates with complete figures, then voids the PEAK drafts and posts",
     "screens": ("RECOVERY",)},
    {"step": 16, "code": "NPL_LEGAL_RECOVERY", "lane": "MANAGER", "placeable": True,
     "name_th": "NPL กฎหมาย และการเรียกคืน", "name_en": "NPL, legal and recovery",
     "gate_rule": "REQ-COL-075, REQ-RCV-001..003",
     "gate_rule_th": "ผู้จัดการกำหนดชนิด NPL · ทีมกฎหมาย ปฏิบัติการ และจัดซื้อเป็นผู้ดำเนินการ",
     "gate_rule_en": "The manager sets the NPL type · legal, operations and procurement carry it out",
     "screens": ("RECOVERY",)},
    # Not placeable: lane LEAD, book-level. It is a report over the book, not a
    # position a single customer occupies.
    {"step": 17, "code": "REPORT", "lane": "LEAD", "placeable": False,
     "name_th": "รายงาน", "name_en": "Report",
     "gate_rule": "REQ-KPI-020, REQ-KPI-021",
     "gate_rule_th": "รายงานประจำสัปดาห์ในรูปแบบที่ทีมใช้ พร้อมตัวชี้วัดรายเจ้าหน้าที่",
     "gate_rule_en": "The weekly report in the team's own format, with per-officer measures",
     "not_placeable_th": "ขั้นนี้เป็นรายงานระดับทั้งเล่ม ไม่ใช่ตำแหน่งของลูกค้ารายใดรายหนึ่ง",
     "not_placeable_en": "This step is a report over the whole book, not the position of any one customer",
     "screens": ("REPORTS",)},
)

STEP_BY_N = {s["step"]: s for s in STEPS}

# SOP §6's own scope, quoted: "pre-installation invoicing (steps 1–8)".
D26_STEPS = frozenset(range(1, 9))

D26 = {
    "code": "D26",
    "register": "SOP_SEC_6",
    "owner": "Owner",
    "state": "OPEN",
    "question_th": ("ใบแจ้งหนี้ก่อนติดตั้ง (ขั้น 1–8) เป็นงานของทีมติดตามหนี้ ของ AR หรือแบ่งกัน "
                    "— และโมดูลควรทำด่านที่ทีมทำมืออยู่หรือไม่"),
    "question_en": ("Is pre-installation invoicing (steps 1-8) Debt's work, AR's, or split "
                    "— and should the module operate the gate the team already runs by hand?"),
    "effect_th": ("ขั้นนี้เป็นงานที่ทีมทำเอง แอปบอกได้ว่าเคสอยู่ขั้นไหน "
                  "แต่ไม่ได้เพิ่มปุ่มผ่านด่านใหม่"),
    "effect_en": ("The team runs this step by hand. The app says which step the case is on "
                  "but adds no new gate control."),
    "holds_steps": sorted(D26_STEPS),
}

# SOP §6 lists external collection agencies as an open decision. The strategy IS a
# served dictionary value, so the branch is LISTED AND REFUSED rather than hidden —
# contract §3: the refusals stay visible and legible, never tidied away.
D27 = {
    "code": "D27",
    "register": "SOP_SEC_6",
    "owner": "Owner",
    "state": "OPEN",
    "question_th": "การส่งบัญชีให้สำนักงานเร่งรัดหนี้ภายนอกเป็นแนวทางที่ใช้ได้หรือไม่ และใช้เงื่อนไขใด",
    "question_en": "Is handing an account to an external collection agency an available path, and on what terms?",
}

LANE_TH = {
    "COLLECTION": "ทีมติดตามหนี้", "AR": "บัญชีลูกหนี้ (AR)",
    "COLLECTION_AR": "ทีมติดตามหนี้ร่วมกับ AR", "AR_COLLECTION": "AR ร่วมกับทีมติดตามหนี้",
    "COLLECTION_CS": "ทีมติดตามหนี้ส่งต่อ CS / O&M", "INVOICE_OWNER": "เจ้าของใบแจ้งหนี้ (ยังไม่ชี้ขาด)",
    "MANAGER": "ผู้จัดการ / Credit & Risk", "SYSTEM": "ระบบ", "LEAD": "หัวหน้าทีม",
}
LANE_EN = {
    "COLLECTION": "Collection", "AR": "AR", "COLLECTION_AR": "Collection with AR",
    "AR_COLLECTION": "AR with Collection", "COLLECTION_CS": "Collection to CS / O&M",
    "INVOICE_OWNER": "Invoice owner (open)", "MANAGER": "Manager / Credit & Risk",
    "SYSTEM": "System", "LEAD": "Lead",
}

SOURCE = {
    "document": "Collection Workflow Alignment v3.0 §2",
    "authority_rank": 2,
    "note_th": "ลำดับขั้นทั้งสิบเจ็ดเป็น SOP ของทีมเอง ระบบไม่ได้ตั้งขึ้น",
    "note_en": "The seventeen steps are the team's own SOP; the system did not invent them.",
}


def _act(code, label_th, label_en, route=None, control=None,
         available=True, why_th=None, why_en=None):
    return {"code": code, "label_th": label_th, "label_en": label_en,
            "route": route, "control": control, "available": available,
            "unavailable_reason_th": why_th, "unavailable_reason_en": why_en}


def _branch(code, label_th, label_en, leads_to_step, route=None, control=None,
            available=True, why_th=None, why_en=None):
    return {"code": code, "label_th": label_th, "label_en": label_en,
            "leads_to_step": leads_to_step, "route": route, "control": control,
            "available": available, "unavailable_reason_th": why_th,
            "unavailable_reason_en": why_en}


def _placed(n, main_act, branches=None, decided_by=None, decided_by_th=None, decided_by_en=None,
            confidence="DETERMINED", confidence_note_th=None, confidence_note_en=None, ladder_hint=None):
    s = STEP_BY_N[n]
    team = n in D26_STEPS
    return {
        "placement": "PLACED",
        "step": n,
        "step_of": len(STEPS),
        "code": s["code"],
        "name_th": s["name_th"], "name_en": s["name_en"],
        "lane": s["lane"], "lane_th": LANE_TH[s["lane"]], "lane_en": LANE_EN[s["lane"]],
        "gate_rule": s["gate_rule"], "gate_rule_th": s["gate_rule_th"], "gate_rule_en": s["gate_rule_en"],
        "screens": list(s["screens"]),
        "operated_by": "TEAM" if team else "SYSTEM",
        "operated_by_th": ("ขั้นนี้ทีมทำเอง แอปบอกตำแหน่ง ไม่ได้ทำด่านให้"
                           if team else "ระบบทำขั้นนี้ได้"),
        "operated_by_en": ("The team runs this step by hand; the app states the position, "
                           "it does not operate the gate" if team else "The system operates this step"),
        "open_decision": dict(D26) if team else None,
        "confidence": confidence,
        "confidence_note_th": confidence_note_th,
        "confidence_note_en": confidence_note_en,
        "decided_by": list(decided_by or []),
        "decided_by_th": decided_by_th,
        "decided_by_en": decided_by_en,
        "main_act": main_act,
        "branches": list(branches or []),
        "ladder_hint": ladder_hint,
        "source": dict(SOURCE),
    }


def _unplaced(read, candidates, reason_th=None, reason_en=None):
    return {
        "placement": "UNPLACED", "step": None, "step_of": len(STEPS),
        "code": None, "name_th": None, "name_en": None,
        "lane": None, "lane_th": None, "lane_en": None,
        "gate_rule": None, "gate_rule_th": None, "gate_rule_en": None, "screens": [],
        "operated_by": None, "operated_by_th": None, "operated_by_en": None,
        "open_decision": None,
        "confidence": "UNDETERMINED",
        "confidence_note_th": None, "confidence_note_en": None,
        "reason_th": reason_th or "สถานะที่มีอยู่ยังไม่ชี้ขั้นตอนใดขั้นตอนหนึ่ง — ระบบไม่เดา",
        "reason_en": reason_en or "The current state does not point to one step — the system does not guess.",
        "read": read, "candidates": list(candidates),
        "main_act": None, "branches": [], "ladder_hint": None,
        "source": dict(SOURCE),
    }


def _off_journey(read, reason_th, reason_en):
    return {
        "placement": "OFF_JOURNEY", "step": None, "step_of": len(STEPS),
        "code": None, "name_th": None, "name_en": None,
        "lane": None, "lane_th": None, "lane_en": None,
        "gate_rule": None, "gate_rule_th": None, "gate_rule_en": None, "screens": [],
        "operated_by": None, "operated_by_th": None, "operated_by_en": None,
        "open_decision": None,
        "confidence": "DETERMINED", "confidence_note_th": None, "confidence_note_en": None,
        "reason_th": reason_th, "reason_en": reason_en,
        "read": read, "candidates": [],
        "main_act": None, "branches": [], "ladder_hint": None,
        "source": dict(SOURCE),
    }


def _ladder_hint(item):
    """The ladder travels as CONTEXT and is never a placement input.

    OD-04 (the collection NPL policy value) is one of the five standing refusals. A
    rung is indicative by construction and `ladder_mode: MANUAL` suppresses even that
    (R6). Reading a rung to place a case on step 16 would declare NPL automatically,
    which is exactly what OD-04 refuses to decide.
    """
    ladder = (item or {}).get("ladder") or {}
    if not ladder:
        return None
    mode = ladder.get("mode")
    if mode == "MANUAL":
        return {"mode": "MANUAL", "indicative": None, "indicative_th": None,
                "is_indicative": False,
                "note_th": "โหมดกำหนดเอง — ระบบไม่ชี้รุ่นบันไดให้",
                "note_en": "Manual mode — the system suggests no ladder rung"}
    return {
        "mode": mode,
        "indicative": ladder.get("indicative") or ladder.get("stage"),
        "indicative_th": ladder.get("indicative_label_th") or ladder.get("stage_label_th"),
        "indicative_en": ladder.get("indicative_label_en") or ladder.get("stage_label_en"),
        "is_indicative": True,
        "note_th": ("รุ่นบันไดนี้เป็นตัวชี้แนะ ไม่ใช่ตัวกำหนดขั้นตอน "
                    "การประกาศ NPL ต้องมีคนตัดสิน (เกณฑ์ยังไม่ได้ชี้ขาด)"),
        "note_en": ("This ladder rung is a hint, not what places the step. "
                    "Declaring NPL needs a person's decision (the threshold is not yet decided)."),
    }


def _contact_branches(case, item, customer_uid):
    """The flowcharts' four contact-result branches (ผลการติดตาม).

    These are outcomes the CUSTOMER chooses, not acts the officer picks — which is why
    the interface renders them as prose behind one disclosure rather than four peer
    buttons. The Act's daily slot closes the three that count; `INBOUND` never does.
    """
    lock = (item or {}).get("contact_lock") or {}
    locked = lock.get("state") == "LOCKED"
    why_th = why_en = None
    if locked:
        who = lock.get("locked_by")
        when = lock.get("locked_at_local_th") or lock.get("locked_at") or ""
        why_th = "ใช้สิทธิ์ติดต่อที่นับได้ของวันนี้ไปแล้วโดย %s %s" % (who or "เจ้าหน้าที่คนก่อน", when)
        why_en = "Today's one counting contact was already used by %s" % (who or "an earlier officer")
    route = "/customers/%s" % customer_uid
    control = "POST /v1/cases/by-customer/{customer_uid}/contacts"
    return [
        _branch("PTP", "ลูกค้านัดชำระ", "Customer promises to pay", 11,
                route, control + " (result=REACHED_PTP)", not locked, why_th, why_en),
        _branch("SERVICE_ISSUE", "แจ้งปัญหาบริการ", "Customer reports a service issue", 12,
                route, control + " (result=SERVICE_ISSUE)", not locked, why_th, why_en),
        _branch("NO_CONTACT", "ติดต่อไม่ได้", "Could not be reached", 13,
                route, control + " (result=UNREACHABLE_NO_ANSWER)", True, None, None),
        _branch("REFUSED", "ปฏิเสธชำระ / ไม่มีข้อยุติ", "Refuses to pay / no agreement", 14,
                route, control + " (result=REFUSED_PAY)", not locked, why_th, why_en),
    ]


def _recovery_branches(customer_uid):
    """Part 4's four recovery strategies. EXTERNAL_COLLECTION is listed and refused,
    naming D27 — hiding it would tidy an open decision off the face."""
    route = "/recovery"
    control = "POST /v1/npl-cases/{uid}/recovery"
    branches = [
        _branch("LEGAL", "ดำเนินคดี", "Legal", 16, route, control, True),
        _branch("REPOSSESSION", "ยึดคืนอุปกรณ์", "Repossession / recovery", 16, route, control, True),
        _branch("COOP_DECOMMISSION", "รื้อถอนโดยความยินยอม", "Cooperative decommission", 16, route, control, True),
        _branch("EXTERNAL_COLLECTION", "ส่งสำนักงานเร่งรัดหนี้ภายนอก", "External collection", 16,
                route, control, False,
                "ยังไม่ชี้ขาดว่าใช้แนวทางนี้ได้หรือไม่ (อยู่ระหว่างรอการตัดสินใจ)",
                "Not yet decided whether this path can be used (a decision is pending)"),
    ]
    # The open decision rides as a structured field; the code stays off the prose.
    branches[-1]["open_decision"] = dict(D27)
    return branches


# Final v2 (prototype 673-684): after a path is chosen, the design lists that path's
# next steps. The SOP draws exactly one step past the fork, so one is served — the
# strategy's own SOP label, noted by the rule of the step it leads to. Nothing here is
# invented: the label is the branch's, the note is STEP_BY_N's gate rule, and
# EXTERNAL_COLLECTION's note is the refusal the branch already carries (contract §3:
# a refusal stays visible). A strategy the SOP does not name gets no steps at all.
#
# Delta-100 REC-14: for REPOSSESSION the S12 lot flow supplies the two further steps
# the prototype's "recover" card draws (count the equipment, resell at the lot price)
# after the strategy's own SOP act. Their labels and notes are the app's own served
# copy — the count gate's variance rule (errors.lot_count) and the sale's
# proceeds-against-NPV rule (the lot flow) — so the three steps are all vocabulary
# the system already uses, not new workflow. The prototype's middle step ("into the
# lot") is not servable: the lot is created by the system when the recovery opens
# (journey.make_lot, status PLANNED), not by an officer, so the officer's acts are
# repossess, count and resale. Strategies where the SOP still draws only one step
# keep one, and RECOVERY_NEXT_STEPS_NOTES says so on the payload.
REPOSSESSION_FURTHER_STEPS = (
    {
        "label_th": "ตรวจนับอุปกรณ์ให้ตรง", "label_en": "Count the equipment correctly",
        "note_th": "จำนวนไม่ตรงกับที่คาดไว้ ต้องระบุเหตุผลและรูปถ่าย",
        "note_en": "A variance from the expected count needs a reason and a photo",
        "leads_to_step": 16, "available": True,
        "control": "POST /v1/repossession-lots/{uid}:count",
    },
    {
        "label_th": "ขายต่อตามราคาล็อต", "label_en": "Resell at the lot price",
        "note_th": "ฝ่ายปฏิบัติการตั้งราคาขายต่อก่อน เงินที่ขายได้หักกับ NPV คงเหลือ",
        "note_en": "Operations sets the resale price first; the proceeds are set against the remaining NPV",
        "leads_to_step": 16, "available": True,
        "control": "POST /v1/repossession-lots/{uid}:price",
    },
)

RECOVERY_NEXT_STEPS = {
    branch["code"]: [{
        "label_th": branch["label_th"], "label_en": branch["label_en"],
        "note_th": branch["unavailable_reason_th"] or STEP_BY_N[branch["leads_to_step"]]["gate_rule_th"],
        "note_en": branch["unavailable_reason_en"] or STEP_BY_N[branch["leads_to_step"]]["gate_rule_en"],
        "leads_to_step": branch["leads_to_step"],
        "available": branch["available"],
    }] + ([dict(step) for step in REPOSSESSION_FURTHER_STEPS]
          if branch["code"] == "REPOSSESSION" else [])
    for branch in _recovery_branches(None)
}

# Served beside next_steps on a recovery case. None where the strategy's steps are
# the full S12 lot flow; a sentence where the SOP itself supports only the one step
# past the fork — REC-14's "serve one and document".
RECOVERY_NEXT_STEPS_NOTES = {
    "LEGAL": ("SOP วาดขั้นถัดไปหลังทางแยกไว้หนึ่งขั้นสำหรับแนวทางนี้ จึงให้บริการหนึ่งขั้น",
              "The SOP draws one step past the fork for this strategy, so one step is served"),
    "REPOSSESSION": (None, None),
    "COOP_DECOMMISSION": ("SOP วาดขั้นถัดไปหลังทางแยกไว้หนึ่งขั้นสำหรับแนวทางนี้ จึงให้บริการหนึ่งขั้น",
                          "The SOP draws one step past the fork for this strategy, so one step is served"),
    "EXTERNAL_COLLECTION": ("แนวทางนี้ยังไม่ได้รับอนุมัติให้ใช้ จึงให้บริการเฉพาะขั้นที่ถูกปฏิเสธไว้",
                            "This path is not yet approved for use, so only its recorded refusal is served"),
}


def _decision_branches():
    """Part 4's กำหนดแนวทางดำเนินการ — four paths. These the MANAGER chooses, so the
    interface draws them as controls, not prose."""
    return [
        _branch("CONTINUE", "ติดตามต่อ", "Continue following up", 10, "/reviews",
                "POST /v1/reviews/{uid}:answer (decision=CONTINUE)", True),
        _branch("ARRANGEMENT", "ผ่อนผันการชำระ", "Repayment arrangement", 15, "/reviews",
                "POST /v1/reviews/{uid}:answer (decision=ARRANGEMENT)", True),
        _branch("RESTRUCTURE", "ปรับโครงสร้างหนี้", "Restructure", 15, "/reviews",
                "POST /v1/reviews/{uid}:answer (decision=RESTRUCTURE_PROPOSE)", True),
        _branch("NPL", "ยืนยัน NPL", "Confirm NPL", 16, "/reviews",
                "POST /v1/reviews/{uid}:answer (decision=NPL_TYPE_SET)", True),
    ]


def _pre_install(pipeline_item):
    """Steps 1 to 5 — the pre-installation pipeline. Every step here is one of the
    D26 eight, so each is marked the team's and carries the open decision."""
    if pipeline_item is None:
        return _unplaced(
            {"in_book": False, "pipeline_item": None},
            [{"step": 1, "why_not_th": "ไม่มีการ์ดก่อนติดตั้งสำหรับลูกค้ารายนี้",
              "why_not_en": "There is no pre-installation card for this customer"}],
            reason_th="ลูกค้ายังไม่มีสัญญาในเล่มและไม่มีการ์ดก่อนติดตั้ง — ระบุขั้นตอนไม่ได้",
            reason_en="The customer has no contract in the book and no pre-installation card — no step can be named")
    uid = pipeline_item.get("uid")
    g1 = (pipeline_item.get("gate_down_payment") or {}).get("state")
    g2 = (pipeline_item.get("gate_epc_confirmed") or {}).get("state")
    g1_passed, g2_passed = g1 == "PASSED", g2 == "PASSED"
    released = pipeline_item.get("released_at")
    delivery = pipeline_item.get("delivery")
    outcome = pipeline_item.get("install_outcome")
    history = pipeline_item.get("history") or []
    read = {"gate_down_payment": g1, "gate_epc_confirmed": g2,
            "released_at": released, "delivery": bool(delivery), "install_outcome": outcome}

    if not g1_passed and not g2_passed and not history:
        return _placed(1, _act("PASS_GATE_1", "บันทึกว่าได้รับเงินดาวน์แล้ว",
                               "Record the down payment", "/pipeline",
                               "POST /v1/pipeline/%s/gates/down-payment" % uid),
                       decided_by=["gate_down_payment=OPEN", "gate_epc_confirmed=OPEN", "history=[]"],
                       decided_by_th="ยังไม่ผ่านด่านใดและยังไม่มีประวัติบนการ์ดนี้",
                       decided_by_en="No gate passed yet and no history on this card")
    if not (g1_passed and g2_passed):
        if not g1_passed:
            act = _act("PASS_GATE_1", "บันทึกว่าได้รับเงินดาวน์แล้ว", "Record the down payment",
                       "/pipeline", "POST /v1/pipeline/%s/gates/down-payment" % uid)
        else:
            act = _act("PASS_GATE_2", "บันทึกวันติดตั้งที่ EPC ยืนยัน",
                       "Record the EPC-confirmed install date", "/pipeline",
                       "POST /v1/pipeline/%s/gates/epc-confirmed" % uid)
        return _placed(2, act, decided_by=["gate_down_payment=%s" % g1, "gate_epc_confirmed=%s" % g2],
                       decided_by_th="ยังผ่านด่านไม่ครบทั้งสอง ปล่อยใบแจ้งหนี้ไม่ได้",
                       decided_by_en="Not both gates passed yet, so the invoice cannot be released")
    if released is None:
        return _placed(3, _act("RELEASE", "ปล่อยใบแจ้งหนี้", "Release the invoice",
                               "/pipeline", "POST /v1/pipeline/%s:release" % uid),
                       decided_by=["gate_down_payment=PASSED", "gate_epc_confirmed=PASSED",
                                   "released_at=None"],
                       decided_by_th="ผ่านทั้งสองด่านแล้ว ยังไม่ได้ปล่อยใบแจ้งหนี้",
                       decided_by_en="Both gates passed; the invoice is not released yet")
    if not delivery:
        # The app has no approve route by design — AR approves inside PEAK.
        return _placed(3, _act("AWAIT_AR_APPROVAL", "รอ AR อนุมัติใน PEAK",
                               "AR approves in PEAK", "/payments", None, False,
                               "การอนุมัติทำใน PEAK แอปไม่มีปุ่มอนุมัติโดยตั้งใจ",
                               "Approval happens in PEAK; the app has no approve button by design"),
                       decided_by=["released_at set", "delivery=None"],
                       decided_by_th="ปล่อยแล้ว รอ AR อนุมัติใน PEAK ก่อนจึงส่งให้ลูกค้าได้",
                       decided_by_en="Released; AR must approve in PEAK before it can go to the customer")
    if outcome is None:
        return _placed(5, _act("RECORD_OUTCOME", "บันทึกผลวันติดตั้ง",
                               "Record the installation-day outcome", "/pipeline",
                               "POST /v1/pipeline/%s/install-outcome" % uid),
                       decided_by=["delivery set", "install_outcome=None"],
                       decided_by_th="ส่งใบแจ้งหนี้แล้ว ยังไม่ได้บันทึกผลวันติดตั้ง",
                       decided_by_en="Invoice delivered; the installation-day outcome is not recorded yet")
    if outcome == "POSTPONED" and pipeline_item.get("reschedule_decision") is None:
        return _placed(5, _act("RESCHEDULE", "เลือกแนวทางหลังเลื่อนติดตั้ง",
                               "Choose the reschedule path", "/pipeline",
                               "POST /v1/pipeline/%s/reschedule" % uid),
                       branches=[
                           _branch("STAND", "คงใบแจ้งหนี้เดิม", "Let the invoice stand", 5,
                                   "/pipeline", "POST /v1/pipeline/%s/reschedule" % uid),
                           _branch("AMEND_DUE_DATE", "แก้วันครบกำหนด", "Amend the due date", 5,
                                   "/pipeline", "POST /v1/pipeline/%s/reschedule" % uid),
                           _branch("CANCEL_AND_REISSUE", "ยกเลิกแล้วออกใหม่", "Cancel and reissue", 5,
                                   "/pipeline", "POST /v1/pipeline/%s/reschedule" % uid),
                       ],
                       decided_by=["install_outcome=POSTPONED", "reschedule_decision=None"],
                       decided_by_th="เลื่อนติดตั้งหลังออกใบแจ้งหนี้ ต้องเลือกคงไว้ แก้ไข หรือยกเลิกแล้วออกใหม่",
                       decided_by_en="Installation postponed after invoicing; choose to keep, amend, or cancel and reissue")
    return _placed(5, _act("AWAIT_BOOK", "รอสัญญาเข้าเล่ม", "Wait for the contract to reach the book",
                           None, None, False,
                           "ติดตั้งแล้วแต่สัญญายังไม่ปรากฏในเล่ม", "Installed, but the contract is not in the book yet"),
                   decided_by=["install_outcome=%s" % outcome],
                   confidence="PARTIAL",
                   confidence_note_th="บันทึกผลติดตั้งแล้ว แต่ยังไม่มีสัญญาในเล่มให้เดินต่อ",
                   confidence_note_en="The installation outcome is recorded, but there is no contract in the book to continue with",
                   decided_by_th="บันทึกผลวันติดตั้งแล้ว",
                       decided_by_en="Installation-day outcome recorded")


def walkthrough(case, item=None, pipeline_item=None, in_book=True):
    """The SOP step this case stands on, the one act that moves it, and the branches.

    States a step; never operates a gate (SOP §6, D26). Carries no money at all.
    Reads only served state — never DPD and never a ladder rung — to place step 16,
    so OD-04 stays refused.
    """
    if not in_book:
        return _pre_install(pipeline_item)

    customer_uid = case.get("customer_uid")
    route_case = "/customers/%s" % customer_uid
    ps = case.get("payment_status")
    hint = _ladder_hint(item)
    read = {
        "payment_status": ps, "dc_status": case.get("dc_status"),
        "npl_type": case.get("npl_type"), "open_ptp_uid": case.get("open_ptp_uid"),
        "open_issue_uid": case.get("open_issue_uid"), "review_uid": case.get("review_uid"),
        "broken_ptp_count": case.get("broken_ptp_count"),
        "next_action": case.get("next_action"), "next_action_on": case.get("next_action_on"),
        "last_contact_at": case.get("last_contact_at"),
    }

    # C0 — a closed account is off the journey. Step 17 is the Lead's report over the
    # book, not this case's position, so it is never the answer here.
    # 2026-09-20: a TERMINATED account is off it for a different reason — the contract
    # ended (default or the customer's request), and the cause is printed so the two
    # never read as one thing.
    if ps == "CLOSED":
        return _off_journey(read,
                            "บัญชีปิดแล้ว ไม่ได้อยู่ในขั้นตอนติดตามหนี้",
                            "The account is closed and is not on the collection journey.")
    if ps == "TERMINATED":
        cause = (case.get("termination") or {}).get("cause")
        if cause == "CUSTOMER_REQUEST":
            return _off_journey(read,
                                "ลูกค้าขอยุติสัญญา สัญญาสิ้นสุดแล้ว ไม่ได้อยู่ในขั้นตอนติดตามหนี้",
                                "The contract ended at the customer's request and is not on the collection journey.")
        if cause == "DEFAULT":
            return _off_journey(read,
                                "สัญญาถูกยุติเพราะผิดสัญญา ไม่ได้อยู่ในขั้นตอนติดตามหนี้",
                                "The contract was terminated on default and is not on the collection journey.")
        return _off_journey(read,
                            "สัญญาสิ้นสุดแล้ว ไม่ได้อยู่ในขั้นตอนติดตามหนี้",
                            "The contract has ended and is not on the collection journey.")

    # C1 — step 16 is placed ONLY from human-set state. Never from DPD, never from a
    # ladder rung: that would declare NPL automatically and answer OD-04.
    if ps == "NPL" or case.get("npl_type"):
        npl_type = case.get("npl_type")
        if not npl_type:
            act = _act("SET_NPL_TYPE", "กำหนดชนิด NPL", "Set the NPL type",
                       "/recovery", "POST /v1/cases/by-customer/{customer_uid}/npl-type")
            branches = []
        else:
            act = _act("CHOOSE_RECOVERY", "เลือกแนวทางเรียกคืน", "Choose the recovery strategy",
                       "/recovery", "POST /v1/npl-cases/{uid}/recovery")
            branches = _recovery_branches(customer_uid)
        return _placed(16, act, branches,
                       decided_by=["payment_status=%s" % ps, "npl_type=%s" % npl_type],
                       decided_by_th="เป็น NPL แล้วโดยการตัดสินของคน ไม่ใช่จากจำนวนวันค้าง",
                       decided_by_en="NPL by a person's decision, not by days overdue",
                       ladder_hint=hint)

    # C2 — an arrangement or a restructure is running.
    if case.get("dc_status") == "RESTRUCTURE_LOAN":
        return _placed(15, _act("TRACK_ARRANGEMENT", "ติดตามแผนชำระใหม่",
                                "Track the new payment plan", "/recovery", None),
                       decided_by=["dc_status=RESTRUCTURE_LOAN"],
                       decided_by_th="สถานะติดตามบอกว่ากำลังปรับโครงสร้างหนี้",
                       decided_by_en="The collection status says a restructure is under way",
                       ladder_hint=hint)

    # C3 — a review is open: the officer's act is to wait, and the app says who answers.
    if case.get("review_uid"):
        return _placed(14, _act("AWAIT_REVIEW", "รอผู้จัดการตอบ", "Wait for the manager's answer",
                                "/reviews", "POST /v1/reviews/{uid}:answer", False,
                                "ส่งให้ผู้จัดการแล้ว รอคำตอบ",
                                "Sent to the manager; waiting for the answer"),
                       branches=_decision_branches(),
                       decided_by=["review_uid set"],
                       decided_by_th="มีเรื่องรอผู้จัดการตอบอยู่",
                       decided_by_en="A request is waiting for the manager's answer",
                       ladder_hint=hint)

    # C4 — an open service ticket freezes the fee clock and owns the case.
    if case.get("open_issue_uid"):
        return _placed(12, _act("TRACK_TICKET", "ติดตามผู้รับผิดชอบและสถานะแก้ไข",
                                "Track the owner and the fix status", route_case,
                                "POST /v1/case-issues/{uid}:close"),
                       decided_by=["open_issue_uid set"],
                       decided_by_th="มีใบแจ้งปัญหาบริการที่ยังไม่ปิด",
                       decided_by_en="A service ticket is still open",
                       ladder_hint=hint)

    # C5 — an open or broken promise.
    if case.get("open_ptp_uid"):
        return _placed(11, _act("CLOSE_PTP", "ปิดผลนัดชำระ", "Close the promise",
                                route_case, "POST /v1/case-ptps/{uid}:close"),
                       decided_by=["open_ptp_uid set"],
                       decided_by_th="มีนัดชำระที่เปิดอยู่",
                       decided_by_en="There is an open promise to pay",
                       ladder_hint=hint)
    if (case.get("broken_ptp_count") or 0) > 0:
        renegotiated = case.get("renegotiation_count") or 0
        if renegotiated >= 2:
            act = _act("ESCALATE", "ส่งผู้จัดการตรวจ", "Raise to the manager", route_case,
                       "POST /v1/cases/by-customer/{customer_uid}/review-requests")
            note = "เจรจาใหม่มาแล้ว %d ครั้ง ครั้งถัดไปส่งผู้จัดการ" % renegotiated
            note_en = "Renegotiated %d times already; the next one goes to the manager" % renegotiated
        else:
            act = _act("RENEGOTIATE", "เจรจานัดชำระใหม่", "Renegotiate the promise",
                       route_case + "?renegotiate=1", "POST /v1/case-ptps/{uid}:renegotiate")
            note = "ผิดนัดแล้วยังไม่ได้เจรจาใหม่"
            note_en = "The promise broke and has not been renegotiated"
        return _placed(11, act,
                       decided_by=["broken_ptp_count=%s" % case.get("broken_ptp_count"),
                                   "renegotiation_count=%s" % renegotiated],
                       decided_by_th=note, decided_by_en=note_en, ladder_hint=hint)

    # C6 — a run of failed contact attempts.
    run = (item or {}).get("unreachable_run") or {}
    if (run.get("unreachable_since_last_reach") or 0) >= 1:
        return _placed(13, _act("TRY_OTHER_CHANNEL", "ลองช่องทางและเวลาอื่น",
                                "Try other channels and times", route_case,
                                "POST /v1/cases/by-customer/{customer_uid}/contacts"),
                       branches=_contact_branches(case, item, customer_uid),
                       decided_by=["unreachable_since_last_reach=%s"
                                   % run.get("unreachable_since_last_reach")],
                       decided_by_th="ติดต่อไม่ได้ติดต่อกันหลายครั้ง",
                       decided_by_en="Several contact attempts in a row failed",
                       ladder_hint=hint)

    # The reminder step, where a next action a person set says so.
    if case.get("next_action") == "SEND_REMINDER":
        return _placed(8, _act("SEND_REMINDER", "ส่งแจ้งเตือน", "Send the reminder",
                               "/", "POST /v1/today/reminders:send"),
                       decided_by=["next_action=SEND_REMINDER"],
                       decided_by_th="งานถัดไปที่ตั้งไว้คือส่งแจ้งเตือน",
                       decided_by_en="The next action set is to send a reminder",
                       ladder_hint=hint)
    if case.get("next_action") == "CONFIRM_SLIP":
        return _placed(6, _act("CONFIRM_SLIP", "ยืนยันสลิป", "Confirm the slip",
                               "/payments", "POST /v1/slips"),
                       decided_by=["next_action=CONFIRM_SLIP"],
                       decided_by_th="งานถัดไปที่ตั้งไว้คือยืนยันสลิป",
                       decided_by_en="The next action set is to confirm a slip",
                       ladder_hint=hint)

    # The working case: overdue, nothing else holding it. Step 10.
    if ps == "LATE":
        lock = (item or {}).get("contact_lock") or {}
        locked = lock.get("state") == "LOCKED"
        act = _act("LOG_CONTACT", "บันทึกผลการติดต่อ", "Save the contact result",
                   route_case, "POST /v1/cases/by-customer/{customer_uid}/contacts",
                   not locked,
                   ("ใช้สิทธิ์ติดต่อที่นับได้ของวันนี้ไปแล้ว — บันทึกที่ไม่นับยังทำได้"
                    if locked else None),
                   "Today's one counting contact is already used — an uncounted record is still possible" if locked else None)
        return _placed(10, act, _contact_branches(case, item, customer_uid),
                       decided_by=["payment_status=LATE", "no open_ptp_uid",
                                   "no open_issue_uid", "no review_uid"],
                       decided_by_th="ค้างชำระแล้ว ยังไม่มีนัดชำระ ไม่มีใบแจ้งปัญหา และไม่มีเรื่องรอผู้จัดการ",
                       decided_by_en="Overdue, with no promise to pay, no service ticket and nothing waiting for the manager",
                       ladder_hint=hint)

    # Current and quiet: the reminder cycle is where the case sits.
    if ps == "CURRENT":
        return _placed(8, _act("SEND_REMINDER", "ส่งแจ้งเตือนก่อนครบกำหนด",
                               "Send the pre-due reminder", "/",
                               "POST /v1/today/reminders:send"),
                       decided_by=["payment_status=CURRENT"],
                       decided_by_th="ยังไม่ค้างชำระ รอบการเตือนก่อนครบกำหนดคือขั้นที่เคสอยู่",
                       decided_by_en="Not overdue; the case sits in the pre-due reminder cycle",
                       ladder_hint=hint)

    # Nothing above matched. Say so, and say what was considered.
    return _unplaced(read, [
        {"step": 8, "why_not_th": "ไม่มีงานส่งแจ้งเตือนที่ถึงกำหนด และสถานะไม่ใช่ปกติ",
         "why_not_en": "No reminder is due and the status is not current"},
        {"step": 10, "why_not_th": "สถานะการชำระไม่ใช่ค้างชำระ",
         "why_not_en": "The payment status is not late"},
        {"step": 11, "why_not_th": "ไม่มีนัดชำระที่เปิดอยู่และไม่มีประวัติผิดนัด",
         "why_not_en": "No open promise to pay and no broken promise"},
        {"step": 16, "why_not_th": "ยังไม่มีการประกาศ NPL โดยคน",
         "why_not_en": "No person has declared NPL"},
    ])

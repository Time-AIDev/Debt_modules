"""Read-time context only. Signed audit payloads/hashes remain untouched."""
from . import cases, journey, termination_archive

ACT_LABELS = {
    'ODOO_SHEET_USED': 'ใช้ข้อมูลชีตจาก Odoo', 'ODOO_SNAPSHOT_USED': 'ใช้ข้อมูล Odoo ที่บันทึกไว้',
    'ODOO_SYNCED': 'อัปเดตข้อมูลจาก Odoo',
    'CONTRACT_TERMINATED': 'ยุติสัญญา', 'RECOVERY_RESOLVED': 'ปิดงานเรียกคืน / ตัดจำหน่าย',
    'TERMINATED_CASE_VIEWED': 'ดูเคสที่ยุติย้อนหลัง', 'CASE_VIEWED': 'เปิดเคสลูกค้า',
    'CONTACT_LOGGED': 'บันทึกผลติดต่อ', 'CUSTOMERS_ASSIGNED': 'มอบหมายลูกค้า',
    'CUSTOMER_ASSIGNED': 'มอบหมายลูกค้า', 'PAYMENT_STATUS_SET': 'ปรับสถานะชำระเงิน',
    'PHONE_SET': 'บันทึกเบอร์โทร', 'PHONE_REVEALED': 'ดูเบอร์โทร', 'PTP_CREATED': 'บันทึกสัญญาชำระ',
    'PTP_RENEGOTIATED': 'ปรับสัญญาชำระ', 'PTP_CANCELLED': 'ยกเลิกสัญญาชำระ',
    'SHEET_INSTALLED': 'นำเข้าข้อมูล', 'IMPORT_UPLOADED': 'อัปโหลดข้อมูล',
    'LOGIN': 'เข้าสู่ระบบ', 'LOGOUT': 'ออกจากระบบ', 'DC_STATUS_SET': 'เปลี่ยนสถานะติดตาม',
    'ISSUE_OPENED': 'เปิดตั๋วปัญหา', 'ISSUE_RESOLVED': 'แก้ไขตั๋วปัญหา',
    'REVIEW_DECIDED': 'พิจารณาคำขอ', 'INVOICE_MATCHED': 'จับคู่ใบแจ้งหนี้',
    'PAYMENT_CLAIM_SUBMITTED': 'บันทึกเงินเข้า', 'PAYMENT_REMINDER_SENT': 'ส่งแจ้งเตือนชำระเงิน',
}


def context():
    customers = {c.uid: c for c in journey.book_customers() + journey.identity_customers()}
    subjects = {uid: uid for uid in customers}
    for uid, customer in customers.items():
        for k in customer.contracts:
            subjects[k.uid] = uid
    state = journey.for_current()
    case_state = cases.for_current()
    for collection in (state.invoices, state.recovery_cases, case_state.issues, case_state.reviews, case_state.ptps, case_state.power):
        for uid, row in collection.items():
            customer_uid = row.get('customer_uid') or subjects.get(row.get('contract_uid'))
            if customer_uid:
                subjects[uid] = customer_uid
    archives = sorted(termination_archive.records(), key=lambda r: r['captured_at'])
    for row in archives:
        subjects[row['customer_uid']] = row['customer_uid']
        for term in row['terminations']:
            subjects[term['contract_uid']] = row['customer_uid']
    return customers, subjects, archives


def matching_subjects(q, ctx):
    customers, subjects, archives = ctx
    needle = q.casefold()
    uids = {uid for uid, c in customers.items() if needle in ' '.join(str(getattr(c, k, '') or '') for k in ('uid', 'display_name', 'customer_no', 'volt_id')).casefold()}
    uids.update(r['customer_uid'] for r in archives if needle in ' '.join(str(r.get(k) or '') for k in ('customer_uid', 'customer_name', 'customer_no', 'volt_id')).casefold())
    return [subject for subject, uid in subjects.items() if uid in uids]


def enrich(entry, ctx):
    customers, subjects, archives = ctx
    detail = entry.get('detail') or {}
    archive_uid = detail.get('archive_uid')
    archive = next((r for r in archives if (archive_uid and r['archive_uid'] == archive_uid) or
                    (r.get('audit_request_id') and r['audit_request_id'] == entry.get('request_id')) or
                    (entry.get('request_id') in r.get('audit_request_ids', []))), None)
    if archive is None and entry.get('outcome') == 'OK':
        termination = detail.get('contract_terminated') or {}
        contract_uid = termination.get('contract_uid')
        matches = [r for r in archives if contract_uid and any(
            t.get('contract_uid') == contract_uid
            and t.get('instrument') == termination.get('instrument') and t.get('cause') == termination.get('cause')
            for t in r['terminations'])]
        if len(matches) == 1:
            archive = matches[0]
    uid = archive['customer_uid'] if archive else subjects.get(entry.get('subject_uid')) or subjects.get((detail.get('contract_terminated') or {}).get('contract_uid'))
    customer = customers.get(uid)
    historical = next((r for r in archives if r['customer_uid'] == uid), None)
    reason = archive.get('reason') if archive else detail.get('reason') or detail.get('note')
    termination_act = entry.get('act') in ('CONTRACT_TERMINATED', 'RECOVERY_RESOLVED') and bool(detail.get('contract_terminated'))
    case_url = '/terminated/' + archive['archive_uid'] if archive else '/customers/' + uid if customer and not termination_act else None
    name = archive['customer_name'] if archive else customer.display_name if customer else historical['customer_name'] if historical else None
    return {**entry, 'display': {'activity_th': ACT_LABELS.get(entry.get('act')) or ('เปิดเคสลูกค้า' if entry.get('verb') == 'GET' and uid else entry.get('act') or entry.get('route_template')),
                               'customer_uid': uid, 'customer_name': name,
                               'customer_no': archive['customer_no'] if archive else customer.customer_no if customer else None,
                               'reason': reason, 'case_url': case_url,
                               'unavailable': not bool(case_url)}}

ACT_LABELS.update({
 'NOTE_ADDED': 'เพิ่มบันทึก', 'NPL_TYPE_SET': 'กำหนดประเภทหนี้เสีย',
 'POWER_APPROVED': 'อนุมัติตัดไฟ', 'POWER_EXECUTED': 'ดำเนินการตัดไฟ', 'POWER_REJECTED': 'ปฏิเสธตัดไฟ', 'POWER_REQUESTED': 'ขอตัดไฟ',
 'APPROVAL_PATH_CREATED': 'สร้างเส้นทางอนุมัติ', 'BOARD_COLUMN_DELETED': 'ลบคอลัมน์งาน', 'BOARD_MOVED': 'ย้ายคอลัมน์งาน',
 'CONTACT_RETRACTED': 'ถอนบันทึกติดต่อ', 'CONTACT_CORRECTED': 'แก้ไขผลติดต่อ', 'CRITERIA_CLEARED': 'ล้างเกณฑ์', 'CRITERIA_SET': 'กำหนดเกณฑ์',
 'FEEDBACK_SUBMITTED': 'ส่งความคิดเห็น', 'ORDER_APPROVED': 'อนุมัติคำสั่งซื้อ', 'ORDER_CREATED': 'สร้างคำสั่งซื้อ', 'ORDER_DELETED': 'ลบคำสั่งซื้อ',
 'PEAK_PAYMENT_RECEIVED': 'รับเงินจาก PEAK', 'PEAK_WEBHOOK_RECEIVED': 'รับข้อมูล PEAK', 'PENALTY_INVOICE_RAISED': 'ออกใบแจ้งหนี้ค่าปรับ',
 'TRANSACTION_RECORDED': 'บันทึกรายการเงิน', 'PTP_PAYMENT_NOTICED': 'แจ้งเงินเข้าก่อนวันนัด',
 'ATTACHMENT_DELETED': 'ลบไฟล์แนบ', 'ATTACHMENT_DOWNLOADED': 'ดาวน์โหลดไฟล์แนบ', 'ATTACHMENT_UPLOADED': 'อัปโหลดไฟล์แนบ',
 'NEXT_ACTION_MOVED': 'เลื่อนงานถัดไป', 'NEXT_ACTION_SET': 'กำหนดงานถัดไป', 'NOTICE_CREATED': 'สร้างการแจ้งเตือน', 'NOTICE_DELETED': 'ลบการแจ้งเตือน', 'NOTICE_UPDATED': 'แก้ไขการแจ้งเตือน',
 'IMPORT_PART_RECEIVED': 'รับส่วนข้อมูลนำเข้า', 'IMPORT_UPLOAD_ABORTED': 'ยกเลิกอัปโหลด', 'TEMPLATE_DOWNLOADED': 'ดาวน์โหลดแบบฟอร์ม',
 'PEAK_INVOICE_ISSUED': 'ออกใบแจ้งหนี้ PEAK', 'R14_OVERRIDE': 'ปรับข้อมูลคำสั่งซื้อ', 'R14_OVERRIDE_CLEARED': 'ล้างการปรับข้อมูล',
 'ARRANGEMENT_BROKEN': 'ผิดสัญญาปรับโครงสร้าง', 'CANCELLATION_CREATED': 'บันทึกยกเลิก', 'CASE_ADVANCED': 'ดำเนินขั้นตอนเคส', 'CASH_CASE_ADVANCED': 'ดำเนินขั้นตอนเคสเงินสด',
 'INTERCOMPANY_DOC_POSTED': 'ลงบัญชีเอกสารระหว่างบริษัท', 'INVOICE_ISSUED': 'ออกใบแจ้งหนี้', 'INVOICE_LINK_SENT': 'ส่งลิงก์ใบแจ้งหนี้',
 'INVOICE_ORIGINAL_REVIEWED': 'ตรวจต้นฉบับใบแจ้งหนี้', 'INVOICE_SENT': 'ส่งใบแจ้งหนี้', 'LADDER_MODE_SET': 'กำหนดรูปแบบติดตาม', 'LADDER_STAGE_SET': 'กำหนดขั้นตอนติดตาม',
 'LOT_COUNTED': 'ตรวจนับทรัพย์สิน', 'LOT_GRADED': 'จัดเกรดทรัพย์สิน', 'LOT_PRICED': 'กำหนดราคาทรัพย์สิน', 'LOT_SOLD': 'ขายทรัพย์สิน',
 'MANAGER_REVIEW_DECIDED': 'ผู้จัดการพิจารณา', 'PTP_CLOSED': 'ปิดสัญญาชำระ', 'RECEIPT_RECORDED': 'บันทึกใบเสร็จ',
 'RECOVERY_OPENED': 'เปิดงานเรียกคืน', 'RECOVERY_RECORDED': 'บันทึกยอดเรียกคืน', 'RECOVERY_STAGE_MOVED': 'เปลี่ยนขั้นตอนเรียกคืน', 'RECOVERY_STRATEGY_CHANGED': 'เปลี่ยนวิธีเรียกคืน',
 'RESTRUCTURE_APPROVED': 'อนุมัติปรับโครงสร้าง', 'RESTRUCTURE_MISS_RECORDED': 'บันทึกผิดนัดปรับโครงสร้าง', 'RESTRUCTURE_PROPOSED': 'เสนอปรับโครงสร้าง',
 'SERVICE_BILLED': 'เรียกเก็บค่าบริการ', 'SERVICE_BILLING_DECLINED': 'ไม่เรียกเก็บค่าบริการ', 'SERVICE_ISSUE_CREATED': 'เปิดตั๋วปัญหา', 'SERVICE_ISSUE_RESOLVED': 'แก้ไขตั๋วปัญหา',
 'SIGNED_IN': 'เข้าสู่ระบบ', 'SIGNED_OUT': 'ออกจากระบบ', 'MESSAGE_TEMPLATE_CREATED': 'สร้างข้อความต้นแบบ', 'MESSAGE_TEMPLATE_DELETED': 'ลบข้อความต้นแบบ', 'MESSAGE_TEMPLATE_UPDATED': 'แก้ไขข้อความต้นแบบ',
 'OPERATION_RUN_CANCEL_REQUESTED': 'ขอยกเลิกงาน', 'PAYMENT_CLAIM_CANCELLED': 'ยกเลิกเงินเข้ารอตรวจ', 'PAYMENT_CLAIM_CREATED': 'บันทึกเงินเข้ารอตรวจ', 'PAYMENT_REMINDER_REPLAYED': 'เปิดการแจ้งเตือนชำระเดิม',
 'CREDIT_NOTE_RAISED': 'ออกใบลดหนี้', 'PEAK_DOCUMENTS_REFRESHED': 'รีเฟรชเอกสาร PEAK', 'PEAK_DOCUMENT_REFRESHED': 'รีเฟรชเอกสาร PEAK', 'PEAK_DOCUMENT_RESENT': 'ส่งเอกสาร PEAK อีกครั้ง', 'PEAK_DOCUMENT_RESUBMITTED': 'ส่งเอกสาร PEAK ใหม่', 'PEAK_STUB_SET': 'ตั้งค่า PEAK ทดสอบ', 'SLIP_CONFIRMED': 'ยืนยันหลักฐานชำระ',
 'PEAK_FIELD_DECIDED': 'ยืนยันข้อมูล PEAK', 'PEAK_FIELD_DECISION_RETIRED': 'ถอนการยืนยันข้อมูล PEAK', 'PEAK_LINK_CONFIRMED': 'ยืนยันจับคู่ PEAK', 'PEAK_LINK_RETIRED': 'ถอนจับคู่ PEAK', 'PEAK_RECEIPT_APPLIED': 'นำเข้าใบเสร็จ PEAK', 'PEAK_RECEIPT_RUN': 'ดึงใบเสร็จ PEAK', 'PEAK_REPORT_APPLIED': 'นำเข้ารายงาน PEAK', 'PEAK_REPORT_RUN': 'ดึงรายงาน PEAK',
 'CONDITION_EVIDENCE_ATTACHED': 'แนบหลักฐานเงื่อนไข', 'CONDITION_EVIDENCE_REMOVED': 'ลบหลักฐานเงื่อนไข', 'DELIVERY_REPLY_RECORDED': 'บันทึกผลส่งเอกสาร', 'GATE_DOWN_PAYMENT_PASSED': 'ยืนยันเงินดาวน์', 'GATE_EPC_CONFIRMED': 'ยืนยัน EPC', 'INSTALL_OUTCOME_SET': 'บันทึกผลติดตั้ง', 'INVOICE_DELIVERED': 'ส่งมอบใบแจ้งหนี้', 'INVOICE_RELEASED': 'ปล่อยใบแจ้งหนี้', 'INVOICE_RESCHEDULED': 'เลื่อนใบแจ้งหนี้',
 'CRM_ELIGIBILITY_APPLY': 'ใช้เงื่อนไขลูกค้า CRM', 'CRM_ELIGIBILITY_PREVIEW': 'ตรวจเงื่อนไขลูกค้า CRM', 'CRM_LEAD_PIPELINE_RUN': 'ดึงลูกค้าจาก CRM', 'CRM_LEAD_SCHEDULE_SET': 'ตั้งรอบดึงลูกค้า CRM',
 'COLLECTION_TARGETS_SET': 'กำหนดเป้าติดตาม', 'MONTHLY_HISTORY_EXPORTED': 'ส่งออกประวัติรายเดือน', 'PTP_REPORT_EXPORTED': 'ส่งออกรายงานนัดชำระ', 'WEEKLY_EDITION_PUBLISHED': 'เผยแพร่รายงานสัปดาห์', 'WEEKLY_FOCUS_SET': 'กำหนดงานสำคัญสัปดาห์', 'WEEKLY_REPORT_EXPORTED': 'ส่งออกรายงานสัปดาห์', 'WEEKLY_SNAPSHOT_RENAMED': 'เปลี่ยนชื่อรายงานสัปดาห์', 'WEEKLY_SNAPSHOT_TAKEN': 'บันทึกรายงานสัปดาห์', 'WEEKLY_TARGETS_SET': 'กำหนดเป้าสัปดาห์',
 'SERVICE_DEFERRAL_ACCOUNTING_REVIEWED': 'บัญชีตรวจการพักงวด', 'SERVICE_DEFERRAL_REVERSED': 'ย้อนรายการพักงวด', 'SERVICE_INSTALMENTS_DEFERRED': 'พักงวดบริการ',
 'BAND_SET_ACTIVATED': 'เปิดใช้เกณฑ์ค้าง', 'BAND_SET_ADDED': 'เพิ่มเกณฑ์ค้าง', 'BAND_SET_DEACTIVATED': 'ปิดเกณฑ์ค้าง', 'CONFIG_SET': 'ตั้งค่าระบบ', 'CUSTOMERS_SPLIT': 'แบ่งงานลูกค้า', 'DICTIONARY_VALUE_ADDED': 'เพิ่มคำในพจนานุกรม', 'DICTIONARY_VALUE_DEACTIVATED': 'ปิดคำในพจนานุกรม',
 'CONTRACT_SCHEDULE_CONFIRMED': 'ยืนยันตารางสัญญา', 'ISSUE_CLOSED': 'ปิดตั๋วปัญหา', 'REMINDER_SENT': 'ส่งแจ้งเตือน', 'REVIEW_ANSWERED': 'ตอบคำขอพิจารณา', 'REVIEW_REQUESTED': 'ขอพิจารณา', 'TODAY_ITEM_DONE': 'ปิดงานวันนี้', 'TODAY_SELECTION_EXPORTED': 'ส่งออกรายการวันนี้', 'WORKBOOK_EXPORTED': 'ส่งออกสมุดลูกค้า', 'PROFILE_SET': 'แก้ไขโปรไฟล์', 'USER_DISABLED': 'ปิดบัญชีผู้ใช้', 'USER_INVITED': 'เชิญผู้ใช้',
})

// Fixtures shaped after the served payloads (verified against the running API on
// 2026-09-19). Values are samples; the shapes are the contract.

export const BOARD_COLUMNS = {
  columns: [
    { column_id: 'col_01H8X', name: 'Call today', order: 1 },
    { column_id: 'col_01H8Y', name: 'Awaiting payment', order: 2 },
    { column_id: 'col_01H8Z', name: 'Promise made', order: 3 },
    { column_id: 'col_01H90', name: 'Escalate', order: 4 },
  ],
}

function workItem(over) {
  return {
    customer: {
      uid: 'c-1', customer_no: '28099990001', volt_id: 'V-1001', display_name: 'ปัทมวรรณ สุขเจริญ',
      officer: 'รุ่งนภา', risk_score: 78, phone_masked: '08x-xxx-1234', phone_on_file: true, phone_revealable: false,
    },
    entity: 'SPV', company_id: 'co-1', data_source: { identity: 'SHEET' },
    aggregate_overdue: '48600.00', aggregate_outstanding: '612400.00', oldest_dpd: 24,
    aging_bucket: 'UNDER_30', band_set_code: 'SOP_30_60_90',
    aging_bucket_label_th: 'ค้างไม่ถึง 30 วัน', aging_bucket_label_en: 'Under 30 days overdue',
    fee_state: null, risk_score: 78,
    money_position: {
      amount_to_ask: '48600.00', penalty_accrued_unbilled: '3159.00', penalty_invoicing_enabled: false,
      penalty_formula_th: 'ค่าปรับนับหลังพ้นระยะผ่อนผัน 14 วัน', note_th: 'ยอดที่ขอชำระยังไม่รวมค่าปรับ',
    },
    payment_position: {
      paid_count: 11, open_count: 4, total_count: 15,
      oldest_unpaid: { uid: 'inv-00199', peak_number: 'IVT-20260400091', due_date: '2026-04-12', outstanding: '8399.00' },
      last_money_in: { amount: '38257.45', on: '2026-07-16', source: 'PEAK_REPORT', ref: 'RE-20260700272' },
      source: 'PEAK_REPORT', as_of: '2026-09-14', as_of_days: 3, stale: false,
      note_th: 'ข้อมูลล่าสุดมาจากรายงานใบแจ้งหนี้ PEAK ณ 2026-09-14',
    },
    board_column_id: 'col_01H8Z', auto_moved: false, auto_moved_cause: null,
    board_override: false, board_pending_review_uid: null,
    recovery_stage: 'CONTACT',
    ladder: { kind: 'LEASE', stage: 'NORMAL', steps: [
      { stage: 'NOTICE_30', act_th: 'ขั้น 30 วัน · โทรแจ้งเตือน', act_en: 'Day 30 · call' },
      { stage: 'SETTLEMENT_PLAN_60', act_th: 'ขั้น 60 วัน · หนังสือแจ้งเตือน', act_en: 'Day 60 · letter' },
      { stage: 'DEFAULT_CONFIRMED_90', act_th: 'ขั้น 90 วัน · หนังสือทวงถาม', act_en: 'Day 90 · demand' },
    ], indicative: false, mode: 'ASSISTED', pending_decision: 'OD-04' },
    open_ptp: { uid: 'p-1', promised_amount: '48600.00', promise_date: '2026-10-23' },
    broken_ptp_count: 0, open_service_issues: 0, manager_review_open: false,
    contact_lock: { state: 'OPEN', locked_by: null },
    session_last_contact: null,
    tier: 'PTP_DUE_TODAY', tier_rank: 1,
    tier_label_th: 'นัดชำระถึงกำหนดวันนี้', tier_label_en: 'PTP due today',
    case: {
      uid: 'case-c-1', payment_status: 'LATE', dc_status: 'NO_ACTION', dc_status_label: 'ยังไม่ดำเนินการ',
      next_action: 'FOLLOW_PTP', next_action_on: '2026-10-23', last_contact_at: null, last_result: null,
      broken_ptp_count: 0, kept_ptp_count: 1, power_state: 'ON', review_uid: null,
    },
    ...over,
  }
}

export const TODAY = {
  run: { business_date: '2026-10-23', job: 'today', officer: null, ordering: 'tier' },
  items: [
    workItem({}),
    workItem({
      customer: { uid: 'c-2', customer_no: '28000577318', volt_id: 'V-1002', display_name: 'สมศรี พงษ์ไพบูลย์', officer: 'สมชาย', risk_score: 81, phone_masked: null, phone_on_file: false, phone_revealable: false },
      aggregate_overdue: '32400.00', aggregate_outstanding: '441600.00', oldest_dpd: 61,
      aging_bucket: 'OVER_90', aging_bucket_label_th: 'ค้าง 90 วันขึ้นไป', aging_bucket_label_en: '90+ days overdue',
      board_column_id: 'col_01H90', tier: 'BROKEN_PTP', tier_rank: 3,
      tier_label_th: 'ผิดนัด PTP', tier_label_en: 'Broken PTP',
      open_ptp: null, broken_ptp_count: 2, open_service_issues: 1,
      case: { uid: 'case-c-2', payment_status: 'NPL', dc_status: 'UNREACHABLE', dc_status_label: 'ติดต่อไม่ได้', next_action: 'CALL', next_action_on: '2026-10-24' },
    }),
  ],
  meta: {
    total: 2, counts_by_tier: { PTP_DUE_TODAY: 1, BROKEN_PTP: 1 },
    tiers: ['PTP_DUE_TODAY', 'NEXT_ACTION_DUE', 'BROKEN_PTP', 'AT_RISK_TWO_MISSED', 'NEW_ARREARS', 'ANSWER_WAITING', 'ROUTINE'],
    tier_labels_th: { PTP_DUE_TODAY: 'นัดชำระถึงกำหนดวันนี้', BROKEN_PTP: 'ผิดนัด PTP' },
    tier_labels_en: { PTP_DUE_TODAY: 'PTP due today', BROKEN_PTP: 'Broken PTP' },
    tier_labels_th_cash: {}, tier_labels_en_cash: {}, officer_totals: {}, filters: {},
  },
}

export const CASE = {
  case: {
    uid: 'case-c-1', customer_uid: 'c-1', customer_no: '28099990001', product: 'LEASE',
    payment_status: 'LATE', dc_status: 'NO_ACTION', dc_status_label: 'ยังไม่ดำเนินการ',
    next_action: 'FOLLOW_PTP', next_action_on: '2026-10-23', power_state: 'ON',
    power_state_label_th: 'จ่ายไฟปกติ', power_state_label_en: 'Power normal',
    broken_ptp_count: 0, kept_ptp_count: 1, risk_score: 78,
  },
  work_item: workItem({}),
  customer: {
    uid: 'c-1', customer_no: '28099990001', display_name: 'ปัทมวรรณ สุขเจริญ', name_roman: 'Patmawan',
    volt_id: 'V-1001', phone_masked: '08x-xxx-1234', phone_on_file: true, phone_revealable: true,
    line_id: null, officer: 'รุ่งนภา', data_source: { identity: 'SHEET' }, risk_score: 78,
  },
  contracts: [{ uid: 'ct-1', product: 'LEASE', entity: 'SPV', status: 'PAST_DUE', instalments_overdue: 1, oldest_dpd: 24 }],
  contract_count: 1,
  payment_summary: { totals: { overdue_amount: '48600.00', outstanding_amount: '612400.00', paid_amount: '0.00', cycle_count: 24 } },
  month_grid: [
    { index: 1, kind: 'PAID', amount: '48600.00', contract_uid: 'ct-1' },
    { index: 2, kind: 'LATE', amount: '48600.00', contract_uid: 'ct-1' },
  ],
  contact_log: [
    { uid: 'ct-1', occurred_at: '2026-10-20T10:00:00+07:00', channel: 'PHONE', result: 'REACHED_ANSWERED', note: 'คุยเรื่องยอดค้าง', counted: true, officer_uid: 'rungnapa' },
  ],
  ptps: [{ uid: 'p-1', promised_amount: '48600.00', promise_date: '2026-10-23', status: 'OPEN' }],
  issues: [],
  reviews: [],
  power: [],
  invoices: [
    { uid: 'iv-1', kind: 'INSTALMENT', amount: '48600.00', due_date: '2026-10-10', outstanding: '48600.00', state: 'OVERDUE', link_sent: true, payment_link_state: 'NOT_AVAILABLE' },
  ],
  receipts: [],
  peak_documents: [],
  contact_allowance: { cap: 1, used: 0 },
  events: [],
  risk_score: 78,
}

export const WORKBOOK = {
  rows: [
    {
      customer: { uid: 'c-1', customer_no: '28099990001', volt_id: 'V-1001', display_name: 'ปัทมวรรณ สุขเจริญ', officer: 'รุ่งนภา' },
      entity: 'SPV', data_source: { identity: 'SHEET' },
      aggregate_overdue: '48600.00', aggregate_outstanding: '612400.00', oldest_dpd: 24,
      aging_bucket: 'UNDER_30', band_set_code: 'SOP_30_60_90',
      aging_bucket_label_th: 'ค้างไม่ถึง 30 วัน', aging_bucket_label_en: 'Under 30 days overdue',
      risk_score: 78, open_service_issues: 0, case: { next_action: 'FOLLOW_PTP', next_action_on: '2026-10-23' },
      payment_position: {
        paid_count: 11, open_count: 4, total_count: 15,
        source: 'PEAK_REPORT', as_of: '2026-09-14', as_of_days: 3, stale: false,
        note_th: 'ข้อมูลล่าสุดมาจากรายงานใบแจ้งหนี้ PEAK ณ 2026-09-14',
      },
    },
    {
      customer: { uid: 'c-2', customer_no: '28000577318', display_name: 'สมศรี พงษ์ไพบูลย์', officer: 'สมชาย' },
      entity: 'SPV', data_source: { identity: 'SHEET' },
      aggregate_overdue: '32400.00', aggregate_outstanding: '441600.00', oldest_dpd: 61,
      aging_bucket: 'OVER_90', band_set_code: 'SOP_30_60_90',
      aging_bucket_label_th: 'ค้าง 90 วันขึ้นไป', aging_bucket_label_en: '90+ days overdue',
      risk_score: 81, open_service_issues: 1, case: { next_action: 'CALL', next_action_on: '2026-10-24' },
    },
  ],
  meta: { total: 2, business_date: '2026-10-23', source_name: 'New Order Master', source_label: 'SHEET' },
  page: { limit: 50, returned: 2, has_more: false, next_cursor: null },
}

export const DICTIONARIES = {
  CONTACT_RESULT: { name: 'CONTACT_RESULT', values: [
    { code: 'REACHED_ANSWERED', label_th: 'ติดต่อได้ - รับสาย', label_en: 'Reached, answered', active: true },
    { code: 'UNREACHABLE_NO_ANSWER', label_th: 'ติดต่อไม่ได้ - ไม่รับสาย', label_en: 'Unreachable', active: true },
  ] },
  NEXT_ACTION: { name: 'NEXT_ACTION', values: [
    { code: 'FOLLOW_PTP', label_th: 'ตรวจสอบยอดตามนัด', label_en: 'Check the promise', active: true },
    { code: 'CALL', label_th: 'โทรติดตาม', label_en: 'Call', active: true },
  ] },
  DC_STATUS: { name: 'DC_STATUS', values: [
    { code: 'NO_ACTION', label_th: 'ยังไม่ดำเนินการ', label_en: 'No Action', active: true },
  ] },
}

export const OFFICERS = { officers: [
  { uid: 'rungnapa', display_name_th: 'รุ่งนภา ทองดี', display_name_en: 'Rungnapa', role: 'OFFICER', roles: ['OFFICER'] },
  { uid: 'somchai', display_name_th: 'สมชาย ใจกล้า', display_name_en: 'Somchai', role: 'OFFICER', roles: ['OFFICER'] },
] }

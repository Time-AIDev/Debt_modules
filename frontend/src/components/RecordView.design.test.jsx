import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { setRole } from '../lib/identity.jsx'
import { RecordView } from './RecordView.jsx'
import { CASE } from '../test-fixtures.js'

vi.mock('../lib/api.js', () => ({
  api: new Proxy({}, {
    get: (target, prop) => {
      if (!(prop in target)) target[prop] = vi.fn(async () => ({}))
      return target[prop]
    },
  }),
  CHANGED_EVENT: 'volt:changed',
  AUTH_REQUIRED_EVENT: 'volt:auth-required',
}))
const { api } = await import('../lib/api.js')

const DICTS = {
  NEXT_ACTION: [
    { code: 'CALL', label_th: 'โทรติดตาม', label_en: 'Call', active: true },
    { code: 'FOLLOW_PTP', label_th: 'ตรวจสอบยอดตามนัด', label_en: 'Check the promise', active: true },
    { code: 'CONFIRM_SLIP', label_th: 'ตรวจสลิป', label_en: 'Confirm slip', active: true },
  ],
  CONTACT_RESULT: [
    { code: 'REACHED_PTP', label_th: 'ติดต่อได้ (โทรศัพท์) - นัดชำระ', label_en: 'Reached by phone — PTP', active: true },
  ],
}

const BIZ = '2026-10-23'
const ptp = (uid, status, date, amount, over = {}) => ({ uid, status, promise_date: date, promised_amount: amount, ...over })

function kase(over = {}, data = {}) {
  return {
    ...CASE,
    case: { ...CASE.case, next_action: 'CALL', next_action_on: BIZ, ...over },
    ptps: [],
    work_item: { ...CASE.work_item, tier: undefined, contact_lock: { state: 'OPEN' } },
    ...data,
  }
}

function todo() {
  return screen.getByRole('region', { name: 'สิ่งที่ต้องทำ' })
}

function view(data, props = {}) {
  return renderScreen(<RecordView data={data} businessDate={BIZ} onChanged={() => {}} onLogContact={() => {}} {...props} />)
}

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
  setRole('OFFICER')
  api.dictionary.mockImplementation(async (name) => ({ name, values: DICTS[name] || [] }))
})

describe('① สิ่งที่ต้องทำ — each fact said once (Arina, 2026-09-24)', () => {
  it('folds a promise due today into the reason and never repeats it', async () => {
    view(kase({ next_action: 'FOLLOW_PTP' }, { ptps: [ptp('p-1', 'OPEN', BIZ, '6985.42')] }), { item: { tier: 'PTP_DUE_TODAY' } })
    const box = todo()
    expect(await within(box).findByText('ตรวจสอบยอดตามนัด')).toBeInTheDocument()   // today's task: no date
    expect(within(box).getByText('นัดชำระ ฿6,985.42 ถึงกำหนดวันนี้')).toBeInTheDocument()
    expect(box.textContent.split('6,985.42')).toHaveLength(2)                     // the amount, once
    // the tier word is the head icon's name, and nothing else says it
    expect(within(box).getByRole('img', { name: 'นัดชำระถึงกำหนดวันนี้' })).toHaveAttribute('title', 'นัดชำระถึงกำหนดวันนี้')
    expect(box.textContent).not.toContain('นัดชำระถึงกำหนดวันนี้')
    expect(within(box).queryByText('นัดเปิดอยู่')).toBeNull()                        // no second promise line
    expect(box).toHaveClass('case__todo--do')
  })

  it('says a broken promise once, the new one on its own line, and drops the date the promise already gives', async () => {
    const data = kase({ next_action: 'FOLLOW_PTP', next_action_on: '2026-10-30', last_result: 'REACHED_PTP' }, {
      ptps: [ptp('p-1', 'RENEGOTIATED', '2026-10-20', '6100.00'), ptp('p-2', 'OPEN', '2026-10-30', '5000.00')],
    })
    view(data, { item: { tier: 'BROKEN_PTP', worked_today: true, worked_at: '2026-10-23T11:05:00+07:00' } })
    const box = todo()
    expect(await within(box).findByText('ตรวจสอบยอดตามนัด')).toBeInTheDocument()
    expect(within(box).getByText('ผิดนัด ฿6,100.00 (นัด 20/10/2026)')).toBeInTheDocument()
    expect(within(box).getByText('นัดเปิดอยู่')).toBeInTheDocument()
    expect(within(box).getByText('30/10/2026 · ฿5,000.00')).toBeInTheDocument()
    expect(box.textContent.split('30/10/2026')).toHaveLength(2)
    expect(within(box).getByText('ติดตามแล้ว 11:05 · ติดต่อได้ (โทรศัพท์) - นัดชำระ')).toBeInTheDocument()   // today: the time alone
    expect(box).toHaveClass('case__todo--problem')
  })

  it('names a broken promise with nothing after it as not renegotiated, and says it only there', async () => {
    view(kase({}, { ptps: [ptp('p-1', 'BROKEN', '2026-10-15', '4850.00')] }), { item: { tier: 'BROKEN_PTP' } })
    const box = todo()
    expect(await within(box).findByText('โทรติดตาม')).toBeInTheDocument()
    expect(within(box).getByText('ผิดนัด ฿4,850.00 (นัด 15/10/2026) · ยังไม่ได้เจรจาใหม่')).toBeInTheDocument()
    expect(within(box).queryByText('ผิดนัด')).toBeNull()                             // no pill repeating it
  })

  it('gives a later task its date and an other tier its word as the reason', async () => {
    view(kase({ next_action_on: '2026-10-24' }), { item: { tier: 'AT_RISK_TWO_MISSED' } })
    const box = todo()
    expect(await within(box).findByText('โทรติดตาม · 24/10/2026')).toBeInTheDocument()
    expect(within(box).getByText('ค้างสองงวดขึ้นไป ไม่มีนัดชำระ')).toBeInTheDocument()
  })

  it('says a worked contact that took the day\'s lock once, on one line', async () => {
    const lock = { state: 'LOCKED', locked_by: 'noon', locked_at_local_th: '23/10/2026 เวลา 09:25 น.' }
    const data = kase({ last_result: 'REACHED_PTP' }, { work_item: { ...CASE.work_item, tier: undefined, contact_lock: lock } })
    const { unmount } = view(data, { item: { tier: 'ROUTINE', worked_today: true, worked_at: '2026-10-23T09:25:04' } })
    let box = todo()
    expect(await within(box).findByText('ติดตามแล้ว 09:25 · ติดต่อได้ (โทรศัพท์) - นัดชำระ · ใช้สิทธิ์ติดต่อวันนี้แล้ว · noon')).toBeInTheDocument()
    expect(box.textContent.split('09:25')).toHaveLength(2)
    unmount()
    // a later, uncounted contact is another fact: the lock keeps its own line
    view(data, { item: { tier: 'ROUTINE', worked_today: true, worked_at: '2026-10-23 11:40:00' } })
    box = todo()
    expect(await within(box).findByText('ใช้สิทธิ์ติดต่อวันนี้แล้ว · noon · 09:25')).toBeInTheDocument()
    expect(within(box).getByText('ติดตามแล้ว 11:40 · ติดต่อได้ (โทรศัพท์) - นัดชำระ')).toBeInTheDocument()
  })

  it('keeps a later task\'s time beside its date', async () => {
    view(kase({ next_action_on: '2026-10-24T14:00' }), { item: { tier: 'NEXT_ACTION_DUE' } })
    expect(await within(todo()).findByText('โทรติดตาม · 24/10/2026 14:00')).toBeInTheDocument()
  })

  it('says when no next task is set, headed by the payment status off Today', async () => {
    view(kase({ next_action: null, next_action_on: null, payment_status: 'NPL' }))
    const box = todo()
    expect(await within(box).findByText('NPL')).toBeInTheDocument()
    expect(within(box).getByText('ยังไม่ได้ตั้งงานถัดไป')).toBeInTheDocument()
    expect(box).toHaveClass('case__todo--problem')
  })

  it('adds money in (with the close), the day’s lock, and closes the promise as kept', async () => {
    const user = userEvent.setup()
    api.closeCasePtp.mockResolvedValue({})
    const data = kase({ next_action: 'CONFIRM_SLIP' }, {
      ptps: [ptp('p-1', 'OPEN', '2026-10-25', '135000.00', {
        paid_before_due: { receipt_no: 'RV-0412', on: '2026-10-22', amount: '135000.00' },
      })],
      work_item: {
        ...CASE.work_item, tier: undefined,
        contact_lock: { state: 'LOCKED', locked_by: 'ploy', locked_at_local_th: '23/10/2026 เวลา 10:15 น.' },
      },
    })
    view(data, { item: { tier: 'NEXT_ACTION_DUE' } })
    const box = todo()
    expect(await within(box).findByText('ตรวจสลิป')).toBeInTheDocument()
    expect(within(box).getByText('25/10/2026 · ฿135,000.00')).toBeInTheDocument()
    expect(within(box).getByText('เงินเข้าก่อนนัด · RV-0412 · ฿135,000.00 · 22/10/2026')).toBeInTheDocument()
    expect(within(box).getByText('ใช้สิทธิ์ติดต่อวันนี้แล้ว · ploy · 10:15')).toBeInTheDocument()
    await user.click(within(box).getByRole('button', { name: 'ปิดนัด: ชำระแล้ว' }))
    await waitFor(() => expect(api.closeCasePtp).toHaveBeenCalledWith('p-1', {
      outcome: 'KEPT', on: '2026-10-22', reason: 'RV-0412', by: undefined,
    }))
  })
})

describe('the case header and tabs (design D)', () => {
  it('offers social composers only when Odoo supplied the channel identifier', async () => {
    const { unmount } = view(kase())
    expect(await screen.findByRole('button', { name: 'LINE' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'LINE' })).toHaveAttribute('title', 'ไม่มี LINE ในระบบ')
    expect(screen.getByRole('button', { name: 'Facebook' })).toBeDisabled()
    unmount()
    view({ ...kase(), customer: { ...CASE.customer, line_id: 'U-line', meta_id: 'U-meta' } })
    expect(await screen.findByRole('button', { name: 'LINE' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Facebook' })).toBeEnabled()
  })

  it('lets an officer terminate a live contract and excludes OPS', async () => {
    const { unmount } = view(kase())
    const officer = await screen.findByRole('button', { name: 'ยุติสัญญา' })
    expect(officer).toBeEnabled()
    const user = userEvent.setup()
    await user.click(officer)
    expect(await screen.findByRole('dialog', { name: 'ยุติสัญญาลูกค้ารายนี้' })).toBeInTheDocument()
    unmount()
    setRole('OPS')
    view(kase())
    expect(await screen.findByRole('button', { name: 'ยุติสัญญา' })).toBeDisabled()
  })

  it('hides termination when every contract has already ended', async () => {
    view(kase({ payment_status: 'CLOSED' }, { contracts: [{ ...CASE.contracts[0], status: 'CLOSED' }] }))
    expect(screen.queryByRole('button', { name: 'ยุติสัญญา' })).toBeNull()
  })

  it('carries a close in the pop-up sheet that calls onClose', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    view(kase(), { mode: 'sheet', onClose })
    await user.click(await screen.findByRole('button', { name: 'ปิด' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('keeps the cycle provenance one click away in the card head', async () => {
    const user = userEvent.setup()
    view({ ...kase(), payment_summary: { ...CASE.payment_summary, contracts: [], provenance_th: 'ตัวเลขเสิร์ฟจาก API' } })
    const card = (await screen.findAllByText('ตารางงวด')).find((el) => el.tagName === 'H2').closest('.card')
    await user.click(within(card).getByRole('button', { name: 'ข้อมูลเพิ่มเติม' }))
    expect(within(card).getByText('ตัวเลขเสิร์ฟจาก API')).toBeInTheDocument()
  })

  it('explains that the displayed CASH instalment count comes from PEAK', async () => {
    const user = userEvent.setup()
    view(kase({}, { payment_summary: { ...CASE.payment_summary,
      display_instalments: { total_count: 2, paid_count: 1, remaining_count: 1, overdue_count: 1,
        contract_outstanding: '325000.00', peak_outstanding: '165000.00',
        provenance_th: 'จำนวนงวดจากใบแจ้งหนี้ PEAK ที่ยืนยันสัญญา', contracts: [] } } }))
    const card = (await screen.findAllByText('ตารางงวด')).find((el) => el.tagName === 'H2').closest('.card')
    await user.click(within(card).getByRole('button', { name: 'ข้อมูลเพิ่มเติม' }))
    expect(within(card).getByText('จำนวนงวดจากใบแจ้งหนี้ PEAK ที่ยืนยันสัญญา')).toBeInTheDocument()
  })

  it('says the history in words: channel, allowance, event kinds and ticket teams', async () => {
    const user = userEvent.setup()
    view({
      ...kase(),
      contact_allowance: { used: 3, cap: 1 },
      events: [{ kind: 'PTP_PAYMENT_NOTICED', on: '2026-10-22', by: 'SYSTEM' }],
      issues: [{ uid: 'i-1', status: 'IN_PROGRESS', summary: 'อินเวอร์เตอร์ดับ', responsible_team: 'CS', deadline: '2026-10-26' }],
    })
    await user.click(await screen.findByRole('tab', { name: /ประวัติการติดต่อ/ }))
    expect(screen.getByText(/โทรศัพท์ ·/)).toBeInTheDocument()
    expect(screen.getByText('ใช้สิทธิ์ติดต่อสัปดาห์นี้ 3 ครั้ง · เพดานวันละ 1 ครั้ง')).toBeInTheDocument()
    expect(screen.getByText('พบเงินเข้าก่อนนัด')).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: /ตั๋วปัญหา/ }))
    expect(screen.getByText('กำลังแก้')).toBeInTheDocument()
    expect(screen.getByText('ทีมบริการลูกค้า (CS) · 26/10/2026')).toBeInTheDocument()
  })

  it('shows the amount-led pending form to an officer without a manager gate', async () => {
    const user = userEvent.setup()
    api.attachments.mockResolvedValue({ attachments: [] })
    view(kase())
    await user.click(await screen.findByRole('tab', { name: 'ใบแจ้งหนี้และเงินเข้า' }))
    expect(await screen.findByLabelText('ยอดที่ลูกค้าชำระ')).toBeEnabled()
    expect(screen.getByLabelText('วันที่รับเงิน')).toBeEnabled()
    expect(screen.getByRole('button', { name: 'ตรวจสอบการทบยอด' })).toBeDisabled()
    expect(screen.queryByText('เฉพาะผู้จัดการขึ้นไป')).not.toBeInTheDocument()
  })

  it('opens an Odoo identity with its served note and the reason in Thai', async () => {
    view({
      identity_only: true, reason: 'no money row in Odoo', order: { order_type: 'LEASE', watt: 5450 },
      customer: { uid: 'i-1', display_name: 'ลูกค้า Odoo', volt_id: 'V-2315', data_source: 'ODOO' },
      identity_note_th: 'ลูกค้ารายนี้มาจาก Odoo crm.lead — ยังไม่มียอดเงินหรือสัญญาในระบบ จึงยังไม่มีเคสติดตาม',
    })
    expect(await screen.findByRole('heading', { name: 'ลูกค้า Odoo' })).toBeInTheDocument()
    expect(screen.getByText('LEASE · สัญญาเช่า')).toBeInTheDocument()
    expect(screen.getByText('5,450')).toBeInTheDocument()
    expect(screen.getByText('เหตุที่ยังไม่มีเคส: ยังไม่มียอดเงินใน Odoo')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'บันทึกผลการติดต่อ' })).toBeNull()
  })

  it('shows the pop-up\'s close while the case loads and when it is refused', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    const { unmount } = renderScreen(<RecordView data={null} mode="sheet" onClose={onClose} />)
    await user.click(screen.getByRole('button', { name: 'ปิด' }))
    expect(onClose).toHaveBeenCalledTimes(1)
    unmount()
    renderScreen(<RecordView data={null} problem={{ code: 'request_failed', message_th: 'โหลดเคสไม่ได้' }} mode="sheet" onClose={onClose} />)
    expect(screen.getByText('โหลดเคสไม่ได้')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'ปิด' }))
    expect(onClose).toHaveBeenCalledTimes(2)
  })

  it('marks a contact recorded as the customer\'s own and one declared not counted', async () => {
    const user = userEvent.setup()
    view({ ...kase(), contact_log: [
      { uid: 'k-2', occurred_at: '2026-10-23T11:00:00', channel: 'PHONE', result: 'REACHED_PTP', direction: 'OUTBOUND', counted: false, not_counted_declared: true },
      { uid: 'k-1', occurred_at: '2026-06-30 14:58:58', channel: 'PHONE', result: 'REACHED_PTP', direction: 'INBOUND', counted: false },
    ] })
    await user.click(await screen.findByRole('tab', { name: /ประวัติการติดต่อ/ }))
    expect(screen.getByText('ไม่นับครั้ง')).toBeInTheDocument()
    expect(screen.getByText(/ติดต่อได้ \(โทรศัพท์\) - นัดชำระ · ลูกค้าติดต่อเข้า/)).toBeInTheDocument()
    expect(screen.getByText('30/06 14:58')).toBeInTheDocument()                    // an imported stamp keeps its time
  })

  it('keeps a refused close on the PTP card, where it was pressed', async () => {
    const user = userEvent.setup()
    api.closeCasePtp.mockRejectedValue({ problem: { code: 'ptp_closed', message_th: 'นัดชำระนี้ปิดแล้ว' } })
    view(kase({}, { ptps: [ptp('p-1', 'OPEN', '2026-10-25', '5000.00', {
      paid_before_due: { receipt_no: 'RV-1', on: '2026-10-22', amount: '5000.00' },
    })] }))
    const card = (await screen.findByText('นัดชำระ (PTP) และตั๋วปัญหา')).closest('.card')
    await user.click(within(card).getByRole('button', { name: 'ปิดนัด: ชำระแล้ว' }))
    expect(await within(card).findByText('นัดชำระนี้ปิดแล้ว')).toBeInTheDocument()
    expect(within(todo()).queryByText('นัดชำระนี้ปิดแล้ว')).toBeNull()
  })

  it('says a refused PEAK-code search as the refusal, not as "no match"', async () => {
    const user = userEvent.setup()
    api.attachments.mockResolvedValue({ attachments: [] })
    api.casePeakCodes.mockRejectedValue({ problem: { code: 'database_required', message_th: 'ต้องมีฐานข้อมูลก่อน' } })
    view(kase())
    await user.click(await screen.findByRole('tab', { name: 'ใบแจ้งหนี้และเงินเข้า' }))
    await user.type(screen.getByLabelText(/ค้นหารหัสผู้ติดต่อ PEAK/), 'VC')
    expect(await screen.findByText('ต้องมีฐานข้อมูลก่อน')).toBeInTheDocument()
    expect(screen.queryByText('ไม่พบรหัสผู้ติดต่อ PEAK ที่ตรงกับคำค้น')).toBeNull()
  })
})

describe('invoice waiting label and Odoo identity', () => {
  it('shows Awaiting on an unpaid PEAK invoice', async () => {
    const user = userEvent.setup()
    view(kase({}, { invoices: [{ ...CASE.invoices[0], state: 'SENT', source: 'PEAK_REPORT', link_sent: false }] }))
    await user.click(await screen.findByRole('tab', { name: 'ใบแจ้งหนี้และเงินเข้า' }))
    expect(await screen.findByText('Awaiting')).toBeInTheDocument()
  })

  it('copies the exact Odoo lead name separately from the customer number', async () => {
    const user = userEvent.setup()
    view(kase({}, { customer: { ...CASE.customer, volt_id: 'old_sheet_name', customer_no: '28006752779',
      odoo_crm: { url: 'https://odoo.example.com/web#id=163222', name: '28006752779_Danudech_ดนุเดช เลขะสันต์_VOLT' } } }))
    const copy = await screen.findByRole('button', { name: 'คัดลอกชื่อจาก Odoo' })
    expect(screen.getByRole('link', { name: '28006752779_Danudech_ดนุเดช เลขะสันต์_VOLT' })).toHaveAttribute('href', 'https://odoo.example.com/web#id=163222')
    expect(screen.getByText('28006752779', { exact: true })).toBeInTheDocument()
    await user.click(copy)
    expect(await navigator.clipboard.readText()).toBe('28006752779_Danudech_ดนุเดช เลขะสันต์_VOLT')
    expect(await screen.findByRole('status')).toHaveTextContent('คัดลอกแล้ว')
  })
})

it('removes the prerequisite contract confirmation form from overview', () => {
  setRole('MANAGER')
  api.confirmContractSchedule.mockResolvedValue({ confirmation: {
    first_due: '2025-10-10', document_ref: 'signed.pdf', confirmed_by: 'Manager', reason: 'checked',
  } })
  view(kase({}, { contracts: [{ uid: 'K-review', product: 'LEASE', first_due: '2025-02-10' }],
    payment_summary: { contracts: [{ contract_uid: 'K-review', product: 'LEASE', requires_schedule_confirmation: true, schedule_verified: false,
      cycles: [], unplaced_peak_details: [] }], totals: { counts: {}, cycle_count: 0 } } }))
  expect(screen.queryByLabelText('วันครบกำหนดงวดแรกตามสัญญา')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'ยืนยันวันเริ่มงวด' })).not.toBeInTheDocument()
})

it('does not display a sheet balance as confirmed or its M mark as a verified contract cycle', async () => {
  const user = userEvent.setup()
  view(kase({}, { invoices: [{ ...CASE.invoices[0], uid: 'sheet-review',
    payment_evidence: 'UNCONFIRMED', confirmed_paid: null, confirmed_outstanding: null,
    projected_outstanding: null, month_index: 17, contract_cycle: null,
    unmatched_reason: 'CONTRACT_UNCONFIRMED', outstanding: '12323.00',
  }] }))
  await user.click(screen.getByRole('tab', { name: /ใบแจ้งหนี้/ }))
  const table = screen.getByRole('table', { name: /ใบแจ้งหนี้/ })
  expect(within(table).getByText('ยังไม่ยืนยันหลักฐาน')).toBeInTheDocument()
  expect(within(table).queryByText('M17')).not.toBeInTheDocument()
  expect(within(table).queryByText(/12,323\.00/)).not.toBeInTheDocument()
})

it('shows confirmed receipt money without presenting the sheet remainder as confirmed debt', async () => {
  const user = userEvent.setup()
  view(kase({}, { invoices: [{ ...CASE.invoices[0], uid: 'receipt-only',
    payment_evidence: 'CONFIRMED', liability_verified: false, confirmed_paid: '40.00',
    confirmed_outstanding: null, projected_outstanding: null, outstanding: '12323.00',
    contract_cycle: 1,
  }] }))
  await user.click(screen.getByRole('tab', { name: /ใบแจ้งหนี้/ }))
  const table = screen.getByRole('table', { name: /ใบแจ้งหนี้/ })
  expect(within(table).getByText(/รับชำระยืนยันแล้ว.*ยอดใบแจ้งหนี้รอตรวจสอบ/)).toBeInTheDocument()
  expect(within(table).getByText(/40\.00/)).toBeInTheDocument()
  expect(within(table).queryByText(/12,323\.00/)).not.toBeInTheDocument()
})

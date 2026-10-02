import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { setRole } from '../lib/identity.jsx'
import { CASE } from '../test-fixtures.js'
import { Recovery } from './Recovery.jsx'

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

// Made-up customers (never real names); shapes as /v1/npl-cases and friends serve them.
const STEPS_REPO = [{ label_th: 'ยึดคืนอุปกรณ์' }, { label_th: 'ตรวจนับอุปกรณ์ให้ตรง' }, { label_th: 'ขายต่อตามราคาล็อต' }]
const PATHS = {
  remaining_npv: '100000.00',
  paths: [
    { strategy: 'LEGAL', rate_pct: '38', expected_recovery: '38000.00', rate_is_assumption: true, available: true, next_steps: [{ label_th: 'ดำเนินคดี' }] },
    { strategy: 'REPOSSESSION', rate_pct: '38', expected_recovery: '38000.00', rate_is_assumption: true, available: true, next_steps: STEPS_REPO },
    { strategy: 'COOP_DECOMMISSION', rate_pct: '38', expected_recovery: '38000.00', rate_is_assumption: true, available: true, next_steps: [{ label_th: 'รื้อถอนโดยความยินยอม' }] },
    { strategy: 'EXTERNAL_COLLECTION', rate_pct: null, expected_recovery: null, rate_is_assumption: false, available: false, pending_decision: 'D27', next_steps: [] },
  ],
}
const row = (over) => ({
  case_uid: 'case-x', entity: 'SPV', volt_id: null, npl_type: null, npl_type_label: null, aggregate_overdue: '1000.00',
  remaining_npv: '100000.00', risk_score: 40, strategy: null, recovery_uid: null, payment_status: 'NPL',
  pending_decision: 'OD-04', source: 'DEMO', recovery_paths: PATHS, ...over,
})
const NPL = {
  npl_cases: [
    row({ uid: 'npl-a', customer_uid: 'c-a', display_name: 'ลูกค้า ก', npl_type: 'NPL_3', npl_type_label: 'NPL 3 - ไม่ให้ความร่วมมือ ดำเนินคดี', source: 'SHEET', origin: 'PAYMENT_STATUS' }),
    row({ uid: 'npl-b', customer_uid: 'c-b', display_name: 'ลูกค้า ข', recovery_uid: 'rec-b', strategy: 'REPOSSESSION', declared_on: '2026-09-14', declared_by: 'Owner', payment_status: 'LATE' }),
    row({ uid: 'npl-c', customer_uid: 'c-c', display_name: 'ลูกค้า ค', recovery_uid: 'rec-c' }),
  ],
  meta: {
    badge: 3,
    note_th: 'หนึ่งแถวต่อลูกค้า NPL หนึ่งราย',
    strategies: [
      { strategy: 'LEGAL', label_th: 'ดำเนินคดี', available: true, rate_pct: '38' },
      { strategy: 'REPOSSESSION', label_th: 'ยึดคืนอุปกรณ์', available: true, rate_pct: '38' },
      { strategy: 'COOP_DECOMMISSION', label_th: 'รื้อถอนโดยความยินยอม', available: true, rate_pct: '38' },
      { strategy: 'EXTERNAL_COLLECTION', label_th: 'ส่งสำนักงานเร่งรัดหนี้ภายนอก', available: false, pending_decision: 'D27', rate_pct: null },
    ],
  },
}
const LOT = {
  uid: 'lot-b', lot_no: 'RP-1', recovery_uid: 'rec-b', status: 'GRADED', expected_count: 12, actual_count: 11, count_variance: -1,
  grades: { A: 6, B: 4, C: 1 }, resale_price: null, stock_blocked: true, uninstall_fee: '25000.00', location: 'WH/REFURB', watt: 5000, product_code: 'PANEL-550-R',
}
const rec = (over) => ({
  entity: 'EPC', contract_uid: 'K-1', recoveries: [], recovered_total: '0.00', expected_recovery: '38000.00', remaining_npv: '100000.00',
  rate_pct: '38', rate_is_assumption: true, rate_basis_th: 'สมมติฐานเชิงพาณิชย์ — ยังไม่ใช่คำตัดสิน', lots: [], ...over,
})
const RECS = {
  recovery_cases: [
    rec({ uid: 'rec-b', source_ref: 'npl-b', strategy: 'REPOSSESSION', status: 'IN_PROGRESS', next_steps: STEPS_REPO, lots: [LOT] }),
    rec({ uid: 'rec-c', source_ref: 'npl-c', strategy: 'LEGAL', status: 'RESOLVED', outcome: 'FULL', resolved_on: '2026-10-20' }),
  ],
}
const refusal = (message_th) => Object.assign(new Error('refused'), { problem: { code: 'refused', message_th } })

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
  setRole('MANAGER')
  api.nplCases.mockResolvedValue(NPL)
  api.recoveryCases.mockResolvedValue(RECS)
  api.lots.mockResolvedValue({ lots: [LOT] })
  api.recoveryBoard.mockResolvedValue({ columns: [] })
  api.serviceBilling.mockResolvedValue({ accounts: [], meta: {} })
  api.caseDetail.mockResolvedValue(CASE)
})

const rowButton = (name) => screen.getByRole('button', { name: new RegExp(`^${name}`) })

describe('NPL cases (design E glyph list)', () => {
  it('groups by whether a path is open — a typed case without a path stays undecided — with no raw code or DPD noise', async () => {
    renderScreen(<Recovery />)
    await screen.findByRole('button', { name: /ยังไม่เลือกแนวทาง\s*1/ })
    expect(screen.getByRole('button', { name: /กำลังดำเนินการ\s*1/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /ปิดแล้ว\s*1/ })).toBeInTheDocument()
    expect(within(rowButton('ลูกค้า ก')).getByText('ยังไม่เลือกแนวทาง')).toBeInTheDocument()
    expect(within(rowButton('ลูกค้า ข')).getByText('เกรดแล้ว รอตั้งราคา')).toBeInTheDocument()
    expect(within(rowButton('ลูกค้า ค')).getByText('ปิดครบ')).toBeInTheDocument()
    expect(screen.queryByText(/ไม่มี DPD/)).toBeNull()
    // The case ref is not a row code (N4); it is a fact of the open row, not a hover-only title.
    expect(within(rowButton('ลูกค้า ก')).queryByText('npl-a')).toBeNull()
    expect(rowButton('ลูกค้า ก').querySelector('[title="npl-a"]')).toBeNull()
    expect(screen.getByText('เลขที่เคส').nextElementSibling).toHaveTextContent('npl-a')
    expect(screen.getByText('3 เคส · ยังไม่เลือกแนวทาง 1 · กำลังดำเนินการ 1 · ปิดแล้ว 1')).toBeInTheDocument()
  })

  it('opens the first row and confirms a path in place as a manager, posting the strategy', async () => {
    const user = userEvent.setup()
    api.openRecovery.mockResolvedValue({ recovery: {} })
    renderScreen(<Recovery />)
    const confirm = await screen.findByRole('button', { name: 'ยืนยันแนวทาง' })
    expect(confirm).toBeDisabled()
    expect(confirm).toHaveAttribute('title', 'เลือกแนวทางก่อน')
    expect(screen.getByTitle('ยังใช้ไม่ได้ · รอคำตัดสิน D27')).toBeInTheDocument()
    await user.click(screen.getByRole('radio', { name: /^ดำเนินคดี/ }))
    await user.click(confirm)
    const ask = screen.getByRole('group', { name: 'ยืนยันแนวทาง' })
    expect(ask).toHaveTextContent('เปิดแนวทาง ดำเนินคดี ให้ ลูกค้า ก?')
    await user.click(within(ask).getByRole('button', { name: 'ยืนยัน' }))
    await waitFor(() => expect(api.openRecovery).toHaveBeenCalledWith('npl-a', expect.objectContaining({ strategy: 'LEGAL', role: 'MANAGER' })))
    expect(await screen.findByText('เปิดแนวทางแล้ว · ดำเนินคดี')).toBeInTheDocument()
  })

  it('sends the optional reason typed in the in-place confirm (fix-all Leg R)', async () => {
    const user = userEvent.setup()
    api.openRecovery.mockResolvedValue({ recovery: {} })
    renderScreen(<Recovery />)
    await user.click(await screen.findByRole('radio', { name: /^ดำเนินคดี/ }))
    await user.click(screen.getByRole('button', { name: 'ยืนยันแนวทาง' }))
    const ask = screen.getByRole('group', { name: 'ยืนยันแนวทาง' })
    await user.type(within(ask).getByRole('textbox', { name: 'เหตุผล (ไม่บังคับ)' }), 'ลูกค้าไม่ตอบรับการเจรจา')
    await user.click(within(ask).getByRole('button', { name: 'ยืนยัน' }))
    await waitFor(() => expect(api.openRecovery).toHaveBeenCalledWith('npl-a', expect.objectContaining({
      strategy: 'LEGAL', reason: 'ลูกค้าไม่ตอบรับการเจรจา',
    })))
  })

  it('keeps the confirm disabled with its reason below manager', async () => {
    setRole('OFFICER')
    const user = userEvent.setup()
    renderScreen(<Recovery />)
    await user.click(await screen.findByRole('radio', { name: /^ดำเนินคดี/ }))
    const confirm = screen.getByRole('button', { name: 'ยืนยันแนวทาง' })
    expect(confirm).toBeDisabled()
    expect(confirm).toHaveAttribute('title', 'เฉพาะผู้จัดการขึ้นไป')
    expect(screen.getByText('ยืนยันแนวทาง: เฉพาะผู้จัดการขึ้นไป')).toBeInTheDocument()
  })

  it('shows the refusal where the path was confirmed', async () => {
    const user = userEvent.setup()
    api.openRecovery.mockRejectedValue(refusal('ไม่รู้จักกลยุทธ์การเรียกคืนที่ระบุ'))
    renderScreen(<Recovery />)
    await user.click(await screen.findByRole('radio', { name: /^ดำเนินคดี/ }))
    await user.click(screen.getByRole('button', { name: 'ยืนยันแนวทาง' }))
    await user.click(within(screen.getByRole('group', { name: 'ยืนยันแนวทาง' })).getByRole('button', { name: 'ยืนยัน' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('ไม่รู้จักกลยุทธ์การเรียกคืนที่ระบุ')
  })

  it('shows an open path as steps and records money in place; a write-off is the owner\'s', async () => {
    const user = userEvent.setup()
    api.recordRecovery.mockResolvedValue({ recovery: {} })
    renderScreen(<Recovery />)
    await user.click(await screen.findByRole('button', { name: /^ลูกค้า ข/ }))
    expect(screen.getByText('ตอนนี้: เกรดแล้ว รอตั้งราคา')).toBeInTheDocument()
    expect(screen.getByText('12 → 11')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'บันทึกเงินที่เรียกคืนได้' }))
    const form = screen.getByRole('region', { name: 'บันทึกเงินที่เรียกคืนได้' })
    await user.type(within(form).getAllByRole('textbox')[0], '1500')
    await user.click(within(form).getByRole('button', { name: 'บันทึก' }))
    await waitFor(() => expect(api.recordRecovery).toHaveBeenCalledWith('rec-b', expect.objectContaining({ amount: '1500', source: 'UNSPECIFIED' })))
    expect(await screen.findByText('บันทึกเงินที่เรียกคืนได้แล้ว')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'ปิดเคส…' }))
    const writeOff = screen.getByRole('radio', { name: 'ตัดจำหน่าย' })
    expect(writeOff).toBeDisabled()
    expect(writeOff.closest('label')).toHaveAttribute('title', 'การตัดจำหน่ายเป็นอำนาจของเจ้าของระบบเท่านั้น')
  })

  it('opens the case pop-up and the contact drawer from a row', async () => {
    const user = userEvent.setup()
    renderScreen(<Recovery />)
    await user.click(await screen.findByRole('button', { name: /เปิดเคสลูกค้า/ }))
    expect(screen.getByRole('dialog', { name: 'เคสลูกค้า' })).toBeInTheDocument()
    await waitFor(() => expect(api.caseDetail).toHaveBeenCalledWith('c-a'))
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'เคสลูกค้า' })).toBeNull())

    await user.click(screen.getByRole('button', { name: /^บันทึกผลการติดต่อ/ }))
    expect(await screen.findByRole('dialog', { name: 'บันทึกผลการติดต่อ' })).toBeInTheDocument()
  })

  it('keeps focus with the person through the in-place confirm', async () => {
    const user = userEvent.setup()
    renderScreen(<Recovery />)
    await user.click(await screen.findByRole('radio', { name: /^ดำเนินคดี/ }))
    await user.click(screen.getByRole('button', { name: 'ยืนยันแนวทาง' }))
    const ask = screen.getByRole('group', { name: 'ยืนยันแนวทาง' })
    expect(within(ask).getByRole('button', { name: 'ยืนยัน' })).toHaveFocus()
    await user.click(within(ask).getByRole('button', { name: 'ยกเลิก' }))
    expect(screen.getByRole('button', { name: 'ยืนยันแนวทาง' })).toHaveFocus()
  })

  it('shows the payment status of a declared case that is not NPL yet, and the case ref', async () => {
    const user = userEvent.setup()
    renderScreen(<Recovery />)
    await user.click(await screen.findByRole('button', { name: /^ลูกค้า ข/ }))
    expect(screen.getByText('สถานะการชำระ').nextElementSibling).toHaveTextContent('ค้างชำระ')
    expect(screen.getByText('เลขที่เคส').nextElementSibling).toHaveTextContent('npl-b')
  })

  it('gates "ย้ายแนวทาง…" on an open path to managers, with its reason', async () => {
    setRole('OFFICER')
    const user = userEvent.setup()
    renderScreen(<Recovery />)
    await user.click(await screen.findByRole('button', { name: /^ลูกค้า ข/ }))
    const move = screen.getByRole('button', { name: 'ย้ายแนวทาง…' })
    expect(move).toBeDisabled()
    expect(move).toHaveAttribute('title', 'เฉพาะผู้จัดการขึ้นไป')
    expect(screen.getByText('ย้ายแนวทาง: เฉพาะผู้จัดการขึ้นไป')).toBeInTheDocument()
  })

  it('refuses a path move on a closed case, and hands focus back to ⋯ when the drawer closes', async () => {
    const user = userEvent.setup()
    renderScreen(<Recovery />)
    await user.click(await screen.findByRole('radio', { name: /บอร์ดแนวทาง/ }))
    await user.click(screen.getByRole('button', { name: 'ตัวเลือกของ ลูกค้า ค' }))
    const closed = within(screen.getByRole('group', { name: 'ตัวเลือกของ ลูกค้า ค' })).getByRole('button', { name: 'ย้ายแนวทาง' })
    expect(closed).toBeDisabled()
    expect(closed).toHaveAttribute('title', 'เคสปิดแล้ว')

    const more = screen.getByRole('button', { name: 'ตัวเลือกของ ลูกค้า ข' })
    await user.click(more)
    await user.click(within(screen.getByRole('group', { name: 'ตัวเลือกของ ลูกค้า ข' })).getByRole('button', { name: 'ย้ายแนวทาง' }))
    expect(await screen.findByRole('dialog', { name: 'ย้ายแนวทาง' })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'ย้ายแนวทาง' })).toBeNull())
    expect(more).toHaveFocus()
  })

  it('folds the rules into "เกณฑ์และที่มา"', async () => {
    const user = userEvent.setup()
    renderScreen(<Recovery />)
    const toggle = await screen.findByRole('button', { name: 'เกณฑ์และที่มา' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await user.click(toggle)
    const list = screen.getByRole('list', { name: 'เกณฑ์และที่มา' })
    expect(list).toHaveTextContent('โอนสิทธิ์ 100% ของ NPV คงเหลือ')
    expect(list).toHaveTextContent('รอคำตัดสิน OD-04')
    expect(list).toHaveTextContent('หนึ่งแถวต่อลูกค้า NPL หนึ่งราย')
  })
})

describe('the other four tabs', () => {
  it('การเรียกคืน joins the customer, shows refusals and locks a closed record', async () => {
    const user = userEvent.setup()
    api.recordRecovery.mockRejectedValue(refusal('จำนวนเงินต้องเป็นค่าจำกัดและมากกว่าศูนย์'))
    renderScreen(<Recovery />)
    await user.click(await screen.findByRole('tab', { name: /^การเรียกคืน/ }))
    expect(within(rowButton('rec-b')).getByText('ลูกค้า ข')).toBeInTheDocument()
    expect(within(rowButton('rec-b')).getByText('กำลังดำเนินการ')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'บันทึกเงินที่เรียกคืนได้' }))
    await user.type(screen.getAllByRole('textbox')[0], '0')
    await user.click(screen.getByRole('button', { name: 'บันทึก' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('จำนวนเงินต้องเป็นค่าจำกัดและมากกว่าศูนย์')

    await user.click(rowButton('rec-c'))
    expect(within(rowButton('rec-c')).getByText('ปิดแล้ว')).toBeInTheDocument()
    const locked = screen.getByRole('button', { name: 'บันทึกเงินที่เรียกคืนได้' })
    expect(locked).toBeDisabled()
    expect(locked).toHaveAttribute('title', 'ปิดแล้ว — บันทึกเพิ่มไม่ได้')
  })

  it('กระดานเรียกคืน names the aging band in Thai, logs a contact and moves a stage with a reason', async () => {
    const user = userEvent.setup()
    api.recoveryBoard.mockResolvedValue({ columns: ['CONTACT', 'NEGOTIATE', 'PROMISE', 'ESCALATE', 'RECOVERY'].map((stage) => ({
      stage, cards: stage === 'CONTACT' ? [{ customer_uid: 'c-x', display_name: 'ลูกค้า จ', arrears: '500.00', aggregate_outstanding: '12345.00', payment_status: 'LATE', oldest_dpd: 40, aging_bucket: 'RISK_REVIEW' }] : [],
    })) })
    api.recoveryBoardMove.mockResolvedValue({})
    renderScreen(<Recovery />)
    await user.click(await screen.findByRole('tab', { name: /^กระดานเรียกคืน/ }))
    const contact = screen.getByRole('region', { name: 'ติดต่อ' })
    expect(within(contact).getByText('ค้าง 30 วันขึ้นไป')).toBeInTheDocument()
    expect(within(contact).getByText('DPD 40')).toBeInTheDocument()
    // fix-all Leg R: the balance line and the case's payment-status pill
    expect(within(contact).getByText('คงเหลือ ฿12,345.00')).toBeInTheDocument()
    expect(within(contact).getByText('ค้างชำระ')).toBeInTheDocument()
    expect(screen.queryByText('RISK_REVIEW')).toBeNull()

    await user.click(within(contact).getByRole('button', { name: 'บันทึกผลการติดต่อ' }))
    expect(await screen.findByRole('dialog', { name: 'บันทึกผลการติดต่อ' })).toBeInTheDocument()
    expect(api.caseDetail).toHaveBeenCalledWith('c-x')
    await user.keyboard('{Escape}')

    await user.click(within(contact).getByRole('button', { name: 'ย้ายขั้น ลูกค้า จ' }))
    const dialog = await screen.findByRole('dialog', { name: 'ย้ายขั้นการเรียกคืน' })
    expect(within(dialog).getByRole('button', { name: 'ติดต่อ ✓' })).toBeDisabled()
    await user.type(within(dialog).getByRole('textbox'), 'ลูกค้าขอเจรจา')
    await user.click(within(dialog).getByRole('button', { name: 'เจรจา' }))
    await waitFor(() => expect(api.recoveryBoardMove).toHaveBeenCalledWith(expect.objectContaining({
      customer_uid: 'c-x', to_stage: 'NEGOTIATE', reason: 'ลูกค้าขอเจรจา',
    })))
    expect(await screen.findByText('ย้ายขั้นแล้ว')).toBeInTheDocument()
  })

  it('ล็อตทรัพย์สิน gates the price to operations or the owner and sells after an in-place confirm', async () => {
    const user = userEvent.setup()
    api.lots.mockResolvedValue({ lots: [LOT, { ...LOT, uid: 'lot-2', lot_no: 'RP-2', status: 'PRICED', resale_price: '50000.00', stock_blocked: false }] })
    api.lotAct.mockResolvedValue({ lot: {} })
    renderScreen(<Recovery />)
    await user.click(await screen.findByRole('tab', { name: /^ล็อตทรัพย์สิน/ }))
    await user.click(rowButton('RP-1'))
    expect(screen.getByRole('button', { name: 'ตั้งราคา' })).toBeDisabled()
    expect(screen.getByText('ทีมปฏิบัติการหรือเจ้าของระบบเท่านั้น')).toBeInTheDocument()

    await user.click(rowButton('RP-2'))
    await user.click(screen.getByRole('button', { name: 'ขาย' }))
    const ask = screen.getByRole('group', { name: 'ขาย' })
    expect(ask).toHaveTextContent('ขายล็อต RP-2 ในราคา 50,000.00?')
    await user.click(within(ask).getByRole('button', { name: 'ยืนยัน' }))
    await waitFor(() => expect(api.lotAct).toHaveBeenCalledWith('lot-2', 'sell', expect.any(Object)))
    expect(await screen.findByText('ขายแล้ว · บันทึกเงินที่เรียกคืนได้')).toBeInTheDocument()
  })

  it('การเรียกคืน locks a superseded record and names the one that replaced it', async () => {
    const user = userEvent.setup()
    api.recoveryCases.mockResolvedValue({ recovery_cases: [
      rec({ uid: 'rec-old', source_ref: 'npl-b', strategy: 'LEGAL', status: 'SUPERSEDED', superseded_by: 'rec-new', superseded_on: '2026-10-23' }),
    ] })
    renderScreen(<Recovery />)
    await user.click(await screen.findByRole('tab', { name: /^การเรียกคืน/ }))
    expect(within(rowButton('rec-old')).getByText('ถูกแทนที่')).toBeInTheDocument()
    for (const name of ['บันทึกเงินที่เรียกคืนได้', 'ปิดเคส']) {
      const button = screen.getByRole('button', { name })
      expect(button).toBeDisabled()
      expect(button).toHaveAttribute('title', 'ถูกแทนที่แล้ว — บันทึกในการเรียกคืนใหม่ (rec-new)')
    }
    expect(screen.getByText('โดย rec-new · 23/10/2026')).toBeInTheDocument()
  })

  it('กระดานเรียกคืน says every band in Thai, the served band words first', async () => {
    const user = userEvent.setup()
    const card = (uid, aging, extra) => ({ customer_uid: uid, display_name: `ลูกค้า ${uid}`, arrears: '0.00', oldest_dpd: null, aging_bucket: aging, ...extra })
    api.recoveryBoard.mockResolvedValue({ columns: [{ stage: 'CONTACT', cards: [
      card('c1', 'CLOSED'), card('c2', 'LDR_45'), card('c3', 'SHEET_GT90'), card('c4', 'TERMINATED'),
      card('c5', 'CUSTOM_7', { aging_bucket_label_th: 'ค้างตามชุดของผู้จัดการ' }),
    ] }] })
    renderScreen(<Recovery />)
    await user.click(await screen.findByRole('tab', { name: /^กระดานเรียกคืน/ }))
    for (const said of ['ปิดสัญญา', 'ค้าง 45–59 วัน', 'ค้าง 90 วันขึ้นไป', 'ยุติสัญญา', 'ค้างตามชุดของผู้จัดการ']) {
      expect(screen.getByText(said)).toBeInTheDocument()
    }
    for (const code of ['CLOSED', 'LDR_45', 'SHEET_GT90', 'TERMINATED', 'CUSTOM_7']) expect(screen.queryByText(code)).toBeNull()
  })

  it('ล็อตทรัพย์สิน asks for the reason when the count differs, and shows the grade refusal', async () => {
    const user = userEvent.setup()
    api.lots.mockResolvedValue({ lots: [
      { ...LOT, uid: 'lot-p', lot_no: 'RP-P', status: 'PLANNED', expected_count: 10, actual_count: null, count_variance: null },
      { ...LOT, uid: 'lot-c', lot_no: 'RP-C', status: 'COUNTED', actual_count: 9 },
    ] })
    api.lotAct.mockImplementation(async (uid, act) => {
      if (act === 'grade') throw refusal('จำนวนเกรดต้องเท่ากับจำนวนที่นับได้')
      return { lot: {} }
    })
    renderScreen(<Recovery />)
    await user.click(await screen.findByRole('tab', { name: /^ล็อตทรัพย์สิน/ }))
    await user.click(rowButton('RP-P'))
    const why = screen.getByRole('textbox', { name: 'เหตุผลที่จำนวนไม่ตรง' })
    expect(why).not.toHaveAttribute('aria-required')
    await user.type(screen.getByRole('textbox', { name: /^นับได้/ }), '9')
    expect(why).toHaveAttribute('aria-required', 'true')
    await user.type(why, 'หาย 1 ชิ้น')
    await user.click(screen.getByRole('button', { name: 'บันทึกการตรวจนับ' }))
    await waitFor(() => expect(api.lotAct).toHaveBeenCalledWith('lot-p', 'count', expect.objectContaining({ actual_count: 9, variance_note: 'หาย 1 ชิ้น' })))

    await user.click(rowButton('RP-C'))
    await user.type(screen.getByRole('textbox', { name: /^A/ }), '5')
    await user.click(screen.getByRole('button', { name: 'บันทึกเกรด' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('จำนวนเกรดต้องเท่ากับจำนวนที่นับได้')
  })

  it('ค่าบริการเดือน 37+ keeps a decline already asked disabled, with its reason', async () => {
    const user = userEvent.setup()
    api.serviceBilling.mockResolvedValue({ meta: {}, accounts: [{
      contract_uid: 'K-8', customer: { display_name: 'ลูกค้า ช' }, month_index: 40, status: 'BILLING', monthly_amount: '399.00',
      decline_requested: true, decline_pending_decision: 'SVC-37', service_invoices: [],
    }] })
    renderScreen(<Recovery />)
    await user.click(await screen.findByRole('tab', { name: /^ค่าบริการเดือน 37\+/ }))
    await user.click(rowButton('K-8'))
    const asked = screen.getByRole('button', { name: 'บันทึกคำขอแล้ว' })
    expect(asked).toBeDisabled()
    expect(asked).toHaveAttribute('title', 'บันทึกคำขอแล้ว — รอคำตัดสิน SVC-37 · บิลยังเดินต่อ')
  })

  it('ล็อตทรัพย์สิน says so when there is none', async () => {
    const user = userEvent.setup()
    api.lots.mockResolvedValue({ lots: [] })
    renderScreen(<Recovery />)
    await user.click(await screen.findByRole('tab', { name: /^ล็อตทรัพย์สิน/ }))
    expect(screen.getByText('ยังไม่มีล็อต')).toBeInTheDocument()
  })

  it('ค่าบริการเดือน 37+ shows the billing refusal and records a decline once', async () => {
    const user = userEvent.setup()
    api.serviceBilling.mockResolvedValue({
      meta: { billing_window: { from_day: 25, to_day: 30 }, decline_pending_decision: 'SVC-37', decline_owner: 'Jo' },
      accounts: [{
        contract_uid: 'K-9', customer: { display_name: 'ลูกค้า ง' }, month_index: 39, status: 'BILLING', monthly_amount: '399.00',
        decline_requested: false, decline_pending_decision: 'SVC-37',
        service_invoices: [{ uid: 'inv-1', state: 'OVERDUE', due_date: '2026-09-25', amount: '399.00' }],
      }],
    })
    api.billService.mockRejectedValue(refusal('ออกบิลค่าบริการได้เฉพาะวันที่ 25-30 ของเดือนเท่านั้น'))
    api.declineService.mockResolvedValue({ recorded: true })
    renderScreen(<Recovery />)
    await user.click(await screen.findByRole('tab', { name: /^ค่าบริการเดือน 37\+/ }))
    const k9 = rowButton('K-9')
    expect(within(k9).getByText('ออกบิลอยู่ · ค้างบิล')).toBeInTheDocument()
    expect(within(k9).getByText('ค้าง 1 บิล (ครบ 25/09/2026)')).toBeInTheDocument()
    await user.click(k9)
    await user.click(screen.getByRole('button', { name: 'ออกบิล' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('ออกบิลค่าบริการได้เฉพาะวันที่ 25-30 ของเดือนเท่านั้น')
    await user.click(screen.getByRole('button', { name: 'บันทึกคำขอปฏิเสธ' }))
    await waitFor(() => expect(api.declineService).toHaveBeenCalledWith('K-9', expect.not.objectContaining({ by: expect.any(Object) })))
    expect(await screen.findByText('บันทึกคำขอแล้ว · บิลยังเดินต่อ')).toBeInTheDocument()
  })
})

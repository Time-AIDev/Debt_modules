import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { DATA_EPOCH_EVENT } from '../lib/events.js'
import { Today } from './Today.jsx'
import { TODAY, CASE, BOARD_COLUMNS, DICTIONARIES, OFFICERS } from '../test-fixtures.js'
import { PREFS_KEYS } from '../lib/prefs.jsx'
import { setRole } from '../lib/identity.jsx'

vi.mock('../lib/download.js', () => ({ downloadText: vi.fn(), downloadBlob: vi.fn() }))
const { downloadText } = await import('../lib/download.js')

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

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
  setRole('OFFICER')
  api.today.mockResolvedValue(TODAY)
  api.officers.mockResolvedValue(OFFICERS)
  api.boardColumns.mockResolvedValue(BOARD_COLUMNS)
  api.caseDetail.mockImplementation(async (uid) => (
    uid === 'c-2'
      ? { ...CASE, customer: { ...CASE.customer, uid: 'c-2', display_name: 'สมศรี พงษ์ไพบูลย์' } }
      : CASE
  ))
  api.dictionary.mockImplementation(async (name) => DICTIONARIES[name] || { name, values: [] })
  api.pipeline.mockResolvedValue({
    items: [{
      uid: 'pip-1', customer_uid: 'pre-1', customer_no: 'C-PRE-1', volt_id: 'VL-PRE-1',
      display_name: 'ลูกค้าก่อนติดตั้ง', entity: 'SPC', amount_due: '5000.00', case_dpd: null,
      risk_score: 12, sales_lead: 'sale-1', released_at: null,
      gate_down_payment: { state: 'OPEN' },
      conditions: [
        { key: 'contract_signed', passed: true },
        { key: 'down_payment', passed: false },
        { key: 'entity_resolved', passed: true },
      ],
    }],
    meta: { total: 1, business_date: '2026-10-23', invoice_owner_role: 'AR' },
  })
})

describe('Today', () => {
  it('switches workstreams through the URL and keeps pre-install separate from collection KPIs', async () => {
    const user = userEvent.setup()
    renderScreen(<Today />)
    const switcher = screen.getByRole('radiogroup', { name: 'ประเภทงาน' })
    expect(within(switcher).getByRole('radio', { name: 'ติดตามหนี้' })).toHaveAttribute('aria-checked', 'true')
    await user.click(within(switcher).getByRole('radio', { name: 'ก่อนติดตั้ง' }))
    await waitFor(() => expect(api.pipeline).toHaveBeenCalled())
    expect(within(switcher).getByRole('radio', { name: 'ก่อนติดตั้ง' })).toHaveAttribute('aria-checked', 'true')
    expect(await screen.findByText('ลูกค้าก่อนติดตั้ง')).toBeInTheDocument()
    expect(screen.getByText('ติดเงื่อนไข')).toBeInTheDocument()
    expect(screen.getByText('รอเงินดาวน์')).toBeInTheDocument()
    expect(screen.queryByText('สรุปการติดตามวันนี้')).not.toBeInTheDocument()
    expect(api.caseDetail).toHaveBeenCalledWith('pre-1')
  })

  it('lets an officer select and export rows with a required reason', async () => {
    api.todayExport.mockResolvedValue({ text: 'customer_uid\nc-1\n', filename: 'selected.csv' })
    const user = userEvent.setup()
    renderScreen(<Today />)
    await user.click(await screen.findByLabelText('เลือก ปัทมวรรณ สุขเจริญ'))
    expect(screen.queryByText('มอบหมายให้')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'ส่งออกที่เลือก' }))
    const dialog = await screen.findByRole('dialog', { name: 'ส่งออกรายการที่เลือก' })
    const run = within(dialog).getByRole('button', { name: 'ส่งออก' })
    expect(run).toBeDisabled()
    await user.type(within(dialog).getByRole('textbox'), 'ตรวจยอดกับทีม AR')
    await user.click(run)
    await waitFor(() => expect(api.todayExport).toHaveBeenCalledWith({
      workstream: 'collection', customer_uids: ['c-1'], reason: 'ตรวจยอดกับทีม AR',
    }))
    expect(downloadText).toHaveBeenCalledWith('selected.csv', 'customer_uid\nc-1\n')
  })

  it('resets selection when the workstream changes', async () => {
    const user = userEvent.setup()
    renderScreen(<Today />)
    await user.click(await screen.findByLabelText('เลือก ปัทมวรรณ สุขเจริญ'))
    expect(screen.getByText('เลือกแล้ว 1 รายการ')).toBeInTheDocument()
    const switcher = screen.getByRole('radiogroup', { name: 'ประเภทงาน' })
    await user.click(within(switcher).getByRole('radio', { name: 'ก่อนติดตั้ง' }))
    expect(await screen.findByText('ลูกค้าก่อนติดตั้ง')).toBeInTheDocument()
    expect(screen.queryByText('เลือกแล้ว 1 รายการ')).not.toBeInTheDocument()
  })

  it('draws the served tier groups with their counts', async () => {
    renderScreen(<Today />)
    expect(await screen.findByText('นัดชำระถึงกำหนดวันนี้')).toBeInTheDocument()
    expect(screen.getByText('ผิดนัด PTP')).toBeInTheDocument()
    const row = await screen.findByRole('button', { name: /ปัทมวรรณ/ })
    expect(within(row).getByText('V-1001')).toBeInTheDocument()
    expect(within(row).queryByText('48,600.00')).not.toBeInTheDocument()
    expect(within(row).queryByText('DPD 24')).not.toBeInTheDocument()
    expect(within(row).getByRole('img', { name: 'ไม่มี issue ticket เปิดอยู่' })).toBeInTheDocument()
    expect(within(row).getByTestId('pp-counts')).toHaveTextContent('จ่าย 11 · ค้าง 4')
  })

  it('offers only List and Board, and remembers the switch', async () => {
    const user = userEvent.setup()
    renderScreen(<Today />)
    await screen.findByText('นัดชำระถึงกำหนดวันนี้')
    const group = screen.getByRole('radiogroup', { name: 'มุมมอง' })
    expect(within(group).getAllByRole('radio').map((o) => o.textContent)).toEqual(['รายการ', 'บอร์ด'])
    expect(within(group).getByRole('radio', { name: 'รายการ' })).toHaveAttribute('aria-checked', 'true')
    await user.click(within(group).getByRole('radio', { name: 'บอร์ด' }))
    expect(within(group).getByRole('radio', { name: 'บอร์ด' })).toHaveAttribute('aria-checked', 'true')
    expect(window.localStorage.getItem(PREFS_KEYS.todayView)).toBe('board')
  })

  it('carries the compact payment position on a queue row', async () => {
    renderScreen(<Today />)
    const rows = await screen.findAllByTestId('payment-position')
    expect(rows.length).toBeGreaterThan(0)
    expect(within(rows[0]).getByTestId('pp-counts')).toHaveTextContent('จ่าย 11 · ค้าง 4')
  })

  it('loads the record for the selected row and shows the ladder path', async () => {
    const user = userEvent.setup()
    renderScreen(<Today />)
    await user.click(await screen.findByRole('button', { name: /สมศรี/ }))
    expect(await screen.findByRole('heading', { name: 'สมศรี พงษ์ไพบูลย์' })).toBeInTheDocument()
    expect(api.caseDetail).toHaveBeenCalledWith('c-2')
    expect(screen.getAllByText(/ขั้น 30 วัน/).length).toBeGreaterThan(0)
  })

  it('renders the selected case in the page flow', async () => {
    renderScreen(<Today />)
    await screen.findByRole('heading', { name: 'ปัทมวรรณ สุขเจริญ' })
    expect(document.querySelector('.today__case > .case')).toHaveClass('case--page')
  })

  it('opens the contact drawer and posts the daily slot with the mapped disposition', async () => {
    api.logContact.mockResolvedValue({ contact_id: 3, counted: true })
    api.logCaseContact.mockResolvedValue({ contact: { uid: 'ct-9' }, case: {} })
    const user = userEvent.setup()
    renderScreen(<Today />)
    await screen.findByRole('heading', { name: 'ปัทมวรรณ สุขเจริญ' })
    await user.click(screen.getByRole('button', { name: 'บันทึกผลการติดต่อ' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByLabelText(/ผลการติดต่อ/)).toHaveAttribute('aria-required', 'true')
    expect(within(dialog).getByLabelText(/งานถัดไป/)).toHaveAttribute('aria-required', 'true')
    expect(within(dialog).getByLabelText(/^วันที่/)).toHaveAttribute('aria-required', 'true')
    expect(within(dialog).getByLabelText('บันทึกเพิ่มเติม')).not.toHaveAttribute('aria-required')
    expect(within(dialog).queryByText('* ช่องที่ต้องกรอก')).toBeNull()   // design D: the red * says it
    await user.click(await screen.findByRole('button', { name: 'บันทึก' }))
    await waitFor(() => expect(api.logContact).toHaveBeenCalled())
    expect(api.logContact.mock.calls[0][0]).toMatchObject({
      customer_uid: 'c-1',
      disposition: 'ANS_DISCUSSED',
      channel: 'PHONE',
    })
    await waitFor(() => expect(api.logCaseContact).toHaveBeenCalled())
    expect(api.logCaseContact.mock.calls[0][1]).toMatchObject({
      result: 'REACHED_ANSWERED', counted: true, next_action: 'FOLLOW_PTP',
    })
  })

  it('renders the board from the served columns, empty columns included', async () => {
    window.localStorage.setItem(PREFS_KEYS.todayView, 'board')
    renderScreen(<Today />)
    const board = await screen.findByTestId('board')
    expect(within(board).getByText('โทรวันนี้')).toBeInTheDocument()
    expect(within(board).getByText('ยกระดับ')).toBeInTheDocument()
    expect(within(board).getByTestId('board-empty-col_01H8X')).toBeInTheDocument()
    expect(within(board).getByText('ปัทมวรรณ สุขเจริญ')).toBeInTheDocument()
  })

  it('reads the shared data-state once per screen mount', async () => {
    renderScreen(<Today />)
    await screen.findByText('นัดชำระถึงกำหนดวันนี้')
    await waitFor(() => expect(api.dataState).toHaveBeenCalled())
    // the epoch hook and the freshness line share one read (two before 2026-09-20)
    expect(api.dataState).toHaveBeenCalledTimes(1)
  })

  it('refetches the queue when another browser moves the import epoch', async () => {
    renderScreen(<Today />)
    await screen.findByText('นัดชำระถึงกำหนดวันนี้')
    await waitFor(() => expect(api.dataState).toHaveBeenCalled())
    const before = api.today.mock.calls.length
    act(() => { window.dispatchEvent(new CustomEvent(DATA_EPOCH_EVENT, { detail: { epoch: 99 } })) })
    await waitFor(() => expect(api.today.mock.calls.length).toBeGreaterThan(before))
  })

  it('moves a card through the drawer with a required reason', async () => {
    api.boardMove.mockResolvedValue({ applied: true, from_column_id: 'col_01H8Z', to_column_id: 'col_01H90', direction: 'FORWARD' })
    window.localStorage.setItem(PREFS_KEYS.todayView, 'board')
    const user = userEvent.setup()
    renderScreen(<Today />)
    const board = await screen.findByTestId('board')
    const cards = within(board).getAllByRole('button', { name: 'ย้าย…' })
    await user.click(cards[0])
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('textbox')).toHaveAttribute('aria-required', 'true')
    expect(within(dialog).getByRole('textbox').closest('label')).toHaveTextContent('*')
    // no reason → the field says so and nothing is sent
    await user.click(within(dialog).getByRole('button', { name: 'ยกระดับ' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent('ต้องระบุเหตุผลที่ย้าย')
    expect(api.boardMove).not.toHaveBeenCalled()
    // the current column stays in the list, disabled
    expect(within(dialog).getByRole('button', { name: 'รับปากชำระ ✓' })).toBeDisabled()
    await user.type(within(dialog).getByRole('textbox'), 'ลูกค้าไม่รับสาย')
    await user.click(within(dialog).getByRole('button', { name: 'ยกระดับ' }))
    await waitFor(() => expect(api.boardMove).toHaveBeenCalled())
    expect(api.boardMove.mock.calls[0][0]).toMatchObject({
      customer_uid: 'c-1', to_column_id: 'col_01H90', reason: 'ลูกค้าไม่รับสาย',
    })
  })

  it('opens a board card in the case pop-up instead of leaving the board', async () => {
    window.localStorage.setItem(PREFS_KEYS.todayView, 'board')
    const user = userEvent.setup()
    renderScreen(<Today />)
    const board = await screen.findByTestId('board')
    await user.click(within(board).getByRole('button', { name: 'สมศรี พงษ์ไพบูลย์' }))
    const sheet = await screen.findByRole('dialog', { name: 'เคสลูกค้า' })
    expect(await within(sheet).findByRole('heading', { name: 'สมศรี พงษ์ไพบูลย์' })).toBeInTheDocument()
    expect(api.caseDetail).toHaveBeenCalledWith('c-2')
    expect(screen.getByTestId('board')).toBeInTheDocument()
  })

  it('logs a contact from a board card inside the case pop-up, with the case\u2019s own facts', async () => {
    window.localStorage.setItem(PREFS_KEYS.todayView, 'board')
    const user = userEvent.setup()
    renderScreen(<Today />)
    const board = await screen.findByTestId('board')
    const card = within(board).getByRole('article', { name: 'สมศรี พงษ์ไพบูลย์' })
    await user.click(within(card).getByRole('button', { name: 'บันทึกผลการติดต่อ' }))
    const sheet = await screen.findByRole('dialog', { name: 'เคสลูกค้า' })
    const drawer = await within(sheet).findByRole('dialog', { name: 'บันทึกผลการติดต่อ' })
    expect(within(drawer).getByLabelText(/ผลการติดต่อ/)).toHaveAttribute('aria-required', 'true')
    // Esc closes the drawer and leaves the case open
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'บันทึกผลการติดต่อ' })).not.toBeInTheDocument())
    expect(screen.getByRole('dialog', { name: 'เคสลูกค้า' })).toBeInTheDocument()
  })

  it('keeps a pop-up log refusal and what was typed, then saves — refreshing the list and the docked case', async () => {
    api.logContact.mockResolvedValue({ contact_id: 3, counted: true })
    api.logCaseContact
      .mockRejectedValueOnce({ status: 409, problem: { code: 'ptp_already_closed', message_th: 'นัดนี้ปิดไปแล้ว', errors: [] } })
      .mockResolvedValue({ contact: { uid: 'ct-9' }, case: {} })
    // the served case carries its run's business date (payment_summary), the drawer's default day
    api.caseDetail.mockImplementation(async (uid) => ({
      ...CASE,
      payment_summary: { ...CASE.payment_summary, business_date: '2026-10-23' },
      customer: { ...CASE.customer, uid, display_name: uid === 'c-2' ? 'สมศรี พงษ์ไพบูลย์' : CASE.customer.display_name },
    }))
    window.localStorage.setItem(PREFS_KEYS.todayView, 'board')
    const user = userEvent.setup()
    renderScreen(<Today />)
    const board = await screen.findByTestId('board')
    const card = within(board).getByRole('article', { name: 'สมศรี พงษ์ไพบูลย์' })
    await user.click(within(card).getByRole('button', { name: 'บันทึกผลการติดต่อ' }))
    const sheet = await screen.findByRole('dialog', { name: 'เคสลูกค้า' })
    const drawer = await within(sheet).findByRole('dialog', { name: 'บันทึกผลการติดต่อ' })
    await user.type(within(drawer).getByLabelText('บันทึกเพิ่มเติม'), 'ลูกค้าขอเลื่อน')
    const lists = api.today.mock.calls.length
    const docked = () => api.caseDetail.mock.calls.filter(([uid]) => uid === 'c-1').length
    const before = docked()
    await user.click(within(drawer).getByRole('button', { name: 'บันทึก' }))
    // the refusal stays in the drawer with the typed note; the list and the docked case reload
    expect(await within(drawer).findByText('นัดนี้ปิดไปแล้ว')).toBeInTheDocument()
    await waitFor(() => expect(api.today.mock.calls.length).toBeGreaterThan(lists))
    await waitFor(() => expect(docked()).toBeGreaterThan(before))
    expect(screen.getByRole('dialog', { name: 'บันทึกผลการติดต่อ' })).toBeInTheDocument()
    expect(within(drawer).getByLabelText('บันทึกเพิ่มเติม')).toHaveValue('ลูกค้าขอเลื่อน')
    // the second try saves: the drawer closes, the case stays open
    await user.click(within(drawer).getByRole('button', { name: 'บันทึก' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'บันทึกผลการติดต่อ' })).not.toBeInTheDocument())
    expect(api.logCaseContact.mock.calls[1][1]).toMatchObject({ note: 'ลูกค้าขอเลื่อน' })
    expect(screen.getByRole('dialog', { name: 'เคสลูกค้า' })).toBeInTheDocument()
  })

  it('says so when the filtered list is empty, with a way back', async () => {
    api.today.mockImplementation(async (params) => (
      params?.unassigned ? { ...TODAY, items: [], meta: { ...TODAY.meta, total: 0, counts_by_tier: {} } } : TODAY
    ))
    const user = userEvent.setup()
    renderScreen(<Today />)
    await screen.findByText('นัดชำระถึงกำหนดวันนี้')
    await user.selectOptions(screen.getByLabelText('เจ้าหน้าที่'), '__unassigned__')
    expect(await screen.findByText('ไม่มีงานในมุมมองนี้')).toBeInTheDocument()
    expect(screen.getByText('ไม่มีเคสให้แสดง — รายการในมุมมองนี้ว่าง')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'ล้างตัวกรอง' }))
    expect(await screen.findByText('นัดชำระถึงกำหนดวันนี้')).toBeInTheDocument()
  })

  it('prints only compact customer facts and the accessible issue-ticket state', async () => {
    renderScreen(<Today />)
    const row = await screen.findByRole('button', { name: /สมศรี/ })
    expect(row.querySelector('.st--problem')).not.toBeNull()
    const first = screen.getByRole('button', { name: /ปัทมวรรณ/ })
    expect(first.querySelector('.st--done')).not.toBeNull()
    expect(first).toHaveAttribute('aria-current', 'true')
    expect(within(first).getByText('V-1001')).toBeInTheDocument()
    expect(within(first).queryByText('เสี่ยง 78')).not.toBeInTheDocument()
    expect(within(first).queryByText(/SPV|รุ่งนภา|DPD/)).not.toBeInTheDocument()
  })

  it('shows a refusal sentence from the served envelope', async () => {
    api.boardMove.mockRejectedValue({
      status: 409,
      problem: {
        code: 'board_move_review_open', message_th: 'มีคำขอที่ยังไม่ได้ตอบอยู่', errors: [],
        extensions: { blocking_reason: 'BROKEN_PTP' },
      },
    })
    window.localStorage.setItem(PREFS_KEYS.todayView, 'board')
    const user = userEvent.setup()
    renderScreen(<Today />)
    const board = await screen.findByTestId('board')
    await user.click(within(board).getAllByRole('button', { name: 'ย้าย…' })[0])
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByRole('textbox'), 'ทดสอบ')
    await user.click(within(dialog).getByRole('button', { name: 'ยกระดับ' }))
    expect(await screen.findByText('มีคำขอที่ยังไม่ได้ตอบอยู่')).toBeInTheDocument()
  })
})

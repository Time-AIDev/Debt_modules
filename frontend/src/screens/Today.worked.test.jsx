import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { setRole } from '../lib/identity.jsx'
import { Today } from './Today.jsx'
import { Record } from './Record.jsx'
import { TODAY, CASE, BOARD_COLUMNS, DICTIONARIES, OFFICERS } from '../test-fixtures.js'
import { DATA_EPOCH_EVENT } from '../lib/events.js'

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

const WORKED_AT = '2026-10-23T10:00:00+07:00'

function workedToday() {
  return {
    ...TODAY,
    items: [
      {
        ...TODAY.items[0],
        worked_today: true,
        worked_at: WORKED_AT,
        open_ptp: { uid: 'p-1', promised_amount: '48600.00', promise_date: '2026-10-23', paid_before_due: { receipt_no: 'RE-2026100022', on: '2026-10-20', amount: '48600.00' } },
      },
      { ...TODAY.items[1], worked_today: false, worked_at: null },
    ],
    meta: {
      ...TODAY.meta,
      worked_today_count: 1,
      daily_summary: {
        '*': { total: 2, not_yet: 1, worked: 1, ptp_count: 1, ptp_amount: '48600.00', unreachable: 0 },
        rungnapa: { total: 1, not_yet: 0, worked: 1, ptp_count: 1, ptp_amount: '48600.00', unreachable: 0 },
      },
    },
  }
}

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
  setRole('OFFICER')
  api.officers.mockResolvedValue(OFFICERS)
  api.boardColumns.mockResolvedValue(BOARD_COLUMNS)
  api.dictionary.mockImplementation(async (name) => DICTIONARIES[name] || { name, values: [] })
})

describe('Today worked rows and the daily summary (F17, D05)', () => {
  it('collects worked rows into the bottom group with the compact customer row and six-number strip', async () => {
    const user = userEvent.setup()
    api.today.mockResolvedValue(workedToday())
    renderScreen(<Today />)
    // the row moved out of its tier into the bottom group (collapsed until opened)
    const label = (await screen.findAllByText('ติดตามแล้ว')).find((el) => el.classList.contains('group__label'))
    const group = label.closest('.group')
    await user.click(label.closest('button'))
    expect(within(group).getByText('ปัทมวรรณ สุขเจริญ')).toBeInTheDocument()
    expect(within(group).getByText('V-1001')).toBeInTheDocument()
    expect(within(group).getByText('จ่าย 11 · ค้าง 4')).toBeInTheDocument()
    expect(within(group).queryByText('ติดตามแล้ว 23/10 10:00')).not.toBeInTheDocument()
    // and it is not in its old tier anymore
    expect(screen.queryByText('นัดชำระถึงกำหนดวันนี้')).not.toBeInTheDocument()
    // the daily summary prints the served numbers of the list on screen ("*": no filter)
    expect(screen.getByText('สรุปการติดตามวันนี้')).toBeInTheDocument()
    expect(screen.getByText('ติดตามแล้ว 1 จาก 2')).toBeInTheDocument()
    expect(screen.getByText('นัดชำระ').closest('.daysum__cell')).toHaveTextContent('1 · 48,600.00')
  })

  it('keeps the worked customer selected when its row drops into the worked group', async () => {
    api.today.mockResolvedValueOnce(TODAY).mockResolvedValue(workedToday())
    api.caseDetail.mockResolvedValue(CASE)
    api.dataState.mockResolvedValue({ epoch: 1, seen_epoch: 1, stale: false, serving: {} })
    renderScreen(<Today />)
    expect(await screen.findByRole('button', { name: /ปัทมวรรณ/ })).toHaveAttribute('aria-current', 'true')
    await waitFor(() => expect(api.dataState).toHaveBeenCalled())
    act(() => { window.dispatchEvent(new CustomEvent(DATA_EPOCH_EVENT, { detail: { epoch: 2 } })) })
    await screen.findByText('ติดตามแล้ว 1 จาก 2')
    // the row left its tier for the collapsed worked group; the case on the right stays
    expect(screen.queryByText('นัดชำระถึงกำหนดวันนี้')).not.toBeInTheDocument()
    expect(api.caseDetail).not.toHaveBeenCalledWith('c-2')
  })

  it('keeps a worked Pending customer in the worked group', async () => {
    const user = userEvent.setup()
    const payload = workedToday()
    payload.items[0] = {
      ...payload.items[0],
      case: { ...payload.items[0].case, payment_status: 'PENDING' },
    }
    api.today.mockResolvedValue(payload)
    renderScreen(<Today />)
    const label = (await screen.findAllByText('ติดตามแล้ว'))
      .find((el) => el.classList.contains('group__label'))
    const group = label.closest('.group')
    await user.click(label.closest('button'))
    expect(within(group).getByText('ปัทมวรรณ สุขเจริญ')).toBeInTheDocument()
  })

  it('picks the first row on screen when the arrears sort is on', async () => {
    const user = userEvent.setup()
    const row = (uid, name, overdue) => ({
      ...TODAY.items[1], tier: 'PTP_DUE_TODAY', aggregate_overdue: overdue,
      customer: { ...TODAY.items[1].customer, uid, display_name: name },
    })
    // the officer's list holds neither of the first rows, served smaller-arrears first
    api.today.mockImplementation(async (params) => (params?.officer
      ? { ...TODAY, items: [row('c-3', 'ชนิดา ใจดี', '20000.00'), row('c-4', 'มานพ เจริญผล', '90000.00')] }
      : TODAY))
    api.caseDetail.mockResolvedValue(CASE)
    renderScreen(<Today />)
    await screen.findByRole('button', { name: /ปัทมวรรณ/ })
    await user.click(screen.getByRole('button', { name: 'ลำดับเดิม' }))
    await user.selectOptions(screen.getByLabelText('เจ้าหน้าที่'), 'rungnapa')
    // the bigger arrears row sits first on screen, and it is the one selected
    expect(await screen.findByRole('button', { name: /มานพ/ })).toHaveAttribute('aria-current', 'true')
  })

  it('opens on the first row still to work, not on a worked one', async () => {
    api.today.mockResolvedValue(workedToday())
    api.caseDetail.mockResolvedValue(CASE)
    renderScreen(<Today />)
    const row = await screen.findByRole('button', { name: /สมศรี/ })
    expect(row).toHaveAttribute('aria-current', 'true')
    expect(api.caseDetail).toHaveBeenCalledWith('c-2')
  })

  it('keeps promise detail out of the compact customer row', async () => {
    const user = userEvent.setup()
    api.today.mockResolvedValue(workedToday())
    renderScreen(<Today />)
    const label = (await screen.findAllByText('ติดตามแล้ว')).find((el) => el.classList.contains('group__label'))
    const group = label.closest('.group')
    await user.click(label.closest('button'))
    expect(within(group).queryByText('เงินเข้าก่อนนัด · RE-2026100022')).not.toBeInTheDocument()
  })

  it('closes a paid promise as KEPT from the case page, with the receipt as the reason', async () => {
    setRole('OFFICER')
    const paidCase = {
      ...CASE,
      ptps: [{
        uid: 'p-1', promised_amount: '48600.00', promise_date: '2026-10-23', status: 'OPEN',
        paid_before_due: { receipt_no: 'RE-2026100022', on: '2026-10-20', amount: '48600.00' },
      }],
    }
    api.caseDetail.mockResolvedValue(paidCase)
    api.closeCasePtp.mockResolvedValue({ ptp: { uid: 'p-1', status: 'KEPT' } })
    const user = userEvent.setup()
    renderScreen(<Record />, { route: '/customers/c-1' })
    expect(await screen.findByText('เงินเข้าก่อนนัด · RE-2026100022')).toBeInTheDocument()
    // design D: the close sits in "สิ่งที่ต้องทำ" and on the PTP card — the first is ①'s
    await user.click(screen.getAllByRole('button', { name: 'ปิดนัด: ชำระแล้ว' })[0])
    expect(api.closeCasePtp).toHaveBeenCalledWith('p-1', {
      outcome: 'KEPT', on: '2026-10-20', reason: 'RE-2026100022', by: undefined,
    })
  })
})

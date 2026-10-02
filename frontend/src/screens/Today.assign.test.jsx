import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { setRole } from '../lib/identity.jsx'
import { Today } from './Today.jsx'
import { TODAY, CASE, BOARD_COLUMNS, DICTIONARIES, OFFICERS } from '../test-fixtures.js'

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
  setRole('SUPERVISOR')
  api.today.mockResolvedValue(TODAY)
  api.officers.mockResolvedValue(OFFICERS)
  api.boardColumns.mockResolvedValue(BOARD_COLUMNS)
  api.assignCustomers.mockResolvedValue({ officer_uid: 'rungnapa', assigned: ['c-1', 'c-2'], count: 2 })
  api.caseDetail.mockResolvedValue(CASE)
  api.dictionary.mockImplementation(async (name) => DICTIONARIES[name] || { name, values: [] })
})

describe('Today bulk assignment (F10)', () => {
  it('offers selection to officers while reserving assignment for supervisors', async () => {
    const { unmount } = renderScreen(<Today />)
    await screen.findByText('นัดชำระถึงกำหนดวันนี้')
    expect(screen.getAllByRole('checkbox')).toHaveLength(2)
    unmount()
    setRole('OFFICER')
    renderScreen(<Today />)
    await screen.findByText('นัดชำระถึงกำหนดวันนี้')
    expect(screen.getAllByRole('checkbox')).toHaveLength(2)
    expect(screen.queryByText('มอบหมายให้')).not.toBeInTheDocument()
  })

  it('assigns the ticked rows to one officer in one request and reloads', async () => {
    const user = userEvent.setup()
    renderScreen(<Today />)
    await screen.findByText('นัดชำระถึงกำหนดวันนี้')
    await user.click(screen.getByRole('checkbox', { name: 'เลือก ปัทมวรรณ สุขเจริญ' }))
    await user.click(screen.getByRole('checkbox', { name: 'เลือก สมศรี พงษ์ไพบูลย์' }))
    expect(screen.getByText('เลือกแล้ว 2 รายการ')).toBeInTheDocument()
    const loads = api.today.mock.calls.length
    await user.type(screen.getByLabelText('เหตุผล (ถ้ามี)'), 'แบ่งงานเช้า')
    await user.click(screen.getByRole('button', { name: 'มอบหมาย' }))
    await waitFor(() => expect(api.assignCustomers).toHaveBeenCalledTimes(1))
    expect(api.assignCustomers.mock.calls[0][0]).toMatchObject({
      customer_uids: ['c-1', 'c-2'], officer_uid: 'rungnapa', reason: 'แบ่งงานเช้า',
    })
    await waitFor(() => expect(api.today.mock.calls.length).toBeGreaterThan(loads))
    expect(screen.queryByText('เลือกแล้ว 2 รายการ')).not.toBeInTheDocument()
  })

  it('shows each officer\u2019s list size and the unassigned option, and sends unassigned=1', async () => {
    api.today.mockImplementation(async (params) => (
      params?.unassigned
        ? { ...TODAY, items: [], meta: { ...TODAY.meta, total: 0 } }
        : { ...TODAY, meta: { ...TODAY.meta, officer_totals: { rungnapa: 1 }, unassigned_total: 4 } }
    ))
    const user = userEvent.setup()
    renderScreen(<Today />)
    await screen.findByText('นัดชำระถึงกำหนดวันนี้')
    const filter = screen.getByLabelText('เจ้าหน้าที่')
    expect(within(filter).getByText('รุ่งนภา ทองดี · 1')).toBeInTheDocument()
    expect(within(filter).getByText('ยังไม่มอบหมาย · 4')).toBeInTheDocument()
    await user.selectOptions(filter, '__unassigned__')
    await waitFor(() => expect(api.today.mock.calls.some(([p]) => p?.unassigned === 1)).toBe(true))
  })

  it('offers the random deal to a supervisor disabled, with its reason', async () => {
    const user = userEvent.setup()
    renderScreen(<Today />)
    await screen.findByText('นัดชำระถึงกำหนดวันนี้')
    await user.click(screen.getByRole('checkbox', { name: 'เลือก ปัทมวรรณ สุขเจริญ' }))
    const random = screen.getByRole('radio', { name: 'สุ่มเท่ากัน' })
    expect(random).toBeDisabled()
    expect(random).toHaveAttribute('title', 'เฉพาะผู้จัดการขึ้นไป')
    expect(screen.getByText('สุ่มเท่ากัน · เฉพาะผู้จัดการขึ้นไป')).toBeInTheDocument()
    // the bar's own clear drops the ticks and the bar with them
    await user.click(screen.getByRole('button', { name: 'ล้าง' }))
    expect(screen.queryByText('เลือกแล้ว 1 รายการ')).not.toBeInTheDocument()
  })

  it('disables the split button with its reason below manager', async () => {
    setRole('SUPERVISOR')
    renderScreen(<Today />)
    await screen.findByText('นัดชำระถึงกำหนดวันนี้')
    const split = screen.getByRole('button', { name: 'แบ่งพอร์ต' })
    expect(split).toBeDisabled()
    expect(split).toHaveAttribute('title', 'เฉพาะผู้จัดการขึ้นไป')
  })

  it('deals the ticked rows equally at random for a manager, previewing before the write', async () => {
    setRole('MANAGER')
    api.assignSplit.mockResolvedValue({
      seed: '2026-10-23-abcd1234', total: 2, dry_run: true, assigned: [],
      per_officer: [{ officer_uid: 'rungnapa', count: 1 }, { officer_uid: 'somchai', count: 1 }],
    })
    const user = userEvent.setup()
    renderScreen(<Today />)
    await screen.findByText('นัดชำระถึงกำหนดวันนี้')
    await user.click(screen.getByRole('checkbox', { name: 'เลือก ปัทมวรรณ สุขเจริญ' }))
    await user.click(screen.getByRole('checkbox', { name: 'เลือก สมศรี พงษ์ไพบูลย์' }))
    await user.click(screen.getByRole('radio', { name: 'สุ่มเท่ากัน' }))
    await user.click(screen.getByRole('checkbox', { name: 'รุ่งนภา ทองดี' }))
    await user.click(screen.getByRole('checkbox', { name: 'สมชาย ใจกล้า' }))
    await user.click(screen.getByRole('button', { name: 'ดูตัวอย่างการสุ่ม' }))
    await waitFor(() => expect(api.assignSplit).toHaveBeenCalledTimes(1))
    expect(api.assignSplit.mock.calls[0][0]).toMatchObject({
      customer_uids: ['c-1', 'c-2'], officer_uids: ['rungnapa', 'somchai'], dry_run: true,
    })
    expect(await screen.findByText(/2 รายการ → รุ่งนภา ทองดี 1 · สมชาย ใจกล้า 1/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'มอบหมาย 2 บัญชี' }))
    await waitFor(() => expect(api.assignSplit).toHaveBeenCalledTimes(2))
    expect(api.assignSplit.mock.calls[1][0]).toMatchObject({ dry_run: false })
  })
})

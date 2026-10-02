import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { Record } from './Record.jsx'
import { Reports } from './Reports.jsx'
import { CASE } from '../test-fixtures.js'
import { setRole } from '../lib/identity.jsx'

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
vi.mock('../lib/download.js', () => ({ downloadText: vi.fn(), downloadBlob: vi.fn() }))
const { api } = await import('../lib/api.js')
const { downloadBlob } = await import('../lib/download.js')

const HISTORY = [
  { month: '2026-09', payment_status: 'LATE', status_source: 'PEAK', overdue: '3199.00', outstanding: '210000.00', oldest_dpd: 15, officer: 'nantapol' },
  { month: '2026-08', payment_status: 'CURRENT', status_source: 'SHEET', overdue: '0.00', outstanding: '213199.00', oldest_dpd: 0, officer: 'nantapol' },
]
const MONTHS = {
  current_month: '2026-09',
  months: [
    { month: '2026-09', customers: 5, outstanding: '500.00', overdue: '30.00', npl_in: 1, npl_out: 1,
      mom: { customers: 1, outstanding: '100.00', overdue: '30.00' },
      by_status: { NPL: { count: 2, outstanding: '200.00', overdue: '20.00' }, CURRENT: { count: 2, outstanding: '200.00', overdue: '0.00' }, LATE: { count: 1, outstanding: '100.00', overdue: '10.00' } } },
    { month: '2026-08', customers: 4, outstanding: '400.00', overdue: '0.00', npl_in: null, npl_out: null, mom: null,
      by_status: { NPL: { count: 2, outstanding: '200.00', overdue: '0.00' } } },
  ],
}

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
  setRole('OFFICER')
  api.caseDetail.mockResolvedValue({ ...CASE, case: { ...CASE.case, monthly_history: HISTORY } })
  api.attachments.mockResolvedValue({ attachments: [] })
  api.weeklyReport.mockResolvedValue({ period: { label: 'WK-43/2026' }, management_summary: {}, portfolio: {}, promises: {}, npl_movement: {} })
  api.weeklyEditions.mockResolvedValue({ editions: [] })
  api.ptpReport.mockResolvedValue({ rows: [], totals: { count: 0, promised_amount: '0', by_status: {} }, meta: { from: '2026-09-01', to: '2026-09-30', statuses: [] } })
  api.officers.mockResolvedValue({ officers: [] })
  api.monthlyReport.mockResolvedValue(MONTHS)
  api.monthlyExport.mockResolvedValue({ blob: new Blob(['x']), filename: 'volt-monthly-history-2026-09.xlsx' })
})

describe('monthly history (2026-09-25)', () => {
  it('the case page lists one row per month with the status and where it came from', async () => {
    const user = userEvent.setup()
    renderScreen(<Record />, { route: '/customers/c-1' })
    await user.click(await screen.findByRole('tab', { name: 'ประวัติรายเดือน' }))
    const table = screen.getByRole('table', { name: 'ประวัติรายเดือน' })
    expect(within(table).getAllByRole('row')).toHaveLength(3)
    expect(within(table).getByText('PEAK')).toBeInTheDocument()
    expect(within(table).getByText('ชีต')).toBeInTheDocument()
    expect(within(table).getByText('210,000.00')).toBeInTheDocument()
  })

  it('the report shows months with NPL in/out, and export is a manager act with a reason', async () => {
    const user = userEvent.setup()
    renderScreen(<Reports />)
    const table = await screen.findByRole('table', { name: 'ภาพรวมรายเดือน' })
    expect(within(table).getByText('+1 / −1')).toBeInTheDocument()
    expect(within(table).getByText('(+1)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ส่งออกเดือน (.xlsx)' })).toBeDisabled()

    setRole('MANAGER')
    renderScreen(<Reports />)
    const buttons = await screen.findAllByRole('button', { name: 'ส่งออกเดือน (.xlsx)' })
    const enabled = buttons.find((b) => !b.disabled)
    await user.click(enabled)
    const run = screen.getByRole('button', { name: 'ส่งออก' })
    expect(run).toBeDisabled()                                   // no reason yet
    await user.type(screen.getByRole('textbox'), 'month-end review')
    await user.click(run)
    await waitFor(() => expect(api.monthlyExport).toHaveBeenCalledWith({ month: '2026-09', reason: 'month-end review' }))
    expect(downloadBlob).toHaveBeenCalledWith('volt-monthly-history-2026-09.xlsx', expect.any(Blob))
  })
})

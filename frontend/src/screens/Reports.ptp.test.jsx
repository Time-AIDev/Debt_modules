import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { Reports } from './Reports.jsx'

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
const { downloadText } = await import('../lib/download.js')

const PTP = {
  rows: [
    {
      uid: 'ptp-1', source: 'case', customer_uid: 'c-1', display_name: 'ปัทมวรรณ สุขเจริญ',
      volt_id: 'V-1', officer_uid: 'nantapol', promise_date: '2026-10-28',
      promised_amount: '6985.42', status: 'OPEN', closed_on: null,
      renegotiation_count: 1, lineage_from_uid: 'ptp-0', lineage_from_closed_on: '2026-10-01',
    },
    {
      uid: 'ptp-2', source: 'journey', customer_uid: 'c-2', display_name: 'สมศรี พงษ์ไพบูลย์',
      volt_id: 'V-2', officer_uid: 'thip', promise_date: '2026-10-30',
      promised_amount: '1500.00', status: 'KEPT', closed_on: '2026-10-30',
      renegotiation_count: 0, lineage_from_uid: null, lineage_from_closed_on: null,
    },
  ],
  totals: {
    count: 2, promised_amount: '8485.42',
    by_status: { OPEN: { count: 1, promised_amount: '6985.42' }, KEPT: { count: 1, promised_amount: '1500.00' } },
  },
  meta: { from: '2026-10-01', to: '2026-10-31', statuses: ['OPEN', 'KEPT', 'BROKEN'], note_th: 'x', note_en: 'y' },
}

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
  api.weeklyReport.mockResolvedValue({ period: { label: 'WK-43/2026' }, management_summary: {}, portfolio: {}, promises: {}, npl_movement: {} })
  api.weeklyEditions.mockResolvedValue({ editions: [] })
  api.ptpReport.mockResolvedValue(PTP)
  api.officers.mockResolvedValue({ officers: [{ uid: 'nantapol', display_name_th: 'นันทพล', role: 'OFFICER' }] })
  api.ptpReportExport.mockResolvedValue({ text: 'customer,amount\nก,1\n', filename: 'ptp-report_2026-10-01_2026-10-31.csv' })
})

describe('the PTP report (F16)', () => {
  it('renders the served rows and totals', async () => {
    renderScreen(<Reports />)
    expect(await screen.findByRole('heading', { name: 'นัดชำระ (PTP) ตามช่วงวันที่' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'ปัทมวรรณ สุขเจริญ' })).toHaveAttribute('href', '/customers/c-1')
    expect(screen.getAllByText('6,985.42').length).toBeGreaterThan(0)
    expect(screen.getByText('เลื่อนนัด 1 ครั้ง')).toBeInTheDocument()
    expect(screen.getByText('ต่อจาก ptp-0')).toBeInTheDocument()
    expect(screen.getByText(/รวม 2 นัด · 8,485.42/)).toBeInTheDocument()
    // raw PTP codes are said in words: the totals and the status pill (brief §3.2)
    expect(screen.getByText(/นัดเปิดอยู่ 1 \(6,985.42\)/)).toBeInTheDocument()
    expect(screen.getAllByText('รักษานัดแล้ว').some((el) => el.closest('.pill--done'))).toBe(true)
    expect(screen.getAllByText('นัดเปิดอยู่').some((el) => el.closest('.pill--do'))).toBe(true)
  })

  it('refetches with the chosen dates', async () => {
    renderScreen(<Reports />)
    await screen.findByText('ปัทมวรรณ สุขเจริญ')
    const from = screen.getByLabelText('จาก')
    fireEvent.change(from, { target: { value: '2026-11-01' } })
    await waitFor(() => expect(api.ptpReport.mock.calls.length).toBeGreaterThan(1))
    const last = api.ptpReport.mock.calls[api.ptpReport.mock.calls.length - 1][0]
    expect(last).toMatchObject({ from: '2026-11-01', to: '2026-10-31' })
  })

  it('exports the served rows as CSV', async () => {
    const user = userEvent.setup()
    renderScreen(<Reports />)
    await screen.findByText('ปัทมวรรณ สุขเจริญ')
    await user.click(screen.getByRole('button', { name: 'ส่งออก CSV' }))
    await waitFor(() => expect(api.ptpReportExport).toHaveBeenCalledTimes(1))
    expect(api.ptpReportExport.mock.calls[0][0]).toMatchObject({ from: '2026-10-01', to: '2026-10-31' })
    expect(downloadText).toHaveBeenCalledWith('ptp-report_2026-10-01_2026-10-31.csv', expect.stringContaining('customer,amount'))
  })
})

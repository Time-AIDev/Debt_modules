import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { PeakIntake } from './PeakIntake.jsx'

vi.mock('../lib/api.js', () => ({
  api: {
    peakReportLastRun: vi.fn(), peakReportDoors: vi.fn(), peakLinks: vi.fn(),
    peakReportStart: vi.fn(), peakReportRun: vi.fn(), peakReportRows: vi.fn(),
    peakReportApply: vi.fn(), peakReportRefreshServed: vi.fn(),
    peakLinkConfirm: vi.fn(), peakLinkRetire: vi.fn(),
    peakConflicts: vi.fn(), peakConflictsDecide: vi.fn(), peakDecisionRetire: vi.fn(),
    peakReceiptStart: vi.fn(), peakReceiptRun: vi.fn(), peakReceiptLastRun: vi.fn(),
    peakReceiptRows: vi.fn(), peakReceiptApply: vi.fn(),
    peakReportSchemas: vi.fn(),
    workbook: vi.fn(),
  },
  CHANGED_EVENT: 'volt:changed',
  AUTH_REQUIRED_EVENT: 'volt:auth-required',
}))
const { api } = await import('../lib/api.js')

beforeEach(() => {
  vi.clearAllMocks()
  api.peakReportLastRun.mockResolvedValue({ staged: null, applied: null, watch: null })
  api.peakReportDoors.mockResolvedValue({ doors: [{ door: 'api', state: 'not_configured' }] })
  api.peakLinks.mockResolvedValue({ links: [] })
  api.peakReceiptLastRun.mockResolvedValue({ staged: null, applied: null })
  api.peakConflicts.mockResolvedValue({ rows: [], total: 0, limit: 50, offset: 0, undecided_fields: 0 })
  api.peakReportSchemas.mockResolvedValue({ invoice: null, receipt: null })
})

describe('the two named uploads (D01)', () => {
  it('offers invoice, receipt and the disabled api door, and the receipt posts to its own route', async () => {
    const user = userEvent.setup()
    renderScreen(<PeakIntake />)
    const radios = await screen.findAllByRole('radio')
    expect(radios.map((r) => r.textContent)).toEqual([
      'ใบแจ้งหนี้',
      'ใบเสร็จรับเงิน',
      'PEAK API',
    ])
    expect(radios[2]).toBeDisabled()

    await user.click(radios[1])
    const input = screen.getByLabelText('เลือกไฟล์รายงานใบเสร็จรับเงิน')
    api.peakReceiptStart.mockResolvedValue({ uid: 'rr-1', state: 'running' })
    const file = new File(['x'], 'receipt.xlsx', { type: 'application/octet-stream' })
    await user.upload(input, file)
    await waitFor(() => expect(api.peakReceiptStart).toHaveBeenCalledWith(
      file, expect.objectContaining({ signal: expect.any(AbortSignal), onProgress: expect.any(Function) }),
    ))
    expect(api.peakReportStart).not.toHaveBeenCalled()
  })

  it('counts receipts, not invoices, while a receipt report is read', async () => {
    api.peakReceiptStart.mockResolvedValue({ uid: 'rr-2', state: 'running', read: 398, total: 398, landed: 120 })
    api.peakReceiptRun.mockResolvedValue({ uid: 'rr-2', state: 'running', read: 398, total: 398, landed: 120 })
    const user = userEvent.setup()
    renderScreen(<PeakIntake />)
    await user.click((await screen.findAllByRole('radio'))[1])
    await user.upload(screen.getByLabelText('เลือกไฟล์รายงานใบเสร็จรับเงิน'), new File(['x'], 'r.xlsx'))
    expect(await screen.findByText('อ่านแล้ว 120 / 398 ใบเสร็จ')).toBeInTheDocument()
  })

  it('shows an honest indeterminate state while the workbook is being read', async () => {
    api.peakReceiptStart.mockResolvedValue({
      uid: 'rr-reading', state: 'running', phase: 'reading', read: 0, total: null,
      processed: 0, phase_total: null, landed: 0,
    })
    const user = userEvent.setup()
    renderScreen(<PeakIntake />)
    await user.click((await screen.findAllByRole('radio'))[1])
    await user.upload(screen.getByLabelText('เลือกไฟล์รายงานใบเสร็จรับเงิน'), new File(['x'], 'r.xlsx'))

    const status = await screen.findByRole('status', { name: 'กำลังอ่านไฟล์รายงานใบเสร็จ' })
    expect(status.querySelector('.imp-progress__bar--indeterminate')).toBeInTheDocument()
  })

  it('shows receipt matching progress from the backend phase counters', async () => {
    api.peakReceiptStart.mockResolvedValue({
      uid: 'rr-matching', state: 'running', phase: 'matching', read: 5889, total: 5399,
      processed: 500, phase_total: 5399, landed: 0,
    })
    const user = userEvent.setup()
    renderScreen(<PeakIntake />)
    await user.click((await screen.findAllByRole('radio'))[1])
    await user.upload(screen.getByLabelText('เลือกไฟล์รายงานใบเสร็จรับเงิน'), new File(['x'], 'r.xlsx'))

    expect(await screen.findByRole('status', { name: 'กำลังจับคู่ใบเสร็จ 500 / 5,399' })).toBeInTheDocument()
  })

  it('shows receipt writing progress from the backend phase counters', async () => {
    api.peakReceiptStart.mockResolvedValue({
      uid: 'rr-writing', state: 'running', phase: 'writing', read: 5889, total: 5399,
      processed: 0, phase_total: 5399, landed: 1200,
    })
    const user = userEvent.setup()
    renderScreen(<PeakIntake />)
    await user.click((await screen.findAllByRole('radio'))[1])
    await user.upload(screen.getByLabelText('เลือกไฟล์รายงานใบเสร็จรับเงิน'), new File(['x'], 'r.xlsx'))

    expect(await screen.findByRole('status', { name: 'กำลังบันทึกใบเสร็จ 1,200 / 5,399' })).toBeInTheDocument()
  })

  it('lists the unmatched receipts of a run read back from the server, ready to link', async () => {
    api.peakReceiptLastRun.mockResolvedValue({
      staged: null,
      applied: { id: 41, row_counts: { read: 412, landed: 398, rejected: 0 },
                 meta: { report_as_of: '2026-09-30', matched: 377, unmatched: 12, applied: { by: 'MANAGER' } } },
    })
    api.peakReceiptRows.mockResolvedValue({
      rows: [{ doc_no: 'RT-2026090001', customer_name: 'Somsri', contact_code: 'C0901', verdict: 'UNMATCHED', candidates: [] }],
      total: 1,
    })
    const user = userEvent.setup()
    renderScreen(<PeakIntake />)
    await user.click((await screen.findAllByRole('radio'))[1])
    expect(await screen.findByText('RT-2026090001')).toBeInTheDocument()
    expect(api.peakReceiptRows).toHaveBeenCalledWith(41, { verdict: 'UNMATCHED', limit: 100, offset: 0 })
    await user.click(screen.getByRole('button', { name: /RT-2026090001/ }))
    expect(screen.getByRole('dialog', { name: 'RT-2026090001' })).toBeInTheDocument()
  })

  it('keeps ambiguous receipt matches visible for review', async () => {
    api.peakReceiptLastRun.mockResolvedValue({
      staged: null,
      applied: { id: 42, row_counts: { read: 1, landed: 1, rejected: 0 },
                 meta: { report_as_of: '2026-09-30', matched: 0, candidates: 1, unmatched: 0 } },
    })
    api.peakReceiptRows.mockImplementation((_runId, params) => Promise.resolve(
      params.verdict === 'CANDIDATE'
        ? { rows: [{ doc_no: 'RE-CANDIDATE', customer_name: 'Somchai', contact_code: 'C0902',
                     verdict: 'CANDIDATE', candidates: [{ customer_no: 'CUST-B', rule: 'INVOICE_REF_CUSTOMER', code: 'IV-1' }] }], total: 1 }
        : { rows: [], total: 0 },
    ))
    const user = userEvent.setup()
    api.peakLinkConfirm.mockResolvedValue({})
    renderScreen(<PeakIntake />)
    await user.click((await screen.findAllByRole('radio'))[1])

    expect(await screen.findByText('RE-CANDIDATE')).toBeInTheDocument()
    expect(screen.getByText(/CUST-B/)).toBeInTheDocument()
    expect(screen.getByText(/ลูกค้าจากใบแจ้งหนี้อ้างอิง/)).toBeInTheDocument()
    expect(api.peakReceiptRows).toHaveBeenCalledWith(42, { verdict: 'CANDIDATE', limit: 100, offset: 0 })
    await user.click(screen.getByText('RE-CANDIDATE'))
    const drawer = screen.getByRole('dialog', { name: 'RE-CANDIDATE' })
    await user.click(within(drawer).getByRole('button', { name: /CUST-B/ }))
    await waitFor(() => expect(api.peakLinkConfirm).toHaveBeenCalledWith({
      contact_code: 'C0902', customer_no: 'CUST-B', reason: undefined,
    }))
    await waitFor(() => expect(api.peakReceiptRows.mock.calls.filter(
      ([id, params]) => id === 42 && params.verdict === 'CANDIDATE',
    )).toHaveLength(2))
  })

  it('keeps historical string candidates usable', async () => {
    api.peakReceiptLastRun.mockResolvedValue({
      staged: null,
      applied: { id: 43, row_counts: { read: 1, landed: 1, rejected: 0 },
                 meta: { report_as_of: '2026-09-30', matched: 0, candidates: 1, unmatched: 0 } },
    })
    api.peakReceiptRows.mockImplementation((_runId, params) => Promise.resolve(
      params.verdict === 'CANDIDATE'
        ? { rows: [{ doc_no: 'RE-LEGACY', customer_name: 'Legacy', verdict: 'CANDIDATE', candidates: ['CUST-LEGACY'] }], total: 1 }
        : { rows: [], total: 0 },
    ))
    const user = userEvent.setup()
    renderScreen(<PeakIntake />)
    await user.click((await screen.findAllByRole('radio'))[1])

    expect(await screen.findByText('RE-LEGACY')).toBeInTheDocument()
    expect(screen.getByText(/CUST-LEGACY/)).toBeInTheDocument()
  })

  it('asks the same confirmation as the invoice report before a receipt report moves payment status', async () => {
    api.peakReceiptLastRun.mockResolvedValue({
      staged: { id: 41, row_counts: { read: 412, landed: 398, rejected: 0 },
                meta: { report_as_of: '2026-09-30', matched: 377, unmatched: 12 } },
      applied: null,
    })
    api.peakReceiptRows.mockResolvedValue({ rows: [], total: 0 })
    api.peakReceiptApply.mockResolvedValue({
      run: { id: 41, meta: { report_as_of: '2026-09-30', applied: { by: 'MANAGER' } } },
      served: true,
      reconciliation: {
        claims_confirmed: 8, claims_partially_confirmed: 2, claims_needs_review: 1,
        allocated_to_invoices: '12500.00', customer_credit: '500.00',
      },
    })
    const user = userEvent.setup()
    renderScreen(<PeakIntake />)
    await user.click((await screen.findAllByRole('radio'))[1])
    await user.click(await screen.findByRole('button', { name: 'ใช้รายงานนี้กับระบบ' }))
    const dialog = screen.getByRole('dialog', { name: 'ใช้รายงาน ณ 30/09/2026 กับระบบ' })
    expect(within(dialog).getByText('ใบเสร็จที่อ่าน 398 ใบ · ใบแจ้งหนี้ที่ชำระแล้ว 377 ใบ')).toBeInTheDocument()
    expect(api.peakReceiptApply).not.toHaveBeenCalled()
    await user.click(within(dialog).getByRole('button', { name: 'ยืนยันใช้รายงาน' }))
    await waitFor(() => expect(api.peakReceiptApply).toHaveBeenCalledWith(41, {}))
    expect(await screen.findByText('ใช้รายงานใบเสร็จนี้แล้ว — สถานะการชำระรายงวดอัปเดตแล้ว')).toBeInTheDocument()
    expect(screen.getByText('ยืนยันรายการรอ 8 · ยืนยันบางส่วน 2 · ต้องตรวจสอบ 1')).toBeInTheDocument()
    expect(screen.getByText('จัดสรรเข้าใบแจ้งหนี้ 12,500.00 · เครดิตลูกค้า 500.00')).toBeInTheDocument()
  })

  it('says when the last receipt run failed, the way the invoice report does (fix-all P6)', async () => {
    api.peakReceiptLastRun.mockResolvedValue({
      staged: null, applied: null,
      failed: { id: 12, note: 'pipeline_failed: The PEAK report run failed (RuntimeError)', meta: { filename: 'receipts.xlsx' } },
    })
    const user = userEvent.setup()
    renderScreen(<PeakIntake />)
    await user.click((await screen.findAllByRole('radio'))[1])
    expect(await screen.findByText(/receipts\.xlsx · การประมวลผลรายงาน PEAK ล้มเหลว/)).toBeInTheDocument()
  })
})

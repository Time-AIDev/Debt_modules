import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { setRole } from '../lib/identity.jsx'
import { PeakIntake } from './PeakIntake.jsx'

vi.mock('../lib/api.js', () => ({
  api: {
    peakReportLastRun: vi.fn(), peakReportDoors: vi.fn(), peakLinks: vi.fn(),
    peakReportStart: vi.fn(), peakReportRun: vi.fn(), peakReportRows: vi.fn(),
    peakReportApply: vi.fn(), peakReportRefreshServed: vi.fn(),
    peakLinkConfirm: vi.fn(), peakLinkRetire: vi.fn(),
    // feedback round 2 (TASK-213/214, additions): the two named uploads and the
    // conflicts tab's own reads.
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

const APPLIED = {
  id: 9,
  row_counts: { read: 7999, landed: 7639, rejected: 0 },
  meta: {
    report_as_of: '2026-09-14', covers_from: '2024-01-01', covers_to: '2026-09-14',
    matched: 7000, candidates: 300, unmatched: 339,
    applied: { by: 'settasak', at: '2026-09-14T10:00:00Z' },
  },
}

const DONE = {
  uid: 'run-1', state: 'done', run_id: 9, invoices: 7639, matched: 7000,
  candidates: 300, unmatched: 339, rejected: 0, report_as_of: '2026-09-14',
}

const CAND_ROW = {
  doc_no: 'IVT-20260700089', doc_kind: 'IVT', status: 'AWAITING',
  due_on: '2026-08-07', amount_awaiting: '8399.00',
  contact_code: '99999000328', reference: '99999000328',
  customer_name: 'Wiwat Sintuboon', cycle_n: 14, cycle_of: 48,
  verdict: 'CANDIDATE', rule: null, customer_no: null, linked_no: null,
  candidates: [{ customer_no: '28005096535', rule: 'CUSTOMER_NO', code: '99999000328' }],
}

beforeEach(() => {
  vi.clearAllMocks()
  setRole('OFFICER')
  api.peakConflicts.mockResolvedValue({ rows: [], total: 0, limit: 50, offset: 0, undecided_fields: 0 })
  api.peakReceiptLastRun.mockResolvedValue({ staged: null, applied: null })
  window.localStorage.clear()
  api.peakReportLastRun.mockResolvedValue({ staged: null, applied: null, watch: null })
  api.peakReportDoors.mockResolvedValue({ doors: [{ door: 'api', state: 'not_configured' }] })
  api.peakLinks.mockResolvedValue({ links: [] })
  api.peakReportRows.mockResolvedValue({ rows: [], total: 0 })
  api.peakReportSchemas.mockResolvedValue({
    invoice: {
      report_type: 'invoice',
      required: [
        { field: 'doc_no', heading: 'เลขที่เอกสาร', aliases: [] },
        { field: 'amount_awaiting', heading: 'มูลค่ารอรับชำระ', aliases: [] },
      ],
      optional: [{ field: 'tax_id', heading: 'เลขประจำตัวผู้เสียภาษี', aliases: [] }],
      contextual_bindings: { doc_no: { strategy: 'first' } },
    },
    receipt: {
      report_type: 'receipt',
      required: [{ field: 'paid_amount', heading: 'จำนวนเงิน', aliases: [] }],
      optional: [], contextual_bindings: { paid_amount: { strategy: 'after', after: 'วันที่' } },
    },
  })
})

describe('PeakIntake', () => {
  it('shows the backend-owned column checklist before upload and safe diagnostics after a refusal', async () => {
    api.peakReportStart.mockRejectedValue({
      problem: {
        code: 'missing_required_columns',
        extensions: { schema: {
          missing_required_fields: ['amount_awaiting'],
          missing_optional_fields: ['tax_id'],
          ignored_headings: ['หัก ณ ที่จ่าย'],
          duplicate_headings: { 'จำนวนเงิน': [8, 12] },
        } },
      },
    })
    const user = userEvent.setup()
    renderScreen(<PeakIntake />)
    expect(await screen.findByText('คอลัมน์ที่ต้องมี')).toBeInTheDocument()
    expect(screen.getByText('เลขที่เอกสาร')).toBeInTheDocument()
    expect(screen.getByText('มูลค่ารอรับชำระ')).toBeInTheDocument()
    await user.upload(screen.getByLabelText('เลือกไฟล์รายงาน PEAK'),
      new File(['x'], 'bad.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }))
    expect(await screen.findByText(/คอลัมน์ที่ขาด: มูลค่ารอรับชำระ/)).toBeInTheDocument()
    expect(screen.getByText(/คอลัมน์เพิ่มเติมที่ไม่ใช้: หัก ณ ที่จ่าย/)).toBeInTheDocument()
    expect(screen.getByText(/แก้ชื่อคอลัมน์ให้ตรง/)).toBeInTheDocument()
  })

  it('says when no report has ever been used, and names the API door state', async () => {
    renderScreen(<PeakIntake />)
    expect(await screen.findByText('ยังไม่เคยใช้รายงาน PEAK')).toBeInTheDocument()
    expect(await screen.findByText(/PEAK API/)).toBeInTheDocument()
  })

  it('shows the report in use with its served counts', async () => {
    api.peakReportLastRun.mockResolvedValue({ staged: null, applied: APPLIED, watch: null })
    renderScreen(<PeakIntake />)
    // design D: the report line says which report is in use; figures carry separators
    expect(await screen.findByText(/รายงานที่ใช้อยู่ ณ 14\/09\/2026 · ครอบคลุม 01\/01\/2024 – 14\/09\/2026/)).toBeInTheDocument()
    expect(screen.getByText('7,000')).toBeInTheDocument()
    expect(screen.getByText('339')).toBeInTheDocument()
  })

  it('uploads a report, lists the uncertain row with its rule, and applies it', async () => {
    api.peakReportStart.mockResolvedValue(DONE)
    api.peakReportRows.mockImplementation(async (id, params) => ({
      rows: params.verdict === 'CANDIDATE' ? [CAND_ROW] : [],
      total: params.verdict === 'CANDIDATE' ? 1 : 0,
    }))
    api.peakReportApply.mockResolvedValue({ run: APPLIED, served: true, moved_cases: 12 })

    const user = userEvent.setup()
    renderScreen(<PeakIntake />)
    await screen.findByText('ยังไม่เคยใช้รายงาน PEAK')
    await user.upload(screen.getByLabelText('เลือกไฟล์รายงาน PEAK'),
                      new File(['x'], 'invoice_export.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }))

    expect(await screen.findByText('IVT-20260700089')).toBeInTheDocument()
    // design D: the row itself opens the side sheet; the rule reads as words
    await user.click(screen.getByRole('button', { name: /IVT-20260700089/ }))
    expect(screen.getByText('ยืนยัน 28005096535 · ตรงเลขลูกค้า')).toBeInTheDocument()
    await user.keyboard('{Escape}')

    await user.click(screen.getByRole('button', { name: 'ใช้รายงานนี้กับระบบ' }))
    await user.click(screen.getByRole('button', { name: 'ยืนยันใช้รายงาน' }))
    await waitFor(() => expect(api.peakReportApply).toHaveBeenCalledWith(9, {}))
    expect(await screen.findByText('ปรับสถานะการชำระ 12 เคส')).toBeInTheDocument()
  })

  it('resumes a staged run read back from the server and applies it by its own id', async () => {
    api.peakReportLastRun.mockResolvedValue({
      staged: { id: 29, row_counts: { read: 7999, landed: 7639, rejected: 0 },
                meta: { report_as_of: '2026-09-14', matched: 7000, candidates: 300, unmatched: 339 } },
      applied: null, watch: null,
    })
    api.peakReportRows.mockImplementation(async (id, params) => ({
      rows: params.verdict === 'CANDIDATE' ? [CAND_ROW] : [],
      total: params.verdict === 'CANDIDATE' ? 1 : 0,
    }))
    api.peakReportApply.mockResolvedValue({ run: { id: 29 }, served: true, moved_cases: 0 })

    const user = userEvent.setup()
    renderScreen(<PeakIntake />)
    expect(await screen.findByText('IVT-20260700089')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'ใช้รายงานนี้กับระบบ' }))
    await user.click(screen.getByRole('button', { name: 'ยืนยันใช้รายงาน' }))
    await waitFor(() => expect(api.peakReportApply).toHaveBeenCalledWith(29, {}))
  })

  it('offers a repair when the apply committed but the served reload failed', async () => {
    api.peakReportStart.mockResolvedValue(DONE)
    api.peakReportApply.mockResolvedValue({
      run: { id: 9 }, served: false, moved_cases: 0,
      note_th: 'บันทึกแล้ว แต่ระบบยังโหลดข้อมูลชุดใหม่ไม่สำเร็จ',
    })
    api.peakReportRefreshServed.mockResolvedValue({ run: APPLIED, served: true })

    const user = userEvent.setup()
    renderScreen(<PeakIntake />)
    await screen.findByText('ยังไม่เคยใช้รายงาน PEAK')
    await user.upload(screen.getByLabelText('เลือกไฟล์รายงาน PEAK'),
                      new File(['x'], 'invoice_export.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }))
    await user.click(await screen.findByRole('button', { name: 'ใช้รายงานนี้กับระบบ' }))
    await user.click(screen.getByRole('button', { name: 'ยืนยันใช้รายงาน' }))

    expect(await screen.findByText('บันทึกแล้ว แต่ระบบยังโหลดข้อมูลชุดใหม่ไม่สำเร็จ')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'ซ่อมการให้บริการ' }))
    await waitFor(() => expect(api.peakReportRefreshServed).toHaveBeenCalledWith(9))
  })

  it('says when the last import run failed instead of leaving the old receipt looking current', async () => {
    api.peakReportLastRun.mockResolvedValue({
      staged: null, applied: APPLIED, watch: null,
      // fix-all P6: the served note is "<code>: <detail>"; the code reads as words
      failed: { id: 8, note: 'peak_run_in_progress: another PEAK report run is in progress', meta: { filename: 'bad.xlsx' } },
    })
    renderScreen(<PeakIntake />)
    expect(await screen.findByText(/รอบนำเข้าล่าสุดล้มเหลว/)).toBeInTheDocument()
    expect(screen.getByText(/bad\.xlsx · มีรายงาน PEAK กำลังนำเข้าอยู่/)).toBeInTheDocument()
  })

  it('confirms a candidate with the report row’s own contact code', async () => {
    api.peakReportStart.mockResolvedValue(DONE)
    api.peakReportRows.mockImplementation(async (id, params) => ({
      rows: params.verdict === 'CANDIDATE' ? [CAND_ROW] : [],
      total: params.verdict === 'CANDIDATE' ? 1 : 0,
    }))
    api.peakLinkConfirm.mockResolvedValue({ link: { uid: 1 } })

    const user = userEvent.setup()
    renderScreen(<PeakIntake />)
    await screen.findByText('ยังไม่เคยใช้รายงาน PEAK')
    await user.upload(screen.getByLabelText('เลือกไฟล์รายงาน PEAK'),
                      new File(['x'], 'invoice_export.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }))
    await user.click(await screen.findByRole('button', { name: /IVT-20260700089/ }))
    await user.click(await screen.findByRole('button', { name: 'ยืนยัน 28005096535 · ตรงเลขลูกค้า' }))

    await waitFor(() => expect(api.peakLinkConfirm).toHaveBeenCalledWith({
      contact_code: '99999000328', customer_no: '28005096535', reason: undefined,
    }))
    expect(await screen.findByText('ผูกแล้ว — รายการนี้จะถูกนำไปใช้')).toBeInTheDocument()
    // the sheet closes on a link
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('links an invoice to a searched customer with a reason from the side sheet, and keeps a refusal there', async () => {
    api.peakReportStart.mockResolvedValue(DONE)
    api.peakReportRows.mockImplementation(async (id, params) => ({
      rows: params.verdict === 'CANDIDATE' ? [CAND_ROW] : [],
      total: params.verdict === 'CANDIDATE' ? 1 : 0,
    }))
    api.workbook.mockResolvedValue({ rows: [{ customer: { uid: 'u1', customer_no: '28000000001', display_name: 'Somchai' } }] })
    api.peakLinkConfirm.mockRejectedValueOnce({ problem: { code: 'forbidden', message_th: 'บทบาทนี้ไม่มีสิทธิ์นำเข้ารายงาน PEAK' } })

    const user = userEvent.setup()
    renderScreen(<PeakIntake />)
    await screen.findByText('ยังไม่เคยใช้รายงาน PEAK')
    await user.upload(screen.getByLabelText('เลือกไฟล์รายงาน PEAK'),
                      new File(['x'], 'invoice_export.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }))
    await user.click(await screen.findByRole('button', { name: /IVT-20260700089/ }))
    const link = screen.getByRole('button', { name: 'ผูกกับลูกค้ารายนี้' })
    expect(link).toBeDisabled()
    await user.type(screen.getByLabelText('ค้นหาลูกค้า'), 'So')
    await user.click(await screen.findByRole('button', { name: 'Somchai · 28000000001' }))
    await user.type(screen.getByLabelText('เหตุผล (ถ้ามี)'), 'same phone')
    await user.click(link)
    await waitFor(() => expect(api.peakLinkConfirm).toHaveBeenCalledWith({
      contact_code: '99999000328', customer_no: '28000000001', reason: 'same phone',
    }))
    expect(await screen.findByText('บทบาทนี้ไม่มีสิทธิ์นำเข้ารายงาน PEAK')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('keeps "use an older report" a Manager’s: disabled with its reason for an officer, sent when a manager ticks it', async () => {
    api.peakReportStart.mockResolvedValue(DONE)
    api.peakReportApply.mockResolvedValue({ run: APPLIED, served: true, moved_cases: 1 })
    const user = userEvent.setup()
    renderScreen(<PeakIntake />)
    await screen.findByText('ยังไม่เคยใช้รายงาน PEAK')
    await user.upload(screen.getByLabelText('เลือกไฟล์รายงาน PEAK'),
                      new File(['x'], 'invoice_export.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }))
    await user.click(await screen.findByRole('button', { name: 'ใช้รายงานนี้กับระบบ' }))
    expect(screen.getByRole('checkbox', { name: /ใช้รายงานเก่ากว่า/ })).toBeDisabled()
    expect(screen.getByText('เฉพาะผู้จัดการขึ้นไป')).toBeInTheDocument()

    act(() => setRole('MANAGER'))
    await user.click(screen.getByRole('checkbox', { name: /ใช้รายงานเก่ากว่า/ }))
    await user.click(screen.getByRole('button', { name: 'ยืนยันใช้รายงาน' }))
    await waitFor(() => expect(api.peakReportApply).toHaveBeenCalledWith(9, { allow_older: true }))
  })

  it('renders the server’s refusal verbatim when the report is older than the one in use', async () => {
    api.peakReportStart.mockResolvedValue(DONE)
    api.peakReportApply.mockRejectedValue({
      problem: {
        code: 'report_older_than_applied', title: 'This report is older than the report in use',
        message_th: 'รายงานนี้เก่ากว่ารายงานที่ใช้อยู่',
      },
    })

    const user = userEvent.setup()
    renderScreen(<PeakIntake />)
    await screen.findByText('ยังไม่เคยใช้รายงาน PEAK')
    await user.upload(screen.getByLabelText('เลือกไฟล์รายงาน PEAK'),
                      new File(['x'], 'invoice_export.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }))
    await user.click(await screen.findByRole('button', { name: 'ใช้รายงานนี้กับระบบ' }))
    await user.click(screen.getByRole('button', { name: 'ยืนยันใช้รายงาน' }))

    expect(await screen.findByText('รายงานนี้เก่ากว่ารายงานที่ใช้อยู่')).toBeInTheDocument()
  })
})

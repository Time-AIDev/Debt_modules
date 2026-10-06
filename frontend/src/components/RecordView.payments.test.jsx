import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { FinancialEvidence, InvoicePaymentEvidence, RecordView } from './RecordView.jsx'
import { CASE } from '../test-fixtures.js'

vi.mock('../lib/api.js', () => ({
  api: new Proxy({}, { get: (target, prop) => (target[prop] ||= vi.fn(async () => ({}))) }),
  CHANGED_EVENT: 'volt:changed', AUTH_REQUIRED_EVENT: 'volt:auth-required',
}))

beforeEach(() => { window.localStorage.clear(); vi.clearAllMocks() })

const evidence = {
  read_only: true,
  reconciliation: { sequence: 7, created_at: '2026-10-07T09:15:00+07:00', snapshot_as_of: '2026-09-14' },
  sources: [
    { id: 1, source_system: 'PEAK', report_as_of: '2026-09-14', exported_at: '2026-09-14T15:53:30', covers_from: '2024-01-01', covers_to: '2026-09-14' },
    { id: 2, source_system: 'PEAK_RECEIPT', report_as_of: '2026-09-30', exported_at: '2026-09-30T16:50:15', covers_from: '2026-01-01', covers_to: '2026-12-31' },
  ],
  receipts: [{ doc_no: 'RE-SPLIT', invoice_ref: 'IV-1', status: 'PAID', components: [
    { uid: 'RE-SPLIT:0', paid_on: '2026-09-10', amount: '40.00', channel: 'Bank A', allocations: [{ invoice_doc_no: 'IV-1', amount: '40.00' }] },
    { uid: 'RE-SPLIT:1', paid_on: '2026-09-20', amount: '60.00', channel: 'Bank B', allocations: [{ invoice_doc_no: 'IV-1', amount: '60.00' }] },
  ], payment_groups: [
    { uid: 'group-one', paid_on: '2026-09-10', net_received: '40.00', allocations: [{ invoice_doc_no: 'IV-1', amount: '40.00' }] },
    { uid: 'group-two', paid_on: '2026-09-20', net_received: '60.00', allocations: [{ invoice_doc_no: 'IV-1', amount: '60.00' }] },
  ] }],
  limitations: [{ code: 'RECEIPT_HISTORY_BEFORE_COVERAGE_UNAVAILABLE', before: '2026-01-01' }],
}

describe('complete payment evidence in the case', () => {
  it('keeps every legacy receipt for one invoice instead of selecting the last', () => {
    renderScreen(<InvoicePaymentEvidence invoice={{ uid: 'IV-1' }} receipts={[
      { uid: 'one', invoice_uid: 'IV-1', ref: 'RE-1', received_on: '2026-09-10', amount: '40.00', channel: 'Bank A' },
      { uid: 'two', invoice_uid: 'IV-1', ref: 'RE-1', received_on: '2026-09-20', amount: '60.00', channel: 'Bank B' },
      { uid: 'other', invoice_uid: 'OTHER', ref: 'OTHER-RECEIPT', amount: '999.00' },
    ]} />)
    const list = screen.getByRole('list', { name: 'รายการรับเงินของใบแจ้งหนี้' })
    expect(within(list).getAllByText('RE-1')).toHaveLength(2)
    expect(within(list).getByText('10/09/2026 · รับเข้า 40.00')).toBeInTheDocument()
    expect(within(list).getByText('20/09/2026 · รับเข้า 60.00')).toBeInTheDocument()
    expect(within(list).queryByText('OTHER-RECEIPT')).not.toBeInTheDocument()
  })

  it('preserves identical components and displays cancellation without a paid allocation', () => {
    renderScreen(<InvoicePaymentEvidence invoice={{ payment_components: [
      { uid: 'a', receipt_doc_no: 'RE-SAME', paid_on: '2026-09-10', amount: '40.00', channel: 'Bank A', allocated_amount: '40.00', status: 'PAID' },
      { uid: 'b', receipt_doc_no: 'RE-SAME', paid_on: '2026-09-10', amount: '40.00', channel: 'Bank A', allocated_amount: '40.00', status: 'PAID' },
      { uid: 'cancelled', receipt_doc_no: 'RE-VOID', paid_on: '2026-09-09', amount: '20.00', channel: 'Bank B', status: 'CANCELLED' },
    ] }} />)
    expect(screen.getAllByText('RE-SAME')).toHaveLength(2)
    expect(screen.getAllByText('10/09/2026 · รับเข้า 40.00')).toHaveLength(2)
    const cancelled = screen.getByText('RE-VOID').closest('li')
    expect(within(cancelled).getByText('ยกเลิกแล้ว — ไม่ใช้ตัดยอด')).toBeInTheDocument()
    expect(within(cancelled).queryByText(/จัดสรรเข้าบิลนี้/)).not.toBeInTheDocument()
  })

  it('retains actual export dates separately from a future receipt coverage end', () => {
    renderScreen(<FinancialEvidence evidence={evidence} />)
    const sources = screen.getByRole('table', { name: 'วันที่รายงานต้นทาง' })
    const receiptRow = within(sources).getByText('ใบเสร็จ PEAK').closest('tr')
    expect(within(receiptRow).getByText('30/09/2026')).toBeInTheDocument()
    expect(within(receiptRow).getByText('30/09/2026 16:50')).toBeInTheDocument()
    expect(within(receiptRow).getByText('01/01/2026 – 31/12/2026')).toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent('ไม่มีรายละเอียดใบเสร็จก่อน 01/01/2026')
    expect(screen.getByRole('note')).toHaveTextContent('ไม่ได้หมายความว่ายังไม่ชำระ')
    expect(screen.getByText(/ไม่ถูกบวกหรือหักซ้ำจากยอดเดิม/)).toBeInTheDocument()
  })

  it('shows all dated components of one receipt and the destination of each allocation', () => {
    renderScreen(<FinancialEvidence evidence={evidence} />)
    const receipts = screen.getByRole('list', { name: 'รายการส่วนรับชำระของใบเสร็จ' })
    expect(within(receipts).getByText('10/09/2026 · รับเข้า 40.00')).toBeInTheDocument()
    expect(within(receipts).getByText('20/09/2026 · รับเข้า 60.00')).toBeInTheDocument()
    expect(within(receipts).getByText('IV-1: 40.00')).toBeInTheDocument()
    expect(within(receipts).getByText('IV-1: 60.00')).toBeInTheDocument()
  })

  it('shows signed adjustments as source adjustments and the dated net allocation separately', () => {
    renderScreen(<FinancialEvidence evidence={{ ...evidence, receipts: [{
      doc_no: 'RE-ADJUSTED', status: 'PAID', components: [
        { uid: 'positive', paid_on: '2026-09-10', amount: '500.00', channel: 'Bank A' },
        { uid: 'adjustment', paid_on: '2026-09-10', amount: '-50.00', channel: 'Adjustment', is_adjustment: true },
      ], payment_groups: [{ uid: 'net', paid_on: '2026-09-10', net_received: '450.00',
        allocations: [{ invoice_doc_no: 'IV-1', amount: '450.00' }] }],
    }] }} />)
    expect(screen.getByText('10/09/2026 · ปรับยอดรับ -50.00')).toBeInTheDocument()
    expect(screen.getByText('10/09/2026 · รับสุทธิ 450.00')).toBeInTheDocument()
    expect(screen.getByText('IV-1: 450.00')).toBeInTheDocument()
    expect(screen.queryByText('ยกเลิกแล้ว — ไม่ใช้ตัดยอด')).not.toBeInTheDocument()
  })

  it('shows canonical evidence in the invoice tab without adding receipt money to served balances', async () => {
    const user = userEvent.setup()
    renderScreen(<RecordView data={{ ...CASE, case: { ...CASE.case, financial_evidence: evidence }, invoices: [{
      uid: 'IV-1', kind: 'INSTALMENT', amount: '100.00', confirmed_paid: '100.00', confirmed_outstanding: '0.00',
      pending_amount: '0.00', projected_outstanding: '0.00', due_date: '2026-09-10', state: 'PAID', peak_number: 'IV-1',
      payment_components: [
        { uid: 'one', receipt_doc_no: 'RE-SPLIT', paid_on: '2026-09-10', amount: '40.00', channel: 'Bank A', allocated_amount: '40.00', status: 'PAID', included_in_snapshot: true },
        { uid: 'two', receipt_doc_no: 'RE-SPLIT', paid_on: '2026-09-20', amount: '60.00', channel: 'Bank B', allocated_amount: '60.00', status: 'PAID' },
      ],
    }] }} onChanged={() => {}} onLogContact={() => {}} />)
    await user.click(await screen.findByRole('tab', { name: 'ใบแจ้งหนี้และเงินเข้า' }))
    const invoices = screen.getByRole('table', { name: 'ใบแจ้งหนี้และเงินเข้า' })
    expect(within(invoices).getAllByText('RE-SPLIT')).toHaveLength(2)
    expect(within(invoices).getByText('เงินส่วนนี้รวมอยู่ในยอดตามวันที่ใบแจ้งหนี้แล้ว')).toBeInTheDocument()
    const row = within(invoices).getByText('IV-1').closest('tr')
    expect(within(row).getAllByText('100.00')).toHaveLength(2) // face and served confirmed-paid only
  })
})

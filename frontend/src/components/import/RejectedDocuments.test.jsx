import { beforeEach, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../../test-utils.jsx'
import { RejectedDocuments } from './RejectedDocuments.jsx'
vi.mock('../../lib/api.js', () => ({ api: { peakReceiptRejectedDocuments: vi.fn() } }))
const { api } = await import('../../lib/api.js')
const document = (doc_no) => ({ doc_no, can_apply: false, codes: ['receipt_document_conflict'], rows: [
  { row: 12, observation: { status_th: 'ชำระแล้ว', contact_code: 'C001', invoice_ref: 'IV001', paid_amount: '100.00', paid_on: '2026-09-30' } },
  { row: 13, observation: { status_th: 'ยกเลิก', contact_code: 'C001', invoice_ref: 'IV001' } },
] })
beforeEach(() => vi.clearAllMocks())
it('discloses conflicting source rows without an apply control and pages documents', async () => {
  api.peakReceiptRejectedDocuments.mockResolvedValueOnce({ rows: [document('RT001')], total: 2, source_rows: 4 })
    .mockResolvedValueOnce({ rows: [document('RT002')], total: 2, source_rows: 4 })
  const user = userEvent.setup()
  renderScreen(<RejectedDocuments runId={42} />)
  await user.click(await screen.findByText(/RT001/))
  expect(screen.getByText('ชำระแล้ว')).toBeInTheDocument()
  expect(screen.getByText('ยกเลิก')).toBeInTheDocument()
  expect(screen.getByText('100.00')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /ยืนยัน|นำไปใช้/ })).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'โหลดเอกสารเพิ่ม' }))
  await screen.findByText(/RT002/)
  expect(api.peakReceiptRejectedDocuments).toHaveBeenLastCalledWith(42, { limit: 50, offset: 1 })
  expect(screen.queryByRole('button', { name: 'โหลดเอกสารเพิ่ม' })).not.toBeInTheDocument()
})
it('shows and retries a read failure instead of claiming an empty quarantine', async () => {
  api.peakReceiptRejectedDocuments.mockRejectedValueOnce({ problem: { code: 'request_failed', message_th: 'อ่านไม่ได้' } })
    .mockResolvedValueOnce({ rows: [document('RT003')], total: 1, source_rows: 2 })
  const user = userEvent.setup()
  renderScreen(<RejectedDocuments runId={43} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('อ่านไม่ได้')
  await user.click(screen.getByRole('button', { name: /ลองใหม่/ }))
  await waitFor(() => expect(screen.getByText(/RT003/)).toBeInTheDocument())
})

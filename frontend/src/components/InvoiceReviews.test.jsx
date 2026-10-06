import { beforeEach, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { setRole } from '../lib/identity.jsx'

vi.mock('../lib/api.js', () => ({ api: {
  previewInvoiceReviews: vi.fn(), confirmInvoiceReviews: vi.fn(),
} }))
const { api } = await import('../lib/api.js')
const rows = Array.from({ length: 26 }, (_, n) => ({ uid: `i${n}`, peak_number: `IV-${n}`,
  is_due: true, contract_cycle: n + 1, review_status: 'AUTO_MATCHED', amount: '100.00', outstanding: '100.00' }))
const data = { customer: { uid: 'c1' }, invoices: rows }
beforeEach(() => { vi.clearAllMocks(); setRole('MANAGER') })

it('previews all eligible customer invoices and requires final acknowledgement for bulk reject', async () => {
  const { InvoiceReviews } = await import('./InvoiceReviews.jsx')
  const user = userEvent.setup()
  api.previewInvoiceReviews.mockResolvedValue({ version: 'v1', items: rows, invoice_count: 26,
    amount: '2600.00', before: { due_outstanding_amount: '2600.00' }, after: { due_outstanding_amount: '0.00' } })
  api.confirmInvoiceReviews.mockResolvedValue({ uid: 'review' })
  const changed = vi.fn()
  renderScreen(<InvoiceReviews data={data} onChanged={changed} />)
  await user.click(screen.getByRole('button', { name: 'ปฏิเสธหลายใบ' }))
  const modal = screen.getByRole('dialog')
  expect(within(modal).getByText(/IV-25/)).toBeInTheDocument()
  expect(within(modal).getByRole('button', { name: 'ดูผลกระทบ' })).toBeDisabled()
  await user.type(screen.getByLabelText('เหตุผลที่ปฏิเสธ'), 'ข้อมูลไม่ถูกต้อง')
  await user.click(screen.getByRole('button', { name: 'ดูผลกระทบ' }))
  await waitFor(() => expect(api.previewInvoiceReviews).toHaveBeenCalledWith('c1', expect.objectContaining({ invoice_uids: rows.map(r => r.uid), action: 'REJECT' })))
  expect(await screen.findByRole('button', { name: 'ยืนยันรายการ' })).toBeDisabled()
  await user.click(screen.getByRole('checkbox', { name: /ตรวจสอบรายการและผลต่อยอด/ }))
  await user.click(screen.getByRole('button', { name: 'ยืนยันรายการ' }))
  await waitFor(() => expect(api.confirmInvoiceReviews).toHaveBeenCalledWith('c1', expect.objectContaining({ preview_version: 'v1', reason: 'ข้อมูลไม่ถูกต้อง' })))
  expect(changed).toHaveBeenCalledOnce()
})

it('requires a fresh preview after a stale commit', async () => {
  const { InvoiceReviews } = await import('./InvoiceReviews.jsx')
  const user = userEvent.setup()
  api.previewInvoiceReviews.mockResolvedValue({ version: 'v1', items: rows, before: {}, after: {} })
  api.confirmInvoiceReviews.mockRejectedValue({ problem: { status: 409, message_th: 'ข้อมูลเปลี่ยนแล้ว' } })
  const refresh = vi.fn()
  renderScreen(<InvoiceReviews data={data} onChanged={refresh} />)
  await user.click(screen.getByRole('button', { name: 'รับรองหลายใบ' }))
  await user.click(screen.getByRole('button', { name: 'ดูผลกระทบ' }))
  await screen.findByRole('checkbox')
  await user.click(screen.getByRole('checkbox'))
  await user.click(screen.getByRole('button', { name: 'ยืนยันรายการ' }))
  expect(await screen.findByRole('button', { name: 'ดูผลกระทบ' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'ยืนยันรายการ' })).not.toBeInTheDocument()
  expect(refresh).toHaveBeenCalledOnce()
})

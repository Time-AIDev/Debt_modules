import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { setRole } from '../lib/identity.jsx'
import { Record } from './Record.jsx'
import { CASE } from '../test-fixtures.js'

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
  api.caseDetail.mockResolvedValue({
    ...CASE,
    payment_claims: [],
    payment_claim_position: {
      confirmed_outstanding: '8399.00', pending_amount: '0.00',
      projected_outstanding: '8399.00', credit_balance: '0.00',
    },
  })
  api.attachments.mockResolvedValue({ attachments: [] })
  api.uploadAttachment.mockResolvedValue({ attachment: { uid: 'att-1', filename: 'invoice-oct.pdf' } })
  api.previewPaymentClaim.mockResolvedValue({
    version: 'balance-v1', amount: '5000.00', confirmed_outstanding: '8399.00',
    projected_outstanding: '3399.00', credit: '0.00',
    allocations: [{ invoice_doc_no: 'IV-1', before: '8399.00', amount: '5000.00', after: '3399.00' }],
  })
  api.createPaymentClaim.mockResolvedValue({ claim: { uid: 'pcl-1', state: 'PENDING' } })
})

describe('the amount-led payment claim on the customer case', () => {
  it('lets an officer upload evidence, preview allocation, then save Pending', async () => {
    const user = userEvent.setup()
    renderScreen(<Record />, { route: '/customers/c-1' })

    await user.click(await screen.findByRole('tab', { name: 'ใบแจ้งหนี้และเงินเข้า' }))
    expect(await screen.findByTestId('manual-invoice')).toBeInTheDocument()

    const file = new File(['%PDF-1.4'], 'invoice-oct.pdf', { type: 'application/pdf' })
    await user.upload(screen.getByLabelText('เลือกไฟล์ใบแจ้งหนี้ / หลักฐาน'), file)
    await waitFor(() => expect(api.uploadAttachment).toHaveBeenCalledWith(
      file, 'case:c-1', expect.objectContaining({ signal: expect.any(AbortSignal), onProgress: expect.any(Function) }),
    ))

    await user.type(screen.getByLabelText('ยอดที่ลูกค้าชำระ'), '5000')
    await user.type(screen.getByLabelText('วันที่รับเงิน'), '2026-10-23')
    await user.type(screen.getByLabelText('หมายเหตุ'), 'ลูกค้าส่งสลิปแล้ว')
    await user.click(screen.getByRole('button', { name: 'ตรวจสอบการทบยอด' }))

    await waitFor(() => expect(api.previewPaymentClaim).toHaveBeenCalledWith('c-1', {
      amount: '5000', paid_on: '2026-10-23', reference: undefined, evidence_uid: 'att-1',
    }))
    expect((await screen.findAllByText('8,399.00 → 3,399.00')).length).toBeGreaterThan(0)
    await user.click(screen.getByRole('button', { name: 'บันทึกเป็นรอยืนยัน' }))

    await waitFor(() => expect(api.createPaymentClaim).toHaveBeenCalledWith('c-1', expect.objectContaining({
      amount: '5000', paid_on: '2026-10-23', note: 'ลูกค้าส่งสลิปแล้ว',
      evidence_uid: 'att-1', preview_version: 'balance-v1',
    })))
  })

  it('does not allow saving until an allocation preview succeeds', async () => {
    const user = userEvent.setup()
    renderScreen(<Record />, { route: '/customers/c-1' })

    await user.click(await screen.findByRole('tab', { name: 'ใบแจ้งหนี้และเงินเข้า' }))
    expect(screen.getByRole('button', { name: 'บันทึกเป็นรอยืนยัน' })).toBeDisabled()
    expect(api.createPaymentClaim).not.toHaveBeenCalled()
  })

  it('keeps preview available without a note but requires a non-whitespace note to save', async () => {
    const user = userEvent.setup()
    renderScreen(<Record />, { route: '/customers/c-1' })
    await user.click(await screen.findByRole('tab', { name: 'ใบแจ้งหนี้และเงินเข้า' }))

    await user.type(screen.getByLabelText('ยอดที่ลูกค้าชำระ'), '5000')
    await user.type(screen.getByLabelText('วันที่รับเงิน'), '2026-10-23')
    const note = screen.getByLabelText('หมายเหตุ')
    expect(note).toBeRequired()
    await user.click(screen.getByRole('button', { name: 'ตรวจสอบการทบยอด' }))
    await waitFor(() => expect(api.previewPaymentClaim).toHaveBeenCalled())

    const save = screen.getByRole('button', { name: 'บันทึกเป็นรอยืนยัน' })
    expect(save).toBeDisabled()
    await user.type(note, '   ')
    expect(save).toBeDisabled()
    await user.type(note, 'โอนผ่านธนาคาร')
    expect(save).toBeEnabled()
  })
})

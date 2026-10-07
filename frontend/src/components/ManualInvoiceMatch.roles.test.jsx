import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { renderScreen } from '../test-utils.jsx'
import { setRole } from '../lib/identity.jsx'
import { ManualInvoiceMatch } from './ManualInvoiceMatch.jsx'

vi.mock('../lib/api.js', () => ({
  api: new Proxy({}, { get: (target, name) => {
    if (!(name in target)) target[name] = vi.fn(async () => ({}))
    return target[name]
  } }),
  CHANGED_EVENT: 'volt:changed', AUTH_REQUIRED_EVENT: 'volt:auth-required',
}))
const { api } = await import('../lib/api.js')

beforeEach(() => {
  window.localStorage.clear()
  setRole('OFFICER')
  vi.clearAllMocks()
  api.attachments.mockResolvedValue({ attachments: [] })
})

const component = () => <ManualInvoiceMatch customerUid="synthetic-customer" kase={{ payment_status: 'LATE' }}
  claims={[{ uid: 'synthetic-claim', state: 'PENDING', amount: '100', paid_on: '2026-10-01' }]} />

describe('payment claim controls follow collection permissions', () => {
  it('keeps evidence upload available for OPS while disabling financial claim actions', async () => {
    setRole('OPS')
    renderScreen(component())
    expect(screen.getByLabelText('เลือกไฟล์ใบแจ้งหนี้ / หลักฐาน')).toBeEnabled()
    expect(screen.getByLabelText('ยอดที่ลูกค้าชำระ')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'ตรวจสอบการทบยอด' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'บันทึกเป็นรอยืนยัน' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'ยกเลิก' })).toBeDisabled()
    expect(screen.getByText(/OPS แนบหลักฐานได้/)).toBeInTheDocument()
    await waitFor(() => expect(api.attachments).toHaveBeenCalled())
    expect(api.previewPaymentClaim).not.toHaveBeenCalled()
    expect(api.createPaymentClaim).not.toHaveBeenCalled()
    expect(api.cancelPaymentClaim).not.toHaveBeenCalled()
  })

  it.each(['OFFICER', 'SUPERVISOR', 'MANAGER', 'OWNER'])('retains payment claim controls for %s', (role) => {
    setRole(role)
    renderScreen(component())
    fireEvent.change(screen.getByLabelText('ยอดที่ลูกค้าชำระ'), { target: { value: '100' } })
    fireEvent.change(screen.getByLabelText('วันที่รับเงิน'), { target: { value: '2026-10-01' } })
    expect(screen.getByRole('button', { name: 'ตรวจสอบการทบยอด' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'ยกเลิก' })).toBeEnabled()
  })
})

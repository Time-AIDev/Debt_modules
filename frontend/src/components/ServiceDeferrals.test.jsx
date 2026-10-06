import { beforeEach, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'

vi.mock('../lib/api.js', () => ({ api: {
  previewServiceDeferral: vi.fn(), confirmServiceDeferral: vi.fn(),
  previewServiceDeferralReverse: vi.fn(), reverseServiceDeferral: vi.fn(),
  reviewServiceDeferral: vi.fn(), uploadAttachment: vi.fn(),
} }))
const { api } = await import('../lib/api.js')

const DATA = {
  customer: { uid: 'c1' }, case: { uid: 'case1' }, issues: [], service_deferrals: [],
  payment_summary: { contracts: [{ contract_uid: 'k1', product: 'LEASE', cycles: [
    { n: 1, status: 'OVERDUE', paid: '0.00', partly_paid: false, amount: '100.00', due_date: '2026-08-01' },
    { n: 2, status: 'PAID', paid: '100.00', amount: '100.00', due_date: '2026-09-01' },
  ] }] },
}

beforeEach(() => vi.clearAllMocks())

it('opens the existing form with the invoice contract and cycle selected', async () => {
  const { InvoiceDeferral } = await import('./ServiceDeferrals.jsx')
  const user = userEvent.setup()
  renderScreen(<InvoiceDeferral data={DATA} invoice={{ uid: 'iv1', contract_uid: 'k1',
    contract_cycle: 1, deferral_eligible: true }} />)
  await user.click(screen.getByRole('button', { name: 'เลื่อนงวดเพราะปัญหาบริการ' }))
  expect(screen.getByLabelText('สัญญา')).toHaveValue('k1')
  expect(screen.getByRole('checkbox', { name: /งวด 1/ })).toBeChecked()
})

it('shows the server refusal reason on a disabled row action', async () => {
  const { InvoiceDeferral } = await import('./ServiceDeferrals.jsx')
  renderScreen(<InvoiceDeferral data={DATA} invoice={{ deferral_eligible: false,
    deferral_reason: 'รอยืนยันรับเงิน' }} />)
  expect(screen.getByRole('button', { name: 'เลื่อนงวดเพราะปัญหาบริการ' })).toBeDisabled()
  expect(screen.getByText('รอยืนยันรับเงิน')).toBeInTheDocument()
})

it('offers preview before confirm, with service evidence and no required receipt', async () => {
  const { ServiceDeferrals } = await import('./ServiceDeferrals.jsx')
  const user = userEvent.setup()
  api.previewServiceDeferral.mockResolvedValue({ version: 'v1', collection_overdue_after: '0.00',
    contract_end_after: '2027-01-01', moves: [{ n: 1, old_due_date: '2026-08-01', new_due_date: '2027-01-01' }] })
  api.confirmServiceDeferral.mockResolvedValue({ deferral: { uid: 'd1' } })
  renderScreen(<ServiceDeferrals data={DATA} onChanged={() => {}} />)
  await user.click(screen.getByRole('button', { name: 'เลื่อนงวดเพราะปัญหาบริการ' }))
  expect(screen.queryByRole('checkbox', { name: /งวด 2/ })).not.toBeInTheDocument()
  await user.click(screen.getByRole('checkbox', { name: /งวด 1/ }))
  await user.type(screen.getByLabelText('เหตุผล'), 'ติดตั้งไม่สมบูรณ์')
  await user.type(screen.getByLabelText('ใช้งานไม่ได้ตั้งแต่'), '2026-08-01')
  await user.type(screen.getByLabelText('ใช้งานไม่ได้ถึง'), '2026-09-30')
  await user.type(screen.getByLabelText('บันทึกยืนยันปัญหา'), 'ทีมติดตั้งยืนยัน')
  await user.type(screen.getByLabelText('ผู้ยืนยันปัญหา'), 'Installation')
  await user.click(screen.getByRole('button', { name: 'ดูตัวอย่างก่อนยืนยัน' }))
  expect(await screen.findByText(/วันสิ้นสุดสัญญาใหม่: 01\/01\/2027/)).toBeInTheDocument()
  expect(api.confirmServiceDeferral).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: 'ยืนยันเลื่อนงวด' }))
  await waitFor(() => expect(api.confirmServiceDeferral).toHaveBeenCalledWith('k1', expect.objectContaining({
    cycles: [1], preview_version: 'v1', confirmation_note: 'ทีมติดตั้งยืนยัน', confirmed_by: 'Installation',
  })))
  expect(await screen.findByRole('status')).toHaveTextContent('เลื่อนงวดแล้ว')
})

it('invalidates preview when a decision input changes', async () => {
  const { ServiceDeferrals } = await import('./ServiceDeferrals.jsx')
  const user = userEvent.setup()
  api.previewServiceDeferral.mockResolvedValue({ version: 'v1', moves: [],
    collection_overdue_after: '0.00', contract_end_after: '2027-01-01' })
  renderScreen(<ServiceDeferrals data={DATA} />)
  await user.click(screen.getByRole('button', { name: 'เลื่อนงวดเพราะปัญหาบริการ' }))
  await user.click(screen.getByRole('checkbox', { name: /งวด 1/ }))
  await user.type(screen.getByLabelText('เหตุผล'), 'เหตุผล')
  await user.type(screen.getByLabelText('ใช้งานไม่ได้ตั้งแต่'), '2026-08-01')
  await user.type(screen.getByLabelText('ใช้งานไม่ได้ถึง'), '2026-09-30')
  await user.type(screen.getByLabelText('บันทึกยืนยันปัญหา'), 'ยืนยัน')
  await user.type(screen.getByLabelText('ผู้ยืนยันปัญหา'), 'ทีม')
  await user.click(screen.getByRole('button', { name: 'ดูตัวอย่างก่อนยืนยัน' }))
  expect(await screen.findByRole('button', { name: 'ยืนยันเลื่อนงวด' })).toBeInTheDocument()
  await user.type(screen.getByLabelText('เหตุผล'), ' เพิ่ม')
  expect(screen.queryByRole('button', { name: 'ยืนยันเลื่อนงวด' })).not.toBeInTheDocument()
})

const DEFERRAL = { uid: 'd1', contract_uid: 'k1', created_by: 'debt', status: 'ACTIVE',
  reason: 'ปัญหาบริการ', created_at: '2026-10-23T10:00:00', moves: [
    { n: 1, old_due_date: '2026-08-01', new_due_date: '2027-01-01' },
  ], accounting: { status: 'PENDING_REVIEW', document_refs: [] }, history: [],
}

it('requires a fresh reversal preview and shows restored balances', async () => {
  const { ServiceDeferrals } = await import('./ServiceDeferrals.jsx')
  const user = userEvent.setup()
  api.previewServiceDeferralReverse.mockResolvedValue({ version: 'reverse-v1', moves: DEFERRAL.moves,
    collection_overdue_after: '100.00', contract_end_after: '2026-11-01', penalty_after: '1.00' })
  api.reverseServiceDeferral.mockResolvedValue({ deferral: { ...DEFERRAL, status: 'REVERSED' } })
  renderScreen(<ServiceDeferrals data={{ ...DATA, service_deferrals: [DEFERRAL] }} />)
  await user.click(screen.getByRole('button', { name: 'ย้อนการเลื่อนงวด' }))
  await user.type(screen.getByLabelText('เหตุผล'), 'แก้ไขวันที่')
  await user.click(screen.getByRole('button', { name: 'ดูตัวอย่างก่อนยืนยัน' }))
  expect(await screen.findByText(/ยอดเกินกำหนดสำหรับติดตาม: 100\.00/)).toBeInTheDocument()
  expect(api.reverseServiceDeferral).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: 'ยืนยันย้อนการเลื่อนงวด' }))
  await waitFor(() => expect(api.reverseServiceDeferral).toHaveBeenCalledWith('k1', 'd1', {
    reason: 'แก้ไขวันที่', preview_version: 'reverse-v1',
  }))
  expect(await screen.findByRole('status')).toHaveTextContent('ย้อนการเลื่อนงวดแล้ว')
})

it('records accounting findings and PEAK document references separately', async () => {
  const { ServiceDeferrals } = await import('./ServiceDeferrals.jsx')
  const user = userEvent.setup()
  api.reviewServiceDeferral.mockResolvedValue({ deferral: DEFERRAL })
  renderScreen(<ServiceDeferrals data={{ ...DATA, service_deferrals: [DEFERRAL] }} />)
  expect(screen.getByRole('link', { name: 'ดูประวัติการตรวจสอบบัญชี' })).toHaveAttribute('href',
    '/audit/accounting-reviews?customer_uid=c1&contract_uid=k1&deferral_uid=d1')
  await user.click(screen.getByRole('button', { name: 'บันทึกการตรวจสอบของบัญชี' }))
  await user.type(screen.getByLabelText('ผลการตรวจสอบ'), 'ปรับเอกสารแล้ว')
  await user.selectOptions(screen.getByLabelText('สถานะตรวจสอบของบัญชี'), 'REVIEWED')
  await user.type(screen.getByLabelText(/เลขเอกสารที่ดำเนินการแล้ว/), 'CN-1, IV-NEW')
  await user.click(screen.getByRole('button', { name: 'บันทึกผลตรวจสอบ' }))
  await waitFor(() => expect(api.reviewServiceDeferral).toHaveBeenCalledWith('k1', 'd1', {
    status: 'REVIEWED', note: 'ปรับเอกสารแล้ว', document_refs: ['CN-1', 'IV-NEW'],
  }))
  expect(await screen.findByRole('status')).toHaveTextContent('บันทึกผลตรวจสอบแล้ว')
})

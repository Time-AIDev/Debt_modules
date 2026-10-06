import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { renderScreen } from '../test-utils.jsx'
import { ContractScheduleReview } from './ContractScheduleReview.jsx'

const mocks = vi.hoisted(() => ({ role: 'OFFICER', confirm: vi.fn(), history: vi.fn() }))
vi.mock('../lib/identity.jsx', () => ({ useIdentity: () => ({ role: mocks.role }) }))
vi.mock('../lib/api.js', () => ({ api: {
  confirmContractSchedule: mocks.confirm, contractScheduleConfirmation: mocks.history,
} }))
const data = { payment_summary: { contracts: [{
  contract_uid: 'K-import', product: 'LEASE', requires_schedule_confirmation: true,
  schedule_verified: false, unplaced_peak_details: [{ uid: 'iv-1', doc_no: 'IV-1',
    due_date: '2025-10-25', reason: 'CONTRACT_UNCONFIRMED' }],
}] } }
beforeEach(() => { mocks.role = 'OFFICER'; mocks.confirm.mockReset(); mocks.history.mockReset() })

it('shows why the schedule and invoice await review without an officer confirmation form', () => {
  renderScreen(<ContractScheduleReview data={data} />)
  expect(screen.getByText(/ตารางเป็นประมาณการ/)).toBeInTheDocument()
  expect(screen.getByText(/IV-1.*รอยืนยันวันเริ่มงวด/)).toBeInTheDocument()
  expect(screen.queryByLabelText('วันครบกำหนดงวดแรกตามสัญญา')).not.toBeInTheDocument()
})

it('submits only the Manager-reviewed date, document reference and reason', async () => {
  mocks.role = 'MANAGER'
  const onChanged = vi.fn()
  mocks.confirm.mockResolvedValue({ confirmation: {
    first_due: '2025-10-10', document_ref: 'signed-contract.pdf',
    confirmed_by: 'Manager', reason: 'ตรวจสัญญาลงนามแล้ว',
  } })
  renderScreen(<ContractScheduleReview data={data} onChanged={onChanged} />)
  fireEvent.change(screen.getByLabelText('วันครบกำหนดงวดแรกตามสัญญา'), { target: { value: '2025-10-10' } })
  fireEvent.change(screen.getByLabelText('เอกสารสัญญาอ้างอิง'), { target: { value: 'signed-contract.pdf' } })
  fireEvent.change(screen.getByLabelText('เหตุผลการยืนยัน'), { target: { value: 'ตรวจสัญญาลงนามแล้ว' } })
  fireEvent.click(screen.getByRole('button', { name: 'ยืนยันวันเริ่มงวด' }))
  await waitFor(() => expect(mocks.confirm).toHaveBeenCalledWith('K-import', {
    first_due: '2025-10-10', document_ref: 'signed-contract.pdf', reason: 'ตรวจสัญญาลงนามแล้ว',
  }))
  expect(onChanged).toHaveBeenCalledOnce()
  expect(screen.getByText(/ยืนยันจากสัญญาแล้ว/)).toBeInTheDocument()
})

it('does not offer a confirmation that cannot update a legacy demo contract', () => {
  const { container } = renderScreen(<ContractScheduleReview data={{ payment_summary: {
    contracts: [{ contract_uid: 'K-demo', product: 'LEASE', schedule_verified: true }],
  } }} />)
  expect(container).toBeEmptyDOMElement()
})

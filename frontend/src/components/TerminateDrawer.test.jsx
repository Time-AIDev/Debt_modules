import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('../lib/api.js', () => ({ api: { terminateCustomerContract: vi.fn() } }))
vi.mock('../lib/dictionaries.js', () => ({
  useDictionary: () => [
    { code: 'DEFAULT', label_th: 'ผิดสัญญา / ยึดคืน', label_en: 'Default', active: true },
    { code: 'CUSTOMER_REQUEST', label_th: 'ลูกค้าขอยุติ', label_en: 'Customer request', active: true },
  ],
  active: (rows) => rows.filter((r) => r.active !== false),
  labelFor: (rows, code, lang) => {
    const row = rows.find((r) => r.code === code) || {}
    return row[lang === 'en' ? 'label_en' : 'label_th'] || code
  },
}))

const { api } = await import('../lib/api.js')
const { TerminateDrawer } = await import('./TerminateDrawer.jsx')
const { renderScreen } = await import('../test-utils.jsx')

beforeEach(() => {
  vi.clearAllMocks()
})

describe('TerminateDrawer', () => {
  it('will not submit without a cause and a reason, then sends both', async () => {
    const user = userEvent.setup()
    const onDone = vi.fn()
    api.terminateCustomerContract.mockResolvedValue({ case: {} })
    renderScreen(<TerminateDrawer open onClose={() => {}} customerUid="c-1" onDone={onDone} />)

    const submit = screen.getByRole('button', { name: 'ยืนยันยุติสัญญา' })
    expect(submit).toBeDisabled()
    await user.selectOptions(screen.getByLabelText(/สาเหตุการยุติ/), 'CUSTOMER_REQUEST')
    expect(submit).toBeDisabled()
    await user.type(screen.getByLabelText(/เหตุผล/), 'ลูกค้าแจ้งขอยกเลิกทาง LINE')
    expect(submit).toBeEnabled()

    await user.click(submit)
    await waitFor(() => expect(api.terminateCustomerContract).toHaveBeenCalledWith('c-1', {
      cause: 'CUSTOMER_REQUEST', reason: 'ลูกค้าแจ้งขอยกเลิกทาง LINE', by: undefined,
    }))
    await waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(await screen.findByRole('status')).toHaveTextContent('ยุติสัญญาแล้ว')
  })

  it('renders a closed-balance refusal as the payoff figure and the blocking contracts', async () => {
    const user = userEvent.setup()
    api.terminateCustomerContract.mockRejectedValue({ problem: {
      code: 'balance_not_closed', title: 'The remaining balance must be closed before terminating',
      message_th: 'ต้องปิดยอดคงเหลือก่อนยุติสัญญา — ชำระให้ครบ หรือให้ OWNER ตัดจำหน่าย',
      extensions: { payoff_amount: '612400.00', blocking: [{ contract_uid: 'ct-1', outstanding: '612400.00' }] },
    } })
    renderScreen(<TerminateDrawer open onClose={() => {}} customerUid="c-1" onDone={() => {}} />)

    await user.selectOptions(screen.getByLabelText(/สาเหตุการยุติ/), 'CUSTOMER_REQUEST')
    await user.type(screen.getByLabelText(/เหตุผล/), 'ลูกค้าขอยกเลิก')
    await user.click(screen.getByRole('button', { name: 'ยืนยันยุติสัญญา' }))

    expect(await screen.findByText('ต้องปิดยอดคงเหลือก่อนยุติสัญญา — ชำระให้ครบ หรือให้ OWNER ตัดจำหน่าย')).toBeInTheDocument()
    // the served decimals are printed as money (they arrive raw)
    expect(screen.getAllByText(/612,400\.00/)).toHaveLength(2)
    expect(screen.getByText('ct-1')).toBeInTheDocument()
    // The drawer stays open: the act is not done, only refused.
    expect(screen.getByRole('button', { name: 'ยืนยันยุติสัญญา' })).toBeInTheDocument()
  })
})

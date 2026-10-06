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

  it('explains that a known outstanding balance remains after termination', () => {
    renderScreen(<TerminateDrawer open onClose={() => {}} customerUid="c-1" outstanding="612400.00" />)
    expect(screen.getByText(/ยอดคงเหลือ ฿612,400\.00 จะยังคงอยู่/)).toBeInTheDocument()
    expect(screen.getByText(/ไม่ใช่การชำระเงินหรือตัดจำหน่าย/)).toBeInTheDocument()
  })

  it('does not present an unknown balance as zero', () => {
    renderScreen(<TerminateDrawer open onClose={() => {}} customerUid="c-1" outstanding={null} />)
    expect(screen.getByText(/ยอดคงเหลือยังไม่ทราบ/)).toBeInTheDocument()
    expect(screen.queryByText(/฿0\.00/)).toBeNull()
  })
})

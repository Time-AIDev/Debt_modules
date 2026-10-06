import { beforeEach, expect, it, vi } from 'vitest'
import { act, screen } from '@testing-library/react'
import { Link } from 'react-router-dom'
import { renderScreen } from '../test-utils.jsx'
import { AccountingHistory } from './AccountingHistory.jsx'

vi.mock('../lib/api.js', () => ({ api: { accountingHistory: vi.fn() } }))
const { api } = await import('../lib/api.js')
beforeEach(() => vi.clearAllMocks())

it('shows recorded findings and requests exact case/contract/deferral filters', async () => {
  api.accountingHistory.mockResolvedValue({ entries: [{ uid: 'd1:0', customer_uid: 'c1', customer_name: 'ลูกค้า ก',
    contract_uid: 'k1', deferral_uid: 'd1', status: 'REVIEWED', at: '2026-10-07T01:00:00Z',
    by: 'บัญชี', note: 'ตรวจยอด\nและเอกสารแล้ว', document_refs: ['CN-1'] }], meta: { total: 1, page: 1, page_size: 50 } })
  renderScreen(<AccountingHistory />, { route: '/audit/accounting-reviews?customer_uid=c1&contract_uid=k1&deferral_uid=d1' })
  expect(await screen.findByText('ลูกค้า ก')).toBeInTheDocument()
  expect(api.accountingHistory).toHaveBeenCalledWith({ customer_uid: 'c1', contract_uid: 'k1', deferral_uid: 'd1', page_size: 50 })
  expect(screen.getByText(/ตรวจยอด/).textContent).toContain('\n')
  expect(screen.getByText('CN-1')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'เปิดหน้าเคส' })).toHaveAttribute('href', '/customers/c1')
  expect(screen.queryByRole('button', { name: 'บันทึกผลตรวจสอบ' })).toBeNull()
})

it('shows an honest empty state when no accounting finding exists', async () => {
  api.accountingHistory.mockResolvedValue({ entries: [], meta: { total: 0, page: 1, page_size: 50 } })
  renderScreen(<AccountingHistory />)
  expect(await screen.findByText('ยังไม่มีผลตรวจสอบบัญชีที่บันทึกไว้ตามตัวกรองนี้')).toBeInTheDocument()
})

it('cannot display a late response from a previous case', async () => {
  let resolveFirst, resolveSecond
  api.accountingHistory.mockImplementation((p) => new Promise((resolve) => {
    if (p.customer_uid === 'first') resolveFirst = resolve; else resolveSecond = resolve
  }))
  const { fireEvent } = await import('@testing-library/react')
  renderScreen(<><Link to="/audit/accounting-reviews?customer_uid=second">ถัดไป</Link><AccountingHistory /></>,
    { route: '/audit/accounting-reviews?customer_uid=first' })
  fireEvent.click(screen.getByRole('link', { name: 'ถัดไป' }))
  await act(async () => resolveFirst({ entries: [{ uid: 'wrong', customer_name: 'ผิดเคส' }], meta: { total: 1 } }))
  expect(screen.queryByText('ผิดเคส')).toBeNull()
  await act(async () => resolveSecond({ entries: [], meta: { total: 0, page_size: 50 } }))
  expect(screen.getByText('ยังไม่มีผลตรวจสอบบัญชีที่บันทึกไว้ตามตัวกรองนี้')).toBeInTheDocument()
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
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
  api.caseDetail.mockResolvedValue(CASE)
  api.attachments.mockResolvedValue({ attachments: [] })
  api.peakLinks.mockResolvedValue({ links: [] })
  api.casePeakCodes.mockResolvedValue({
    codes: [
      { contact_code: 'VC-CASE-1', customer_name: 'Worarut Sangtong', invoices: 2, last_due_on: '2026-07-18', linked_to: null },
      { contact_code: 'VC-OTHER', customer_name: 'Someone Else', invoices: 1, last_due_on: '2026-07-18', linked_to: '28000000009' },
    ],
    meta: { total: 2 },
  })
  api.casePeakLink.mockResolvedValue({ link: { contact_code: 'VC-CASE-1', customer_no: '28099990001', rule: 'PERSON_CASE' } })
})

describe('pairing from the case side (D03)', () => {
  it('searches PEAK codes, flags one linked elsewhere and links the free one', async () => {
    const user = userEvent.setup()
    renderScreen(<Record />, { route: '/customers/c-1' })
    await user.click(await screen.findByRole('tab', { name: 'ใบแจ้งหนี้และเงินเข้า' }))
    await user.type(screen.getByLabelText(/ค้นหารหัสผู้ติดต่อ PEAK/), 'VC')
    await waitFor(() => expect(api.casePeakCodes).toHaveBeenCalled())
    expect(await screen.findByText('VC-CASE-1')).toBeInTheDocument()
    expect(screen.getByText('ผูกกับ 28000000009 อยู่แล้ว')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'ผูกกับลูกค้ารายนี้' }))
    await user.type(screen.getByLabelText('เหตุผล (ถ้ามี)'), 'ตรงกับเคสนี้')
    await user.click(screen.getByRole('button', { name: 'ผูกกับลูกค้ารายนี้ VC-CASE-1' }))
    await waitFor(() => expect(api.casePeakLink).toHaveBeenCalledTimes(1))
    expect(api.casePeakLink.mock.calls[0]).toEqual(['c-1', { contact_code: 'VC-CASE-1', reason: 'ตรงกับเคสนี้' }])
  })

  it('lists the case\u2019s own links and can unlink one', async () => {
    api.peakLinks.mockResolvedValue({ links: [{ uid: 5, contact_code: 'VC-CASE-1', customer_no: '28099990001', reason: 'ตรงกับเคสนี้' }] })
    const user = userEvent.setup()
    renderScreen(<Record />, { route: '/customers/c-1' })
    await user.click(await screen.findByRole('tab', { name: 'ใบแจ้งหนี้และเงินเข้า' }))
    expect(await screen.findByText('รหัส PEAK ที่ผูกกับเคสนี้')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'เลิกผูก' }))
    await waitFor(() => expect(api.peakLinkRetire).toHaveBeenCalledWith(5, {}))
  })
})

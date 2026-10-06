import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useLocation } from 'react-router-dom'
import { renderScreen } from '../test-utils.jsx'
import { Palette } from './Palette.jsx'

vi.mock('../lib/api.js', () => ({
  api: {
    customerSearch: vi.fn(),
    customerInvoiceStatuses: vi.fn(),
  },
}))
const { api } = await import('../lib/api.js')

function LocationProbe() {
  return <output data-testid="location">{useLocation().pathname}</output>
}

const CUSTOMER = {
  customer_uid: 'c-1', display_name: 'ปัทมวรรณ สุขเจริญ', name_roman: 'Patmawan',
  volt_id: 'V-1001', customer_no: '28099990001', phone_masked: '08x-xxx-1234',
  email_masked: 'p•••@volt.test', officer: 'รุ่งนภา', matched_on: 'phone_masked',
}

beforeEach(() => {
  vi.clearAllMocks()
  api.customerSearch.mockResolvedValue({ items: [], meta: { total: 0, limit: 6 } })
  api.customerInvoiceStatuses.mockResolvedValue({
    customer_uid: 'c-1',
    items: [{ uid: 'inv-1', reference: 'IV-001', kind: 'BALANCE', month_index: 1, due_date: '2026-10-01', state: 'OVERDUE', peak_state: 'SENT_PEAK', amount: '3000.00', outstanding: '3000.00' }],
    meta: { total: 1, limit: 5, has_more: false },
  })
})

describe('the customer command palette', () => {
  it('shows payment totals on each customer card before opening its complete invoice list', async () => {
    api.customerSearch.mockResolvedValue({ items: [CUSTOMER], meta: { total: 1, limit: 6 } })
    api.customerInvoiceStatuses.mockImplementation((_uid, params) => Promise.resolve({
      items: Array.from({ length: params?.include_all ? 25 : 5 }, (_, i) => ({
        uid: `inv-${i}`, reference: `IV-${i + 1}`, state: 'SENT', amount: '100.00', outstanding: '100.00',
      })),
      summary: { paid: '1250.50', outstanding: '2500.00' },
      meta: { total: 25, has_more: !params?.include_all, remaining: 20 },
    }))
    const user = userEvent.setup()
    renderScreen(<Palette open onClose={() => {}} />)
    await user.type(screen.getByRole('textbox'), 'ป')

    const row = await screen.findByRole('button', { name: /^ลูกค้า ปัทมวรรณ/ })
    expect(await within(row).findByText('จ่ายแล้ว ฿1,250.50')).toBeInTheDocument()
    expect(within(row).getByText('ค้าง ฿2,500.00')).toBeInTheDocument()
    expect(screen.queryByText('IV-25')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'ดูสถานะใบแจ้งหนี้ของ ปัทมวรรณ สุขเจริญ' }))
    const region = await screen.findByRole('region', { name: 'ดูสถานะใบแจ้งหนี้ของ ปัทมวรรณ สุขเจริญ' })
    expect(within(region).getByText('IV-25')).toBeInTheDocument()
    expect(within(region).getAllByRole('listitem')).toHaveLength(25)
    expect(screen.queryByText('อีก 20 รายการ')).not.toBeInTheDocument()
  })

  it('searches after one character and keeps a masked-field match visible', async () => {
    api.customerSearch.mockResolvedValue({ items: [CUSTOMER], meta: { total: 1, limit: 6 } })
    const user = userEvent.setup()
    renderScreen(<Palette open onClose={() => {}} />)

    await user.type(screen.getByRole('textbox'), '4')

    expect(await screen.findByText('ปัทมวรรณ สุขเจริญ')).toBeInTheDocument()
    expect(screen.getByText('08x-xxx-1234')).toBeInTheDocument()
    expect(api.customerSearch).toHaveBeenCalledWith({ q: '4', limit: 6 }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
  })

  it('aborts an obsolete search and never renders its stale result', async () => {
    const pending = []
    api.customerSearch.mockImplementation((_params, { signal }) => new Promise((resolve) => pending.push({ resolve, signal })))
    const user = userEvent.setup()
    renderScreen(<Palette open onClose={() => {}} />)

    await user.type(screen.getByRole('textbox'), 'ก')
    await waitFor(() => expect(pending).toHaveLength(1))
    await user.type(screen.getByRole('textbox'), 'ข')
    await waitFor(() => expect(pending).toHaveLength(2))
    expect(pending[0].signal.aborted).toBe(true)
    pending[1].resolve({ items: [{ ...CUSTOMER, display_name: 'ผลใหม่' }], meta: { total: 1, limit: 6 } })
    expect(await screen.findByText('ผลใหม่')).toBeInTheDocument()
    pending[0].resolve({ items: [{ ...CUSTOMER, display_name: 'ผลเก่า' }], meta: { total: 1, limit: 6 } })
    await Promise.resolve()
    expect(screen.queryByText('ผลเก่า')).not.toBeInTheDocument()
  })

  it('opens invoice statuses from hover or keyboard focus without nesting controls', async () => {
    api.customerSearch.mockResolvedValue({ items: [CUSTOMER], meta: { total: 1, limit: 6 } })
    const user = userEvent.setup()
    renderScreen(<Palette open onClose={() => {}} />)
    await user.type(screen.getByRole('textbox'), 'ป')
    const preview = await screen.findByRole('button', { name: 'ดูสถานะใบแจ้งหนี้ของ ปัทมวรรณ สุขเจริญ' })

    fireEvent.focus(preview)

    expect(await screen.findByText('IV-001')).toBeInTheDocument()
    expect(screen.getByText('เลยกำหนด')).toBeInTheDocument()
    expect(screen.getByText('เลยกำหนด').closest('span').querySelector('.st--problem')).toBeTruthy()
    expect(screen.queryByText('BALANCE')).not.toBeInTheDocument()
    expect(screen.queryByText('3,000.00')).not.toBeInTheDocument()
    expect(screen.queryByText(/M1/)).not.toBeInTheDocument()
    expect(preview).toHaveAttribute('aria-expanded', 'true')
    expect(preview.parentElement.querySelector('button button')).toBeNull()
    fireEvent.keyDown(preview, { key: 'Escape' })
    expect(screen.queryByText('IV-001')).not.toBeInTheDocument()

    fireEvent.mouseEnter(preview)
    expect(await screen.findByText('IV-001')).toBeInTheDocument()
  })

  it('opens the invoice preview by click for pointer and touch users', async () => {
    api.customerSearch.mockResolvedValue({ items: [CUSTOMER], meta: { total: 1, limit: 6 } })
    const user = userEvent.setup()
    renderScreen(<Palette open onClose={() => {}} />)
    await user.type(screen.getByRole('textbox'), 'ป')

    await user.click(await screen.findByRole('button', { name: 'ดูสถานะใบแจ้งหนี้ของ ปัทมวรรณ สุขเจริญ' }))

    expect(await screen.findByText('IV-001')).toBeInTheDocument()
  })

  it.each([
    ['empty', () => api.customerInvoiceStatuses.mockResolvedValue({ items: [], meta: { total: 0, has_more: false } }), 'ไม่พบใบแจ้งหนี้'],
    ['error', () => api.customerInvoiceStatuses.mockRejectedValue(new Error('offline')), 'โหลดสถานะใบแจ้งหนี้ไม่สำเร็จ'],
  ])('shows the invoice preview %s state', async (_state, arrange, message) => {
    api.customerSearch.mockResolvedValue({ items: [CUSTOMER], meta: { total: 1, limit: 6 } })
    arrange()
    const user = userEvent.setup()
    renderScreen(<Palette open onClose={() => {}} />)
    await user.type(screen.getByRole('textbox'), 'ป')

    fireEvent.focus(await screen.findByRole('button', { name: 'ดูสถานะใบแจ้งหนี้ของ ปัทมวรรณ สุขเจริญ' }))

    expect(await screen.findByText(message)).toBeInTheDocument()
  })

  it('keeps the customer row as the navigation control', async () => {
    api.customerSearch.mockResolvedValue({ items: [CUSTOMER], meta: { total: 1, limit: 6 } })
    const user = userEvent.setup()
    renderScreen(<><Palette open onClose={() => {}} /><LocationProbe /></>)
    await user.type(screen.getByRole('textbox'), 'ป')

    await user.click(await screen.findByRole('button', { name: /^ลูกค้า ปัทมวรรณ/ }))

    expect(screen.getByTestId('location')).toHaveTextContent('/customers/c-1')
  })
})

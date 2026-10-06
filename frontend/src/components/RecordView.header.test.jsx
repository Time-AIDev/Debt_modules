import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { renderScreen } from '../test-utils.jsx'
import { Record } from '../screens/Record.jsx'
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

function headerCase(over = {}) {
  return {
    ...CASE,
    customer: { ...CASE.customer, volt_id: 'V-1001', system_size_kwp: '6.25' },
    contracts: [{ ...CASE.contracts[0], pmt: '2899.00', term_months: 96 }],
    payment_summary: {
      ...CASE.payment_summary,
      totals: {
        ...CASE.payment_summary.totals,
        cycle_count: 96, paid_count: 23, remaining_count: 73,
        counts: { PAID: 23, OVERDUE: 2, UPCOMING: 71, NO_AMOUNT: 0 },
      },
    },
    ...over,
  }
}

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
  api.caseDetail.mockResolvedValue(headerCase())
})

describe('the case header (F03, F04, F12, F15)', () => {
  it('opens with paid / total, its remaining note and the emphasis class', async () => {
    const { container } = renderScreen(<Record />, { route: '/customers/c-1' })
    const value = await screen.findByText('23 / 96')
    expect(value.closest('.case__fact--key')).toBeTruthy()
    const first = container.querySelector('.case__facts .case__fact')
    expect(first).toHaveClass('case__fact--key')
    expect(first).toHaveTextContent('จ่ายแล้ว / ทั้งหมด')
    expect(screen.getByText('เหลือ 73 งวด')).toBeInTheDocument()
    // the v1.1 overdue count rides in row A; its restating caption is now its tooltip
    expect(screen.getByText('งวดค้าง').closest('.case__fact')).toHaveAttribute('title', 'งวดที่เกินกำหนดแล้ว')
  })

  it('does not count a paid down payment as a paid instalment', async () => {
    api.caseDetail.mockResolvedValue(headerCase({
      payment_summary: {
        ...CASE.payment_summary,
        totals: {
          cycle_count: 2, paid_count: 1, remaining_count: 1,
          counts: { PAID: 1, OVERDUE: 0, UPCOMING: 1, NO_AMOUNT: 0 },
          breakdown: {
            deposit: { count: 1, counts: { PAID: 1 }, remaining_count: 0 },
            instalment: { count: 1, counts: { PAID: 0, OVERDUE: 0, UPCOMING: 1, NO_AMOUNT: 0 }, remaining_count: 1 },
          },
        },
      },
    }))

    renderScreen(<Record />, { route: '/customers/c-1' })

    expect(await screen.findByText('0 / 1')).toBeInTheDocument()
    expect(screen.getByText('เหลือ 1 งวด')).toBeInTheDocument()
  })

  it('shows two invoice-backed CASH instalments and separates the PEAK balance', async () => {
    api.caseDetail.mockResolvedValue(headerCase({
      contracts: [{ ...CASE.contracts[0], product: 'CASH', entity: 'EPC' }],
      work_item: { ...CASE.work_item, aggregate_outstanding: '325000.00' },
      payment_summary: {
        ...CASE.payment_summary,
        totals: { ...CASE.payment_summary.totals, outstanding_amount: '0.00',
          breakdown: { instalment: { count: 1, display_paid_count: 1, display_remaining_count: 0,
            counts: { PAID: 1, OVERDUE: 0 } } } },
        display_instalments: {
          total_count: 2, paid_count: 1, remaining_count: 1, overdue_count: 1,
          peak_outstanding: '165000.00', contract_outstanding: '325000.00', peak_balance_complete: true,
          contracts: [{ contract_uid: 'ct-1', source: 'PEAK_REPORT', cycles: [
            { n: 1, kind: 'BALANCE', status: 'PAID', source: 'PEAK', due_date: '2026-07-20', amount: '160000.00' },
            { n: 2, kind: 'BALANCE', status: 'OVERDUE', source: 'PEAK', due_date: '2026-08-23', amount: '165000.00' },
          ] }],
        },
      },
    }))
    renderScreen(<Record />, { route: '/customers/c-1' })
    expect(await screen.findByText('1 / 2')).toBeInTheDocument()
    expect(screen.getByText('เหลือ 1 งวด')).toBeInTheDocument()
    expect(screen.getByText('งวดค้าง').closest('.case__fact')).toHaveTextContent('1')
    expect(screen.getByText('คงเหลือ').closest('.case__fact')).toHaveTextContent('325,000.00')
    expect(screen.getByText(/PEAK.*165,000.00/)).toBeInTheDocument()
  })

  it('does not compare a partial PEAK balance with a multi-contract case balance', async () => {
    api.caseDetail.mockResolvedValue(headerCase({
      contracts: [{ ...CASE.contracts[0], product: 'CASH' }, { ...CASE.contracts[0], uid: 'ct-2', product: 'LEASE' }],
      payment_summary: { ...CASE.payment_summary, display_instalments: {
        total_count: 2, paid_count: 1, remaining_count: 1, overdue_count: 1,
        peak_outstanding: '165000.00', contract_outstanding: '325000.00', peak_balance_complete: false,
        contracts: [],
      } },
    }))
    renderScreen(<Record />, { route: '/customers/c-1' })
    expect(await screen.findByText('1 / 2')).toBeInTheDocument()
    expect(screen.queryByText(/PEAK.*165,000.00/)).not.toBeInTheDocument()
  })

  it('serves the system size, the monthly instalment and the unpaid-invoice count', async () => {
    renderScreen(<Record />, { route: '/customers/c-1' })
    expect(await screen.findByText('6.25 kWp')).toBeInTheDocument()
    expect(screen.getByText('6.25 kWp').closest('.case__fact')).toHaveAttribute('title', 'จากใบสั่งซื้อ Odoo')
    expect(screen.getByText('2,899.00')).toBeInTheDocument()
    expect(screen.getByText('96 งวดตามสัญญา')).toBeInTheDocument()
    expect(screen.getByText('4 ใบ')).toBeInTheDocument()
    expect(screen.getByText('PEAK ณ 14/09/2026')).toBeInTheDocument()
  })

  it('says why the system size is absent instead of inventing a zero', async () => {
    api.caseDetail.mockResolvedValue(headerCase({ customer: { ...CASE.customer, volt_id: 'V-1001', system_size_kwp: null } }))
    renderScreen(<Record />, { route: '/customers/c-1' })
    expect(await screen.findByText('ไม่มีข้อมูลขนาดระบบ')).toBeInTheDocument()
  })

  it('prints the Volt ID before the customer number', async () => {
    renderScreen(<Record />, { route: '/customers/c-1' })
    const identity = await screen.findByText('V-1001')
    expect(identity.closest('.case__idRow')).toHaveTextContent('V-1001· 28099990001')
    expect(screen.getByRole('button', { name: 'คัดลอกตัวระบุลูกค้า' })).toBeInTheDocument()
  })

  it('says what the sheet says, where PEAK disagrees, and the day the sheet knows payments to', async () => {
    api.caseDetail.mockResolvedValue(headerCase({
      case: {
        ...CASE.case,
        sheet_status: { code: 'LATE', word: 'Late', unknown: false, month: 'Aug 2026' },
        status_disagreements: [
          { month: null, peak: 'CURRENT', sheet: 'LATE', peak_off: false },
          { month: 'Jul 2026', peak: 'PAID', sheet: 'LATE' },
        ],
        sheet_captured_on: '2026-09-25',
      },
      work_item: { ...CASE.work_item, business_date: '2026-10-23' },
    }))
    const { container } = renderScreen(<Record />, { route: '/customers/c-1' })
    expect(await screen.findByText('สถานะตามชีต: Late (Aug 2026)')).toBeInTheDocument()
    const row = container.querySelector('.case__sheetRow')
    expect(row).toHaveTextContent('สถานะปัจจุบัน · PEAK ปกติ · ชีต ค้างชำระ')
    expect(row).toHaveTextContent('Jul 2026 · PEAK ชำระแล้ว · ชีต ค้างชำระ')
    // beside the days overdue: after the capture day only PEAK knows what was paid
    expect(screen.getByText('อายุหนี้').closest('.case__fact'))
      .toHaveTextContent('ข้อมูลการชำระจากชีต ณ 25/09/2026')
  })

  it('flags a sheet word it does not know, and says nothing of a capture day on the held book', async () => {
    api.caseDetail.mockResolvedValue(headerCase({
      case: { ...CASE.case, sheet_status: { code: null, word: 'Service Issue', unknown: true, month: 'Aug 2026' },
              status_disagreements: [], sheet_captured_on: null },
    }))
    renderScreen(<Record />, { route: '/customers/c-1' })
    expect(await screen.findByText('สถานะตามชีต: Service Issue (Aug 2026) · ระบบไม่รู้จักคำนี้ จึงใช้สถานะจากสัญญา'))
      .toBeInTheDocument()
    expect(screen.queryByText(/ข้อมูลการชำระจากชีต/)).toBeNull()
  })
})


it('shows reported paid instalments and the unverified count together in the scorecard', async () => {
  api.caseDetail.mockResolvedValue(headerCase({ payment_summary: {
    ...CASE.payment_summary,
    totals: { ...CASE.payment_summary.totals,
      breakdown: { instalment: {
        count: 48, counts: { PAID: 4, INFERRED_PAID: 6, SHEET_REPORTED_PAID: 2 },
        remaining_count: 44, display_paid_count: 12, unverified_paid_count: 8,
        display_remaining_count: 36,
      } },
    },
  } }))
  renderScreen(<Record />, { route: '/customers/c-1' })
  const value = await screen.findByText('12 / 48')
  const card = value.closest('.case__fact')
  expect(card).toHaveTextContent('8 รอยืนยันจาก PEAK')
  expect(card).toHaveTextContent('เหลือ 36 งวด')
  expect(card.querySelector('.case__unverifiedPaid')).toHaveTextContent('8')
})

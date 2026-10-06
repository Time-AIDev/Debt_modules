import { describe, it, expect } from 'vitest'
import { screen, fireEvent } from '@testing-library/react'
import { renderScreen } from '../test-utils.jsx'
import { CycleGrid } from './CycleGrid.jsx'

function cycle(n, status, over = {}) {
  return {
    n, kind: 'INSTALMENT', due_date: '2026-11-10', amount: '2899.00',
    paid: status === 'PAID' ? '2899.00' : '0.00', outstanding: status === 'PAID' ? '0.00' : '2899.00',
    status, partly_paid: false, source: 'SHEET_DERIVED', doc_no: null, ...over,
  }
}

const CYCLES = Array.from({ length: 96 }, (_, i) => (
  i < 23 ? cycle(i + 1, 'PAID')
    : i === 23 ? cycle(24, 'OVERDUE', { partly_paid: true })
      : cycle(i + 1, 'UPCOMING')
))

const SUMMARY = {
  contracts: [{ contract_uid: 'ct-1', cycles: CYCLES }],
  totals: { cycle_count: 96, counts: { PAID: 23, OVERDUE: 1, UPCOMING: 72, NO_AMOUNT: 0 } },
  provenance_th: 'ตัวเลขเสิร์ฟจาก API',
  provenance_en: 'Every figure is served by the API',
}

it('shows original and adjusted dates on keyboard focus and touch', () => {
  renderScreen(<CycleGrid summary={{ contracts: [{ contract_uid: 'k1', cycles: [cycle(1, 'UPCOMING', {
    due_date: '2026-09-23', collection_due_date: '2027-01-23',
    deferral: { old_due_date: '2026-09-23', new_due_date: '2027-01-23' },
  })] }], totals: {} }} />)
  const button = screen.getByRole('button', { name: /M1/ })
  fireEvent.focus(button)
  expect(screen.getByRole('tooltip')).toHaveTextContent('23/09/2026')
  expect(screen.getByRole('tooltip')).toHaveTextContent('23/01/2027')
  fireEvent.blur(button)
  fireEvent.click(button)
  expect(screen.getByRole('tooltip')).toBeInTheDocument()
  fireEvent.keyDown(button, { key: 'Escape' })
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
})

describe('the instalment cycle grid (F14)', () => {
  it('names CASH months awaiting evidence in the count summary', () => {
    const summary = { contracts: [{ contract_uid: 'cash-1', cycles: [] }], totals: {},
      display_instalments: { total_count: 1, paid_count: 0, overdue_count: 0,
        upcoming_count: 0, unconfirmed_count: 1, contracts: [{ contract_uid: 'cash-1', cycles: [
          cycle(1, 'UNCONFIRMED', { kind: 'BALANCE' }),
        ] }] } }
    renderScreen(<CycleGrid summary={summary} />)
    expect(screen.getByText('รอตรวจสอบ 1 งวด')).toBeInTheDocument()
  })
  it('draws both invoice-backed CASH instalments rather than the synthetic balance row', () => {
    const summary = {
      contracts: [{ contract_uid: 'cash-1', cycles: [
        cycle(1, 'PAID', { kind: 'DEPOSIT' }), cycle(2, 'PAID', { kind: 'BALANCE', instalment_n: 1 }),
      ] }],
      totals: { cycle_count: 2, counts: { PAID: 2 }, breakdown: { instalment: { count: 1, counts: { PAID: 1 } } } },
      display_instalments: { total_count: 2, paid_count: 1, remaining_count: 1, overdue_count: 1,
        upcoming_count: 0, unconfirmed_count: 0, contracts: [{ contract_uid: 'cash-1', source: 'PEAK_REPORT', cycles: [
          cycle(1, 'PAID', { kind: 'BALANCE', source: 'PEAK', doc_no: 'IV-PAID' }),
          cycle(2, 'OVERDUE', { kind: 'BALANCE', source: 'PEAK', doc_no: 'IV-OPEN' }),
        ] }] },
    }
    const { container } = renderScreen(<CycleGrid summary={summary} />)
    expect(screen.getByText('จ่ายแล้ว 1 · เกินกำหนด 1 · ยังไม่ถึงกำหนด 0 · รวม 2')).toBeInTheDocument()
    expect(screen.getByText('M1')).toHaveClass('monthgrid__cell--paid')
    expect(screen.getByText('M2')).toHaveClass('monthgrid__cell--late')
    expect(container.querySelectorAll('.monthgrid .monthgrid__cell')).toHaveLength(2)
  })

  it('draws one cell per served cycle and the served counts line', () => {
    const { container } = renderScreen(<CycleGrid summary={SUMMARY} />)
    expect(container.querySelectorAll('.monthgrid__cell')).toHaveLength(96)
    expect(screen.getByText('จ่ายแล้ว 23 · เกินกำหนด 1 · ยังไม่ถึงกำหนด 72 · รวม 96')).toBeInTheDocument()
    // the legend names every state a cell can take, the half-fill included
    for (const word of ['ชำระแล้ว', 'ชำระบางส่วน', 'ค้างชำระ', 'ยังไม่ถึงกำหนด']) expect(screen.getByText(word)).toBeInTheDocument()
  })

  it('maps a status to its tone and half-fills a partly paid cycle', () => {
    const { container } = renderScreen(<CycleGrid summary={SUMMARY} />)
    const cells = container.querySelectorAll('.monthgrid__cell')
    expect(cells[0]).toHaveClass('monthgrid__cell--paid')
    // the tooltip says kind · due · amount · status · source in words, not codes
    expect(cells[0]).toHaveAttribute('title', 'ค่างวด · 10/11/2026 · 2,899.00 · ชำระแล้ว · ชีต')
    expect(cells[1]).toHaveAttribute('title', expect.stringContaining('ชำระแล้ว'))
    expect(cells[23]).toHaveClass('monthgrid__cell--part')
    expect(cells[24]).not.toHaveClass('monthgrid__cell--part')
  })

  it('renders nothing without a summary', () => {
    const { container } = renderScreen(<CycleGrid summary={null} />)
    expect(container.querySelector('.cyclegrid')).toBeNull()
  })

  it('overlays pending payment with text as well as a visual treatment', () => {
    const { container } = renderScreen(
      <CycleGrid summary={SUMMARY} invoices={[{ month_index: 24, pending_amount: '1000.00' }]} />,
    )
    const pending = container.querySelectorAll('.monthgrid__cell')[23]
    expect(pending).toHaveClass('monthgrid__cell--pending')
    expect(pending).toHaveTextContent('M24รอยืนยัน')
    expect(pending).toHaveAttribute('title', expect.stringContaining('รอยืนยัน 1,000.00'))
  })

  it('renders a paid down payment separately from the unpaid first instalment', () => {
    const summary = {
      contracts: [{
        contract_uid: 'cash-1',
        cycles: [
          cycle(1, 'PAID', { kind: 'DEPOSIT', instalment_n: null, amount: '20000.00' }),
          cycle(2, 'UPCOMING', { kind: 'BALANCE', instalment_n: 1, amount: '137353.00' }),
        ],
      }],
      totals: {
        cycle_count: 2,
        counts: { PAID: 1, OVERDUE: 0, UPCOMING: 1, NO_AMOUNT: 0 },
        breakdown: {
          deposit: { count: 1, counts: { PAID: 1, OVERDUE: 0, UPCOMING: 0, NO_AMOUNT: 0 } },
          instalment: { count: 1, counts: { PAID: 0, OVERDUE: 0, UPCOMING: 1, NO_AMOUNT: 0 } },
        },
      },
    }

    const { container } = renderScreen(<CycleGrid summary={summary} />)

    expect(screen.getByText('จ่ายแล้ว 0 · เกินกำหนด 0 · ยังไม่ถึงกำหนด 1 · รวม 1')).toBeInTheDocument()
    expect(screen.getByText('DP')).toHaveClass('monthgrid__cell--paid')
    expect(screen.getByText('M1')).toHaveClass('monthgrid__cell--notdue')
    expect(container.querySelector('.cyclegrid__deposits')).toBeTruthy()
  })
})

it('distinguishes inferred payments and lists actual PEAK dates with review totals', () => {
  const summary = {
    contracts: [{ contract_uid: 'ct-1', schedule_verified: false, cycles: [
      cycle(1, 'INFERRED_PAID', { payment_evidence: 'INFERRED_PAID' }),
      cycle(2, 'PAID', { source: 'PEAK', payment_evidence: 'CONFIRMED', due_date: '2025-10-25',
        schedule_due_date: '2025-10-10', peak_due_dates: ['2025-10-25', '2025-10-28'] }),
    ] }],
    totals: { cycle_count: 2, counts: { PAID: 1, INFERRED_PAID: 1 }, review_count: 1, review_amount: '100.00' },
  }
  const { container } = renderScreen(<CycleGrid summary={summary} />)
  expect(screen.getByText(/ยอดรอตรวจสอบ.*100/)).toBeInTheDocument()
  expect(container.querySelectorAll('.monthgrid__cell')[0]).toHaveAttribute('title', expect.stringContaining('อนุมานว่าจ่าย'))
  expect(container.querySelectorAll('.monthgrid__cell')[1]).toHaveAttribute('title', expect.stringContaining('28/10/2025'))
})

it('does not overlay a pending payment on an unplaced invoice M mark', () => {
  const { container } = renderScreen(<CycleGrid summary={SUMMARY}
    invoices={[{ contract_cycle: null, month_index: 24, pending_amount: '1000.00' }]} />)
  expect(container.querySelector('.monthgrid__cell--pending')).toBeNull()
})

it('labels the backend business-date cycle as due today', () => {
  renderScreen(<CycleGrid summary={{ business_date: '2026-10-23', contracts: [{contract_uid:'ct-1',
    cycles:[cycle(1,'UPCOMING',{due_date:'2026-10-23'})]}], totals:{counts:{UPCOMING:1},cycle_count:1} }} />)
  expect(screen.getByRole('button',{name:/ครบกำหนดวันนี้/})).toHaveClass('monthgrid__cell--notdue')
})

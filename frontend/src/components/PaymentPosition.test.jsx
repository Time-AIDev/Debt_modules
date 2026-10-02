import { describe, it, expect } from 'vitest'
import { screen } from '@testing-library/react'
import { renderScreen } from '../test-utils.jsx'
import { PaymentPosition } from './PaymentPosition.jsx'

const FULL = {
  paid_count: 11, open_count: 4, total_count: 15,
  oldest_unpaid: { uid: 'inv-00199', peak_number: 'IVT-20260400091', due_date: '2026-04-12', outstanding: '8399.00' },
  last_money_in: { amount: '38257.45', on: '2026-07-16', source: 'PEAK_REPORT', ref: 'RE-20260700272' },
  source: 'PEAK_REPORT', as_of: '2026-09-14', as_of_days: 3, stale: false,
  note_th: 'ข้อมูลล่าสุดมาจากรายงานใบแจ้งหนี้ PEAK ณ 2026-09-14',
  note_en: 'Latest data from the PEAK invoice report as of 2026-09-14',
}

describe('PaymentPosition', () => {
  it('names the source, so the officer knows who says this', () => {
    renderScreen(<PaymentPosition pp={FULL} />)
    expect(screen.getByTestId('pp-source')).toHaveAttribute('data-source', 'PEAK_REPORT')
  })

  it('prints the served counts, the oldest unpaid and the last money in', () => {
    renderScreen(<PaymentPosition pp={FULL} />)
    expect(screen.getByTestId('pp-counts')).toHaveTextContent('จ่ายแล้ว 11 จาก 15 · ค้าง 4')
    expect(screen.getByTestId('pp-oldest')).toHaveTextContent('IVT-20260400091')
    expect(screen.getByTestId('pp-oldest')).toHaveTextContent('8,399.00')
    expect(screen.getByTestId('pp-lastin')).toHaveTextContent('38,257.45')
  })

  it('marks a stale position rather than showing it as current', () => {
    renderScreen(<PaymentPosition pp={{ ...FULL, stale: true }} />)
    expect(screen.getByTestId('pp-stale')).toBeInTheDocument()
    // with the problem icon beside its word, never colour alone (brief §3.2)
    expect(screen.getByTestId('pp-stale').querySelector('.st--problem')).not.toBeNull()
  })

  it('does not mark a fresh position', () => {
    renderScreen(<PaymentPosition pp={FULL} />)
    expect(screen.queryByTestId('pp-stale')).toBeNull()
  })

  it('an unknown as-of is drawn as unknown, never as fresh', () => {
    renderScreen(<PaymentPosition pp={{ ...FULL, as_of: null, as_of_days: null, stale: null }} />)
    expect(screen.getByTestId('pp-asof-unknown')).toBeInTheDocument()
    expect(screen.queryByTestId('pp-stale')).toBeNull()
  })

  it('renders nothing at all when the API does not carry the block', () => {
    const { container } = renderScreen(<PaymentPosition pp={null} />)
    expect(container.querySelector('[data-testid="payment-position"]')).toBeNull()
  })

  it('the compact form is one line and keeps the source and the stale mark', () => {
    renderScreen(<PaymentPosition pp={{ ...FULL, stale: true }} compact />)
    expect(screen.getByTestId('pp-counts')).toHaveTextContent('จ่าย 11 · ค้าง 4')
    expect(screen.getByTestId('pp-source')).toBeInTheDocument()
    expect(screen.getByTestId('pp-stale')).toBeInTheDocument()
    expect(screen.queryByTestId('pp-oldest')).toBeNull()
    expect(screen.queryByTestId('pp-lastin')).toBeNull()
  })
})

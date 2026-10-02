import { describe, it, expect } from 'vitest'
import { screen } from '@testing-library/react'
import { renderScreen } from '../test-utils.jsx'
import { DailySummary } from './DailySummary.jsx'

describe('the daily summary (F17)', () => {
  it('prints the served numbers in four cells and computes nothing', () => {
    renderScreen(<DailySummary summary={{
      total: 62, not_yet: 59, worked: 3, ptp_count: 2, ptp_amount: '12600.50', unreachable: 4,
    }} />)
    expect(screen.getByText('สรุปการติดตามวันนี้')).toBeInTheDocument()
    // the served worked count against the list, and its bar
    expect(screen.getByText('ติดตามแล้ว 3 จาก 62')).toBeInTheDocument()
    expect(document.querySelector('.daysum__bar > span').style.width).toBe('5%')
    for (const value of ['62', '59', '4']) {
      expect(screen.getByText(value)).toBeInTheDocument()
    }
    // the PTP cell carries its count and the promised amount in one figure
    const ptp = screen.getByText('นัดชำระ').closest('.daysum__cell')
    expect(ptp).toHaveTextContent('2')
    expect(ptp).toHaveTextContent('12,600.50')
    for (const label of ['ต้องติดตาม', 'ยังไม่ติดตาม', 'นัดชำระ', 'ติดต่อไม่ได้']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('renders nothing without a served summary', () => {
    const { container } = renderScreen(<DailySummary summary={null} />)
    expect(container.querySelector('.daysum')).toBeNull()
  })
})

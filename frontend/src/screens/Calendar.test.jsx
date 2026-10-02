import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('../lib/api.js', () => ({ api: { calendar: vi.fn(), dataState: vi.fn() } }))
const { api } = await import('../lib/api.js')
const { Calendar } = await import('./Calendar.jsx')
const { renderScreen } = await import('../test-utils.jsx')

const BD = '2026-10-23'                       // the served business date
// 2026-10-01 is a Thursday, so the October grid opens on Monday 2026-09-28 (+41 days).
const OCT_GRID = { from: '2026-09-28', to: '2026-11-08' }

function payload(overrides = {}) {
  return {
    items: [],
    days: [],
    meta: { business_date: BD, total: 0, by_kind: {}, by_month: [], from: OCT_GRID.from, to: OCT_GRID.to },
    ...overrides,
  }
}

const YEAR_ITEMS = [
  { uid: 'a', kind: 'PTP_DUE', on: '2026-01-05', display_name: 'ก' },
  { uid: 'b', kind: 'NOTICE', on: '2026-01-20', display_name: 'ข' },
  { uid: 'c', kind: 'PTP_DUE', on: '2026-03-02', display_name: 'ค' },
]
const YEAR_MONTHS = ['2026-01', '2026-02', '2026-03'].map((month) => ({
  month,
  total: YEAR_ITEMS.filter((i) => i.on.slice(0, 7) === month).length,
  by_kind: {},
})).concat(Array.from({ length: 9 }, (_, i) => ({
  month: `2026-${String(i + 4).padStart(2, '0')}`, total: 0, by_kind: {},
})))

function calledWith(from, to) {
  return api.calendar.mock.calls.some(([range]) => range?.from === from && range?.to === to)
}

beforeEach(() => {
  vi.clearAllMocks()
  api.calendar.mockResolvedValue(payload())
  api.dataState.mockResolvedValue({ epoch: 0, seen_epoch: 0, stale: false, serving: {} })
})

describe('Calendar · the day / week / month / year picker', () => {
  it('opens on the month grid around the served business date', async () => {
    renderScreen(<Calendar />)
    await waitFor(() => expect(calledWith(OCT_GRID.from, OCT_GRID.to)).toBe(true))
    expect(screen.getByRole('radio', { name: 'เดือน' })).toHaveAttribute('aria-checked', 'true')
  })

  it('switches to the day unit and asks for that one day', async () => {
    const user = userEvent.setup()
    renderScreen(<Calendar />)
    await waitFor(() => expect(api.calendar).toHaveBeenCalled())
    await user.click(screen.getByRole('radio', { name: 'วัน' }))
    await waitFor(() => expect(calledWith(BD, BD)).toBe(true))
    expect(screen.getByText('รายการของวันนั้น')).toBeInTheDocument()
  })

  it('steps the month grid with the arrows', async () => {
    const user = userEvent.setup()
    renderScreen(<Calendar />)
    await waitFor(() => expect(api.calendar).toHaveBeenCalled())
    await user.click(screen.getByRole('button', { name: 'ช่วงถัดไป' }))
    // November 2026 starts on a Sunday, so its grid opens Monday 2026-10-26.
    await waitFor(() => expect(calledWith('2026-10-26', '2026-12-06')).toBe(true))
  })

  it('shows the twelve-month summary on the year unit and drills into a month', async () => {
    const user = userEvent.setup()
    api.calendar.mockResolvedValue(payload({
      items: YEAR_ITEMS,
      meta: { business_date: BD, total: 3, by_kind: { PTP_DUE: 2, NOTICE: 1 }, by_month: YEAR_MONTHS },
    }))
    renderScreen(<Calendar />)
    await waitFor(() => expect(api.calendar).toHaveBeenCalled())
    await user.click(screen.getByRole('radio', { name: 'ปี' }))
    await waitFor(() => expect(calledWith('2026-01-01', '2026-12-31')).toBe(true))
    expect(screen.getByText('ภาพรวมทั้งปี')).toBeInTheDocument()
    expect(await screen.findByText('มกราคม')).toBeInTheDocument()
    expect(screen.getByText('ธันวาคม')).toBeInTheDocument()

    await user.click(screen.getByRole('radio', { name: 'ปี' }))
    await user.click(screen.getByRole('button', { name: 'มกราคม' }))
    // A month row switches to the month unit anchored on the first of that month.
    await waitFor(() => expect(calledWith('2025-12-29', '2026-02-08')).toBe(true))
    expect(screen.getByRole('radio', { name: 'เดือน' })).toHaveAttribute('aria-checked', 'true')
  })

  it('steps a whole year when the unit is year', async () => {
    const user = userEvent.setup()
    renderScreen(<Calendar />)
    await waitFor(() => expect(api.calendar).toHaveBeenCalled())
    await user.click(screen.getByRole('radio', { name: 'ปี' }))
    await waitFor(() => expect(calledWith('2026-01-01', '2026-12-31')).toBe(true))
    await user.click(screen.getByRole('button', { name: 'ช่วงถัดไป' }))
    await waitFor(() => expect(calledWith('2027-01-01', '2027-12-31')).toBe(true))
  })

  it('returns to today with the วันนี้ button', async () => {
    const user = userEvent.setup()
    renderScreen(<Calendar />)
    await waitFor(() => expect(api.calendar).toHaveBeenCalled())
    await user.click(screen.getByRole('button', { name: 'ช่วงถัดไป' }))
    await waitFor(() => expect(api.calendar.mock.calls.length).toBeGreaterThan(1))
    await user.click(screen.getByRole('button', { name: 'วันนี้' }))
    await waitFor(() => expect(calledWith(OCT_GRID.from, OCT_GRID.to)).toBe(true))
  })

  it('jumps to a date picked in the calendar field', async () => {
    renderScreen(<Calendar />)
    await waitFor(() => expect(api.calendar).toHaveBeenCalled())
    fireEvent.change(screen.getByLabelText('เลือกวันที่'), { target: { value: '2027-03-15' } })
    // The month unit around 2027-03-15: March 1 2027 is a Monday, so the grid opens there.
    await waitFor(() => expect(calledWith('2027-03-01', '2027-04-11')).toBe(true))
  })
})

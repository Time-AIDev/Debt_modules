import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { Calendar } from './Calendar.jsx'

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

const KIND_ORDER = ['PTP_DUE', 'NEXT_ACTION', 'REVIEW_SLA', 'ISSUE_DEADLINE', 'NPL_BUYBACK',
  'RESTRUCTURE', 'SETTLEMENT', 'REMINDER_BATCH', 'NOTICE']

const CAL = {
  items: [
    { uid: 'ptp:1', kind: 'PTP_DUE', source: 'cases.ptp', on: '2026-10-23', display_name: 'ปัทมวรรณ สุขเจริญ', customer_uid: 'c-1', priority: 0, overdue: false, movable: false, facts: {} },
    { uid: 'na:1', kind: 'NEXT_ACTION', source: 'cases.next_action', on: '2026-10-23', display_name: 'สมศรี พงษ์ไพบูลย์', customer_uid: 'c-2', priority: 1, overdue: false, movable: true, facts: { action: 'CALL' } },
  ],
  days: [],
  meta: {
    business_date: '2026-10-23', from: '2026-10-01', to: '2026-10-31', defaulted: false,
    by_kind: { PTP_DUE: 1, NEXT_ACTION: 1 }, kind_order: KIND_ORDER,
  },
}

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
  api.calendar.mockResolvedValue(CAL)
})

describe('the calendar colours (F07)', () => {
  it('gives every chip its kind\u2019s status icon and marks PTP as the most urgent', async () => {
    const { container } = renderScreen(<Calendar />)
    const ptp = await screen.findByRole('button', { name: /นัดชำระ · ปัทมวรรณ/ })
    expect(ptp).toHaveClass('cal__chip--ptp')
    expect(ptp.querySelector('svg.st--do')).not.toBeNull()
    const next = screen.getByRole('button', { name: /งานถัดไป · สมศรี/ })
    expect(next).not.toHaveClass('cal__chip--ptp')
    expect(next.querySelector('svg.st--do')).not.toBeNull()
    // the legend lists the served kinds in the served order, PTP first with its note,
    // each with the icon its chips wear
    const legend = container.querySelector('.cal__legend')
    const entries = legend.querySelectorAll(':scope > span')
    expect(entries).toHaveLength(2)
    expect(entries[0]).toHaveTextContent('นัดชำระ · ด่วนที่สุด')
    expect(entries[0].querySelector('svg.st--do')).not.toBeNull()
    expect(entries[1]).toHaveTextContent('งานถัดไป')
  })

  it('draws an NPL buy-back as a problem, a notice as idle, and says overdue as a problem', async () => {
    api.calendar.mockResolvedValue({
      ...CAL,
      items: [
        { uid: 'npl:1', kind: 'NPL_BUYBACK', on: '2026-10-23', display_name: 'อรุณี ใจสว่าง', customer_uid: 'c-3', overdue: true, movable: false, facts: {} },
        { uid: 'nt:1', kind: 'NOTICE', on: '2026-10-23', display_name: null, customer_uid: null, overdue: false, movable: false, facts: { title: 'ประชุมทีม', notice_uid: 'n-1' } },
      ],
      meta: { ...CAL.meta, by_kind: { NPL_BUYBACK: 1, NOTICE: 1 } },
    })
    const user = userEvent.setup()
    renderScreen(<Calendar />)
    const npl = await screen.findByRole('button', { name: /ซื้อคืน NPV · อรุณี/ })
    expect(npl.querySelector('svg.st--problem')).not.toBeNull()
    expect(screen.getByRole('button', { name: /^บันทึก$/ }).querySelector('svg.st--idle')).not.toBeNull()
    await user.click(screen.getByRole('radio', { name: 'วัน' }))
    const overdue = await screen.findByText('เลยกำหนด')
    expect(overdue.closest('.pill')).toHaveClass('pill--problem')
  })
})

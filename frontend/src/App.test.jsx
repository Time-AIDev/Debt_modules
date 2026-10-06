import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderApp } from './test-utils.jsx'
import App from './App.jsx'

vi.mock('./lib/api.js', () => ({
  api: new Proxy({}, {
    get: (target, prop) => {
      if (!(prop in target)) target[prop] = vi.fn(async () => ({}))
      return target[prop]
    },
  }),
  CHANGED_EVENT: 'volt:changed',
  AUTH_REQUIRED_EVENT: 'volt:auth-required',
}))
const { api } = await import('./lib/api.js')

const SUMMARY = {
  business_date: '2026-10-23',
  workload: { caseload: 212, cap: 240, contact_denominator: 198, bar_pct: 88 },
  badges: { today: 34, book: 212, reviews: 4, pipeline: 7, payments: 3, recovery: 6, settings: 7 },
  kpi: { value: '1284600.00', target: '2060000.00', achieved: '62.4%', period: 'WK-38/2026' },
}

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
  api.shellSummary.mockResolvedValue(SUMMARY)
  api.officers.mockResolvedValue({ officers: [] })
  api.workbook.mockResolvedValue({ rows: [] })
  api.customerSearch.mockResolvedValue({ items: [] })
})

describe('the shell', () => {
  it('redirects legacy termination history with its exact customer filter into Action log', async () => {
    api.terminated.mockResolvedValue({ entries: [], meta: { total: 0, actors: [] } })
    renderApp(<App />, { route: '/terminated?customer_uid=c1' })
    await waitFor(() => expect(api.terminated).toHaveBeenCalledWith({ customer_uid: 'c1' }))
    const rail = screen.getByRole('navigation', { name: 'Volt Debt' })
    expect(rail.querySelector('[title="บันทึกการใช้งาน"]')).toHaveClass('rail__link--on')
    expect(rail.querySelector('[title="สัญญาที่ยุติ"]')).toBeNull()
  })

  it('draws the consolidated rail rows with served badge counts', async () => {
    renderApp(<App />)
    const rail = await screen.findByRole('navigation', { name: 'Volt Debt' })
    for (const label of ['ภาพรวม', 'วันนี้', 'ปฏิทิน', 'ลูกค้า / สมุดงาน', 'รอตรวจ',
      'เงินเข้าและ PEAK', 'NPL และการเรียกคืน', 'รายงาน', 'ตั้งค่า', 'แหล่งข้อมูล', 'บันทึกการใช้งาน']) {
      expect(rail.querySelector(`[title="${label}"]`), label).toBeTruthy()
    }
    expect(rail.querySelector('[title="ใบแจ้งหนี้ก่อนติดตั้ง"]')).toBeNull()
    const today = rail.querySelector('[title="วันนี้"]')
    expect(today.textContent).toContain('34')
    const book = rail.querySelector('[title="ลูกค้า / สมุดงาน"]')
    expect(book.textContent).toContain('212')
  })

  it('redirects the legacy pipeline route into Today pre-install', async () => {
    api.pipeline.mockResolvedValue({ items: [], meta: { total: 0, business_date: '2026-10-23' } })
    api.boardColumns.mockResolvedValue({ columns: [] })
    api.dictionary.mockResolvedValue({ values: [] })
    renderApp(<App />, { route: '/pipeline' })
    const workstream = await screen.findByRole('radiogroup', { name: 'ประเภทงาน' })
    expect(workstream.querySelector('[aria-checked="true"]')).toHaveTextContent('ก่อนติดตั้ง')
    expect(api.pipeline).toHaveBeenCalled()
  })

  it('shows the served KPI strip, not a computed one', async () => {
    renderApp(<App />)
    expect(await screen.findByText('62.4%')).toBeInTheDocument()
    expect(screen.getByText('1,284,600.00 จากเป้า 2,060,000.00')).toBeInTheDocument()
  })

  it('formats the rail cash-in even when no target is configured', async () => {
    api.shellSummary.mockResolvedValue({ ...SUMMARY, kpi: { value: '1509304.80', target: null, achieved: null, week_label: 'WK-40/2026' } })

    renderApp(<App />)

    expect(await screen.findByText('1,509,304.80')).toBeInTheDocument()
    expect(screen.getByText('WK-40/2026')).toBeInTheDocument()
  })

  it('collapses the rail and persists the choice', async () => {
    const user = userEvent.setup()
    renderApp(<App />)
    await user.click(await screen.findByTitle('ย่อแถบนำทาง'))
    expect(window.localStorage.getItem('volt.shell.rail')).toBe('closed')
    expect(screen.queryByText('ปริมาณงาน')).not.toBeInTheDocument()
  })

  it('switches theme from the View popover', async () => {
    const user = userEvent.setup()
    renderApp(<App />)
    await user.click(await screen.findByRole('button', { name: 'มุมมอง' }))
    await user.click(screen.getByRole('radio', { name: 'มืด' }))
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  })

  it('opens the palette with ⌘K and runs a command', async () => {
    const user = userEvent.setup()
    renderApp(<App />)
    fireEvent.keyDown(window, { key: 'k', metaKey: true })
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    const input = screen.getByPlaceholderText('ค้นหาลูกค้า หน้าจอ หรือคำสั่ง…')
    await user.type(input, 'ธีม')
    await user.click(screen.getByText('สลับธีมสว่าง / มืด'))
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('searches customers through the lightweight customer index', async () => {
    api.customerSearch.mockResolvedValue({
      items: [{ customer_uid: 'c-1', display_name: 'ปัทมวรรณ สุขเจริญ', officer: 'รุ่งนภา' }],
    })
    const user = userEvent.setup()
    renderApp(<App />)
    fireEvent.keyDown(window, { key: 'k', metaKey: true })
    const input = await screen.findByPlaceholderText('ค้นหาลูกค้า หน้าจอ หรือคำสั่ง…')
    await user.type(input, 'ปัทม')
    expect(await screen.findByText('ปัทมวรรณ สุขเจริญ')).toBeInTheDocument()
    expect(api.customerSearch).toHaveBeenCalledWith(
      { q: 'ปัทม', limit: 6 },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })
})

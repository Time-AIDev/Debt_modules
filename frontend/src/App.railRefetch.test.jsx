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

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
  api.shellSummary.mockResolvedValue({ badges: {}, workload: {}, kpi: {} })
  api.officers.mockResolvedValue({ officers: [] })
  api.workbook.mockResolvedValue({ rows: [] })
})

// 2026-09-27 staging: every summary is a full-book build on one CPU, and a refetch per
// pathname (each customer page is one) stacked them into 30–51 s bursts.
describe('the rail counts', () => {
  it('are fetched once per write or import, not once per page', async () => {
    const user = userEvent.setup()
    renderApp(<App />)
    const rail = await screen.findByRole('navigation', { name: 'Volt Debt' })
    await waitFor(() => expect(api.shellSummary).toHaveBeenCalledTimes(1))
    await user.click(rail.querySelector('[title="ลูกค้า / สมุดงาน"]'))
    await user.click(rail.querySelector('[title="วันนี้"]'))
    expect(api.shellSummary).toHaveBeenCalledTimes(1)
    fireEvent(window, new CustomEvent('volt:changed'))
    await waitFor(() => expect(api.shellSummary).toHaveBeenCalledTimes(2))
    fireEvent(window, new CustomEvent('volt:data-epoch'))
    await waitFor(() => expect(api.shellSummary).toHaveBeenCalledTimes(3))
  })
})

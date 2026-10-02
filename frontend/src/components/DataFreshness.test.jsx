import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { DataFreshness } from './DataFreshness.jsx'

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

beforeEach(() => vi.clearAllMocks())

const STATE = {
  epoch: 3, seen_epoch: 3, stale: false,
  serving: { serving_name: 'Odoo crm.lead', imported_at: '2026-09-20T10:00:00+07:00' },
  peak_as_of: '2026-09-14',
}

describe('the freshness line', () => {
  it('shows the served source, its import time and the PEAK report date', async () => {
    api.dataState.mockResolvedValue(STATE)
    renderScreen(<DataFreshness />)
    expect(await screen.findByText(/Odoo crm\.lead/)).toBeInTheDocument()
    expect(screen.getByText(/รายงาน PEAK ณ/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'อัปเดตทันที' })).not.toBeInTheDocument()
  })

  it('offers the update action only while the session is behind', async () => {
    api.dataState
      .mockResolvedValueOnce({ ...STATE, stale: true, seen_epoch: 2 })
      .mockResolvedValue({ ...STATE, seen_epoch: 3 })
    api.refreshImports.mockResolvedValue({ refreshed: true, stale: false })
    const user = userEvent.setup()
    renderScreen(<DataFreshness />)

    const stale = await screen.findByText(/ข้อมูลนำเข้าใหม่/)
    expect(stale).toBeInTheDocument()
    expect(stale.querySelector('.st--do')).not.toBeNull()
    await user.click(screen.getByRole('button', { name: 'อัปเดตทันที' }))
    await waitFor(() => expect(api.refreshImports).toHaveBeenCalled())
    await waitFor(() => expect(screen.queryByText(/ข้อมูลนำเข้าใหม่/)).not.toBeInTheDocument())
  })
})

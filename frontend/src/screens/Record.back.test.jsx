import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { renderScreen } from '../test-utils.jsx'
import { Record } from './Record.jsx'
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

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
  api.caseDetail.mockResolvedValue(CASE)
})

describe('the case page back button', () => {
  it('returns to the calendar when the case was opened from it', async () => {
    renderScreen(<Record />, {
      route: { pathname: '/customers/c-1', state: { from: 'calendar', unit: 'week', anchor: '2026-10-05' } },
    })
    const back = await screen.findByRole('link', { name: /ปฏิทิน/ })
    expect(back).toHaveAttribute('href', '/calendar')
    expect(screen.queryByRole('link', { name: /วันนี้/ })).toBeNull()
  })

  it('returns to Today otherwise', async () => {
    renderScreen(<Record />, { route: '/customers/c-1' })
    expect(await screen.findByRole('link', { name: /วันนี้/ })).toHaveAttribute('href', '/')
  })

  it('returns to an internal origin with its exact query, state and scroll position', async () => {
    renderScreen(<Record />, {
      route: {
        pathname: '/customers/c-1',
        state: { origin: {
          to: '/reviews?status=OPEN&tab=npl',
          state: { selected: 'rv-4' },
          label: 'nav.reviews',
          scrollY: 420,
        } },
      },
    })

    const back = await screen.findByRole('link', { name: /รอตรวจ/ })
    expect(back).toHaveAttribute('href', '/reviews?status=OPEN&tab=npl')
  })
})

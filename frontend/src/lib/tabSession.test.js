import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './api.js'

const response = (body, status = 200) => ({ ok: status < 400, status, json: async () => body })

beforeEach(() => { window.sessionStorage.clear(); window.localStorage.clear() })
afterEach(() => vi.restoreAllMocks())

describe('tab credential transport', () => {
  it('persists login only in this tab and attaches the credential to subsequent calls', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(response({ session_policy: 'tab', session_token: 'opaque-tab-token', expires_at: null }))
      .mockResolvedValueOnce(response({ subject: 'user@volt.co.th' }))
    const signedIn = await api.authGoogle({ credential: 'google-proof' })
    expect(signedIn).not.toHaveProperty('session_token')
    expect(window.sessionStorage.getItem('volt.auth.tab')).toBe('opaque-tab-token')
    expect(window.localStorage.getItem('volt.auth.tab')).toBeNull()
    await api.authMe()
    expect(fetch.mock.calls[1][1].headers.Authorization).toBe('Bearer opaque-tab-token')
  })

  it('clears the credential after successful logout', async () => {
    window.sessionStorage.setItem('volt.auth.tab', 'opaque-tab-token')
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response({ signed_out: true }))
    await api.authLogout()
    expect(window.sessionStorage.getItem('volt.auth.tab')).toBeNull()
  })

  it('keeps the credential after a network outage', async () => {
    window.sessionStorage.setItem('volt.auth.tab', 'opaque-tab-token')
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('offline'))
    await expect(api.authMe()).rejects.toThrow('offline')
    expect(window.sessionStorage.getItem('volt.auth.tab')).toBe('opaque-tab-token')
  })

  it('clears revoked credentials on an authoritative 401', async () => {
    window.sessionStorage.setItem('volt.auth.tab', 'opaque-tab-token')
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response({ code: 'auth_required' }, 401))
    await expect(api.authMe()).rejects.toMatchObject({ status: 401 })
    expect(window.sessionStorage.getItem('volt.auth.tab')).toBeNull()
  })
})

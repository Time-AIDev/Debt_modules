import { describe, it, expect, vi, afterEach } from 'vitest'
import { api } from './api.js'

const ok = (body) => ({ ok: true, status: 201, json: async () => body, headers: { get: () => null } })
afterEach(() => vi.restoreAllMocks())

// Defect 1 of the NPL inventory: the body was wrapped twice ({ strategy: { strategy, by } })
// and journey.py open_recovery refused every path choice.
describe('the NPL acts post the bodies their routes read', () => {
  it('opens a recovery with the strategy at the top of the body', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok({ recovery: {} }))
    await api.openRecovery('npl-1', { strategy: 'LEGAL', by: 'u-1' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/npl-cases/npl-1/recovery')
    expect(JSON.parse(init.body)).toEqual({ strategy: 'LEGAL', by: 'u-1' })
  })

  it('records a service decline with the signer unwrapped', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok({ recorded: true }))
    await api.declineService('K-1', { by: 'u-1' })
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ by: 'u-1' })
  })
})

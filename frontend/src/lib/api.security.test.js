import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { webcrypto } from 'node:crypto'

let api
const response = (body, version, status = 200) => ({
  ok: status >= 200 && status < 300, status,
  json: async () => body,
  headers: { get: (name) => name === 'x-volt-state-version' ? String(version) : null },
})

beforeEach(async () => {
  vi.resetModules()
  vi.stubGlobal('crypto', webcrypto)
  window.sessionStorage.clear()
  ;({ api } = await import('./api.js'))
})
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('production write transport', () => {
  it('reuses an idempotency key after a connection failure', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch')
      .mockRejectedValueOnce(new TypeError('connection lost'))
      .mockResolvedValueOnce(response({ case: {} }, 2))
    const payload = { next_action: 'CALL', next_action_on: '2026-10-24' }
    await expect(api.setNextAction('customer', payload)).rejects.toThrow('connection lost')
    await api.setNextAction('customer', payload)
    const first = fetch.mock.calls[0][1].headers['Idempotency-Key']
    expect(first).toBeTruthy()
    expect(fetch.mock.calls[1][1].headers['Idempotency-Key']).toBe(first)
  })

  it('retains the key when a successful body cannot be read', async () => {
    const unreadable = response(null, 2)
    const fetch = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(unreadable)
      .mockResolvedValueOnce(response({ case: {} }, 2))
    const payload = { next_action: 'CALL' }
    await expect(api.setNextAction('customer', payload)).rejects.toMatchObject({ problem: { code: 'malformed_response' } })
    await api.setNextAction('customer', payload)
    expect(fetch.mock.calls[1][1].headers['Idempotency-Key']).toBe(fetch.mock.calls[0][1].headers['Idempotency-Key'])
  })

  it('preserves the version of an open edit across background polling', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(response({ case: {} }, 7))
      .mockResolvedValueOnce(response({}, 9))
      .mockResolvedValueOnce(response({ case: {} }, 10))
    await api.caseDetail('customer')
    await api.dataState({ background: true })
    await api.setNextAction('customer', { next_action: 'CALL' })
    expect(fetch.mock.calls[2][1].headers['If-Match']).toBe('7')
  })

  it('surfaces a stale-write conflict without retrying the edit automatically', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(response({ case: {} }, 7))
      .mockResolvedValueOnce(response({ code: 'state_conflict' }, 9, 409))
    await api.caseDetail('customer')
    await expect(api.setNextAction('customer', { next_action: 'CALL' })).rejects.toMatchObject({ problem: { code: 'state_conflict' } })
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(fetch.mock.calls[1][1].headers['If-Match']).toBe('7')
  })

  it('retains only opaque retry metadata across reload and preserves the original edit version', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(response({ case: {} }, 7))
      .mockRejectedValueOnce(new TypeError('connection lost'))
      .mockResolvedValueOnce(response({ case: {} }, 9))
      .mockResolvedValueOnce(response({ case: {} }, 10))
    const payload = { next_action: 'CALL', note: 'private note: person@example.com', customer_uid: 'customer-private' }
    await api.caseDetail('customer-private')
    await expect(api.setNextAction('customer-private', payload)).rejects.toThrow('connection lost')
    const saved = window.sessionStorage.getItem('volt.pending-operations.v1')
    expect(saved).not.toContain('person@example.com')
    expect(saved).not.toContain('customer-private')
    expect(saved).not.toContain('private note')
    const metadata = JSON.parse(saved)[0]
    expect(metadata.fingerprint).toMatch(/^[a-f0-9]{64}$/)
    expect(Object.keys(metadata).sort()).toEqual(['at', 'expectedVersion', 'fingerprint', 'key'])
    vi.resetModules()
    ;({ api } = await import('./api.js'))
    await api.caseDetail('customer-private')
    await api.setNextAction('customer-private', payload)
    expect(fetch.mock.calls[3][1].headers['Idempotency-Key']).toBe(fetch.mock.calls[1][1].headers['Idempotency-Key'])
    expect(fetch.mock.calls[3][1].headers['If-Match']).toBe('7')
    expect(window.sessionStorage.getItem('volt.pending-operations.v1')).toBeNull()
  })

  it('refuses an expired uncertain operation instead of silently issuing a new key', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('connection lost'))
    const payload = { next_action: 'CALL' }
    await expect(api.setNextAction('customer', payload)).rejects.toThrow('connection lost')
    const now = Date.now()
    vi.spyOn(Date, 'now').mockReturnValue(now + 24 * 60 * 60 * 1000 + 1000)
    await expect(api.setNextAction('customer', payload)).rejects.toMatchObject({ problem: { code: 'operation_outcome_unknown' } })
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('refuses additional commands when the unresolved operation cache is full', async () => {
    const entries = Array.from({ length: 128 }, (_, i) => ({
      fingerprint: i.toString(16).padStart(64, '0'), key: `pending-${i}`, expectedVersion: '1', at: Date.now(),
    }))
    window.sessionStorage.setItem('volt.pending-operations.v1', JSON.stringify(entries))
    vi.resetModules()
    ;({ api } = await import('./api.js'))
    const fetch = vi.spyOn(globalThis, 'fetch')
    await expect(api.setNextAction('new-customer', { next_action: 'CALL' })).rejects.toMatchObject({ problem: { code: 'pending_operations_full' } })
    expect(fetch).not.toHaveBeenCalled()
    expect(JSON.parse(window.sessionStorage.getItem('volt.pending-operations.v1'))).toHaveLength(128)
  })

  it('clears persistent retry metadata when the authenticated session ends', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch')
      .mockRejectedValueOnce(new TypeError('connection lost'))
      .mockResolvedValueOnce(response({ code: 'auth_required' }, 1, 401))
    await expect(api.setNextAction('customer', {})).rejects.toThrow('connection lost')
    expect(window.sessionStorage.getItem('volt.pending-operations.v1')).toBeTruthy()
    await expect(api.officers()).rejects.toMatchObject({ problem: { code: 'auth_required' } })
    expect(window.sessionStorage.getItem('volt.pending-operations.v1')).toBeNull()
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('keeps an uncertain file intake locked for reconciliation when a reload creates new chunks', async () => {
    let starts = 0
    const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async (path, init) => {
      if (String(path).endsWith('/v1/imports:start')) {
        starts += 1
        if (starts === 1) throw new TypeError('connection lost')
        return response({ code: 'idempotency_conflict' }, 4, 409)
      }
      return response({ received: true, discarded: true }, 2)
    })
    const file = new File(['csv contents'], 'private-name.csv', { type: 'text/csv', lastModified: 123 })
    file.arrayBuffer = async () => new TextEncoder().encode('csv contents').buffer
    await expect(api.createImport(file)).rejects.toThrow('connection lost')
    vi.resetModules()
    ;({ api } = await import('./api.js'))
    await expect(api.createImport(file)).rejects.toMatchObject({ problem: { code: 'operation_outcome_unknown' } })
    const startCalls = fetch.mock.calls.filter(([path]) => String(path).endsWith('/v1/imports:start'))
    expect(startCalls[1][1].headers['Idempotency-Key']).toBe(startCalls[0][1].headers['Idempotency-Key'])
    expect(startCalls[1][1].headers['X-Volt-Upload']).not.toBe(startCalls[0][1].headers['X-Volt-Upload'])
    const saved = window.sessionStorage.getItem('volt.pending-operations.v1')
    expect(saved).not.toContain('private-name')
    expect(saved).not.toContain('csv contents')
    expect(JSON.parse(saved)).toHaveLength(1)
  })
})

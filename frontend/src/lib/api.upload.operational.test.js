import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'

const response = (body, version = 80, status = 200) => ({
  ok: status < 400, status, json: async () => body,
  headers: { get: (name) => name.toLowerCase() === 'x-volt-state-version' ? String(version) : null },
})

let api
beforeEach(async () => {
  window.sessionStorage.clear()
  vi.resetModules()
  ;({ api } = await import('./api.js'))
})
afterEach(() => vi.restoreAllMocks())

describe('upload transport with actual production version headers', () => {
  it('does not send a portfolio fence for parts or preview after a worker changes it', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(response({}, 78))
      .mockResolvedValueOnce(response({ received: 1 }, 80))
      .mockResolvedValueOnce(response({ uid: 'preview-one', state: 'queued' }, 80, 202))
      .mockResolvedValueOnce(response({ uid: 'preview-one', state: 'done', result: {
        preview: { uid: 'dimp-one', version: 'digest', review_state_version: '80' },
      } }, 81))
      .mockResolvedValueOnce(response({ received: 1 }, 81))
      .mockResolvedValueOnce(response({ uid: 'receipt-one', state: 'done', run_id: 44, review_state_version: '82' }, 82, 202))
    await api.dataState()
    await api.createImport(new File(['master'], 'master.xlsx'), { profile: 'debt_status' })
    await api.peakReceiptStart(new File(['receipt'], 'receipt.xlsx'))
    for (const [path, init] of fetch.mock.calls) {
      if (init.method === 'POST') expect(init.headers['If-Match'], path).toBeUndefined()
    }
  })

  it('binds apply to the reviewed version even when background polling has a newer head', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(response({}, 99))
      .mockResolvedValueOnce(response({ code: 'preview_stale' }, 99, 409))
    await api.dataState({ background: true })
    await expect(api.peakReceiptApply(44, { review_state_version: '82' }))
      .rejects.toMatchObject({ status: 409, problem: { code: 'preview_stale' } })
    expect(fetch.mock.calls[1][1].headers['If-Match']).toBe('82')
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('replays a lost enqueue reply with the same uploaded bytes and command identity', async () => {
    let submissions = 0
    const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async (path) => {
      if (path.includes('/parts/')) return response({ received: 1 })
      submissions += 1
      if (submissions === 1) throw new TypeError('reply lost after enqueue commit')
      return response({ uid: 'accepted-job', state: 'done', result: { preview: { uid: 'dimp' } } }, 80, 202)
    })
    await api.createImport(new File(['bytes'], 'master.xlsx'), { profile: 'debt_status' })
    const starts = fetch.mock.calls.filter(([path]) => path.includes('/imports:start'))
    expect(starts).toHaveLength(2)
    expect(starts[1][1].headers['X-Volt-Upload']).toBe(starts[0][1].headers['X-Volt-Upload'])
    expect(starts[1][1].headers['Idempotency-Key']).toBe(starts[0][1].headers['Idempotency-Key'])
    expect(fetch.mock.calls.some(([, init]) => init.method === 'DELETE')).toBe(false)
    expect(window.sessionStorage.getItem('volt.pending-operations.v1')).toBeNull()
  })
})

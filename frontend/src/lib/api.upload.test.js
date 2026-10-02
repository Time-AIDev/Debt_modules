import { describe, it, expect, vi, afterEach } from 'vitest'
import { api, PART_BYTES } from './api.js'

const ok = (body) => ({ ok: true, status: 200, json: async () => body, headers: { get: () => null } })
const refused = (body, status = 409) => ({ ok: false, status, json: async () => body, headers: { get: () => null } })
afterEach(() => vi.restoreAllMocks())

describe('a big upload goes up in parts (Cloud Run refuses a body over 32 MiB)', () => {
  it('sends parts, then names them on the upload with no body', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok({ run: {} }))
    const file = new File([new Uint8Array(2 * PART_BYTES + 5)], 'book.xlsx')
    await api.installSheet(file, 3)
    const paths = fetchMock.mock.calls.map(([url]) => url)
    expect(paths.slice(0, 3).every((p) => /\/v1\/imports\/parts\/[0-9a-f-]{36}\/[012]\?of=3$/.test(p))).toBe(true)
    expect(fetchMock.mock.calls[2][1].body.size).toBe(5)
    const [last, init] = fetchMock.mock.calls[3]
    expect(last).toMatch(/\/v1\/imports:start\?install=true&confirm_retire=3$/)
    expect(init.headers['X-Volt-Upload']).toBe(paths[0].match(/parts\/([0-9a-f-]{36})\//)[1])
    expect(init.body).toBe('')
  })

  it('tracks byte progress for small files and attachments through the same chunk door', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok({ run: {} }))
    const progress = vi.fn()
    await api.createImport(new File(['a,b'], 'small.csv'), { onProgress: progress })
    await api.uploadAttachment(new File([new Uint8Array(PART_BYTES + 1)], 'scan.pdf'))
    expect(fetchMock.mock.calls.some(([path]) => String(path).includes('/v1/imports/parts/'))).toBe(true)
    expect(progress).toHaveBeenCalledWith(expect.objectContaining({
      phase: 'uploading', uploadedBytes: 3, totalBytes: 3,
    }))
  })

  it('aborts the request and deletes held chunks when cancelled', async () => {
    const controller = new AbortController()
    let calls = 0
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((path, init) => {
      calls += 1
      if (calls === 1) {
        return new Promise((resolve, reject) => {
          init.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
        })
      }
      return Promise.resolve(ok({ discarded: true }))
    })
    const pending = api.createImport(new File(['abc'], 'book.csv'), { signal: controller.signal })
    controller.abort()

    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
    expect(fetchMock.mock.calls.some(([path, init]) =>
      String(path).includes('/v1/imports/parts/') && init.method === 'DELETE')).toBe(true)
  })

  it('surfaces run_not_cancellable when abort races with an already committed run', async () => {
    const controller = new AbortController()
    vi.spyOn(globalThis, 'fetch').mockImplementation((path, init = {}) => {
      const url = String(path)
      if (url.endsWith('/v1/operation-runs/run-1:cancel')) {
        return Promise.resolve(refused({
          code: 'run_not_cancellable',
          message_th: 'งานนี้บันทึกผลแล้วหรือจบแล้ว จึงยกเลิกไม่ได้',
        }))
      }
      if (url.includes('/v1/imports:start')) {
        return Promise.resolve(ok({ uid: 'run-1', state: 'applying' }))
      }
      if (init.signal?.aborted) {
        return Promise.reject(new DOMException('aborted', 'AbortError'))
      }
      return Promise.resolve(ok({ received: true }))
    })

    const pending = api.createImport(new File(['abc'], 'book.csv'), {
      signal: controller.signal,
      onProgress: (progress) => {
        if (progress.uid === 'run-1') controller.abort()
      },
    })

    await expect(pending).rejects.toMatchObject({
      problem: { code: 'run_not_cancellable' },
    })
  })
})

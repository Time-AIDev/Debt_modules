import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'

vi.mock('./api.js', () => ({ api: { dataState: vi.fn() } }))
const { api } = await import('./api.js')
const { loadDataState, forgetDataState, useDataState } = await import('./dataEpoch.jsx')

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

beforeEach(() => { forgetDataState(); api.dataState.mockReset() })

describe('import publication and client dataflow ordering', () => {
  it('shares one pending read across consumers', async () => {
    const pending = deferred()
    api.dataState.mockReturnValue(pending.promise)
    const first = loadDataState()
    expect(loadDataState()).toBe(first)
    pending.resolve({ epoch: 7 })
    expect(await first).toEqual({ epoch: 7 })
    expect(await loadDataState()).toEqual({ epoch: 7 })
    expect(api.dataState).toHaveBeenCalledTimes(1)
  })

  it('does not let a pre-import response overwrite the newer published state', async () => {
    const old = deferred(), fresh = deferred()
    api.dataState.mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise)
    const before = loadDataState()
    const after = loadDataState({ force: true })
    fresh.resolve({ epoch: 8, serving: 'new-import' })
    await after
    old.resolve({ epoch: 7, serving: 'old-import' })
    await before
    expect(await loadDataState()).toEqual({ epoch: 8, serving: 'new-import' })
  })

  it('does not clear the newer pending request when the older request settles', async () => {
    const old = deferred(), fresh = deferred()
    api.dataState.mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise)
    const before = loadDataState(), after = loadDataState({ force: true })
    old.resolve({ epoch: 7 })
    await before
    expect(loadDataState()).toBe(after)
    expect(api.dataState).toHaveBeenCalledTimes(2)
    fresh.resolve({ epoch: 8 })
    await after
  })

  it('does not resurrect a forgotten session cache from an earlier response', async () => {
    const old = deferred()
    api.dataState.mockReturnValueOnce(old.promise).mockResolvedValueOnce({ epoch: 9 })
    const first = loadDataState()
    forgetDataState()
    old.resolve({ epoch: 7, serving: 'previous-session' })
    await first
    expect(await loadDataState()).toEqual({ epoch: 9 })
    expect(api.dataState).toHaveBeenCalledTimes(2)
  })

  it('publishes only the winning response to mounted consumers', async () => {
    const old = deferred(), fresh = deferred()
    api.dataState.mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise)
    const { result, unmount } = renderHook(() => useDataState())
    const after = loadDataState({ force: true })
    await act(async () => { fresh.resolve({ epoch: 8 }); await after })
    await waitFor(() => expect(result.current).toEqual({ epoch: 8 }))
    await act(async () => { old.resolve({ epoch: 7 }); await old.promise })
    expect(result.current).toEqual({ epoch: 8 })
    unmount()
  })

  it('retains the last measured state when a refresh fails', async () => {
    api.dataState.mockResolvedValueOnce({ epoch: 8 }).mockRejectedValueOnce(new Error('offline'))
    await loadDataState()
    expect(await loadDataState({ force: true })).toEqual({ epoch: 8 })
  })
})

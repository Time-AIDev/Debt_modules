import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook } from '@testing-library/react'

vi.mock('./api.js', () => ({ api: { dataState: vi.fn(async () => ({ epoch: 1 })) } }))
const { api } = await import('./api.js')
const { useDataStatePoll, POLL_MS } = await import('./dataEpoch.jsx')

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  api.dataState.mockClear()
})

// Fix-all F4: an open screen hears of an import within 30 s, not at the next click.
describe('the data-state poll', () => {
  it('asks every 30 s as background, and leaves no timer behind', () => {
    vi.useFakeTimers()
    const { unmount } = renderHook(() => useDataStatePoll())
    vi.advanceTimersByTime(POLL_MS)
    expect(api.dataState).toHaveBeenCalledTimes(1)
    expect(api.dataState).toHaveBeenCalledWith({ background: true })
    unmount()
    expect(vi.getTimerCount()).toBe(0)
    vi.advanceTimersByTime(POLL_MS * 3)
    expect(api.dataState).toHaveBeenCalledTimes(1)
  })

  it('skips its turn while the page is hidden', () => {
    vi.useFakeTimers()
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    const { unmount } = renderHook(() => useDataStatePoll())
    vi.advanceTimersByTime(POLL_MS * 2)
    expect(api.dataState).not.toHaveBeenCalled()
    visibility.mockReturnValue('visible')
    vi.advanceTimersByTime(POLL_MS)
    expect(api.dataState).toHaveBeenCalledTimes(1)
    unmount()
  })
})

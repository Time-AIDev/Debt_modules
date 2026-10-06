import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useCaseDetail } from './useCaseDetail.js'
vi.mock('./api.js', () => ({ api: { caseDetail: vi.fn() } }))
vi.mock('./dataEpoch.jsx', () => ({ useReloadOnEpoch: vi.fn() }))
const { api } = await import('./api.js')
beforeEach(() => vi.clearAllMocks())
it('ignores a slow previous customer response', async () => {
  let finishOld
  api.caseDetail.mockImplementation((uid) => uid === 'old'
    ? new Promise((resolve) => { finishOld = resolve }) : Promise.resolve({ customer: { uid } }))
  const { result, rerender } = renderHook(({ uid }) => useCaseDetail(uid), { initialProps: { uid: 'old' } })
  rerender({ uid: 'new' })
  await waitFor(() => expect(result.current.data?.customer.uid).toBe('new'))
  await act(async () => finishOld({ customer: { uid: 'old' } }))
  expect(result.current.data.customer.uid).toBe('new')
})
it('ignores an older read after a fresh reload and rejects mismatched identities', async () => {
  let finishOld
  api.caseDetail.mockReturnValueOnce(new Promise((resolve) => { finishOld = resolve }))
    .mockResolvedValueOnce({ customer: { uid: 'selected' }, version: 2 })
    .mockResolvedValueOnce({ customer: { uid: 'other' } })
  const { result } = renderHook(() => useCaseDetail('selected'))
  act(() => result.current.load())
  await waitFor(() => expect(result.current.data?.version).toBe(2))
  await act(async () => finishOld({ customer: { uid: 'selected' }, version: 1 }))
  expect(result.current.data.version).toBe(2)
  act(() => result.current.load())
  await waitFor(() => expect(result.current.problem?.code).toBe('case_response_mismatch'))
  expect(result.current.data).toBeNull()
})

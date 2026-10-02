import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { renderScreen } from '../test-utils.jsx'
import { AuthGate } from './AuthGate.jsx'

vi.mock('../lib/api.js', () => ({ api: { authConfig: vi.fn(), authMe: vi.fn() }, AUTH_REQUIRED_EVENT: 'auth-required' }))
vi.mock('../screens/Login.jsx', () => ({ Login: () => <p>login form</p> }))
const { api } = await import('../lib/api.js')

beforeEach(() => vi.resetAllMocks())
describe('session verification', () => {
  it('offers retry without treating a network failure as logout', async () => {
    api.authConfig.mockResolvedValue({ mode: 'on', session_policy: 'tab' })
    api.authMe.mockRejectedValue(new TypeError('offline'))
    renderScreen(<AuthGate><p>business data</p></AuthGate>)
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.queryByText('login form')).toBeNull()
    expect(screen.queryByText('business data')).toBeNull()
  })
})

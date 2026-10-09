import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { Login } from './Login.jsx'

vi.mock('../lib/api.js', () => ({
  api: {
    authPassword: vi.fn(),
    authGoogle: vi.fn(),
    authConfig: vi.fn(),
  },
  AUTH_REQUIRED_EVENT: 'volt:auth-required',
}))
vi.mock('../lib/googleScript.js', () => ({ loadGoogleScript: vi.fn() }))
const { api } = await import('../lib/api.js')
const { loadGoogleScript } = await import('../lib/googleScript.js')

beforeEach(() => {
  vi.clearAllMocks()
  loadGoogleScript.mockResolvedValue(null)
})

describe('login', () => {
  it('renders Google’s own button and posts the credential it returns', async () => {
    const initialize = vi.fn()
    const renderButton = vi.fn()
    loadGoogleScript.mockResolvedValue({ accounts: { id: { initialize, renderButton } } })
    api.authGoogle.mockResolvedValue({ role: 'MANAGER', officer: 'settasak', can_switch: false })
    const onSignedIn = vi.fn()
    renderScreen(<Login config={{ mode: 'on', google_client_id: 'client-1', environment: 'staging' }} onSignedIn={onSignedIn} />)

    await waitFor(() => expect(renderButton).toHaveBeenCalled())
    const initOptions = initialize.mock.calls[0][0]
    expect(initOptions.client_id).toBe('client-1')
    expect(initOptions.use_fedcm_for_prompt).toBe(true)
    expect(renderButton.mock.calls[0][1].width).toBe(348)

    // What Google calls after a choice, and what it calls when it cannot open.
    await initOptions.callback({ credential: 'jwt-token' })
    expect(api.authGoogle).toHaveBeenCalledWith({ credential: 'jwt-token' })
    expect(onSignedIn).toHaveBeenCalled()

    initOptions.error_callback({ type: 'network_error' })
    expect(await screen.findByText(/เบราว์เซอร์นี้เปิดหน้าต่าง Google ไม่ได้/)).toBeInTheDocument()
  })

  it('posts the test account and hands the session up', async () => {
    api.authPassword.mockResolvedValue({ role: 'OFFICER', officer: 'u-1', can_switch: true })
    const onSignedIn = vi.fn()
    const user = userEvent.setup()
    renderScreen(<Login config={{ mode: 'on', google_client_id: null, environment: 'staging' }} onSignedIn={onSignedIn} />)
    await user.type(screen.getByPlaceholderText('ชื่อผู้ใช้'), 'tester')
    await user.type(screen.getByPlaceholderText('รหัสผ่าน'), 'secret')
    await user.click(screen.getByRole('button', { name: 'เข้าสู่ระบบ' }))
    expect(api.authPassword).toHaveBeenCalledWith({ username: 'tester', password: 'secret' })
    expect(onSignedIn).toHaveBeenCalledWith(expect.objectContaining({ officer: 'u-1' }))
  })

  it('renders the served refusal sentence and stays on the form', async () => {
    api.authPassword.mockRejectedValue({
      status: 401,
      problem: { code: 'login_failed', title: 'Login failed', message_th: 'ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง', errors: [], extensions: {} },
    })
    const onSignedIn = vi.fn()
    const user = userEvent.setup()
    renderScreen(<Login config={{ mode: 'on', environment: 'staging' }} onSignedIn={onSignedIn} />)
    await user.type(screen.getByPlaceholderText('ชื่อผู้ใช้'), 'tester')
    await user.type(screen.getByPlaceholderText('รหัสผ่าน'), 'wrong')
    await user.click(screen.getByRole('button', { name: 'เข้าสู่ระบบ' }))
    expect(await screen.findByText('ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง')).toBeInTheDocument()
    expect(onSignedIn).not.toHaveBeenCalled()
  })
})

describe('login · test-accounts-only estate', () => {
  it('offers no Google button and no divider when no client id is served', () => {
    renderScreen(<Login config={{ mode: 'on', google_client_id: null, environment: 'staging' }} onSignedIn={() => {}} />)
    // 2026-09-21: staging has no origin for its Google client, so the estate signs in
    // with role accounts only — a Google button there could only fail.
    expect(screen.queryByText('เข้าสู่ระบบด้วย Google')).toBeNull()
    expect(screen.queryByText(/หรือ/)).toBeNull()
    expect(screen.getByText('บัญชีทดสอบ')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'เข้าสู่ระบบ' })).toBeInTheDocument()
  })

  it('keeps the section outside production, whatever password_enabled says', () => {
    // Only the production version drops it: staging serves password_enabled false
    // today and still draws the design it was drawn with.
    renderScreen(<Login config={{ mode: 'on', google_client_id: 'client-1', environment: 'staging', password_enabled: false }} onSignedIn={() => {}} />)
    expect(screen.getByText('บัญชีทดสอบ')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('ชื่อผู้ใช้')).toBeInTheDocument()
    expect(screen.getByText(/หรือ/)).toBeInTheDocument()
  })
})

describe('login · production', () => {
  const production = { mode: 'on', google_client_id: 'client-1', environment: 'production' }

  it('renders Google alone — no eyebrow, no fields, no note, no divider', async () => {
    const renderButton = vi.fn()
    loadGoogleScript.mockResolvedValue({ accounts: { id: { initialize: vi.fn(), renderButton } } })
    renderScreen(<Login config={production} onSignedIn={() => {}} />)

    await waitFor(() => expect(renderButton).toHaveBeenCalled())
    expect(screen.queryByText('บัญชีทดสอบ')).toBeNull()
    expect(screen.queryByPlaceholderText('ชื่อผู้ใช้')).toBeNull()
    expect(screen.queryByPlaceholderText('รหัสผ่าน')).toBeNull()
    expect(screen.queryByRole('button', { name: 'เข้าสู่ระบบ' })).toBeNull()
    expect(screen.queryByText(/หรือ/)).toBeNull()
  })

  it('does not send the signer to a test account that is not there', async () => {
    let initOptions
    loadGoogleScript.mockResolvedValue({
      accounts: { id: { initialize: (options) => { initOptions = options }, renderButton: vi.fn() } },
    })
    renderScreen(<Login config={production} onSignedIn={() => {}} />)
    await waitFor(() => expect(initOptions).toBeTruthy())

    initOptions.error_callback({ type: 'network_error' })
    expect(await screen.findByText('เบราว์เซอร์นี้เปิดหน้าต่าง Google ไม่ได้')).toBeInTheDocument()
    expect(screen.queryByText(/บัญชีทดสอบ/)).toBeNull()
  })
})

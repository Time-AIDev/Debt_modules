import { useCallback, useEffect, useRef, useState } from 'react'
import { api, AUTH_REQUIRED_EVENT } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { setSession } from '../lib/identity.jsx'
import { Login } from '../screens/Login.jsx'

/**
 * Login is on only when the server says so. Off — or an older API with no
 * /v1/auth/config (404) — renders the app as before. Any other failure is a check
 * that did not happen: it offers retry and never opens the app on a guess.
 */
export function AuthGate({ children }) {
  const { t } = usePrefs()
  const [phase, setPhase] = useState('checking')
  const [config, setConfig] = useState(null)
  const loaded = useRef(false)

  const check = useCallback(async () => {
    setPhase('checking')
    let served
    try {
      served = await api.authConfig()
    } catch (error) {
      setSession(null)
      setPhase(error?.status === 404 ? 'open' : 'failed')
      return
    }
    loaded.current = true
    setConfig(served)
    if (!served || served.mode !== 'on') { setSession(null); setPhase('open'); return }
    try {
      setSession(await api.authMe())
      setPhase('in')
    } catch (error) {
      setSession(null)
      setPhase(error?.status === 401 ? 'login' : 'failed')
    }
  }, [])

  useEffect(() => { check() }, [check])

  useEffect(() => {
    const onRequired = () => {
      setSession(null)
      if (!loaded.current) { check(); return }
      setPhase('login')
    }
    window.addEventListener(AUTH_REQUIRED_EVENT, onRequired)
    return () => window.removeEventListener(AUTH_REQUIRED_EVENT, onRequired)
  }, [check])

  if (phase === 'checking') return <p className="login__checking" role="status">{t('auth.checking')}</p>
  if (phase === 'failed') {
    return (
      <div className="login__checking">
        <p role="alert">{t('auth.configFailed')}</p>
        <button type="button" className="btn btn--primary" onClick={check}>{t('auth.retry')}</button>
      </div>
    )
  }
  if (phase === 'login') {
    return <Login config={config} onSignedIn={(me) => { setSession(me); setPhase('in') }} />
  }
  return children
}

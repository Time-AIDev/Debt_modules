import { useEffect, useRef, useState } from 'react'
import logo from '../assets/volt-logo-lockup.png'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { Problem } from '../components/Problem.jsx'
import { loadGoogleScript } from '../lib/googleScript.js'

/**
 * The design's login card: Google first, then the test account.
 *
 * Google is rendered by Google itself (accounts.id.renderButton), not by a scripted
 * prompt(): One Tap's prompt() is silently skipped whenever FedCM or cookie rules
 * decide to, and a button that does nothing on click is worse than no button. The
 * rendered button opens the account chooser every time, and error_callback turns a
 * refusal into the same Problem the server's refusals render. The hand-built button
 * stays only as the fallback when there is nothing to render (no client id, or the
 * script could not load).
 */
export function Login({ config, onSignedIn }) {
  const { t, lang } = usePrefs()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState(null)
  const googleRef = useRef(null)
  // Google appends its iframe into the host div and nothing else may touch that DOM:
  // React removing a child it rendered there is the removeChild crash, so the host
  // is empty in every React render and the fallback button lives outside it.
  const renderedFor = useRef(null)
  // The parent re-creates onSignedIn every render; a ref keeps the effect's
  // dependency list to the client id and the language, so its first run is not
  // cancelled by the render that immediately follows it.
  const onSignedInRef = useRef(onSignedIn)
  onSignedInRef.current = onSignedIn

  useEffect(() => {
    const clientId = config?.google_client_id
    if (!clientId || !googleRef.current) return undefined
    const stamp = `${clientId}|${lang}`
    if (renderedFor.current === stamp) return undefined
    renderedFor.current = stamp
    loadGoogleScript().then((googleApi) => {
      if (!googleApi?.accounts?.id || !googleRef.current) return
      googleApi.accounts.id.initialize({
        client_id: clientId,
        callback: async (response) => {
          setProblem(null)
          try {
            onSignedInRef.current(await api.authGoogle({ credential: response.credential }))
          } catch (error) {
            setProblem(error?.problem || { code: 'google_token_invalid' })
          }
        },
        error_callback: (error) => {
          setProblem({
            code: 'google_unavailable',
            message_th: t('login.googleFailed'),
            message_en: t('login.googleFailed'),
            detail: error?.type || undefined,
            errors: [],
            extensions: {},
          })
        },
        use_fedcm_for_prompt: true,
        auto_select: false,
        cancel_on_tap_outside: true,
      })
      googleApi.accounts.id.renderButton(googleRef.current, {
        type: 'standard',
        theme: 'outline',
        size: 'large',
        shape: 'rectangular',
        logo_alignment: 'left',
        text: 'continue_with',
        locale: lang === 'en' ? 'en' : 'th',
        width: 348,
      })
    }).catch(() => {
      renderedFor.current = null
      setProblem({
        code: 'google_unavailable',
        message_th: t('login.googleFailed'),
        message_en: t('login.googleFailed'),
        errors: [],
        extensions: {},
      })
    })
    return undefined
  }, [config?.google_client_id, lang])

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setProblem(null)
    try {
      onSignedIn(await api.authPassword({ username, password }))
    } catch (error) {
      setProblem(error?.problem || { code: 'login_failed', title: t('login.signIn') })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <section className="login__card">
        <img src={logo} alt="VOLT" className="login__logo" />
        <div className="login__intro">
          <h1>{t('login.title')}</h1>
          <p>{t('login.sub')}</p>
        </div>
        {/* No client id, no Google: a deployed estate with test accounts only must not
            offer a button that can only fail. The "or" divider goes with it — there is
            nothing to divide from. (2026-09-21: staging's Google client had no origin
            for the run.app URL, so the fallback button was a dead end.) */}
        {config?.google_client_id ? (
          <>
            <div className="login__googleHost" ref={googleRef} />
            <div className="login__or">
              <span /><span className="login__orLabel">{t('login.or')}</span><span />
            </div>
          </>
        ) : null}
        <form className="login__form" onSubmit={submit}>
          <p className="login__eyebrow">{t('login.testAccount')}</p>
          <label className="sr-only" htmlFor="login-user">{t('login.username')}</label>
          <input id="login-user" className="field" autoComplete="username" required aria-required="true"
                 placeholder={t('login.username')} value={username}
                 onChange={(e) => setUsername(e.target.value)} />
          <label className="sr-only" htmlFor="login-pass">{t('login.password')}</label>
          <input id="login-pass" className="field" type="password" autoComplete="current-password" required aria-required="true"
                 placeholder={t('login.password')} value={password}
                 onChange={(e) => setPassword(e.target.value)} />
          <button type="submit" className="btn btn--primary" disabled={busy || !username || !password}>
            {t('login.signIn')}
          </button>
          <p className="login__note">{t('login.testNote')}</p>
        </form>
        {problem ? <Problem problem={problem} /> : null}
      </section>
    </div>
  )
}

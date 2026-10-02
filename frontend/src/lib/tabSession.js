const KEY = 'volt.auth.tab'

export function tabToken() {
  try { return window.sessionStorage.getItem(KEY) } catch { return null }
}

export function clearTabToken() {
  try { window.sessionStorage.removeItem(KEY) } catch { /* unavailable storage */ }
}

export function acceptLogin(body) {
  if (body?.session_policy !== 'tab') return body
  if (!body.session_token) throw new Error('Missing tab credential')
  // A tab that cannot persist its credential cannot promise reload continuity.
  // Refuse the login instead of silently storing a long-lived credential elsewhere.
  window.sessionStorage.setItem(KEY, body.session_token)
  const { session_token, ...identity } = body
  return identity
}

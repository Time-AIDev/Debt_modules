// Google Identity Services, loaded once and only by the login screen.
const SRC = 'https://accounts.google.com/gsi/client'
let pending = null

export function loadGoogleScript() {
  if (typeof window === 'undefined' || typeof document === 'undefined') return Promise.resolve(null)
  if (window.google?.accounts?.id) return Promise.resolve(window.google)
  if (!pending) {
    pending = new Promise((resolve, reject) => {
      const script = document.createElement('script')
      script.src = SRC
      script.async = true
      script.onload = () => resolve(window.google || null)
      script.onerror = () => { pending = null; reject(new Error('google identity script failed to load')) }
      document.head.appendChild(script)
    })
  }
  return pending
}

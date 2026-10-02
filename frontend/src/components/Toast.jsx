import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'

const ToastContext = createContext(null)

export function ToastProvider({ children }) {
  const [message, setMessage] = useState(null)
  const timer = useRef(null)

  const say = useCallback((text) => {
    setMessage(text)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => setMessage(null), 4200)
  }, [])

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])

  const value = useMemo(() => ({ say }), [say])

  return (
    <ToastContext.Provider value={value}>
      {children}
      {message ? (
        <div className="toast" role="status" aria-live="polite">
          <span className="toast__dot" aria-hidden="true" />
          <span>{message}</span>
        </div>
      ) : null}
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast outside ToastProvider')
  return ctx.say
}

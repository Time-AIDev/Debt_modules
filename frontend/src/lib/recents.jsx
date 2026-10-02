import { createContext, useCallback, useContext, useMemo, useState } from 'react'

const RecentsContext = createContext({ items: [], remember: () => {}, forget: () => {} })

/** Up to four recently opened records, newest first; the context tab strip reads it. */
export function RecentsProvider({ children }) {
  const [items, setItems] = useState([])
  const remember = useCallback((entry) => {
    setItems((prev) => [entry, ...prev.filter((e) => e.key !== entry.key)].slice(0, 4))
  }, [])
  // F13 / TASK-017: closing a tab drops it from the list — never a navigation.
  const forget = useCallback((key) => {
    setItems((prev) => prev.filter((e) => e.key !== key))
  }, [])
  const value = useMemo(() => ({ items, remember, forget }), [items, remember, forget])
  return <RecentsContext.Provider value={value}>{children}</RecentsContext.Provider>
}

export function useRecents() {
  return useContext(RecentsContext)
}

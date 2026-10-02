import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

const CrumbContext = createContext(null)

export function CrumbProvider({ children }) {
  const [crumb, setCrumb] = useState({ group: 'group.mine', page: 'nav.today' })
  const value = useMemo(() => ({ crumb, setCrumb }), [crumb])
  return <CrumbContext.Provider value={value}>{children}</CrumbContext.Provider>
}

export function useCrumbContext() {
  const ctx = useContext(CrumbContext)
  if (!ctx) throw new Error('useCrumbContext outside CrumbProvider')
  return ctx
}

/** A screen declares its breadcrumb; keys are translated by the Topbar. */
export function useCrumb(groupKey, pageKey, pageLabel, parent) {
  const { setCrumb } = useCrumbContext()
  const apply = useCallback(() => setCrumb({ group: groupKey, page: pageKey, pageLabel, parent }), [setCrumb, groupKey, pageKey, pageLabel, parent])
  useEffect(() => { apply() }, [apply])
}

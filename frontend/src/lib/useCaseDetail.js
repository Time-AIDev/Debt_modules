import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import { useReloadOnEpoch } from './dataEpoch.jsx'

/** One customer's case detail — loaded on mount and when uid changes, reloaded when the import epoch moves. */
export function useCaseDetail(uid) {
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState(null)

  const load = useCallback(() => {
    setProblem(null)
    api.caseDetail(uid)
      .then(setData)
      .catch((e) => setProblem(e?.problem || { code: 'request_failed' }))
  }, [uid])

  useEffect(() => { load() }, [load])
  useReloadOnEpoch(load)

  return { data, problem, load }
}

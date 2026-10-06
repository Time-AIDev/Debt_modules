import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { useReloadOnEpoch } from './dataEpoch.jsx'

/** One customer's case detail — loaded on mount and when uid changes, reloaded when the import epoch moves. */
export function useCaseDetail(uid) {
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState(null)
  const requestVersion = useRef(0)

  const load = useCallback(() => {
    const version = ++requestVersion.current
    setProblem(null)
    if (!uid) return
    api.caseDetail(uid)
      .then((next) => {
        if (version !== requestVersion.current) return
        if (next?.customer?.uid !== uid) throw { problem: { code: 'case_response_mismatch', message_th: 'ข้อมูลเคสไม่ตรงกับลูกค้าที่เลือก กรุณาโหลดใหม่' } }
        setData(next)
      })
      .catch((e) => {
        if (version !== requestVersion.current) return
        if (e?.problem?.code === 'case_response_mismatch') setData(null)
        setProblem(e?.problem || { code: 'request_failed' })
      })
  }, [uid])

  useEffect(() => { load(); return () => { requestVersion.current += 1 } }, [load])
  useReloadOnEpoch(load)

  return { data: data?.customer?.uid === uid ? data : null, problem, load }
}

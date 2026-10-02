import { useEffect, useState } from 'react'
import { api } from './api.js'

const cache = new Map()

/** One dictionary read per name per session; served labels, never a client table. */
export function useDictionary(name) {
  const [values, setValues] = useState(() => cache.get(name) || null)
  useEffect(() => {
    if (!name) return undefined
    if (cache.has(name)) { setValues(cache.get(name)); return undefined }
    let alive = true
    api.dictionary(name).then((d) => {
      const v = d?.values || []
      cache.set(name, v)
      if (alive) setValues(v)
    }).catch(() => { if (alive) setValues([]) })
    return () => { alive = false }
  }, [name])
  return values || []
}

export function labelFor(values, code, lang) {
  const hit = (values || []).find((v) => v.code === code)
  if (!hit) return code || '—'
  return (lang === 'en' ? hit.label_en : hit.label_th) || hit.label || code
}

export function active(values) {
  return (values || []).filter((v) => v.active !== false)
}

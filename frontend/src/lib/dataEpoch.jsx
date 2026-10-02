// The import epoch on the client: one shared data-state read, and a counter that
// moves when the server says the imported facts changed (X-Volt-Data-Epoch) or when
// someone pressed the freshness banner's own refresh.
//
// 2026-09-20: the hook and the banner each fetched /v1/data-state, so opening Today
// or Pipeline cost two identical requests (each ~225 ms server-side before the
// summary cache). They now share one fetch, one cache and one event subscription.
import { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { DATA_EPOCH_EVENT, IMPORT_REFRESHED_EVENT } from './events.js'

let cached = null
let inflight = null
const subscribers = new Set()

function publish(value) {
  subscribers.forEach((fn) => fn(value))
}

/** The shared /v1/data-state read: cached until an event forces a re-read. */
export function loadDataState({ force = false, background = false } = {}) {
  if (!force) {
    if (inflight) return inflight
    if (cached) return Promise.resolve(cached)
  }
  inflight = api.dataState({ background })
    .then((value) => { cached = value || null; publish(cached); return cached })
    .catch(() => cached)
    .finally(() => { inflight = null })
  return inflight
}

export function forgetDataState() {
  cached = null
  inflight = null
}

if (typeof window !== 'undefined') {
  const refresh = () => { loadDataState({ force: true }) }
  window.addEventListener(DATA_EPOCH_EVENT, refresh)
  window.addEventListener(IMPORT_REFRESHED_EVENT, refresh)
}

/** The shared state, for components that render it (the freshness banner). */
export function useDataState() {
  const [state, setState] = useState(cached)
  useEffect(() => {
    let alive = true
    const on = (value) => { if (alive) setState(value) }
    subscribers.add(on)
    loadDataState().then((value) => { if (alive) setState(value) })
    return () => { alive = false; subscribers.delete(on) }
  }, [])
  return state
}

/** A counter that moves when the imported facts moved after this screen mounted. */
export function useDataEpoch() {
  const [version, setVersion] = useState(0)
  const seeded = useRef(false)
  useEffect(() => {
    let alive = true
    loadDataState().finally(() => { if (alive) seeded.current = true })
    const bump = () => {
      if (!seeded.current) { seeded.current = true; return }
      setVersion((n) => n + 1)
    }
    window.addEventListener(DATA_EPOCH_EVENT, bump)
    window.addEventListener(IMPORT_REFRESHED_EVENT, bump)
    return () => {
      alive = false
      window.removeEventListener(DATA_EPOCH_EVENT, bump)
      window.removeEventListener(IMPORT_REFRESHED_EVENT, bump)
    }
  }, [])
  return version
}

/** Call `reload` when the data version moved after this screen mounted. */
export function useReloadOnEpoch(reload) {
  const version = useDataEpoch()
  const first = useRef(version)
  const callback = useRef(reload)
  callback.current = reload
  useEffect(() => {
    if (version === first.current) return
    first.current = version
    callback.current?.()
  }, [version])
  return version
}

/** Fix-all F4: while the page is visible, ask every 30 s whether the imported facts
 * moved. The answer's epoch header fires DATA_EPOCH_EVENT (api.js), so an open screen
 * refetches at once instead of at the next click. Sent as background, so the poll
 * never keeps an idle session signed in. */
export const POLL_MS = 30 * 1000

export function useDataStatePoll() {
  useEffect(() => {
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') loadDataState({ force: true, background: true })
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [])
}

export async function refreshImports() {
  const result = await api.refreshImports()
  window.dispatchEvent(new window.CustomEvent(IMPORT_REFRESHED_EVENT, { detail: result }))
  return result
}

// Every figure the interface renders is computed server-side. REQ-COL-027 and
// Data_Model §7.8 both say it plainly: "No arithmetic is performed in the API layer
// or the interface." If a number is missing from a response, the fix is in the API,
// never a calculation here.
const BASE = '/api'

// API Surface v2.3 §0 — the session role travels on every request in place of SSO.
// readRole is synchronous and storage-guarded (components/role.jsx).
// X-Volt-Officer names the acting person (round-1: an act was signed with a demo
// name because no screen knew who was working).
import { readRole, readOfficer } from './identity.jsx'
import { acceptLogin, clearTabToken, tabToken } from './tabSession.js'

// Fix-all F4: the 30-minute idle sign-out (SEC-002) counts a person's work, not the
// screen's own refreshes. The 30 s data poll, and any request sent when nobody has
// touched the page for a minute (the refetches a new data epoch sets off), carry
// X-Volt-Background, and the server does not move the idle clock for them.
export const QUIET_AFTER_MS = 60 * 1000
let lastInput = Date.now()
if (typeof window !== 'undefined') {
  ['pointerdown', 'keydown', 'click'].forEach((type) => {
    window.addEventListener(type, () => { lastInput = Date.now() }, true)
  })
}

function roleHeaders(background = false) {
  try {
    const headers = { 'X-Volt-Role': readRole(), 'X-Volt-Officer': readOfficer() }
    const token = tabToken()
    if (token) headers.Authorization = `Bearer ${token}`
    if (background || Date.now() - lastInput > QUIET_AFTER_MS) headers['X-Volt-Background'] = '1'
    return headers
  } catch { return {} }
}

// A 200 must carry the JSON object its callers read keys off. `response.json()`
// rejects on an empty or truncated body — live, that is what
// ERR_CONTENT_LENGTH_MISMATCH produces — and this used to resolve `null`, so
// Today threw on `null.items` and App on `null.meta`, unmounting the tree. The
// body is now read in ONE place: a malformed 200 becomes the same RFC 9457
// Problem a refusal already carries (`fromError`/`<Problem>`), so every screen's
// existing catch renders its own error state instead of crashing. A 200 body
// that parses to null (or any scalar) is malformed by the same rule. `problem`
// on a refusal is never null either: a non-JSON error body gets the same
// fallback the CSV exports below already use.
export const MALFORMED_BODY = {
  code: 'malformed_response',
  title: 'The server sent a body this screen cannot read',
  detail: 'The response was not valid JSON — an empty or truncated body.',
  message_th: 'อ่านข้อมูลจากเซิร์ฟเวอร์ไม่ได้ (คำตอบว่างหรือถูกตัดขาด) กรุณาลองใหม่อีกครั้ง',
  errors: [],
  extensions: {},
}

async function readJson(response, path) {
  noteEpoch(response)
  let body = null
  try { body = await response.json() } catch { body = null }
  if (response.ok) {
    if (body === null || typeof body !== 'object') {
      throw Object.assign(new Error(path), {
        problem: { ...MALFORMED_BODY, status: response.status },
        status: response.status,
      })
    }
    noteState(response, path)
    finishMutation(response)
    return body
  }
  finishMutation(response, body)
  signalAuth(response.status, body)
  if (body?.code === 'idempotency_conflict') {
    throw pendingProblem('operation_outcome_unknown', 'คำขอนี้มีรายการก่อนหน้าที่อาจบันทึกแล้ว กรุณาตรวจสอบผลในระบบก่อนส่งใหม่')
  }
  throw Object.assign(new Error(path), {
    problem: body || { code: 'request_failed', title: `HTTP ${response.status}`, status: response.status },
    status: response.status,
  })
}

async function get(path, params, { background = false, signal } = {}) {
  const url = new URL(BASE + path, window.location.origin)
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v)
  })
  const headers = roleHeaders(background)
  const response = await fetch(url, { headers, signal })
  if (headers['X-Volt-Background']) backgroundResponses.add(response)
  return readJson(response, path)
}

// UAT round-2 (J-21 / J-45): the rail counts went stale after an act on a screen
// that did not navigate. Every non-GET success announces itself on the window so
// App.jsx can refetch the counts — a tiny event bus, no store.
// 2026-09-20 sync audit: the server stamps every response with the import epoch.
// When it differs from what THIS tab last saw (another browser applied a PEAK
// report, a pull landed), the open screens refetch through useReloadOnEpoch.
export { CHANGED_EVENT, AUTH_REQUIRED_EVENT, DATA_EPOCH_EVENT, IMPORT_REFRESHED_EVENT } from './events.js'
import { CHANGED_EVENT, AUTH_REQUIRED_EVENT, DATA_EPOCH_EVENT } from './events.js'

export function notifyChanged(path, method) {
  try {
    if (typeof window !== 'undefined' && typeof window.CustomEvent === 'function') {
      window.dispatchEvent(new window.CustomEvent(CHANGED_EVENT, { detail: { path, method } }))
    }
  } catch { /* the act still succeeded; only the rail is late */ }
}

let seenEpoch = null
function noteEpoch(response) {
  let raw = null
  try { raw = response.headers && response.headers.get && response.headers.get('x-volt-data-epoch') } catch { raw = null }
  const epoch = raw === null || raw === undefined || raw === '' ? null : Number(raw)
  if (epoch === null || Number.isNaN(epoch) || epoch <= 0) return
  if (seenEpoch === null) { seenEpoch = epoch; return }
  if (epoch === seenEpoch) return
  seenEpoch = epoch
  try {
    if (typeof window !== 'undefined' && typeof window.CustomEvent === 'function') {
      window.dispatchEvent(new window.CustomEvent(DATA_EPOCH_EVENT, { detail: { epoch } }))
    }
  } catch { /* the next mount still reads fresh */ }
}

// Login (design 2026-09-13): a 401 auth_required means the session ended (idle, 8 h,
// signed out elsewhere). AuthGate listens and shows the login screen in place, so
// the URL, and the page the person was on, survives. Only that code: a wrong
// password is also a 401, and must stay on the login form.
// AUTH_REQUIRED_EVENT is re-exported from ./events.js above — declaring it here too
// is a duplicate export and the browser refuses the whole module (blank page).
function signalAuth(status, body) {
  if (status !== 401 || !body || !['auth_required', 'reauth_required'].includes(body.code)) return
  clearTabToken()
  clearPendingMutations()
  resourceVersions.clear()
  caseVersions.clear()
  seenStateVersion = null
  try {
    if (typeof window !== 'undefined' && typeof window.CustomEvent === 'function') {
      window.dispatchEvent(new window.CustomEvent(AUTH_REQUIRED_EVENT))
    }
  } catch { /* the screen still shows the problem */ }
}

// An uncertain network outcome keeps its key for a user's retry. Known refusals
// clear it; malformed successful JSON also retains it until a readable replay.
const PENDING_KEY = 'volt.pending-operations.v1'
const PENDING_TTL_MS = 24 * 60 * 60 * 1000
const PENDING_MAX_ENTRIES = 128
const PENDING_MAX_BYTES = 64 * 1024
const pendingMutations = new Map()
let pendingStorageCorrupt = false
restorePendingMutations()
const responseMutations = new WeakMap()
const backgroundResponses = new WeakSet()
const resourceVersions = new Map()
const caseVersions = new Map()
let seenStateVersion = null

function resourceKey(path) {
  const clean = path.split('?')[0]
  const customer = /^\/v1\/(?:cases\/by-customer|customers)\/([^/:]+)/.exec(clean)
  if (customer) return `customer:${customer[1]}`
  const record = /^\/v1\/([^/]+)\/([^/:]+)/.exec(clean)
  return record ? `${record[1]}:${record[2]}` : clean.split(':')[0]
}

function noteState(response, path) {
  const scope = /^\/v1\/cases\/by-customer\/([^/]+)/.exec(path)
  const token = response.headers?.get?.('x-volt-case-version')
  if (scope && typeof token === 'string' && token.startsWith(`case:${decodeURIComponent(scope[1])}:`)
      && /^case:[A-Za-z0-9_.:-]{1,200}:\d{1,20}$/.test(token)
      && response.ok && !backgroundResponses.has(response)) {
    caseVersions.set(decodeURIComponent(scope[1]), token)
  } else if (scope && /^\/v1\/cases\/by-customer\/[^/]+$/.test(path.split('?')[0])
      && response.ok && !backgroundResponses.has(response)) {
    // A successful fallback read has numeric versions; do not reuse an opaque
    // token issued before customer scopes were disabled.
    caseVersions.delete(decodeURIComponent(scope[1]))
  }
  const raw = response.headers?.get?.('x-volt-state-version')
  if (!/^\d+$/.test(String(raw))) return
  const version = String(raw)
  if (seenStateVersion === null || BigInt(version) > BigInt(seenStateVersion)) seenStateVersion = version
  // Background polling may announce new data, but must not make an open edit
  // silently claim it was based on that unseen newer version.
  if (response.ok && !backgroundResponses.has(response)) resourceVersions.set(resourceKey(path), version)
}

function pendingProblem(code, message) {
  return Object.assign(new Error(code), {
    status: 409,
    problem: { code, status: 409, title: 'Confirm the previous operation first',
      detail: 'An earlier result is uncertain. Check the saved records before submitting a new operation.',
      message_th: message, retryable: false },
  })
}

function restorePendingMutations() {
  let raw = null
  try { raw = window.sessionStorage.getItem(PENDING_KEY) } catch { return }
  if (!raw) return
  try {
    if (raw.length > PENDING_MAX_BYTES) throw new Error('size')
    const entries = JSON.parse(raw)
    if (!Array.isArray(entries) || entries.length > PENDING_MAX_ENTRIES) throw new Error('entries')
    for (const entry of entries) {
      if (!entry || !/^[a-f0-9]{64}$/.test(entry.fingerprint) ||
          !/^[A-Za-z0-9_.:-]{1,200}$/.test(entry.key) || !Number.isFinite(entry.at) || entry.at <= 0 ||
          !(entry.expectedVersion === null || /^\d{1,20}$/.test(String(entry.expectedVersion))
            || /^case:[A-Za-z0-9_.:-]{1,200}:\d{1,20}$/.test(String(entry.expectedVersion)))) throw new Error('metadata')
      pendingMutations.set(entry.fingerprint, {
        key: entry.key, at: entry.at, expectedVersion: entry.expectedVersion, persistent: true,
      })
    }
  } catch { pendingStorageCorrupt = true }
}

function persistPendingMutations() {
  const entries = [...pendingMutations].filter(([, item]) => item.persistent)
    .map(([fingerprint, item]) => ({ fingerprint, key: item.key, expectedVersion: item.expectedVersion, at: item.at }))
  const serialized = JSON.stringify(entries)
  if (entries.length > PENDING_MAX_ENTRIES || serialized.length > PENDING_MAX_BYTES) {
    throw pendingProblem('pending_operations_full', 'มีงานที่ผลลัพธ์ยังไม่ยืนยันมากเกินไป กรุณาตรวจสอบประวัติรายการก่อนดำเนินการต่อ')
  }
  try {
    if (entries.length) window.sessionStorage.setItem(PENDING_KEY, serialized)
    else window.sessionStorage.removeItem(PENDING_KEY)
  } catch {
    throw pendingProblem('operation_storage_unavailable', 'เก็บข้อมูลสำหรับตรวจสอบการบันทึกซ้ำไม่ได้ กรุณาตรวจสอบการตั้งค่าเบราว์เซอร์')
  }
}

function clearPendingMutations() {
  pendingMutations.clear()
  pendingStorageCorrupt = false
  try { window.sessionStorage.removeItem(PENDING_KEY) } catch { /* auth still ends */ }
}

function acceptAuthenticatedLogin(body) {
  // A successful sign-in can switch people in this tab. Previous-person retry
  // metadata must never become an instruction submitted by the new identity.
  clearPendingMutations()
  resourceVersions.clear()
  caseVersions.clear()
  seenStateVersion = null
  return acceptLogin(body)
}

function finishMutation(response, problem = null) {
  const operation = responseMutations.get(response)
  if (!operation || response.status >= 500) return
  // A reused key with a changed payload proves an earlier submission exists,
  // not that it is safe to submit again with a new key.
  if (problem?.code === 'idempotency_conflict') return
  pendingMutations.delete(operation.signature)
  try { persistPendingMutations() } catch { /* retaining a completed replay is safe */ }
  noteState(response, operation.path)
}

async function operationFingerprint(method, path, body, headers, stableUploadIdentity = null) {
  // Auth bodies contain credentials and have no server response cache. Never
  // persist even their hashes, which could make weak test passwords guessable.
  if (path.startsWith('/v1/auth/')) return null
  let payload = typeof body === 'string' ? body : [body?.size || 0, body?.type || '', body?.lastModified || 0]
  let trustworthy = true
  if (stableUploadIdentity) {
    payload = stableUploadIdentity.value
    trustworthy = stableUploadIdentity.trustworthy
  } else if (body && typeof body !== 'string') {
    const identity = await fileIdentity(body)
    payload = identity.value
    trustworthy = identity.trustworthy
  }
  const source = JSON.stringify([method, path, payload,
    ...['Content-Type', 'X-Volt-Filename', 'X-Volt-Attach-To'].map((key) => headers?.[key] || ''),
    stableUploadIdentity ? '' : headers?.['X-Volt-Upload'] || ''])
  if (trustworthy && globalThis.crypto?.subtle && typeof TextEncoder !== 'undefined') {
    const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(source))
    return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('')
  }
  // Insecure prototype origins can lack SubtleCrypto. This fallback is volatile,
  // bounded in aggregate, and deliberately never enters sessionStorage.
  return `volatile:${source}`
}

async function fileIdentity(file) {
  const metadata = [file?.name || '', file?.size || 0, file?.type || '', file?.lastModified || 0]
  if (globalThis.crypto?.subtle && typeof file?.arrayBuffer === 'function') {
    const digest = await globalThis.crypto.subtle.digest('SHA-256', await file.arrayBuffer())
    return { value: [...metadata, [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('')], trustworthy: true }
  }
  return { value: metadata, trustworthy: false }
}

function mutationHeaders(path, signature) {
  const headers = roleHeaders()
  if (signature === null) return headers
  if (pendingStorageCorrupt) throw pendingProblem('operation_outcome_unknown', 'ข้อมูลตรวจสอบงานก่อนหน้าอ่านไม่ได้ กรุณาตรวจสอบประวัติรายการก่อนดำเนินการต่อ')
  let operation = pendingMutations.get(signature)
  if (operation && (Date.now() - operation.at >= PENDING_TTL_MS || operation.at > Date.now() + 60000)) {
    throw pendingProblem('operation_outcome_unknown', 'งานก่อนหน้าเกินช่วงเวลาที่ตรวจสอบการบันทึกซ้ำได้ กรุณาตรวจสอบผลในระบบก่อนส่งใหม่')
  }
  if (!operation) {
    const totalBytes = [...pendingMutations.keys()].reduce((sum, key) => sum + key.length + 256, signature.length + 256)
    if (pendingMutations.size >= PENDING_MAX_ENTRIES || totalBytes > PENDING_MAX_BYTES) {
      throw pendingProblem('pending_operations_full', 'มีงานที่ผลลัพธ์ยังไม่ยืนยันมากเกินไป กรุณาตรวจสอบประวัติรายการก่อนดำเนินการต่อ')
    }
    const caseNote = /^\/v1\/cases\/by-customer\/([^/]+)\/notes(?:\?|$)/.exec(path)
    operation = { key: uploadId(), at: Date.now(),
      expectedVersion: (caseNote && caseVersions.get(decodeURIComponent(caseNote[1])))
        || resourceVersions.get(resourceKey(path)) || seenStateVersion,
      persistent: !signature.startsWith('volatile:') }
    pendingMutations.set(signature, operation)
    if (operation.persistent) {
      try { persistPendingMutations() } catch (error) { pendingMutations.delete(signature); throw error }
    }
  }
  headers['Idempotency-Key'] = operation.key
  if (operation.expectedVersion !== null && !path.startsWith('/v1/operation-runs/')) headers['If-Match'] = operation.expectedVersion
  return headers
}

async function mutationFetch(method, path, body, extra = {}) {
  const { stableUploadIdentity, ...options } = extra
  const signature = await operationFingerprint(method, path, body, extra.headers, stableUploadIdentity)
  if (extra.signal?.aborted) throw new DOMException('aborted', 'AbortError')
  const response = await fetch(BASE + path, {
    ...options, method, body,
    headers: { ...mutationHeaders(path, signature), ...extra.headers },
  })
  if (signature !== null) responseMutations.set(response, { signature, path })
  return response
}

async function post(path, payload) {
  return send('POST', path, payload || {})
}

async function send(method, path, payload) {
  const response = await mutationFetch(method, path,
    payload === undefined ? undefined : JSON.stringify(payload),
    { headers: { 'Content-Type': 'application/json' } })
  const body = await readJson(response, path)
  notifyChanged(path, method)
  return body
}

function withQuery(path, params) {
  const url = new URL(BASE + path, window.location.origin)
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v)
  })
  return url.pathname + url.search
}

// The work book export is a CSV (200 text/csv with Content-Disposition), not JSON:
// fetched with the role headers so the refusal, if any, is a Problem the screen
// can show, and handed back as text plus the server's file name.
async function exportCsv(path, params) {
  const response = await fetch(withQuery(path, params), { headers: roleHeaders() })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    finishMutation(response, body)
    signalAuth(response.status, body)
    throw Object.assign(new Error(path), {
      problem: body || { code: 'export_failed', title: `HTTP ${response.status}`, status: response.status },
      status: response.status,
    })
  }
  const text = await response.text()
  finishMutation(response)
  const disposition = (response.headers && typeof response.headers.get === 'function' && response.headers.get('Content-Disposition')) || ''
  const named = /filename\*?="?([^";]+)"?/.exec(disposition)
  return { text, filename: named ? decodeURIComponent(named[1].replace(/^UTF-8''/i, '')) : 'workbook.csv' }
}

const put = (path, payload) => send('PUT', path, payload)
const del = (path) => send('DELETE', path)

// Ruling 71 — the officer's own upload. A RAW request body, never `FormData`:
// `python-multipart` is not installed, so an `UploadFile` route would crash the
// server at import time (C-backend.md §2.1). The browser's `File` object IS a
// Blob, so it can be the fetch body directly; the filename travels in a header
// because a raw body carries no field names of its own.
// 2026-09-25: Cloud Run refuses a request body over 32 MiB and New Order Master
// grows every month, so a file past PART_BYTES goes up in parts first; the upload
// then names them with X-Volt-Upload and carries no body (app/imports.py put_part).
export const PART_BYTES = 8 * 1024 * 1024

// crypto.randomUUID exists only on a secure origin (https, localhost); a LAN
// address over http has getRandomValues alone.
function uploadId() {
  if (crypto.randomUUID) return crypto.randomUUID()
  const b = crypto.getRandomValues(new Uint8Array(16))
  b[6] = (b[6] & 0x0f) | 0x40
  b[8] = (b[8] & 0x3f) | 0x80
  const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('')
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
}

async function discardParts(id) {
  const path = `/v1/imports/parts/${id}`
  try {
    const response = await mutationFetch('DELETE', path)
    finishMutation(response)
  } catch { /* best effort; the backend also expires abandoned chunks */ }
}

async function sendParts(file, { signal, onProgress } = {}) {
  const id = uploadId()
  const of = Math.ceil(file.size / PART_BYTES)
  try {
    for (let i = 0; i < of; i += 1) {
      const path = `/v1/imports/parts/${id}/${i}?of=${of}`
      const response = await mutationFetch('POST', path, file.slice(i * PART_BYTES, (i + 1) * PART_BYTES), {
        headers: { 'Content-Type': 'application/octet-stream' },
        signal,
      })
      await readJson(response, path)
      onProgress?.({
        phase: 'uploading',
        uploadedBytes: Math.min(file.size, (i + 1) * PART_BYTES),
        totalBytes: file.size,
      })
    }
  } catch (error) {
    await discardParts(id)
    throw error
  }
  return id
}

async function postRaw(path, file, extraHeaders = {}, {
  chunk = true, signal, onProgress,
} = {}) {
  let upload = null
  const stableUploadIdentity = await fileIdentity(file)
  try {
    upload = chunk && file.size ? await sendParts(file, { signal, onProgress }) : null
    onProgress?.({ phase: 'parsing', uploadedBytes: file.size, totalBytes: file.size })
    const response = await mutationFetch('POST', path, upload ? '' : file, {
      stableUploadIdentity,
      headers: {
        'Content-Type': file.type || 'application/octet-stream',
        'X-Volt-Filename': encodeURIComponent(file.name || 'upload'),
        ...(upload ? { 'X-Volt-Upload': upload } : {}),
        ...extraHeaders,
      },
      signal,
    })
    const body = await readJson(response, path)
    notifyChanged(path, 'POST')
    return body
  } catch (error) {
    if (upload) await discardParts(upload)
    throw error
  }
}

const waitFor = (ms, signal) => new Promise((resolve, reject) => {
  if (signal?.aborted) {
    reject(new DOMException('aborted', 'AbortError'))
    return
  }
  const onAbort = () => {
    clearTimeout(timer)
    reject(new DOMException('aborted', 'AbortError'))
  }
  const timer = setTimeout(() => {
    signal?.removeEventListener('abort', onAbort)
    resolve()
  }, ms)
  signal?.addEventListener('abort', onAbort, { once: true })
})

const ACTIVE_OPERATION_STATES = new Set([
  'queued', 'uploading', 'parsing', 'scanning', 'applying', 'cancel_requested', 'running',
])

async function postOperation(path, file, extraHeaders = {}, options = {}) {
  let run = null
  try {
    run = await postRaw(path, file, extraHeaders, options)
    options.onProgress?.(run)
    if (!run?.uid || !run?.state) return run
    while (ACTIVE_OPERATION_STATES.has(run.state)) {
      await waitFor(350, options.signal)
      run = await get(`/v1/operation-runs/${run.uid}`, undefined, { signal: options.signal, background: true })
      options.onProgress?.(run)
    }
    if (run.state === 'done') return run.result ?? run
    const problem = run.problem || {
      code: run.state === 'cancelled' ? 'operation_cancelled' : 'operation_failed',
      message_th: run.state === 'cancelled' ? 'ยกเลิกงานแล้ว' : 'ดำเนินการไม่สำเร็จ',
    }
    throw Object.assign(new Error(problem.detail || problem.code), { problem })
  } catch (error) {
    if (run?.uid && error?.name === 'AbortError') {
      try {
        await post(`/v1/operation-runs/${run.uid}:cancel`, {})
      } catch (cancelError) {
        // The commit boundary is authoritative: the UI must not claim that an
        // already-persisted operation was cancelled merely because polling was
        // aborted at the same instant.
        if (cancelError?.problem?.code === 'run_not_cancellable') throw cancelError
      }
    }
    throw error
  }
}

// Ruling 72 — the governed export. Same CSV-over-fetch shape as `exportCsv`
// above, POSTed with a JSON body (the reason) instead of GET's bare query, and
// carrying back the `X-Volt-Export-Uid` the server minted for the record.
async function exportCsvPost(path, payload, filters) {
  const query = new URLSearchParams()
  Object.entries(filters || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') query.set(key, String(value))
  })
  if (query.size) path += `${path.includes('?') ? '&' : '?'}${query}`
  const response = await mutationFetch('POST', path, JSON.stringify(payload || {}), {
    headers: { 'Content-Type': 'application/json' },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    finishMutation(response, body)
    signalAuth(response.status, body)
    throw Object.assign(new Error(path), {
      problem: body || { code: 'export_failed', title: `HTTP ${response.status}`, status: response.status },
      status: response.status,
    })
  }
  const text = await response.text()
  finishMutation(response)
  const disposition = (response.headers && typeof response.headers.get === 'function' && response.headers.get('Content-Disposition')) || ''
  const named = /filename\*?="?([^";]+)"?/.exec(disposition)
  const uid = (response.headers && typeof response.headers.get === 'function' && response.headers.get('X-Volt-Export-Uid')) || null
  notifyChanged(path, 'POST')
  return { text, filename: named ? decodeURIComponent(named[1].replace(/^UTF-8''/i, '')) : 'workbook.csv', uid }
}

// A binary file over POST (the weekly report's .xlsx): same refusal handling as the
// CSV exports above, handed back as a Blob plus the server's file name. The
// `filename*=UTF-8''…` form wins when the server sends both.
async function exportFilePost(path, payload, fallbackName) {
  const response = await mutationFetch('POST', path, JSON.stringify(payload || {}), {
    headers: { 'Content-Type': 'application/json' },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    finishMutation(response, body)
    signalAuth(response.status, body)
    throw Object.assign(new Error(path), {
      problem: body || { code: 'export_failed', title: `HTTP ${response.status}`, status: response.status },
      status: response.status,
    })
  }
  const blob = await response.blob()
  finishMutation(response)
  const disposition = (response.headers && typeof response.headers.get === 'function' && response.headers.get('Content-Disposition')) || ''
  const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  const filename = star ? decodeURIComponent(star[1]) : plain ? plain[1] : fallbackName
  return { blob, filename }
}

export const api = {
  contractScheduleConfirmation: (uid) => get(`/v1/contracts/${uid}/schedule-confirmation`),
  confirmContractSchedule: (uid, body) => post(`/v1/contracts/${uid}/schedule-confirmation`, body),
  messageTemplates: (params) => get('/v1/message-templates', params),
  createMessageTemplate: (payload) => post('/v1/message-templates', payload),
  updateMessageTemplate: (uid, payload) => put(`/v1/message-templates/${uid}`, payload),
  deleteMessageTemplate: (uid) => del(`/v1/message-templates/${uid}`),
  todayList: (params) => get('/v1/today-list', params),
  shellSummary: (params) => get('/v1/shell/summary', params),
  // 2026-09-20 sync audit: which import epoch the process serves, which this session
  // seeded from, and the session's own catch-up (the stale banner's button).
  dataState: (options) => get('/v1/data-state', undefined, options),
  // One request for the Data sources screen (migration + integrations + crm + peak).
  dataSourcesOverview: () => get('/v1/data-sources/overview'),
  refreshImports: () => post('/v1/session:refresh-imports', {}),
  readyz: () => fetch('/api/readyz').then((r) => (r.ok ? r.json() : null)).catch(() => null),
  boardColumns: () => get('/v1/board/columns'),
  customerContracts: (uid) => get(`/v1/customers/${uid}/contracts`),
  contractSummary: (uid) => get(`/v1/contracts/${uid}/summary`),
  exceptions: (populationFilter) => get('/v1/dashboards/exceptions', { population_filter: populationFilter }),
  recoveryBoard: () => get('/v1/recovery-board'),
  pending: () => get('/v1/config/pending'),
  orders: (params) => get('/v1/orders', params),
  loanBook: () => get('/v1/loan-book'),
  approveOrder: (no, by) => post(`/v1/orders/${no}/approve`, { by }),
  createOrder: (payload) => post('/v1/orders', payload),
  deleteOrder: (no) => del(`/v1/orders/${no}`),
  uatTasks: () => get('/v1/uat/tasks'),
  sendFeedback: (payload) => post('/v1/feedback', payload),
  feedback: () => get('/v1/feedback'),
  logContact: (payload) => post('/v1/contacts', payload),
  retractContact: (id, at) => post(`/v1/contacts/${id}:retract`, { at }),
  raisePenaltyInvoice: (uid) => post(`/v1/contracts/${uid}/penalty-invoices`, {}),

  // --- the 2026-08-30 rebuild ----------------------------------------------------
  workingList: (params) => get('/v1/working-list', params),
  scenarios: () => get('/v1/scenarios'),
  ladderMode: () => get('/v1/ladder-mode'),
  setLadderMode: (mode) => put('/v1/ladder-mode', { ladder_mode: mode }),
  createPtp: (payload) => post('/v1/ptps', payload),
  ptps: (params) => get('/v1/ptps', params),
  closePtp: (uid, payload) => post(`/v1/ptps/${uid}:close`, payload),
  cancelPtp: (uid, reason) => post(`/v1/ptps/${uid}:cancel`, { reason }),
  serviceIssues: (params) => get('/v1/service-issues', params),
  createServiceIssue: (payload) => post('/v1/service-issues', payload),
  resolveServiceIssue: (uid, note) => post(`/v1/service-issues/${uid}:resolve`, { note }),
  boardMove: (payload) => post('/v1/board/moves', payload),
  recoveryBoardMove: (payload) => post('/v1/recovery-board/moves', payload),
  cases: (params) => get('/v1/cases', params),
  advanceCase: (uid, payload) => post(`/v1/cases/${uid}:advance`, payload),
  cashCases: () => get('/v1/cash-cases'),
  advanceCashCase: (uid, payload) => post(`/v1/cash-cases/${uid}:advance`, payload),
  proposeRestructure: (caseUid, payload) => post(`/v1/cases/${caseUid}/restructures`, payload),
  approveRestructure: (uid, payload) => post(`/v1/restructures/${uid}:approve`, payload),
  recordRestructureMiss: (uid) => post(`/v1/restructures/${uid}:record-miss`, {}),
  reviewQueue: (params) => get('/v1/manager-review', params),
  decideReview: (uid, payload) => post(`/v1/manager-review/${uid}:decide`, payload),
  nplCases: () => get('/v1/npl-cases'),
  // The body IS { strategy, … } — journey.py open_recovery reads body.strategy (it was
  // wrapped twice, { strategy: { strategy, by } }, and always refused).
  openRecovery: (nplUid, payload) => post(`/v1/npl-cases/${nplUid}/recovery`, payload),
  recoveryCases: () => get('/v1/recovery-cases'),
  recordRecovery: (uid, payload) => post(`/v1/recovery-cases/${uid}/recoveries`, payload),
  resolveRecovery: (uid, payload) => post(`/v1/recovery-cases/${uid}:resolve`, payload),
  lots: () => get('/v1/repossession-lots'),
  lotAct: (uid, act, payload) => post(`/v1/repossession-lots/${uid}:${act}`, payload),
  serviceBilling: () => get('/v1/service-billing'),
  billService: (contractUid) => post(`/v1/contracts/${contractUid}/service-billing:bill`, {}),
  declineService: (contractUid, payload) => post(`/v1/contracts/${contractUid}/service-billing:decline`, payload),
  // UAT round-2 (T2-04): the slip picker searches the invoice list with ?q= /
  // ?customer_uid= instead of taking the first 25 rows.
  arPipeline: (params) => get('/v1/ar/pipeline', params),
  caseInvoices: (customerUid) => get(`/v1/cases/by-customer/${customerUid}/invoices`),
  contractInvoices: (uid) => get(`/v1/contracts/${uid}/invoices`),
  contractReceipts: (uid) => get(`/v1/contracts/${uid}/receipts`),
  contractInstalments: (uid) => get(`/v1/contracts/${uid}/instalments`),
  previewServiceDeferral: (uid, payload) => post(`/v1/contracts/${uid}/service-deferrals/preview`, payload),
  previewInvoiceReviews: (uid, payload) => post(`/v1/cases/by-customer/${uid}/invoice-reviews/preview`, payload),
  confirmInvoiceReviews: (uid, payload) => post(`/v1/cases/by-customer/${uid}/invoice-reviews`, payload),
  confirmServiceDeferral: (uid, payload) => post(`/v1/contracts/${uid}/service-deferrals`, payload),
  previewServiceDeferralReverse: (uid, row, payload) => post(`/v1/contracts/${uid}/service-deferrals/${row}/reverse-preview`, payload),
  reverseServiceDeferral: (uid, row, payload) => post(`/v1/contracts/${uid}/service-deferrals/${row}/reverse`, payload),
  reviewServiceDeferral: (uid, row, payload) => post(`/v1/contracts/${uid}/service-deferrals/${row}/accounting-review`, payload),
  accountingHistory: (params) => get('/v1/service-deferrals/history', params),
  recordReceipt: (payload) => post('/v1/receipts', payload),
  timeline: (customerUid) => get(`/v1/customers/${customerUid}/timeline`),
  intercompanyDocs: (params) => get('/v1/intercompany/docs', params),
  cancellations: () => get('/v1/cancellations'),
  integrationsStatus: () => get('/v1/integrations/status'),
  odooDiscovery: () => get('/v1/integrations/odoo/discovery'),
  overrideOrderStatus: (no, payload) => post(`/v1/orders/${no}/status-override`, payload),
  statusOverrides: () => get('/v1/status-overrides'),
  issuePeak: (invoiceUid) => post(`/v1/invoices/${invoiceUid}:issue-peak`, {}),
  // J2-03: the sheet says a link was sent but never when; the officer records today's send.
  recordLinkSent: (invoiceUid) => post(`/v1/invoices/${invoiceUid}:link-sent`, {}),

  // --- the 2026-09-02 realignment (API Surface v2.3) ------------------------------
  today: (params) => get('/v1/today', params),
  todayExport: (payload) => exportCsvPost('/v1/today:export', payload),
  todayItemDone: (uid) => post(`/v1/today/items/${uid}:done`, {}),
  reminders: (params) => get('/v1/today/reminders', params),
  sendReminder: (payload) => post('/v1/today/reminders:send', payload),
  customerSearch: (params, options) => get('/v1/customers/search', params, options),
  customerInvoiceStatuses: (customerUid, params, options) =>
    get(`/v1/customers/${customerUid}/invoice-statuses`, params, options),
  workbook: (params) => get('/v1/workbook', params),
  workbookExportUrl: (params) => withQuery('/v1/workbook:export', params),
  workbookExport: (params) => exportCsv('/v1/workbook:export', params),
  caseDetail: (customerUid) => get(`/v1/cases/by-customer/${customerUid}`),
  setNextAction: (customerUid, payload) => post(`/v1/cases/by-customer/${customerUid}/next-action`, payload),
  setDcStatus: (customerUid, payload) => post(`/v1/cases/by-customer/${customerUid}/dc-status`, payload),
  // Arina, 2026-09-14: a person's payment status, with a reason (spec 2026-09-14).
  setPaymentStatus: (customerUid, payload) => post(`/v1/cases/by-customer/${customerUid}/payment-status`, payload),
  previewPaymentClaim: (customerUid, payload) => post(`/v1/customers/${customerUid}/payment-claims:preview`, payload),
  createPaymentClaim: (customerUid, payload) => post(`/v1/customers/${customerUid}/payment-claims`, payload),
  paymentClaims: (customerUid) => get(`/v1/customers/${customerUid}/payment-claims`),
  cancelPaymentClaim: (uid) => post(`/v1/payment-claims/${uid}:cancel`, {}),
  paymentReconciliationExceptions: () => get('/v1/payment-reconciliation/exceptions'),
  paymentReminderPreview: (customerUid, month) => get(`/v1/customers/${customerUid}/payment-reminders:preview`, { month }),
  sendPaymentReminder: (customerUid, payload) => post(`/v1/customers/${customerUid}/payment-reminders`, payload),
  setNplType: (customerUid, payload) => post(`/v1/cases/by-customer/${customerUid}/npl-type`, payload),
  // Feedback Round 1 / WP9: a phone number a person enters, with a reason ({ phone, reason, by }).
  setCustomerPhone: (customerUid, payload) => post(`/v1/cases/by-customer/${customerUid}/phone`, payload),
  // End live contracts with a cause and reason; the actual balance remains unchanged.
  terminateCustomerContract: (customerUid, payload) => post(`/v1/cases/by-customer/${customerUid}:terminate`, payload),
  // 2026-09-20: the one audited read of the customer's full number. Every list and
  // the case detail serve only the mask plus `phone_revealable`; the server writes
  // PHONE_REVEALED (source and kind, never the digits) on each call.
  revealCustomerPhone: (customerUid) => post(`/v1/cases/by-customer/${customerUid}/phone:reveal`, {}),
  logCaseContact: (customerUid, payload) => post(`/v1/cases/by-customer/${customerUid}/contacts`, payload),
  correctContact: (uid, payload) => post(`/v1/contacts/${uid}:correct`, payload),
  closeCasePtp: (uid, payload) => post(`/v1/case-ptps/${uid}:close`, payload),
  renegotiatePtp: (uid, payload) => post(`/v1/case-ptps/${uid}:renegotiate`, payload),
  // Feedback round 2 (TASK-001) — the routes phases 1-4 read. `ptpReportExport` is
  // a governed POST export (backend TASK-115 audits PTP_REPORT_EXPORTED), so it
  // uses the POST-over-fetch shape the other governed exports already use.
  reportsOfficer: (uid) => get(`/v1/reports/officers/${uid}`),
  assignCustomers: (payload) => post('/v1/customers:assign', payload),
  // Feedback round 2 / TASK-028 (F10b, F10c): the portfolio split, its served preview
  // and its template. The template is fetched with the role headers (it is a
  // manager's download), so it uses the same CSV-over-fetch shape as the exports —
  // a bare <a href> would reach the gate as an OFFICER and be refused.
  assignSplitBuckets: () => get('/v1/customers:assign-split/buckets'),
  assignSplit: (payload) => post('/v1/customers:assign-split', payload),
  assignTemplate: () => exportCsv('/v1/imports/assignments:template'),
  assignTemplateUpload: (file, options) => postOperation('/v1/imports/assignments:start', file, {}, options),
  setCaseStage: (caseUid, payload) => post(`/v1/cases/${caseUid}:set-stage`, payload),
  setCashCaseStage: (caseUid, payload) => post(`/v1/cash-cases/${caseUid}:set-stage`, payload),
  changeRecoveryStrategy: (recoveryUid, payload) => post(`/v1/recovery-cases/${recoveryUid}:change-strategy`, payload),
  ptpReport: (params) => get('/v1/reports/ptps', params),
  ptpReportExport: (params) => exportCsvPost('/v1/reports/ptps:export', params),
  requestReview: (customerUid, payload) => post(`/v1/cases/by-customer/${customerUid}/review-requests`, payload),
  reviews: (params) => get('/v1/reviews', params),
  answerReview: (uid, payload) => post(`/v1/reviews/${uid}:answer`, payload),
  closeCaseIssue: (uid, payload) => post(`/v1/case-issues/${uid}:close`, payload),
  requestPower: (customerUid, payload) => post(`/v1/cases/by-customer/${customerUid}/power-restriction`, payload),
  powerAct: (uid, act, payload) => post(`/v1/power-restrictions/${uid}:${act}`, payload),
  powerRestrictions: () => get('/v1/power-restrictions'),
  pipeline: (params) => get('/v1/pipeline', params),
  // Round 7 / WP2: the seventeen-step SOP catalogue, so a screen that owns a STEP
  // can name it without the client hard-coding workflow content it does not own.
  sopSteps: () => get('/v1/sop/steps'),
  pipelineGateDownPayment: (uid, payload) => post(`/v1/pipeline/${uid}/gates/down-payment`, payload),
  pipelineGateEpc: (uid, payload) => post(`/v1/pipeline/${uid}/gates/epc-confirmed`, payload),
  pipelineRelease: (uid, payload) => post(`/v1/pipeline/${uid}:release`, payload),
  pipelineDeliver: (uid, payload) => post(`/v1/pipeline/${uid}/delivery`, payload),
  pipelineInstallOutcome: (uid, payload) => post(`/v1/pipeline/${uid}/install-outcome`, payload),
  pipelineReschedule: (uid, payload) => post(`/v1/pipeline/${uid}/reschedule`, payload),
  pipelineReply: (uid, reply) => post(`/v1/pipeline/${uid}/delivery/reply`, { reply }),
  // Delta-100 D2h / P2 (prototype 1199-1209, DR5): the Attach-evidence drawer. A
  // condition's evidence is its own record; attaching to contract_signed is the only
  // way it can pass, and removing the last record reopens the condition.
  pipelineConditionEvidence: (uid, key, payload) => post(`/v1/pipeline/${uid}/conditions/${key}/evidence`, payload),
  pipelineConditionEvidenceRemove: (uid, key, evidenceUid) => post(`/v1/pipeline/${uid}/conditions/${key}/evidence/${evidenceUid}:remove`, {}),
  peakDocuments: (params) => get('/v1/peak-documents', params),
  peakResend: (uid) => post(`/v1/peak-documents/${uid}:resend`, {}),
  peakRefresh: (uid) => post(`/v1/peak-documents/${uid}:refresh`, {}),
  // Delta-100 PAY-12 (prototype 597): fix a REFUSED document and resubmit it —
  // Manager+ only on the wire, audited as PEAK_DOCUMENT_RESUBMITTED.
  peakResubmit: (uid) => post(`/v1/peak-documents/${uid}/resubmit`, {}),
  peakRefreshAll: () => post('/v1/peak-documents:refresh-all', {}),
  peakStub: (payload) => post('/v1/peak-documents/stub', payload),
  confirmSlip: (payload) => post('/v1/slips', payload),
  creditNote: (payload) => post('/v1/credit-notes', payload),
  dictionaries: () => get('/v1/dictionaries'),
  dictionary: (name) => get(`/v1/dictionaries/${name}`),
  addDictionaryValue: (name, payload) => post(`/v1/dictionaries/${name}/values`, payload),
  deactivateDictionaryValue: (name, code) => post(`/v1/dictionaries/${name}/values/${code}:deactivate`, {}),
  config: () => get('/v1/config'),
  putConfig: (payload) => put('/v1/config', payload),
  bandSets: () => get('/v1/band-sets'),
  addBandSet: (payload) => post('/v1/band-sets', payload),
  deactivateBandSet: (code) => post(`/v1/band-sets/${code}:deactivate`, {}),
  // Round-3 J3-11 / J3-38: one click retired a set with no way back from the screen.
  // Round-6 S6-02: the button was inert because this said :reactivate and the API
  // serves :activate — the request 404'd and the row never came back.
  reactivateBandSet: (code) => post(`/v1/band-sets/${code}:activate`, {}),
  assignCustomer: (uid, payload) => post(`/v1/customers/${uid}/assign`, payload),
  migrationReport: () => get('/v1/migration/report'),
  gapList: () => get('/v1/migration/gap-list'),
  // Ruling 71/72 (round 5) — the officer's own upload and the governed export.
  createImport: (file, options = {}) => {
    const { profile, ...operationOptions } = options
    const query = profile ? `?profile=${encodeURIComponent(profile)}` : ''
    return postOperation(`/v1/imports:start${query}`, file, {}, operationOptions)
  },
  applyImportPreview: (uid, payload) => post(`/v1/imports/previews/${encodeURIComponent(uid)}:apply`, payload),
  confirmInstallation: (uid, payload) => post(`/v1/contracts/${encodeURIComponent(uid)}/installation-confirmation`, payload),
  // Fix-all leg S (Arina 2026-09-24): a manager installs the checked New Order Master
  // as the book; the review list names where PEAK and the sheet disagree.
  // `confirm` echoes the count of customers the install would retire (the check serves it).
  installSheet: (file, confirm, options) => postOperation(
    `/v1/imports:start?install=true${confirm != null ? `&confirm_retire=${confirm}` : ''}`, file, {}, options),
  sheetDisagreements: () => get('/v1/imports/sheet/disagreements'),
  // The crm.lead pipeline (2026-09-11 design). Same raw-body shape as
  // `createImport` when a file is dropped; a JSON body when the officer chooses
  // the Odoo door instead. One endpoint, because the two doors differ only here.
  crmLeadLastRun: () => get('/v1/pipelines/crm-lead/last-run'),
  // The watchable run (2026-09-11). `:start` answers 202 with a uid; the screen
  // polls `crmLeadRun` until the state leaves "running". `send` carries the role
  // headers, so a refusal renders as a Problem like every other act. `crmLeadRun`
  // (the poll) never takes a mode — the run named it the moment it started. Odoo
  // only: the crm.lead file door closed on 2026-09-25 (the sheet lands at /v1/imports).
  startCrmLeadPipeline: (mode) => post('/v1/pipelines/crm-lead:start', { source: 'odoo', mode }),
  crmLeadRun: (uid) => get(`/v1/pipelines/crm-lead/runs/${uid}`),
  crmLeadLandingRun: (runId, params) => get(`/v1/pipelines/crm-lead/landing-runs/${runId}`, params),
  crmLeadProvenance: (voltId) => get('/v1/pipelines/crm-lead/provenance', { volt_id: voltId }),
  crmLeadCustomers: (params) => get('/v1/pipelines/crm-lead/customers', params),
  crmLeadSchedule: () => get('/v1/pipelines/crm-lead/schedule'),
  crmLeadScheduleSet: (payload) => put('/v1/pipelines/crm-lead/schedule', payload),
  // Feedback Round 1 / WP1 — the PEAK invoice report door (routers/peak_pipeline.py).
  peakReportStart: (file, options) => postRaw('/v1/pipelines/peak-report:start', file, {}, options),
  peakReportRun: (uid) => get(`/v1/pipelines/peak-report/runs/${uid}`),
  peakReportLastRun: () => get('/v1/pipelines/peak-report/last-run'),
  peakReportRows: (runId, params) => get(`/v1/pipelines/peak-report/landing-runs/${runId}/rows`, params),
  peakReportApply: (runId, body) => post(`/v1/pipelines/peak-report/landing-runs/${runId}:apply`, body || {}),
  // Repairs a committed apply whose served reload failed (`served: false`).
  peakReportRefreshServed: (runId) => post(`/v1/pipelines/peak-report/landing-runs/${runId}:refresh-served`, {}),
  peakLinks: (params) => get('/v1/pipelines/peak-report/links', params),
  peakLinkConfirm: (body) => post('/v1/pipelines/peak-report/links', body),
  peakLinkRetire: (uid, body) => post(`/v1/pipelines/peak-report/links/${uid}:retire`, body || {}),
  // Feedback Round 1 / WP5 (F19): both doors and their state, in codes the card words.
  peakReportDoors: () => get('/v1/pipelines/peak-report/doors'),
  peakReportSchemas: () => get('/v1/pipelines/peak-report/schemas'),
  // Feedback round 2 / Q6-Q7 (TASK-212): the receipt door, the conflict review and
  // the case-side pairing.
  peakReceiptStart: (file, options) => postRaw('/v1/pipelines/peak-receipt:start', file, {}, options),
  peakReceiptRun: (uid) => get(`/v1/pipelines/peak-receipt/runs/${uid}`),
  peakReceiptLastRun: () => get('/v1/pipelines/peak-receipt/last-run'),
  peakReceiptRows: (runId, params) => get(`/v1/pipelines/peak-receipt/landing-runs/${runId}/rows`, params),
  peakReceiptApply: (runId, body) => post(`/v1/pipelines/peak-receipt/landing-runs/${runId}:apply`, body || {}),
  peakConflicts: (runId, params) => get(`/v1/pipelines/peak-report/landing-runs/${runId}/conflicts`, params),
  peakConflictsDecide: (runId, body) => post(`/v1/pipelines/peak-report/landing-runs/${runId}/conflicts:decide`, body),
  peakDecisionRetire: (uid) => post(`/v1/pipelines/peak-report/field-decisions/${uid}:retire`, {}),
  casePeakCodes: (uid, q) => get(`/v1/cases/by-customer/${uid}/peak-codes`, { q }),
  casePeakLink: (uid, body) => post(`/v1/cases/by-customer/${uid}/peak-link`, body),
  setCrmLeadSchedule: (enabled, minutes) =>
    send('PUT', '/v1/pipelines/crm-lead/schedule',
         { enabled, interval_minutes: minutes }),
  imports: () => get('/v1/imports'),
  importRun: (uid) => get(`/v1/imports/${uid}`),
  workbookExportGoverned: (options) => {
    const filters = typeof options === 'string' ? { reason: options } : { ...(options || {}) }
    const reason = filters.reason
    delete filters.reason
    delete filters.limit
    delete filters.cursor
    return exportCsvPost('/v1/workbook:export', { reason }, filters)
  },
  // `api.orders()` already exists below (line ~279) and is reused, not
  // redefined: its `source.data_source` is the fact the fallback chain
  // describes — which source is serving the order/loan book right now — and
  // was already served (main.py:302) before any screen read it.
  weeklyReport: () => get('/v1/reports/weekly'),
  putWeeklyTargets: (period, payload) => put(`/v1/reports/weekly/${period}/targets`, payload),
  putWeeklyFocus: (period, payload) => put(`/v1/reports/weekly/${period}/focus`, payload),
  officerReport: () => get('/v1/reports/officers'),
  reportsTeam: () => get('/v1/reports/team'),
  bucketFlow: (params) => get('/v1/reports/bucket-flow', params),
  // Round-4 J4-19: a snapshot's label is the generated period; a person naming
  // the report they just saved sends that name with it. An API that ignores the
  // field simply keeps the period label.
  weeklySnapshot: (payload) => post('/v1/reports/weekly:snapshot', payload || {}),
  weeklySnapshots: () => get('/v1/reports/weekly/snapshots'),
  // Editions: the live report is the draft; publishing freezes it as edition N of
  // its week. The Excel file is a POST so every copy that leaves is in the action log.
  weeklyPublish: (payload) => post('/v1/reports/weekly:publish', payload || {}),
  weeklyEditions: () => get('/v1/reports/weekly/editions'),
  weeklyEdition: (uid) => get(`/v1/reports/weekly/editions/${uid}`),
  weeklyExport: (payload) => exportFilePost('/v1/reports/weekly:export', payload, 'weekly-report.xlsx'),
  // Monthly history (2026-09-25): per month by payment status, and one month as .xlsx.
  monthlyReport: (months = 12) => get(`/v1/reports/monthly?months=${months}`),
  monthlyExport: (payload) => exportFilePost('/v1/reports/monthly:export', payload, 'monthly-history.xlsx'),
  // UAT round-2 (S2-04): the identities a role may sign as.
  officers: () => get('/v1/officers'),
  // Login (design 2026-09-13).
  authConfig: () => get('/v1/auth/config'),
  authMe: () => get('/v1/auth/me'),
  authPassword: async (payload) => acceptAuthenticatedLogin(await post('/v1/auth/password', payload)),
  authGoogle: async (payload) => acceptAuthenticatedLogin(await post('/v1/auth/google', payload)),
  authLogout: async () => {
    const result = await post('/v1/auth/logout', {})
    clearTabToken()
    clearPendingMutations()
    resourceVersions.clear()
    caseVersions.clear()
    seenStateVersion = null
    return result
  },
  // Feedback Round 1 / WP10–WP11: the managed allow-list, and one's own display name.
  authUsers: () => get('/v1/auth/users'),
  authInviteUser: (payload) => post('/v1/auth/users', payload),
  authDisableUser: (uid) => post(`/v1/auth/users/${encodeURIComponent(uid)}:disable`, {}),
  authSetProfile: (payload) => put('/v1/auth/me/profile', payload),
  // Round 5, rulings 78-83 — REQ-KPI-017's two collected-amount indicators and
  // the four shortfall bands. `measure` is never defaulted client-side (the API
  // refuses 422 collection_measure_unset when it is omitted, on purpose); the
  // month is likewise left to the server's own business-month default.
  collectionIndicator: (params) => get('/v1/reports/collection', params),
  putCollectionTargets: (month, payload) => put(`/v1/reports/collection/${month}/targets`, payload),
  // The action audit log (design 2026-09-11): a hash-chained, append-only record.
  terminated: (params) => get('/v1/terminated-customers', params),
  terminatedCase: (uid) => get(`/v1/terminated-customers/${encodeURIComponent(uid)}`),
  audit: (params) => get('/v1/audit', params),
  auditVerify: () => get('/v1/audit/verify'),

  // Feedback Round 1 / WP4 / Task 24 — evidence files and repeatable notes on
  // the Save-contact dialog. Raw body over `postRaw` (ruling 71's shape, not
  // FormData); the download answers a 201-free `filename*=UTF-8''…` header the
  // same way `exportCsv`/`exportCsvPost` above already read one.
  uploadAttachment: (file, attachTo, options) => postOperation(
    '/v1/attachments:start', file, attachTo ? { 'X-Volt-Attach-To': attachTo } : {}, options),
  operationRun: (uid) => get(`/v1/operation-runs/${uid}`),
  cancelOperationRun: (uid) => post(`/v1/operation-runs/${uid}:cancel`, {}),
  // The evidence a case already carries, read back by its attach-to target string.
  attachments: (attachedTo) => get('/v1/attachments', { attached_to: attachedTo }),
  downloadAttachment: async (uid) => {
    const response = await fetch(`${BASE}/v1/attachments/${uid}:download`, { method: 'POST', headers: roleHeaders() })
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      // I4 (fix round 1): every other fetcher in this file calls signalAuth
      // on a refusal — a session that ended mid-download must show the login
      // screen the same way any other 401 auth_required does, not just fail
      // the one file quietly.
      signalAuth(response.status, body)
      // Minor (fix round 2): the same fallback `exportCsv`/`exportCsvPost`
      // already use for a non-JSON error body — without it, `fromError`
      // falls through to `new Error(uid).message`, and the refusal shown to
      // the officer becomes the raw attachment uid instead of a sentence.
      throw Object.assign(new Error(uid), {
        problem: body || { code: 'download_failed', title: `HTTP ${response.status}`, status: response.status },
        status: response.status,
      })
    }
    const disposition = response.headers.get('Content-Disposition') || ''
    const m = /filename\*=UTF-8''([^;]+)/.exec(disposition)
    return { blob: await response.blob(), filename: m ? decodeURIComponent(m[1]) : uid }
  },
  // The uploader's or a Manager's undo for a file uploaded but never attached
  // (Pipeline's evidence drawer: a chosen file the officer then removes).
  deleteAttachment: (uid) => post(`/v1/attachments/${uid}:delete`, {}),
  addContactNote: (uid, body) => post(`/v1/contacts/${uid}/notes`, body),
  addCaseNote: (customerUid, body) => post(`/v1/cases/by-customer/${customerUid}/notes`, body),
  // Feedback Round 1 / WP6 (F16) — the calendar (routers/calendar.py).
  calendar: (params) => get('/v1/calendar', params),
  // C3b: move a next action to another day, with a reason (C2c).
  moveNextAction: (customerUid, body) => post(`/v1/calendar/next-actions/${customerUid}:move`, body),
  // C3c: personal notices — each person's own, no recurrence, no sharing, no e-mail.
  createNotice: (body) => post('/v1/calendar/notices', body),
  updateNotice: (uid, body) => put(`/v1/calendar/notices/${uid}`, body),
  deleteNotice: (uid) => del(`/v1/calendar/notices/${uid}`),
}

export { get, post, put, del }

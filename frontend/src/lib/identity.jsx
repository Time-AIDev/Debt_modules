// The acting identity: signing role + officer, and the signed-in session when
// AUTH_MODE=on. One module store (same shape the old role.jsx proved) so the api
// transport can read synchronously and React can subscribe. Every write the app
// makes travels through here, so header/body conventions cannot drift per screen.
import { useSyncExternalStore } from 'react'

export const ROLES = ['OFFICER', 'SUPERVISOR', 'MANAGER', 'OWNER', 'OPS']
export const ROLE_LABELS_TH = {
  OFFICER: 'เจ้าหน้าที่',
  SUPERVISOR: 'หัวหน้างาน',
  MANAGER: 'ผู้จัดการ',
  OWNER: 'เจ้าของระบบ',
  OPS: 'ปฏิบัติการ',
}
export const ROLE_RANK = { OFFICER: 1, OPS: 1, SUPERVISOR: 2, MANAGER: 3, OWNER: 4 }

const ROLE_KEY = 'volt.role'
const OFFICER_KEY = 'volt.officer'

let role = 'OFFICER'
let officer = ''
let locked = false
let session = null
let roster = []
const listeners = new Set()

function read(key, fallback) {
  try { return window.localStorage.getItem(key) || fallback } catch { return fallback }
}
function write(key, value) {
  try {
    if (value === null || value === undefined || value === '') window.localStorage.removeItem(key)
    else window.localStorage.setItem(key, value)
  } catch { /* private mode: the session still works, it just does not persist */ }
}
function emit() { listeners.forEach((fn) => fn()) }

const storedRole = read(ROLE_KEY, 'OFFICER')
role = ROLES.includes(storedRole) ? storedRole : 'OFFICER'
officer = read(OFFICER_KEY, '') || ''

export function readRole() { return role }
export function readOfficer() { return officer }
export function isLocked() { return locked }
export function getSession() { return session }
export function getRoster() { return roster }

export function setRole(next) {
  if (locked || !ROLES.includes(next) || next === role) return
  role = next
  write(ROLE_KEY, next)
  emit()
}

export function setOfficer(next) {
  if (locked || next === officer) return
  officer = next || ''
  write(OFFICER_KEY, officer)
  emit()
}

/** A signed-in session is not switchable: the name on every act is the account's. */
export function setSession(next) {
  session = next || null
  locked = !!(next && next.can_switch === false)
  if (next && next.role && ROLES.includes(next.role)) {
    role = next.role
    write(ROLE_KEY, role)
  }
  if (next && next.officer) {
    officer = next.officer
    write(OFFICER_KEY, officer)
  }
  emit()
}

export function setRoster(next) {
  roster = Array.isArray(next) ? next : []
  emit()
}

export function roleLabel(roleCode, lang) {
  const label = ROLE_LABELS_TH[roleCode] || roleCode
  return lang === 'en' ? roleCode : label
}

export function displayName() {
  if (session && (session.display_name_th || session.display_name)) {
    return session.display_name_th || session.display_name
  }
  const hit = roster.find((r) => r.uid === officer)
  return (hit && (hit.display_name_th || hit.display_name)) || officer || '—'
}

export function subscribe(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

let snapshot = null
function currentSnapshot() {
  const next = JSON.stringify([role, officer, locked, session, roster, displayName()])
  if (snapshot !== next) snapshot = next
  return next
}

export function useIdentity() {
  useSyncExternalStore(subscribe, currentSnapshot, currentSnapshot)
  return { role, officer, locked, session, roster, name: displayName() }
}

/** Manager and above — the same bar the server enforces on the same acts. */
export function atLeast(target) {
  return (ROLE_RANK[role] || 0) >= (ROLE_RANK[target] || 99)
}

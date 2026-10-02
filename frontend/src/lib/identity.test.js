import { describe, it, expect, beforeEach } from 'vitest'
import {
  readRole, readOfficer, setRole, setOfficer, setSession, isLocked,
  atLeast, roleLabel, ROLES,
} from './identity.jsx'

beforeEach(() => {
  window.localStorage.clear()
  setSession(null)
  setRole('OFFICER')
  setOfficer('')
})

describe('identity', () => {
  it('persists the signing role and officer', () => {
    setRole('MANAGER')
    setOfficer('u-1')
    expect(readRole()).toBe('MANAGER')
    expect(readOfficer()).toBe('u-1')
    expect(window.localStorage.getItem('volt.role')).toBe('MANAGER')
  })

  it('ignores unknown roles', () => {
    setRole('SUPERUSER')
    expect(readRole()).toBe('OFFICER')
  })

  it('locks identity for a non-switchable session', () => {
    setSession({ role: 'OFFICER', officer: 'u-9', can_switch: false })
    expect(isLocked()).toBe(true)
    setRole('OWNER')
    setOfficer('u-2')
    expect(readRole()).toBe('OFFICER')
    expect(readOfficer()).toBe('u-9')
  })

  it('allows switching for a test session', () => {
    setSession({ role: 'OFFICER', officer: 'u-9', can_switch: true })
    expect(isLocked()).toBe(false)
    setRole('OWNER')
    expect(readRole()).toBe('OWNER')
  })

  it('ranks roles for the same bar the server enforces', () => {
    setRole('OFFICER')
    expect(atLeast('MANAGER')).toBe(false)
    setRole('MANAGER')
    expect(atLeast('MANAGER')).toBe(true)
    setRole('OPS')
    expect(atLeast('SUPERVISOR')).toBe(false)
  })

  it('labels roles in both languages', () => {
    expect(roleLabel('MANAGER', 'th')).toBe('ผู้จัดการ')
    expect(roleLabel('MANAGER', 'en')).toBe('MANAGER')
    expect(ROLES).toHaveLength(5)
  })
})

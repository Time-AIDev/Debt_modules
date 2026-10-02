import { describe, it, expect } from 'vitest'
import th from './i18n/th.js'
import en from './i18n/en.js'
import { translate, served } from './i18n/index.js'

const slots = (s) => (String(s).match(/\{(\w+)\}/g) || []).sort().join(',')
const THAI = /[\u0E00-\u0E7F]/
const INTERNAL = /(CF1|OD-\d+|OQ-\d+|SVC-\d+|REQ-[A-Z]+-\d+|DEBT-[A-Z]+-\d+)/

describe('dictionaries', () => {
  it('carry identical key sets', () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(th).sort())
  })

  it('have no empty values', () => {
    for (const [k, v] of Object.entries(th)) expect(v, k).toBeTruthy()
    for (const [k, v] of Object.entries(en)) expect(v, k).toBeTruthy()
  })

  it('match interpolation slots between languages', () => {
    for (const key of Object.keys(th)) {
      expect(slots(en[key]), key).toBe(slots(th[key]))
    }
  })

  it('never leak internal decision codes into user-facing copy', () => {
    for (const [k, v] of Object.entries(th)) expect(INTERNAL.test(v), k).toBe(false)
    for (const [k, v] of Object.entries(en)) expect(INTERNAL.test(v), k).toBe(false)
  })

  it('keep Thai out of the English table', () => {
    for (const [k, v] of Object.entries(en)) expect(THAI.test(v), k).toBe(false)
  })
})

describe('translate', () => {
  it('interpolates named slots', () => {
    expect(translate('th', 'rail.caseloadLine', { caseload: 212, cap: 240 })).toBe('ลูกหนี้ 212 ราย จากเพดาน 240')
    expect(translate('en', 'rail.caseloadLine', { caseload: 212, cap: 240 })).toBe('212 debtors of 240 cap')
  })

  it('returns the key when unknown', () => {
    expect(translate('th', 'nope.nope')).toBe('nope.nope')
  })
})

describe('served twins', () => {
  it('never falls back to Thai on an EN surface', () => {
    const obj = { label_th: 'ไทย', label_en: 'English' }
    expect(served(obj, 'label', 'en')).toBe('English')
    expect(served(obj, 'label', 'th')).toBe('ไทย')
  })

  it('prefers EN only when it exists', () => {
    const obj = { label_th: 'ไทย' }
    expect(served(obj, 'label', 'en')).toBe('')
    expect(served(obj, 'label', 'th')).toBe('ไทย')
  })
})

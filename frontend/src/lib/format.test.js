import { describe, it, expect } from 'vitest'
import { money, int, pct, date, when, severity, dpdTone, mondayOf, addDays } from './format.js'

describe('format', () => {
  it('lays out served money with two decimals and no symbol', () => {
    expect(money('48600')).toBe('48,600.00')
    expect(money('3842150.00')).toBe('3,842,150.00')
  })

  it('answers an em dash for absent figures, never 0', () => {
    expect(money(null)).toBe('—')
    expect(int(undefined)).toBe('—')
    expect(pct(null)).toBe('—')
  })

  it('keeps served percent strings intact', () => {
    expect(pct('62.4%')).toBe('62.4%')
    expect(pct('62.4')).toBe('62.4%')
  })

  it('renders ISO dates as dd/mm/yyyy gregorian', () => {
    expect(date('2026-10-23')).toBe('23/10/2026')
    expect(date(null)).toBe('—')
    expect(when('2026-10-23T14:32:00')).toBe('23/10 14:32')
  })

  it('maps risk scores to the five severity steps', () => {
    expect(severity(90)).toBe(5)
    expect(severity(65)).toBe(4)
    expect(severity(41)).toBe(3)
    expect(severity(21)).toBe(2)
    expect(severity(3)).toBe(1)
  })

  it('marks DPD past the 30-day line, and only there', () => {
    expect(dpdTone(74)).toBe('over')
    expect(dpdTone(30)).toBe('over')
    expect(dpdTone(29)).toBe('idle')
    expect(dpdTone(0)).toBe('idle')
    expect(dpdTone(null)).toBe('idle')
    expect(dpdTone(undefined)).toBe('idle')
  })

  it('walks calendar dates from Monday', () => {
    expect(mondayOf('2026-10-23')).toBe('2026-10-19')
    expect(addDays('2026-10-19', 6)).toBe('2026-10-25')
  })
})

import { expect, it } from 'vitest'
import { thaiTime } from './Terminated.jsx'

it('interprets naive legacy stamps as Bangkok regardless of browser timezone', () => {
  const legacy = thaiTime('2026-10-07T08:00:00')
  expect(legacy).toBe(thaiTime('2026-10-07T08:00:00+07:00'))
  expect(legacy).toBe(thaiTime('2026-10-07T01:00:00Z'))
})

it('keeps date-only Bangkok dates and handles unreadable history safely', () => {
  expect(thaiTime('2026-10-07')).toBe(thaiTime('2026-10-07T00:00:00+07:00'))
  expect(thaiTime('invalid')).toBe('ไม่พบหลักฐาน')
  expect(thaiTime(null)).toBe('ไม่พบหลักฐาน')
})

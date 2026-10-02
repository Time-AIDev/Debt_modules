import { afterEach, describe, expect, it, vi } from 'vitest'
import { downloadText } from './download.js'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('CSV text downloads', () => {
  it.each([
    ['without a server BOM', 'display_name,aging_bucket_label_th,next_action_on,missed_basis_th,tier_reason_th\nสมชาย,ค้าง 30 วัน,2026-10-23,ค้างสองงวด,ติดตามด่วน\n'],
    ['with an existing BOM', '\ufeffdisplay_name,aging_bucket_label_th,next_action_on,missed_basis_th,tier_reason_th\nสมชาย,ค้าง 30 วัน,2026-10-23,ค้างสองงวด,ติดตามด่วน\n'],
  ])('writes exactly one UTF-8 BOM %s', (_label, csv) => {
    let blob
    vi.stubGlobal('Blob', class {
      constructor(parts, options) { this.parts = parts; this.type = options.type }
    })
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn((value) => { blob = value; return 'blob:test' }),
      revokeObjectURL: vi.fn(),
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    downloadText('customers.csv', csv)

    expect(blob.type).toBe('text/csv;charset=utf-8')
    expect(blob.parts).toEqual([`\ufeff${csv.replace(/^\ufeff/, '')}`])
    expect(blob.parts[0]).toContain('สมชาย,ค้าง 30 วัน,2026-10-23,ค้างสองงวด,ติดตามด่วน')
  })
})

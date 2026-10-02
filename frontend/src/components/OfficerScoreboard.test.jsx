import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { renderScreen } from '../test-utils.jsx'
import { OfficerScoreboard } from './OfficerScoreboard.jsx'

vi.mock('../lib/api.js', () => ({
  api: new Proxy({}, {
    get: (target, prop) => {
      if (!(prop in target)) target[prop] = vi.fn(async () => ({}))
      return target[prop]
    },
  }),
  CHANGED_EVENT: 'volt:changed',
  AUTH_REQUIRED_EVENT: 'volt:auth-required',
}))
const { api } = await import('../lib/api.js')

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
})

const ROW = {
  officer_uid: 'nantapol', display_name: 'นันทพล', queue_done: 3, queue_today: 10,
  cases: 65, arrears: '151856.00', contact_rate: '100.0%', ptp_kept_rate: '0.0%',
  receipts_month: '0.00',
}

describe('the officer scoreboard (F09)', () => {
  it('prints the six served rows and the served note', async () => {
    api.reportsOfficer.mockResolvedValue({ officer: ROW, note_th: 'ตัวเลขจากเซิร์ฟเวอร์', note_en: 'Served note' })
    renderScreen(<OfficerScoreboard officerUid="nantapol" />)
    expect(await screen.findByText('ความคืบหน้าของเจ้าหน้าที่ · นันทพล')).toBeInTheDocument()
    expect(screen.getByText('3 / 10')).toBeInTheDocument()
    expect(screen.getByText('65')).toBeInTheDocument()
    expect(screen.getByText('151,856.00')).toBeInTheDocument()
    expect(screen.getAllByText('100.0%').length).toBeGreaterThan(0)
    expect(screen.getByText('0.0%')).toBeInTheDocument()
    expect(screen.getByText('0.00')).toBeInTheDocument()
    expect(screen.getByText('ตัวเลขจากเซิร์ฟเวอร์')).toBeInTheDocument()
    expect(api.reportsOfficer).toHaveBeenCalledWith('nantapol')
  })

  it('says no officer is assigned before it calls anything', () => {
    renderScreen(<OfficerScoreboard officerUid={null} />)
    expect(screen.getByText('ยังไม่มอบหมายเจ้าหน้าที่')).toBeInTheDocument()
    expect(api.reportsOfficer).not.toHaveBeenCalled()
  })

  it('renders the served refusal through Problem', async () => {
    api.reportsOfficer.mockRejectedValue({ problem: { code: 'request_failed', message_th: 'โหลดข้อมูลเจ้าหน้าที่ไม่ได้' } })
    renderScreen(<OfficerScoreboard officerUid="ghost" />)
    expect(await screen.findByText('โหลดข้อมูลเจ้าหน้าที่ไม่ได้')).toBeInTheDocument()
  })
})

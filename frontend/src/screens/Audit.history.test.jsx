import { it, expect, vi } from 'vitest'
import { screen, fireEvent } from '@testing-library/react'
import { renderScreen } from '../test-utils.jsx'
import { Audit, auditDateRange } from './Audit.jsx'
vi.mock('../lib/api.js', () => ({ api: { audit: vi.fn(), auditVerify: vi.fn() } }))
const { api } = await import('../lib/api.js')
it('queries complete Bangkok calendar days', () => {
  expect(auditDateRange('2026-10-01', '2026-10-02')).toEqual({ since: '2026-10-01T00:00:00+07:00', until: '2026-10-02T17:00:00.000Z' })
})
it('shows full evidence and an exact snapshot link in audit details', async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
  api.audit.mockResolvedValue({ entries: [{ seq: 1, at: '2026-10-01T10:00:00Z', act: 'CONTRACT_TERMINATED', actor_claimed: 'ploy', outcome: 'OK', request_id: 'r-1', subject_uid: 'c-1', display: { activity_th: 'ยุติสัญญา', customer_name: 'ลูกค้า', reason: 'เหตุผลหนึ่ง\nเหตุผลสอง', case_url: '/terminated/archive-1' } }], meta: { actors: ['ploy'], acts: ['CONTRACT_TERMINATED'] } })
  renderScreen(<Audit />)
  fireEvent.click(await screen.findByRole('button', { name: 'ยุติสัญญา' }))
  expect(screen.getByRole('dialog', { name: 'รายละเอียดกิจกรรม' })).toBeInTheDocument()
  expect(screen.getByText(/เหตุผลหนึ่ง/).textContent).toContain('\nเหตุผลสอง')
  expect(screen.getByRole('link', { name: 'เปิดเคสย้อนหลัง' })).toHaveAttribute('href', '/terminated/archive-1')
  fireEvent.click(screen.getByRole('button', { name: 'ปิด' }))
  expect(screen.queryByRole('dialog')).toBeNull()
})

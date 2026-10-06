import { it, expect, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { renderScreen } from '../test-utils.jsx'
import { Terminated, ArchivedCase } from './Terminated.jsx'
vi.mock('../lib/api.js', () => ({ api: { terminated: vi.fn(), terminatedCase: vi.fn() } }))
const { api } = await import('../lib/api.js')
it('reads the archive without offering case actions and preserves multiline reasons', async () => {
  api.terminatedCase.mockResolvedValue({ archive_uid: 'a', customer_name: 'ลูกค้า ก', reason: 'บรรทัดแรก\nบรรทัดสอง', capture_kind: 'BACKFILL', terminations: [], snapshot: { contracts: [], events: [], customer: {} } })
  renderScreen(<Routes><Route path="/terminated/:uid" element={<ArchivedCase />} /></Routes>, { route: '/terminated/a' })
  expect(await screen.findByText('ลูกค้า ก')).toBeInTheDocument()
  expect(screen.getByText('อ่านอย่างเดียว')).toBeInTheDocument()
  expect(screen.getByText(/บรรทัดแรก/).textContent).toContain('\nบรรทัดสอง')
  expect(screen.queryByRole('button', { name: 'ยุติสัญญา' })).toBeNull()
  expect(screen.queryByRole('button', { name: /บันทึกผลติดต่อ/ })).toBeNull()
})
it('keeps archive filters in the URL and provides an accessible case link', async () => {
  api.terminated.mockResolvedValue({ entries: [{ archive_uid: 'a', customer_name: 'ลูกค้า ข', customer_no: 'C1', causes: ['DEFAULT'], reason: 'เหตุผลครบ' }], meta: { total: 1, actors: [] } })
  renderScreen(<Terminated />, { route: '/terminated?q=C1' })
  expect(await screen.findByRole('link', { name: /ดูเคสย้อนหลัง/ })).toHaveAttribute('href', '/audit/terminated/a')
  expect(screen.getByRole('searchbox', { name: /ค้นหา/ })).toHaveValue('C1')
})

it('does not show the old case while the next archive loads or accept a late response', async () => {
  const { Link } = await import('react-router-dom')
  let resolveFirst, resolveSecond
  api.terminatedCase.mockImplementation((uid) => new Promise((resolve) => { if (uid === 'first') resolveFirst = resolve; else resolveSecond = resolve }))
  const view = renderScreen(<><Link to="/terminated/second">เคสถัดไป</Link><Routes><Route path="/terminated/:uid" element={<ArchivedCase />} /></Routes></>, { route: '/terminated/first' })
  const { fireEvent, act } = await import('@testing-library/react')
  fireEvent.click(screen.getByText('เคสถัดไป'))
  await act(async () => resolveFirst({ customer_name: 'เคสผิด', terminations: [], snapshot: {} }))
  expect(screen.queryByText('เคสผิด')).toBeNull()
  expect(screen.getByRole('status')).toHaveTextContent('กำลังโหลด')
  await act(async () => resolveSecond({ customer_name: 'เคสถูก', terminations: [], snapshot: {} }))
  expect(screen.getByText('เคสถูก')).toBeInTheDocument()
  view.unmount()
})

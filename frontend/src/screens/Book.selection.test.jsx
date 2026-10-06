import { beforeEach, expect, it, vi } from 'vitest'
import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { Book } from './Book.jsx'
import { WORKBOOK } from '../test-fixtures.js'

vi.mock('../lib/api.js', () => ({ api: new Proxy({}, {
  get: (target, key) => target[key] ||= vi.fn(async () => ({})),
}), CHANGED_EVENT: 'volt:changed', AUTH_REQUIRED_EVENT: 'volt:auth-required' }))
vi.mock('../components/RecordView.jsx', () => ({ RecordView: ({ data, onChanged }) => <section>
  <p data-testid="active-case">{data?.customer?.uid || 'loading'}</p>
  <button onClick={onChanged}>save selected case</button>
</section> }))
const { api } = await import('../lib/api.js')
const row = (uid) => ({ ...WORKBOOK.rows[0], customer: { ...WORKBOOK.rows[0].customer,
  uid, display_name: uid, customer_no: `NO-${uid}` } })
const page = (uid, more = false) => ({ ...WORKBOOK, rows: [row(uid)],
  page: { has_more: more, next_cursor: more ? 'next' : null } })

beforeEach(() => {
  vi.clearAllMocks()
  window.localStorage.clear()
  api.workbook.mockResolvedValue(page('first'))
  api.caseDetail.mockImplementation(async (uid) => ({ customer: { uid } }))
})

it('keeps a selected case beyond the loaded page after a write reload', async () => {
  api.workbook.mockResolvedValueOnce(page('first', true))
    .mockResolvedValueOnce(page('second')).mockResolvedValueOnce(page('first', true))
  const user = userEvent.setup()
  renderScreen(<Book />)
  await user.click(await screen.findByRole('button', { name: 'โหลดเพิ่ม' }))
  await user.click(await screen.findByText('second'))
  await waitFor(() => expect(screen.getByTestId('active-case')).toHaveTextContent('second'))
  await user.click(screen.getByRole('button', { name: 'save selected case' }))
  await waitFor(() => expect(api.workbook).toHaveBeenCalledTimes(3))
  await waitFor(() => expect(screen.getByTestId('active-case')).toHaveTextContent('second'))
  expect(api.caseDetail).toHaveBeenLastCalledWith('second')
})

it('ignores an old case response after the selected case changes', async () => {
  let resolveOld
  api.workbook.mockResolvedValue({ ...WORKBOOK, rows: [row('first'), row('second')] })
  api.caseDetail.mockImplementation((uid) => uid === 'first'
    ? new Promise((resolve) => { resolveOld = resolve }) : Promise.resolve({ customer: { uid } }))
  const user = userEvent.setup()
  renderScreen(<Book />)
  await user.click(await screen.findByText('second'))
  await waitFor(() => expect(screen.getByTestId('active-case')).toHaveTextContent('second'))
  await act(async () => resolveOld({ customer: { uid: 'first' } }))
  expect(screen.getByTestId('active-case')).toHaveTextContent('second')
})

it('rejects a detail body for a different selected customer', async () => {
  api.caseDetail.mockResolvedValue({ customer: { uid: 'other' } })
  renderScreen(<Book />, { route: '/book?sel=selected' })
  await waitFor(() => expect(api.caseDetail).toHaveBeenCalledWith('selected'))
  expect(screen.getByTestId('active-case')).not.toHaveTextContent('other')
})

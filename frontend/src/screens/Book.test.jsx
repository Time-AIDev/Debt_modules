import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, within, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { Book } from './Book.jsx'
import { WORKBOOK, CASE, DICTIONARIES } from '../test-fixtures.js'

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
vi.mock('../lib/download.js', () => ({ downloadText: vi.fn(), downloadBlob: vi.fn() }))
const { api } = await import('../lib/api.js')
const { downloadText } = await import('../lib/download.js')

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
  api.workbook.mockResolvedValue(WORKBOOK)
  api.caseDetail.mockResolvedValue(CASE)
  api.dictionary.mockImplementation(async (name) => DICTIONARIES[name] || { name, values: [] })
})

describe('Book', () => {
  it('restores company/search/sort filters from the URL and includes company in exports', async () => {
    api.workbookExport.mockResolvedValue({ filename: 'book.csv', text: 'customer_uid\n' })
    const user = userEvent.setup()
    renderScreen(<Book />, { route: '/book?entity=EPC&q=C1&sort=display_name&dir=asc' })
    await waitFor(() => expect(api.workbook).toHaveBeenCalledWith({ entity: 'EPC', q: 'C1',
      sort: 'display_name', dir: 'asc', identities: 1, limit: 50 }))
    expect(screen.getByRole('combobox', { name: 'EPC/SPV' })).toHaveValue('EPC')
    await user.click(screen.getByRole('button', { name: 'ส่งออก CSV' }))
    expect(api.workbookExport).toHaveBeenCalledWith({ entity: 'EPC', q: 'C1', sort: 'display_name', dir: 'asc', identities: 1 })
  })

  it('groups rows by the served aging band and shows the served source', async () => {
    renderScreen(<Book />)
    expect(await screen.findByText('ค้างไม่ถึง 30 วัน')).toBeInTheDocument()
    expect(screen.getByText('ค้าง 90 วันขึ้นไป')).toBeInTheDocument()
    expect(screen.getByText('New Order Master')).toBeInTheDocument()
  })

  it('carries the compact payment position on a book row', async () => {
    renderScreen(<Book />)
    const rows = await screen.findAllByTestId('payment-position')
    expect(rows.length).toBeGreaterThan(0)
    expect(within(rows[0]).getByTestId('pp-counts')).toHaveTextContent('จ่าย 11 · ค้าง 4')
  })

  it('keeps each customer row to identity, payment counts, and issue status', async () => {
    renderScreen(<Book />)
    const list = screen.getByRole('complementary', { name: 'ลูกค้า / สมุดงาน' })
    const customer = await within(list).findByRole('button', { name: /ปัทมวรรณ/ })
    expect(customer).toHaveTextContent('V-1001')
    expect(customer).toHaveTextContent('จ่าย 11 · ค้าง 4')
    expect(customer).not.toHaveTextContent('SPV')
    expect(customer).not.toHaveTextContent('48,600.00')
    expect(within(customer).getByRole('img', { name: 'ไม่มี issue ticket เปิดอยู่' })).toBeInTheDocument()
  })

  it('asks the server for the workbook with sort and search', async () => {
    const user = userEvent.setup()
    renderScreen(<Book />)
    await screen.findByText('ค้างไม่ถึง 30 วัน')
    await user.type(screen.getByPlaceholderText('ค้นหาในสมุดงาน'), 'สมศรี')
    await waitFor(() => expect(api.workbook).toHaveBeenLastCalledWith({ sort: 'aggregate_overdue', dir: 'desc', identities: 1, limit: 50, q: 'สมศรี' }))
  })

  it('loads the next cursor page and appends it without losing the first page', async () => {
    const user = userEvent.setup()
    const first = {
      ...WORKBOOK,
      rows: [WORKBOOK.rows[0]],
      page: { limit: 50, returned: 1, has_more: true, next_cursor: 'next-50' },
    }
    const second = {
      ...WORKBOOK,
      rows: [WORKBOOK.rows[1]],
      page: { limit: 50, returned: 1, has_more: false, next_cursor: null },
    }
    api.workbook.mockResolvedValueOnce(first).mockResolvedValueOnce(second)
    renderScreen(<Book />)
    const list = screen.getByRole('complementary', { name: 'ลูกค้า / สมุดงาน' })
    expect(await within(list).findByText('ปัทมวรรณ สุขเจริญ')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'โหลดเพิ่ม' }))
    expect(await within(list).findByText('สมศรี พงษ์ไพบูลย์')).toBeInTheDocument()
    expect(api.workbook).toHaveBeenLastCalledWith({
      sort: 'aggregate_overdue', dir: 'desc', identities: 1, limit: 50, cursor: 'next-50',
    })
    expect(within(list).getByText('ปัทมวรรณ สุขเจริญ')).toBeInTheDocument()
  })

  it('restarts from page one when a load-more cursor becomes stale', async () => {
    const user = userEvent.setup()
    const first = {
      ...WORKBOOK,
      rows: [WORKBOOK.rows[0]],
      page: { limit: 50, returned: 1, has_more: true, next_cursor: 'stale-50' },
    }
    const refreshed = {
      ...WORKBOOK,
      rows: [WORKBOOK.rows[1]],
      page: { limit: 50, returned: 1, has_more: false, next_cursor: null },
    }
    api.workbook
      .mockResolvedValueOnce(first)
      .mockRejectedValueOnce({ problem: { code: 'workbook_cursor_stale' } })
      .mockResolvedValueOnce(refreshed)
    renderScreen(<Book />)
    const list = screen.getByRole('complementary', { name: 'ลูกค้า / สมุดงาน' })
    await within(list).findByText('ปัทมวรรณ สุขเจริญ')
    await user.click(screen.getByRole('button', { name: 'โหลดเพิ่ม' }))
    expect(await within(list).findByText('สมศรี พงษ์ไพบูลย์')).toBeInTheDocument()
    expect(api.workbook).toHaveBeenLastCalledWith({
      sort: 'aggregate_overdue', dir: 'desc', identities: 1, limit: 50,
    })
    expect(within(list).queryByText('ปัทมวรรณ สุขเจริญ')).not.toBeInTheDocument()
  })

  it('runs the governed export only with a stated reason', async () => {
    api.workbookExportGoverned.mockResolvedValue({ text: 'a,b', filename: 'wb.csv' })
    const user = userEvent.setup()
    renderScreen(<Book />)
    await screen.findByText('ค้างไม่ถึง 30 วัน')
    await user.click(screen.getByRole('button', { name: 'ส่งออกอย่างเป็นทางการ' }))
    const dialog = await screen.findByRole('dialog')
    const run = within(dialog).getByRole('button', { name: 'ส่งออก' })
    expect(run).toBeDisabled()
    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'ตรวจยอดกับ AR' } })
    expect(run).toBeEnabled()
    await user.click(run)
    await waitFor(() => expect(api.workbookExportGoverned).toHaveBeenCalledWith({ reason: 'ตรวจยอดกับ AR', sort: 'aggregate_overdue', dir: 'desc', identities: 1 }))
    expect(downloadText).toHaveBeenCalledWith('wb.csv', 'a,b')
  })
})

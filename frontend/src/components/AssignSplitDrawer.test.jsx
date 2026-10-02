import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { AssignSplitDrawer } from './AssignSplitDrawer.jsx'
import { OFFICERS } from '../test-fixtures.js'

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

const BUCKETS = [
  { code: 'CURRENT', label_th: 'ปกติ', label_en: 'Current', count: 500, unassigned: 500 },
  { code: 'NPL', label_th: 'NPL ยืนยันแล้ว', label_en: 'NPL confirmed', count: 12, unassigned: 0 },
]

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
  api.assignSplitBuckets.mockResolvedValue(BUCKETS)
  api.assignSplit.mockResolvedValue({
    seed: '2026-10-23-abcd1234', total: 500, dry_run: true, assigned: [],
    per_officer: [{ officer_uid: 'rungnapa', count: 250 }, { officer_uid: 'somchai', count: 250 }],
  })
  api.assignTemplate.mockResolvedValue({ text: 'volt_id,customer_no,officer\n', filename: 'assignments-template.csv' })
})

function drawer(over = {}) {
  return (
    <AssignSplitDrawer
      open
      onClose={() => {}}
      officers={OFFICERS.officers}
      totals={{ rungnapa: 12, somchai: 30 }}
      onDone={() => {}}
      {...over}
    />
  )
}

describe('the portfolio split drawer (F10b, F10c)', () => {
  it('renders the served buckets and officers and previews the served counts', async () => {
    const user = userEvent.setup()
    renderScreen(drawer())
    expect(await screen.findByText('แบ่งพอร์ตลูกค้า')).toBeInTheDocument()
    expect(await screen.findByText(/ปกติ \(CURRENT\) · 500 บัญชี/)).toBeInTheDocument()
    expect(screen.getByText(/NPL ยืนยันแล้ว \(NPL\) · 12 บัญชี/)).toBeInTheDocument()
    expect(screen.getByText('รุ่งนภา ทองดี')).toBeInTheDocument()
    expect(screen.getByText('ดูแลอยู่ 12 ราย')).toBeInTheDocument()
    await user.click(screen.getByLabelText(/รุ่งนภา/))
    await user.click(screen.getByLabelText(/สมชาย/))
    await user.click(screen.getByRole('button', { name: 'ตัวอย่างผลลัพธ์' }))
    await waitFor(() => expect(api.assignSplit).toHaveBeenCalled())
    expect(api.assignSplit.mock.calls[0][0]).toMatchObject({
      bucket: 'CURRENT', officer_uids: ['rungnapa', 'somchai'], dry_run: true,
    })
    expect(await screen.findByText(/รุ่งนภา ทองดี 250 · สมชาย ใจกล้า 250/)).toBeInTheDocument()
    expect(await screen.findByText(/500 บัญชี →/)).toBeInTheDocument()
    expect(await screen.findByText(/สุ่มด้วย seed 2026-10-23-abcd1234/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'มอบหมาย 500 บัญชี' }))
    await waitFor(() => expect(api.assignSplit).toHaveBeenCalledTimes(2))
    expect(api.assignSplit.mock.calls[1][0]).toMatchObject({ dry_run: false })
  })

  it('shows the server\u2019s refusal when the preview names no officer', async () => {
    const user = userEvent.setup()
    api.assignSplit.mockRejectedValue({
      problem: {
        code: 'validation_failed', message_th: 'ข้อมูลไม่ถูกต้อง',
        errors: [{ pointer: '/officer_uids', code: 'required', message_th: 'เลือกพนักงานอย่างน้อย 1 คนที่จะรับผิดชอบกลุ่มนี้' }],
      },
    })
    renderScreen(drawer())
    await screen.findByText(/ปกติ \(CURRENT\) · 500 บัญชี/)
    await user.click(screen.getByRole('button', { name: 'ตัวอย่างผลลัพธ์' }))
    expect(await screen.findByText('เลือกพนักงานอย่างน้อย 1 คนที่จะรับผิดชอบกลุ่มนี้')).toBeInTheDocument()
    expect(api.assignSplit.mock.calls[0][0]).toMatchObject({ officer_uids: [], dry_run: true })
    expect(screen.queryByRole('button', { name: /^มอบหมาย/ })).not.toBeInTheDocument()
  })

  it('disables the confirm with its reason when the preview deals nothing', async () => {
    const user = userEvent.setup()
    api.assignSplit.mockResolvedValue({ seed: 's-0', total: 0, dry_run: true, assigned: [], per_officer: [{ officer_uid: 'rungnapa', count: 0 }] })
    renderScreen(drawer())
    await screen.findByText(/ปกติ \(CURRENT\) · 500 บัญชี/)
    await user.click(screen.getByLabelText(/รุ่งนภา/))
    await user.click(screen.getByRole('button', { name: 'ตัวอย่างผลลัพธ์' }))
    const confirm = await screen.findByRole('button', { name: 'มอบหมาย 0 บัญชี' })
    expect(confirm).toBeDisabled()
    expect(confirm).toHaveAttribute('title', 'ไม่มีบัญชีที่ยังไม่มอบหมายในกลุ่มนี้')
    expect(screen.getByText('ไม่มีบัญชีที่ยังไม่มอบหมายในกลุ่มนี้')).toBeInTheDocument()
  })

  it('downloads the template through the role-carrying fetch and uploads a file', async () => {
    const user = userEvent.setup()
    renderScreen(drawer())
    await screen.findByText(/ปกติ \(CURRENT\) · 500 บัญชี/)
    await user.click(screen.getByRole('radio', { name: 'สุ่มแบ่งเท่ากัน' }))
    await user.click(screen.getByRole('radio', { name: 'อัปโหลดไฟล์แบ่งงาน (เทมเพลต)' }))
    await user.click(screen.getByRole('button', { name: 'ดาวน์โหลดเทมเพลต' }))
    await waitFor(() => expect(api.assignTemplate).toHaveBeenCalled())

    api.assignTemplateUpload.mockResolvedValue({ count: 3, officer_uids: ['rungnapa'], assigned: ['a', 'b', 'c'] })
    const file = new File(['volt_id,customer_no,officer\n'], 'assignments.csv', { type: 'text/csv' })
    const input = document.querySelector('input[type="file"]')
    await user.upload(input, file)
    await waitFor(() => expect(api.assignTemplateUpload).toHaveBeenCalledWith(
      file, expect.objectContaining({ signal: expect.any(AbortSignal), onProgress: expect.any(Function) }),
    ))
    expect((await screen.findAllByText('มอบหมายแล้ว 3 บัญชี')).length).toBeGreaterThan(0)
  })

  it('renders the served refusal list when the file is refused', async () => {
    const user = userEvent.setup()
    api.assignTemplateUpload.mockRejectedValue({
      problem: {
        code: 'validation_failed', message_th: 'ไฟล์ถูกปฏิเสธ',
        errors: [
          { pointer: '/rows/2', code: 'officer_unknown', message_th: 'แถวที่ 2 ไม่รู้จักเจ้าหน้าที่' },
          { pointer: '/rows/3', code: 'duplicate', message_th: 'แถวที่ 3 ซ้ำ' },
        ],
      },
    })
    renderScreen(drawer())
    await screen.findByText(/ปกติ \(CURRENT\) · 500 บัญชี/)
    await user.click(screen.getByRole('radio', { name: 'สุ่มแบ่งเท่ากัน' }))
    await user.click(screen.getByRole('radio', { name: 'อัปโหลดไฟล์แบ่งงาน (เทมเพลต)' }))
    const file = new File(['x'], 'assignments.csv', { type: 'text/csv' })
    await user.upload(document.querySelector('input[type="file"]'), file)
    expect(await screen.findByText('แถวที่ 2 ไม่รู้จักเจ้าหน้าที่')).toBeInTheDocument()
    expect(screen.getByText('แถวที่ 3 ซ้ำ')).toBeInTheDocument()
    expect(api.assignTemplateUpload).toHaveBeenCalled()
  })
})

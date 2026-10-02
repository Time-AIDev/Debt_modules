import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { Pipeline } from './Pipeline.jsx'

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
vi.mock('../lib/download.js', () => ({ downloadBlob: vi.fn(), downloadText: vi.fn() }))
const { api } = await import('../lib/api.js')
const { downloadBlob } = await import('../lib/download.js')

const CONDITION = (key, label, evidence = []) => ({
  key,
  label_th: label,
  label_en: label,
  note_th: '',
  note_en: '',
  passed: key === 'down_payment',
  state_label_th: key === 'down_payment' ? 'ผ่าน' : 'ค้าง',
  state_label_en: key === 'down_payment' ? 'Passed' : 'Held',
  attach_label_th: 'แนบหลักฐาน',
  attach_label_en: 'Attach evidence',
  evidence_count: evidence.length,
  evidence,
  evidence_scope: `pipeline:PL-1:condition:${key}`,
})

const ITEM = {
  uid: 'PL-1',
  display_name: 'บริษัท ทดสอบ จำกัด',
  customer_no: 'C-001',
  entity: 'SPC',
  amount_due: '100000',
  case_dpd: null,
  risk_score: 40,
  planned_install_on: '2026-09-25',
  released_at: null,
  conditions: [
    CONDITION('down_payment', 'รับเงินดาวน์', [{
      uid: 'ev-1', note: 'สลิปโอนเงินดาวน์', file_uid: 'att-1', uploaded_at: '2026-09-19T10:00:00Z',
    }]),
    CONDITION('contract_signed', 'เซ็นสัญญา'),
    CONDITION('entity_resolved', 'ระบุบริษัท', [{ uid: 'ev-2', note: 'เอกสารยืนยัน', file_uid: null, uploaded_at: '2026-09-19T11:00:00Z' }]),
  ],
}

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
  api.pipeline.mockResolvedValue({ items: [ITEM], meta: { total: 1, invoice_owner_role: 'COLLECTION' } })
  api.attachments.mockImplementation(async (scope) => ({
    attachments: scope.endsWith('down_payment')
      ? [{ uid: 'att-1', filename: 'slip.pdf', uploaded_at: '2026-09-19T10:00:00Z' }]
      : [],
  }))
})

describe('Pipeline evidence', () => {
  it('shows a served evidence file by name and views it', async () => {
    api.downloadAttachment.mockResolvedValue({ blob: new Blob(['x']), filename: 'slip.pdf' })
    const user = userEvent.setup()
    renderScreen(<Pipeline />)
    expect(await screen.findByText(/slip\.pdf/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'เปิดดู' }))
    await waitFor(() => expect(api.downloadAttachment).toHaveBeenCalledWith('att-1'))
    expect(downloadBlob).toHaveBeenCalledWith('slip.pdf', expect.any(Blob))
  })

  it('uploads a file in the drawer and attaches it by uid, note optional', async () => {
    const user = userEvent.setup()
    api.uploadAttachment.mockResolvedValue({ attachment: { uid: 'att-9', filename: 'deed.pdf' } })
    api.pipelineConditionEvidence.mockResolvedValue({})
    renderScreen(<Pipeline />)
    await screen.findByText(/slip\.pdf/)
    await user.click(screen.getAllByRole('button', { name: 'แนบหลักฐาน' })[1])
    const dialog = await screen.findByRole('dialog')
    await user.upload(within(dialog).getByLabelText('แนบไฟล์หลักฐาน'), new File(['x'], 'deed.pdf', { type: 'application/pdf' }))
    await waitFor(() => expect(api.uploadAttachment).toHaveBeenCalled())
    const run = within(dialog).getByRole('button', { name: 'แนบหลักฐาน' })
    expect(run).toBeEnabled()
    await user.click(run)
    await waitFor(() => expect(api.pipelineConditionEvidence).toHaveBeenCalledWith(
      'PL-1', 'contract_signed', expect.objectContaining({ file_uid: 'att-9' }),
    ))
  })

  it('keeps the attach verb disabled with neither a note nor a file', async () => {
    const user = userEvent.setup()
    renderScreen(<Pipeline />)
    await screen.findByText(/slip\.pdf/)
    await user.click(screen.getAllByRole('button', { name: 'แนบหลักฐาน' })[1])
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('button', { name: 'แนบหลักฐาน' })).toBeDisabled()
  })
})

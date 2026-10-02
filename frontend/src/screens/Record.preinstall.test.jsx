import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { Record } from './Record.jsx'
import { CASE } from '../test-fixtures.js'

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

function condition(key, over) {
  return {
    key,
    label_th: { contract_signed: 'สัญญาลงนามแล้ว', down_payment: 'ได้รับเงินดาวน์', entity_resolved: 'ระบุบริษัทได้' }[key],
    label_en: key,
    note_th: 'คำอธิบาย', note_en: 'note',
    state: 'OPEN', passed: false, evidence: [], evidence_count: 0,
    evidence_scope: `pipeline:pip-00001:condition:${key}`,
    state_label_th: 'ยังไม่ผ่าน', state_label_en: 'Open',
    attach_label_th: 'แนบหลักฐาน', attach_label_en: 'Attach evidence',
    ...over,
  }
}

function pipelineItem(over = {}) {
  return {
    uid: 'pip-00001', customer_uid: 'c-1', display_name: 'ปัทมวรรณ สุขเจริญ',
    amount_due: null, amount_hint: '5000.00', planned_install_on: '2026-10-25',
    confirmed_install_on: null, released_at: null,
    gate_down_payment: { state: 'OPEN', ref: null, on: null, by: null },
    gate_epc_confirmed: { state: 'OPEN', ref: null, on: null, by: null, source: null },
    conditions: [
      condition('contract_signed'),
      condition('down_payment'),
      condition('entity_resolved', { state: 'PASSED', passed: true }),
    ],
    ...over,
  }
}

function preInstallCase(item, over = {}) {
  return {
    ...CASE,
    pre_install: true,
    pipeline_item: item,
    pipeline_meta: { invoice_owner_role: 'AR' },
    events: [
      { kind: 'CASE_OPENED', case_uid: 'case-c-1', on: '2026-10-20', by: 'SYSTEM', reason: 'เปิดเคส' },
      { kind: 'CONDITION_EVIDENCE_ATTACHED', case_uid: 'case-c-1', on: '2026-10-21', by: 'thip', condition: 'down_payment' },
    ],
    ...over,
  }
}

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
  api.attachments.mockResolvedValue({ attachments: [] })
})

describe('the pre-install card on the customer case', () => {
  it('renders the conditions and the evidence actions on the case page', async () => {
    api.caseDetail.mockResolvedValue(preInstallCase(pipelineItem()))
    renderScreen(<Record />, { route: '/customers/c-1' })

    const invoices = await screen.findByRole('tab', { name: 'ใบแจ้งหนี้และเงินเข้า' })
    await waitFor(() => expect(invoices).toHaveAttribute('aria-selected', 'true'))
    expect(await screen.findByText('เงื่อนไขก่อนติดตั้งบนเคสนี้')).toBeInTheDocument()
    expect(screen.getByText('สัญญาลงนามแล้ว')).toBeInTheDocument()
    expect(screen.getByText('ได้รับเงินดาวน์')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'แนบหลักฐาน' }).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: 'ปล่อยใบแจ้งหนี้' })).toBeDisabled()
  })

  it('moves between case tabs with the keyboard', async () => {
    const user = userEvent.setup()
    api.caseDetail.mockResolvedValue(preInstallCase(pipelineItem()))
    renderScreen(<Record />, { route: '/customers/c-1' })

    const invoices = await screen.findByRole('tab', { name: 'ใบแจ้งหนี้และเงินเข้า' })
    await waitFor(() => expect(invoices).toHaveAttribute('aria-selected', 'true'))
    invoices.focus()
    await user.keyboard('{ArrowRight}')

    const history = screen.getByRole('tab', { name: /ประวัติการติดต่อ/ })
    await waitFor(() => expect(history).toHaveFocus())
    expect(history).toHaveAttribute('aria-selected', 'true')
    await user.keyboard('{Home}')
    await waitFor(() => expect(screen.getByRole('tab', { name: 'ภาพรวมเคส' })).toHaveFocus())
  })

  it('opens the served Odoo CRM record from the customer name without leaking opener access', async () => {
    api.caseDetail.mockResolvedValue(preInstallCase(pipelineItem(), {
      customer: {
        ...CASE.customer,
        odoo_crm: { model: 'crm.lead', record_id: 74482,
          url: 'https://odoo.example.com/web#id=74482&model=crm.lead&view_type=form' },
      },
    }))
    renderScreen(<Record />, { route: '/customers/c-1' })
    const link = await screen.findByRole('link', { name: CASE.customer.display_name })
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(link).toHaveAttribute('href', expect.stringContaining('model=crm.lead'))
  })

  it('attaches evidence to a condition and refreshes the case', async () => {
    const user = userEvent.setup()
    api.caseDetail.mockResolvedValue(preInstallCase(pipelineItem()))
    api.pipelineConditionEvidence.mockResolvedValue({})
    renderScreen(<Record />, { route: '/customers/c-1' })

    const attachButtons = await screen.findAllByRole('button', { name: 'แนบหลักฐาน' })
    await user.click(attachButtons[0])
    const noteField = await screen.findByLabelText('บันทึกประกอบหลักฐาน')
    expect(noteField).not.toHaveAttribute('aria-required')
    // the "one of the two" rule rides the attach verb as its tooltip (a notice, design D)
    expect(within(screen.getByRole('dialog')).getByRole('button', { name: 'แนบหลักฐาน' }))
      .toHaveAttribute('title', 'แนบอย่างน้อย 1 อย่าง: บันทึก หรือ ไฟล์')
    await user.type(noteField, 'สำเนาสัญญาที่ลงนาม')
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'แนบหลักฐาน' }))

    await waitFor(() => expect(api.pipelineConditionEvidence).toHaveBeenCalledWith(
      'pip-00001', 'contract_signed', expect.objectContaining({ note: 'สำเนาสัญญาที่ลงนาม' })))
    expect(api.caseDetail.mock.calls.length).toBeGreaterThan(1)
  })

  it('records the down-payment gate from the case, with its amount', async () => {
    const user = userEvent.setup()
    api.caseDetail.mockResolvedValue(preInstallCase(pipelineItem()))
    api.pipelineGateDownPayment.mockResolvedValue({})
    renderScreen(<Record />, { route: '/customers/c-1' })

    await user.click(await screen.findByRole('button', { name: 'บันทึกว่าได้รับเงินดาวน์' }))
    const ref = await screen.findByLabelText(/เลขที่อ้างอิงสลิป/)
    expect(ref).toHaveAttribute('aria-required', 'true')
    // the red * says "required"; the "* ช่องที่ต้องกรอก" notice is gone (brief §3.4)
    expect(ref.closest('label')).toHaveTextContent('*')
    expect(screen.queryByText('* ช่องที่ต้องกรอก')).toBeNull()
    await user.type(ref, 'slip-9')
    expect(ref).toHaveValue('slip-9')
    const amount = screen.getByLabelText(/ยอดเงินดาวน์/)
    await user.clear(amount)
    await user.type(amount, '5000.00')
    const save = screen.getByRole('button', { name: 'บันทึก' })
    expect(save).toBeEnabled()
    await user.click(save)

    await waitFor(() => expect(api.pipelineGateDownPayment).toHaveBeenCalledWith(
      'pip-00001', expect.objectContaining({ slip_ref: 'slip-9', amount: '5000.00' })))
  })

  it('releases only when every condition is passed', async () => {
    const user = userEvent.setup()
    const passed = ['contract_signed', 'down_payment', 'entity_resolved'].map((k) =>
      condition(k, { state: 'PASSED', passed: true }))
    api.caseDetail.mockResolvedValue(preInstallCase(pipelineItem({
      conditions: passed,
      amount_due: '5000.00',
      gate_down_payment: { state: 'PASSED', ref: 'slip-9', on: '2026-10-20', by: 'thip' },
      gate_epc_confirmed: { state: 'PASSED', ref: '2026-10-22', on: '2026-10-20', by: 'thip', source: 'ODOO' },
    })))
    api.pipelineRelease.mockResolvedValue({})
    renderScreen(<Record />, { route: '/customers/c-1' })

    const release = await screen.findByRole('button', { name: 'ปล่อยใบแจ้งหนี้' })
    expect(release).toBeEnabled()
    await user.click(release)

    await waitFor(() => expect(api.pipelineRelease).toHaveBeenCalledWith('pip-00001', expect.anything()))
  })

  it('shows the case events on the history tab', async () => {
    const user = userEvent.setup()
    api.caseDetail.mockResolvedValue(preInstallCase(pipelineItem()))
    renderScreen(<Record />, { route: '/customers/c-1' })

    await user.click(await screen.findByRole('tab', { name: /ประวัติการติดต่อ/ }))
    expect(await screen.findByText('เหตุการณ์ของเคส')).toBeInTheDocument()
    expect(screen.getByText('เปิดเคส')).toBeInTheDocument()
    expect(screen.getByText('แนบหลักฐานเงื่อนไข')).toBeInTheDocument()
  })

  it('opens a condition\'s evidence LIST from ดูหลักฐาน (it used to open the attach form)', async () => {
    const user = userEvent.setup()
    api.caseDetail.mockResolvedValue(preInstallCase(pipelineItem({
      conditions: [
        condition('contract_signed', {
          state: 'PASSED', passed: true, evidence_count: 1, attach_label_th: 'ดูหลักฐาน',
          evidence: [{ uid: 'ev-1', note: 'สัญญาลงนามครบทั้งสองฝ่าย', file_uid: null, uploaded_at: '2026-10-21T16:20:00+07:00' }],
        }),
        condition('down_payment'),
        condition('entity_resolved'),
      ],
    })))
    renderScreen(<Record />, { route: '/customers/c-1' })
    const view = await screen.findByRole('button', { name: 'ดูหลักฐาน' })
    expect(view).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('สัญญาลงนามครบทั้งสองฝ่าย')).toBeNull()
    await user.click(view)
    expect(screen.getByText('สัญญาลงนามครบทั้งสองฝ่าย')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ซ่อนหลักฐาน' })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})

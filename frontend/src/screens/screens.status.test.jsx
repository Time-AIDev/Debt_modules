import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { setRole, setRoster } from '../lib/identity.jsx'
import { Payments } from './Payments.jsx'
import { Reviews } from './Reviews.jsx'
import { Reports } from './Reports.jsx'
import { Audit } from './Audit.jsx'
import { Settings } from './Settings.jsx'
import { Dashboard } from './Dashboard.jsx'
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
const { api } = await import('../lib/api.js')

const REJECTED = {
  uid: 'pkd-1', customer_name: 'บริษัท ทดสอบ จำกัด', entity: 'EPC', intent: 'INVOICE_CREATE',
  state: 'REJECTED', rejection_reason: 'เลขผู้เสียภาษีไม่ตรง', risk_score: 40,
}
const ALLOCATION = {
  lines: [
    { state: 'ALLOCATED', label_th: 'จัดสรรแล้ว', label_en: 'Allocated', tone: 'current', count: 1, amount: '100.00' },
    { state: 'AWAITING_RULING', label_th: 'รอคำตัดสิน', label_en: 'Awaiting the ruling', tone: 'held', count: 2, amount: '20399.00' },
  ],
}

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
  setRole('OFFICER')
  api.peakDocuments.mockResolvedValue({ documents: [REJECTED], meta: { counts: { REJECTED: 1 }, write_mode: 'DRAFT_ONLY', allocation: ALLOCATION } })
  api.weeklyReport.mockResolvedValue({ period: { label: 'WK' }, management_summary: {}, portfolio: {}, promises: {}, npl_movement: {} })
  api.ptpReport.mockResolvedValue({ rows: [], totals: {}, meta: { statuses: [] } })
  api.officers.mockResolvedValue({ officers: [] })
})

describe('the status language on the undesigned screens', () => {
  it('payments: the refused draft wears the problem icon and its resubmit says the manager rule', async () => {
    renderScreen(<Payments />)
    const resubmit = await screen.findByRole('button', { name: 'แก้แล้วส่งใหม่' })
    expect(resubmit).toBeDisabled()
    expect(resubmit).toHaveAttribute('title', 'เฉพาะผู้จัดการขึ้นไป')
    expect(screen.getByText('เฉพาะผู้จัดการขึ้นไป')).toBeInTheDocument()
    // the write mode is said in words, the allocation lines wear their status icons
    expect(screen.getByText('สร้างได้แค่ร่าง')).toHaveAttribute('title', 'DRAFT_ONLY')
    expect(screen.getByText('จัดสรรแล้ว').closest('.pill').querySelector('svg.st--done')).not.toBeNull()
    expect(screen.getByText('รอคำตัดสิน').closest('.pill').querySelector('svg.st--off')).not.toBeNull()
    expect(document.querySelector('.group__head svg.st--problem')).not.toBeNull()
    // the served intent reads as words; the owner-only stub switch is shown disabled with its reason
    expect(screen.getByText(/pkd-1 · EPC · ใบแจ้งหนี้/)).toBeInTheDocument()
    const stub = screen.getByRole('button', { name: 'เปิด PEAK จำลอง' })
    expect(stub).toBeDisabled()
    expect(stub).toHaveAttribute('title', 'เฉพาะเจ้าของระบบ')
  })

  it('payments: a manager resubmits the refused draft', async () => {
    setRole('MANAGER')
    api.peakResubmit.mockResolvedValue({})
    const user = userEvent.setup()
    renderScreen(<Payments />)
    const resubmit = await screen.findByRole('button', { name: 'แก้แล้วส่งใหม่' })
    expect(resubmit).toBeEnabled()
    await user.click(resubmit)
    await waitFor(() => expect(api.peakResubmit).toHaveBeenCalledWith('pkd-1', {}))
  })

  it('reviews: an answered review names its decision in words, not the code', async () => {
    api.reviews.mockResolvedValue({
      reviews: [{
        uid: 'rv-9', display_name: 'สมศรี พงษ์ไพบูลย์', customer_uid: 'c-2', status: 'DECIDED', decision: 'NPL_TYPE_SET',
        sla_breached: true, reason_label: 'เกณฑ์ NPL', question_th: 'ขอตั้งประเภท NPL', raised_at: '2026-09-14',
        aggregate_overdue: '1000.00', oldest_dpd: 95, risk_score: 60,
        decisions: [{ code: 'NPL_TYPE_SET', label_th: 'ตั้งประเภท NPL', label_en: 'Set the NPL type' }],
        evidence: { kept_ptp_count: 0, broken_ptp_count: 2, last_contacts: [] },
      }],
      meta: { open: 0, decisions: [], npl_types: [], sla_hours: 48 },
    })
    renderScreen(<Reviews />)
    const answered = await screen.findByText('ตอบแล้ว · ตั้งประเภท NPL')
    expect(answered.closest('.pill')).toHaveClass('pill--done')
    expect(screen.queryByText('NPL_TYPE_SET')).toBeNull()
    // the SLA breach is a problem, in the row and in the head
    expect(screen.getAllByText('เกิน SLA').every((el) => el.closest('.pill--problem'))).toBe(true)
  })

  it('reports: an edition shows its served status, a replaced one as superseded', async () => {
    api.weeklyEditions.mockResolvedValue({
      editions: [
        { edition_uid: 'wke-00002', period: '2026-10-17..2026-10-23', status: 'PUBLISHED', cash_total: '10.00', ptp_kept: 1, ptp_total: 2 },
        { edition_uid: 'wke-00001', period: '2026-10-17..2026-10-23', status: 'SUPERSEDED', cash_total: '5.00', ptp_kept: 0, ptp_total: 1 },
      ],
    })
    renderScreen(<Reports />)
    expect(await screen.findByText('wke-00002')).toBeInTheDocument()
    expect(screen.getByText('เผยแพร่แล้ว').closest('.pill')).toHaveClass('pill--done')
    expect(screen.getByText('ถูกแทนที่').closest('.pill').querySelector('svg.st--off')).not.toBeNull()
    expect(screen.getAllByText('17/10/2026 – 23/10/2026')).toHaveLength(2)
  })

  it('reports: the portfolio head-count wears the payment-status pills and says its unit', async () => {
    api.weeklyReport.mockResolvedValue({
      period: { label: '2026-10-17..2026-10-23' }, management_summary: {}, promises: {}, npl_movement: {},
      portfolio: { current: 57, late: 88, npl: 5, in_collection: 150, unit_th: 'นับหัวลูกค้า ณ วันทำการ', unit_en: 'Head count', ratio_late_pct: '58.7' },
    })
    api.weeklyEditions.mockResolvedValue({ editions: [] })
    renderScreen(<Reports />)
    expect((await screen.findByText('ปกติ')).closest('.pill')).toHaveClass('pill--done')
    expect(screen.getByText('ค้างชำระ').closest('.pill')).toHaveClass('pill--do')
    expect(screen.getByText('NPL', { selector: '.pill' })).toHaveClass('pill--problem')
    expect(screen.getByText('นับหัวลูกค้า ณ วันทำการ')).toHaveClass('card__note')
    expect(screen.getByText('58.7%')).toBeInTheDocument()
    expect(screen.getByText('17/10/2026 – 23/10/2026')).toBeInTheDocument()
  })

  it('audit: the result is a pill in words and a refusal keeps its error code beside it', async () => {
    api.audit.mockResolvedValue({
      entries: [
        { seq: 2, at: '2026-10-23T10:42:00', actor_claimed: 'officer-a', actor_source: 'SESSION', act: 'CONTACT_LOGGED', subject_uid: 'c-2', outcome: 'REFUSED', error_code: 'contact_locked' },
        { seq: 1, at: '2026-10-23T10:40:00', actor_claimed: 'officer-a', actor_source: 'SESSION', act: 'CASE_VIEWED', subject_uid: 'c-2', outcome: 'OK', error_code: null },
      ],
      meta: { actors: ['officer-a'], acts: [], signing_source: null },
    })
    renderScreen(<Audit />)
    expect((await screen.findByText('ถูกปฏิเสธ')).closest('.pill')).toHaveClass('pill--problem')
    expect(screen.getByText('contact_locked')).toBeInTheDocument()
    expect(screen.getByText('สำเร็จ').closest('.pill')).toHaveClass('pill--done')
  })

  it('settings: lock and band pills, the invite reason, and login-off as a quiet line', async () => {
    api.config.mockResolvedValue({
      role: 'OFFICER',
      config: {
        pipeline_lookahead_days: { value: '3', editable: false, editable_by: 'MANAGER', lock: 'manager', note_th: 'x', note_en: 'x' },
        invoice_owner_role: { value: 'COLLECTION', editable: false, editable_by: null, lock: 'locked', note_th: 'y', note_en: 'y' },
      },
    })
    api.bandSets.mockResolvedValue({ band_sets: [{ code: 'SOP_30_60_90', active: true }] })
    api.dictionaries.mockResolvedValue({ dictionaries: {} })
    api.authConfig.mockResolvedValue({ mode: 'off' })
    renderScreen(<Settings />)
    expect((await screen.findByText('ล็อก · รอตัดสิน')).closest('.pill').querySelector('svg.st--off')).not.toBeNull()
    expect(screen.getByText('ต้องเป็นผู้จัดการขึ้นไป', { selector: '.pill' }).querySelector('svg.st--off')).not.toBeNull()
    expect(screen.getByText('ใช้อยู่').closest('.pill')).toHaveClass('pill--done')
    const invite = screen.getByRole('button', { name: 'เพิ่มผู้ใช้' })
    expect(invite).toBeDisabled()
    expect(invite).toHaveAttribute('title', 'ต้องเป็นผู้จัดการขึ้นไป')
    expect(await screen.findByText(/การเข้าสู่ระบบปิดอยู่/)).toHaveClass('empty')
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('settings: roles read as words in the list and the invite choice; the in-row save is secondary', async () => {
    setRole('MANAGER')
    setRoster([{ uid: 'u-officer', display_name_th: 'เจ้าหน้าที่ทดสอบ', display_name_en: 'u-officer', role: 'OFFICER', roles: ['OFFICER'] }])
    api.config.mockResolvedValue({
      role: 'MANAGER',
      config: { pipeline_lookahead_days: { value: '3', editable: true, editable_by: 'MANAGER', lock: 'manager', note_th: 'x', note_en: 'x' } },
    })
    api.bandSets.mockResolvedValue({ band_sets: [] })
    api.dictionaries.mockResolvedValue({ dictionaries: {} })
    api.authConfig.mockResolvedValue({ mode: 'on' })
    api.authUsers.mockResolvedValue({ users: [{ uid: 'u-1', display_name: 'ผู้ใช้ทดสอบ', email: 'a@example.com', role: 'SUPERVISOR' }], grantable_roles: ['OFFICER', 'SUPERVISOR'] })
    const user = userEvent.setup()
    renderScreen(<Settings />)
    expect(await screen.findByText('หัวหน้างาน')).toHaveAttribute('title', 'SUPERVISOR')
    const field = screen.getByLabelText('มองล่วงหน้าก่อนติดตั้ง (วัน)')
    await user.clear(field)
    await user.type(field, '5')
    expect(screen.getByRole('button', { name: 'บันทึก' })).not.toHaveClass('btn--primary')
    await user.click(screen.getByRole('button', { name: 'เพิ่มผู้ใช้' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('option', { name: 'หัวหน้างาน' })).toHaveValue('SUPERVISOR')
    setRoster([])
  })

  it('dashboard: the NPL roll and the queue counts wear their status icons', async () => {
    api.reportsTeam.mockResolvedValue({
      period: { business_date: '2026-10-23', month: '2026-10', officers: 3, month_label_th: 'ตุลาคม 2026', month_label_en: 'October 2026' },
      team: { arrears_total: '100.00', debtors: 2 }, receipts_by_month: [], aging_bands: [], officers: [], officers_total: null,
      npl_roll: { rolled_in: { customers: 1, amount: '10.00' }, rolled_out: { customers: 0, amount: '0.00' }, still_npl: { customers: 2, amount: '20.00' } },
      queues: { reviews_open: 3, pipeline: 0, peak_not_approved: 0, npl_cases: 1 },
    })
    api.workbook.mockResolvedValue({ rows: [], meta: { total: 0 } })
    renderScreen(<Dashboard />)
    expect((await screen.findByText('ไหลเข้า NPL')).closest('.pill')).toHaveClass('pill--problem')
    expect(screen.getByText('ไหลออกจาก NPL').closest('.pill')).toHaveClass('pill--done')
    const queuePill = (name) => screen.getByRole('link', { name }).closest('li').querySelector('.pill')
    expect(queuePill('รอตรวจ')).toHaveClass('pill--do')
    expect(queuePill('รอตรวจ')).toHaveAttribute('title', 'มีงานรอ')
    expect(queuePill('ใบแจ้งหนี้ก่อนติดตั้ง')).toHaveClass('pill--done')
  })

  it('pipeline: one of three passed draws the quarter pie; the groups wear their icons', async () => {
    const cond = (key, passed) => ({ key, label_th: key, label_en: key, passed, evidence: [], evidence_count: 0 })
    api.pipeline.mockResolvedValue({
      items: [
        { uid: 'PL-1', display_name: 'ลูกค้าทดสอบ หนึ่ง', amount_due: '1000', conditions: [cond('a', true), cond('b', false), cond('c', false)] },
        { uid: 'PL-2', display_name: 'ลูกค้าทดสอบ สอง', amount_due: '2000', conditions: [cond('a', true), cond('b', true), cond('c', true)] },
      ],
      meta: { total: 2 },
    })
    renderScreen(<Pipeline />)
    const quarter = (await screen.findAllByText('ผ่าน 1 จาก 3'))[0].closest('.pill')
    expect(quarter.querySelector('svg.st--moving-1')).not.toBeNull()
    expect(screen.getAllByText('ผ่าน 3 จาก 3')[0].closest('.pill')).toHaveClass('pill--done')
    expect(document.querySelectorAll('.group__head svg.st--idle')).toHaveLength(1)
    expect(document.querySelectorAll('.group__head svg.st--done')).toHaveLength(1)
  })
})

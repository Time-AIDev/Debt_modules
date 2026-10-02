import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { setRole, setRoster } from '../lib/identity.jsx'
import { Dashboard } from './Dashboard.jsx'
import { Calendar } from './Calendar.jsx'
import { Reports } from './Reports.jsx'
import { Settings } from './Settings.jsx'
import { DataSources } from './DataSources.jsx'
import { Audit } from './Audit.jsx'
import { Reviews } from './Reviews.jsx'
import { Pipeline } from './Pipeline.jsx'
import { Payments } from './Payments.jsx'
import { Recovery } from './Recovery.jsx'

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
  setRole('OFFICER')
  setRoster([])
  vi.clearAllMocks()
  api.reportsTeam.mockResolvedValue({
    period: { business_date: '2026-10-23', month: '2026-10', officers: 3, month_label_th: 'ตุลาคม 2026', month_label_en: 'October 2026' },
    team: { arrears_total: '9081825.88', debtors: 94, cases_total: 212, queue_today: 151, queue_done: 0, ptp_kept_rate: '0.0%', npl_count: 5, attainment: '0.0%', receipts_month: '0', target_month: null, contact_success_rate: '56.4%', dso_days: 47 },
    receipts_by_month: [], npl_roll: { rolled_in: { customers: 1, amount: '16320.00' }, rolled_out: { customers: 0, amount: '0.00' }, still_npl: { customers: 5, amount: '154444.00' } },
    aging_bands: [{ code: 'CURRENT', label_th: 'ปกติ', label_en: 'Current', customers: 118, arrears: '0.00' }],
    band_set_code: 'SOP_30_60_90', officers: [], officers_total: null,
    queues: { reviews_open: 3, pipeline: 108, peak_not_approved: 0, npl_cases: 6 },
  })
  api.weeklyReport.mockResolvedValue({ period: {}, management_summary: { cash_in: { total: '0' } }, portfolio: {}, promises: {}, npl_movement: {} })
  api.workbook.mockResolvedValue({ rows: [], meta: { total: 0 } })
  api.calendar.mockResolvedValue({ items: [], days: [], meta: { business_date: '2026-10-23', total: 0, by_kind: {} } })
  api.weeklyEditions.mockResolvedValue({ editions: [] })
  api.config.mockResolvedValue({ config: {}, role: 'MANAGER', power_states: [], pending: [] })
  api.bandSets.mockResolvedValue({ band_sets: [] })
  api.dictionaries.mockResolvedValue({ dictionaries: {} })
  api.authConfig.mockResolvedValue({ mode: 'off' })
  api.migrationReport.mockResolvedValue({ source_chain: { rungs: [] }, counts: {}, reconciliation: [] })
  api.integrationsStatus.mockResolvedValue({ odoo: {}, peak: {} })
  // The screen reads one overview; the individual endpoints stay for other callers.
  api.dataSourcesOverview.mockResolvedValue({
    migration: { source_chain: { rungs: [] }, counts: {}, reconciliation: [] },
    integrations: { odoo: {}, peak: {} },
    crm: { last: null, schedule: { enabled: true, interval_minutes: 120, next_run_at: 1764000000, odoo_configured: true } },
    peak: { last: null, doors: [] },
  })
  // The screen also polls the schedule directly; the overview copy can be older.
  api.crmLeadSchedule.mockResolvedValue({ enabled: true, interval_minutes: 120, next_run_at: 1764000000, odoo_configured: true })
  api.audit.mockResolvedValue({ entries: [], meta: { actors: [], acts: [], signing_source: null } })
  api.reviews.mockResolvedValue({ reviews: [], meta: { open: 0, decisions: [], npl_types: [] } })
  api.pipeline.mockResolvedValue({ items: [], meta: { total: 0 } })
  api.peakDocuments.mockResolvedValue({ documents: [], meta: { counts: {}, allocation: { lines: [] } } })
  api.nplCases.mockResolvedValue({ npl_cases: [], meta: {} })
  api.recoveryCases.mockResolvedValue({ recovery_cases: [] })
  api.lots.mockResolvedValue({ lots: [] })
  api.recoveryBoard.mockResolvedValue({ columns: [] })
  api.serviceBilling.mockResolvedValue({ accounts: [], meta: {} })
})

describe('system lenses render served shapes without crashing', () => {
  it('dashboard shows the served team figures', async () => {
    renderScreen(<Dashboard />)
    expect(await screen.findByText('ภาพรวมทีมติดตามหนี้')).toBeInTheDocument()
    expect(screen.getByText('9,081,825.88')).toBeInTheDocument()
    expect(screen.queryByText('ลูกค้า / สมุดงาน')).toBeNull()
  })

  it('dashboard keeps every next-action link inside its own lens', async () => {
    renderScreen(<Dashboard />)
    const link = await screen.findByRole('link', { name: 'รอตรวจ' })
    expect(link).toHaveAttribute('href', '/reviews')
  })

  it('a manager sets the month’s cash-in target from the overview', async () => {
    setRole('MANAGER')
    api.putCollectionTargets.mockResolvedValue({ month: '2026-10', targets: {} })
    const user = userEvent.setup()
    renderScreen(<Dashboard />)

    await user.click(await screen.findByRole('button', { name: 'ตั้งเป้าเดือนนี้' }))
    const input = await screen.findByLabelText('เป้า (บาท)')
    await user.clear(input)
    await user.type(input, '2000000')
    await user.click(screen.getByRole('button', { name: 'บันทึก' }))

    await waitFor(() => expect(api.putCollectionTargets).toHaveBeenCalledWith('2026-10', { 'cash_received:portfolio': '2000000' }))
  })

  it('an officer sees the target control disabled with its reason (GUD-002)', async () => {
    renderScreen(<Dashboard />)
    const control = await screen.findByRole('button', { name: 'ตั้งเป้าเดือนนี้' })
    expect(control).toBeDisabled()
    expect(control).toHaveAttribute('title', 'ตั้งเป้าได้เฉพาะผู้จัดการขึ้นไป')
    expect(screen.getByText('ตั้งเป้าได้เฉพาะผู้จัดการขึ้นไป')).toBeInTheDocument()
  })

  it('calendar renders the served month grid', async () => {
    renderScreen(<Calendar />)
    expect((await screen.findAllByText('จ')).length).toBeGreaterThan(0)
    expect(screen.getByText('รายการในช่วง')).toBeInTheDocument()
  })

  it('reports renders the management summary and editions table', async () => {
    renderScreen(<Reports />)
    expect(await screen.findByText('สรุปผู้บริหาร')).toBeInTheDocument()
    expect(screen.getByText('ยังไม่มีฉบับที่เผยแพร่')).toBeInTheDocument()
  })

  it('settings explains that sign-in is off instead of leaking a refusal', async () => {
    renderScreen(<Settings />)
    expect(await screen.findByText(/การเข้าสู่ระบบปิดอยู่/)).toBeInTheDocument()
  })

  it('settings register shows the plain label with the served key on the label', async () => {
    api.config.mockResolvedValue({
      role: 'MANAGER',
      config: {
        pipeline_lookahead_days: {
          value: '3', state: 'SET', owner: null, editable: true, editable_by: 'MANAGER', lock: 'manager',
          note_th: 'ผู้จัดการหรือเจ้าของระบบแก้ไขได้', note_en: 'A Manager or the Owner may change it',
        },
        invoice_owner_role: {
          value: 'COLLECTION', state: 'OPEN', owner: 'Owner', editable: false, editable_by: null, lock: 'locked',
          note_th: 'ค่าล็อก', note_en: 'Locked',
        },
      },
    })
    setRole('MANAGER')
    renderScreen(<Settings />)

    const editable = await screen.findByText('มองล่วงหน้าก่อนติดตั้ง (วัน)')
    expect(editable).toHaveAttribute('data-key', 'pipeline_lookahead_days')
    const locked = screen.getByText('เจ้าของงานออกใบแจ้งหนี้')
    expect(locked).toHaveAttribute('data-key', 'invoice_owner_role')
    expect(screen.getByText('ล็อก · รอตัดสิน')).toBeInTheDocument()
    expect(screen.getByLabelText('เจ้าของงานออกใบแจ้งหนี้')).toBeDisabled()
    expect(screen.getByLabelText('มองล่วงหน้าก่อนติดตั้ง (วัน)')).not.toBeDisabled()
  })

  it('settings saves a dirty value under the original key', async () => {
    api.config.mockResolvedValue({
      role: 'MANAGER',
      config: {
        pipeline_lookahead_days: {
          value: '3', state: 'SET', owner: null, editable: true, editable_by: 'MANAGER', lock: 'manager',
          note_th: 'ผู้จัดการหรือเจ้าของระบบแก้ไขได้', note_en: 'A Manager or the Owner may change it',
        },
      },
    })
    api.putConfig.mockResolvedValue({})
    setRole('MANAGER')
    const user = userEvent.setup()
    renderScreen(<Settings />)

    const input = await screen.findByLabelText('มองล่วงหน้าก่อนติดตั้ง (วัน)')
    await user.clear(input)
    await user.type(input, '5')
    await user.click(await screen.findByRole('button', { name: 'บันทึก' }))
    await waitFor(() => expect(api.putConfig).toHaveBeenCalledWith({ pipeline_lookahead_days: '5' }))
  })

  it('data sources opens on the PEAK tile, the Odoo tile says the sync is automatic, and the sheet door is one click away', async () => {
    const user = userEvent.setup()
    renderScreen(<DataSources />)
    expect(await screen.findByText('ลำดับแหล่งข้อมูลขาเข้า')).toBeInTheDocument()
    // design D: four source tiles select the panel, PEAK first; the Odoo tile still
    // says the refetch is automatic (2026-09-21).
    expect(screen.getByRole('button', { name: /^PEAK/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getAllByText('ซิงก์อัตโนมัติเปิดอยู่').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/ทุก 2 ชั่วโมง/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/รอบถัดไป/).length).toBeGreaterThan(0)
    expect(screen.queryByText('ลากไฟล์มาวาง หรือเลือกไฟล์')).toBeNull()
    await user.click(screen.getByRole('button', { name: /^ไฟล์ชีต/ }))
    expect(screen.getByText('ลากไฟล์มาวาง หรือเลือกไฟล์')).toBeInTheDocument()
  })

  it('audit renders the signed log table', async () => {
    renderScreen(<Audit />)
    expect(await screen.findByText('ไม่มีรายการในช่วงนี้')).toBeInTheDocument()
  })

  it('reviews, pipeline, payments and recovery render their empty states', async () => {
    renderScreen(<Reviews />)
    expect(await screen.findByText('ไม่มีคำขอที่เปิดอยู่')).toBeInTheDocument()
    renderScreen(<Pipeline />)
    expect(await screen.findByText('ไม่มีรายการในช่วงนี้')).toBeInTheDocument()
    renderScreen(<Payments />)
    expect(await screen.findByText('ไม่มีเอกสาร PEAK ในรอบนี้')).toBeInTheDocument()
    renderScreen(<Recovery />)
    expect(await screen.findByText('ไม่มีเคส NPL')).toBeInTheDocument()
  })

  it('the NPL-type answer cannot be confirmed without a served NPL type', async () => {
    api.reviews.mockResolvedValue({
      reviews: [{
        uid: 'rv-1', display_name: 'สมศรี พงษ์ไพบูลย์', customer_uid: 'c-2', status: 'OPEN',
        sla_breached: false, reason_label: 'เกณฑ์ NPL', reason_label_en: 'NPL rule',
        question_th: 'ขอตั้งประเภท NPL', question_en: 'Set the NPL type', raised_at: '2026-09-14',
        aggregate_overdue: '1000.00', oldest_dpd: 95, risk_score: 60,
        decisions: [{ code: 'NPL_TYPE_SET', label_th: 'ตั้งประเภท NPL', label_en: 'Set the NPL type' }],
        evidence: { kept_ptp_count: 0, broken_ptp_count: 2, last_contacts: [] },
      }],
      meta: { open: 1, decisions: [], npl_types: [] },
    })
    setRole('MANAGER')
    const user = userEvent.setup()
    renderScreen(<Reviews />)

    await user.click(await screen.findByRole('button', { name: 'ตอบคำขอ' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByLabelText(/คำตัดสิน/)).toHaveAttribute('aria-required', 'true')
    expect(within(dialog).getByLabelText(/ประเภท NPL/)).toHaveAttribute('aria-required', 'true')
    // the red * marks a required field; the "* ช่องที่ต้องกรอก" notice is dropped (brief §3.4)
    expect(within(dialog).getByText('คำตัดสิน').querySelector('.req')).toHaveTextContent('*')
    expect(within(dialog).queryByText('* ช่องที่ต้องกรอก')).toBeNull()
    expect(within(dialog).getByRole('button', { name: 'ยืนยันคำตอบ' })).toBeDisabled()
    expect(api.answerReview).not.toHaveBeenCalled()
  })

  it('invite carries the registry officer and never offers one above the actor', async () => {
    api.authConfig.mockResolvedValue({ mode: 'on' })
    api.authUsers.mockResolvedValue({
      users: [], grantable_roles: ['OFFICER', 'SUPERVISOR', 'MANAGER'],
      durable: true, note_th: null, note_en: null,
    })
    api.authInviteUser.mockResolvedValue({ user: { uid: 'u-1' } })
    setRole('MANAGER')
    setRoster([
      { uid: 'u-officer', display_name_th: 'ชไมพร', display_name_en: 'u-officer', role: 'OFFICER', roles: ['OFFICER'] },
      { uid: 'owner', display_name_th: 'เจ้าของระบบ', display_name_en: 'owner', role: 'OWNER', roles: ['OWNER'] },
    ])
    const user = userEvent.setup()
    renderScreen(<Settings />)

    await user.click(await screen.findByRole('button', { name: 'เพิ่มผู้ใช้' }))
    const dialog = await screen.findByRole('dialog')
    const officer = within(dialog).getByLabelText(/เจ้าหน้าที่ในระบบ/)
    expect(officer).toHaveAttribute('aria-required', 'true')
    expect(within(dialog).getByText('อีเมล').querySelector('.req')).toHaveTextContent('*')
    expect(within(dialog).queryByText('เจ้าของระบบ')).not.toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'ส่งคำเชิญ' })).toBeDisabled()

    await user.type(within(dialog).getByLabelText(/อีเมล/), 'new.manager@example.com')
    await user.selectOptions(officer, 'u-officer')
    await user.click(within(dialog).getByRole('button', { name: 'ส่งคำเชิญ' }))

    await waitFor(() => expect(api.authInviteUser).toHaveBeenCalledWith({
      email: 'new.manager@example.com', role: 'OFFICER', officer: 'u-officer',
    }))
  })
})

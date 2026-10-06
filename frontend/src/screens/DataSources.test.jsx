import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { setRole } from '../lib/identity.jsx'
import { DataSources } from './DataSources.jsx'

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

const SCHEDULE = { enabled: true, interval_minutes: 15, next_run_at: 1764000000, odoo_configured: true }
const overview = (patch = {}) => ({
  migration: {
    counts: { served: 2648, landed: 35752, registry: 2648, skipped: 2648, engine_book: 0 },
    reconciliation: [{ payment_status: 'CURRENT', sheet: null, imported: 0, matches: null, note: 'odoo_no_money_pivots' }],
    source_chain: {
      serving_code: 'ODOO', serving_name: 'Odoo crm.lead',
      rungs: [
        { rank: 1, code: 'ODOO_CRM_LEAD', name: 'Odoo crm.lead', serving: true, state_en: 'Serving', note_th: 'x' },
        { rank: 2, code: 'SHEET', name: 'New Order Master (SHEET)', serving: false, state_en: 'Reserve', note_th: 'ชีตหลักที่ทีมกรอกเอง' },
        { rank: 3, code: 'MANUAL_FILE', name: 'ไฟล์ที่นำเข้าด้วยมือ', serving: false, state_en: 'Fallback',
          note_th: 'ใช้เมื่อชีตหลักอ่านไม่ได้ · ครั้งล่าสุด 2026-09-24T06:41:07.123+00:00' },
      ],
    },
  },
  integrations: {
    odoo: { integration: 'Odoo UAT', configured: true, snapshot: { synced_at: '2026-09-24T13:41:00', door: 'odoo' } },
    peak: { integration: 'PEAK UAT', configured: true, mode: 'DRAFT_ONLY — create-draft + read-state',
            probe: { reachable: false, reason: 'PEAK UAT is not reachable: ConnectError' } },
  },
  crm: { last: { run: null, watch: null, receipt: null }, schedule: SCHEDULE },
  peak: { doors: { doors: [{ door: 'api', state: 'not_configured' }] } },
  ...patch,
})

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
  setRole('OFFICER')
  api.dataSourcesOverview.mockResolvedValue(overview())
  api.crmLeadSchedule.mockResolvedValue(SCHEDULE)
  api.crmLeadLastRun.mockResolvedValue({ run: null, watch: null, receipt: null })
  api.peakReportLastRun.mockResolvedValue({ staged: null, applied: null })
  api.peakReportDoors.mockResolvedValue({ doors: [] })
  api.peakLinks.mockResolvedValue({ links: [] })
  api.dataState.mockResolvedValue({ stale: false, serving: { serving_name: 'Odoo crm.lead', imported_at: '2026-09-24T13:41:00' } })
})

describe('แหล่งข้อมูล (design D)', () => {
  it('disables Odoo pulls with a visible reason when the connector is not configured', async () => {
    const data = overview()
    data.integrations.odoo.configured = false
    api.dataSourcesOverview.mockResolvedValue(data)
    api.crmLeadSchedule.mockResolvedValue({ ...SCHEDULE, odoo_configured: false })
    setRole('MANAGER')
    const user = userEvent.setup()
    renderScreen(<DataSources />)
    await user.click(await screen.findByRole('button', { name: /^Odoo crm\.lead/ }))
    expect(screen.getByRole('button', { name: 'ดึงจาก Odoo crm.lead' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'ซิงก์ Odoo' })).toBeDisabled()
    expect(screen.getAllByText('Odoo ยังไม่ได้ตั้งค่า').length).toBeGreaterThan(0)
    expect(api.startCrmLeadPipeline).not.toHaveBeenCalled()
  })

  it('shows the Thai job failure reason instead of the generic English review text', async () => {
    const watch = { uid: 'review-job', kind: 'odoo', state: 'failed', problem: {
      code: 'job_dead_letter', detail: 'Task requires operator review before a new submission.',
      message_th: 'งานหยุดแล้ว กรุณาให้ผู้ดูแลตรวจสอบก่อนส่งงานใหม่',
    } }
    api.crmLeadLastRun.mockResolvedValue({ run: null, receipt: null, watch })
    const user = userEvent.setup()
    renderScreen(<DataSources />)
    await user.click(await screen.findByRole('button', { name: /^Odoo crm\.lead/ }))
    expect(await screen.findByText(watch.problem.message_th)).toBeInTheDocument()
    expect(screen.queryByText(watch.problem.detail)).toBeNull()
  })
  it('shows every served count with separators, and the Odoo rung its served slice', async () => {
    const user = userEvent.setup()
    renderScreen(<DataSources />)
    expect(await screen.findByText('แสดง 2,648 จาก 35,752 ราย (ที่เหลือยังไม่มี VOLT ID) · Odoo ไม่มียอดเงิน')).toBeInTheDocument()
    expect(screen.getByText('New Order Master (ชีต)')).toBeInTheDocument()
    // served ISO stamps in a rung note read dd/mm/yyyy hh:mm
    expect(screen.getByText('ใช้เมื่อชีตหลักอ่านไม่ได้ · ครั้งล่าสุด 24/09/2026 06:41')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^สมุดงาน/ }))
    // all five counts — the old card cut the fifth
    for (const label of ['ลูกค้าในสมุดงาน', 'แถวที่นำเข้าทั้งหมด', 'ยังไม่มีสัญญา', 'ข้ามสัญญา', 'สัญญาในระบบ']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    expect(screen.getByText('35,752')).toBeInTheDocument()
    // the reconciliation is on the page now, in plain words
    expect(screen.getByText('เทียบไม่ได้ — Odoo ไม่มียอดเงินหรือสถานะการชำระ')).toBeInTheDocument()
    expect(screen.getByText('ไม่มีข้อมูลเทียบ')).toBeInTheDocument()
  })

  it('names the Odoo sync, gates it with a reason, and runs the crm.lead pull (no source switches)', async () => {
    const user = userEvent.setup()
    renderScreen(<DataSources />)
    const sync = await screen.findByRole('button', { name: 'ซิงก์ Odoo' })
    expect(sync).toBeDisabled()
    expect(screen.getAllByText('เฉพาะผู้จัดการขึ้นไป').length).toBe(1)
    // 2026-09-25: the sale.order sync and the snapshot/sheet switches are gone
    expect(screen.queryByRole('button', { name: 'ใช้ชีต' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'ใช้ข้อมูลค้าง' })).toBeNull()

    act(() => setRole('MANAGER'))
    expect(sync).toBeEnabled()
    api.startCrmLeadPipeline.mockRejectedValueOnce({ problem: { code: 'integration_not_configured', message_th: 'ยังไม่ได้ตั้งค่าการเชื่อมต่อระบบภายนอก' } })
    await user.click(sync)
    // no dialog: it starts the crm.lead pull and opens the Odoo panel, where a refusal stays visible
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(api.startCrmLeadPipeline).toHaveBeenCalledWith('NEW_ONLY')
    expect(await screen.findByText('ยังไม่ได้ตั้งค่าการเชื่อมต่อระบบภายนอก')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Odoo crm.lead', level: 2 })).toBeInTheDocument()
  })

  it('says why PEAK UAT is unreachable in Thai and tests it again on demand', async () => {
    const user = userEvent.setup()
    renderScreen(<DataSources />)
    expect(await screen.findByText('ตั้งค่าแล้ว · ติดต่อ PEAK UAT ไม่ได้ (ConnectError) · โหมดสร้างร่างเท่านั้น')).toBeInTheDocument()
    expect(screen.getByText('ครั้งล่าสุด 24/09/2026 13:41')).toBeInTheDocument()
    api.integrationsStatus.mockResolvedValue(overview().integrations)
    await user.click(screen.getByRole('button', { name: 'ทดสอบอีกครั้ง' }))
    await waitFor(() => expect(api.integrationsStatus).toHaveBeenCalledTimes(1))
    expect(await screen.findByText('ยังติดต่อไม่ได้ — ConnectError')).toBeInTheDocument()
  })

  it('shows a failed crm.lead run and a refused pull instead of saying nothing', async () => {
    api.dataSourcesOverview.mockResolvedValue(overview({
      crm: { last: { run: null, receipt: null, watch: { uid: 'run-1', kind: 'odoo', state: 'failed', problem: { code: 'integration_not_configured', detail: 'missing ODOO_URL' } } }, schedule: SCHEDULE },
    }))
    api.crmLeadLastRun.mockResolvedValue({ run: null, receipt: null, watch: { uid: 'run-1', kind: 'odoo', state: 'failed', problem: { code: 'integration_not_configured', detail: 'missing ODOO_URL' } } })
    setRole('MANAGER')
    api.startCrmLeadPipeline.mockRejectedValue({ problem: { code: 'forbidden', message_th: 'เฉพาะผู้จัดการนำเข้าข้อมูลได้' } })
    const user = userEvent.setup()
    renderScreen(<DataSources />)
    await user.click(await screen.findByRole('button', { name: /^Odoo crm\.lead/ }))
    expect(screen.getAllByText('รอบล่าสุดล้มเหลว').length).toBeGreaterThan(0)
    expect(screen.getByText('ยังไม่ได้ตั้งค่าการเชื่อมต่อระบบภายนอก')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'ดึงจาก Odoo crm.lead' }))
    expect(await screen.findByText('เฉพาะผู้จัดการนำเข้าข้อมูลได้')).toBeInTheDocument()
  })

  it('never lets a PEAK run in the served watch drive the Odoo tile', async () => {
    // /crm-lead/last-run serves the latest run of ANY pipeline as `watch`
    const peakRun = { uid: 'run-9', kind: 'peak-report', state: 'running', read: 10, total: 100 }
    api.dataSourcesOverview.mockResolvedValue(overview({ crm: { last: { run: null, receipt: null, watch: peakRun }, schedule: SCHEDULE } }))
    api.crmLeadLastRun.mockResolvedValue({ run: null, receipt: null, watch: { ...peakRun, state: 'failed', problem: { code: 'header_not_found' } } })
    setRole('MANAGER')
    const user = userEvent.setup()
    renderScreen(<DataSources />)
    await user.click(await screen.findByRole('button', { name: /^Odoo crm\.lead/ }))
    expect(screen.getAllByText('ซิงก์อัตโนมัติเปิดอยู่').length).toBeGreaterThan(0)
    expect(screen.queryByText('รอบล่าสุดล้มเหลว')).toBeNull()
    expect(screen.queryByText(/กำลังอ่าน/)).toBeNull()
    expect(screen.getByRole('button', { name: 'ดึงจาก Odoo crm.lead' })).toBeEnabled()
    expect(api.crmLeadRun).not.toHaveBeenCalled()
  })

  it('shows the last crm.lead run with its duplicates and the refusals by rule, in words', async () => {
    const last = {
      run: { finished_at: '2026-09-24T13:41:00', row_counts: { read: 34658, landed: 34287, rejected: 144, duplicates: 227 } },
      receipt: { rejected_by_rule: { no_identity: 96, unshaped_volt_id: 21, duplicate_volt_id: 27 } },
      watch: null,
    }
    api.dataSourcesOverview.mockResolvedValue(overview({ crm: { last, schedule: SCHEDULE } }))
    api.crmLeadLastRun.mockResolvedValue(last)
    const user = userEvent.setup()
    renderScreen(<DataSources />)
    const tile = await screen.findByRole('button', { name: /^Odoo crm\.lead/ })
    expect(within(tile).getByText('13:41')).toBeInTheDocument()
    expect(within(tile).getByText('ครั้งล่าสุด 24/09')).toBeInTheDocument()
    await user.click(tile)
    for (const [word, n] of [['ซ้ำ', '227'], ['ไม่มีข้อมูลระบุตัวลูกค้า', '96'], ['Volt ID รูปแบบไม่ถูกต้อง', '21'], ['Volt ID ซ้ำ', '27']]) {
      expect(screen.getByText(word).nextElementSibling).toHaveTextContent(n)
    }
    expect(screen.getByText('34,287')).toBeInTheDocument()
  })

  it('lists the past crm.lead runs with their counts, the unchanged count, and a durable failure in words', async () => {
    const ok = (id, hh) => ({ id, status: 'OK', started_at: `2026-09-24T${hh}:40:00`, finished_at: `2026-09-24T${hh}:41:00`,
      row_counts: { read: 34120, landed: 5, rejected: 14 }, meta: { door: 'odoo', mode: 'NEW_ONLY', new: 3, changed: 2, unchanged: 34100, retired: 1 } })
    const failed = { id: 9, status: 'FAILED', started_at: '2026-09-24T14:00:00', finished_at: '2026-09-24T14:01:00',
      note: 'odoo_unreachable: ConnectError', meta: { door: 'odoo', mode: 'NEW_ONLY' } }
    const runs = [failed, ok(8, '13'), ok(7, '12'), ok(6, '11'), ok(5, '10'), ok(4, '09'), ok(3, '08')]
    const last = { run: ok(8, '13'), receipt: { rejected_by_rule: {}, unchanged: 34100 }, watch: null, failed }
    api.dataSourcesOverview.mockResolvedValue(overview({ crm: { last, schedule: SCHEDULE, runs } }))
    api.crmLeadLastRun.mockResolvedValue(last)
    const user = userEvent.setup()
    renderScreen(<DataSources />)
    await user.click(await screen.findByRole('button', { name: /^Odoo crm\.lead/ }))
    // the newest run failed durably: the tile says so, and the panel names the reason
    expect(screen.getAllByText('รอบล่าสุดล้มเหลว').length).toBeGreaterThan(0)
    expect(screen.getByText(/^รอบนำเข้าล่าสุดล้มเหลว · .+ · ติดต่อ Odoo ไม่ได้$/)).toBeInTheDocument()
    // the unchanged count sits beside "imported"
    expect(screen.getByText('เหมือนเดิม').nextElementSibling).toHaveTextContent('34,100')
    const list = screen.getByRole('list', { name: 'รอบที่ผ่านมา' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(5)
    expect(within(list).getByText('ติดต่อ Odoo ไม่ได้')).toBeInTheDocument()
    expect(within(list).getAllByText('ใหม่ 3 · เปลี่ยน 2 · เหมือนเดิม 34,100 · เลิกใช้ 1')).toHaveLength(4)
    expect(within(list).getAllByText('ดึงจาก Odoo')).toHaveLength(5)
    await user.click(screen.getByRole('button', { name: 'ดูทั้งหมด 7' }))
    expect(within(list).getAllByRole('listitem')).toHaveLength(7)
  })

  it('shows the PEAK report PeakIntake hands up on its tile', async () => {
    api.peakReportLastRun.mockResolvedValue({
      staged: null,
      applied: { id: 56, row_counts: { read: 7998, landed: 7638, rejected: 0 },
                 meta: { report_as_of: '2026-09-14', matched: 6985, candidates: 429, unmatched: 224 } },
    })
    api.peakReportRows.mockResolvedValue({ rows: [], total: 0 })
    renderScreen(<DataSources />)
    const tile = await screen.findByRole('button', { name: /^PEAK.*653/ })
    expect(within(tile).getByText('รอตรวจ')).toBeInTheDocument()
    expect(within(tile).getByText('ณ 14/09/2026')).toBeInTheDocument()
    expect(within(tile).getByText('รอยืนยัน 429 · ไม่พบลูกค้า 224')).toBeInTheDocument()
  })

  it('updates a stale session on request, says so, and shows a refusal in the stale box', async () => {
    api.dataState.mockResolvedValue({ stale: true, serving: { serving_name: 'Odoo crm.lead' } })
    api.refreshImports.mockRejectedValueOnce({ problem: { code: 'forbidden', message_th: 'ระบบปฏิเสธการอัปเดต' } })
    const user = userEvent.setup()
    renderScreen(<DataSources />)
    const update = await screen.findByRole('button', { name: 'อัปเดตทันที' })
    await user.click(update)
    expect(await screen.findByText('ระบบปฏิเสธการอัปเดต')).toBeInTheDocument()
    api.refreshImports.mockResolvedValueOnce({ refreshed: true, stale: false })
    await user.click(update)
    await waitFor(() => expect(api.refreshImports).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('อัปเดตแล้ว')).toBeInTheDocument()
    expect(screen.queryByText('ระบบปฏิเสธการอัปเดต')).toBeNull()
  })

  it('labels each refused sheet row with its sheet row number and shows them all on request', async () => {
    const refusals = [118, 240, 311, 402, 517, 600].map((row) => ({
      source_ref: { sheet: 'Order', row }, reason: 'no_volt_id', reason_th: 'ไม่มีค่า VOLT ID ที่ถูกต้องในแถวนี้',
    }))
    api.createImport.mockResolvedValue({ counts: { rows_read: 632, rows_imported: 618, rows_refused: 6, customers: 421 }, refusals })
    const user = userEvent.setup()
    renderScreen(<DataSources />)
    await user.click(await screen.findByRole('button', { name: /^ไฟล์ชีต/ }))
    await user.upload(screen.getByLabelText('เลือกไฟล์'), new File(['x'], 'new-order-master.xlsx'))
    expect(await screen.findByText('ใบรับรอง · new-order-master.xlsx')).toBeInTheDocument()
    expect(screen.getByText('แถว 118')).toBeInTheDocument()
    expect(screen.queryByText('แถว 600')).toBeNull()
    await user.click(screen.getByRole('button', { name: 'ดูทั้งหมด 6' }))
    expect(screen.getByText('แถว 600')).toBeInTheDocument()
    // the one-way reveal hands focus to the list instead of dropping it
    expect(screen.getByRole('list', { name: 'แถวที่ปฏิเสธ' })).toHaveFocus()
    // the tile says what the file did
    expect(screen.getByRole('button', { name: /^ไฟล์ชีต จัดเก็บชั่วคราว 632/ })).toBeInTheDocument()
  })

  it('lets only a manager install the checked sheet as the book, then shows what it serves and where PEAK disagrees', async () => {
    const counts = { rows_read: 3, rows_imported: 3, rows_refused: 0, customers: 3 }
    const retire = { customers: 1, live: 3, dropped_tabs: ['tracking'], needs_confirm: true }
    api.createImport.mockResolvedValue({ counts, refusals: [], installed: false, retire })
    api.installSheet.mockResolvedValue({ counts, refusals: [], installed: true,
      install: { customers: 3, contracts: 3, tracked: 2, retired: 1 } })
    const who = { customer_uid: 'sheet-91000000001', name: 'กานดา ทดสอบ', customer_no: '91000000001' }
    api.sheetDisagreements.mockResolvedValue({ rows: [
      { ...who, month: null, peak: 'CURRENT', sheet: 'LATE' },
      { ...who, month: 'Jul 2025', peak: 'PAID', sheet: 'LATE' }], meta: { total: 2, customers: 1 } })
    const user = userEvent.setup()
    renderScreen(<DataSources />)
    await user.click(await screen.findByRole('button', { name: /^ไฟล์ชีต/ }))
    await user.selectOptions(screen.getByRole('combobox', { name: 'รูปแบบข้อมูลที่ต้องการนำเข้า' }), 'fullbook')
    const install = screen.getByRole('button', { name: 'นำเข้าเป็นสมุดงาน' })
    expect(install).toBeDisabled()                                    // an officer checks, never installs
    expect(within(screen.getByRole('region', { name: 'ไฟล์ชีต' })).getByText('เฉพาะผู้จัดการขึ้นไป')).toBeInTheDocument()

    // the review list: every row names the month (or the current status) and opens the customer
    const review = await screen.findByRole('region', { name: 'ไม่ตรงกับ PEAK' })
    const links = await within(review).findAllByRole('link', { name: 'กานดา ทดสอบ' })
    expect(links.map((a) => a.getAttribute('href'))).toEqual(['/customers/sheet-91000000001', '/customers/sheet-91000000001'])
    const [now, july] = within(review).getAllByRole('row').slice(1)
    expect(within(now).getByText('สถานะปัจจุบัน')).toBeInTheDocument()
    expect([within(now).getByText('ปกติ'), within(now).getByText('ค้างชำระ')]).toHaveLength(2)
    expect(within(july).getByText('Jul 2025')).toBeInTheDocument()
    expect(within(july).getByText('ชำระแล้ว')).toBeInTheDocument()

    act(() => setRole('MANAGER'))
    expect(install).toBeDisabled()                                    // nothing checked yet
    await user.upload(screen.getByLabelText('เลือกไฟล์'), new File(['x'], 'nom.xlsx'))
    expect(await screen.findByText('ตรวจไฟล์แล้ว — ยังไม่ได้นำเข้าสมุดงาน')).toBeInTheDocument()
    // the check already says what an install would take out of the book
    expect(screen.getByText('ลูกค้า 1 จาก 3 รายในสมุดงานจะออกจากสมุดงาน · ไฟล์นี้ไม่มีแท็บ done collection ที่สมุดงานมีอยู่ตอนนี้'))
      .toBeInTheDocument()
    expect(install).toBeEnabled()
    await user.click(install)
    const dialog = screen.getByRole('dialog', { name: 'นำเข้าเป็นสมุดงาน' })
    expect(within(dialog).getByText('ลูกค้า 1 จาก 3 รายในสมุดงานจะออกจากสมุดงาน')).toBeInTheDocument()
    expect(within(dialog).getByText('ไฟล์นี้ไม่มีแท็บ done collection ที่สมุดงานมีอยู่ตอนนี้')).toBeInTheDocument()
    expect(api.installSheet).not.toHaveBeenCalled()                   // asked first
    await user.click(within(dialog).getByRole('button', { name: 'นำเข้าเป็นสมุดงาน' }))
    await waitFor(() => expect(api.installSheet).toHaveBeenCalledTimes(1))
    const [sent, confirmed] = api.installSheet.mock.calls[0]
    expect(sent.name).toBe('nom.xlsx')                                // the checked file, sent again
    expect(confirmed).toBe(1)                                         // with the count it confirmed
    expect(screen.queryByRole('dialog')).toBeNull()
    expect((await screen.findAllByText('นำเข้าเป็นสมุดงานแล้ว · 3 ราย')).length).toBeGreaterThan(0)
    for (const [label, n] of [['สัญญา', '3'], ['แถว done collection', '2'], ['ออกจากสมุดงาน', '1']]) {
      expect(screen.getByText(label).nextElementSibling).toHaveTextContent(n)
    }
    expect(api.sheetDisagreements).toHaveBeenCalledTimes(2)           // re-read after the install
  })

  it('says the review list could not be read instead of "nothing differs", and when PEAK is off', async () => {
    api.sheetDisagreements.mockRejectedValueOnce({ problem: { code: 'request_failed', message_th: 'อ่านรายการไม่สำเร็จ' } })
    const user = userEvent.setup()
    renderScreen(<DataSources />)
    await user.click(await screen.findByRole('button', { name: /^ไฟล์ชีต/ }))
    const review = await screen.findByRole('region', { name: 'ไม่ตรงกับ PEAK' })
    expect(await within(review).findByText('อ่านรายการไม่สำเร็จ')).toBeInTheDocument()
    expect(within(review).queryByText('ไม่มีรายการที่ไม่ตรงกับ PEAK')).toBeNull()

    api.sheetDisagreements.mockResolvedValue({ rows: [{ customer_uid: 'u-1', name: 'สมมติ ทดสอบ', month: null,
      peak: 'CURRENT', sheet: 'LATE', peak_off: true }], meta: { total: 1, customers: 1 } })
    await user.click(screen.getByRole('button', { name: /^PEAK/ }))
    await user.click(screen.getByRole('button', { name: /^ไฟล์ชีต/ }))
    expect(await within(screen.getByRole('region', { name: 'ไม่ตรงกับ PEAK' })).findByText('PEAK ปิดอยู่ — สถานะตามชีต'))
      .toBeInTheDocument()
  })
})

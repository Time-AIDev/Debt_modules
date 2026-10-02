import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { api, MALFORMED_BODY, CHANGED_EVENT, AUTH_REQUIRED_EVENT, DATA_EPOCH_EVENT, QUIET_AFTER_MS } from './api.js'
import { setRole, setOfficer } from './identity.jsx'

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
    headers: { get: () => null },
  }
}

beforeEach(() => {
  window.localStorage.clear()
  setRole('OFFICER')
  setOfficer('u-1')
})
afterEach(() => vi.restoreAllMocks())

describe('api transport', () => {
  it('sends the signing headers on every GET', async () => {
    setRole('MANAGER')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ ok: true }))
    await api.shellSummary()
    const [, init] = fetchMock.mock.calls[0]
    expect(init.headers['X-Volt-Role']).toBe('MANAGER')
    expect(init.headers['X-Volt-Officer']).toBe('u-1')
  })

  it('passes cancellation through the lightweight customer search transport', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ items: [] }))
    const controller = new AbortController()

    await api.customerSearch({ q: 'ส', limit: 6 }, { signal: controller.signal })

    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/api/v1/customers/search?q=%E0%B8%AA&limit=6')
    expect(init.signal).toBe(controller.signal)
  })

  it('announces a successful write on the changed event', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ case: {} }))
    const seen = vi.fn()
    window.addEventListener(CHANGED_EVENT, seen)
    await api.setNextAction('c-1', { next_action: 'CALL', next_action_on: '2026-10-24' })
    expect(seen).toHaveBeenCalled()
    window.removeEventListener(CHANGED_EVENT, seen)
  })

  it('turns a malformed 200 into the same Problem shape as a refusal', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true, status: 200, json: async () => { throw new Error('bad json') },
    })
    await expect(api.officers()).rejects.toMatchObject({ problem: { code: MALFORMED_BODY.code } })
  })

  it('reads the refusal envelope off a failed call', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({
      code: 'board_move_reason_required', status: 422, message_th: 'ต้องระบุเหตุผล', errors: [], extensions: {},
    }, 422))
    await expect(api.boardMove({})).rejects.toMatchObject({
      problem: { code: 'board_move_reason_required', message_th: 'ต้องระบุเหตุผล' },
    })
  })

  it('signals the auth gate only for auth_required 401s', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ code: 'auth_required' }, 401))
    const seen = vi.fn()
    window.addEventListener(AUTH_REQUIRED_EVENT, seen)
    await expect(api.officers()).rejects.toBeTruthy()
    expect(seen).toHaveBeenCalledTimes(1)
    window.removeEventListener(AUTH_REQUIRED_EVENT, seen)

    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ code: 'login_failed' }, 401))
    const seenAgain = vi.fn()
    window.addEventListener(AUTH_REQUIRED_EVENT, seenAgain)
    await expect(api.authPassword({ username: 'x', password: 'y' })).rejects.toBeTruthy()
    expect(seenAgain).not.toHaveBeenCalled()
    window.removeEventListener(AUTH_REQUIRED_EVENT, seenAgain)
  })

  it('marks the poll, and whatever the page sends after a quiet minute, as background', async () => {
    // Fix-all F4: the server does not move the 30-minute idle clock for these.
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({}))
    const background = (n) => fetchMock.mock.calls[n][1].headers['X-Volt-Background']
    window.dispatchEvent(new Event('keydown'))            // the person is working
    await api.shellSummary()
    await api.dataState({ background: true })             // the poll
    expect(background(0)).toBeUndefined()
    expect(background(1)).toBe('1')
    vi.spyOn(Date, 'now').mockReturnValue(Date.now() + QUIET_AFTER_MS + 1000)
    await api.shellSummary()                               // a refetch nobody asked for
    expect(background(2)).toBe('1')
    window.dispatchEvent(new Event('pointerdown'))        // back at the desk
    await api.shellSummary()
    expect(background(3)).toBeUndefined()
  })

  it('announces a moved import epoch once per change', async () => {
    const epoch = (n) => ({
      ok: true, status: 200, json: async () => ({}),
      headers: { get: (k) => (k === 'x-volt-data-epoch' ? String(n) : null) },
    })
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(epoch(4))
    const seen = vi.fn()
    window.addEventListener(DATA_EPOCH_EVENT, seen)
    await api.shellSummary()                 // first sight seeds, never fires
    expect(seen).not.toHaveBeenCalled()
    await api.shellSummary()                 // the same epoch is not news
    expect(seen).not.toHaveBeenCalled()
    fetchMock.mockResolvedValue(epoch(5))
    await api.shellSummary()
    expect(seen).toHaveBeenCalledTimes(1)
    window.removeEventListener(DATA_EPOCH_EVENT, seen)
  })

  it('uploads a file with the filename header and starts its operation', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ run: {} }))
    const file = new File(['a,b'], 'sheet.csv', { type: 'text/csv' })
    await api.createImport(file)
    const [url, init] = fetchMock.mock.calls.find(([path]) => String(path) === '/api/v1/imports:start')
    expect(String(url)).toBe('/api/v1/imports:start')
    expect(init.headers['X-Volt-Filename']).toBe(encodeURIComponent('sheet.csv'))
    expect(init.headers['X-Volt-Upload']).toBeTruthy()
  })
})

describe('feedback round 2 routes (TASK-001)', () => {
  it('reads one officer row from the reports route', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ officer: {} }))
    await api.reportsOfficer('nantapol')
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/reports/officers/nantapol')
  })

  it('posts the bulk assignment as one request', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ count: 2 }))
    await api.assignCustomers({ customer_uids: ['c-1', 'c-2'], officer_uid: 'o-1' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toBe('/api/v1/customers:assign')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toMatchObject({ officer_uid: 'o-1' })
  })

  it('posts a ladder stage move for lease and cash cases', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ case: {} }))
    await api.setCaseStage('case-1', { to_stage: 'NORMAL', reason: 'x' })
    await api.setCashCaseStage('case-2', { to_stage: 'NORMAL', reason: 'x' })
    expect(String(fetchMock.mock.calls[0][0])).toBe('/api/v1/cases/case-1:set-stage')
    expect(String(fetchMock.mock.calls[1][0])).toBe('/api/v1/cash-cases/case-2:set-stage')
  })

  it('posts a recovery strategy change', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ recovery: {} }))
    await api.changeRecoveryStrategy('rec-1', { strategy: 'LEGAL', reason: 'x' })
    expect(String(fetchMock.mock.calls[0][0])).toBe('/api/v1/recovery-cases/rec-1:change-strategy')
  })

  it('reads the PTP report with its date filters', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ rows: [], totals: {} }))
    await api.ptpReport({ from: '2026-10-01', to: '2026-10-31' })
    const url = String(fetchMock.mock.calls[0][0])
    expect(url).toContain('/api/v1/reports/ptps?')
    expect(url).toContain('from=2026-10-01')
    expect(url).toContain('to=2026-10-31')
  })

  it('exports the PTP report through the governed POST export', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true, status: 200, text: async () => 'customer,amount\nก,100\n',
      headers: { get: (k) => (k === 'Content-Disposition' ? 'attachment; filename="ptp-report_2026-10-01_2026-10-31.csv"' : null) },
    })
    const out = await api.ptpReportExport({ from: '2026-10-01', to: '2026-10-31' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toBe('/api/v1/reports/ptps:export')
    expect(init.method).toBe('POST')
    expect(out.filename).toBe('ptp-report_2026-10-01_2026-10-31.csv')
    expect(out.text).toContain('customer,amount')
  })

  it('reads the split buckets and posts the split', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse([]))
    await api.assignSplitBuckets()
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/customers:assign-split/buckets')
    fetchMock.mockResolvedValue(jsonResponse({ total: 500 }))
    await api.assignSplit({ bucket: 'CURRENT', officer_uids: ['o-1'], dry_run: true })
    const [url, init] = fetchMock.mock.calls[1]
    expect(String(url)).toBe('/api/v1/customers:assign-split')
    expect(JSON.parse(init.body)).toMatchObject({ bucket: 'CURRENT', dry_run: true })
  })

  it('fetches the assignment template with the role headers and uploads a filled one', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse('volt_id,customer_no,officer\n'))
    const out = await api.assignTemplate()
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/imports/assignments:template')
    expect(out.text).toContain('volt_id,customer_no,officer')
    const file = new File(['volt_id,customer_no,officer\n'], 'assignments.csv', { type: 'text/csv' })
    fetchMock.mockResolvedValue(jsonResponse({ count: 1 }))
    await api.assignTemplateUpload(file)
    const [url, init] = fetchMock.mock.calls.find(([path]) => String(path) === '/api/v1/imports/assignments:start')
    expect(String(url)).toBe('/api/v1/imports/assignments:start')
    expect(init.headers['X-Volt-Filename']).toBe(encodeURIComponent('assignments.csv'))
  })
})

describe('feedback round 2 data routes (TASK-212)', () => {
  it('starts a receipt run and reads it back', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ uid: 'r-1' }))
    const file = new File(['x'], 'receipt.xlsx', { type: 'application/octet-stream' })
    await api.peakReceiptStart(file)
    const startCall = fetchMock.mock.calls.find(([path]) => String(path) === '/api/v1/pipelines/peak-receipt:start')
    expect(startCall[1].headers['X-Volt-Filename']).toBe(encodeURIComponent('receipt.xlsx'))
    await api.peakReceiptRun('r-1')
    expect(fetchMock.mock.calls.some(([path]) => String(path).includes('/api/v1/pipelines/peak-receipt/runs/r-1'))).toBe(true)
    await api.peakReceiptLastRun()
    expect(fetchMock.mock.calls.some(([path]) => String(path).includes('/api/v1/pipelines/peak-receipt/last-run'))).toBe(true)
    await api.peakReceiptRows(7, { verdict: 'UNMATCHED' })
    const rowsCall = fetchMock.mock.calls.find(([path]) => String(path).includes('/landing-runs/7/rows'))
    expect(String(rowsCall[0])).toContain('verdict=UNMATCHED')
    await api.peakReceiptApply(7, {})
    expect(fetchMock.mock.calls.some(([path]) => String(path) === '/api/v1/pipelines/peak-receipt/landing-runs/7:apply')).toBe(true)
  })

  it('reads and decides conflicts and retires a decision', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ rows: [], total: 0 }))
    await api.peakConflicts(7, { limit: 1 })
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/pipelines/peak-report/landing-runs/7/conflicts')
    expect(String(fetchMock.mock.calls[0][0])).toContain('limit=1')
    await api.peakConflictsDecide(7, { customer_no: 'c-1', decisions: [] })
    expect(String(fetchMock.mock.calls[1][0])).toBe('/api/v1/pipelines/peak-report/landing-runs/7/conflicts:decide')
    await api.peakDecisionRetire(3)
    expect(String(fetchMock.mock.calls[2][0])).toBe('/api/v1/pipelines/peak-report/field-decisions/3:retire')
  })

  it('searches and links the case-side PEAK codes', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ codes: [] }))
    await api.casePeakCodes('c-1', 'VC')
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/cases/by-customer/c-1/peak-codes')
    expect(String(fetchMock.mock.calls[0][0])).toContain('q=VC')
    await api.casePeakLink('c-1', { contact_code: 'VC1', reason: 'x' })
    expect(String(fetchMock.mock.calls[1][0])).toBe('/api/v1/cases/by-customer/c-1/peak-link')
    expect(fetchMock.mock.calls[1][1].method).toBe('POST')
  })
})

// One status language (final design, brief §3.2 "Mapping of every state").
// Every lookup returns { kind, key }: `kind` is a StatusIcon kind (do · problem ·
// moving-1…4 · idle · done · off · moneyin · lock) and `key` is the i18n key of the word
// to show next to it — render t(key), passing the slots a word carries ({when}, {who}…).
// An unknown code comes back as { kind: 'idle', key: <the code> }: t() of an unknown key
// is the key itself, so the raw code shows — never a blank. A missing code is "—".
import th from './i18n/th.js'

/** The pie for "in progress": 0 done → idle, all done → done, else moving-1…4 by quarter. */
export function movingKind(done, total) {
  const d = Number(done)
  const n = Number(total)
  if (!Number.isFinite(d) || !Number.isFinite(n) || n <= 0 || d <= 0) return 'idle'
  if (d >= n) return 'done'
  return `moving-${Math.min(4, Math.max(1, Math.round((d / n) * 4)))}`
}

// family → [key prefix, { CODE: kind }]. The codes are the ones the API serves
// (backend/app: cases.py, today.py, board.py, journey.py, peak_documents.py,
// invoice_pipeline.py, pipelines/*, main.py audit) plus a few named states the
// helpers below derive from served flags (marked).
export const FAMILIES = {
  payment: ['pay.', { CURRENT: 'done', LATE: 'do', PENDING: 'moving-2', NPL: 'problem', CLOSED: 'done', TERMINATED: 'off', NOT_INSTALLED: 'idle' }],
  // today.py TIERS (+ WORKED: the served worked_today flag).
  tier: ['status.tier.', {
    PTP_DUE_TODAY: 'do', NEXT_ACTION_DUE: 'do', BROKEN_PTP: 'problem', AT_RISK_TWO_MISSED: 'problem',
    NEW_ARREARS: 'idle', ANSWER_WAITING: 'moving-2', ROUTINE: 'idle', WORKED: 'done',
  }],
  // A Today row's exceptions: contact_lock LOCKED · paid before the promise · stale payment data · worked.
  today: ['status.today.', { LOCKED: 'lock', MONEY_IN: 'moneyin', STALE: 'problem', WORKED: 'done' }],
  // board.py columns (+ AWAITING_MANAGER: a card's pending backward move).
  board: ['status.board.', { col_01H8X: 'do', col_01H8Y: 'idle', col_01H8Z: 'moving-2', col_01H90: 'problem', AWAITING_MANAGER: 'do' }],
  ptp: ['status.ptp.', { OPEN: 'do', BROKEN: 'problem', KEPT: 'done', KEPT_PARTIAL: 'done', RENEGOTIATED: 'moving-2', CANCELLED: 'off' }],
  // Issue tickets (+ NONE: no ticket open).
  issue: ['status.issue.', { OPEN: 'do', IN_PROGRESS: 'moving-2', RESOLVED: 'done', NONE: 'done' }],
  // Manager reviews: the case's (OPEN · ANSWERED) and the journey's (OPEN · DECIDED).
  review: ['status.review.', { OPEN: 'do', ANSWERED: 'done', DECIDED: 'done' }],
  invoice: ['inv.state.', {
    PAID: 'done', PARTIALLY_PAID: 'moving-2', ISSUED: 'idle', SENT: 'idle', OVERDUE: 'problem',
    DRAFT: 'off', CANCELLED: 'off', AR_REVIEW: 'moving-1', REVIEW_ORIGINAL: 'moving-1',
  }],
  // peak_documents.py STATES (the Payments screen's PEAK drafts).
  peakDoc: ['status.peakDoc.', { PENDING: 'moving-1', DRAFT_CREATED: 'moving-1', APPROVED_IN_PEAK: 'done', REJECTED: 'problem', UNSENT: 'off' }],
  // invoice_pipeline.py: a release condition or gate is OPEN (no evidence yet) or PASSED.
  preinstall: ['status.pre.', { PASSED: 'done', OPEN: 'idle' }],
  recovery: ['status.rec.', { IN_PROGRESS: 'moving-2', RESOLVED: 'done', SUPERSEDED: 'off' }],
  outcome: ['status.outcome.', { FULL: 'done', PARTIAL: 'done', NO_CONCLUSION: 'done', CLOSED_WRITE_OFF: 'done' }],
  lot: ['status.lot.', { PLANNED: 'idle', UNINSTALLED: 'moving-1', COUNTED: 'moving-2', GRADED: 'moving-3', PRICED: 'moving-4', SOLD: 'done' }],
  // journey.py service accounts: PREPAID · BILLING · CANCELLED (+ BILLING_UNPAID and
  // DECLINE_REQUESTED, derived by serviceStatus()).
  service: ['status.svc.', { BILLING_UNPAID: 'problem', BILLING: 'do', DECLINE_REQUESTED: 'moving-2', PREPAID: 'done', CANCELLED: 'off' }],
  // แหล่งข้อมูล. Served codes: run states running/done/failed (pipelines/runs.py) and
  // OK/FAILED (landing), PEAK match verdicts EXACT/CANDIDATE/UNMATCHED/REJECTED. The rest
  // are named states the helpers below derive from served flags.
  import: ['status.import.', {
    SERVING: 'done', RESERVE: 'idle', READ_ONLY: 'idle', NO_FILE: 'idle', LAST_RESORT: 'off', NOT_CONNECTED: 'off',
    AUTO_ON: 'done', AUTO_OFF: 'off',
    running: 'moving-1', done: 'done', failed: 'problem', OK: 'done', FAILED: 'problem',
    CONNECTED: 'done', UNREACHABLE: 'problem', NOT_CONFIGURED: 'off',
    STALE: 'do',
    REVIEW: 'do', EXACT: 'done', CANDIDATE: 'do', UNMATCHED: 'do', CONFLICT: 'do', DECIDED: 'done',
    REJECTED: 'problem', LINKED: 'done', REPORT_STAGED: 'do', REPORT_APPLIED: 'done', RECEIPTS_NEVER: 'idle',
    SHEET_STAGED: 'idle',
    MATCH: 'done', DIFFERS: 'problem', UNJUDGED: 'idle', NO_BASE: 'off',
  }],
  // calendar_feed.py item kinds; the words are the calendar's own.
  calendar: ['cal.kind.', {
    PTP_DUE: 'do', NEXT_ACTION: 'do', ISSUE_DEADLINE: 'do', REVIEW_SLA: 'do', NPL_BUYBACK: 'problem',
    RESTRUCTURE: 'moving-2', SETTLEMENT: 'moving-2', REMINDER_BATCH: 'idle', NOTICE: 'idle', PTP_PAYMENT: 'moneyin',
  }],
  // routers/payments.py allocation lines: allocated · nothing attempted yet · held until OD-02 is ruled.
  allocation: ['payments.alloc.', { ALLOCATED: 'done', NOT_ALLOCATED: 'idle', AWAITING_RULING: 'off' }],
  // reports.py weekly editions: the one that is out · replaced by a later edition of its week.
  edition: ['reports.editionState.', { PUBLISHED: 'done', SUPERSEDED: 'off' }],
  // Small states the other screens name from served flags: a register row (settingStatus),
  // a band set in use, a review past its SLA, a queue with work waiting, a dated item overdue.
  setting: ['settings.lock.', { EDITABLE: 'done', LOCKED: 'off', OWNER: 'off', MANAGER: 'off' }],
  bandSet: ['settings.bandSet.', { ACTIVE: 'done' }],
  reviewSla: ['reviews.slaState.', { BREACHED: 'problem', WITHIN: 'do' }],
  queue: ['dash.nextState.', { WAITING: 'do', CLEAR: 'done' }],
  due: ['cal.due.', { OVERDUE: 'problem' }],
  // main.py audit entries: outcome OK | REFUSED.
  audit: ['status.audit.', { OK: 'done', REFUSED: 'problem' }],
}

/** The generic lookup: statusOf('ptp', 'BROKEN') → { kind: 'problem', key: 'status.ptp.BROKEN' }. */
export function statusOf(family, code) {
  if (code === null || code === undefined || code === '') return { kind: 'idle', key: 'common.none' }
  const [prefix, kinds] = FAMILIES[family] || ['', {}]
  const kind = kinds[code]
  return kind ? { kind, key: `${prefix}${code}` } : { kind: 'idle', key: String(code) }
}

export const paymentStatus = (code) => statusOf('payment', code)
export const tierStatus = (code) => statusOf('tier', code)
export const todayException = (code) => statusOf('today', code)
export const boardColumnStatus = (id) => statusOf('board', id)
export const ptpStatus = (code) => statusOf('ptp', code)
export const issueStatus = (code) => statusOf('issue', code)
export const reviewStatus = (code) => statusOf('review', code)
export const invoiceStatus = (code) => statusOf('invoice', code)
export const peakDocStatus = (code) => statusOf('peakDoc', code)
export const preinstallStatus = (code) => statusOf('preinstall', code)
export const recoveryStatus = (code) => statusOf('recovery', code)
export const recoveryOutcome = (code) => statusOf('outcome', code)
export const lotStatus = (code) => statusOf('lot', code)
export const importStatus = (code) => statusOf('import', code)
export const calendarKind = (code) => statusOf('calendar', code)
export const auditStatus = (code) => statusOf('audit', code)

/** A settings register row (routers/settings.py): locked for a ruling · editable in this role · owner only · manager and above. */
export function settingStatus(row) {
  const r = row || {}
  if (r.lock === 'locked' || r.locked) return statusOf('setting', 'LOCKED')
  if (r.editable === true) return statusOf('setting', 'EDITABLE')
  return statusOf('setting', r.editable_by === 'OWNER' ? 'OWNER' : 'MANAGER')
}

/** Pre-install progress "ผ่าน {done} จาก {total}": the pie by share passed, all passed → done. */
export function preinstallProgress(done, total) {
  return { kind: movingKind(done, total), key: 'status.pre.progress' }
}

/** Released "ปล่อยแล้ว {date}". */
export function preinstallReleased() {
  return { kind: 'done', key: 'status.pre.released' }
}

/**
 * An NPL case (brief §3.2): no recovery record yet → do "ยังไม่เลือกแนวทาง"; IN_PROGRESS →
 * the pie by steps done of 4; RESOLVED → done in its outcome's word; SUPERSEDED → off; a
 * path that cannot be opened (available false, "ยังใช้ไม่ได้ · รอ {decision}") → off.
 * `status`/`outcome` are the recovery record's.
 */
export function nplCaseStatus({ status, outcome, done = 0, available } = {}) {
  if (available === false) return { kind: 'off', key: 'status.npl.UNAVAILABLE' }
  if (!status) return { kind: 'do', key: 'status.npl.UNDECIDED' }
  if (status === 'IN_PROGRESS') {
    // choosing the path is step 1, so an open path shows at least a quarter
    return { kind: `moving-${Math.min(4, Math.max(1, Number(done) || 0))}`, key: 'status.rec.IN_PROGRESS' }
  }
  if (status === 'RESOLVED') return outcome ? recoveryOutcome(outcome) : recoveryStatus(status)
  return recoveryStatus(status)
}

/**
 * A service month 37+ account: CANCELLED off · PREPAID done · BILLING with an OVERDUE
 * service invoice → problem ("ค้างบิล") · a decline requested → moving-2 ("รอ {decision}")
 * · BILLING do.
 */
export function serviceStatus(account) {
  const a = account || {}
  if (a.status !== 'BILLING') return statusOf('service', a.status)
  if ((a.service_invoices || []).some((i) => i.state === 'OVERDUE')) return statusOf('service', 'BILLING_UNPAID')
  if (a.decline_requested) return statusOf('service', 'DECLINE_REQUESTED')
  return statusOf('service', 'BILLING')
}

/** A background run (running · done · failed; OK · FAILED): running → the pie by read of total. */
export function runStatus(state, done, total) {
  if (state !== 'running') return importStatus(state)
  const kind = movingKind(done, total)
  return { kind: kind === 'idle' || kind === 'done' ? 'moving-1' : kind, key: 'status.import.running' }
}

// ponytail: the source chain's rungs carry words, not state codes (migration.py
// _source_chain) — matched on the served English word; add a code server-side if it moves.
const RUNG = { Serving: 'SERVING', Reserve: 'RESERVE', Fallback: 'RESERVE', 'Read-only': 'READ_ONLY',
  'No file yet': 'NO_FILE', 'Not connected': 'NOT_CONNECTED', 'Last resort': 'LAST_RESORT' }

/** One rung of the served source chain → its status; an unknown word shows as served. */
export function rungStatus(rung) {
  const r = rung || {}
  if (r.serving) return importStatus('SERVING')
  if (r.code === 'STALE_SYSTEM') return importStatus('LAST_RESORT')
  const code = RUNG[r.state_en]
  return code ? importStatus(code) : { kind: 'idle', key: r.state_th || r.state || r.code || 'common.none' }
}

/** An integration: not configured → off · unreachable → problem · else connected. */
export function connectionStatus({ configured, reachable } = {}) {
  if (!configured) return importStatus('NOT_CONFIGURED')
  return importStatus(reachable === false ? 'UNREACHABLE' : 'CONNECTED')
}

/** A reconciliation row (migration.py run_report): judged false → UNJUDGED · matches → MATCH · false → DIFFERS · null → NO_BASE. */
export function reconStatus(row) {
  const r = row || {}
  if (r.judged === false) return importStatus('UNJUDGED')
  if (r.matches === true) return importStatus('MATCH')
  if (r.matches === false) return importStatus('DIFFERS')
  return importStatus('NO_BASE')
}

/**
 * Instalment cells (colours, not icons): kind ∈ paid · late · notdue · link · closed ·
 * part → the class `monthgrid__cell--<kind>`. Codes: payment_summary cycles (PAID ·
 * OVERDUE · UPCOMING · NO_AMOUNT, + partly_paid) and the sheet month grid (PAID · LATE
 * · LINK_SENT · CLOSED · empty). Any other sheet kind looks "not due" and says its code.
 */
const CELL = { REJECTED: 'rejected', INFERRED_PAID: 'inferred', SHEET_REPORTED_PAID: 'reported', UNCONFIRMED: 'unconfirmed', PAID: 'paid', OVERDUE: 'late', LATE: 'late', UPCOMING: 'notdue', NO_AMOUNT: 'notdue', LINK_SENT: 'link', CLOSED: 'closed' }
export function cellStatus(code, partly = false) {
  if (partly) return { kind: 'part', key: 'status.cell.part' }
  if (!code) return { kind: 'notdue', key: 'status.cell.notdue' }
  const kind = CELL[code]
  return kind ? { kind, key: `status.cell.${kind}` } : { kind: 'notdue', key: String(code) }
}

/** A ladder rung by its index against the current one: passed · current · later. */
export function ladderRung(index, current) {
  const kind = current < 0 ? 'later' : index < current ? 'passed' : index === current ? 'current' : 'later'
  return { kind, key: `status.ladder.${kind}` }
}

/** The colour of a status kind — for a dot that stands for it (the context tab's customer dot). */
export function statusColor(kind) {
  if (kind === 'do') return 'var(--volt-yellow)'
  if (kind === 'problem') return 'var(--volt-red)'
  if (kind === 'done' || kind === 'moneyin') return 'var(--volt-green)'
  if (String(kind).startsWith('moving')) return 'var(--volt-ink)'
  return 'var(--volt-ink-2)'
}

// Words only — no status meaning, no icon: contact channels and case event kinds.
const CHANNEL = { PHONE: 'drawer.channel.phone', LINE: 'drawer.channel.line', VISIT: 'drawer.channel.visit' }
export const channelKey = (code) => CHANNEL[code] || (code ? String(code) : 'common.none')
export const eventKey = (code) => (th[`case.event.${code}`] ? `case.event.${code}` : code ? String(code) : 'common.none')

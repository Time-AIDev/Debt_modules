import { causeLabel } from '../screens/Terminated.jsx'
import { Fragment, useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { money, int, date as fmtDate, when, monthLabel } from '../lib/format.js'
import {
  paymentStatus, tierStatus, ptpStatus, issueStatus, reviewStatus, invoiceStatus,
  ladderRung, statusColor, channelKey, eventKey,
} from '../lib/status.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useIdentity, atLeast } from '../lib/identity.jsx'
import { useRecents } from '../lib/recents.jsx'
import { useDictionary, labelFor } from '../lib/dictionaries.js'
import { EntityChip, SourceChip } from './Chips.jsx'
import { StatusIcon, StatusPill, NeutralChip } from './StatusIcon.jsx'
import { Icon } from './Icon.jsx'
import { InfoPopover } from './InfoPopover.jsx'
import { PhoneLine } from './PhoneLine.jsx'
import { CustomerIdentity } from './CustomerIdentity.jsx'
import { InvoiceReviews } from './InvoiceReviews.jsx'
import { TerminateDrawer } from './TerminateDrawer.jsx'
import { MoveDrawer } from './MoveDrawer.jsx'
import { DataTable } from './DataTable.jsx'
import { ManualInvoiceMatch } from './ManualInvoiceMatch.jsx'
import { PreInstallCard } from './PreInstallCard.jsx'
import { CycleGrid } from './CycleGrid.jsx'
import { ServiceDeferrals, InvoiceDeferral } from './ServiceDeferrals.jsx'
import { InstallationConfirmation } from './InstallationConfirmation.jsx'
import { OfficerScoreboard } from './OfficerScoreboard.jsx'
import { ContractDetailsDrawer } from './ContractDetailsDrawer.jsx'
import { SocialComposer } from './SocialComposer.jsx'
import { openPromise } from './ContactDrawer.jsx'
import { LoadError, Problem } from './Problem.jsx'
import { useToast } from './Toast.jsx'

const CHANNEL_ICON = { PHONE: 'phone', LINE: 'chat', VISIT: 'user' }
const FAMILY = { do: 'do', problem: 'problem', done: 'done', moneyin: 'done' }
const TABS = [
  ['overview', 'record.tabOverview'], ['invoices', 'record.tabInvoices'], ['history', 'record.tabHistory'],
  ['issues', 'record.tabIssues'], ['monthly', 'record.tabMonthly'],
]

/** The business day the case detail was computed on (ISO). The case detail serves it
 * on its payment summary; Today passes its own run date. */
export function businessDateOf(data) {
  return data?.work_item?.business_date || data?.payment_summary?.business_date || undefined
}

// "hh:mm" of a served stamp ("2026-10-23T09:25:03" or "2026-06-30 14:58:58"), '' if none.
const hhmm = (stamp) => (/[T ](\d{2}):(\d{2})/.exec(String(stamp || '')) || []).slice(1).join(':')

// The served list is in creation order; the latest of a status is the one to speak of.
const latest = (ptps, status) => ptps.filter((p) => p.status === status)
  .sort((a, b) => String(b.promise_date || '').localeCompare(String(a.promise_date || '')))[0]

/** Officer uid → the roster's name (the raw uid when the roster does not know it). */
function useOfficerName() {
  const { roster } = useIdentity()
  const { lang } = usePrefs()
  return (uid) => {
    if (!uid) return '—'
    const hit = (roster || []).find((r) => r.uid === uid)
    return (hit && (lang === 'en' ? hit.display_name_en : hit.display_name_th)) || uid
  }
}

/** A word for a code, or the code itself when no word exists (never a blank). */
function useWord() {
  const { t } = usePrefs()
  return (key, code) => {
    const word = t(key)
    return word === key ? (code || '—') : word
  }
}

/** The design's card head: title, then whatever sits beside it. */
function Card({ title, extra, tip, children, className }) {
  return (
    <section className={`card${className ? ` ${className}` : ''}`}>
      <header className="card__head" title={tip}>
        <h2>{title}</h2>
        {extra}
      </header>
      {children}
    </section>
  )
}

/** A crm.lead customer with no money row: identity and order facts, no case. */
function IdentityOnlyRecord({ data, mode, onClose }) {
  const { t, lang } = usePrefs()
  const word = useWord()
  const customer = data.customer || {}
  const crm = customer.odoo_crm
  const order = data.order || {}
  const facts = [
    [t('record.orderStage'), order.order_status],
    [t('record.orderType'), order.order_type ? word(`record.contractType.${order.order_type}`, order.order_type) : null],
    [t('record.orderWatt'), order.watt !== null && order.watt !== undefined ? int(order.watt) : null],
    [t('record.orderPhase'), order.phase],
    [t('record.orderEpc'), order.epc],
    [t('record.orderProvince'), order.province],
    [t('record.orderLead'), order.sales_lead],
    [t('record.orderRef'), customer.order_ref],
  ].filter(([, value]) => value !== null && value !== undefined && value !== '')
  // The served reason is an English developer phrase; the one the book serves has a Thai word.
  const reason = data.reason === 'no money row in Odoo' ? t('record.identityNoMoney') : data.reason

  return (
    <div className={`case case--${mode}`}>
      <header className="case__head" aria-label={t('record.debtor')}>
        <div className="case__top">
          <div className="case__chips">
            <NeutralChip title={t('record.sourceTip', { source: customer.data_source || 'ODOO' })}>{customer.data_source || 'ODOO'}</NeutralChip>
          </div>
          {mode === 'sheet' ? <CloseButton onClose={onClose} /> : null}
        </div>
        <div className="case__identity">
          <div className="case__nameRow"><h1 className="case__name">{crm?.url ? (
            <a className="case__odooLink" href={crm.url} target="_blank" rel="noopener noreferrer">{customer.display_name}</a>
          ) : customer.display_name}</h1></div>
          <div className="case__idRow">
            <CustomerIdentity customer={customer} />
          </div>
        </div>
      </header>
      <div className="case__body">
        <Card title={t('record.identityTitle')}>
          <div className="card__body case__stack">
            <p className="case__text">{lang === 'en' ? data.identity_note_en : data.identity_note_th}</p>
            {facts.length ? (
              <dl className="kv">
                {facts.map(([label, value]) => (
                  <Fragment key={label}>
                    <dt>{label}</dt>
                    <dd className="num">{String(value)}</dd>
                  </Fragment>
                ))}
              </dl>
            ) : null}
          </div>
          <p className="card__note">{t('record.identityReason', { reason })}</p>
        </Card>
      </div>
    </div>
  )
}

function CloseButton({ onClose }) {
  const { t } = usePrefs()
  return (
    <button type="button" className="btn btn--quiet case__close" aria-label={t('common.close')}
            title={t('common.close')} onClick={onClose}>
      <Icon name="close" size={18} />
    </button>
  )
}

/**
 * ① "สิ่งที่ต้องทำ" — why this case is in the list today and what the next step is.
 * Each fact is said once (Arina, 2026-09-24): line 1 is the next task (its date only
 * when it is not today), line 2 says why — a promise that is the reason is folded in
 * there — then a promise not said yet, money in, the day's lock and "worked", each
 * only when true. Every part is a served fact: the Today row's tier and worked stamp
 * (when docked beside it), the case's next action, its promises and the daily lock.
 */
function TodoCallout({ data, item: row, biz, busy, problem, onClosePaid }) {
  const { t, lang } = usePrefs()
  const officerName = useOfficerName()
  const nextActions = useDictionary('NEXT_ACTION')
  const results = useDictionary('CONTACT_RESULT')
  const kase = data.case || {}
  const ptps = data.ptps || []
  const lock = data.work_item?.contact_lock
  // Today's row speaks for this case only (the pane may still hold the last one's detail).
  const item = row && (!row.customer || row.customer.uid === data.customer?.uid) ? row : null
  const tier = item?.tier || data.work_item?.tier
  const head = tier ? tierStatus(tier)
    : kase.payment_status ? paymentStatus(kase.payment_status) : { kind: 'idle', key: 'common.none' }

  const open = ptps.find((p) => p.status === 'OPEN')
  const dueToday = open && biz && open.promise_date === biz ? open : null
  const broke = tier === 'BROKEN_PTP' ? latest(ptps, 'BROKEN') || latest(ptps, 'RENEGOTIATED') : null
  const moved = openPromise(data)
  const promise = moved && moved !== (dueToday || broke) ? moved : null

  const why = dueToday ? t('record.todoDueToday', { amount: money(dueToday.promised_amount) })
    : broke ? [t('record.todoBroke', { amount: money(broke.promised_amount), date: fmtDate(broke.promise_date) }),
      open ? '' : t('record.todoNotRenegotiated')].filter(Boolean).join(' · ')
      : !kase.next_action ? t('record.todoNoTask')
        : tier && tier !== 'PTP_DUE_TODAY' && tier !== 'NEXT_ACTION_DUE' ? t(head.key) : ''

  const [day, time] = String(kase.next_action_on || '').split(/[T ]/)
  const clock = time ? time.slice(0, 5) : ''
  const on = !day ? ''
    : day === biz ? clock
      : promise && kase.next_action === 'FOLLOW_PTP' && day === promise.promise_date ? '' : [fmtDate(day), clock].filter(Boolean).join(' ')
  const title = kase.next_action
    ? [labelFor(nextActions, kase.next_action, lang), on].filter(Boolean).join(' · ')
    : t(head.key)
  // The head icon's word rides as its name — unless the headline or the reason says it.
  const iconWord = kase.next_action && why !== t(head.key) ? t(head.key) : undefined

  const early = open?.paid_before_due
  const locked = lock?.state === 'LOCKED'
  const lockedAt = locked
    ? ((lang === 'en' ? lock.locked_at_local_en : lock.locked_at_local_th) || '').match(/\d{1,2}:\d{2}/)?.[0] || ''
    : ''
  // Worked today is a same-day stamp: the time alone. When the day's lock is that same
  // contact, "worked" and "slot used" are one fact on one line (Arina: every fact once).
  const workedAt = item?.worked_today ? hhmm(item.worked_at) : ''
  const sameContact = locked && workedAt && workedAt === lockedAt
  const workedResult = kase.last_result ? labelFor(results, kase.last_result, lang) : ''
  const lockWords = locked ? [t('record.todoLock'), officerName(lock.locked_by)] : []
  const pill = promise ? ptpStatus(promise.status) : null

  return (
    <section className={`case__todo case__todo--${FAMILY[head.kind] || 'warm'}`} aria-label={t('record.todo')}>
      <p className="case__todoTitle">
        {/* the word rides as the icon's name and tooltip, never as a second visible line */}
        {iconWord
          ? <span className="case__todoIcon" role="img" aria-label={iconWord} title={iconWord}><StatusIcon kind={head.kind} /></span>
          : <StatusIcon kind={head.kind} />}
        {title}
      </p>
      {why ? <p className="case__todoWhy num">{why}</p> : null}
      {promise ? (
        <p className="case__todoLine">
          <StatusPill kind={pill.kind}>{t(pill.key)}</StatusPill>
          <span className="num">{t('record.todoPromise', { date: fmtDate(promise.promise_date), amount: money(promise.promised_amount) })}</span>
        </p>
      ) : null}
      {early ? (
        <p className="case__todoLine">
          <StatusIcon kind="moneyin" />
          <span className="num">{t('record.todoMoneyIn', { ref: early.receipt_no || '—', amount: money(early.amount), date: fmtDate(early.on) })}</span>
          <button type="button" className="btn btn--sm" disabled={busy} onClick={onClosePaid}>{t('record.closePtpPaid')}</button>
        </p>
      ) : null}
      {locked && !sameContact ? (
        <p className="case__todoLine">
          <StatusIcon kind="lock" />
          <span>{[...lockWords, lockedAt].filter(Boolean).join(' · ')}</span>
        </p>
      ) : null}
      {item?.worked_today ? (
        <p className="case__todoLine">
          <StatusIcon kind="done" />
          <span className="num">
            {[t('status.today.WORKED', { when: workedAt || when(item.worked_at) }), workedResult, ...(sameContact ? lockWords : [])]
              .filter(Boolean).join(' · ')}
          </span>
        </p>
      ) : null}
      {problem ? <Problem problem={problem} /> : null}
    </section>
  )
}

/** One contact line: when · channel · result · note · "นับตามกฎหมาย". */
function ContactRow({ c, full }) {
  const { t, lang } = usePrefs()
  const results = useDictionary('CONTACT_RESULT')
  const channel = t(channelKey(c.channel))
  return (
    <li className="case__row">
      <span className="case__when num">{full ? when(c.occurred_at) : fmtDate(String(c.occurred_at || '').slice(0, 10))}</span>
      {full
        ? <Icon name={CHANNEL_ICON[c.channel] || 'chat'} className="case__rowIcon" />
        : <Icon name={CHANNEL_ICON[c.channel] || 'chat'} className="case__rowIcon" title={channel} />}
      <span className="case__rowMain">
        <span className="case__rowTitle">
          {full ? <span className="case__muted">{channel} · </span> : null}
          {labelFor(results, c.result, lang)}
          {/* A contact recorded as the customer's own (a way through a locked slot). */}
          {c.direction === 'INBOUND' && c.result !== 'INBOUND' ? ` · ${t('record.inboundMark')}` : ''}
        </span>
        {c.note ? <span className="case__rowNote">{c.note}</span> : null}
      </span>
      {c.counted ? <NeutralChip>{t('record.counted')}</NeutralChip> : null}
      {c.not_counted_declared ? <NeutralChip>{t('record.notCounted')}</NeutralChip> : null}
    </li>
  )
}

/** A ticket: status pill · summary · "{team} · {deadline}". */
function IssueRow({ issue, stacked }) {
  const { t } = usePrefs()
  const word = useWord()
  const s = issueStatus(issue.status)
  const meta = `${word(`record.team.${issue.responsible_team}`, issue.responsible_team)} · ${fmtDate(issue.deadline)}`
  return (
    <li className={stacked ? 'case__issue case__issue--stacked' : 'case__issue'}>
      <span className="case__issuePill"><StatusPill kind={s.kind}>{t(s.key)}</StatusPill></span>
      <span className="case__rowMain">
        <span className="case__rowTitle">{issue.summary}</span>
        <span className="case__rowNote">{meta}</span>
      </span>
    </li>
  )
}

/**
 * The customer case (design D's case sheet): header, ① what to do, ② the ten facts,
 * ③ the ladder, ④ five tabs and ⑤ their content. One component in three places:
 * `mode="page"` (the /customers/{uid} route, Today and Workbook) and `"sheet"`
 * (the CaseSheet pop-up; the header then carries a close button → `onClose`).
 * `item` is the served Today row the case is docked beside (tier, worked stamp) — the
 * case detail itself does not serve those, so without it ① speaks from the payment status.
 */
export function RecordView({
  data, problem, businessDate, onRetry, onChanged, onLogContact, mode = 'page', onClose, item,
}) {
  const { t, lang } = usePrefs()
  const identity = useIdentity()
  const officerName = useOfficerName()
  const word = useWord()
  const toast = useToast()
  const dcStatuses = useDictionary('DC_STATUS')
  const { remember } = useRecents()
  const [tab, setTab] = useState('overview')
  const [terminateOpen, setTerminateOpen] = useState(false)
  // F05 / TASK-019: the manager's hand move, and F15 phase 2 (TASK-022).
  const [stageOpen, setStageOpen] = useState(false)
  const [stageBusy, setStageBusy] = useState(false)
  const [stageProblem, setStageProblem] = useState(null)
  const [contractOpen, setContractOpen] = useState(false)
  const [social, setSocial] = useState(null)
  // D05 / TASK-030: closing a promise the customer already paid (the receipt proves it).
  const [closingPtp, setClosingPtp] = useState(false)
  const [ptpProblem, setPtpProblem] = useState(null)

  const uid = data?.customer?.uid
  useEffect(() => {
    if (!uid) return
    remember({
      key: `case-${uid}`,
      label: data.customer.display_name,
      meta: t('nav.today'),
      // The tab dot is the customer's status colour (payment status → its icon's colour).
      color: statusColor(paymentStatus(data.case?.payment_status).kind),
      to: `/customers/${uid}`,
    })
    // Another customer: back to the overview, every drawer closed (design D, §1).
    setTab(data.pre_install ? 'invoices' : 'overview')
    setTerminateOpen(false)
    setStageOpen(false)
    setContractOpen(false)
    setSocial(null)
    setPtpProblem(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uid])

  // In the pop-up the close is there from the first frame, loading or refused.
  const bare = (content) => (mode === 'sheet'
    ? <div className="case__bare"><CloseButton onClose={onClose} />{content}</div>
    : content)
  if (problem) return bare(<LoadError problem={problem} onRetry={onRetry} />)
  if (!data) return bare(<p className="empty">{t('common.loading')}</p>)
  // The 2026-09-19 ruling serves crm.lead identities as customers; a lead with no
  // money row has no case, and this renders it as what it is — an identity with the
  // served reason, no money figures invented.
  if (data.identity_only) return <IdentityOnlyRecord data={data} mode={mode} onClose={onClose} />

  const kase = data.case || {}
  const customer = data.customer || {}
  const crm = customer.odoo_crm
  const work = data.work_item || {}
  const mp = work.money_position || {}
  const summary = data.payment_summary
  const totals = summary?.totals || {}
  const displayInstalments = summary?.display_instalments
  const instalmentTotals = totals.breakdown?.instalment
  const instalmentCount = displayInstalments?.total_count ?? instalmentTotals?.count ?? totals.cycle_count
  const instalmentCounts = instalmentTotals?.counts ?? totals.counts
  const instalmentPaid = displayInstalments?.paid_count ?? instalmentTotals?.display_paid_count ?? instalmentCounts?.PAID ?? 0
  const instalmentUnverifiedPaid = displayInstalments?.unverified_paid_count ?? instalmentTotals?.unverified_paid_count ?? 0
  const instalmentRemaining = displayInstalments?.remaining_count ?? instalmentTotals?.display_remaining_count ?? instalmentTotals?.remaining_count ?? totals.remaining_count
  const overdue = totals.overdue_amount ?? work.aggregate_overdue
  const hasCash = (data.contracts || []).some((contract) => contract.product === 'CASH')
  const balance = totals.due_outstanding_amount ?? (hasCash && displayInstalments ? displayInstalments.contract_outstanding : totals.outstanding_amount ?? work.aggregate_outstanding)
  const peakBalanceDiffers = hasCash && displayInstalments?.peak_balance_complete && displayInstalments?.peak_outstanding != null
    && displayInstalments.peak_outstanding !== displayInstalments.contract_outstanding
  const dpd = work.oldest_dpd
  const bandLabel = lang === 'en' ? work.aging_bucket_label_en : work.aging_bucket_label_th
  const assessmentHold = kase.npl_assessment?.assessment_hold
    ? (lang === 'en' ? kase.npl_assessment.label_en : kase.npl_assessment.label_th)
    : ''
  const ladder = work.ladder
  const steps = ladder?.steps || []
  const ladderIndex = steps.findIndex((s) => s.stage === ladder?.stage)
  const indicativeIndex = steps.findIndex((s) => s.stage === ladder?.indicative)
  const entity = (data.contracts && data.contracts[0] && data.contracts[0].entity) || work.entity
  const first = (data.contracts || [])[0]
  const pp = work.payment_position || {}
  const manager = atLeast('MANAGER')
  const canTerminate = ['OFFICER', 'SUPERVISOR', 'MANAGER', 'OWNER'].includes(identity.role)
  const hasLiveContract = (data.contracts || []).some((contract) =>
    !['CLOSED', 'WRITTEN_OFF', 'TERMINATED', 'CANCELLED'].includes(contract.status))
  const pay = paymentStatus(kase.payment_status)
  const system = kase.payment_status_confirmed || kase.payment_status_system
  const biz = businessDate || businessDateOf(data)
  // The sheet's own word for this customer, and where PEAK says otherwise (fix-all leg S).
  const sheetWord = (code) => (code === 'PAID' ? t('status.cell.paid') : t(paymentStatus(code).key))
  const sheetStatus = kase.sheet_status
  const disagreements = kase.status_disagreements || []
  // A landed sheet's contracts are worked out as of its capture day; after it, payments
  // are known only from PEAK — said beside the days overdue.
  const capturedNote = kase.sheet_captured_on && biz && kase.sheet_captured_on < biz
    ? t('data.sheetCapturedOn', { on: fmtDate(kase.sheet_captured_on) }) : ''
  const provenance = summary ? ((lang === 'en' ? displayInstalments?.provenance_en : displayInstalments?.provenance_th)
    || (lang === 'en' ? summary.provenance_en : summary.provenance_th) || t('record.cycleNote')) : ''
  const actName = (s) => (lang === 'en' ? s.act_en : s.act_th)

  const contacts = data.contact_log || []
  const events = data.events || []
  const ptps = data.ptps || []
  const openPtp = ptps.find((p) => p.status === 'OPEN')
  const paidBefore = openPtp?.paid_before_due
  const issues = data.issues || []
  const openIssues = issues.filter((i) => i.status !== 'RESOLVED')
  const reviews = data.reviews || []
  const power = data.power || []
  const invoices = data.invoices || []
  const receiptByInvoice = new Map((data.receipts || []).map((r) => [r.invoice_uid, r]))
  const allowance = data.contact_allowance || {}
  const none = issueStatus('NONE')

  // ② the ten facts (spec §2.3): row A is what the team tells the customer first (F03);
  // a sub only when it carries data, a caption that restates its label becomes a title.
  const scheduled = instalmentCount != null
  const facts = [
    {
      key: 'paid', label: t('record.paidOfTotal'), big: true,
      value: scheduled ? <><span>{`${instalmentPaid} / ${instalmentCount}`}</span>
        {instalmentUnverifiedPaid > 0 ? <small className="case__unverifiedPaid" title={t('record.unverifiedPaidNote')}>
          {t('record.unverifiedPaid', { n: instalmentUnverifiedPaid })}
        </small> : null}</> : '—',
      sub: instalmentRemaining != null ? t('record.remainingNote', { n: instalmentRemaining }) : t('record.noSchedule'),
    },
    {
      key: 'pmt', label: t('record.pmtMonth'), value: money(first?.pmt),
      sub: first?.term_months != null
        ? t('record.pmtNote', { n: first.term_months }) + (data.contract_count > 1 ? ` · ${t('record.contracts', { n: data.contract_count })}` : '')
        : '',
    },
    { key: 'overdueCycles', label: t('record.overdueCycles'), value: displayInstalments?.overdue_count ?? instalmentCounts?.OVERDUE ?? '—', title: t('record.overdueCyclesNote') },
    { key: 'arrears', label: t('record.arrears'), value: money(overdue), sub: work.installments_note || '', title: t('record.arrearsNote') },
    { key: 'age', label: t('record.age'), value: dpd === null || dpd === undefined ? t('today.dpdNone') : `DPD ${dpd}`,
      sub: [bandLabel, assessmentHold, capturedNote].filter(Boolean).join(' · ') },
    { key: 'balance', label: t('record.balance'), value: money(balance),
      sub: totals.due_outstanding_amount !== undefined ? [
        t('invoiceReview.future', { amount: money(totals.future_outstanding_amount) }),
        t('invoiceReview.contractBalance', { amount: money(work.contract_outstanding ?? totals.outstanding_amount) }),
      ].join(' · ') : peakBalanceDiffers ? t('record.peakBalanceDiff', { amount: money(displayInstalments.peak_outstanding) }) : '',
      title: t('record.balanceNote') },
    { key: 'asked', label: t('record.asked'), value: money(mp.amount_to_ask), sub: mp.amount_to_ask != null ? t('record.askedNote') : '' },
    {
      key: 'penalty', label: t('record.penalty'), value: money(mp.penalty_accrued_unbilled),
      sub: mp.penalty_accrued_unbilled == null ? '' : mp.penalty_invoicing_enabled ? t('record.penaltyIssued') : t('record.penaltyHeld'),
    },
    {
      key: 'openInv', label: t('record.openInvoices'),
      value: pp.open_count != null ? t('record.openInvoicesValue', { n: pp.open_count }) : '—',
      sub: pp.as_of ? t('record.openInvoicesNote', { on: fmtDate(pp.as_of) }) : t('pp.asOfUnknown'),
    },
    {
      key: 'kwp', label: t('record.kwp'), value: customer.system_size_kwp ? `${customer.system_size_kwp} kWp` : '—',
      sub: customer.system_size_kwp ? '' : t('record.kwpNone'), title: customer.system_size_kwp ? t('record.kwpNote') : undefined,
    },
  ]

  // The case's own events, beside the contact log. A kind the dictionaries do not
  // name renders as its code — never a blank row that hides an act.
  const conditionLabel = (key) => {
    const condition = (data.pipeline_item?.conditions || []).find((c) => c.key === key)
    return condition ? (lang === 'en' ? condition.label_en : condition.label_th) : key
  }
  const eventDetail = (e) => [
    e.condition ? conditionLabel(e.condition) : null,
    e.invoice_uid,
    e.contract_uid,
    e.cause ? causeLabel(e.cause) : null,
    e.instrument,
    e.origin,
    e.reason || e.reason_th || e.note,
    e.due_date ? fmtDate(e.due_date) : null,
    e.by ? (e.by === 'SYSTEM' ? t('record.bySystem') : officerName(e.by)) : null,
  ].filter(Boolean).join(' · ')

  // D05 (TASK-030): a receipt dated before the promise's date is the reason it is
  // closed as kept — the officer presses the button, the server keeps the receipt.
  async function closePaidPromise(at) {
    if (!openPtp || !paidBefore || closingPtp) return
    setClosingPtp(true)
    setPtpProblem(null)
    try {
      await api.closeCasePtp(openPtp.uid, {
        outcome: 'KEPT',
        on: paidBefore.on,
        reason: paidBefore.receipt_no,
        by: identity.officer || undefined,
      })
      toast(t('record.ptpClosed'))
      onChanged?.()
    } catch (e) {
      setPtpProblem({ at, problem: e?.problem || { code: 'request_failed' } })
    } finally {
      setClosingPtp(false)
    }
  }

  // F05 / Q1 (TASK-019): the hand move — either direction, a reason, logged. The
  // payload names whether this is a lease or a cash ladder, so the right route is called.
  async function submitStage(toStage, reason) {
    if (!ladder?.case_uid || stageBusy) return
    setStageBusy(true)
    setStageProblem(null)
    try {
      const call = ladder.kind === 'CASH' ? api.setCashCaseStage : api.setCaseStage
      await call(ladder.case_uid, {
        to_stage: toStage,
        reason,
        by: identity.officer || undefined,
        role: identity.role,
      })
      toast(t('record.stageMoved'))
      setStageOpen(false)
      onChanged?.()
    } catch (e) {
      setStageProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setStageBusy(false)
    }
  }

  // The cycle grid card on the overview (F14 / feedback-r2 TASK-006): every instalment
  // cycle from the served payment_summary, its provenance one click away.
  const cycleCard = (title) => (
    <Card title={title} extra={summary ? <InfoPopover>{provenance}</InfoPopover> : null}>
      <div className="card__body case__stack">
        <InstallationConfirmation data={data} onChanged={onChanged} />
        {summary ? <CycleGrid summary={summary} invoices={invoices} /> : null}
        <ServiceDeferrals data={data} onChanged={onChanged} />
      </div>
    </Card>
  )

  function moveTab(event, index) {
    let next = null
    if (event.key === 'ArrowRight') next = (index + 1) % TABS.length
    if (event.key === 'ArrowLeft') next = (index - 1 + TABS.length) % TABS.length
    if (event.key === 'Home') next = 0
    if (event.key === 'End') next = TABS.length - 1
    if (next === null) return
    event.preventDefault()
    const nextId = TABS[next][0]
    setTab(nextId)
    requestAnimationFrame(() => document.getElementById(`case-tab-${nextId}`)?.focus())
  }

  return (
    <div className={`case case--${mode}`}>
      <header className="case__head" aria-label={t('record.debtor')}>
        <div className="case__top">
          <div className="case__chips">
            {kase.payment_status ? (
              <StatusPill kind={pay.kind}
                          title={system && system !== kase.payment_status ? t('record.payStatusSystemTip', { label: t(paymentStatus(system).key) }) : undefined}>
                {t(pay.key)}
              </StatusPill>
            ) : null}
            {kase.dc_status ? (
              <NeutralChip title={t('record.dcTip')}>{kase.dc_status_label || labelFor(dcStatuses, kase.dc_status, lang)}</NeutralChip>
            ) : null}
            {bandLabel ? <NeutralChip title={t('record.agingTip')}>{bandLabel}</NeutralChip> : null}
            {assessmentHold ? <NeutralChip>{assessmentHold}</NeutralChip> : null}
            {power.length ? (
              <NeutralChip>{t('record.powerChip', { state: (lang === 'en' ? kase.power_state_label_en : kase.power_state_label_th) || kase.power_state || '—' })}</NeutralChip>
            ) : null}
            {mp.penalty_invoicing_enabled === false && mp.penalty_accrued_unbilled ? (
              <NeutralChip title={t('record.indicativeTip')}>{t('record.indicative')}</NeutralChip>
            ) : null}
          </div>
          <div className="case__score">
            <span className="case__scoreLabel">{t('record.riskScore')}</span>
            <span className="case__scoreValue num">{work.risk_score ?? kase.risk_score ?? '—'}</span>
          </div>
          {mode === 'sheet' ? <CloseButton onClose={onClose} /> : null}
        </div>
        <div className="case__identity">
        <div className="case__nameRow">
          <h1 className="case__name">{crm?.url ? (
            <a className="case__odooLink" href={crm.url} target="_blank" rel="noopener noreferrer">{customer.display_name}</a>
          ) : customer.display_name}</h1>
          {/* Q7 / TASK-215: the name is a PEAK decision's — the chip says so, its title is
              the served provenance. */}
          {customer.field_sources?.customer_name === 'PEAK' ? (
            <NeutralChip title={(lang === 'en' ? customer.field_notes_en?.customer_name : customer.field_notes_th?.customer_name) || undefined}>PEAK</NeutralChip>
          ) : null}
          <span className="case__spacer" />
          <EntityChip entity={entity} />
          <SourceChip source={customer.data_source} />
        </div>
        <div className="case__idRow">
          <CustomerIdentity customer={customer} />
          <span className="case__idPart"><span aria-hidden="true">·</span>{t('record.officerLine', { name: officerName(customer.officer) })}</span>
          <span className="case__idPart"><span aria-hidden="true">·</span><PhoneLine key={customer.uid} customer={customer} /></span>
        </div>
        {kase.payment_status === 'PENDING' ? (
          <p className="case__idRow" role="status">
            {t('record.pendingNotice', {
              status: system ? t(paymentStatus(system).key) : '—',
              since: kase.payment_pending_since ? when(kase.payment_pending_since) : '—',
            })}
          </p>
        ) : null}
        {sheetStatus || disagreements.length ? (
          <div className="case__idRow case__sheetRow">
            {sheetStatus ? (
              <span>
                {t('data.sheetStatusLine', { word: sheetStatus.word, month: sheetStatus.month || '—' })}
                {sheetStatus.unknown ? ` · ${t('data.sheetStatusUnknown')}` : ''}
              </span>
            ) : null}
            {disagreements.map((d) => (
              <span key={d.month || 'now'} className="case__idPart">
                <span aria-hidden="true">·</span>
                {t('data.sheetDisagreeRow', {
                  month: d.month || (d.peak_off ? t('data.sheetPeakOff') : t('data.sheetDisagreeNow')),
                  peak: sheetWord(d.peak), sheet: sheetWord(d.sheet),
                })}
              </span>
            ))}
          </div>
        ) : null}
        </div>
        <div className="case__actions">
          <button type="button" className="btn btn--primary" onClick={onLogContact}>{t('record.logContact')}</button>
          <button type="button" className="btn" disabled={!customer.line_id}
                  title={customer.line_id ? 'LINE' : t('record.noLine')}
                  onClick={() => setSocial('LINE')}>
            <Icon name="chat" />LINE
          </button>
          <button type="button" className="btn" disabled={!customer.meta_id}
                  title={customer.meta_id ? 'Facebook' : t('record.noFacebook')}
                  onClick={() => setSocial('FACEBOOK')}>
            <Icon name="chat" />Facebook
          </button>
          {data.contract_count > 0 ? (
            <button type="button" className="btn" onClick={() => setContractOpen(true)}>
              <Icon name="doc" />{t('record.contractDetails')}
            </button>
          ) : null}
          <span className="case__spacer" />
          {hasLiveContract ? (
            <button type="button" className="btn btn--danger" disabled={!canTerminate}
                    title={canTerminate ? undefined : t('record.terminateRoleOnly')}
                    onClick={() => setTerminateOpen(true)}>
              {t('record.terminate')}
            </button>
          ) : null}
        </div>
      </header>

      <div className="tabs case__tabs" role="tablist" aria-label={t('record.tabs')}>
        {TABS.map(([id, key], index) => {
          const count = id === 'history' ? contacts.length : id === 'issues' ? openIssues.length : 0
          return (
            <button key={id} id={`case-tab-${id}`} type="button" role="tab" aria-selected={tab === id}
                    aria-controls="case-panel" tabIndex={tab === id ? 0 : -1}
                    onKeyDown={(event) => moveTab(event, index)}
                    className={`tabs__tab${tab === id ? ' tabs__tab--on' : ''}`} onClick={() => setTab(id)}>
              {t(key)}
              {count ? <span className="tabs__count">{count}</span> : null}
            </button>
          )
        })}
      </div>

      <div className="case__body">
        <TodoCallout data={data} item={item} biz={biz} busy={closingPtp}
                     problem={ptpProblem?.at === 'todo' ? ptpProblem.problem : null}
                     onClosePaid={() => closePaidPromise('todo')} />

        {mp.review_required ? <p className="case__rowNote">{t('schedule.confirmedOnly')}</p> : null}
        <section className="case__facts" aria-label={t('record.fields')}>
          {facts.map((f) => (
            <div key={f.key} className={`case__fact${f.big ? ' case__fact--key' : ''}`} title={f.title}>
              <span className="case__factLabel">{f.label}</span>
              <span className="case__factValue num">{f.value}</span>
              {f.sub ? <span className="case__factSub">{f.sub}</span> : null}
            </div>
          ))}
        </section>

        {steps.length ? (
          <Card
            title={t('record.ladder')}
            className="case__ladder"
            extra={(
              <>
                {ladder.indicative ? (
                  <NeutralChip title={indicativeIndex >= 0 ? t('record.indicativeRung', { n: indicativeIndex + 1, label: actName(steps[indicativeIndex]) }) : undefined}>
                    {t('record.indicative')}
                  </NeutralChip>
                ) : null}
                <InfoPopover>
                  {t('record.ladderNote')}
                  {ladder.pending_decision ? ` · ${t('record.ladderPending', { code: ladder.pending_decision })}` : ''}
                </InfoPopover>
                <span className="case__spacer" />
                {/* F05 / Q1 (TASK-019): below MANAGER the control is visible and disabled
                    with its reason, never absent (GUD-002). No journey case, no button. */}
                {ladder.case_uid ? (
                  <button type="button" className="btn btn--sm" disabled={!manager}
                          title={manager ? undefined : t('record.adjustStageManagerOnly')}
                          onClick={() => { setStageProblem(null); setStageOpen(true) }}>
                    {t('record.adjustStage')}
                  </button>
                ) : null}
              </>
            )}
          >
            <ol className="case__rungs">
              {steps.map((s, i) => {
                const rung = ladderRung(i, ladderIndex)
                return (
                  <li key={s.stage} className={`case__rung case__rung--${rung.kind}`} title={t(rung.key)}
                      aria-current={rung.kind === 'current' ? 'step' : undefined}>
                    <span className="case__rungMark" aria-hidden="true">
                      {rung.kind === 'passed' ? <Icon name="check" size={12} /> : null}
                    </span>
                    <span className="case__rungLabel">{actName(s)}</span>
                  </li>
                )
              })}
            </ol>
          </Card>
        ) : null}

        <div role="tabpanel" id="case-panel" aria-labelledby={`case-tab-${tab}`} className="case__tabpanel">
        {tab === 'overview' && (
          <div className="case__overview">
            <div className="case__main">
              {/* F14 / feedback-r2 TASK-006: the served cycles lead the overview. */}
              {summary ? cycleCard(t('record.cycleGrid')) : null}
              <Card title={t('record.recent')}>
                {contacts.length === 0 ? <p className="case__empty case__pad">{t('record.noContact')}</p> : (
                  <ul className="case__rows">{contacts.slice(0, 3).map((c) => <ContactRow key={c.uid} c={c} />)}</ul>
                )}
              </Card>
            </div>
            <div className="case__side">
              {/* F11 / feedback-r2 TASK-008: the PTP card keeps the promises and the
                  open-ticket status. */}
              <Card title={t('record.ptpAndIssues')}>
                <div className="card__body case__stack">
                  {ptps.length === 0 ? <p className="case__empty">{t('record.noPtp')}</p> : ptps.slice().reverse().map((p) => {
                    const s = ptpStatus(p.status)
                    return (
                      <div key={p.uid} className="case__ptp">
                        <div className="case__ptpTop">
                          <StatusPill kind={s.kind}>{t(s.key)}</StatusPill>
                          <span className="case__spacer" />
                          <span className="case__amount num">{money(p.promised_amount)}</span>
                        </div>
                        <span className="case__rowNote num">{t('record.ptpDate', { date: fmtDate(p.promise_date) })}</span>
                      </div>
                    )
                  })}
                  {/* D05 / TASK-030: the customer paid before the promise date — the
                      receipt is the reason, the officer closes it as KEPT. */}
                  {paidBefore ? (
                    <div className="case__early">
                      <p className="case__line">
                        <StatusIcon kind="moneyin" />
                        <span className="num">
                          <span>{t('record.paidBeforeDue', { ref: paidBefore.receipt_no || '—' })}</span>
                          {' · '}{t('record.moneyOn', { amount: money(paidBefore.amount), date: fmtDate(paidBefore.on) })}
                        </span>
                      </p>
                      <button type="button" className="btn btn--sm" disabled={closingPtp} onClick={() => closePaidPromise('card')}>
                        {t('record.closePtpPaid')}
                      </button>
                      {ptpProblem?.at === 'card' ? <Problem problem={ptpProblem.problem} /> : null}
                    </div>
                  ) : null}
                  <hr className="case__rule" />
                  {openIssues.length === 0 ? (
                    <div><StatusPill kind={none.kind}>{t(none.key)}</StatusPill></div>
                  ) : (
                    <ul className="case__stack">{openIssues.map((i) => <IssueRow key={i.uid} issue={i} stacked />)}</ul>
                  )}
                  <div>
                    <button type="button" className="btn btn--quiet btn--sm case__more" onClick={() => setTab('issues')}>
                      {t('record.viewIssues')}<Icon name="arrow-right" size={14} />
                    </button>
                  </div>
                </div>
              </Card>
              {/* F09 / ruling Q4 (feedback-r2 TASK-009): the officer's own scoreboard. */}
              <OfficerScoreboard officerUid={customer.officer} />
              {reviews.length ? (
                <Card title={t('record.reviews')}>
                  <ul className="card__body case__stack">
                    {reviews.map((r) => {
                      const s = reviewStatus(r.status)
                      return (
                        <li key={r.uid} className="case__review">
                          <StatusPill kind={s.kind}>{t(s.key)}</StatusPill>
                          <span>{lang === 'en' ? r.question_en : r.question_th || r.question}</span>
                        </li>
                      )
                    })}
                  </ul>
                </Card>
              ) : null}
            </div>
          </div>
        )}

        {tab === 'invoices' && (
          <>
            {data.pre_install && data.pipeline_item ? (
              <PreInstallCard item={data.pipeline_item} meta={data.pipeline_meta} onChanged={onChanged}
                              heading="preinstall.heading" evidenceOpen={false} />
            ) : null}
            <Card title={t('record.tabInvoices')} extra={<InvoiceReviews data={data} onChanged={onChanged} />}>
              {invoices.length === 0 ? <p className="case__empty case__pad">{t('record.noInvoices')}</p> : (
                <DataTable
                  caption={t('record.tabInvoices')}
                  minWidth={720}
                  getKey={(r) => r.uid}
                  rows={invoices}
                  columns={[
                    { key: 'kind', label: t('record.invKind'), render: (r) => word(`inv.kind.${r.kind}`, r.kind) },
                    { key: 'amount', label: t('record.invAmount'), num: true, render: (r) => money(r.amount) },
                    {
                      // An amendment AR has not approved stays a request: the due date is the
                      // served one, the request rides its note (fixes the early-move gap).
                      key: 'due', label: t('record.invDue'),
                      render: (r) => <span className="num" title={(lang === 'en' ? r.amended_due_note_en : r.amended_due_note_th) || undefined}>
                        {fmtDate(r.due_date)}{r.schedule_due_date && r.schedule_due_date !== r.due_date ? <small className="case__rowNote">{t('schedule.scheduleDate', { date: fmtDate(r.schedule_due_date) })}</small> : null}{r.service_deferral ? <small className="case__rowNote">
                          {t('deferral.collectionDue')}: {fmtDate(r.collection_due_date)}</small> : null}</span>,
                    },
                    { key: 'confirmedPaid', label: t('record.invConfirmedPaid'), num: true, render: (r) => r.payment_evidence === 'UNCONFIRMED' ? '—' : money(r.confirmed_paid || 0) },
                    { key: 'pending', label: t('record.invPending'), num: true, render: (r) => money(r.pending_amount || 0) },
                    { key: 'outstanding', label: t('record.invOutstanding'), num: true, render: (r) => (r.payment_evidence === 'UNCONFIRMED' || r.liability_verified === false) ? '—' : money(r.confirmed_outstanding ?? r.outstanding) },
                    { key: 'change', label: t('record.invChange'), num: true,
                      render: (r) => (r.payment_evidence === 'UNCONFIRMED' || r.liability_verified === false) ? '—' : `${money(r.confirmed_outstanding ?? r.outstanding)} → ${money(r.projected_outstanding ?? r.outstanding)}` },
                    { key: 'state', label: t('record.invState'), render: (r) => { const s = invoiceStatus(r.collection_state || r.state); return <span><StatusPill kind={(r.payment_evidence === 'UNCONFIRMED' || r.liability_verified === false) ? 'notdue' : s.kind}>{r.payment_evidence === 'UNCONFIRMED' ? t('schedule.evidence.UNCONFIRMED') : r.liability_verified === false ? t('schedule.receiptOnly') : t(s.key)}</StatusPill>{r.unmatched_reason ? <small className="case__rowNote">{t(`schedule.reason.${r.unmatched_reason}`)}</small> : null}</span> } },
                    { key: 'deferral', label: t('deferral.create'), render: (r) => <InvoiceDeferral invoice={r} data={data} onChanged={onChanged} /> },
                    { key: 'peak', label: t('record.invPeak'), render: (r) => r.peak_number || '—' },
                    { key: 'cycle', label: t('record.invCycle'), render: (r) => ('contract_cycle' in r ? (r.contract_cycle ? `M${r.contract_cycle}` : '—') : (r.month_index ? `M${r.month_index}` : '—')) },
                    {
                      key: 'receipt', label: t('record.invReceipt'),
                      render: (r) => {
                        const refs = r.receipt_references || []
                        if (refs.length) return refs.join(', ')
                        const rcp = receiptByInvoice.get(r.uid)
                        if (!rcp) return '—'
                        return `${rcp.ref || '—'} · ${rcp.received_on ? fmtDate(String(rcp.received_on).slice(0, 10)) : '—'}`
                      },
                    },
                    { key: 'review', label: t('invoiceReview.title'), render: (r) => <InvoiceReviews invoice={r} data={data} onChanged={onChanged} /> },
                  ]}
                />
              )}
            </Card>
            <ManualInvoiceMatch customerUid={customer.uid} kase={kase} invoices={invoices}
                                claims={data.payment_claims || []} position={data.payment_claim_position}
                                onChanged={onChanged} />
          </>
        )}

        {tab === 'monthly' && (
          <Card title={t('record.tabMonthly')} extra={<InfoPopover>{t('record.monthlyNote')}</InfoPopover>}>
            {(kase.monthly_history || []).length === 0 ? <p className="case__empty case__pad">{t('record.monthlyNone')}</p> : (
              <DataTable
                caption={t('record.tabMonthly')}
                minWidth={720}
                getKey={(r) => r.month}
                rows={kase.monthly_history}
                columns={[
                  { key: 'month', label: t('record.monthlyMonth'), render: (r) => monthLabel(r.month, lang) },
                  { key: 'status', label: t('record.monthlyStatus'), render: (r) => { const s = paymentStatus(r.payment_status); return <StatusPill kind={s.kind}>{t(s.key)}</StatusPill> } },
                  { key: 'source', label: t('record.monthlySource'), render: (r) => <NeutralChip>{t(`record.src.${r.status_source}`)}</NeutralChip> },
                  { key: 'overdue', label: t('record.monthlyOverdue'), num: true, render: (r) => money(r.overdue) },
                  { key: 'outstanding', label: t('record.monthlyOutstanding'), num: true, render: (r) => money(r.outstanding) },
                  { key: 'dpd', label: 'DPD', num: true, render: (r) => (r.oldest_dpd ?? '—') },
                  { key: 'officer', label: t('record.monthlyOfficer'), render: (r) => r.officer || '—' },
                ]}
              />
            )}
          </Card>
        )}

        {tab === 'history' && (
          <>
            <Card title={t('record.tabHistory')}>
              {contacts.length === 0 ? <p className="case__empty case__pad">{t('record.noContact')}</p> : (
                <ul className="case__rows">{contacts.map((c) => <ContactRow key={c.uid} c={c} full />)}</ul>
              )}
              <p className="card__note num">{t('record.allowance', { used: allowance.used ?? 0, cap: allowance.cap ?? '—' })}</p>
            </Card>
            <Card title={t('record.events')}>
              {events.length === 0 ? <p className="case__empty case__pad">{t('record.noEvents')}</p> : (
                <ul className="case__rows">
                  {events.slice().reverse().map((e, i) => (
                    <li key={`${e.kind}-${e.on || ''}-${i}`} className="case__row case__row--event">
                      <span className="case__when num">{fmtDate(String(e.on || '').slice(0, 10))}</span>
                      <span className="case__rowTitle">{t(eventKey(e.kind))}</span>
                      <span className="case__rowNote" style={{ whiteSpace: 'pre-wrap' }}>{eventDetail(e)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </>
        )}

        {tab === 'issues' && (
          <Card title={t('record.tabIssues')} tip={t('record.issuesNote')}>
            {issues.length === 0 ? <div className="card__body"><StatusPill kind={none.kind}>{t(none.key)}</StatusPill></div> : (
              <ul className="case__rows">{issues.map((i) => <IssueRow key={i.uid} issue={i} />)}</ul>
            )}
          </Card>
        )}
        </div>
      </div>

      {canTerminate ? (
        <TerminateDrawer
          open={terminateOpen}
          onClose={() => setTerminateOpen(false)}
          customerUid={customer.uid}
          outstanding={balance}
          onDone={onChanged}
        />
      ) : null}

      <MoveDrawer
        open={stageOpen}
        onClose={() => setStageOpen(false)}
        title={t('record.stageMoveTitle')}
        subtitle={customer.display_name}
        currentId={ladder?.stage}
        options={steps.map((s) => ({ id: s.stage, label: actName(s) }))}
        noteKey="record.stageMoveNote"
        busy={stageBusy}
        problem={stageProblem}
        onConfirm={submitStage}
      />
      <ContractDetailsDrawer open={contractOpen} onClose={() => setContractOpen(false)} data={data} />
      <SocialComposer open={Boolean(social)} onClose={() => setSocial(null)} channel={social}
                      recipientId={social === 'FACEBOOK' ? customer.meta_id : customer.line_id} />

      {onChanged ? <span className="sr-only" data-testid="record-ready">{kase.uid || ''}</span> : null}
    </div>
  )
}

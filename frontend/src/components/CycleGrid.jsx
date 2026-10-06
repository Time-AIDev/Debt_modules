import { useId, useState } from 'react'
import { usePrefs } from '../lib/prefs.jsx'
import { money, date as fmtDate } from '../lib/format.js'
import { cellStatus } from '../lib/status.js'

/** A colour legend for instalment cells: one swatch + word per kind (lib/status.js cellStatus). */
export function Legend({ kinds }) {
  const { t } = usePrefs()
  return (
    <div className="legend">
      {kinds.map((k) => <span key={k}><i className={`monthgrid__cell--${k}`} />{t(`status.cell.${k}`)}</span>)}
    </div>
  )
}

function CycleCell({ title, label, className, children }) {
  const id = useId()
  const [open, setOpen] = useState(false)
  return <span className="cyclegrid__tooltipAnchor">
    <button type="button" className={className} title={title} aria-label={`${label} · ${title}`}
      aria-describedby={open ? id : undefined} onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
      onClick={() => setOpen(true)} onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); setOpen(false) } }}>
      {label}{children}
    </button>
    {open ? <span role="tooltip" id={id} className="cyclegrid__tooltip">{title}</span> : null}
  </span>
}

/**
 * F14 (feedback-r2 TASK-006): every instalment cycle of every contract from
 * `payment_summary` alone. The counts line and every cell come from the served payload
 * — the grid computes nothing. A partly paid cycle carries its own class (the
 * half-fill), a missing amount reads as "not due yet". The served provenance sentence
 * sits in the card head's "i" (the card is the caller's).
 */
export function CycleGrid({ summary, invoices = [] }) {
  const { t } = usePrefs()
  if (!summary) return null
  const totals = summary.totals || {}
  const display = summary.display_instalments
  const instalmentTotals = totals.breakdown?.instalment || {
    count: totals.cycle_count,
    counts: totals.counts,
  }
  const counts = display ? { PAID: display.paid_count, OVERDUE: display.overdue_count,
    UPCOMING: display.upcoming_count } : instalmentTotals.counts || {}
  // The per-contract entries are read by shape (an array whose items carry `cycles`),
  // the key `payment_summary.build()` serves them under is `contracts`.
  const originalEntries = Object.values(summary).find(
    (value) => Array.isArray(value) && value.some((e) => Array.isArray(e?.cycles)),
  ) || []
  const entries = display?.contracts || originalEntries
  // Raw codes → words (kind, status, source); an unknown code shows as itself.
  const word = (key, code) => { const w = t(key); return w === key ? code : w }
  const pendingFor = (contractUid, cycle) => invoices.find((invoice) => (
    Number('contract_cycle' in invoice ? invoice.contract_cycle : invoice.month_index) === Number(cycle)
    && (!invoice.contract_uid || !contractUid || invoice.contract_uid === contractUid)
    && Number(invoice.pending_amount || 0) > 0
  ))
  return (
    <div className="cyclegrid">
      <p className="cyclegrid__counts num">
        {t('record.cycleCounts', {
          paid: counts.PAID ?? 0, overdue: counts.OVERDUE ?? 0,
          upcoming: counts.UPCOMING ?? 0, total: display?.total_count ?? instalmentTotals.count ?? 0,
        })}
      </p>
      {totals.due_invoice_count !== undefined ? <p className="case__rowNote">{t('invoiceReview.dueCounts', {
        invoices: totals.due_invoice_count, cycles: totals.due_cycle_count,
      })}</p> : null}
      {display?.unconfirmed_count > 0 ? <p className="case__rowNote">
        {t('record.cyclesAwaitingEvidence', { n: display.unconfirmed_count })}
      </p> : null}
      {totals.review_count > 0 ? <p className="case__rowNote">{t('schedule.reviewTotals', {
        n: totals.review_count, amount: money(totals.review_amount),
      })}</p> : null}
      {totals.counts?.INFERRED_PAID > 0 || totals.counts?.SHEET_REPORTED_PAID > 0 ? <p className="case__rowNote">
        {t('schedule.evidenceCounts', { inferred: totals.counts.INFERRED_PAID || 0,
          reported: totals.counts.SHEET_REPORTED_PAID || 0 })}
      </p> : null}
      {totals.deferred_count > 0 ? <p className="case__rowNote">{t('deferral.count', { n: totals.deferred_count })}</p> : null}
      {entries.map((entry) => {
        const original = display ? originalEntries.find((row) => row.contract_uid === entry.contract_uid) : entry
        const deposits = (original?.cycles || []).filter((cycle) => cycle.kind === 'DEPOSIT')
        const instalments = (entry.cycles || []).filter((cycle) => cycle.kind !== 'DEPOSIT')
        const renderCycle = (c, label) => {
          const s = cellStatus(c.status, c.partly_paid)
          const pending = pendingFor(entry.contract_uid, c.n)
          const title = [
            word(`record.cycleKind.${c.kind}`, c.kind), fmtDate(c.due_date), money(c.amount),
            t(c.status === 'UPCOMING' && c.due_date === summary.business_date ? 'invoiceReview.dueToday' : s.key),
            word(`record.cycleSource.${c.source}`, c.source),
            c.doc_no || null,
            pending ? t('record.cyclePendingAmount', { amount: money(pending.pending_amount) }) : null,
            c.payment_evidence ? t(`schedule.evidence.${c.payment_evidence}`) : null,
            c.schedule_due_date && c.schedule_due_date !== c.due_date ? t('schedule.scheduleDate', { date: fmtDate(c.schedule_due_date) }) : null,
            c.peak_due_dates?.length > 1 ? t('schedule.peakDates', { dates: c.peak_due_dates.map(fmtDate).join(', ') }) : null,
            c.deferral ? t('deferral.title') : null,
            c.deferral ? t('deferral.originalDue', { date: fmtDate(c.deferral.old_due_date) }) : null,
            c.deferral ? t('deferral.newDue', { date: fmtDate(c.deferral.new_due_date) }) : null,
          ].filter(Boolean).join(' · ')
          return (
            <CycleCell key={c.n} label={label} className={`monthgrid__cell monthgrid__cell--${s.kind}${pending ? ' monthgrid__cell--pending' : ''}`} title={title}>
              {pending ? <small>{t('record.cyclePending')}</small> : null}
              {c.deferral ? <small>{t('deferral.short')}</small> : null}
            </CycleCell>
          )
        }
        return (
          <div key={entry.contract_uid || 'contract'} className="cyclegrid__entry">
            {entries.length > 1 && entry.contract_uid ? <p className="cyclegrid__caption">{entry.contract_uid}</p> : null}
            {deposits.length ? (
              <div className="cyclegrid__deposits">
                {deposits.map((cycle) => renderCycle(cycle, 'DP'))}
              </div>
            ) : null}
            <div className="monthgrid">
              {instalments.map((cycle) => renderCycle(cycle, `M${cycle.instalment_n ?? cycle.n}`))}
            </div>
          </div>
        )
      })}
      <Legend kinds={['paid', 'part', 'late', 'notdue', ...(totals.review_count > 0 || display?.unconfirmed_count > 0 ? ['inferred', 'reported', 'unconfirmed'] : [])]} />
    </div>
  )
}

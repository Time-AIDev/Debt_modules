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
  const instalmentTotals = totals.breakdown?.instalment || {
    count: totals.cycle_count,
    counts: totals.counts,
  }
  const counts = instalmentTotals.counts || {}
  // The per-contract entries are read by shape (an array whose items carry `cycles`),
  // the key `payment_summary.build()` serves them under is `contracts`.
  const entries = Object.values(summary).find(
    (value) => Array.isArray(value) && value.some((e) => Array.isArray(e?.cycles)),
  ) || []
  // Raw codes → words (kind, status, source); an unknown code shows as itself.
  const word = (key, code) => { const w = t(key); return w === key ? code : w }
  const pendingFor = (contractUid, cycle) => invoices.find((invoice) => (
    Number(invoice.month_index) === Number(cycle)
    && (!invoice.contract_uid || !contractUid || invoice.contract_uid === contractUid)
    && Number(invoice.pending_amount || 0) > 0
  ))
  return (
    <div className="cyclegrid">
      <p className="cyclegrid__counts num">
        {t('record.cycleCounts', {
          paid: counts.PAID ?? 0, overdue: counts.OVERDUE ?? 0,
          upcoming: counts.UPCOMING ?? 0, total: instalmentTotals.count ?? 0,
        })}
      </p>
      {totals.deferred_count > 0 ? <p className="case__rowNote">{t('deferral.count', { n: totals.deferred_count })}</p> : null}
      {entries.map((entry) => {
        const deposits = (entry.cycles || []).filter((cycle) => cycle.kind === 'DEPOSIT')
        const instalments = (entry.cycles || []).filter((cycle) => cycle.kind !== 'DEPOSIT')
        const renderCycle = (c, label) => {
          const s = cellStatus(c.status, c.partly_paid)
          const pending = pendingFor(entry.contract_uid, c.n)
          const title = [
            word(`record.cycleKind.${c.kind}`, c.kind), fmtDate(c.due_date), money(c.amount), t(s.key),
            word(`record.cycleSource.${c.source}`, c.source),
            pending ? t('record.cyclePendingAmount', { amount: money(pending.pending_amount) }) : null,
            c.deferral ? t('deferral.title') : null,
          ].filter(Boolean).join(' · ')
          return (
            <span key={c.n} className={`monthgrid__cell monthgrid__cell--${s.kind}${pending ? ' monthgrid__cell--pending' : ''}`} title={title}>
              {label}{pending ? <small>{t('record.cyclePending')}</small> : null}
              {c.deferral ? <small>{t('deferral.short')}</small> : null}
            </span>
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
      <Legend kinds={['paid', 'part', 'late', 'notdue']} />
    </div>
  )
}

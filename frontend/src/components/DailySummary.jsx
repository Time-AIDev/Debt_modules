import { usePrefs } from '../lib/prefs.jsx'
import { money } from '../lib/format.js'

/**
 * F17 / R-A (feedback-r2 TASK-030), final design spec-main §3.1: the day's served
 * numbers — "ติดตามแล้ว {worked} จาก {total}" with its progress bar, then four figures:
 * to follow, not yet followed, promises made today with their amount, and the
 * unreachable. Every value arrives on `meta.daily_summary`; the strip computes nothing
 * but the bar's width.
 */
export function DailySummary({ summary }) {
  const { t } = usePrefs()
  if (!summary) return null
  const total = Number(summary.total) || 0
  const worked = Number(summary.worked) || 0
  const cells = [
    [t('today.sumToFollow'), summary.total ?? 0],
    [t('today.sumNotYet'), summary.not_yet ?? 0],
    [t('today.sumPtp'), `${summary.ptp_count ?? 0}${summary.ptp_amount != null ? ` · ${money(summary.ptp_amount)}` : ''}`],
    [t('today.sumUnreachable'), summary.unreachable ?? 0],
  ]
  return (
    <section className="daysum" aria-label={t('today.summaryTitle')}>
      <p className="daysum__head">
        <span className="eyebrow">{t('today.summaryTitle')}</span>
        <span className="num">{t('today.sumWorked', { worked, total })}</span>
      </p>
      <span className="daysum__bar" aria-hidden="true">
        <span style={{ width: `${total ? Math.round((worked / total) * 100) : 0}%` }} />
      </span>
      <dl className="daysum__grid">
        {cells.map(([label, value]) => (
          <div key={label} className="daysum__cell">
            <dt>{label}</dt>
            <dd className="num">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

import { usePrefs } from '../lib/prefs.jsx'
import { money, date } from '../lib/format.js'
import { StatusIcon } from './StatusIcon.jsx'

/**
 * The payment position (payment_position.py): did they pay, how much is left, when
 * money last came in, and who says so. It sits beside the status chip, never in its
 * place, and computes nothing — every figure is served.
 *
 * `compact` is the one-line row form (list rows, board chips); the full form is the
 * case page. An unknown as-of is drawn as unknown, never as fresh; stale data says so
 * with the problem icon and its word (brief §3.2), never with colour alone.
 */
export function PaymentPosition({ pp, compact = false }) {
  const { t, lang } = usePrefs()
  if (!pp || typeof pp !== 'object' || pp.paid_count === undefined) return null

  if (compact) {
    // The stale mark rides beside the line (its own chip in a row), so it wraps whole.
    const note = lang === 'en' ? pp.note_en || pp.note_th : pp.note_th
    return (
      <>
        <span className="pp pp--compact" data-testid="payment-position" title={note}>
          <span data-testid="pp-counts">{t('pp.short', { paid: pp.paid_count, open: pp.open_count })}</span>
          <span className="pp__source" data-testid="pp-source" data-source={pp.source}>
            {' · '}{t(`pp.source.${pp.source}`)}
          </span>
          {pp.as_of ? null : <span data-testid="pp-asof-unknown">{' · '}{t('pp.asOfUnknown')}</span>}
        </span>
        {pp.stale === true ? (
          <span className="pp__stale" data-testid="pp-stale" title={note}><StatusIcon kind="problem" size={12} />{t('pp.stale')}</span>
        ) : null}
      </>
    )
  }

  const oldest = pp.oldest_unpaid
  const lastIn = pp.last_money_in
  return (
    <span className="pp" data-testid="payment-position">
      <span className="pp__line" data-testid="pp-counts">
        {t('pp.counts', { paid: pp.paid_count, open: pp.open_count, total: pp.total_count })}
      </span>
      {pp.collection_overdue !== undefined ? <>
        <span className="pp__line">{t('deferral.peakOutstanding')}: {money(pp.peak_outstanding)}</span>
        <span className="pp__line">{t('deferral.overdueAfter')}: {money(pp.collection_overdue)}</span>
        <span className="pp__line">{t('deferral.deferredAmount')}: {money(pp.deferred_amount)}</span>
        <span className="pp__note">{lang === 'en' ? pp.adjustment_note_en : pp.adjustment_note_th}</span>
      </> : null}
      {oldest ? (
        <span className="pp__line" data-testid="pp-oldest">
          {t('pp.oldest', {
            ref: oldest.peak_number || oldest.uid,
            amount: money(oldest.outstanding),
            due: oldest.due_date ? date(oldest.due_date) : '—',
          })}
        </span>
      ) : null}
      {lastIn ? (
        <span className="pp__line" data-testid="pp-lastin">
          {t('pp.lastIn', { amount: money(lastIn.amount), on: date(lastIn.on), ref: lastIn.ref || '—' })}
        </span>
      ) : null}
      <span className="pp__prov">
        <span className="pp__source" data-testid="pp-source" data-source={pp.source}>
          {t(`pp.source.${pp.source}`)}
        </span>
        {pp.as_of
          ? <span className="pp__asof">{t('pp.asOf', { on: date(pp.as_of), days: pp.as_of_days })}</span>
          : <span className="pp__asof pp__asof--unknown" data-testid="pp-asof-unknown">{t('pp.asOfUnknown')}</span>}
        {pp.stale === true ? <span className="pp__stale" data-testid="pp-stale"><StatusIcon kind="problem" size={12} />{t('pp.stale')}</span> : null}
      </span>
      {(lang === 'en' ? pp.note_en || pp.note_th : pp.note_th)
        ? <span className="pp__note">{lang === 'en' ? pp.note_en || pp.note_th : pp.note_th}</span>
        : null}
    </span>
  )
}

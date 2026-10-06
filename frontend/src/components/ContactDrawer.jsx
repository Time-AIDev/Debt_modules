import { useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useIdentity } from '../lib/identity.jsx'
import { useDictionary, active, labelFor } from '../lib/dictionaries.js'
import { addDays, money, date as fmtDate } from '../lib/format.js'
import { ptpStatus } from '../lib/status.js'
import { Drawer } from './Drawer.jsx'
import { Problem } from './Problem.jsx'
import { useToast } from './Toast.jsx'

const CHANNELS = [
  { id: 'PHONE', key: 'drawer.channel.phone' },
  { id: 'LINE', key: 'drawer.channel.line' },
]

// PTP is channel-split: REACHED_PTP is the phone promise, PROMISED is the LINE
// promise (dictionaries.py CONTACT_RESULT). Other phone-only results
// (answered / no-answer / inconvenient / callback) hide on LINE; LINE-only
// results (read / sent-unread) hide on PHONE. Unknown future codes show for
// both channels. Backend still accepts any combo + historic VISIT rows.
const HIDE_BY_CHANNEL = {
  PHONE: new Set(['PROMISED', 'LINE_READ', 'LINE_SENT_UNREAD']),
  LINE: new Set(['REACHED_ANSWERED', 'REACHED_PTP', 'UNREACHABLE_NO_ANSWER', 'INCONVENIENT', 'CALLBACK_REQUESTED']),
}

const PTP_COUNTERPART = { REACHED_PTP: 'PROMISED', PROMISED: 'REACHED_PTP' }

/** The drawer's three-cell strip, straight off the served case detail. Nothing is
 * computed: paid/total/remaining are served counts (backend TASK-102) and the
 * outstanding figure falls back to the work item's own aggregate. */
export function contactSummary(data) {
  const totals = data?.payment_summary?.totals
  if (!totals) return undefined
  const instalments = totals.breakdown?.instalment
  return {
    arrears: money(totals.overdue_amount ?? data?.work_item?.aggregate_overdue),
    paid: instalments?.counts?.PAID ?? totals.paid_count ?? totals.counts?.PAID ?? '—',
    total: instalments?.count ?? totals.cycle_count ?? '—',
    remaining: instalments?.remaining_count ?? totals.remaining_count ?? '—',
  }
}

/** The customer's promise the drawer moves instead of duplicating: the OPEN one, or
 * the most recently broken one when nothing is open. */
export function openPromise(data) {
  const all = data?.ptps || []
  const open = all.find((p) => p.status === 'OPEN')
  if (open) return open
  return [...all]
    .filter((p) => p.status === 'BROKEN')
    .sort((a, b) => String(b.promise_date || '').localeCompare(String(a.promise_date || '')))[0]
}

// The daily slot's closed dictionary (app/collections/contact.py DISPOSITIONS) is a
// different set from the case row's CONTACT_RESULT. The proven map from the previous
// drawer, kept verbatim: one result choice, two codes, no guessing by the server.
const DISPOSITION = {
  REACHED_ANSWERED: 'ANS_DISCUSSED',
  REACHED_PTP: 'ANS_DISCUSSED',
  PROMISED: 'ANS_DISCUSSED',
  SERVICE_ISSUE: 'ANS_DISCUSSED',
  REFUSED_PAY: 'REFUSED_PAY',
  INCONVENIENT: 'ANS_NOT_DISC',
  CALLBACK_REQUESTED: 'ANS_NOT_DISC',
  UNREACHABLE_NO_ANSWER: 'NO_ANSWER',
  LINE_READ: 'LINE_READ',
  LINE_SENT_UNREAD: 'LINE_SENT_UNREAD',
  INBOUND: 'INBOUND_CALLED',
}

/**
 * The contact drawer. Two posts, in the order the daily slot requires:
 *  1. POST /v1/contacts — spends today's slot and returns the 90-second retraction.
 *  2. POST /v1/cases/by-customer/{uid}/contacts — the case row with the mandatory
 *     next action, so the record's history and Today both see the act.
 * A refused slot renders the server's alternatives; `not_counted` retries are offered
 * exactly when the refusal carries them.
 *
 * Feedback round 2 (TASK-010): `summary` is the drawer's three-cell strip (all served
 * strings); a promise result requires its amount and date (R-E) and rides the contact
 * as `ptp`; `promise` is the customer's OPEN or BROKEN promise — when one exists the
 * PTP fields open in "เลื่อนนัด" mode and Save renegotiates it through the existing
 * route, which records its own contact row (J4-02) and spends the slot itself.
 */
export function ContactDrawer({ open, onClose, customer, businessDate, summary, promise, onSaved }) {
  const { t, lang } = usePrefs()
  const identity = useIdentity()
  const toast = useToast()
  const results = useDictionary('CONTACT_RESULT')
  const nextActions = useDictionary('NEXT_ACTION')

  const [channel, setChannel] = useState('PHONE')
  const [result, setResult] = useState('')
  const [note, setNote] = useState('')
  const [nextAction, setNextAction] = useState('')
  const [nextOn, setNextOn] = useState('')
  const [ptpAmount, setPtpAmount] = useState('')
  const [ptpDate, setPtpDate] = useState('')
  const [rescheduleReason, setRescheduleReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState(null)
  const [lockedAlternatives, setLockedAlternatives] = useState(null)

  const options = active(results)
  const actionOptions = active(nextActions)
  const hidden = HIDE_BY_CHANNEL[channel] || new Set()
  const filteredOptions = options.filter((o) => !hidden.has(o.code))
  const allowedOptions = filteredOptions.filter((o) => identity.role !== 'OPS' || !['REACHED_PTP', 'PROMISED'].includes(o.code))
  const showPtp = result === 'REACHED_PTP' || result === 'PROMISED'
  const ptpForbidden = identity.role === 'OPS' && showPtp
  const reschedule = Boolean(promise) && showPtp

  // A fresh form when the drawer opens or the customer changes — never on a reload of
  // the same customer (a refused save reloads the case, and its answer and the typed
  // fields must stay on screen even when the reloaded case carries another promise).
  useEffect(() => {
    if (!open) return
    setChannel('PHONE')
    setResult('')
    setNote('')
    setNextAction('')
    setNextOn(businessDate ? addDays(businessDate, 1) : '')
    setPtpAmount(promise?.promised_amount || '')
    setPtpDate(promise?.promise_date || (businessDate ? addDays(businessDate, 1) : ''))
    setRescheduleReason('')
    setProblem(null)
    setLockedAlternatives(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, customer?.uid])

  useEffect(() => {
    if (allowedOptions.length && (!result || ptpForbidden)) setResult(allowedOptions[0].code)
  }, [allowedOptions, result, ptpForbidden])
  // Channel switch keeps a PTP as a PTP: phone promise <-> LINE promise.
  // Any other hidden result falls back to the first visible option.
  useEffect(() => {
    if (!result) return
    if (!hidden.has(result)) return
    const counterpart = PTP_COUNTERPART[result]
    if (counterpart && allowedOptions.some((o) => o.code === counterpart)) {
      setResult(counterpart)
    } else if (allowedOptions.length) {
      setResult(allowedOptions[0].code)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channel])
  useEffect(() => {
    if (actionOptions.length && !nextAction) setNextAction(actionOptions[0].code)
  }, [actionOptions, nextAction])

  // `alternative` is one of the served ways through a locked daily slot (contact_locked):
  // INBOUND_NOT_COUNTED records the contact as the customer's own (inbound never counts);
  // SECOND_CONTACT_NOT_COUNTED re-sends the same act declared not counted — the server's
  // own `how_th`. Neither takes or releases the day's lock.
  async function save({ alternative } = {}) {
    if (!customer?.uid) return
    setBusy(true)
    setProblem(null)
    setLockedAlternatives(null)
    const by = identity.officer || undefined
    const direction = result === 'INBOUND' || alternative === 'INBOUND_NOT_COUNTED' ? 'INBOUND' : 'OUTBOUND'
    const notCounted = alternative ? { not_counted: true } : {}
    // F01b / TASK-010(e): a promise already open is moved, never duplicated. The
    // renegotiate route writes its own contact row and spends the daily slot itself
    // (J4-02), so no second logCaseContact follows it.
    if (reschedule) {
      try {
        await api.renegotiatePtp(promise.uid, {
          amount: ptpAmount,
          date: ptpDate,
          reason: rescheduleReason.trim() || note.trim() || t('drawer.renegotiateReason'),
          by,
          channel,
          note: note.trim() || undefined,
          ...notCounted,
        })
      } catch (error) {
        const p = error?.problem
        if (p?.code === 'contact_locked' && Array.isArray(p.extensions?.alternatives)) {
          setLockedAlternatives(p.extensions.alternatives)
        }
        setProblem(p || { code: 'request_failed' })
        setBusy(false)
        onSaved?.()
        return
      }
      setBusy(false)
      toast(t('drawer.saved'))
      onSaved?.()
      onClose()
      return
    }
    let first = null
    try {
      first = await api.logContact({
        customer_uid: customer.uid,
        channel,
        direction,
        disposition: DISPOSITION[result] || 'ANS_NOT_DISC',
        officer: by,
        role: identity.role,
        ...(alternative === 'SECOND_CONTACT_NOT_COUNTED' ? notCounted : {}),
      })
    } catch (error) {
      const p = error?.problem
      if (p?.code === 'contact_locked' && Array.isArray(p.extensions?.alternatives)) {
        setLockedAlternatives(p.extensions.alternatives)
      }
      setProblem(p || { code: 'request_failed' })
      setBusy(false)
      return
    }
    try {
      await api.logCaseContact(customer.uid, {
        result,
        channel,
        direction,
        counted: Boolean(first?.counted),
        // The slot's own answer, like `counted`: a second contact declared not counted
        // keeps its "ไม่นับ" chip on the case's history.
        not_counted: Boolean(first?.not_counted_declared),
        note: note.trim() || null,
        next_action: nextAction,
        next_action_on: nextOn,
        by,
        // R-E / TASK-010(c): the promise travels with the contact, amount and date
        // included, exactly as the server stores it.
        ...(showPtp ? { ptp: { amount: ptpAmount, date: ptpDate } } : {}),
      })
    } catch (error) {
      setProblem(error?.problem || { code: 'request_failed' })
      setBusy(false)
      onSaved?.()
      return
    }
    setBusy(false)
    toast(t('drawer.saved'))
    onSaved?.()
    onClose()
  }

  // TASK-010(d): the case already holds an OPEN promise — the refusal names it, and
  // the drawer offers the same renegotiation the reschedule mode uses.
  async function renegotiate() {
    const uid = problem?.extensions?.ptp_uid || promise?.uid
    if (!uid) return
    setBusy(true)
    setProblem(null)
    try {
      await api.renegotiatePtp(uid, {
        amount: ptpAmount,
        date: ptpDate,
        reason: note.trim() || t('drawer.renegotiateReason'),
        by: identity.officer || undefined,
        channel,
        note: note.trim() || undefined,
      })
    } catch (error) {
      setProblem(error?.problem || { code: 'request_failed' })
      setBusy(false)
      onSaved?.()
      return
    }
    setBusy(false)
    toast(t('drawer.saved'))
    onSaved?.()
    onClose()
  }

  const missingPtp = showPtp && (!ptpAmount || !ptpDate)
  const missingReason = reschedule && !rescheduleReason.trim()
  const missingNext = !nextAction || !nextOn
  const saveDisabled = busy || !result || missingNext || missingPtp || missingReason || ptpForbidden
  // The disabled Save says what is missing (the server's own sentence for a promise);
  // the enabled one carries the rule the officer needs at the moment of saving.
  const saveTitle = ptpForbidden ? t('drawer.ptpRoleRequired') : missingPtp ? t('drawer.needPtp') : missingReason ? t('drawer.needReason')
    : missingNext ? t('drawer.needNext') : t('drawer.countsToday')

  const alternatives = (lockedAlternatives || []).filter((a) => a.code === 'INBOUND_NOT_COUNTED' || a.code === 'SECOND_CONTACT_NOT_COUNTED')
  const promiseWord = promise ? t(ptpStatus(promise.status).key) : ''

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('drawer.contactTitle')}
      subtitle={customer?.display_name || ''}
      footer={(
        <>
          <button type="button" className="btn" onClick={onClose}>{t('common.cancel')}</button>
          <button type="button" className="btn btn--primary" disabled={saveDisabled} title={saveTitle}
                  onClick={() => save()}>
            {t('drawer.save')}
          </button>
        </>
      )}
    >
      {/* F02 / TASK-010(a): the three served figures first — outstanding, instalments
          paid of the total, instalments remaining. */}
      {summary ? (
        <div className="contact__strip">
          <div>
            <span className="eyebrow">{t('drawer.summaryArrears')}</span>
            <span className="contact__stripValue num">{summary.arrears ?? '—'}</span>
          </div>
          <div>
            <span className="eyebrow">{t('drawer.summaryPaid')}</span>
            <span className="contact__stripValue num">{summary.paid ?? '—'} / {summary.total ?? '—'}</span>
          </div>
          <div>
            <span className="eyebrow">{t('drawer.summaryRemaining')}</span>
            <span className="contact__stripValue num">{summary.remaining ?? '—'}</span>
          </div>
        </div>
      ) : null}
      <div className="contact__grid contact__grid--channel">
        <label>
          <span className="eyebrow">{t('drawer.channel')}</span>
          <select className="field" value={channel} onChange={(e) => setChannel(e.target.value)}>
            {CHANNELS.map((c) => <option key={c.id} value={c.id}>{t(c.key)}</option>)}
          </select>
        </label>
        <label>
          <span className="eyebrow">{t('drawer.result')}<span className="req" aria-hidden="true">*</span></span>
          <select className="field" value={result} aria-required="true" onChange={(e) => setResult(e.target.value)}>
            {filteredOptions.map((o) => <option key={o.code} value={o.code}
              disabled={identity.role === 'OPS' && ['REACHED_PTP', 'PROMISED'].includes(o.code)}>{labelFor(options, o.code, lang)}</option>)}
          </select>
        </label>
      </div>
      {identity.role === 'OPS' ? <p className="contact__hint">{t('drawer.ptpRoleRequired')}</p> : null}
      {/* F01 / F01b / F01c (TASK-010(b)(e)): a promise result carries its amount and
          date; when one is already open the same fields move it instead. */}
      {showPtp ? (
        <fieldset className="contact__ptp">
          <legend>{reschedule ? t('drawer.rescheduleTitle') : t('drawer.ptpLegend')}</legend>
          {reschedule ? (
            <p className="contact__hint num" title={t('drawer.rescheduleRule')}>
              {t('drawer.rescheduleHint', {
                n: promise.renegotiation_count ?? 0, status: promiseWord,
                amount: money(promise.promised_amount), date: fmtDate(promise.promise_date),
              })}
            </p>
          ) : null}
          <div className="contact__grid">
            <label>
              <span className="eyebrow">{t('drawer.ptpAmount')}<span className="req" aria-hidden="true">*</span></span>
              <input className="field" inputMode="decimal" value={ptpAmount} aria-required="true"
                     onChange={(e) => setPtpAmount(e.target.value)} />
            </label>
            <label>
              <span className="eyebrow">{t('drawer.ptpDate')}<span className="req" aria-hidden="true">*</span></span>
              <input className="field" type="date" value={ptpDate} aria-required="true"
                     onChange={(e) => setPtpDate(e.target.value)} />
            </label>
          </div>
          {reschedule ? (
            <label>
              <span className="eyebrow">{t('drawer.rescheduleReason')}<span className="req" aria-hidden="true">*</span></span>
              <textarea className="field" rows={2} value={rescheduleReason} aria-required="true"
                        onChange={(e) => setRescheduleReason(e.target.value)} />
            </label>
          ) : null}
        </fieldset>
      ) : null}
      <div className="contact__grid contact__grid--next">
        <label>
          <span className="eyebrow">{t('drawer.nextAction')}<span className="req" aria-hidden="true">*</span></span>
          <select className="field" value={nextAction} aria-required="true" onChange={(e) => setNextAction(e.target.value)}>
            {actionOptions.map((o) => <option key={o.code} value={o.code}>{labelFor(actionOptions, o.code, lang)}</option>)}
          </select>
        </label>
        <label>
          <span className="eyebrow">{t('drawer.nextDate')}<span className="req" aria-hidden="true">*</span></span>
          <input className="field" type="date" value={nextOn} aria-required="true" onChange={(e) => setNextOn(e.target.value)} />
        </label>
      </div>
      <label>
        <span className="eyebrow">{t('drawer.note')}</span>
        <textarea className="field" rows={4} value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      {problem ? <Problem problem={problem} /> : null}
      {problem?.code === 'ptp_already_open' ? (
        <div className="contact__alt">
          <p className="contact__hint">{t('drawer.ptpOpen', { uid: problem.extensions?.ptp_uid || '—' })}</p>
          <button type="button" className="btn btn--sm" disabled={busy || missingPtp}
                  onClick={renegotiate}>
            {t('drawer.renegotiate')}
          </button>
        </div>
      ) : null}
      {alternatives.length > 0 ? (
        <div className="contact__alt">
          {alternatives.map((a) => (
            <button key={a.code} type="button" className="btn btn--sm" disabled={saveDisabled}
                    onClick={() => save({ alternative: a.code })}>
              {lang === 'en' ? a.label_en || a.label_th : a.label_th || a.label_en || a.code}
            </button>
          ))}
        </div>
      ) : null}
    </Drawer>
  )
}

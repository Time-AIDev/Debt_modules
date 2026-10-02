import { useState } from 'react'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { money } from '../lib/format.js'
import { useIdentity } from '../lib/identity.jsx'
import { useDictionary, active, labelFor } from '../lib/dictionaries.js'
import { Drawer } from './Drawer.jsx'
import { Problem } from './Problem.jsx'
import { useToast } from './Toast.jsx'

/**
 * End a customer's contract — 2026-09-20, the Closed/Terminated ruling.
 *
 * CLOSED means paid per the terms and nothing else; every other way a contract ends
 * (VOLT on default, or the customer's own request) is TERMINATED and must carry its
 * cause. The server enforces both: a cause from TERMINATION_CAUSE, a reason, and a
 * closed balance — a live contract that still owes answers 409 `balance_not_closed`
 * with the payoff figure and the blocking contracts, which this drawer renders as
 * what to do next (settle it, or have an OWNER write it off). The screen only opens
 * it for MANAGER and up; the route refuses the rest.
 */
export function TerminateDrawer({ open, onClose, customerUid, onDone }) {
  const { t, lang } = usePrefs()
  const identity = useIdentity()
  const toast = useToast()
  const causes = useDictionary('TERMINATION_CAUSE')
  const [cause, setCause] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState(null)

  const blocking = problem?.extensions?.blocking || []
  const payoff = problem?.extensions?.payoff_amount

  function reset() {
    setCause('')
    setReason('')
    setProblem(null)
  }

  function close() {
    reset()
    onClose()
  }

  async function submit() {
    if (busy) return
    setBusy(true)
    setProblem(null)
    try {
      await api.terminateCustomerContract(customerUid, {
        cause, reason, by: identity.officer || undefined,
      })
      toast(t('record.terminated'))
      reset()
      onDone?.()
      onClose()
    } catch (e) {
      setProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Drawer
      open={open}
      onClose={close}
      title={t('record.terminateTitle')}
      footer={(
        <>
          <button type="button" className="btn" onClick={close}>{t('common.cancel')}</button>
          <button type="button" className="btn btn--primary" title={t('record.terminateNote')}
                  disabled={busy || !cause || !reason.trim()} onClick={submit}>
            {t('record.terminateRun')}
          </button>
        </>
      )}
    >
      <label>
        <span className="eyebrow">{t('record.terminateCause')}<span className="req" aria-hidden="true">*</span></span>
        <select className="field" value={cause} aria-required="true" onChange={(e) => setCause(e.target.value)}>
          <option value="">—</option>
          {active(causes).map((c) => <option key={c.code} value={c.code}>{labelFor(causes, c.code, lang)}</option>)}
        </select>
      </label>
      <label>
        <span className="eyebrow">{t('record.terminateReason')}<span className="req" aria-hidden="true">*</span></span>
        <textarea className="field" rows={3} value={reason} aria-required="true" onChange={(e) => setReason(e.target.value)} />
      </label>
      {/* The balance refusal says what to do next: the payoff figure and the contracts
          that still owe, right under the served refusal. */}
      {problem ? <Problem problem={problem} /> : null}
      {payoff ? (
        <p className="contact__hint num" role="status">{t('record.terminateBalance', { amount: money(payoff) })}</p>
      ) : null}
      {blocking.length ? (
        <ul className="terminate__blocking">
          {blocking.map((b) => (
            <li key={b.contract_uid} className="num">
              <span>{b.contract_uid}</span>
              <span>{money(b.outstanding)}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </Drawer>
  )
}

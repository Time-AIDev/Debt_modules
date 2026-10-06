import { useState } from 'react'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { money } from '../lib/format.js'
import { useIdentity } from '../lib/identity.jsx'
import { useDictionary, active, labelFor } from '../lib/dictionaries.js'
import { Drawer } from './Drawer.jsx'
import { Problem } from './Problem.jsx'
import { useToast } from './Toast.jsx'

/** Ending a contract preserves the actual balance and money records. */
export function TerminateDrawer({ open, onClose, customerUid, outstanding, onDone }) {
  const { t, lang } = usePrefs()
  const identity = useIdentity()
  const toast = useToast()
  const causes = useDictionary('TERMINATION_CAUSE')
  const [cause, setCause] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState(null)

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
      <p className="contact__hint" role="note">{t('record.terminateNote')}</p>
      <p className="contact__hint num">
        {outstanding == null ? t('record.terminateBalanceUnknown')
          : t('record.terminateBalance', { amount: money(outstanding) })}
      </p>
      {problem ? <Problem problem={problem} /> : null}
    </Drawer>
  )
}

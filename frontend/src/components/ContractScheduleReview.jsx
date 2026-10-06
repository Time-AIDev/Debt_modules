import { useState } from 'react'
import { api } from '../lib/api.js'
import { useIdentity } from '../lib/identity.jsx'
import { usePrefs } from '../lib/prefs.jsx'
import { date as fmtDate } from '../lib/format.js'
import { Problem } from './Problem.jsx'

export function ContractScheduleReview({ data, onChanged }) {
  return (data.payment_summary?.contracts || []).filter((entry) => entry.requires_schedule_confirmation
    && entry.product === 'LEASE').map((entry) => <Review key={entry.contract_uid}
      entry={entry} onChanged={onChanged} />)
}

function Review({ entry, onChanged }) {
  const { t } = usePrefs()
  const { role } = useIdentity()
  const [confirmation, setConfirmation] = useState(null)
  const [history, setHistory] = useState(null)
  const [form, setForm] = useState({ first_due: '', document_ref: '', reason: '' })
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState(null)
  const current = confirmation || entry.schedule_confirmation
  const allowed = ['MANAGER', 'OWNER'].includes(role)
  async function submit(event) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setProblem(null)
    try {
      const result = await api.confirmContractSchedule(entry.contract_uid, form)
      setConfirmation(result.confirmation)
      setHistory(null)
      onChanged?.()
    } catch (error) { setProblem(error.problem || { code: 'request_failed' }) }
    finally { setBusy(false) }
  }
  async function readHistory() {
    setProblem(null)
    try { setHistory((await api.contractScheduleConfirmation(entry.contract_uid)).history) }
    catch (error) { setProblem(error.problem || { code: 'request_failed' }) }
  }
  return <section className="case__stack" aria-label={t('schedule.title')}>
    <strong>{entry.contract_uid} · {t('schedule.title')}</strong>
    {current ? <>
      <span>{t('schedule.verified', { date: fmtDate(current.first_due) })}</span>
      <small>{current.document_ref} · {current.confirmed_by} · {current.reason}</small>
    </> : <><span>{t('schedule.unverified')}</span>
      {entry.source_first_due ? <small>{t('schedule.provisionalDate', { date: fmtDate(entry.source_first_due) })}</small> : null}</>}
    {entry.schedule_conflict ? <span>{t('schedule.conflict', {
      date: fmtDate(entry.schedule_conflict.source_first_due),
      confirmed: fmtDate(entry.schedule_conflict.confirmed_first_due),
    })}</span> : null}
    {entry.unplaced_peak_details?.length ? <details>
      <summary>{t('schedule.unplaced', { n: entry.unplaced_peak_details.length })}</summary>
      {entry.unplaced_peak_details.map((invoice) => <p key={invoice.uid}>
        {invoice.doc_no || invoice.uid} · {fmtDate(invoice.due_date)} · {t(`schedule.reason.${invoice.reason}`)}
      </p>)}
    </details> : null}
    {allowed ? <details><summary>{t('schedule.review')}</summary>
      <form className="case__stack" onSubmit={submit}>
        <label>{t('schedule.firstDue')}<input type="date" required value={form.first_due}
          onChange={(e) => setForm({ ...form, first_due: e.target.value })} /></label>
        <label>{t('schedule.document')}<input required maxLength={1000} value={form.document_ref}
          onChange={(e) => setForm({ ...form, document_ref: e.target.value })} /></label>
        <label>{t('schedule.reason')}<textarea required maxLength={1000} value={form.reason}
          onChange={(e) => setForm({ ...form, reason: e.target.value })} /></label>
        <button className="btn btn--sm" disabled={busy} type="submit">{t('schedule.confirm')}</button>
      </form>
    </details> : null}
    <button className="btn btn--sm" type="button" onClick={readHistory}>{t('schedule.history')}</button>
    {history ? <ul>{history.map((row) => <li key={row.uid}>
      {fmtDate(row.first_due)} · {row.document_ref} · {row.confirmed_by} · {row.confirmed_at} · {row.reason}
    </li>)}</ul> : null}
    {problem ? <Problem problem={problem} /> : null}
  </section>
}

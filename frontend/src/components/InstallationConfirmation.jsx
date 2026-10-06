import { useState } from 'react'
import { api } from '../lib/api.js'
import { useIdentity } from '../lib/identity.jsx'
import { usePrefs } from '../lib/prefs.jsx'
import { date } from '../lib/format.js'
import { Problem } from './Problem.jsx'
import { useToast } from './Toast.jsx'

/** An imported installation month is source evidence; it cannot attest completion. */
export function InstallationConfirmation({ data, onChanged }) {
  const { t } = usePrefs()
  const exclusions = data.case?.npl_assessment?.exclusions || []
  const contracts = (data.contracts || []).filter((contract) =>
    exclusions.some((r) => r.contract_uid === contract.uid && r.reason === 'INSTALLATION_UNCONFIRMED')
    || contract.installation_confirmation?.eligibility?.state === 'UNCONFIRMED')
  if (!contracts.length) return null
  return <section className="case__stack" aria-label={t('installation.title')}>
    <strong>{t('installation.title')}</strong><p>{t('installation.note')}</p>
    {contracts.map((contract) => <Confirmation key={contract.uid} contract={contract} onChanged={onChanged} />)}
  </section>
}

function Confirmation({ contract, onChanged }) {
  const { t } = usePrefs()
  const { role } = useIdentity()
  const toast = useToast()
  const allowed = ['OFFICER', 'SUPERVISOR', 'MANAGER', 'OWNER', 'OPS'].includes(role)
  const [form, setForm] = useState({ completed_on: '', document_ref: '', reason: '' })
  const [saved, setSaved] = useState(null)
  const [problem, setProblem] = useState(null)
  const [busy, setBusy] = useState(false)
  const [idempotencyKey] = useState(() => crypto.randomUUID())
  async function submit(event) {
    event.preventDefault()
    if (busy || !allowed) return
    setBusy(true); setProblem(null)
    try {
      const result = await api.confirmInstallation(contract.uid, { ...form, idempotency_key: idempotencyKey })
      setSaved(result.confirmation)
      toast(t('installation.saved')); onChanged?.()
    } catch (error) { setProblem(error.problem || { code: 'request_failed' }) }
    finally { setBusy(false) }
  }
  return <div className="case__stack"><span>{contract.uid}</span>
    {saved ? <p>{t('installation.confirmed', { date: date(saved.completed_on) })} · {saved.document_ref}</p> :
      <details><summary>{t('installation.record')}</summary>
        <form className="case__stack" onSubmit={submit}>
          <fieldset disabled={busy || !allowed} className="case__stack">
            <label>{t('installation.completedOn')}<input className="field" type="date" required value={form.completed_on}
              onChange={(e) => setForm({ ...form, completed_on: e.target.value })} /></label>
            <label>{t('installation.reference')}<input className="field" required maxLength={1000} value={form.document_ref}
              onChange={(e) => setForm({ ...form, document_ref: e.target.value })} /></label>
            <label>{t('installation.reason')}<textarea className="field" required maxLength={1000} value={form.reason}
              onChange={(e) => setForm({ ...form, reason: e.target.value })} /></label>
            <button className="btn btn--sm" disabled={busy} type="submit">{t('installation.confirm')}</button>
          </fieldset>
        </form>
      </details>}
    <Problem problem={problem} />
  </div>
}

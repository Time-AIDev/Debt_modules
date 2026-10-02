import { useState } from 'react'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useIdentity } from '../lib/identity.jsx'
import { money, date as fmtDate, when } from '../lib/format.js'
import { Drawer } from './Drawer.jsx'
import { Problem } from './Problem.jsx'
import { useToast } from './Toast.jsx'

/** Service evidence and collection due dates are independent of PEAK cash. */
export function ServiceDeferrals({ data, onChanged }) {
  const { t } = usePrefs()
  const identity = useIdentity()
  const [action, setAction] = useState(null)
  const entries = (data.payment_summary?.contracts || []).filter((e) => e.product === 'LEASE'
    && !['CLOSED', 'TERMINATED'].includes(data.contracts?.find((k) => k.uid === e.contract_uid)?.status))
  const rows = data.service_deferrals || []
  const position = data.work_item?.payment_position
  const allowed = ['OFFICER', 'SUPERVISOR', 'MANAGER', 'OWNER'].includes(identity.role)
  const allowedReview = allowed || identity.role === 'OPS'
  if (!entries.length && !rows.length) return null
  return <section className="case__stack" aria-label={t('deferral.title')}>
    {position?.collection_overdue !== undefined ? <div className="case__stack">
      <span>{t('deferral.peakOutstanding')}: {money(position.peak_outstanding)}</span>
      <span>{t('deferral.overdueAfter')}: {money(position.collection_overdue)}</span>
      <span>{t('deferral.deferredAmount')}: {money(position.deferred_amount)}</span>
      <small>{t('deferral.balanceNote')}</small>
    </div> : null}
    {allowed && entries.length > 0 ? <button type="button" className="btn btn--sm"
      onClick={() => setAction({ kind: 'create' })}>{t('deferral.create')}</button> : null}
    {rows.length ? <ul className="case__rows">{rows.map((row) => <li key={row.uid} className="case__stack">
      <strong>{t(row.status === 'ACTIVE' ? 'deferral.title' : 'deferral.reversed')}</strong>
      <span>{row.contract_uid} · {row.reason}</span>
      {row.moves.map((move) => <span key={move.n} className="num">
        {t('deferral.cycle', { n: move.n })}: {fmtDate(move.old_due_date)} → {fmtDate(move.new_due_date)}
      </span>)}
      <small>{row.created_by} · {when(row.created_at)} · {t(`deferral.accounting.${row.accounting.status}`)}</small>
      {row.accounting.document_refs?.length ? <small>{row.accounting.document_refs.join(' · ')}</small> : null}
      {row.accounting.note ? <small>{row.accounting.note}</small> : null}
      {row.status === 'REVERSED' ? <small>{row.reversed_by} · {when(row.reversed_at)} · {row.reversal_reason}</small> : null}
      <details><summary>{t('deferral.history')}</summary>
        <p>{fmtDate(row.inputs?.service_from)} → {fmtDate(row.inputs?.service_until)}</p>
        {row.inputs?.confirmation_note ? <p>{row.inputs.confirmation_note} · {row.inputs.confirmed_by}</p> : null}
        {row.ticket_evidence ? <p>{row.ticket_evidence.ticket_ref || row.ticket_evidence.uid} · {row.ticket_evidence.summary}</p> : null}
        {row.history?.map((h, n) => <p key={n}>{t(`deferral.history.${h.act}`)} · {h.by} · {when(h.at)} {h.reason}</p>)}
      </details>
      {allowedReview ? <div className="case__actions">
        {allowed && row.status === 'ACTIVE' ? <button className="btn btn--sm" type="button"
          onClick={() => setAction({ kind: 'reverse', row })}>{t('deferral.reverse')}</button> : null}
        <button className="btn btn--sm" type="button" onClick={() => setAction({ kind: 'accounting', row })}>
          {t('deferral.review')}</button>
      </div> : null}
    </li>)}</ul> : null}
    {action ? <DeferralDrawer key={`${action.kind}-${action.row?.uid || 'new'}`} action={action}
      data={data} entries={entries} onClose={() => setAction(null)} onChanged={onChanged} /> : null}
  </section>
}

function DeferralDrawer({ action, data, entries, onClose, onChanged }) {
  const { t } = usePrefs()
  const toast = useToast()
  const [contractUid, setContractUid] = useState(action.row?.contract_uid || entries[0]?.contract_uid || '')
  const [form, setForm] = useState({ cycles: [], reason: '', service_from: '', service_until: '',
    issue_uid: '', confirmation_note: '', confirmed_by: '', evidence_uid: '' })
  const [preview, setPreview] = useState(null)
  const [problem, setProblem] = useState(null)
  const [busy, setBusy] = useState(false)
  const [uploadName, setUploadName] = useState('')
  const [idempotencyKey] = useState(() => crypto.randomUUID())
  const [reviewStatus, setReviewStatus] = useState(action.row?.accounting?.status || 'PENDING_REVIEW')
  const [documentRefs, setDocumentRefs] = useState(action.row?.accounting?.document_refs?.join(', ') || '')
  const create = action.kind === 'create'
  const accounting = action.kind === 'accounting'
  const contract = entries.find((e) => e.contract_uid === contractUid)
  const selectable = (contract?.cycles || []).filter((c) => c.status === 'OVERDUE' && !c.deferral && !c.partly_paid && Number(c.paid || 0) === 0)
  const issues = data.issues || []
  const ticket = issues.find((i) => i.uid === form.issue_uid)
  const ticketConfirmed = ticket && (ticket.status === 'RESOLVED' || ticket.fault_confirmed === true)
  const ready = form.reason.trim() && (!create || (form.cycles.length && form.service_from && form.service_until
    && (ticketConfirmed || (form.confirmation_note.trim() && form.confirmed_by.trim()))))
  const title = t(accounting ? 'deferral.review' : create ? 'deferral.create' : 'deferral.reverse')
  const close = () => { if (!busy) onClose() }
  function change(key, value) {
    setForm((current) => ({ ...current, [key]: value }))
    setPreview(null)
    setProblem(null)
  }
  async function run(confirm) {
    if (busy) return
    setBusy(true)
    setProblem(null)
    try {
      if (accounting) {
        await api.reviewServiceDeferral(contractUid, action.row.uid, {
          status: reviewStatus, note: form.reason, document_refs: documentRefs.split(',').map((r) => r.trim()).filter(Boolean),
        })
      } else if (confirm) {
        if (create) await api.confirmServiceDeferral(contractUid, { ...form, preview_version: preview.version, idempotency_key: idempotencyKey })
        else await api.reverseServiceDeferral(contractUid, action.row.uid, { reason: form.reason, preview_version: preview.version })
      } else {
        const result = create
          ? await api.previewServiceDeferral(contractUid, form)
          : await api.previewServiceDeferralReverse(contractUid, action.row.uid, { reason: form.reason })
        setPreview(result)
        return
      }
      toast(t(accounting ? 'deferral.reviewed' : create ? 'deferral.saved' : 'deferral.reversed'))
      onChanged?.()
      onClose()
    } catch (e) {
      setProblem(e?.problem || { code: 'request_failed' })
      if (!accounting) setPreview(null)
    } finally { setBusy(false) }
  }
  async function upload(file) {
    if (!file) return
    setPreview(null)
    setBusy(true)
    setProblem(null)
    try {
      const result = await api.uploadAttachment(file, `case:${data.customer.uid}`)
      if (!result?.attachment?.uid) throw new Error('Missing attachment')
      change('evidence_uid', result.attachment.uid)
      setUploadName(file.name)
    } catch (e) { setProblem(e?.problem || { code: 'request_failed' }) }
    finally { setBusy(false) }
  }
  const field = (key, type = 'text') => <label className="label">{t(`deferral.${key}`)}
    <input className="field" type={type} value={form[key]} onChange={(e) => change(key, e.target.value)} />
  </label>
  return <Drawer open title={title} onClose={close} footer={<>
    <button type="button" className="btn" disabled={busy} onClick={close}>{t('common.cancel')}</button>
    <button type="button" className="btn btn--primary" disabled={busy || !ready}
      onClick={() => run(accounting || Boolean(preview))}>
      {busy ? t('common.loading') : t(accounting ? 'deferral.reviewSave' : preview ? create ? 'deferral.confirm' : 'deferral.reverseConfirm' : 'deferral.preview')}
    </button>
  </>}>
    <div className="case__stack">
      <p>{t(create ? 'deferral.note' : accounting ? 'deferral.accountingNote' : 'deferral.reverseNote')}</p>
      <fieldset disabled={busy} className="case__stack">
        {create ? <>
          <label className="label">{t('deferral.contract')}
            <select className="field" value={contractUid} onChange={(e) => {
              setContractUid(e.target.value); change('cycles', [])
            }}>{entries.map((e) => <option key={e.contract_uid} value={e.contract_uid}>{e.contract_uid}</option>)}</select>
          </label>
          <fieldset className="case__stack"><legend>{t('deferral.cycles')}</legend>
            {selectable.length ? selectable.map((c) => <label key={c.n}>
              <input type="checkbox" checked={form.cycles.includes(c.n)} onChange={(e) => change('cycles',
                e.target.checked ? [...form.cycles, c.n] : form.cycles.filter((n) => n !== c.n))} />
              {' '}{t('deferral.cycle', { n: c.n })} · {fmtDate(c.due_date)} · {money(c.amount)}
            </label>) : <p>{t('deferral.noEligible')}</p>}
          </fieldset>
          {field('service_from', 'date')}{field('service_until', 'date')}
          <label className="label">{t('deferral.issue_uid')}
            <select className="field" value={form.issue_uid} onChange={(e) => change('issue_uid', e.target.value)}>
              <option value="">{t('deferral.useNote')}</option>
              {issues.map((i) => <option key={i.uid} value={i.uid}>{i.ticket_ref || i.uid} · {i.summary}</option>)}
            </select>
          </label>
          {field('confirmation_note')}{field('confirmed_by')}
          <label className="label">{t('deferral.evidence')}
            <input type="file" onChange={(e) => upload(e.target.files?.[0])} />
          </label>
          {uploadName ? <small>{uploadName}</small> : null}
        </> : null}
        <label className="label">{t(accounting ? 'deferral.reviewNote' : 'deferral.reason')}
          <textarea className="field" value={form.reason} onChange={(e) => change('reason', e.target.value)} />
        </label>
        {accounting ? <>
          <label className="label">{t('deferral.accountingStatus')}
            <select className="field" value={reviewStatus} onChange={(e) => setReviewStatus(e.target.value)}>
              {['PENDING_REVIEW', 'REVIEWED'].map((s) => <option key={s} value={s}>{t(`deferral.accounting.${s}`)}</option>)}
            </select>
          </label>
          <label className="label">{t('deferral.documentRefs')}
            <input className="field" value={documentRefs} onChange={(e) => setDocumentRefs(e.target.value)} />
          </label>
        </> : null}
      </fieldset>
      {preview ? <section aria-label={t('deferral.preview')} className="case__stack" aria-live="polite">
        <ul>{preview.moves.map((m) => <li key={m.n}>{t('deferral.cycle', { n: m.n })}: {' '}
          {fmtDate(create ? m.old_due_date : m.new_due_date)} → {fmtDate(create ? m.new_due_date : m.old_due_date)}</li>)}</ul>
        <p>{t('deferral.newEnd')}: {fmtDate(preview.contract_end_after)}</p>
        <p>{t('deferral.overdueAfter')}: {money(preview.collection_overdue_after)}</p>
        <p>{t('deferral.penaltyAfter')}: {money(preview.penalty_after)}</p>
      </section> : null}
      {problem ? <Problem problem={problem} /> : null}
    </div>
  </Drawer>
}

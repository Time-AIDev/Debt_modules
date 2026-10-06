import { useState } from 'react'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useIdentity } from '../lib/identity.jsx'
import { money, date as fmtDate } from '../lib/format.js'
import { Drawer } from './Drawer.jsx'
import { Problem } from './Problem.jsx'

const active = (row) => row.is_due && !['DRAFT', 'VOID', 'CANCELLED', 'AR_REVIEW'].includes(row.state)
  && row.collection_exclusion_reason !== 'DUPLICATE_DOCUMENT'
const eligible = (row, action) => active(row) && (action === 'REJECT' ? row.review_status !== 'REJECTED'
  : row.review_status !== 'ACCEPTED' && !row.unmatched_reason && row.liability_verified !== false)

/** Row and bulk use the same preview/commit protocol; bulk receives the full API list. */
export function InvoiceReviews({ data, invoice, onChanged }) {
  const { t } = usePrefs()
  const identity = useIdentity()
  const [action, setAction] = useState(null)
  const allowed = ['OFFICER', 'SUPERVISOR', 'MANAGER', 'OWNER'].includes(identity.role)
    && (identity.role !== 'OFFICER' || !data.case?.officer_uid || !identity.officer || data.case.officer_uid === identity.officer)
  const rows = invoice ? [invoice] : data.invoices || []
  return <div className="case__stack">
    {invoice ? <span>{t(`invoiceReview.status.${invoice.review_status || 'UNMATCHED'}`)}</span> : null}
    {invoice?.review?.reason ? <small>{invoice.review.reason}</small> : null}
    {invoice?.review_source_changed ? <small>{t('invoiceReview.sourceChanged')}</small> : null}
    {allowed ? <div className="case__actions">{['ACCEPT', 'REJECT'].map((kind) =>
      <button key={kind} type="button" className="btn btn--sm"
        disabled={!rows.some((row) => eligible(row, kind))}
        onClick={() => setAction(kind)}>{t(`invoiceReview.${invoice ? 'single' : 'bulk'}.${kind}`)}</button>)}
    </div> : null}
    {action ? <ReviewDialog key={action} action={action} customerUid={data.customer.uid}
      rows={rows.filter((row) => eligible(row, action))} onClose={() => setAction(null)} onChanged={onChanged} /> : null}
  </div>
}

function ReviewDialog({ action, customerUid, rows, onClose, onChanged }) {
  const { t } = usePrefs()
  const [reason, setReason] = useState('')
  const [preview, setPreview] = useState(null)
  const [checked, setChecked] = useState(false)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState(null)
  const [key, setKey] = useState(() => crypto.randomUUID())
  const payload = { invoice_uids: rows.map((r) => r.uid), action, reason }
  async function run() {
    if (busy) return
    setBusy(true); setProblem(null)
    try {
      if (!preview) {
        setPreview(await api.previewInvoiceReviews(customerUid, payload))
        setChecked(false)
      } else {
        await api.confirmInvoiceReviews(customerUid, { ...payload, preview_version: preview.version, idempotency_key: key })
        onChanged?.(); onClose()
      }
    } catch (error) {
      setProblem(error?.problem || { code: 'request_failed' })
      if (error?.problem?.status === 409) {
        setPreview(null); setChecked(false); setKey(crypto.randomUUID()); onChanged?.()
      }
    } finally { setBusy(false) }
  }
  return <Drawer open title={t(`invoiceReview.bulk.${action}`)} onClose={() => { if (!busy) onClose() }}
    footer={<><button className="btn" type="button" disabled={busy} onClick={onClose}>{t('common.cancel')}</button>
      <button className="btn btn--primary" type="button"
        disabled={busy || (action === 'REJECT' && !reason.trim()) || (preview && !checked)} onClick={run}>
        {t(preview ? 'invoiceReview.confirm' : 'invoiceReview.preview')}</button></>}>
    <div className="case__stack">
      <p>{t(action === 'REJECT' ? 'invoiceReview.rejectEffect' : 'invoiceReview.acceptEffect')}</p>
      <ul className="case__rows">{(preview?.items || rows).map((r) => <li key={r.uid}>
        {r.peak_number || r.uid} · {fmtDate(r.collection_due_date || r.due_date)} · {money(r.amount)}
      </li>)}</ul>
      {action === 'REJECT' ? <label className="label">{t('invoiceReview.reason')}
        <textarea className="field" value={reason} disabled={busy} maxLength={2000} onChange={(e) => {
          setReason(e.target.value); setPreview(null); setChecked(false); setKey(crypto.randomUUID())
        }} /></label> : null}
      {preview ? <section className="case__stack" aria-live="polite">
        <p>{t('invoiceReview.count', { n: preview.invoice_count })} · {money(preview.amount)}</p>
        <p>{t('invoiceReview.impact')}: {money(preview.before.due_outstanding_amount)} → {money(preview.after.due_outstanding_amount)}</p>
        <label><input type="checkbox" checked={checked} disabled={busy} onChange={(e) => setChecked(e.target.checked)} />{' '}
          {t('invoiceReview.acknowledge')}</label>
      </section> : null}
      {problem ? <Problem problem={problem} /> : null}
    </div>
  </Drawer>
}

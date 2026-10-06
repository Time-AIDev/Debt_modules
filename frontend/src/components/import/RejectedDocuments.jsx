import { useCallback, useEffect, useState } from 'react'
import { api } from '../../lib/api.js'
import { usePrefs } from '../../lib/prefs.jsx'
import { date, int, money } from '../../lib/format.js'
import { LoadError } from '../Problem.jsx'

export function RejectedDocuments({ runId }) {
  const { t } = usePrefs()
  const [page, setPage] = useState(null)
  const [problem, setProblem] = useState(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback(async (offset = 0) => {
    setBusy(true)
    setProblem(null)
    try {
      const next = await api.peakReceiptRejectedDocuments(runId, { limit: 50, offset })
      setPage((previous) => ({ ...next, rows: [...(offset ? previous?.rows || [] : []), ...(next.rows || [])] }))
    } catch (error) {
      setProblem(error.problem || { code: 'request_failed', message_th: 'อ่านเอกสารที่ต้องตรวจสอบไม่ได้ กรุณาลองใหม่' })
    } finally { setBusy(false) }
  }, [runId])
  useEffect(() => { setPage(null); load() }, [load])
  return <section aria-label={t('peak.rejectedDocuments')}>
    <h3>{t('peak.rejectedDocuments')}</h3>
    <p>{t('peak.rejectedReadOnly')}</p>
    {problem ? <LoadError problem={problem} onRetry={() => load()} /> : null}
    {page ? <p role="status">{t('peak.rejectedDocumentCount', { documents: int(page.total), rows: int(page.source_rows) })}</p>
      : !problem ? <p role="status">{t('common.loading')}</p> : null}
    {(page?.rows || []).map((document) => <details key={document.doc_no || document.rows?.[0]?.row}>
      <summary>{document.doc_no || t('peak.reportUndated')} · {(document.codes || []).map((code) => {
        const label = t(`peak.failCode.${code}`)
        return label === `peak.failCode.${code}` ? t('peak.documentNeedsReview') : label
      }).join(', ')}</summary>
      <table className="table">
        <thead><tr>{['peak.sourceRow', 'peak.documentStatus', 'peak.contactCode', 'peak.invoiceRef', 'peak.paymentDate', 'peak.paymentAmount'].map((key) => <th key={key}>{t(key)}</th>)}</tr></thead>
        <tbody>{(document.rows || []).map((row, index) => {
          const value = row.observation || {}
          return <tr key={`${row.row}-${index}`}><td>{row.row}</td><td>{value.status_th || '—'}</td>
            <td>{value.contact_code || '—'}</td><td>{value.invoice_ref || value.system_invoice_ref || value.reference || value.system_reference || '—'}</td>
            <td>{value.paid_on ? date(value.paid_on) : '—'}</td><td>{value.paid_amount == null ? '—' : money(value.paid_amount)}</td></tr>
        })}</tbody>
      </table>
    </details>)}
    {page && page.rows.length < page.total ? <button className="btn" disabled={busy} onClick={() => load(page.rows.length)}>{t('peak.moreRejected')}</button> : null}
  </section>
}

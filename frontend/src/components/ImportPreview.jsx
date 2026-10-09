import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useDictionary, active, labelFor } from '../lib/dictionaries.js'
import { internalOrigin, recordState } from '../lib/origin.js'
import { ConfirmDialog } from './ConfirmDialog.jsx'
import { Problem } from './Problem.jsx'
import { useToast } from './Toast.jsx'

/** A reviewed supplement overlays the current cases; it never replaces the book. */
export function ImportPreview({ preview, canApply, onApplied, onRecheck }) {
  const { t, lang } = usePrefs()
  const location = useLocation()
  const toast = useToast()
  const causes = useDictionary('TERMINATION_CAUSE')
  const [selected, setSelected] = useState(() => new Set())
  const [termination, setTermination] = useState({})
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState(null)
  const [applied, setApplied] = useState(false)
  const [force, setForce] = useState(false)
  const [reason, setReason] = useState('')
  const [page, setPage] = useState(1)
  const [idempotencyKey] = useState(() => crypto.randomUUID())
  const entries = preview.entries || []
  const pageSize = 50
  const visible = entries.slice((page - 1) * pageSize, page * pageSize)
  const chosen = entries.filter((r) => selected.has(r.key))
  const terminating = chosen.filter((r) => r.termination_candidate?.completed_evidence && termination[r.key]?.requested)
  const complete = terminating.every((r) => termination[r.key]?.cause
    && termination[r.key]?.reason?.trim() && termination[r.key]?.scope_confirmed)
  // The review fence answered a refusal: data changed after the review. The
  // honest repair is to re-check (re-upload the same file for a fresh preview);
  // a manager's forced confirm may cross it on record, with a reason.
  const stale = ['state_conflict', 'preview_stale'].includes(problem?.code)
  function toggle(key, checked) {
    setSelected((current) => {
      const next = new Set(current)
      checked ? next.add(key) : next.delete(key)
      return next
    })
    setProblem(null)
  }
  function editTermination(key, field, value) {
    setTermination((current) => ({ ...current, [key]: { ...current[key], [field]: value } }))
    setProblem(null)
  }
  function reasonText(reason) {
    if (typeof reason === 'object') return (lang === 'en' ? reason.message_en : reason.message_th) || reason.message || t('supplement.reviewNeeded')
    const translated = t(`supplement.reason.${reason}`)
    return translated === `supplement.reason.${reason}` ? t('supplement.reviewNeeded') : translated
  }
  async function apply() {
    if (busy || !canApply || !chosen.length || !complete) return
    if (force && !reason.trim()) return
    setBusy(true)
    setProblem(null)
    try {
      const result = await api.applyImportPreview(preview.uid, {
        preview_version: preview.version, idempotency_key: idempotencyKey,
        ...(preview.review_state_version ? { review_state_version: preview.review_state_version } : {}),
        ...(force ? { force_state_change: true, reason: reason.trim() } : {}),
        selected_keys: chosen.map((r) => r.key),
        termination_confirmations: terminating.map((r) => ({ key: r.key,
          cause: termination[r.key].cause, reason: termination[r.key].reason.trim(),
          contract_uids: r.termination_candidate.contract_uids,
        })),
      })
      setApplied(true)
      setConfirmOpen(false)
      toast(t('supplement.applied'))
      onApplied?.(result)
    } catch (error) { setProblem(error.problem || { code: 'request_failed' }) }
    finally { setBusy(false) }
  }
  return <section className="imp__box supplement" aria-label={t('supplement.title')}>
    <div className="imp__receiptHead"><h3 className="imp__h3">{t('supplement.title')}</h3>
      <span>{t(`supplement.profile.${preview.profile}`)}</span></div>
    <div className="imp__receiptBody">
      <p>{t('supplement.overlayNote')}</p>
      <p className="scr-meta">{t('supplement.qualityNote')}</p>
      <div className="history-pagination"><span>{t('supplement.selected', { n: chosen.length, total: entries.length })}</span>
        <button type="button" className="btn btn--sm" disabled={busy || applied || !canApply}
          onClick={() => setSelected((current) => new Set([...current, ...visible.filter((r) => r.eligible).map((r) => r.key)]))}>
          {t('supplement.reviewPage')}</button>
        <button type="button" className="btn btn--primary" disabled={busy || applied || !canApply || !chosen.length || !complete || (force && !reason.trim())}
          onClick={() => { setProblem(null); setConfirmOpen(true) }}>{applied ? t('supplement.applied') : t('supplement.reviewApply')}</button>
      </div>
      {!canApply ? <p>{t('data.managerOnly')}</p> : null}
      {chosen.length && !complete ? <p role="note">{t('supplement.terminationRequired')}</p> : null}
      <Problem problem={problem} />
      {stale ? (
        <div className="imp-apply__fence" role="alert">
          <p>{t('supplement.staleNote')}</p>
          <div className="imp-apply__fenceActs">
            {onRecheck ? (
              <button type="button" className="btn btn--sm" disabled={busy || applied} onClick={onRecheck}>
                {t('supplement.recheck')}
              </button>
            ) : null}
          </div>
          {canApply ? (
            <label className="imp-apply__check">
              <input type="checkbox" checked={force} disabled={busy || applied}
                     onChange={(e) => { setForce(e.target.checked); setProblem(null) }} />
              {t('supplement.forceState')}
            </label>
          ) : null}
          {force ? (
            <label className="label">
              {t('supplement.forceReason')}
              <input className="field" value={reason} disabled={busy || applied}
                     placeholder={t('supplement.forceReasonHint')} onChange={(e) => setReason(e.target.value)} />
            </label>
          ) : null}
          {force && !reason.trim() ? <p className="imp-apply__reason">{t('supplement.forceReasonRequired')}</p> : null}
        </div>
      ) : null}
      <ul className="case__rows supplement__rows">{visible.map((row) => {
        const candidate = row.termination_candidate
        const selectable = row.eligible
        const quality = row.quality || {}
        const fields = [...(quality.missing_cached_fields || []), ...(quality.unknown_money_fields || [])]
        return <li key={row.key} className="case__stack supplement__row">
          <div className="case__actions"><label>
            <input type="checkbox" checked={selected.has(row.key)}
              disabled={busy || applied || !canApply || !selectable}
              onChange={(e) => toggle(row.key, e.target.checked)} />
            {' '}{t('supplement.reviewRow', { name: row.customer_no || row.customer_uid || `${row.source_ref?.sheet} ${row.source_ref?.row}` })}
          </label>
            {row.customer_uid ? <Link className="btn btn--sm" to={`/customers/${encodeURIComponent(row.customer_uid)}`}
              state={recordState(internalOrigin(location, 'nav.data'))}>{t('history.customerCase')}</Link> : null}
          </div>
          <small>{row.source_ref?.sheet} · {t('data.refusalRow', { n: row.source_ref?.row ?? '—' })} · {row.product || '—'} · {row.contract_uid || '—'}</small>
          <p>{t('supplement.statusChange')}: {row.source_status || t('supplement.unknown')} → {row.mapped_status || t('supplement.unknown')}</p>
          {fields.length ? <p role="note">{t('supplement.unknownFields')}: {fields.map((field) => {
            const label = t(`supplement.field.${field}`)
            return label === `supplement.field.${field}`
              ? (/^M\d+$/.test(field) ? field : t('supplement.unknown')) : label
          }).join(' · ')}</p> : null}
          {row.monthly_cells?.length ? <details><summary>{t('supplement.monthEvidence')}</summary>
            {row.monthly_cells.map((cell, index) => <p key={`${cell.month}-${index}`}>
              {cell.month} · {cell.amount_field}: {cell.unknown || cell.amount == null ? t('supplement.unknown') : cell.amount}
              {' · '}{cell.status_field}: {cell.status || t('supplement.unknown')}
            </p>)}
          </details> : null}
          {row.installation ? <p>{t('supplement.installation')}: {row.installation.state || t('supplement.unknown')}
            {row.installation.requires_confirmation ? ` · ${t('supplement.installationReview')}` : ''}</p> : null}
          {row.review_reasons?.length ? <ul>{row.review_reasons.map((reason, index) => <li key={index}>{reasonText(reason)}</li>)}</ul> : null}
          {candidate ? <p>{t(candidate.completed_evidence ? 'supplement.terminationEvidence' : 'supplement.terminationIncomplete')}</p> : null}
          {candidate && selected.has(row.key) ? <label>
            <input type="checkbox" disabled={busy || applied || !candidate.completed_evidence}
              checked={!!termination[row.key]?.requested} onChange={(e) => editTermination(row.key, 'requested', e.target.checked)} />
            {' '}{t('supplement.requestTermination')}
          </label> : null}
          {candidate?.completed_evidence && selected.has(row.key) && termination[row.key]?.requested ? <fieldset disabled={busy || applied} className="case__stack">
            <legend>{t('supplement.terminationReview')}</legend>
            <label>{t('record.terminateCause')}<select className="field" value={termination[row.key]?.cause || ''}
              onChange={(e) => editTermination(row.key, 'cause', e.target.value)}>
              <option value="">{t('supplement.chooseCause')}</option>
              {active(causes).map((cause) => <option key={cause.code} value={cause.code}>{labelFor(causes, cause.code, lang)}</option>)}
            </select></label>
            <label>{t('record.terminateReason')}<textarea className="field" value={termination[row.key]?.reason || ''}
              onChange={(e) => editTermination(row.key, 'reason', e.target.value)} /></label>
            <label><input type="checkbox" checked={!!termination[row.key]?.scope_confirmed}
              onChange={(e) => editTermination(row.key, 'scope_confirmed', e.target.checked)} />
              {' '}{t('supplement.confirmContracts', { contracts: (candidate.contract_uids || []).join(', ') })}</label>
          </fieldset> : null}
        </li>
      })}</ul>
      <div className="history-pagination">
        <button className="btn btn--sm" disabled={page <= 1 || busy} onClick={() => setPage((n) => n - 1)}>{t('history.previous')}</button>
        <span>{t('history.page', { page, total: Math.max(1, Math.ceil(entries.length / pageSize)) })}</span>
        <button className="btn btn--sm" disabled={page * pageSize >= entries.length || busy} onClick={() => setPage((n) => n + 1)}>{t('history.next')}</button>
      </div>
    </div>
    <ConfirmDialog open={confirmOpen} title={t('supplement.reviewApply')}
      onClose={() => { if (!busy) setConfirmOpen(false) }} onConfirm={apply}
      confirmLabel={t('supplement.confirm')} busy={busy} danger={terminating.length > 0}>
      <p>{t('supplement.confirmCount', { n: chosen.length })}</p>
      <ul>{chosen.map((row) => <li key={row.key}>{row.customer_no || row.customer_uid || row.key} · {row.contract_uid || '—'}</li>)}</ul>
      {terminating.length ? <p>{t('supplement.confirmTerminate', { n: terminating.length })}</p> : null}
      <p>{t('supplement.overlayNote')}</p>
      {force ? <p>{t('supplement.confirmForce', { reason: reason.trim() })}</p> : null}
      <Problem problem={problem} />
    </ConfirmDialog>
  </section>
}

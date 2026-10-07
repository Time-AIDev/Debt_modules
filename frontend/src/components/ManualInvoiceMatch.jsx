import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useIdentity } from '../lib/identity.jsx'
import { money, when } from '../lib/format.js'
import { downloadBlob } from '../lib/download.js'
import { paymentStatus } from '../lib/status.js'
import { StatusPill, NeutralChip } from './StatusIcon.jsx'
import { Icon } from './Icon.jsx'
import { InfoPopover } from './InfoPopover.jsx'
import { Problem } from './Problem.jsx'
import { useToast } from './Toast.jsx'
import { OperationProgress } from './import/parts.jsx'

const ACCEPT = '.png,.svg,.csv,.xlsx,.docx,.pdf'

const claimKey = () => globalThis.crypto?.randomUUID?.()
  || `claim-${Date.now()}-${Math.random().toString(16).slice(2)}`

/**
 * Case-side amount-led payment journey. Any operational role can attach evidence,
 * while collection roles can preview and save a provisional claim. Confirmed balances are
 * never edited here; an applied PEAK receipt export resolves the claim later.
 * The lower section retains the existing PEAK identity-link repair tools.
 */
export function ManualInvoiceMatch({ customerUid, kase, invoices = [], claims = [], position, onChanged }) {
  const { t } = usePrefs()
  const identity = useIdentity()
  const canRecordPayments = ['OFFICER', 'SUPERVISOR', 'MANAGER', 'OWNER'].includes(identity.role)
  const toast = useToast()
  const attachTo = `case:${customerUid}`
  const [files, setFiles] = useState(null)
  const [problem, setProblem] = useState(null)
  const [busy, setBusy] = useState(false)
  const [amount, setAmount] = useState('')
  const [paidOn, setPaidOn] = useState('')
  const [note, setNote] = useState('')
  const [reference, setReference] = useState('')
  const [evidenceUid, setEvidenceUid] = useState(null)
  const [allocation, setAllocation] = useState(null)
  const [idempotencyKey, setIdempotencyKey] = useState(claimKey)
  const [writeProblem, setWriteProblem] = useState(null)
  const [fileProblem, setFileProblem] = useState(null)
  // Q7 / TASK-215: pairing this case with a PEAK contact code, from the case side.
  const [codeQuery, setCodeQuery] = useState('')
  const [codes, setCodes] = useState(null)
  const [pickedCode, setPickedCode] = useState('')
  const [linkReason, setLinkReason] = useState('')
  const [linked, setLinked] = useState([])
  const [linkProblem, setLinkProblem] = useState(null)
  const [uploadTask, setUploadTask] = useState(null)
  const uploadAbort = useRef(null)

  const load = useCallback(() => {
    setProblem(null)
    api.attachments(attachTo)
      .then((d) => setFiles(d?.attachments || []))
      .catch((e) => setProblem(e?.problem || { code: 'request_failed' }))
  }, [attachTo])
  useEffect(() => { load() }, [load])

  // A refused read of the case's links is said, not swallowed (refusals stay visible).
  const [linksProblem, setLinksProblem] = useState(null)
  const loadLinks = useCallback(() => {
    setLinksProblem(null)
    if (!kase?.customer_no) { setLinked([]); return }
    api.peakLinks({ customer_no: kase.customer_no })
      .then((d) => setLinked(d?.links || []))
      .catch((e) => { setLinked([]); setLinksProblem(e?.problem || { code: 'request_failed' }) })
  }, [kase?.customer_no])
  useEffect(() => { loadLinks() }, [loadLinks])

  // A refused search is said as the refusal, never as "no match".
  const [codesProblem, setCodesProblem] = useState(null)
  useEffect(() => {
    setCodesProblem(null)
    if (codeQuery.trim().length < 2) { setCodes([]); return undefined }
    let alive = true
    setCodes(null)
    const id = setTimeout(() => {
      api.casePeakCodes(customerUid, codeQuery.trim())
        .then((d) => { if (alive) setCodes(d?.codes || []) })
        .catch((e) => { if (alive) { setCodes([]); setCodesProblem(e?.problem || { code: 'request_failed' }) } })
    }, 180)
    return () => { alive = false; clearTimeout(id) }
  }, [codeQuery, customerUid])

  async function linkCode() {
    if (!pickedCode) return
    setBusy(true)
    setLinkProblem(null)
    try {
      await api.casePeakLink(customerUid, { contact_code: pickedCode, reason: linkReason.trim() || undefined })
      toast(t('peak.linkedToast'))
      setPickedCode('')
      setLinkReason('')
      setCodeQuery('')
      setCodes([])
      loadLinks()
      onChanged?.()
    } catch (e) {
      setLinkProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  async function unlink(uid) {
    setBusy(true)
    setLinkProblem(null)
    try {
      await api.peakLinkRetire(uid, {})
      toast(t('peak.retiredToast'))
      loadLinks()
      onChanged?.()
    } catch (e) {
      setLinkProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  async function upload(file) {
    if (!file) return
    setBusy(true)
    setFileProblem(null)
    const controller = new AbortController()
    uploadAbort.current = controller
    setUploadTask({ phase: 'uploading', uploadedBytes: 0, totalBytes: file.size })
    try {
      const uploaded = await api.uploadAttachment(file, attachTo, {
        signal: controller.signal, onProgress: setUploadTask,
      })
      setEvidenceUid(uploaded?.attachment?.uid || null)
      setUploadTask(null)
      toast(t('record.manualUploaded'))
      load()
    } catch (e) {
      if (e?.name === 'AbortError') return
      setFileProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  async function download(uid, filename) {
    setFileProblem(null)
    try {
      const { blob, filename: named } = await api.downloadAttachment(uid)
      downloadBlob(named || filename, blob)
    } catch (e) {
      setFileProblem(e?.problem || { code: 'request_failed' })
    }
  }

  async function previewClaim() {
    if (!canRecordPayments || !amount || !paidOn) return
    setBusy(true)
    setWriteProblem(null)
    try {
      const next = await api.previewPaymentClaim(customerUid, {
        amount, paid_on: paidOn, reference: reference || undefined,
        evidence_uid: evidenceUid || undefined,
      })
      setAllocation(next)
    } catch (e) {
      setAllocation(null)
      setWriteProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  async function saveClaim() {
    if (!canRecordPayments || !allocation || !note.trim()) return
    setBusy(true)
    setWriteProblem(null)
    try {
      await api.createPaymentClaim(customerUid, {
        amount, paid_on: paidOn, note: note.trim() || undefined,
        reference: reference || undefined, evidence_uid: evidenceUid || undefined,
        preview_version: allocation.version, idempotency_key: idempotencyKey,
      })
      toast(t('record.claimSaved'))
      setAmount('')
      setPaidOn('')
      setNote('')
      setReference('')
      setEvidenceUid(null)
      setAllocation(null)
      setIdempotencyKey(claimKey())
      onChanged?.()
    } catch (e) {
      setWriteProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  async function cancelClaim(uid) {
    if (!canRecordPayments) return
    setBusy(true)
    setWriteProblem(null)
    try {
      await api.cancelPaymentClaim(uid)
      toast(t('record.claimCancelled'))
      onChanged?.()
    } catch (e) {
      setWriteProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  const current = kase?.payment_status
  const system = kase?.payment_status_confirmed || kase?.payment_status_system
  const governed = ['NPL', 'CLOSED', 'TERMINATED', 'NOT_INSTALLED'].includes(system || current)
  const pill = paymentStatus(current)
  const searched = codeQuery.trim().length >= 2

  return (
    <section className="card" data-testid="manual-invoice">
      <header className="card__head mim__head">
        <h2>{t('record.manualTitle')}</h2>
        {/* R-B: the same payment-status pill as the case header (one mapping). */}
        {current ? <StatusPill kind={pill.kind}>{t(pill.key)}</StatusPill> : null}
        {system && system !== current ? (
          <span className="case__rowNote">{t('record.payStatusSystemTip', { label: t(paymentStatus(system).key) })}</span>
        ) : null}
        <InfoPopover align="right">
          {t('record.manualNote')} {t('record.payReasonHint')}
        </InfoPopover>
      </header>
      <div className="card__body mim__body">
        {kase?.payment_status_set_by ? (
          <p className="case__rowNote">
            {t('record.payStatusSetBy', { by: kase.payment_status_set_by, reason: kase.payment_status_reason || '—' })}
          </p>
        ) : null}

        <div className="mim__section">
          <div className="mim__sectionHead">
            <span className="eyebrow">{t('record.manualFilesLabel')}</span>
            {/* The picker is the design's button; the real file input sits inside it. */}
            <label className={`btn btn--sm mim__upload${busy ? ' mim__upload--busy' : ''}`} title={t('record.manualAccept')}>
              <Icon name="upload" />{t('record.manualChoose')}
              <input type="file" className="sr-only" accept={ACCEPT} disabled={busy} aria-label={t('record.manualChoose')}
                     onChange={(e) => upload(e.target.files?.[0])} />
            </label>
          </div>
          {problem ? <Problem problem={problem} onRetry={load} /> : files === null ? (
            <p className="case__empty">{t('common.loading')}</p>
          ) : files.length === 0 ? (
            <p className="case__empty">{t('record.manualNoFiles')}</p>
          ) : (
            <ul className="mim__list" aria-label={t('record.manualFiles')}>
              {files.map((f) => (
                <li key={f.uid} className="mim__file">
                  <Icon name="file" className="case__muted" />
                  <span className="mim__grow">{f.filename}</span>
                  <span className="case__rowNote num">{when(f.uploaded_at)}</span>
                  <button type="button" className="btn btn--quiet btn--sm" onClick={() => download(f.uid, f.filename)}>
                    <Icon name="download" />{t('record.manualDownload')}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {fileProblem ? <Problem problem={fileProblem} /> : null}
          {busy && uploadTask ? (
            <OperationProgress task={uploadTask} onCancel={() => uploadAbort.current?.abort()} />
          ) : null}
        </div>

        {/* Q7 / TASK-215: pairing this case with a PEAK contact code, from the case side. */}
        <div className="mim__section mim__section--rule">
          <label className="label">
            {t('peak.linkCase')}
            <input className="field" value={codeQuery} placeholder={t('peak.linkSearch')}
                   aria-label={t('peak.linkSearch')} disabled={busy}
                   onChange={(e) => { setCodeQuery(e.target.value); setPickedCode('') }} />
          </label>
          {codesProblem ? <Problem problem={codesProblem} /> : null}
          {searched && !codesProblem && Array.isArray(codes) && codes.length === 0 ? <p className="case__empty">{t('record.peakNoMatch')}</p> : null}
          {(codes || []).length ? (
            <ul className="mim__list mim__list--results">
              {codes.map((c) => (
                <li key={c.contact_code} className="mim__code">
                  <span className="mim__codeId num">{c.contact_code}</span>
                  <span className="mim__grow case__rowNote">
                    {[c.customer_name, t('peak.conflictInvoices', { n: c.invoices })].filter(Boolean).join(' · ')}
                  </span>
                  {c.linked_to && c.linked_to !== kase?.customer_no ? (
                    <NeutralChip>{t('peak.linkedElsewhere', { no: c.linked_to })}</NeutralChip>
                  ) : (
                    <button type="button" className="btn btn--sm" disabled={busy}
                            onClick={() => setPickedCode(c.contact_code)}>
                      <Icon name="link" size={14} />{t('peak.link')}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          ) : null}
          {pickedCode ? (
            <div className="mim__pick">
              <label className="label mim__grow">
                {t('peak.decisionReason')}
                <input className="field" value={linkReason} disabled={busy}
                       onChange={(e) => setLinkReason(e.target.value)} />
              </label>
              <button type="button" className="btn btn--quiet" disabled={busy}
                      onClick={() => { setPickedCode(''); setLinkReason('') }}>
                {t('common.cancel')}
              </button>
              <button type="button" className="btn btn--primary" disabled={busy} onClick={linkCode}>
                {t('peak.link')} {pickedCode}
              </button>
            </div>
          ) : null}
          {linked.length ? (
            <>
              <span className="eyebrow">{t('peak.caseLinks')}</span>
              <ul className="mim__list">
                {linked.map((l) => (
                  <li key={l.uid} className="mim__code">
                    <Icon name="link" className="case__muted" />
                    <span className="mim__codeId num">{l.contact_code}</span>
                    <span className="mim__grow case__rowNote">{l.customer_no}{l.reason ? ` · ${l.reason}` : ''}</span>
                    <button type="button" className="btn btn--quiet btn--sm" disabled={busy} onClick={() => unlink(l.uid)}>
                      <Icon name="unlink" />{t('peak.unlink')}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
          {linksProblem ? <Problem problem={linksProblem} onRetry={loadLinks} /> : null}
          {linkProblem ? <Problem problem={linkProblem} /> : null}
        </div>

        {/* Amount-led claim: provisional only. PEAK receipt reconciliation owns the
            confirmed ledger and status. */}
        <div className="mim__section mim__section--rule">
          <div className="mim__sectionHead">
            <div>
              <span className="eyebrow">{t('record.claimTitle')}</span>
              <p className="case__rowNote">{t('record.claimNote')}</p>
            </div>
            {position ? (
              <span className="case__rowNote num">
                {t('record.claimPosition', {
                  confirmed: money(position.confirmed_outstanding),
                  pending: money(position.pending_amount),
                  projected: money(position.projected_outstanding),
                })}
              </span>
            ) : null}
          </div>
          {!canRecordPayments ? <p className="case__rowNote">{t('record.claimRoleHint')}</p> : null}
          {governed ? <p className="case__empty">{t('record.claimGoverned')}</p> : (
            <div className="mim__foldBody">
              <div className="mim__pick">
                <label className="label mim__grow">
                  <span>{t('record.claimAmount')}<span className="req" aria-hidden="true">*</span></span>
                  <input className="field num" type="number" min="0.01" step="0.01" value={amount}
                         aria-label={t('record.claimAmount')} aria-required="true" disabled={busy || !canRecordPayments}
                         onChange={(e) => { setAmount(e.target.value); setAllocation(null) }} />
                </label>
                <label className="label mim__grow">
                  <span>{t('record.claimPaidOn')}<span className="req" aria-hidden="true">*</span></span>
                  <input className="field num" type="date" value={paidOn}
                         aria-label={t('record.claimPaidOn')} aria-required="true" disabled={busy || !canRecordPayments}
                         onChange={(e) => { setPaidOn(e.target.value); setAllocation(null) }} />
                </label>
                <label className="label mim__grow">
                  {t('record.claimReference')}
                  <select className="field" value={reference} disabled={busy || !canRecordPayments}
                          aria-label={t('record.claimReference')}
                          onChange={(e) => { setReference(e.target.value); setAllocation(null) }}>
                    <option value="">{t('record.claimFifo')}</option>
                    {invoices.map((invoice) => (
                      <option key={invoice.uid} value={invoice.peak_number || invoice.uid}>
                        {invoice.peak_number || invoice.uid}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <label className="label">
                <span>{t('record.claimNoteLabel')}<span className="req" aria-hidden="true">*</span></span>
                <textarea className="field" rows={2} value={note} aria-label={t('record.claimNoteLabel')}
                          required aria-required="true" disabled={busy || !canRecordPayments} onChange={(e) => setNote(e.target.value)} />
              </label>
              <div className="mim__actions">
                <button type="button" className="btn" disabled={busy || !canRecordPayments || !amount || !paidOn}
                        onClick={previewClaim}>{busy ? t('common.loading') : t('record.claimPreview')}</button>
                <button type="button" className="btn btn--primary" disabled={busy || !canRecordPayments || !allocation || !note.trim()}
                        onClick={saveClaim}>{t('record.claimSave')}</button>
              </div>
              <div aria-live="polite">
                {allocation ? (
                  <div className="mim__section mim__section--rule">
                    {allocation.duplicate_warning ? (
                      <p className="case__empty">{t('record.claimDuplicate')}</p>
                    ) : null}
                    <p className="case__line num">
                      {money(allocation.confirmed_outstanding)} → {money(allocation.projected_outstanding)}
                      {Number(allocation.credit || 0) > 0 ? ` · ${t('record.claimCredit', { amount: money(allocation.credit) })}` : ''}
                    </p>
                    <ul className="mim__list">
                      {(allocation.allocations || []).map((row) => (
                        <li key={`${row.invoice_doc_no}-${row.order}`} className="mim__file">
                          <span className="mim__grow num">{row.invoice_doc_no}</span>
                          <span className="num">{money(row.before)} → {money(row.after)}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {writeProblem ? <Problem problem={writeProblem} /> : null}
              </div>
            </div>
          )}
          {claims.length ? (
            <ul className="mim__list" aria-label={t('record.claimHistory')}>
              {claims.map((claim) => (
                <li key={claim.uid} className="mim__file">
                  <StatusPill kind={claim.state === 'CONFIRMED' ? 'done' : claim.state === 'NEEDS_REVIEW' ? 'problem' : 'moving-2'}>
                    {t(`record.claimState.${claim.state}`)}
                  </StatusPill>
                  <span className="mim__grow num">{money(claim.amount)} · {claim.paid_on}</span>
                  {claim.state === 'PENDING' ? (
                    <button type="button" className="btn btn--quiet btn--sm" disabled={busy || !canRecordPayments}
                            onClick={() => cancelClaim(claim.uid)}>{t('common.cancel')}</button>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </div>
    </section>
  )
}

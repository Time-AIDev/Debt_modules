import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useIdentity } from '../lib/identity.jsx'
import { money, date as fmtDate, when } from '../lib/format.js'
import { downloadBlob } from '../lib/download.js'
import { preinstallProgress, preinstallReleased } from '../lib/status.js'
import { Drawer } from './Drawer.jsx'
import { Problem } from './Problem.jsx'
import { StatusIcon, StatusPill } from './StatusIcon.jsx'
import { Icon } from './Icon.jsx'
import { useToast } from './Toast.jsx'
import { OperationProgress } from './import/parts.jsx'

const ACCEPT = '.png,.svg,.csv,.xlsx,.docx,.pdf'
const passed = (item) => (item.conditions || []).every((c) => c.passed)

/**
 * The pre-installation card: three release conditions, their evidence, the two gate
 * records and the release act — one component for the Pipeline screen and the
 * customer's own case (2026-09-20). Attaching a slip also passes its gate and lands
 * on the case timeline server-side, so this card never re-implements that rule.
 */
export function PreInstallCard({ item, meta, onChanged, heading = 'pipeline.conditions', evidenceOpen = true }) {
  const { t, lang } = usePrefs()
  const identity = useIdentity()
  const toast = useToast()

  const [evidenceFor, setEvidenceFor] = useState(null)
  const [note, setNote] = useState('')
  const [amount, setAmount] = useState('')
  const [attachFile, setAttachFile] = useState(null)
  const [fileBusy, setFileBusy] = useState(false)
  const [evidenceFiles, setEvidenceFiles] = useState({})
  const [gate, setGate] = useState(null)
  const [gateForm, setGateForm] = useState({ slip_ref: '', amount: '', confirmed_on: '', source: 'ODOO', reason: '' })
  const [busy, setBusy] = useState(false)
  const [writeProblem, setWriteProblem] = useState(null)
  // "ดูหลักฐาน" opens a condition's evidence LIST (it used to open the attach form).
  // Pipeline shows the lists open; the case starts them folded (design D).
  const [folds, setFolds] = useState({})
  const [uploadTask, setUploadTask] = useState(null)
  const uploadAbort = useRef(null)

  const by = identity.officer || undefined

  const loadEvidenceFiles = useCallback((row) => {
    const scopes = (row?.conditions || []).map((c) => c.evidence_scope).filter(Boolean)
    if (!scopes.length) { setEvidenceFiles({}); return }
    Promise.all(scopes.map((s) => api.attachments(s).catch(() => ({ attachments: [] }))))
      .then((parts) => {
        const next = {}
        parts.forEach((p) => (p?.attachments || []).forEach((f) => { next[f.uid] = f }))
        setEvidenceFiles(next)
      })
  }, [])
  useEffect(() => { if (item) loadEvidenceFiles(item) }, [item?.uid, item, loadEvidenceFiles])

  const conditions = item?.conditions || []
  const done = conditions.filter((c) => c.passed).length
  const released = !!item?.released_at
  const downGate = item?.gate_down_payment || {}
  const epcGate = item?.gate_epc_confirmed || {}

  function closeDrawers() {
    setEvidenceFor(null)
    setGate(null)
    setNote('')
    setAmount('')
    setAttachFile(null)
    setWriteProblem(null)
  }

  async function uploadAttachFile(file) {
    if (!file) return
    setFileBusy(true)
    setWriteProblem(null)
    const controller = new AbortController()
    uploadAbort.current = controller
    setUploadTask({ phase: 'uploading', uploadedBytes: 0, totalBytes: file.size })
    try {
      // No attach-to yet: the evidence POST stamps the scope, so a drawer the
      // officer abandons leaves the file unattached rather than half-attached.
      const { attachment } = await api.uploadAttachment(file, undefined, {
        signal: controller.signal, onProgress: setUploadTask,
      })
      setAttachFile({ uid: attachment.uid, filename: attachment.filename })
      setUploadTask(null)
    } catch (e) {
      if (e?.name === 'AbortError') return
      setWriteProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setFileBusy(false)
    }
  }

  async function clearAttachFile() {
    if (!attachFile) return
    setFileBusy(true)
    setWriteProblem(null)
    try {
      await api.deleteAttachment(attachFile.uid)
      setAttachFile(null)
    } catch (e) {
      setWriteProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setFileBusy(false)
    }
  }

  async function viewEvidence(uid, filename) {
    setWriteProblem(null)
    try {
      const { blob, filename: named } = await api.downloadAttachment(uid)
      downloadBlob(named || filename || uid, blob)
    } catch (e) {
      setWriteProblem(e?.problem || { code: 'request_failed' })
    }
  }

  async function attach() {
    setBusy(true)
    setWriteProblem(null)
    try {
      await api.pipelineConditionEvidence(item.uid, evidenceFor.key, {
        note,
        file_uid: attachFile?.uid,
        // Only a down-payment slip carries an amount: it is the figure release needs.
        amount: evidenceFor.key === 'down_payment' && amount ? amount : undefined,
        by,
      })
      closeDrawers()
      toast(t('pipeline.attached'))
      onChanged?.()
    } catch (e) {
      setWriteProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  async function removeEvidence(condition, evidenceUid) {
    setBusy(true)
    setWriteProblem(null)
    try {
      await api.pipelineConditionEvidenceRemove(item.uid, condition.key, evidenceUid)
      toast(t('pipeline.evidenceRemoved'))
      onChanged?.()
    } catch (e) {
      setWriteProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  function openGate(which) {
    setWriteProblem(null)
    setGate(which)
    setGateForm({
      slip_ref: downGate.ref && !String(downGate.ref).startsWith('EVIDENCE:') ? downGate.ref : '',
      amount: item.amount_due || item.amount_hint || '',
      confirmed_on: item.confirmed_install_on || item.planned_install_on || '',
      source: 'ODOO',
      reason: '',
    })
  }

  async function saveGate() {
    setBusy(true)
    setWriteProblem(null)
    try {
      if (gate === 'down_payment') {
        await api.pipelineGateDownPayment(item.uid, {
          slip_ref: gateForm.slip_ref, amount: gateForm.amount || undefined, by: by || 'officer',
        })
        toast(t('pipeline.gateDownSaved'))
      } else {
        await api.pipelineGateEpc(item.uid, {
          confirmed_on: gateForm.confirmed_on, source: gateForm.source,
          reason: gateForm.reason || undefined, by: by || 'epc',
        })
        toast(t('pipeline.gateEpcSaved'))
      }
      closeDrawers()
      onChanged?.()
    } catch (e) {
      setWriteProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  async function release() {
    setBusy(true)
    setWriteProblem(null)
    try {
      await api.pipelineRelease(item.uid, { by: by || 'officer' })
      toast(t('pipeline.released'))
      onChanged?.()
    } catch (e) {
      setWriteProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  const gateReady = gate === 'down_payment'
    ? gateForm.slip_ref.trim().length > 0
    : gateForm.confirmed_on && (gateForm.source === 'ODOO' || gateForm.reason.trim().length > 0)

  const progress = preinstallProgress(done, conditions.length)
  const releaseTitle = released
    ? t('pipeline.releasedAt', { date: fmtDate(item.released_at) })
    : [meta?.invoice_owner_role ? t('pipeline.ownerRole', { role: meta.invoice_owner_role }) : '', t('pipeline.peakNote')].filter(Boolean).join(' · ')
  const openAttach = (c) => { setWriteProblem(null); setNote(''); setAmount(item.amount_due || ''); setAttachFile(null); setEvidenceFor(c) }

  return (
    <section className="card preinstall">
      <header className="card__head" title={t('pipeline.conditionsNote')}>
        <h2>{t(heading)}</h2>
        <StatusPill kind={progress.kind}>{t('pipeline.progress', { done, total: conditions.length })}</StatusPill>
        {released ? <StatusPill kind={preinstallReleased().kind}>{t('pipeline.releasedAt', { date: fmtDate(item.released_at) })}</StatusPill> : null}
      </header>
      <div className="card__body preinstall__body">
        {conditions.map((c) => {
          const evidence = c.evidence || []
          const open = evidence.length > 0 && (folds[c.key] ?? evidenceOpen)
          return (
            <div key={c.key} className="cond">
              <StatusIcon kind={c.passed ? 'done' : 'idle'} className="cond__mark" />
              <div className="cond__main">
                <span className="cond__label">{lang === 'en' ? c.label_en : c.label_th}</span>
                <span className="cond__note">{lang === 'en' ? c.note_en : c.note_th}</span>
                {evidence.length ? <span className="cond__note">{t('pipeline.evidenceCount', { n: c.evidence_count ?? evidence.length })}</span> : null}
                {open ? (
                  <ul className="cond__evidence">
                    {evidence.map((e) => {
                      const f = e.file_uid ? evidenceFiles[e.file_uid] : null
                      return (
                        <li key={e.uid} className="cond__item">
                          <span className="cond__itemMain">
                            <span>{e.note || t('pipeline.evidenceNoNote')}</span>
                            {e.file_uid || e.uploaded_at ? (
                              <span className="cond__note num">
                                {[e.file_uid ? f?.filename || t('pipeline.evidenceFile') : '', e.uploaded_at ? when(e.uploaded_at) : ''].filter(Boolean).join(' · ')}
                              </span>
                            ) : null}
                          </span>
                          {e.file_uid ? (
                            <button type="button" className="btn btn--quiet btn--sm"
                                    onClick={() => viewEvidence(e.file_uid, f?.filename)}>
                              {t('pipeline.evidenceView')}
                            </button>
                          ) : null}
                          {!released ? (
                            <button type="button" className="btn btn--quiet btn--sm" disabled={busy}
                                    onClick={() => removeEvidence(c, e.uid)}>
                              {t('pipeline.removeEvidence')}
                            </button>
                          ) : null}
                        </li>
                      )
                    })}
                    {!released ? (
                      <li>
                        <button type="button" className="btn btn--quiet btn--sm" onClick={() => openAttach(c)}>
                          <Icon name="plus" />{t('pipeline.attachRun')}
                        </button>
                      </li>
                    ) : null}
                  </ul>
                ) : null}
              </div>
              <StatusPill kind={c.passed ? 'done' : 'idle'}>{lang === 'en' ? c.state_label_en : c.state_label_th}</StatusPill>
              {evidence.length ? (
                <button type="button" className="btn btn--sm" aria-expanded={open}
                        onClick={() => setFolds((m) => ({ ...m, [c.key]: !open }))}>
                  {open ? t('pipeline.hideEvidence') : t('pipeline.viewEvidence')}
                </button>
              ) : !released ? (
                <button type="button" className="btn btn--sm" onClick={() => openAttach(c)}>
                  {t('pipeline.attachRun')}
                </button>
              ) : null}
            </div>
          )
        })}

        <div className="preinstall__actions">
          {!released && downGate.state !== 'PASSED' ? (
            <button type="button" className="btn btn--sm" disabled={busy} onClick={() => openGate('down_payment')}>
              {t('pipeline.recordDownPayment')}
            </button>
          ) : null}
          {!released && epcGate.state !== 'PASSED' ? (
            <button type="button" className="btn btn--sm" disabled={busy} onClick={() => openGate('epc')}>
              {t('pipeline.recordEpc')}
            </button>
          ) : null}
          <span className="preinstall__spacer" />
          <span className="preinstall__amount num" title={t('pipeline.amountTip')}>{money(item.amount_due)}</span>
          <button type="button" className="btn btn--primary" disabled={busy || !passed(item) || released}
                  title={releaseTitle} onClick={release}>
            {t('pipeline.release')}
          </button>
        </div>
        {writeProblem && !gate && !evidenceFor ? <Problem problem={writeProblem} /> : null}
      </div>

      <Drawer
        open={!!evidenceFor}
        onClose={closeDrawers}
        title={t('pipeline.attachTitle')}
        subtitle={item.display_name}
        footer={(
          <>
            <button type="button" className="btn" onClick={closeDrawers}>{t('common.cancel')}</button>
            <button type="button" className="btn btn--primary" title={t('pipeline.evidenceNeedOne')}
                    disabled={busy || fileBusy || (!note.trim() && !attachFile)} onClick={attach}>
              {t('pipeline.attachRun')}
            </button>
          </>
        )}
      >
        {/* The condition this evidence binds to; the scope rule rides it as a tooltip. */}
        <p className="preinstall__cond" title={t('pipeline.evidenceScope')}>
          {evidenceFor ? (lang === 'en' ? evidenceFor.label_en : evidenceFor.label_th) : ''}
        </p>
        <label>
          <span className="eyebrow">{t('pipeline.evidenceNote')}</span>
          <textarea className="field" rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        <div className="preinstall__file">
          <span className="eyebrow">{t('pipeline.evidenceFileLabel')}</span>
          {attachFile ? (
            <div className="preinstall__picked">
              <Icon name="file" />
              <span className="preinstall__grow">{attachFile.filename}</span>
              <button type="button" className="btn btn--quiet btn--sm" disabled={fileBusy} onClick={clearAttachFile}>
                {t('pipeline.evidenceRemoveFile')}
              </button>
            </div>
          ) : (
            <label className={`btn btn--sm preinstall__pick${fileBusy || busy ? ' preinstall__pick--busy' : ''}`} title={t('pipeline.evidenceAccept')}>
              <Icon name="upload" />{t('pipeline.evidencePick')}
              <input type="file" className="sr-only" accept={ACCEPT} disabled={fileBusy || busy}
                     aria-label={t('pipeline.evidenceFileLabel')}
                     onChange={(e) => uploadAttachFile(e.target.files?.[0])} />
            </label>
          )}
          {fileBusy && uploadTask ? (
            <OperationProgress task={uploadTask} onCancel={() => uploadAbort.current?.abort()} />
          ) : null}
        </div>
        {evidenceFor?.key === 'down_payment' ? (
          <label>
            <span className="eyebrow">{t('pipeline.gateAmount')}</span>
            <input className="field" inputMode="decimal" value={amount} title={t('pipeline.gateAmountNote')}
                   onChange={(e) => setAmount(e.target.value)} />
          </label>
        ) : null}
        {writeProblem ? <Problem problem={writeProblem} /> : null}
      </Drawer>

      <Drawer
        open={!!gate}
        onClose={closeDrawers}
        title={gate === 'down_payment' ? t('pipeline.gateDownTitle') : t('pipeline.gateEpcTitle')}
        subtitle={item.display_name}
        footer={(
          <>
            <button type="button" className="btn" onClick={closeDrawers}>{t('common.cancel')}</button>
            <button type="button" className="btn btn--primary" disabled={busy || !gateReady} onClick={saveGate}>
              {t('common.save')}
            </button>
          </>
        )}
      >
        {gate === 'down_payment' ? (
          <>
            <label>
              <span className="eyebrow">{t('pipeline.gateRef')}<span className="req" aria-hidden="true">*</span></span>
              <input className="field" value={gateForm.slip_ref} aria-required="true"
                     onChange={(e) => setGateForm((f) => ({ ...f, slip_ref: e.target.value }))} />
            </label>
            <label>
              <span className="eyebrow">{t('pipeline.gateAmount')}</span>
              <input className="field" inputMode="decimal" value={gateForm.amount} title={t('pipeline.gateAmountNote')}
                     onChange={(e) => setGateForm((f) => ({ ...f, amount: e.target.value }))} />
            </label>
          </>
        ) : (
          <>
            <label>
              <span className="eyebrow">{t('pipeline.epcDate')}<span className="req" aria-hidden="true">*</span></span>
              <input className="field" type="date" value={gateForm.confirmed_on} aria-required="true"
                     onChange={(e) => setGateForm((f) => ({ ...f, confirmed_on: e.target.value }))} />
            </label>
            <label>
              <span className="eyebrow">{t('pipeline.epcSource')}</span>
              <select className="field" value={gateForm.source}
                      onChange={(e) => setGateForm((f) => ({ ...f, source: e.target.value }))}>
                <option value="ODOO">{t('pipeline.epcSourceOdoo')}</option>
                <option value="OTHER">{t('pipeline.epcSourceOther')}</option>
              </select>
            </label>
            {gateForm.source !== 'ODOO' ? (
              <label>
                <span className="eyebrow">{t('pipeline.epcReason')}<span className="req" aria-hidden="true">*</span></span>
                <textarea className="field" rows={2} value={gateForm.reason} aria-required="true"
                          onChange={(e) => setGateForm((f) => ({ ...f, reason: e.target.value }))} />
              </label>
            ) : null}
          </>
        )}
        {writeProblem ? <Problem problem={writeProblem} /> : null}
      </Drawer>
    </section>
  )
}

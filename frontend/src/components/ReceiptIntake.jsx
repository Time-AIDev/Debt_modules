import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { atLeast } from '../lib/identity.jsx'
import { date, int, money } from '../lib/format.js'
import { StatusIcon, StatusPill } from './StatusIcon.jsx'
import { Icon } from './Icon.jsx'
import { LoadError, Problem } from './Problem.jsx'
import { useToast } from './Toast.jsx'
import { ApplyDialog, Dropzone, Fig, FileInput, Progress, ReviewRows, RowSheet, runProblem } from './import/parts.jsx'
import { SchemaFeedback } from './import/SchemaFeedback.jsx'
import { isRunActive } from '../lib/operation.js'
import { RejectedDocuments } from './import/RejectedDocuments.jsx'

const PAGE = 100

/**
 * A durable FAILED run of either PEAK door (landing.import_run). Its note is
 * "<code>: <detail>"; a known code anywhere in it reads as words, else the note
 * shows as served — so an old OK run never looks like the whole story.
 */
export function FailedRun({ failed }) {
  const { t } = usePrefs()
  if (!failed) return null
  const code = (String(failed.note || '').match(/[a-z_]+/g) || [])
    .find((c) => t(`peak.failCode.${c}`) !== `peak.failCode.${c}`)
  const word = code ? t(`peak.failCode.${code}`) : failed.note || failed.meta?.door
  return (
    <p className="imp-peak__failed" title={failed.note || undefined}>
      <StatusIcon kind="problem" size={14} />
      {[t('data.runFailed'), failed.meta?.filename, word].filter(Boolean).join(' · ')}
    </p>
  )
}

/**
 * Q6 / TASK-213: the frequent upload — รายงานใบเสร็จรับเงิน. Same doors, watchable
 * run and apply as the invoice report; the file is read by the receipt parser and
 * only the settled/uncertain rows are shown. An unmatched row can be linked to a
 * customer the same way an unmatched invoice can. Design D: applying asks the same
 * confirmation as the invoice report. `modes` is PeakIntake's upload-mode switch.
 */
export function ReceiptIntake({ modes, schema }) {
  const { t } = usePrefs()
  const toast = useToast()
  const [last, setLast] = useState(null)
  const [lastProblem, setLastProblem] = useState(null)
  const [watchProblem, setWatchProblem] = useState(null)
  const [run, setRun] = useState(null)
  const [rowsBy, setRowsBy] = useState({ CANDIDATE: null, UNMATCHED: null })
  const [tab, setTab] = useState(null)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState(null)
  const [applied, setApplied] = useState(null)
  const [applyOpen, setApplyOpen] = useState(false)
  const [applyProblem, setApplyProblem] = useState(null)
  const [allowOlder, setAllowOlder] = useState(false)
  const [sheetRow, setSheetRow] = useState(null)
  const [sheetProblem, setSheetProblem] = useState(null)
  const fileRef = useRef(null)
  const uploadAbort = useRef(null)
  const [uploadTask, setUploadTask] = useState(null)

  const loadLast = useCallback(() => {
    setLastProblem(null)
    api.peakReceiptLastRun().then(setLast)
      .catch((error) => setLastProblem(error.problem || { code: 'request_failed', message_th: 'อ่านสถานะการนำเข้าใบเสร็จไม่ได้ กรุณาลองใหม่' }))
  }, [])
  const loadRows = useCallback((runId, verdict, offset = 0) => {
    if (!runId || !verdict) return
    api.peakReceiptRows(runId, { verdict, limit: PAGE, offset }).then((page) => {
      setRowsBy((prev) => ({
        ...prev,
        [verdict]: {
          rows: [...(offset > 0 ? (prev[verdict]?.rows || []) : []), ...(page.rows || [])],
          total: page.total ?? 0,
        },
      }))
    }).catch((e) => setProblem(e?.problem || { code: 'request_failed' }))
  }, [])

  useEffect(() => { loadLast() }, [loadLast])

  useEffect(() => {
    if (!isRunActive(run)) return undefined
    const timer = setInterval(() => {
      api.peakReceiptRun(run.uid).then((next) => {
        setWatchProblem(null)
        setRun(next)
        if (!isRunActive(next)) {
          loadLast()
          if (next.run_id) {
            loadRows(next.run_id, 'CANDIDATE')
            loadRows(next.run_id, 'UNMATCHED')
          }
        }
      }).catch((error) => setWatchProblem(error.problem || {
        code: 'request_failed', message_th: 'อ่านความคืบหน้าการนำเข้าไม่ได้ ระบบกำลังลองอ่านใหม่ ห้ามส่งไฟล์ซ้ำจนกว่าจะทราบผล',
      }))
    }, 2000)
    return () => clearInterval(timer)
  }, [run, loadLast, loadRows])

  async function start(file) {
    setBusy(true)
    setProblem(null)
    setApplied(null)
    setRowsBy({ CANDIDATE: null, UNMATCHED: null })
    setTab(null)
    const controller = new AbortController()
    uploadAbort.current = controller
    setUploadTask({ phase: 'uploading', uploadedBytes: 0, totalBytes: file.size })
    try {
      const started = await api.peakReceiptStart(file, {
        signal: controller.signal, onProgress: setUploadTask,
      })
      setRun(started)
      setUploadTask(started)
      if (!isRunActive(started) && started.run_id) {
        loadRows(started.run_id, 'CANDIDATE')
        loadRows(started.run_id, 'UNMATCHED')
        loadLast()
      }
      toast(t('peak.receiptStarted'))
    } catch (e) {
      if (e?.name === 'AbortError') return
      setProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  async function cancelRun() {
    uploadAbort.current?.abort()
    if (run?.uid && isRunActive(run)) {
      try { setRun(await api.cancelOperationRun(run.uid)) } catch (e) {
        setProblem(e?.problem || { code: 'request_failed' })
      }
    }
    setUploadTask(null)
  }

  const appliedRun = applied?.run || last?.applied
  // Defect 10: the server's own record of a finished watch run carries the figures.
  const record = (id) => [last?.staged, appliedRun].find((r) => r && r.id === id)
  const staged = run ? (run.state === 'done' ? (record(run.run_id) || run) : null) : (last?.staged || null)
  const manifest = staged || appliedRun
  const stagedId = staged ? (staged.run_id ?? staged.id) : null
  // target/07: the unmatched list belongs to the receipt report in use as much as to
  // a staged one — an applied run still has rows to review and link.
  const reviewId = stagedId || appliedRun?.id || null
  const alreadyApplied = !!(stagedId && appliedRun && appliedRun.id === stagedId)
  const waiting = !!(staged && !alreadyApplied)

  // A run read back from the server (staged or in use): its rows are not in this tab's
  // memory, so the unmatched list would sit on "loading" without this.
  useEffect(() => {
    if (run || !reviewId) return
    loadRows(reviewId, 'CANDIDATE')
    loadRows(reviewId, 'UNMATCHED')
  }, [run, reviewId, loadRows])

  async function apply() {
    setBusy(true)
    setApplyProblem(null)
    try {
      const result = await api.peakReceiptApply(stagedId, {
        ...(atLeast('MANAGER') && allowOlder ? { allow_older: true } : {}),
        ...((staged?.meta?.review_state_version || run?.review_state_version) ? {
          review_state_version: staged?.meta?.review_state_version || run?.review_state_version,
        } : {}),
      })
      setApplied(result)
      setApplyOpen(false)
      toast(t('peak.appliedToast'))
      loadLast()
    } catch (e) {
      setApplyProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  async function linkRow(row, customerNo, reason) {
    const code = row.contact_code || row.reference
    if (!code || !customerNo) return
    setBusy(true)
    setSheetProblem(null)
    try {
      await api.peakLinkConfirm({ contact_code: code, customer_no: customerNo, reason: reason || undefined })
      toast(t('peak.linkedToast'))
      setSheetRow(null)
      if (reviewId) {
        loadRows(reviewId, 'CANDIDATE')
        loadRows(reviewId, 'UNMATCHED')
      }
    } catch (e) {
      setSheetProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  const meta = manifest?.meta || {}
  const counts = manifest?.row_counts || {}
  const reading = isRunActive(run) || (!!busy && !!uploadTask)
  const readDone = run?.total ? (run.landed || 0) : (run?.read || 0)
  let progress
  if (run?.phase === 'queued' || run?.phase === 'reading') {
    progress = {
      done: 0,
      total: null,
      indeterminate: true,
      text: t(`peak.receiptPhase.${run.phase}`),
    }
  } else if (run?.phase === 'matching') {
    progress = {
      done: run.processed,
      total: run.phase_total,
      text: t('peak.receiptPhase.matching', { processed: int(run.processed), total: int(run.phase_total) }),
    }
  } else if (run?.phase === 'writing') {
    progress = {
      done: run.landed,
      total: run.total ?? run.phase_total,
      text: t('peak.receiptPhase.writing', {
        processed: int(run.landed), total: int(run.total ?? run.phase_total),
      }),
    }
  } else {
    progress = {
      done: readDone,
      total: run?.total,
      text: t('peak.receiptProgress', { read: int(readDone), total: int(run?.total) }),
    }
  }
  const asOf = meta.report_as_of ?? manifest?.report_as_of
  const receipts = manifest?.receipts ?? counts.landed
  const matched = meta.matched ?? manifest?.matched
  const candidates = meta.candidates ?? manifest?.candidates ?? 0
  const unmatched = meta.unmatched ?? manifest?.unmatched ?? 0
  const rejected = counts.rejected ?? manifest?.rejected ?? 0
  const activeTab = tab || (Number(candidates) > 0 ? 'CANDIDATE' : 'UNMATCHED')
  const reviewTabs = [
    { id: 'CANDIDATE', label: t('peak.tabCandidates'), n: candidates },
    { id: 'UNMATCHED', label: t('peak.tabUnmatched'), n: unmatched },
  ]

  return (
    <>
      <div className="imp-peak__top" id="peak-receipt">
        <div className="imp-peak__bar">
          {modes}
          <span className="spacer" />
          <button type="button" className="btn" disabled={busy || reading} onClick={() => fileRef.current?.click()}>
            <Icon name="upload" />{t('peak.upload')}
          </button>
          {waiting ? (
            <button type="button" className="btn btn--primary" disabled={busy || !!lastProblem}
                    onClick={() => { setApplyProblem(null); setAllowOlder(false); setApplyOpen(true) }}>
              {t('peak.apply')}
            </button>
          ) : alreadyApplied ? <StatusPill kind="done">{t('peak.applied')}</StatusPill> : null}
        </div>
        {lastProblem ? <LoadError problem={lastProblem} onRetry={loadLast} /> : null}
        {watchProblem ? <Problem problem={watchProblem} /> : null}
        <FileInput inputRef={fileRef} label={t('peak.chooseReceipt')} disabled={busy || reading} onFile={start} />
        <p className="imp-peak__report">
          <span className="eyebrow">{t('peak.uploadReceipt')}</span>
          {appliedRun?.meta?.report_as_of ? (
            <StatusPill kind="done">{t('peak.lastApplied', {
              on: date(appliedRun.meta.report_as_of), by: appliedRun.meta.applied?.by || '—',
            })}</StatusPill>
          ) : <StatusPill kind="idle">{t('peak.never')}</StatusPill>}
          {waiting ? <StatusPill kind="do">{t('status.import.REPORT_STAGED')}</StatusPill> : null}
          {manifest ? <span className="num">{asOf ? t('peak.reportOn', { on: date(asOf) }) : t('peak.reportUndated')}</span> : null}
        </p>
        {applied ? (
          <div className="imp-peak__result" role="status">
            <StatusIcon kind={applied.served === false ? 'problem' : 'done'} />
            <span className="imp-peak__resultText">
              <b>{t('peak.receiptApplied')}</b>
              <span>{applied.served === false ? (applied.note_th || applied.note_en) : t('peak.sessionNote')}</span>
              {applied.reconciliation ? (
                <>
                  <span>{t('peak.claimReconciliation', {
                    confirmed: int(applied.reconciliation.claims_confirmed),
                    partial: int(applied.reconciliation.claims_partially_confirmed),
                    review: int(applied.reconciliation.claims_needs_review),
                  })}</span>
                  <span>{t('peak.amountReconciliation', {
                    allocated: money(applied.reconciliation.allocated_to_invoices),
                    credit: money(applied.reconciliation.customer_credit),
                  })}</span>
                </>
              ) : null}
            </span>
          </div>
        ) : null}
        {reading ? (
          <Progress {...(uploadTask?.phase === 'uploading' ? {
            done: uploadTask.uploadedBytes, total: uploadTask.totalBytes,
            text: t('upload.phase.uploading', { done: int(uploadTask.uploadedBytes), total: int(uploadTask.totalBytes) }),
          } : progress)} onCancel={cancelRun} cancelLabel={t('common.cancel')} />
        ) : (
          <Dropzone text={t('peak.receiptDropHint')} hint={t('peak.dropHint')} disabled={busy}
                    onPick={() => fileRef.current?.click()} onFile={start} />
        )}
        <SchemaFeedback contract={schema}
                        diagnostics={meta.schema || problem?.extensions?.schema || run?.problem?.schema || run?.problem?.extensions?.schema} />
        <FailedRun failed={last?.failed} />
        {run?.state === 'failed' ? <Problem problem={runProblem(t('peak.failed'), run.problem)} /> : null}
        <Problem problem={problem} />
      </div>

      {manifest && !reading ? (
        <div className="imp-figs">
          <Fig label={t('peak.linesRead')} value={int(meta.source_read ?? counts.read)} />
          <Fig label={t('peak.receiptsRead')} value={int(receipts)} />
          <Fig label={t('peak.settled')} value={int(matched)} />
          <Fig label={t('peak.receiptOnly')} value={int(manifest.receipt_only ?? run?.receipt_only ?? 0)} />
          {rejected ? <Fig label={t('peak.rejected')} kind="problem" value={int(rejected)} /> : null}
          {reviewId ? (
            <>
              <span className="imp-figs__rule" aria-hidden="true" />
              <div className="imp-figs__tabs" role="tablist" aria-label={t('peak.reviewLabel')}>
                {reviewTabs.map((item) => (
                  <button key={item.id} type="button" role="tab" aria-selected={activeTab === item.id}
                          className={`imp-figs__tab${activeTab === item.id ? ' imp-figs__tab--on' : ''}`}
                          onClick={() => setTab(item.id)}>
                    <span className="imp-figs__label"><StatusIcon kind="do" size={14} />{item.label}</span>
                    <span className="imp-figs__value num">{int(item.n)}</span>
                  </button>
                ))}
              </div>
            </>
          ) : null}
        </div>
      ) : null}

      {manifest && !reading && reviewId ? (
        <ReviewRows page={rowsBy[activeTab]} busy={busy} current={sheetRow?.doc_no}
                    empty={activeTab === 'CANDIDATE' ? t('peak.noCandidates') : t('peak.noUnmatched')}
                    onOpen={(r) => { setSheetProblem(null); setSheetRow(r) }}
                    onMore={() => loadRows(reviewId, activeTab, (rowsBy[activeTab]?.rows || []).length)} />
      ) : null}

      {rejected > 0 && reviewId && !reading ? <RejectedDocuments key={reviewId} runId={reviewId} /> : null}

      {sheetRow ? (
        <RowSheet key={sheetRow.doc_no} row={sheetRow} busy={busy} problem={sheetProblem}
                  onClose={() => setSheetRow(null)} onLink={linkRow} />
      ) : null}
      <ApplyDialog
        open={applyOpen}
        title={asOf ? t('peak.applyDialog', { on: date(asOf) }) : t('peak.apply')}
        facts={[t('peak.receiptCounts', { receipts: int(receipts), matched: int(matched) })]}
        busy={busy}
        problem={applyProblem}
        allowOlder={allowOlder}
        onAllowOlder={setAllowOlder}
        onClose={() => setApplyOpen(false)}
        onConfirm={apply}
      />
    </>
  )
}

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { atLeast } from '../lib/identity.jsx'
import { date, when, int } from '../lib/format.js'
import { runStatus } from '../lib/status.js'
import { StatusIcon, StatusPill } from './StatusIcon.jsx'
import { Icon } from './Icon.jsx'
import { LoadError, Problem } from './Problem.jsx'
import { SegmentedControl } from './SegmentedControl.jsx'
import { FailedRun, ReceiptIntake } from './ReceiptIntake.jsx'
import { ConflictList } from './ConflictList.jsx'
import { useToast } from './Toast.jsx'
import { ApplyDialog, ChangesDrawer, Dropzone, Fig, FileInput, Progress, ReviewRows, RowSheet, runProblem } from './import/parts.jsx'
import { SchemaFeedback } from './import/SchemaFeedback.jsx'
import { isRunActive } from '../lib/operation.js'

const PAGE = 100

/**
 * รายงานใบแจ้งหนี้ PEAK — the intake desk for the report the debt team exports from
 * PEAK. The backend door (routers/peak_pipeline.py) reads, matches and only proposes;
 * a person confirms the uncertain rows and applies. Applying moves every case's
 * system payment status, which is what makes this the monthly update.
 *
 * Design D: the figures are the review tabs, a row opens one side sheet, and applying
 * asks a confirmation. `onSummary` hands the แหล่งข้อมูล tile what it shows.
 */
export function PeakIntake({ onSummary }) {
  const { t } = usePrefs()
  const toast = useToast()

  const [last, setLast] = useState(null)
  const [lastProblem, setLastProblem] = useState(null)
  const [deskProblems, setDeskProblems] = useState({})
  const [watchProblem, setWatchProblem] = useState(null)
  const [conflictProblem, setConflictProblem] = useState(null)
  const [door, setDoor] = useState(null)
  const [schemas, setSchemas] = useState(null)
  const [run, setRun] = useState(null)
  const [rowsBy, setRowsBy] = useState({ CANDIDATE: null, UNMATCHED: null })
  const [tab, setTab] = useState('CANDIDATE')
  const [links, setLinks] = useState([])
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState(null)
  const [applyOpen, setApplyOpen] = useState(false)
  const [applyProblem, setApplyProblem] = useState(null)
  const [stale, setStale] = useState(false)
  const [changesOpen, setChangesOpen] = useState(false)
  const [allowOlder, setAllowOlder] = useState(false)
  const [applied, setApplied] = useState(null)
  const [repairId, setRepairId] = useState(null)
  const [sheetRow, setSheetRow] = useState(null)
  const [sheetProblem, setSheetProblem] = useState(null)
  const [conflictTick, setConflictTick] = useState(0)
  // Q6 / TASK-213: the two named manual uploads plus the (still closed) API door.
  const [upload, setUpload] = useState('invoice')
  const fileRef = useRef(null)
  const uploadAbort = useRef(null)
  const [uploadTask, setUploadTask] = useState(null)

  const loadLast = useCallback(() => {
    setLastProblem(null)
    api.peakReportLastRun().then(setLast)
      .catch((error) => setLastProblem(error.problem || { code: 'request_failed', message_th: 'อ่านสถานะการนำเข้าใบแจ้งหนี้ไม่ได้ กรุณาลองใหม่' }))
  }, [])
  const loadLinks = useCallback(() => {
    return api.peakLinks().then((d) => {
      setLinks(d?.links || [])
      setDeskProblems((previous) => ({ ...previous, links: null }))
    }).catch((error) => setDeskProblems((previous) => ({ ...previous, links: error.problem || {
      code: 'request_failed', message_th: 'อ่านรหัสจับคู่ PEAK ไม่ได้ กรุณาลองใหม่',
    } })))
  }, [])
  const loadDesk = useCallback(() => {
    loadLinks()
    api.peakReportDoors().then((d) => {
      setDoor((d?.doors || []).find((x) => x.door === 'api') || null)
      setDeskProblems((previous) => ({ ...previous, door: null }))
    }).catch((error) => setDeskProblems((previous) => ({ ...previous, door: error.problem || {
      code: 'request_failed', message_th: 'อ่านสถานะการเชื่อมต่อ PEAK ไม่ได้ กรุณาลองใหม่',
    } })))
    api.peakReportSchemas().then((d) => {
      setSchemas(d)
      setDeskProblems((previous) => ({ ...previous, schema: null }))
    }).catch((error) => setDeskProblems((previous) => ({ ...previous, schema: error.problem || {
      code: 'request_failed', message_th: 'อ่านรูปแบบไฟล์ PEAK ไม่ได้ กรุณาลองใหม่',
    } })))
  }, [loadLinks])
  const loadRows = useCallback((runId, verdict, offset = 0) => {
    if (!runId || !verdict) return
    api.peakReportRows(runId, { verdict, limit: PAGE, offset }).then((page) => {
      setRowsBy((prev) => ({
        ...prev,
        [verdict]: {
          rows: [...(offset > 0 ? (prev[verdict]?.rows || []) : []), ...(page.rows || [])],
          total: page.total ?? 0,
        },
      }))
    }).catch((e) => setProblem(e?.problem || { code: 'request_failed' }))
  }, [])

  useEffect(() => {
    loadLast()
    loadDesk()
  }, [loadLast, loadDesk])

  useEffect(() => {
    if (!isRunActive(run)) return undefined
    const timer = setInterval(() => {
      api.peakReportRun(run.uid).then((next) => {
        setWatchProblem(null)
        setRun(next)
        if (!isRunActive(next)) {
          loadLast()
          if (next.run_id) { loadRows(next.run_id, 'CANDIDATE'); loadRows(next.run_id, 'UNMATCHED') }
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
    const controller = new AbortController()
    uploadAbort.current = controller
    setUploadTask({ phase: 'uploading', uploadedBytes: 0, totalBytes: file.size })
    try {
      const started = await api.peakReportStart(file, {
        signal: controller.signal, onProgress: setUploadTask,
      })
      setRun(started)
      setUploadTask(started)
      if (!isRunActive(started) && started.run_id) {
        loadRows(started.run_id, 'CANDIDATE')
        loadRows(started.run_id, 'UNMATCHED')
        loadLast()
      }
      toast(t('peak.started'))
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
  // Defect 10: a finished watch run carries flat counts only, so the figures read the
  // server's own record of that run as soon as /last-run has it.
  const record = (id) => [last?.staged, appliedRun].find((r) => r && r.id === id)
  const staged = run ? (run.state === 'done' ? (record(run.run_id) || run) : null) : (last?.staged || null)
  const manifest = staged || appliedRun
  // A watch run carries `run_id`; a run read back from `/last-run` carries `id`.
  const stagedId = staged ? (staged.run_id ?? staged.id) : null
  // target/07: the review tabs (candidates, unmatched, conflicts, links) belong to the
  // report in use as much as to a staged one — an applied run is still reviewable.
  const reviewId = stagedId || appliedRun?.id || null
  const alreadyApplied = !!(stagedId && appliedRun && appliedRun.id === stagedId)
  const waiting = !!(staged && !alreadyApplied)

  // Q7 / TASK-214: the tab's served count and the apply confirmation's undecided
  // number, both from the conflicts page itself.
  const [conflictInfo, setConflictInfo] = useState(null)
  useEffect(() => {
    if (!reviewId) { setConflictInfo(null); return undefined }
    let alive = true
    setConflictProblem(null)
    api.peakConflicts(reviewId, { limit: 1 })
      .then((body) => { if (alive) setConflictInfo({ total: body.total ?? 0, undecided: body.undecided_fields ?? 0 }) })
      .catch((error) => { if (alive) setConflictProblem(error.problem || {
        code: 'request_failed', message_th: 'อ่านข้อมูลขัดแย้งของรายงานไม่ได้ กรุณาลองใหม่ก่อนนำไปใช้',
      }) })
    return () => { alive = false }
  }, [reviewId, applied, conflictTick])

  // Resume a staged-but-applied run read back from the server: its rows are not in
  // this tab's memory, so the lists would sit on "loading" forever without this.
  useEffect(() => {
    if (run || !reviewId) return
    loadRows(reviewId, 'CANDIDATE')
    loadRows(reviewId, 'UNMATCHED')
  }, [run, reviewId, loadRows])

  const STALE_CODES = ['state_conflict', 'preview_stale']

  async function applyReport(force = false, reason = '') {
    setBusy(true)
    setApplyProblem(null)
    try {
      const result = await api.peakReportApply(stagedId, {
        ...(atLeast('MANAGER') && allowOlder ? { allow_older: true } : {}),
        ...(force ? { force_state_change: true, reason } : {}),
        ...((staged?.meta?.review_state_version || run?.review_state_version) ? {
          review_state_version: staged?.meta?.review_state_version || run?.review_state_version,
        } : {}),
      })
      setApplied(result)
      setStale(false)
      setRepairId(result.served === false ? stagedId : null)
      setApplyOpen(false)
      toast(t('peak.appliedToast'))
      loadLast()
    } catch (e) {
      const problem = e?.problem || { code: 'request_failed' }
      setApplyProblem(problem)
      setStale(STALE_CODES.includes(problem.code))
    } finally {
      setBusy(false)
    }
  }

  async function recheckReport() {
    if (!stagedId || busy) return
    setBusy(true)
    setApplyProblem(null)
    try {
      // Re-binds the staged run's fence to the version that stands now after the
      // rows/conflicts have been read again (loadLast re-reads the run's meta).
      await api.peakReportRecheck(stagedId)
      setStale(false)
      loadLast()
      loadRows(stagedId, 'CANDIDATE')
      loadRows(stagedId, 'UNMATCHED')
      setConflictTick((n) => n + 1)
      toast(t('peak.rechecked'))
    } catch (e) {
      setApplyProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  async function repairServed() {
    if (!repairId) return
    setBusy(true)
    setProblem(null)
    try {
      const result = await api.peakReportRefreshServed(repairId)
      if (result.served !== false) {
        setRepairId(null)
        toast(t('data.repairServed') + ' ✓')
      }
      setApplied((a) => (a ? { ...a, served: result.served !== false } : a))
      loadLast()
    } catch (e) {
      setProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  const reloadReview = () => {
    loadLinks()
    if (reviewId) { loadRows(reviewId, 'CANDIDATE'); loadRows(reviewId, 'UNMATCHED') }
  }

  async function linkRow(row, customerNo, reason) {
    const code = row.contact_code || row.reference
    if (!code || !customerNo) return
    setBusy(true)
    setSheetProblem(null)
    try {
      await api.peakLinkConfirm({
        contact_code: code,
        customer_no: customerNo,
        reason: reason || undefined,
      })
      toast(t('peak.linkedToast'))
      setSheetRow(null)
      reloadReview()
    } catch (e) {
      setSheetProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  async function retireLink(uid) {
    setBusy(true)
    setProblem(null)
    try {
      await api.peakLinkRetire(uid, {})
      toast(t('peak.retiredToast'))
      reloadReview()
    } catch (e) {
      setProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  const meta = manifest?.meta || {}
  const counts = manifest?.row_counts || {}
  const reading = isRunActive(run) || (!!busy && !!uploadTask)
  // Defect 10: the write phase counts what has landed, so the bar moves instead of
  // sitting at "n / n" until the run ends.
  const readDone = run?.total ? (run.landed || 0) : (run?.read || 0)
  const asOf = meta.report_as_of ?? manifest?.report_as_of
  const covers = meta.covers_from && meta.covers_to
    ? t('peak.covers', { from: date(meta.covers_from), to: date(meta.covers_to) }) : null
  const inUseOn = appliedRun?.meta?.report_as_of
  const cand = meta.candidates ?? manifest?.candidates
  const unm = meta.unmatched ?? manifest?.unmatched
  const rejected = counts.rejected ?? manifest?.rejected ?? 0
  const reportText = !manifest ? null : [
    asOf ? t(waiting ? 'peak.reportNew' : 'peak.inUse', { on: date(asOf) }) : t('peak.reportUndated'),
    covers,
    waiting && inUseOn ? t('peak.inUse', { on: date(inUseOn) }) : null,
  ].filter(Boolean).join(' · ')

  // What the แหล่งข้อมูล tile shows for PEAK (primitives, so the effect runs on change only).
  const readingKind = reading ? runStatus(
    'running', uploadTask?.phase === 'uploading' ? uploadTask.uploadedBytes : readDone,
    uploadTask?.phase === 'uploading' ? uploadTask.totalBytes : run?.total,
  ).kind : null
  const never = !manifest
  useEffect(() => {
    onSummary?.({ readingKind, waiting, never, cand, unm, asOf })
  }, [onSummary, readingKind, waiting, never, cand, unm, asOf])

  const modes = (
    <SegmentedControl
      label={t('peak.uploadMode')}
      value={upload}
      onChange={setUpload}
      options={[
        { id: 'invoice', label: t('peak.uploadInvoice') },
        { id: 'receipt', label: t('peak.uploadReceipt') },
        {
          id: 'api',
          label: t('peak.uploadApi'),
          disabled: true,
          title: door?.state === 'untested' ? t('peak.apiUntested') : t('peak.apiNotConfigured'),
        },
      ]}
    />
  )

  if (upload === 'receipt') {
    return <div className="imp-peak" id="peak-report">
      {Object.entries(deskProblems).filter(([, value]) => value).map(([key, value]) => <LoadError key={key} problem={value} onRetry={loadDesk} />)}
      <ReceiptIntake modes={modes} schema={schemas?.receipt} />
    </div>
  }

  const tabs = [
    { id: 'CANDIDATE', label: t('peak.tabCandidates'), kind: 'do', n: cand },
    { id: 'UNMATCHED', label: t('peak.tabUnmatched'), kind: 'do', n: unm },
    { id: 'CONFLICTS', label: t('status.import.CONFLICT'), kind: conflictInfo?.undecided ? 'do' : 'done', n: conflictInfo?.total ?? 0 },
    { id: 'LINKS', label: t('peak.tabLinks'), kind: 'done', n: links.length },
  ]

  return (
    <div className="imp-peak" id="peak-report">
      {lastProblem ? <LoadError problem={lastProblem} onRetry={loadLast} /> : null}
      {Object.entries(deskProblems).filter(([, value]) => value).map(([key, value]) => <LoadError key={key} problem={value} onRetry={loadDesk} />)}
      {conflictProblem ? <LoadError problem={conflictProblem} onRetry={() => setConflictTick((current) => current + 1)} /> : null}
      {watchProblem ? <Problem problem={watchProblem} /> : null}
      <div className="imp-peak__top">
        <div className="imp-peak__bar">
          {modes}
          <span className="spacer" />
          <button type="button" className="btn" disabled={busy || reading} onClick={() => fileRef.current?.click()}>
            <Icon name="upload" />{t('peak.upload')}
          </button>
          {waiting ? (
            <button type="button" className="btn btn--primary" disabled={busy || !!lastProblem || !!conflictProblem}
                    onClick={() => { setApplyProblem(null); setStale(false); setAllowOlder(false); setApplyOpen(true) }}>
              {t('peak.apply')}
            </button>
          ) : alreadyApplied ? <StatusPill kind="done">{t('peak.applied')}</StatusPill> : null}
        </div>
        <FileInput inputRef={fileRef} label={t('peak.choose')} disabled={busy || reading} onFile={start} />
        <p className="imp-peak__report">
          {never ? <StatusPill kind="idle">{t('peak.never')}</StatusPill> : null}
          {waiting ? <StatusPill kind="do">{t('status.import.REPORT_STAGED')}</StatusPill> : null}
          {reportText ? <span className="num">{reportText}</span> : null}
        </p>
        {applied ? (
          <div className="imp-peak__result" role="status">
            <StatusIcon kind={applied.served === false ? 'problem' : 'done'} />
            <span className="imp-peak__resultText">
              <b>{t('peak.moved', { n: int(applied.moved_cases ?? 0) })}</b>
              <span>{applied.served === false ? (applied.note_th || applied.note_en) : t('peak.sessionNote')}</span>
              {applied.served === false ? (
                <button type="button" className="btn btn--sm" disabled={busy} onClick={repairServed}>{t('data.repairServed')}</button>
              ) : null}
            </span>
          </div>
        ) : null}
        {reading ? (
          <Progress done={uploadTask?.phase === 'uploading' ? uploadTask.uploadedBytes : readDone}
                    total={uploadTask?.phase === 'uploading' ? uploadTask.totalBytes : run?.total}
                    indeterminate={!run?.total && uploadTask?.phase !== 'uploading'}
                    onCancel={cancelRun} cancelLabel={t('common.cancel')}
                    text={uploadTask?.phase === 'uploading'
                      ? t('upload.phase.uploading', { done: int(uploadTask.uploadedBytes), total: int(uploadTask.totalBytes) })
                      : t('peak.progress', { read: int(readDone), total: int(run?.total) })} />
        ) : (
          <Dropzone text={t('peak.dropLine')} hint={t('peak.dropHint')} disabled={busy}
                    onPick={() => fileRef.current?.click()} onFile={start} />
        )}
        <SchemaFeedback contract={schemas?.invoice}
                        diagnostics={meta.schema || problem?.extensions?.schema || run?.problem?.schema || run?.problem?.extensions?.schema} />
        <FailedRun failed={last?.failed} />
        {run?.state === 'failed' ? <Problem problem={runProblem(t('peak.failed'), run.problem)} /> : null}
        <Problem problem={problem} />
      </div>

      {manifest && !reading ? (
        <div className="imp-figs">
          <Fig label={t('peak.linesRead')} value={int(counts.read)} />
          <Fig label={t('peak.invoices')} value={int(counts.landed ?? manifest.invoices)} />
          <Fig label={t('peak.matched')} kind="done" value={int(meta.matched ?? manifest.matched)} />
          {rejected ? <Fig label={t('peak.rejected')} kind="problem" value={int(rejected)} /> : null}
          {reviewId ? (
            <>
              <span className="imp-figs__rule" aria-hidden="true" />
              <div className="imp-figs__tabs" role="tablist" aria-label={t('peak.reviewLabel')}>
                {tabs.map((x) => (
                  <button key={x.id} type="button" role="tab" aria-selected={tab === x.id}
                          className={`imp-figs__tab${tab === x.id ? ' imp-figs__tab--on' : ''}`}
                          onClick={() => setTab(x.id)}>
                    <span className="imp-figs__label"><StatusIcon kind={x.kind} size={14} />{x.label}</span>
                    <span className="imp-figs__value num">{int(x.n)}</span>
                  </button>
                ))}
              </div>
            </>
          ) : null}
        </div>
      ) : null}

      {manifest && !reading && reviewId ? (
        tab === 'LINKS' ? (
          <LinksList links={links} busy={busy} onRetire={retireLink} />
        ) : tab === 'CONFLICTS' ? (
          <ConflictList runId={reviewId} busy={busy} onChanged={() => { loadLast(); setConflictTick((n) => n + 1) }} />
        ) : (
          <ReviewRows page={rowsBy[tab]} busy={busy} current={sheetRow?.doc_no}
                      empty={tab === 'CANDIDATE' ? t('peak.noCandidates') : t('peak.noUnmatched')}
                      onOpen={(r) => { setSheetProblem(null); setSheetRow(r) }}
                      onMore={() => loadRows(reviewId, tab, (rowsBy[tab]?.rows || []).length)} />
        )
      ) : null}

      {sheetRow ? (
        <RowSheet key={sheetRow.doc_no} row={sheetRow} busy={busy} problem={sheetProblem}
                  onClose={() => setSheetRow(null)} onLink={linkRow} />
      ) : null}
      <ApplyDialog
        open={applyOpen}
        title={asOf ? t('peak.applyDialog', { on: date(asOf) }) : t('peak.apply')}
        facts={[
          [t('peak.applyCounts', { invoices: int(counts.landed ?? manifest?.invoices), matched: int(meta.matched ?? manifest?.matched) }),
            inUseOn ? t('peak.inUse', { on: date(inUseOn) }) : null].filter(Boolean).join(' · '),
          conflictInfo ? t('peak.applyDefaults', { n: int(conflictInfo.undecided) }) : null,
        ]}
        busy={busy}
        problem={applyProblem}
        stale={stale}
        allowOlder={allowOlder}
        onAllowOlder={setAllowOlder}
        onRecheck={recheckReport}
        onShowChanges={() => setChangesOpen(true)}
        onForce={(reason) => applyReport(true, reason)}
        onClose={() => setApplyOpen(false)}
        onConfirm={() => applyReport()}
      />
      <ChangesDrawer open={changesOpen} runId={reviewId} onClose={() => setChangesOpen(false)} />
    </div>
  )
}

/** ผูกแล้ว: every active link in the register (not only this run's), each retirable. */
function LinksList({ links, busy, onRetire }) {
  const { t } = usePrefs()
  if (!links.length) return <p className="empty">{t('peak.noLinks')}</p>
  return (
    <div className="imp-rows">
      <div className="imp-links__grid imp-rows__head">
        <span /><span>{t('peak.colCode')}</span><span>{t('peak.colLinkedTo')}</span><span>{t('peak.colLinkedBy')}</span><span />
      </div>
      {links.map((l) => (
        <div key={l.uid} className="imp-links__grid imp-links__row">
          <StatusIcon kind="done" />
          <span className="num imp-links__code">{l.contact_code}</span>
          <span className="num">→ {l.customer_no}</span>
          <span className="imp-links__meta">
            {t('peak.linkedBy', { who: l.confirmed_by || '—', on: when(l.confirmed_at) })}
            {l.reason ? ` · ${l.reason}` : ''}
          </span>
          <span className="imp-links__act">
            <button type="button" className="btn btn--quiet btn--sm" disabled={busy} onClick={() => onRetire(l.uid)}>
              <Icon name="unlink" size={14} />{t('peak.retire')}
            </button>
          </span>
        </div>
      ))}
    </div>
  )
}

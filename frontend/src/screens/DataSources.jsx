import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useIdentity, atLeast } from '../lib/identity.jsx'
import { useCrumb } from '../lib/crumb.jsx'
import { refreshImports, useDataState, useReloadOnEpoch } from '../lib/dataEpoch.jsx'
import { date, dateShort, when, int } from '../lib/format.js'
import { connectionStatus, importStatus, reconStatus, rungStatus, runStatus } from '../lib/status.js'
import { StatusIcon, StatusPill } from '../components/StatusIcon.jsx'
import { Icon } from '../components/Icon.jsx'
import { Popover } from '../components/Popover.jsx'
import { PeakIntake } from '../components/PeakIntake.jsx'
import { ImportPreview } from '../components/ImportPreview.jsx'
import { Problem, LoadError } from '../components/Problem.jsx'
import { useToast } from '../components/Toast.jsx'
import { Dropzone, FileInput, OperationProgress, Progress, codeWord, runProblem } from '../components/import/parts.jsx'
// The sheet install's own confirm (its own name, so it never leans on another panel's import).
import { ConfirmDialog as InstallConfirm } from '../components/ConfirmDialog.jsx'
import { internalOrigin, recordState } from '../lib/origin.js'
import { isRunActive } from '../lib/operation.js'

const hm = (iso) => /T(\d{2}:\d{2})/.exec(String(iso || ''))?.[1] || ''
const stamp = (iso) => [date(iso), hm(iso)].filter(Boolean).join(' ')
// A served sentence's ISO stamps ("2026-09-24T06:41:00+00:00", "2026-09-24") read dd/mm/yyyy [hh:mm].
const human = (text) => String(text || '').replace(/\d{4}-\d{2}-\d{2}(?:T[\d:.]+(?:Z|[+-]\d{2}:?\d{2})?)?/g, (m) => stamp(m))
// "PEAK UAT is not reachable: ConnectError" → "ConnectError".
const probeWhy = (reason) => /:\s*([\w.]+)\s*$/.exec(String(reason || ''))?.[1] || reason || '—'

function Figure({ label, value }) {
  return (
    <div className="imp__fig">
      <span className="imp__figLabel">{label}</span>
      <span className="imp__figValue num">{value}</span>
    </div>
  )
}

function Tile({ id, on, title, status, big, meta, sub, onPick }) {
  const { t } = usePrefs()
  return (
    <button type="button" className={`imp__tile${on ? ' imp__tile--on' : ''}`} aria-pressed={on} onClick={() => onPick(id)}>
      <span className="imp__tileHead">
        <span className="imp__tileTitle">{title}</span>
        {status ? <StatusPill kind={status.kind}>{t(status.key)}</StatusPill> : null}
      </span>
      <span className="imp__tileBig"><span className="imp__tileNum num">{big}</span><span className="imp__tileMeta">{meta}</span></span>
      <span className="imp__tileSub">{sub}</span>
    </button>
  )
}

/**
 * แหล่งข้อมูล, design D: four source tiles say how each source is doing and select the
 * panel below (PEAK by default); one right column holds the source order, the
 * connections and "Sync Odoo" (the crm.lead pull — the sale.order sync and the
 * source switches went on 2026-09-25); PEAK decisions open in a side sheet.
 */
export function DataSources() {
  const { t, served } = usePrefs()
  useIdentity()
  const toast = useToast()
  const location = useLocation()
  const dataState = useDataState()
  useCrumb('group.system', 'nav.data')

  const [overview, setOverview] = useState(null)
  const [integrations, setIntegrations] = useState(null)
  const [problem, setProblem] = useState(null)
  const [crmLast, setCrmLast] = useState(null)
  const [crmSchedule, setCrmSchedule] = useState(null)
  const [crmRun, setCrmRun] = useState(null)
  const [tile, setTile] = useState('peak')
  const [peak, setPeak] = useState(null)
  // Which act is running: pull · sheet · retest · refresh.
  const [busy, setBusy] = useState('')
  const [pullProblem, setPullProblem] = useState(null)
  const [retestProblem, setRetestProblem] = useState(null)
  const [sheet, setSheet] = useState(null)
  const [sheetProfile, setSheetProfile] = useState('debt_status')
  const [sheetProblem, setSheetProblem] = useState(null)
  const [allRefusals, setAllRefusals] = useState(false)
  const [allRuns, setAllRuns] = useState(false)
  const [disagree, setDisagree] = useState(null)
  const [disagreeProblem, setDisagreeProblem] = useState(null)
  const [askInstall, setAskInstall] = useState(false)
  const [installProblem, setInstallProblem] = useState(null)
  const [infoOpen, setInfoOpen] = useState(false)
  const [refreshProblem, setRefreshProblem] = useState(null)
  const sheetRef = useRef(null)
  const refusalsRef = useRef(null)
  const sheetAbort = useRef(null)
  const [sheetTask, setSheetTask] = useState(null)

  const load = useCallback(() => {
    setProblem(null)
    // One request for the whole screen (migration + integrations + crm + peak state);
    // it mounted with seven before. The single endpoints remain for other callers.
    api.dataSourcesOverview()
      .then((d) => {
        setOverview(d)
        setIntegrations(d.integrations)
        setCrmLast(d.crm?.last || null)
        setCrmSchedule(d.crm?.schedule || null)
      })
      .catch((e) => setProblem(e?.problem || { code: 'request_failed' }))
  }, [])
  const loadCrm = useCallback(() => {
    api.crmLeadLastRun().then(setCrmLast).catch(() => setCrmLast(null))
    api.crmLeadSchedule().then(setCrmSchedule).catch(() => setCrmSchedule(null))
  }, [])
  useEffect(() => { load() }, [load])
  useEffect(() => { loadCrm() }, [loadCrm])
  useReloadOnEpoch(load)

  // The watchable run (2026-09-11 design): the one started here, or the served latest
  // one (the 2-hour timer's). The served `watch` is the latest crm.lead pull; the
  // kind is still checked, as the registry is shared with the PEAK runs. Poll only
  // while it is running, and pull the receipt + the book once when it leaves that state.
  const latest = crmLast?.watch
  const crmWatch = crmRun || (latest?.kind === 'odoo' ? latest : null)
  const odooNotConfigured = overview?.integrations?.odoo?.configured === false
  useEffect(() => {
    if (!isRunActive(crmWatch)) return undefined
    const timer = setInterval(() => {
      api.crmLeadRun(crmWatch.uid).then((next) => {
        setCrmRun(next)
        if (!isRunActive(next)) { loadCrm(); load() }
      }).catch(() => {})
    }, 2000)
    return () => clearInterval(timer)
  }, [crmWatch, loadCrm, load])

  async function act(kind, fn, onProblem) {
    setBusy(kind)
    onProblem(null)
    try {
      await fn()
    } catch (e) {
      if (e?.name === 'AbortError') return
      onProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy('')
    }
  }

  const pullCrmLead = () => act('pull', async () => {
    const started = await api.startCrmLeadPipeline('NEW_ONLY')
    setCrmRun(started)
    toast(t('data.crmLeadStarted'))
  }, setPullProblem)

  // "ทดสอบอีกครั้ง": the status read probes PEAK live, so reading it again is the test.
  const retest = () => act('retest', async () => {
    const next = await api.integrationsStatus()
    setIntegrations(next)
    const probe = next?.peak?.probe
    toast(probe?.reachable ? t('data.reachable') : t('data.retestFailed', { why: probeWhy(probe?.reason) }))
  }, setRetestProblem)

  const checkFile = (file) => act('sheet', async () => {
    setSheet(null)
    setAllRefusals(false)
    const controller = new AbortController()
    sheetAbort.current = controller
    setSheetTask({ phase: 'uploading', uploadedBytes: 0, totalBytes: file.size })
    const run = await api.createImport(file, { signal: controller.signal, onProgress: setSheetTask,
      ...(sheetProfile !== 'fullbook' ? { profile: sheetProfile } : {}) })
    setSheet({ run, file: file.name, raw: file })
    setSheetTask(null)
    toast(t('data.checked'))
    load()
  }, setSheetProblem)

  // The sheet's review list: where PEAK and the "done collection" tab disagree.
  const loadDisagree = useCallback(() => {
    setDisagreeProblem(null)
    api.sheetDisagreements().then(setDisagree).catch((e) => {
      setDisagree(null)                   // a failed read is never "nothing differs"
      setDisagreeProblem(e?.problem || { code: 'request_failed' })
    })
  }, [])
  useEffect(() => { if (tile === 'sheet') loadDisagree() }, [tile, loadDisagree])

  // Leg S (Arina 2026-09-24): the checked file becomes the book — a manager's act, asked
  // first with what it takes out of the book; the confirmed count travels with it.
  const installFile = () => act('install', async () => {
    const controller = new AbortController()
    sheetAbort.current = controller
    setSheetTask({ phase: 'uploading', uploadedBytes: 0, totalBytes: sheet.raw.size })
    const run = await api.installSheet(sheet.raw, sheet.run?.retire?.customers,
      { signal: controller.signal, onProgress: setSheetTask })
    setSheet({ ...sheet, run })
    setSheetTask(null)
    setAskInstall(false)
    toast(t('data.sheetInstalled', { customers: int(run.install?.customers) }))
    load()
    loadDisagree()
  }, setInstallProblem)

  const cancelSheet = () => {
    sheetAbort.current?.abort()
    setSheetTask((current) => current ? { ...current, phase: 'cancel_requested' } : current)
  }

  const cancelCrm = async () => {
    if (!crmWatch?.uid) return
    try { setCrmRun(await api.cancelOperationRun(crmWatch.uid)) } catch (e) {
      setPullProblem(e?.problem || { code: 'request_failed' })
    }
  }

  const refresh = () => act('refresh', async () => {
    await refreshImports()
    toast(t('data.refreshed'))
  }, setRefreshProblem)

  if (problem) return <LoadError problem={problem} onRetry={load} />
  if (!overview) return <p className="empty">{t('common.loading')}</p>

  const mgr = atLeast('MANAGER')
  const migration = overview.migration || {}
  const chain = migration.source_chain || {}
  const rungs = chain.rungs || []
  const counts = Object.entries(migration.counts || {}).filter(([, v]) => typeof v === 'number')
  const count = Object.fromEntries(counts)
  const rungName = (rung) => String(served(rung, 'name') || rung.code || '').replace(/\(SHEET\)$/, t('data.sheetSuffix'))
  const servingRung = rungs.find((r) => r.serving)
  const sourceName = servingRung ? rungName(servingRung) : chain.serving_name || '—'

  // Odoo crm.lead: the schedule, the running or failed run, the last landed run.
  const running = isRunActive(crmWatch)
  const crmFailed = crmWatch?.state === 'failed' ? (crmWatch.problem || {}) : null
  // last-run serves the newest durable failure only while no later pull succeeded.
  const durableFailed = crmLast?.failed
  const crmStat = running ? { kind: runStatus('running', crmWatch.read, crmWatch.total).kind, key: 'data.pulling' }
    : crmFailed || durableFailed ? { kind: 'problem', key: 'data.crmRunFailed' }
      : !crmSchedule ? null
        : importStatus(crmSchedule.odoo_configured === false || crmSchedule.enabled === false ? 'AUTO_OFF' : 'AUTO_ON')
  // Whole hours read as hours (2026-09-25: the sync runs every 2 hours).
  const everyText = (n) => (n % 60 === 0 ? t('data.autoSyncEveryHours', { n: n / 60 }) : t('data.autoSyncEvery', { n }))
  const nextAt = crmSchedule?.next_run_at
    ? new Date(crmSchedule.next_run_at * 1000).toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit' }) : null
  const schedText = !crmSchedule ? '' : crmSchedule.odoo_configured === false ? t('data.odooNotConfigured')
    : [everyText(crmSchedule.interval_minutes ?? 120), nextAt ? t('data.autoSyncNext', { at: nextAt }) : null]
      .filter(Boolean).join(' · ')
  const lastAt = crmLast?.run?.finished_at
  const rc = crmLast?.run?.row_counts || {}
  const byRule = Object.entries(crmLast?.receipt?.rejected_by_rule || {})
  const crmRuns = overview.crm?.runs || []
  // A durable run's note is "<code>: <class>"; a known code reads as words (as PeakIntake does).
  const failWord = (note) => {
    const code = (String(note || '').match(/[a-z_]+/g) || []).find((c) => t(`data.runProblem.${c}`) !== `data.runProblem.${c}`)
    return code ? t(`data.runProblem.${code}`) : note
  }

  // PEAK: what PeakIntake reports up.
  const peakStat = !peak ? null
    : peak.readingKind ? { kind: peak.readingKind, key: 'status.import.running' }
      : peak.waiting ? importStatus('REPORT_STAGED')
        : peak.never ? importStatus('RECEIPTS_NEVER')
          : importStatus((peak.cand || 0) + (peak.unm || 0) ? 'REVIEW' : 'REPORT_APPLIED')

  const sr = sheet?.run
  const sheetPreview = sr?.preview || sr?.result?.preview || sr?.result?.result?.preview
  // A PEAK-vs-sheet answer in words: a month is paid or late, the current row a payment status.
  const payWord = (code) => (code === 'PAID' ? t('status.cell.paid') : codeWord(t, 'pay.', code))
  // What installing the checked file would take out of the book (served by the check).
  const retire = sr?.retire
  const retireTabs = (retire?.dropped_tabs || []).map((k) => t(`data.sheetTab.${k}`)).join(', ')
  const tiles = [
    { id: 'book', title: t('data.tileBook'), status: importStatus('SERVING'), big: int(count.served),
      meta: t('data.people'), sub: t('data.tileBookSub', { source: sourceName }) },
    { id: 'odoo', title: 'Odoo crm.lead', status: crmStat, big: hm(lastAt) || '—',
      meta: lastAt ? t('data.lastAt', { on: dateShort(lastAt) }) : t('data.crmLeadNoRun'), sub: schedText },
    { id: 'peak', title: 'PEAK', status: peakStat,
      big: peak && !peak.never ? int((peak.cand || 0) + (peak.unm || 0)) : '—',
      meta: peak?.asOf ? t('data.asOf', { on: date(peak.asOf) }) : '',
      sub: t('data.peakTileSub', { cand: int(peak?.cand), unm: int(peak?.unm) }) },
    { id: 'sheet', title: t('data.sourceSheet'),
      status: sr?.installed ? importStatus('SERVING') : sr ? { kind: 'idle', key: 'data.sheetTileStaged' } : importStatus('RESERVE'),
      big: sr ? int(sr.counts?.rows_read) : '—', meta: sr ? t('data.sheetTileRows') : '',
      sub: sr?.installed ? t('data.sheetInstalled', { customers: int(sr.install?.customers) })
        : sr ? t('data.sheetTileSub', { imported: int(sr.counts?.rows_imported), refused: int(sr.counts?.rows_refused) })
          : t('data.sheetTileNone') },
  ]

  // Connections: Odoo, PEAK UAT (the live probe), and the PEAK API door.
  const odoo = integrations?.odoo || {}
  const peakInt = integrations?.peak || {}
  const probe = peakInt.probe
  const apiDoor = (overview.peak?.doors?.doors || []).find((d) => d.door === 'api')
  const conns = [
    { name: odoo.integration || 'Odoo', status: connectionStatus({ configured: odoo.configured }),
      note: odoo.snapshot?.synced_at ? t('data.lastAt', { on: stamp(odoo.snapshot.synced_at) }) : '' },
    { name: peakInt.integration || 'PEAK', status: connectionStatus({ configured: peakInt.configured, reachable: probe ? probe.reachable : undefined }),
      note: [peakInt.configured ? t('data.peakConfigured') : null,
        probe ? (probe.reachable ? t('data.reachable') : t('data.peakUnreachable', { name: peakInt.integration || 'PEAK', why: probeWhy(probe.reason) })) : null,
        String(peakInt.mode || '').startsWith('DRAFT_ONLY') ? t('data.peakDraftOnly') : null].filter(Boolean).join(' · '),
      retry: !!(peakInt.configured && probe && probe.reachable === false) },
    { name: t('peak.uploadApi'), status: apiDoor?.state === 'untested' ? { kind: 'idle', key: 'data.apiUntested' } : importStatus('NOT_CONFIGURED'),
      note: t('data.apiUseUpload') },
  ]

  const recon = (migration.reconciliation || []).slice(0, 8)
  const reconNotes = [...new Set(recon.map((r) => r.note).filter(Boolean))].map((n) => (
    n === 'odoo_no_money_pivots' ? t('data.noMoneyPivots') : n === 'export truncated per tab' ? t('data.exportTruncated') : n))
  const refusals = sr?.refusals || []
  const freshText = dataState ? t('data.freshness', {
    source: dataState.serving?.serving_name || '—', on: when(dataState.serving?.imported_at) || '—',
  }) : ''

  return (
    <div className="imp">
      <div className="imp__lens">
        <h1 className="imp__title">{t('data.title')}</h1>
        {dataState?.stale ? (
          <div className="imp__staleCol">
            <div className="imp__stale" role="status" title={freshText}>
              <StatusIcon kind="do" />
              <span>{t('data.staleBanner')}</span>
              <button type="button" className="btn btn--sm" disabled={busy === 'refresh'} onClick={refresh}>{t('data.staleRefresh')}</button>
            </div>
            <Problem problem={refreshProblem} />
          </div>
        ) : dataState ? (
          <p className="imp__fresh">
            {freshText}
            {dataState.peak_as_of ? (
              <>
                {' · '}
                <button type="button" className="imp__link" onClick={() => setTile('peak')}>
                  {t('today.peakAsOf', { on: date(dataState.peak_as_of) })}
                </button>
              </>
            ) : null}
          </p>
        ) : null}
        <span className="spacer" />
        <span className="info">
          <button type="button" className="btn btn--quiet" aria-expanded={infoOpen}
                  onMouseDown={(e) => { if (infoOpen) e.stopPropagation() }} onClick={() => setInfoOpen((v) => !v)}>
            <Icon name="info" />{t('data.howToRead')}
          </button>
          <Popover open={infoOpen} onClose={() => setInfoOpen(false)} label={t('data.howToRead')} width={320} as="span"
                   className="popover--info popover--right imp__notes">
            <b>{t('data.howToRead')}</b>
            <span>{t('data.crmLeadNote')}</span>
            <span>{t('data.importNote')}</span>
            <span>{t('peak.note')}</span>
          </Popover>
        </span>
      </div>

      <div className="imp__tiles">
        {tiles.map((x) => <Tile key={x.id} {...x} on={tile === x.id} onPick={setTile} />)}
      </div>

      <div className="imp__area">
        <section className="imp__main card" aria-label={tiles.find((x) => x.id === tile)?.title}>
          <div hidden={tile !== 'peak'}><PeakIntake onSummary={setPeak} /></div>

          {tile === 'book' ? (
            <div className="imp__pad">
              <div className="imp__head">
                <h2 className="imp__h2">{t('data.tileBook')}</h2>
                <StatusPill kind="done">{t('status.import.SERVING')}</StatusPill>
                <span className="imp__meta">{t('data.fromSource', { source: sourceName })}</span>
              </div>
              <div className="imp__figs imp__figs--5">
                {counts.map(([k, v]) => <Figure key={k} label={codeWord(t, 'data.count.', k)} value={int(v)} />)}
              </div>
              <div className="imp__subhead">
                <h3 className="imp__h3" title={t('data.reconciliationNote')}>{t('data.reconTitle')}</h3>
                <span className="spacer" />
                <Link to="/book" className="btn btn--sm"><Icon name="doc" />{t('data.openBook')}</Link>
              </div>
              {recon.length ? (
                <div className="imp__box imp__box--flush">
                  <table className="table">
                    <thead>
                      <tr>
                        <th scope="col" className="table__th">{t('data.reconStatus')}</th>
                        <th scope="col" className="table__th table__th--num">{t('data.reconSystem')}</th>
                        <th scope="col" className="table__th table__th--num">{t('data.reconSheet')}</th>
                        <th scope="col" className="table__th">{t('data.reconResult')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {recon.map((r, i) => {
                        const s = reconStatus(r)
                        return (
                          <tr key={r.payment_status || i}>
                            <td className="table__td">{r.payment_status ? codeWord(t, 'pay.', r.payment_status) : served(r, 'label') || r.code || '—'}</td>
                            <td className="table__td table__td--num">{int(r.imported)}</td>
                            <td className="table__td table__td--num">{int(r.sheet)}</td>
                            <td className="table__td"><StatusPill kind={s.kind}>{t(s.key)}</StatusPill></td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              ) : <p className="imp__meta">—</p>}
              {reconNotes.map((n) => <p key={n} className="imp__meta">{n}</p>)}
            </div>
          ) : null}

          {tile === 'odoo' ? (
            <div className="imp__pad">
              <div className="imp__head imp__head--act">
                <div className="imp__head">
                  <h2 className="imp__h2">Odoo crm.lead</h2>
                  {crmStat ? <StatusPill kind={crmStat.kind}>{t(crmStat.key)}</StatusPill> : null}
                  <span className="imp__meta">{schedText}</span>
                </div>
                <span className="spacer" />
                <span className="imp__act">
                  <button type="button" className="btn btn--primary" disabled={!!busy || !mgr || running || odooNotConfigured} onClick={pullCrmLead}
                          title={!mgr ? t('data.managerOnly') : running ? t('data.pullRunning')
                            : odooNotConfigured ? t('data.odooNotConfigured') : undefined}>
                    {t('data.crmLeadRun')}
                  </button>
                  {mgr ? null : <span className="imp__reason">{t('data.managerOnly')}</span>}
                </span>
              </div>
              {running ? (
                <Progress done={crmWatch.read ?? 0} total={crmWatch.total}
                          onCancel={cancelCrm} cancelLabel={t('common.cancel')}
                          text={t('data.crmLeadProgress', { read: int(crmWatch.read ?? 0), total: int(crmWatch.total) })} />
              ) : null}
              {odooNotConfigured ? <p className="imp__reason">{t('data.odooNotConfigured')}</p> : null}
              <Problem problem={pullProblem} />
              {crmFailed ? (
                <Problem problem={runProblem(t('data.crmRunFailed'), crmFailed,
                  t(`data.runProblem.${crmFailed.code}`) === `data.runProblem.${crmFailed.code}` ? null : t(`data.runProblem.${crmFailed.code}`))} />
              ) : durableFailed && !running ? (
                <p className="imp-peak__failed" title={durableFailed.note || undefined}>
                  <StatusIcon kind="problem" size={14} />
                  {[t('data.runFailed'), when(durableFailed.finished_at), failWord(durableFailed.note)].filter(Boolean).join(' · ')}
                </p>
              ) : null}
              <div className="imp__cols">
                <section className="imp__box">
                  <h3 className="imp__h3">{t('data.lastRunTitle')}</h3>
                  <dl className="kv">
                    <dt>{t('data.crmLeadLast')}</dt><dd className="num">{lastAt ? when(lastAt) : t('data.crmLeadNoRun')}</dd>
                    <dt>{t('data.rowsRead')}</dt><dd className="num">{int(rc.read)}</dd>
                    <dt>{t('data.rowsImported')}</dt><dd className="num">{int(rc.landed)}</dd>
                    <dt>{t('data.unchanged')}</dt><dd className="num">{int(crmLast?.receipt?.unchanged)}</dd>
                    <dt>{t('data.rowsRefused')}</dt><dd className="num">{int(rc.rejected)}</dd>
                    <dt>{t('data.duplicates')}</dt><dd className="num">{int(rc.duplicates)}</dd>
                  </dl>
                </section>
                {byRule.length ? (
                  <section className="imp__box">
                    <h3 className="imp__h3">{t('data.rejectTitle')}</h3>
                    <dl className="imp__rules">
                      {byRule.map(([code, n]) => (
                        <div key={code}><dt>{codeWord(t, 'data.rejectRule.', code)}</dt><dd className="num">{int(n)}</dd></div>
                      ))}
                    </dl>
                  </section>
                ) : null}
              </div>
              {crmRuns.length ? (
                <section className="imp__box">
                  <h3 className="imp__h3">{t('data.runsTitle')}</h3>
                  <ul className="imp__refusals" aria-label={t('data.runsTitle')}>
                    {crmRuns.slice(0, allRuns ? undefined : 5).map((r) => {
                      const s = importStatus(r.status === 'RUNNING' ? 'running' : r.status)
                      const m = r.meta || {}
                      return (
                        <li key={r.id}>
                          <StatusPill kind={s.kind}>{t(s.key)}</StatusPill>
                          <span className="num">{when(r.finished_at || r.started_at)}</span>
                          <span>{codeWord(t, 'data.door.', m.door)}</span>
                          <span className="num">{r.status === 'FAILED' ? failWord(r.note) : t('data.runCounts', {
                            new: int(m.new), changed: int(m.changed), unchanged: int(m.unchanged), retired: int(m.retired),
                          })}</span>
                        </li>
                      )
                    })}
                  </ul>
                  {crmRuns.length > 5 && !allRuns ? (
                    <button type="button" className="btn btn--quiet btn--sm" onClick={() => setAllRuns(true)}>
                      {t('data.showAllRefusals', { n: int(crmRuns.length) })}
                    </button>
                  ) : null}
                </section>
              ) : null}
            </div>
          ) : null}

          {tile === 'sheet' ? (
            <div className="imp__pad">
              <div className="imp__head imp__head--act">
                <h2 className="imp__h2">{t('data.sourceSheet')}</h2>
                <span className="spacer" />
                {sheetProfile === 'fullbook' ? <span className="imp__act">
                  <button type="button" className="btn btn--primary" disabled={!!busy || !mgr || !sr}
                          onClick={() => { setInstallProblem(null); setAskInstall(true) }}
                          title={!mgr ? t('data.managerOnly') : !sr ? t('data.sheetInstallFirst') : undefined}>
                    {t('data.sheetInstall')}
                  </button>
                  {mgr ? null : <span className="imp__reason">{t('data.managerOnly')}</span>}
                </span> : null}
              </div>
              <label className="label">{t('supplement.profileLabel')}
                <select className="field" value={sheetProfile} disabled={!!busy}
                  onChange={(e) => { setSheetProfile(e.target.value); setSheet(null); setSheetProblem(null) }}>
                  {['debt_status', 'contract_supplement', 'fullbook'].map((profile) => <option key={profile} value={profile}>
                    {t(`supplement.profile.${profile}`)}</option>)}
                </select>
              </label>
              <p className="scr-meta">{t(sheetProfile === 'fullbook' ? 'data.sheetInstallNote' : 'supplement.tabsNote')}</p>
              <InstallConfirm open={askInstall} onClose={() => setAskInstall(false)} onConfirm={installFile}
                              busy={busy === 'install'} danger={!!retire?.needs_confirm}
                              title={t('data.sheetInstall')} confirmLabel={t('data.sheetInstall')}>
                <p>{t('data.sheetInstallNote')}</p>
                {retire ? <p>{t('data.sheetRetireCount', { n: int(retire.customers), live: int(retire.live) })}</p> : null}
                {retireTabs ? <p>{t('data.sheetRetireTabs', { tabs: retireTabs })}</p> : null}
                <Problem problem={installProblem} />
              </InstallConfirm>
              {busy === 'sheet' || busy === 'install' ? (
                <OperationProgress task={sheetTask || { phase: 'parsing' }} onCancel={cancelSheet} />
              ) : (
                <Dropzone tall text={t('data.dropLine')} hint={t('data.dropHint')} disabled={!!busy}
                          onPick={() => sheetRef.current?.click()} onFile={checkFile} />
              )}
              <FileInput inputRef={sheetRef} label={t('data.chooseFile')} disabled={!!busy} onFile={checkFile} />
              <Problem problem={sheetProblem} />
              {sheetPreview ? <ImportPreview key={sheetPreview.uid} preview={sheetPreview} canApply={mgr}
                onApplied={() => { load(); refreshImports().catch(() => {}) }} /> : sr ? (
                <section className="imp__box imp__box--flush">
                  <div className="imp__receiptHead">
                    <h3 className="imp__h3">{t('data.receipt', { file: sheet.file })}</h3>
                    {sr.installed ? <StatusPill kind="done">{t('status.import.SERVING')}</StatusPill>
                      : <StatusPill kind="idle">{t('status.import.SHEET_STAGED')}</StatusPill>}
                  </div>
                  <div className="imp__receiptBody">
                    <div className="imp__figs imp__figs--4">
                      <Figure label={t('data.rowsRead')} value={int(sr.counts?.rows_read)} />
                      <Figure label={t('data.rowsImported')} value={int(sr.counts?.rows_imported)} />
                      <Figure label={t('data.rowsRefused')} value={int(sr.counts?.rows_refused)} />
                      <Figure label={t('data.customers')} value={int(sr.counts?.customers)} />
                    </div>
                    {sr.formula_cache?.rows > 0 ? (
                      <details className="imp__meta">
                        <summary>{t('data.formulaCacheMissing', { n: int(sr.formula_cache.rows) })}</summary>
                        <ul>{sr.formula_cache.sheets.map((tab) => (
                          <li key={tab.sheet}>{tab.sheet}: {Object.keys(tab.fields).join(', ')}</li>
                        ))}</ul>
                      </details>
                    ) : null}
                    {retire && !sr.installed ? (
                      <p className="imp__meta">
                        {t('data.sheetRetireCount', { n: int(retire.customers), live: int(retire.live) })}
                        {retireTabs ? ` · ${t('data.sheetRetireTabs', { tabs: retireTabs })}` : ''}
                      </p>
                    ) : null}
                    {sr.installed ? (
                      <div className="imp__figs imp__figs--4" aria-label={t('data.sheetInstalled', { customers: int(sr.install?.customers) })}>
                        <Figure label={t('data.customers')} value={int(sr.install?.customers)} />
                        <Figure label={t('data.sheetContracts')} value={int(sr.install?.contracts)} />
                        <Figure label={t('data.sheetTracked')} value={int(sr.install?.tracked)} />
                        <Figure label={t('data.sheetRetired')} value={int(sr.install?.retired)} />
                      </div>
                    ) : null}
                    {refusals.length ? (
                      <ul className="imp__refusals" aria-label={t('data.refusalsLabel')} ref={refusalsRef} tabIndex={-1}>
                        {refusals.slice(0, allRefusals ? undefined : 5).map((r, i) => (
                          <li key={i}>
                            <StatusIcon kind="problem" size={14} />
                            <span className="imp__refRow num" title={r.source_ref?.sheet != null ? String(r.source_ref.sheet) : undefined}>
                              {t('data.refusalRow', { n: r.source_ref?.row ?? r.row ?? r.line ?? '—' })}
                            </span>
                            <span>{served(r, 'message') || served(r, 'reason') || r.code}</span>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    {refusals.length > 5 && !allRefusals ? (
                      <span>
                        <button type="button" className="btn btn--quiet btn--sm"
                                onClick={() => { setAllRefusals(true); refusalsRef.current?.focus() }}>
                          {t('data.showAllRefusals', { n: int(refusals.length) })}
                        </button>
                      </span>
                    ) : null}
                  </div>
                </section>
              ) : null}
              <section className="imp__box imp__box--flush" aria-label={t('data.sheetDisagreeTitle')}>
                <div className="imp__receiptHead">
                  <h3 className="imp__h3" title={t('data.sheetDisagreeNote')}>{t('data.sheetDisagreeTitle')}</h3>
                </div>
                {disagreeProblem ? <Problem problem={disagreeProblem} /> : disagree?.rows?.length ? (
                  <table className="table">
                    <thead>
                      <tr>
                        <th scope="col" className="table__th">{t('data.customers')}</th>
                        <th scope="col" className="table__th">{t('data.sheetDisagreeMonth')}</th>
                        <th scope="col" className="table__th">PEAK</th>
                        <th scope="col" className="table__th">{t('data.reconSheet')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {disagree.rows.map((r) => (
                        <tr key={`${r.customer_uid}-${r.month || 'now'}`}>
                          <td className="table__td"><Link to={`/customers/${r.customer_uid}`} state={recordState(internalOrigin(location, 'nav.data'))}>{r.name || r.customer_no}</Link></td>
                          <td className="table__td">{r.month || (r.peak_off ? t('data.sheetPeakOff') : t('data.sheetDisagreeNow'))}</td>
                          <td className="table__td">{payWord(r.peak)}</td>
                          <td className="table__td">{payWord(r.sheet)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : <p className="imp__meta">{t('data.sheetDisagreeNone')}</p>}
              </section>
            </div>
          ) : null}
        </section>

        <aside className="imp__side card" aria-label={t('data.sideLabel')}>
          <section className="imp__sec">
            <h2 className="imp__h3" title={t('data.chainNote')}>{t('data.chain')}</h2>
            <ol className="imp__list">
              {rungs.map((rung, i) => {
                const s = rungStatus(rung)
                // The Odoo rung serving the book: its served slice with thousands separators.
                const note = rung.code === 'ODOO_CRM_LEAD' && rung.serving
                  ? t('data.rungOdooServing', { served: int(count.served), landed: int(count.landed) })
                  : human(served(rung, 'note'))
                return (
                  <li key={rung.code || i} className="imp__item imp__item--rank">
                    <span className="imp__rank num">{rung.rank ?? i + 1}</span>
                    <span className="imp__itemName">{rungName(rung)}</span>
                    <StatusPill kind={s.kind}>{t(s.key)}</StatusPill>
                    <span className="imp__itemNote">{note}</span>
                  </li>
                )
              })}
            </ol>
          </section>
          <section className="imp__sec">
            <h2 className="imp__h3">{t('data.integrations')}</h2>
            <ul className="imp__list">
              {conns.map((c) => (
                <li key={c.name} className="imp__item">
                  <span className="imp__itemName">{c.name}</span>
                  <StatusPill kind={c.status.kind}>{t(c.status.key)}</StatusPill>
                  {c.note ? <span className="imp__itemNote">{c.note}</span> : null}
                  {c.retry ? (
                    <span className="imp__itemNote">
                      <button type="button" className="btn btn--quiet btn--sm imp__retest" disabled={!!busy} onClick={retest}>
                        <Icon name="refresh" size={14} />{t('data.retest')}
                      </button>
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
            <Problem problem={retestProblem} />
          </section>
          <section className="imp__sec">
            <h2 className="imp__h3" title={t('data.integrationsNote')}>{t('data.syncTitle')}</h2>
            <ul className="imp__switches">
              <li>
                {/* "Sync Odoo" is the crm.lead pull; the Odoo panel opens to show its progress. */}
                <button type="button" className="btn btn--sm" disabled={!!busy || !mgr || running || odooNotConfigured}
                        title={!mgr ? t('data.managerOnly') : odooNotConfigured ? t('data.odooNotConfigured') : undefined}
                        onClick={() => { setTile('odoo'); pullCrmLead() }}>
                  {t('data.sync')}
                </button>
                <span className="imp__meta">{t('data.syncDesc')}</span>
                {mgr ? null : <span className="imp__meta">{t('data.managerOnly')}</span>}
              </li>
            </ul>
          </section>
        </aside>
      </div>
    </div>
  )
}

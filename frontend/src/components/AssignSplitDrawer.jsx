import { useEffect, useRef, useState } from 'react'
import { usePrefs } from '../lib/prefs.jsx'
import { api } from '../lib/api.js'
import { downloadText } from '../lib/download.js'
import { useToast } from './Toast.jsx'
import { Drawer } from './Drawer.jsx'
import { SegmentedControl } from './SegmentedControl.jsx'
import { Problem } from './Problem.jsx'
import { InfoPopover } from './InfoPopover.jsx'
import { StatusIcon } from './StatusIcon.jsx'
import { Icon } from './Icon.jsx'
import { OperationProgress } from './import/parts.jsx'

/**
 * F10b/F10c, ruling R-C (feedback-r2 TASK-028/029), final design spec-main §5.2: the
 * manager's portfolio split. Tab 1 deals one bucket to ticked officers through a
 * served dry-run preview; tab 2 uploads the system's own template, all-or-nothing.
 * Every count on screen is a number the server sent. The how-it-works subtitle is a
 * notice: it sits in the "i" beside the title.
 */
export function AssignSplitDrawer({ open, onClose, officers, totals, onDone }) {
  const { t, lang } = usePrefs()
  const toast = useToast()
  const [tab, setTab] = useState('random')
  const [buckets, setBuckets] = useState(null)
  const [bucket, setBucket] = useState('')
  const [picked, setPicked] = useState(() => new Set())
  const [includeAssigned, setIncludeAssigned] = useState(false)
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState(null)
  const [templateProblem, setTemplateProblem] = useState(null)
  const [templateDone, setTemplateDone] = useState(null)
  const [fileName, setFileName] = useState('')
  const [uploadTask, setUploadTask] = useState(null)
  const uploadAbort = useRef(null)

  function prepare() {
    setTab('random')
    setPreview(null)
    setProblem(null)
    setTemplateProblem(null)
    setTemplateDone(null)
    setFileName('')
    setUploadTask(null)
    setPicked(new Set())
    setIncludeAssigned(false)
    api.assignSplitBuckets()
      .then((rows) => {
        setBuckets(rows)
        setBucket((current) => current || rows?.[0]?.code || '')
      })
      .catch((e) => setProblem(e?.problem || { code: 'request_failed' }))
  }

  useEffect(() => {
    if (open) prepare()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const chosen = (buckets || []).find((b) => b.code === bucket)
  const officersList = officers || []

  function toggle(uid) {
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(uid)) next.delete(uid)
      else next.add(uid)
      setPreview(null)
      return next
    })
  }

  async function loadPreview() {
    setBusy(true)
    setProblem(null)
    try {
      const body = await api.assignSplit({
        bucket, officer_uids: [...picked], include_assigned: includeAssigned, dry_run: true,
      })
      setPreview(body)
    } catch (e) {
      setProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  async function confirmSplit() {
    if (!preview) return
    setBusy(true)
    setProblem(null)
    try {
      const body = await api.assignSplit({
        bucket, officer_uids: [...picked], include_assigned: includeAssigned, dry_run: false,
      })
      toast(t('today.splitDone', { n: body.total }))
      onDone?.()
      onClose?.()
    } catch (e) {
      setProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  async function downloadTemplate() {
    setTemplateProblem(null)
    try {
      const { text, filename } = await api.assignTemplate()
      downloadText(filename || 'assignments-template.csv', text)
    } catch (e) {
      setTemplateProblem(e?.problem || { code: 'request_failed' })
    }
  }

  async function uploadTemplate(file) {
    if (!file) return
    setFileName(file.name)
    setBusy(true)
    setTemplateProblem(null)
    setTemplateDone(null)
    const controller = new AbortController()
    uploadAbort.current = controller
    setUploadTask({ phase: 'uploading', uploadedBytes: 0, totalBytes: file.size })
    try {
      const body = await api.assignTemplateUpload(file, {
        signal: controller.signal, onProgress: setUploadTask,
      })
      setTemplateDone(body)
      setUploadTask(null)
      toast(t('today.splitDone', { n: body.count }))
      onDone?.()
    } catch (e) {
      if (e?.name === 'AbortError') return
      setTemplateProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  const nothing = preview && !preview.total
  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('today.splitTitle')}
      subtitle={<InfoPopover>{t('today.splitNote')}</InfoPopover>}
      width={560}
      footer={(
        <>
          {nothing ? <span className="split__reason">{t('today.splitNothing')}</span> : null}
          <button type="button" className="btn" onClick={onClose}>{t('common.cancel')}</button>
          {preview && tab === 'random' ? (
            <button type="button" className="btn btn--primary" disabled={busy || nothing}
                    title={nothing ? t('today.splitNothing') : undefined} onClick={confirmSplit}>
              {t('today.splitConfirm', { n: preview.total })}
            </button>
          ) : null}
        </>
      )}
    >
      <SegmentedControl
        label={t('today.split')}
        value={tab}
        onChange={setTab}
        className="split__tabs"
        options={[
          { id: 'random', label: t('today.splitRandom') },
          { id: 'upload', label: t('today.splitUpload') },
        ]}
      />
      {tab === 'random' ? (
        <>
          <label className="label">
            {t('today.bucket')}
            <select className="field" value={bucket} onChange={(e) => { setBucket(e.target.value); setPreview(null) }}>
              {(buckets || []).map((b) => (
                <option key={b.code} value={b.code}>
                  {`${lang === 'en' ? b.label_en : b.label_th} (${b.code}) · ${t('today.splitAccounts', { n: b.count })}`}
                </option>
              ))}
            </select>
            {chosen ? <span className="split__unassigned num">{t('today.officerUnassigned', { n: chosen.unassigned })}</span> : null}
          </label>
          <div className="split__officers" role="group" aria-labelledby="split-officers-label">
            <div className="split__officersHead">
              <span id="split-officers-label" className="eyebrow">{t('today.pickOfficers')}</span>
              <button type="button" className="btn btn--quiet btn--sm"
                      onClick={() => { setPicked(new Set(officersList.map((o) => o.uid))); setPreview(null) }}>
                {t('today.pickAll')}
              </button>
              <button type="button" className="btn btn--quiet btn--sm"
                      onClick={() => { setPicked(new Set()); setPreview(null) }}>
                {t('today.pickNone')}
              </button>
            </div>
            <div className="split__list">
              {officersList.map((o) => {
                const name = (lang === 'en' ? o.display_name_en : o.display_name_th) || o.uid
                const caring = totals?.[o.uid]
                return (
                  <label key={o.uid} className="split__officer">
                    <input type="checkbox" checked={picked.has(o.uid)} onChange={() => toggle(o.uid)} />
                    <span className="split__name">{name}</span>
                    <span className="split__load num">{t('today.caring', { n: caring ?? '—' })}</span>
                  </label>
                )
              })}
            </div>
          </div>
          <label className="split__check">
            <input type="checkbox" checked={includeAssigned} onChange={(e) => { setIncludeAssigned(e.target.checked); setPreview(null) }} />
            {t('today.includeAssigned')}
          </label>
          {problem ? <Problem problem={problem} /> : null}
          {preview ? (
            <div className="split__preview">
              <span className="eyebrow">{t('today.splitPreview')}</span>
              <p className="num">
                {t('today.splitAccounts', { n: preview.total })} → {preview.per_officer.map((p) => {
                  const o = officersList.find((x) => x.uid === p.officer_uid)
                  const name = (lang === 'en' ? o?.display_name_en : o?.display_name_th) || p.officer_uid
                  return `${name} ${p.count}`
                }).join(' · ')}
              </p>
              <span className="split__seed">{t('today.splitSeed', { seed: preview.seed })}</span>
            </div>
          ) : (
            <div>
              <button type="button" className="btn" disabled={busy || !bucket} onClick={loadPreview}>
                {t('today.splitPreview')}
              </button>
            </div>
          )}
        </>
      ) : (
        <>
          <div>
            <button type="button" className="btn btn--sm" title={t('today.templateColumns')} onClick={downloadTemplate}>
              <Icon name="download" />{t('today.downloadTemplate')}
            </button>
          </div>
          <div className="label">
            <span id="split-upload-label">{t('today.splitUpload')}</span>
            <div className="split__file">
              <label className="btn" title={t('today.fileTypes')}>
                <Icon name="upload" />{t('today.chooseFile')}
                <input type="file" className="sr-only" accept=".csv,.xlsx" disabled={busy} aria-labelledby="split-upload-label"
                       onChange={(e) => uploadTemplate(e.target.files?.[0])} />
              </label>
              <span className="split__fileName">{fileName || t('today.noFile')}</span>
            </div>
          </div>
          {busy && uploadTask ? (
            <OperationProgress task={uploadTask} onCancel={() => uploadAbort.current?.abort()} />
          ) : null}
          {templateProblem ? <Problem problem={templateProblem} /> : null}
          {templateDone ? (
            <p className="split__done"><StatusIcon kind="done" />{t('today.splitDone', { n: templateDone.count })}</p>
          ) : null}
        </>
      )}
    </Drawer>
  )
}

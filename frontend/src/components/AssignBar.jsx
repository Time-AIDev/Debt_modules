import { useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useIdentity, atLeast } from '../lib/identity.jsx'
import { Problem } from './Problem.jsx'
import { InfoPopover } from './InfoPopover.jsx'
import { SegmentedControl } from './SegmentedControl.jsx'
import { useToast } from './Toast.jsx'

/**
 * F10 / Q5 (feedback-r2 TASK-014), final design spec-main §3.1: the bar that appears
 * while Today rows are ticked. One officer, an optional reason, one request — the
 * screen sends the whole set and shows the server's own counts beside each name.
 * Build round 3 adds the manager's random deal for the very ticks in front of them,
 * previewed with the served per-officer counts first; below manager that mode is
 * disabled with its reason (the server refuses it there). The how-to is a notice in
 * the "i".
 */
export function AssignBar({ count, customerUids, officers, totals, busy, problem, onAssign, onDone, onClear }) {
  const { t, lang } = usePrefs()
  useIdentity()
  const toast = useToast()
  const canRandom = atLeast('MANAGER')
  const [mode, setMode] = useState('one')
  const [officerUid, setOfficerUid] = useState('')
  const [reason, setReason] = useState('')
  const [picked, setPicked] = useState(() => new Set())
  const [preview, setPreview] = useState(null)
  const [working, setWorking] = useState(false)
  const [splitProblem, setSplitProblem] = useState(null)

  useEffect(() => {
    if (!officerUid && officers.length) setOfficerUid(officers[0].uid)
  }, [officers, officerUid])

  const name = (uid) => {
    const o = officers.find((x) => x.uid === uid)
    return (lang === 'en' ? o?.display_name_en : o?.display_name_th) || uid
  }

  function toggle(uid) {
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(uid)) next.delete(uid)
      else next.add(uid)
      setPreview(null)
      return next
    })
  }

  async function previewSplit() {
    setWorking(true)
    setSplitProblem(null)
    try {
      const body = await api.assignSplit({ customer_uids: customerUids, officer_uids: [...picked], dry_run: true })
      setPreview(body)
    } catch (e) {
      setSplitProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setWorking(false)
    }
  }

  async function confirmSplit() {
    if (!preview) return
    setWorking(true)
    setSplitProblem(null)
    try {
      const body = await api.assignSplit({ customer_uids: customerUids, officer_uids: [...picked], dry_run: false })
      toast(t('today.splitDone', { n: body.total }))
      onDone?.()
    } catch (e) {
      setSplitProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setWorking(false)
    }
  }

  const busyAll = busy || working
  const random = mode === 'random' && canRandom
  return (
    <div className="assignbar" role="region" aria-label={t('today.assignRegion')}>
      <div className="assignbar__head">
        <p className="assignbar__count num">{t('today.selectedN', { n: count })}</p>
        <button type="button" className="btn btn--quiet btn--sm" onClick={onClear}>{t('today.assignClear')}</button>
        <span className="spacer" />
        <InfoPopover align="right">{t('today.assignHint')}</InfoPopover>
      </div>
      <SegmentedControl
        label={t('today.assignMode')}
        value={random ? 'random' : 'one'}
        onChange={(v) => { setMode(v); setPreview(null) }}
        className="assignbar__modes"
        options={[
          { id: 'one', label: t('today.modeOne') },
          { id: 'random', label: t('today.modeRandom'), disabled: !canRandom, title: canRandom ? undefined : t('today.splitManagerOnly') },
        ]}
      />
      {canRandom ? null : <p className="assignbar__reason">{t('today.randomManagerOnly')}</p>}
      {random ? (
        <>
          <div className="assignbar__officers" role="group" aria-label={t('today.randomOfficers')}>
            {officers.map((o) => (
              <label key={o.uid} className={`assignbar__pill${picked.has(o.uid) ? ' assignbar__pill--on' : ''}`}>
                <input type="checkbox" checked={picked.has(o.uid)} onChange={() => toggle(o.uid)} />
                {name(o.uid)}
              </label>
            ))}
          </div>
          {preview ? (
            <div className="assignbar__preview">
              <p className="num">
                {preview.total} {t('today.items')} → {preview.per_officer.map((p) => `${name(p.officer_uid)} ${p.count}`).join(' · ')}
              </p>
              <button type="button" className="btn btn--sm btn--primary" disabled={busyAll} onClick={confirmSplit}>
                {t('today.splitConfirm', { n: preview.total })}
              </button>
            </div>
          ) : (
            <div>
              <button type="button" className="btn btn--sm" disabled={busyAll || !picked.size} onClick={previewSplit}>
                {t('today.randomPreview')}
              </button>
            </div>
          )}
          {splitProblem ? <Problem problem={splitProblem} /> : null}
        </>
      ) : (
        <>
          <div className="assignbar__one">
            <label className="label">
              {t('today.assignTo')}
              <select className="field" value={officerUid} onChange={(e) => setOfficerUid(e.target.value)}>
                {officers.map((o) => {
                  const held = totals?.[o.uid]
                  return (
                    <option key={o.uid} value={o.uid}>
                      {`${name(o.uid)} · ${held === undefined || held === null ? '—' : held} ${t('today.items')}`}
                    </option>
                  )
                })}
              </select>
            </label>
            <label className="label">
              {t('today.assignReason')}
              <input className="field" value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
          </div>
          <div className="assignbar__go">
            <button type="button" className="btn btn--sm btn--primary"
                    disabled={busyAll || !officerUid}
                    onClick={() => onAssign(officerUid, reason.trim() || undefined)}>
              {t('today.assign')}
            </button>
          </div>
        </>
      )}
      {problem ? <Problem problem={problem} /> : null}
    </div>
  )
}

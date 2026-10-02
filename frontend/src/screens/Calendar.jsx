import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useIdentity } from '../lib/identity.jsx'
import { useCrumb } from '../lib/crumb.jsx'
import { addDays, mondayOf, date as fmtDate } from '../lib/format.js'
import { calendarKind, statusOf } from '../lib/status.js'
import { SegmentedControl } from '../components/SegmentedControl.jsx'
import { Drawer } from '../components/Drawer.jsx'
import { Problem, LoadError } from '../components/Problem.jsx'
import { StatusIcon, StatusPill } from '../components/StatusIcon.jsx'
import { Icon } from '../components/Icon.jsx'
import { useToast } from '../components/Toast.jsx'
import { useReloadOnEpoch } from '../lib/dataEpoch.jsx'
import { internalOrigin, recordState } from '../lib/origin.js'

const WEEKDAYS = ['จ', 'อ', 'พ', 'พฤ', 'ศ', 'ส', 'อา']

function firstOfMonth(iso) {
  return `${String(iso).slice(0, 7)}-01`
}

function addMonths(iso, n) {
  const [y, m] = String(iso).slice(0, 7).split('-').map(Number)
  const d = new Date(y, m - 1 + n, 1)
  const pad = (v) => String(v).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-01`
}

function yearStart(iso, delta = 0) {
  return `${Number(String(iso).slice(0, 4)) + delta}-01-01`
}

/** ปฏิทิน · month and week from one served dated list; moving a next action needs a reason. */
export function Calendar() {
  const { t, lang } = usePrefs()
  const identity = useIdentity()
  const toast = useToast()
  const navigate = useNavigate()
  const location = useLocation()
  const back = location.state
  useCrumb('group.mine', 'nav.calendar')

  // 2026-09-21: the shown range is picked by day / week / month / year, around an
  // `anchor` date the officer navigates. The server still answers one dated range.
  // A case opened from here comes back to the same view (unit + anchor ride the router state).
  const [unit, setUnit] = useState(back?.unit || 'month')
  const [anchor, setAnchor] = useState(back?.anchor ?? null)
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState(null)
  const [moveFor, setMoveFor] = useState(null)
  const [newDay, setNewDay] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [writeProblem, setWriteProblem] = useState(null)
  const [noticeOpen, setNoticeOpen] = useState(false)
  const [notice, setNotice] = useState({ title: '', on: '', text: '' })

  const load = useCallback((range, silent) => {
    if (!silent) setProblem(null)
    return api.calendar(range)
      .then((d) => { setData(d); return d })
      .catch((e) => { setProblem(e?.problem || { code: 'request_failed' }); return null })
  }, [])

  useEffect(() => { load(undefined) }, [load])
  useReloadOnEpoch(() => load(range, true))

  const businessDate = data?.meta?.business_date
  // The anchor starts at the business date ONCE; a later epoch reload must not yank
  // the officer back to today while they are reading another month.
  useEffect(() => {
    if (!anchor && businessDate) setAnchor(businessDate)
  }, [anchor, businessDate])

  const range = useMemo(() => {
    if (!anchor) return null
    if (unit === 'day') return { from: anchor, to: anchor }
    if (unit === 'week') {
      const start = mondayOf(anchor)
      return { from: start, to: addDays(start, 6) }
    }
    if (unit === 'year') return { from: yearStart(anchor), to: `${String(anchor).slice(0, 4)}-12-31` }
    const start = mondayOf(firstOfMonth(anchor))
    return { from: start, to: addDays(start, 41) }
  }, [anchor, unit])

  useEffect(() => {
    if (range) load(range)
  }, [range?.from, range?.to, load])

  function step(delta) {
    if (!anchor) return
    if (unit === 'day') setAnchor(addDays(anchor, delta))
    else if (unit === 'week') setAnchor(addDays(anchor, 7 * delta))
    else if (unit === 'year') setAnchor(yearStart(anchor, delta))
    else setAnchor(addMonths(anchor, delta))
  }

  const monthLabel = (month) => new Intl.DateTimeFormat(lang === 'en' ? 'en-US' : 'th-TH', { month: 'long' })
    .format(new Date(Number(month.slice(0, 4)), Number(month.slice(5, 7)) - 1, 1))

  const items = data?.items || []
  const meta = data?.meta || {}
  const byDay = useMemo(() => {
    const map = new Map()
    for (const it of items) {
      if (!map.has(it.on)) map.set(it.on, [])
      map.get(it.on).push(it)
    }
    return map
  }, [items])

  // One status language: a kind's icon and word come from lib/status.js (an unknown kind shows its code).
  const kindIcon = (kind) => calendarKind(kind).kind
  const kindLabel = (kind) => t(calendarKind(kind).key)
  // F07 / TASK-016: the served urgency order (meta.kind_order, PTP first) decides the
  // legend; an older server without it falls back to the object's own order.
  const legendKinds = Object.keys(meta.by_kind || {}).sort((a, b) => {
    const order = meta.kind_order || []
    const rank = (k) => (order.indexOf(k) === -1 ? order.length : order.indexOf(k))
    return rank(a) - rank(b)
  })

  function openItem(it) {
    if (it.customer_uid) navigate(`/customers/${it.customer_uid}`, {
      state: recordState(internalOrigin(location, 'nav.calendar', { unit, anchor })),
    })
  }

  function openMove(it) {
    setWriteProblem(null)
    setReason('')
    setNewDay(it.on)
    setMoveFor(it)
  }

  async function submitMove() {
    setBusy(true)
    setWriteProblem(null)
    try {
      await api.moveNextAction(moveFor.customer_uid, { reason, on: newDay, by: identity.officer || undefined })
      toast(t('cal.moved'))
      setMoveFor(null)
      load(range)
    } catch (e) {
      setWriteProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  async function addNotice() {
    setBusy(true)
    setWriteProblem(null)
    try {
      await api.createNotice({ ...notice, by: identity.officer || undefined })
      toast(t('cal.noticeAdded'))
      setNoticeOpen(false)
      setNotice({ title: '', on: '', text: '' })
      load(range)
    } catch (e) {
      setWriteProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  async function removeNotice(uid) {
    try {
      await api.deleteNotice(uid)
      toast(t('cal.noticeRemoved'))
      load(range)
    } catch (e) {
      setProblem(e?.problem || { code: 'request_failed' })
    }
  }

  const fields = [
    { key: 'kinds', label: t('cal.byKind'), value: Object.entries(meta.by_kind || {}).map(([k, v]) => `${kindLabel(k)} ${v}`).join(' · ') || '—' },
    { key: 'total', label: t('cal.total'), value: `${meta.total ?? items.length}` },
    { key: 'from', label: t('cal.range'), value: `${fmtDate(meta.from)} → ${fmtDate(meta.to)}` },
    { key: 'officers', label: t('cal.officers'), value: `${(meta.officers || []).length}` },
  ]

  return (
    <div className="stack">
      <div className="lensbar">
        <span className="lensbar__title">{t('nav.calendar')}</span>
        <span className="lensbar__meta num">{items.length} {t('today.items')}</span>
        <span className="spacer" />
        <button type="button" className="btn btn--sm" onClick={() => { setWriteProblem(null); setNotice({ title: '', on: businessDate || '', text: '' }); setNoticeOpen(true) }}>
          {t('cal.addNotice')}
        </button>
        <div className="cal__nav">
          <button type="button" className="btn btn--sm btn--icon" aria-label={t('cal.prev')} onClick={() => step(-1)}><Icon name="left" /></button>
          <input className="field" type="date" value={anchor || ''} aria-label={t('cal.pickDate')}
                 onChange={(e) => e.target.value && setAnchor(e.target.value)} />
          <button type="button" className="btn btn--sm btn--icon" aria-label={t('cal.next')} onClick={() => step(1)}><Icon name="right" /></button>
          <button type="button" className="btn btn--sm" disabled={!businessDate || anchor === businessDate}
                  onClick={() => businessDate && setAnchor(businessDate)}>{t('cal.today')}</button>
        </div>
        <SegmentedControl
          label={t('shell.view')}
          value={unit}
          onChange={setUnit}
          options={[{ id: 'day', label: t('cal.day') }, { id: 'week', label: t('cal.week') },
                    { id: 'month', label: t('cal.month') }, { id: 'year', label: t('cal.year') }]}
        />
      </div>
      {problem ? <LoadError problem={problem} onRetry={() => load(range)} /> : null}

      <section className="card">
        <div className="scr-facts">
          {fields.map((f) => (
            <div className="scr-fact" key={f.key}>
              <span className="eyebrow">{f.label}</span>
              <span className="scr-meta">{f.value}</span>
            </div>
          ))}
        </div>
      </section>

      {unit === 'month' && range ? (
        <section className="card">
          {/* F07 / TASK-016: the legend, in the server's own urgency order (PTP first) —
              every kind the served month actually carries, with the icon its chips wear. */}
          <div className="legend cal__legend">
            {legendKinds.map((kind) => (
              <span key={kind}>
                <StatusIcon kind={kindIcon(kind)} size={14} />
                {kindLabel(kind)}{kind === 'PTP_DUE' ? ` · ${t('cal.mostUrgent')}` : ''}
              </span>
            ))}
          </div>
          <div className="cal__weekdays">
            {WEEKDAYS.map((w) => <span key={w} className="cal__weekday">{w}</span>)}
          </div>
          <div className="cal__grid">
            {Array.from({ length: 42 }, (_, i) => addDays(range.from, i)).map((day) => {
              const list = byDay.get(day) || []
              const inMonth = day.slice(0, 7) === anchor.slice(0, 7)
              const today = day === businessDate
              return (
                <div key={day} className={`cal__day${inMonth ? '' : ' cal__day--out'}${today ? ' cal__day--today' : ''}`}>
                  <div className="cal__dayHead">
                    <span className="cal__num">{day.slice(8)}</span>
                    {list.length ? <span className="cal__total num">{list.length}</span> : null}
                  </div>
                  <div className="cal__chips">
                    {list.slice(0, 3).map((it) => (
                      <button key={it.uid} type="button"
                              className={`cal__chip${it.kind === 'PTP_DUE' ? ' cal__chip--ptp' : ''}`}
                              onClick={() => openItem(it)} title={it.display_name || kindLabel(it.kind)}>
                        <StatusIcon kind={kindIcon(it.kind)} size={12} />
                        <span>{kindLabel(it.kind)}{it.display_name ? ` · ${it.display_name}` : ''}</span>
                      </button>
                    ))}
                    {list.length > 3 ? <span className="cal__more">{t('cal.more', { n: list.length - 3 })}</span> : null}
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      ) : null}

      {(unit === 'day' || unit === 'week') ? (
        <section className="card">
          <header className="card__head"><h2>{unit === 'day' ? t('cal.dayList') : t('cal.weekList')}</h2></header>
          <div className="card__body">
            <ul className="rows">
              {items.filter((it) => it.on >= range?.from && it.on <= range?.to).map((it) => (
                <li key={it.uid} className="rows__row">
                  <span className="scr-meta num">{fmtDate(it.on)}</span>
                  <StatusPill kind={kindIcon(it.kind)}>{kindLabel(it.kind)}</StatusPill>
                  <button type="button" className="rows__main cal__link" onClick={() => openItem(it)}>
                    {it.display_name || (it.facts && it.facts.title) || it.uid}
                  </button>
                  {it.overdue ? <StatusPill kind={statusOf('due', 'OVERDUE').kind}>{t(statusOf('due', 'OVERDUE').key)}</StatusPill> : null}
                  {it.movable ? (
                    <button type="button" className="btn btn--sm" onClick={() => openMove(it)}>{t('cal.move')}</button>
                  ) : null}
                  {it.kind === 'NOTICE' && it.facts?.notice_uid ? (
                    <button type="button" className="btn btn--sm btn--quiet" onClick={() => removeNotice(it.facts.notice_uid)}>
                      {t('cal.noticeDelete')}
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
            {!items.length ? <p className="empty">{t('cal.empty')}</p> : null}
          </div>
          <p className="card__note">{t('cal.note')}</p>
        </section>
      ) : null}

      {unit === 'year' && range ? (
        <section className="card">
          <header className="card__head"><h2>{t('cal.yearSummary')}</h2></header>
          <div className="card__body">
            <ul className="rows">
              {(meta.by_month || []).map((m) => (
                <li key={m.month} className="rows__row">
                  <button type="button" className="rows__main cal__link"
                          onClick={() => { setUnit('month'); setAnchor(firstOfMonth(m.month)) }}>
                    {monthLabel(m.month)}
                  </button>
                  <span className="scr-meta">{t('cal.monthTotal')}</span>
                  <span className="num">{m.total}</span>
                  {Object.entries(m.by_kind || {}).slice(0, 3).map(([kind, n]) => (
                    <StatusPill key={kind} kind={kindIcon(kind)}>{kindLabel(kind)} {n}</StatusPill>
                  ))}
                </li>
              ))}
            </ul>
            {!items.length ? <p className="empty">{t('cal.empty')}</p> : null}
          </div>
          <p className="card__note">{t('cal.note')}</p>
        </section>
      ) : null}

      <Drawer
        open={!!moveFor}
        onClose={() => setMoveFor(null)}
        title={t('cal.moveTitle')}
        subtitle={moveFor?.display_name}
        footer={(
          <>
            <button type="button" className="btn" onClick={() => setMoveFor(null)}>{t('common.cancel')}</button>
            <button type="button" className="btn btn--primary" disabled={busy || !reason.trim() || !newDay} onClick={submitMove}>
              {t('cal.moveRun')}
            </button>
          </>
        )}
      >
        <label>
          <span className="eyebrow">{t('cal.newDay')}<span className="req" aria-hidden="true">*</span></span>
          <input className="field" type="date" value={newDay} aria-required="true" onChange={(e) => setNewDay(e.target.value)} />
        </label>
        <label>
          <span className="eyebrow">{t('cal.moveReason')}<span className="req" aria-hidden="true">*</span></span>
          <textarea className="field" rows={3} value={reason} aria-required="true" onChange={(e) => setReason(e.target.value)} />
        </label>
        {writeProblem ? <Problem problem={writeProblem} /> : null}
        <p className="drawer__hint">{t('cal.moveNote')}</p>
      </Drawer>

      <Drawer
        open={noticeOpen}
        onClose={() => setNoticeOpen(false)}
        title={t('cal.addNotice')}
        footer={(
          <>
            <button type="button" className="btn" onClick={() => setNoticeOpen(false)}>{t('common.cancel')}</button>
            <button type="button" className="btn btn--primary" disabled={busy || !notice.title || !notice.on} onClick={addNotice}>
              {t('common.save')}
            </button>
          </>
        )}
      >
        <label><span className="eyebrow">{t('cal.noticeTitle')}<span className="req" aria-hidden="true">*</span></span>
          <input className="field" value={notice.title} aria-required="true" onChange={(e) => setNotice({ ...notice, title: e.target.value })} /></label>
        <label><span className="eyebrow">{t('cal.newDay')}<span className="req" aria-hidden="true">*</span></span>
          <input className="field" type="date" value={notice.on} aria-required="true" onChange={(e) => setNotice({ ...notice, on: e.target.value })} /></label>
        <label><span className="eyebrow">{t('cal.noticeText')}</span>
          <textarea className="field" rows={3} value={notice.text} onChange={(e) => setNotice({ ...notice, text: e.target.value })} /></label>
        {writeProblem ? <Problem problem={writeProblem} /> : null}
        <p className="drawer__hint">{t('cal.noticeScope')}</p>
      </Drawer>
    </div>
  )
}

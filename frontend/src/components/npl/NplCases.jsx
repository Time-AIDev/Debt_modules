import { Fragment, useEffect, useId, useRef, useState } from 'react'
import { api } from '../../lib/api.js'
import { usePrefs } from '../../lib/prefs.jsx'
import { useIdentity, atLeast } from '../../lib/identity.jsx'
import { money, date } from '../../lib/format.js'
import { nplCaseStatus, lotStatus, recoveryOutcome, recoveryStatus, paymentStatus } from '../../lib/status.js'
import { StatusIcon, StatusPill, NeutralChip } from '../StatusIcon.jsx'
import { Icon } from '../Icon.jsx'
import { Problem } from '../Problem.jsx'
import { SegmentedControl } from '../SegmentedControl.jsx'
import { Lanes, MoneyForm, CloseForm, RecoveryLines, SrLabel, useAct, word } from './parts.jsx'

const LOT_ORDER = ['PLANNED', 'UNINSTALLED', 'COUNTED', 'GRADED', 'PRICED', 'SOLD']

/**
 * Each NPL row joined to its recovery chain (source_ref) — the open record, else the
 * resolved one — and that record's lot. Grouped by whether a path is open (spec §2.1:
 * a typed-but-undecided case is undecided; the old grouping said otherwise). A row
 * whose served `strategy` names an open path the list does not carry keeps that path.
 */
export function caseModels(rows, recs) {
  return rows.map((row) => {
    const mine = recs.filter((r) => r.source_ref === row.uid || r.uid === row.recovery_uid)
    const rec = mine.find((r) => r.status === 'IN_PROGRESS') || mine.find((r) => r.status === 'RESOLVED')
      || (row.strategy ? { uid: row.recovery_uid, strategy: row.strategy, status: 'IN_PROGRESS' } : null)
    const state = !rec ? 'undecided' : rec.status === 'IN_PROGRESS' ? 'active' : 'closed'
    return {
      row, rec, state, lot: rec?.lots?.[0] || null, strategy: rec?.strategy || null,
      history: mine.filter((r) => r.status === 'SUPERSEDED'),
    }
  })
}

/** The path's steps: chosen → the served next steps; a repossession follows its lot. */
function stepsOf(m, t, served) {
  const { rec, lot, state } = m
  if (state === 'undecided') return []
  const ns = rec.next_steps || []
  const name = (i) => (ns[i] ? served(ns[i], 'label') : '—')
  const out = [{ kind: 'done', label: t('recovery.choosePath') }]
  if (lot) {
    const k = LOT_ORDER.indexOf(lot.status)
    const now = lotStatus(lot.status)
    out.push(
      { kind: k >= 1 ? 'done' : 'moving-2', label: name(0) },
      { kind: k >= 2 ? 'done' : k === 1 ? 'moving-2' : 'idle', label: name(1),
        sub: lot.actual_count == null ? '' : `${lot.expected_count} → ${lot.actual_count}` },
      { kind: k >= 5 ? 'done' : k >= 2 ? now.kind : 'idle', label: name(2),
        sub: k >= 5 ? t(now.key) : k >= 2 ? t('recovery.stepNow', { state: t(now.key) }) : '' },
    )
  } else {
    ns.forEach((s, i) => out.push({ kind: i ? 'idle' : 'moving-2', label: served(s, 'label'), sub: i ? '' : t('status.rec.IN_PROGRESS') }))
  }
  if (state !== 'closed') return out
  return [
    ...out.map((s) => (s.kind === 'done' ? s : { ...s, kind: 'off', sub: t('recovery.stepSkipped') })),
    { kind: 'done', label: t('recovery.resolve'), sub: `${t(recoveryOutcome(rec.outcome).key)} · ${date(rec.resolved_on)}` },
  ]
}

/** Row icon = the case (pie by steps done of 4); the pill says the lot's stage when there is one. */
export function lookOf(m, steps) {
  const done = steps.filter((s) => s.kind === 'done').length
  const st = nplCaseStatus({ status: m.rec?.status, outcome: m.rec?.outcome, done })
  return { st, pill: m.state === 'active' && m.lot ? lotStatus(m.lot.status) : st }
}

const GROUPS = [
  ['undecided', 'recovery.undecided', 'do', 'recovery.noUndecided'],
  ['active', 'recovery.inflight', 'moving-3', 'recovery.noInflight'],
  ['closed', 'recovery.closedGroup', 'done', 'recovery.noClosed'],
]

/** Tab "เคส NPL": design E's glyph list (default) or the F08 path board. */
export function NplCases({ models, strategies, label, reload, onCase, onLog, onMove }) {
  const { t } = usePrefs()
  const [view, setView] = useState('list')
  // The first row shown is open by default (the pattern shows); then the person decides.
  const [openUid, setOpenUid] = useState(() => GROUPS.flatMap(([k]) => models.filter((m) => m.state === k))[0]?.row.uid ?? null)
  const [shut, setShut] = useState({})

  // "เปิดดูลูกค้า" from the board: the list, that row open and focused (the card is gone).
  const [focusUid, setFocusUid] = useState(null)
  const goList = (uid) => { setView('list'); setShut({}); setOpenUid(uid); setFocusUid(uid) }
  useEffect(() => { if (focusUid) setFocusUid(null) }, [focusUid]) // once: the row took focus on mount
  const acts = (m) => ({
    onCase: () => onCase(m.row.customer_uid),
    onLog: () => onLog(m.row.customer_uid, m.row.display_name),
    onMove: () => onMove(m),
  })

  return (
    <>
      <div className="npl__toolbar">
        <SegmentedControl label={t('recovery.views')} value={view} onChange={setView} options={[
          { id: 'list', label: <><Icon name="list" />{t('recovery.viewList')}</> },
          { id: 'board', label: <><Icon name="board" />{t('recovery.viewBoard')}</> },
        ]} />
      </div>

      {view === 'list' ? (
        <div className="glist glist--cases">
          <div className="glist__head" aria-hidden="true">
            <span className="glist__headCase">{t('recovery.colCase')}</span><span>{t('recovery.colType')}</span>
            <span className="r">{t('recovery.colOverdue')}</span><span className="r">{t('recovery.npv')}</span>
            <span className="glist__pad">{t('recovery.colPath')}</span><span>{t('recovery.colStatus')}</span><span />
          </div>
          {models.length ? null : <p className="empty">{t('recovery.empty')}</p>}
          {models.length ? GROUPS.map(([k, labelKey, icon, emptyKey]) => {
            const list = models.filter((m) => m.state === k)
            const open = !shut[k]
            return (
              <Fragment key={k}>
                <button type="button" className="glist__group" aria-expanded={open}
                        onClick={() => setShut((s) => ({ ...s, [k]: open }))}>
                  <StatusIcon kind={icon} />
                  <span className="glist__groupName">{t(labelKey)}</span>
                  <span className="glist__groupCount num">{list.length}</span>
                  <span className="spacer" />
                  <Icon name="down" className="glist__caret" />
                </button>
                {open && !list.length ? <p className="glist__empty">{t(emptyKey)}</p> : null}
                {open ? list.map((m) => (
                  <CaseRow key={m.row.uid} m={m} open={openUid === m.row.uid} label={label} strategies={strategies}
                           focus={focusUid === m.row.uid} reload={reload} {...acts(m)}
                           onToggle={() => setOpenUid(openUid === m.row.uid ? null : m.row.uid)} />
                )) : null}
              </Fragment>
            )
          }) : null}
        </div>
      ) : (
        <PathBoard models={models} strategies={strategies} onGoList={goList} acts={acts} />
      )}
    </>
  )
}

function CaseRow({ m, open, focus, label, strategies, reload, onToggle, onCase, onLog, onMove }) {
  const { t, served } = usePrefs()
  const rowRef = useRef(null)
  const { row } = m
  const pay = row.payment_status && row.payment_status !== 'NPL' ? paymentStatus(row.payment_status) : null
  const steps = stepsOf(m, t, served)
  const look = lookOf(m, steps)
  const type = row.npl_type_label || t('recovery.noType')
  const meta = row.source === 'SHEET' ? t('recovery.src.SHEET') : [row.volt_id, row.entity].filter(Boolean).join(' · ')
  const origin = [
    row.declared_on ? t('recovery.declared', { date: date(row.declared_on), by: row.declared_by || '—' }) : null,
    row.source ? word(t, `recovery.src.${row.source}`, row.source) : null,
    row.origin === 'PAYMENT_STATUS' ? t('recovery.fromStatus') : null,
  ].filter(Boolean).join(' · ')
  return (
    <>
      <button type="button" className="glist__row" aria-expanded={open} onClick={onToggle} ref={rowRef} autoFocus={focus}>
        <StatusIcon kind={look.st.kind} />
        <span className="glist__who">
          <span className="glist__name" title={row.display_name || undefined}>{row.display_name || '—'}</span>
          {meta ? <span className="glist__meta" title={meta}>{meta}</span> : null}
        </span>
        <span className="glist__meta glist__clip" title={type}><SrLabel>{t('recovery.colType')}</SrLabel>{type}</span>
        <span className="num r"><SrLabel>{t('recovery.colOverdue')}</SrLabel>{money(row.aggregate_overdue)}</span>
        <span className="num r strong"><SrLabel>{t('recovery.npv')}</SrLabel>{money(row.remaining_npv)}</span>
        <span className="glist__pad glist__small glist__clip">
          <SrLabel>{t('recovery.colPath')}</SrLabel>{m.state === 'undecided' ? '—' : label(m.strategy)}
        </span>
        <span className="glist__clip"><StatusPill kind={look.pill.kind}>{t(look.pill.key)}</StatusPill></span>
        <Icon name="down" className="glist__caret" />
      </button>
      {open ? (
        <div className="glist__open">
          <div className="nplcase__facts">
            <p className="eyebrow">{t('recovery.npv')}</p>
            <p className="nplcase__npv num">{money(row.remaining_npv)}</p>
            <dl className="kv nplcase__kv">
              <dt>{t('recovery.colOverdue')}</dt><dd className="num">{money(row.aggregate_overdue)}</dd>
              <dt>{t('recovery.colType')}</dt><dd>{type}</dd>
              <dt>{t('recovery.entity')}</dt><dd>{row.entity || '—'}</dd>
              <dt>{t('recovery.voltId')}</dt><dd>{row.volt_id || '—'}</dd>
              <dt>{t('recovery.caseRef')}</dt><dd>{row.uid}</dd>
              {pay ? <><dt>{t('recovery.fromStatus')}</dt><dd><StatusPill kind={pay.kind}>{t(pay.key)}</StatusPill></dd></> : null}
              <dt>{t('recovery.source')}</dt><dd>{origin || '—'}</dd>
              <dt>{t('recovery.risk')}</dt><dd className="num">{row.risk_score ?? '—'}</dd>
              {row.pending_decision ? (
                <><dt>{t('recovery.pending')}</dt><dd><NeutralChip>{row.pending_decision}</NeutralChip></dd></>
              ) : null}
            </dl>
          </div>
          <div className="nplcase__main">
            {m.state === 'undecided'
              ? <Decide m={m} strategies={strategies} label={label} reload={reload} onCase={onCase} onLog={onLog}
                        onOpened={() => rowRef.current?.focus()} />
              : <Progress m={m} steps={steps} label={label} reload={reload} onCase={onCase} onLog={onLog} onMove={onMove} />}
          </div>
        </div>
      ) : null}
    </>
  )
}

/** Undecided: pick a path (radio list, Thai words), confirm IN PLACE — MANAGER+ (spec §2.1). */
function Decide({ m, strategies, label, reload, onCase, onLog, onOpened }) {
  const { t, served } = usePrefs()
  const identity = useIdentity()
  const mgr = atLeast('MANAGER')
  const { busy, problem, run } = useAct(reload)
  const [pick, setPick] = useState('')
  const [asking, setAsking] = useState(false)
  const [reason, setReason] = useState('')
  const group = useId()
  const paths = m.row.recovery_paths?.paths || []
  const pathOf = (code) => paths.find((p) => p.strategy === code) || {}
  const rated = paths.find((p) => p.available !== false && p.rate_pct)
  const why = !mgr ? 'mgr' : !pick ? 'pick' : null
  // The in-place ask replaces the trigger: "ยืนยัน" takes focus, "ยกเลิก" hands it back.
  const triggerRef = useRef(null)
  const back = useRef(false)
  useEffect(() => { if (!asking && back.current) { back.current = false; triggerRef.current?.focus() } }, [asking])

  async function confirm() {
    // The reason is optional here and travels like the board drawer's (Recovery.jsx):
    // the recovery keeps it as opened_reason and the audit row as its reason.
    const ok = await run(() => api.openRecovery(m.row.uid, {
      strategy: pick, reason: reason.trim() || undefined, by: identity.officer || undefined, role: identity.role,
    }), t('recovery.pathOpened', { path: label(pick) }))
    if (ok) { setPick(''); setReason(''); setAsking(false); onOpened() }
  }

  return (
    <>
      <fieldset className="nplpaths">
        <legend className="eyebrow">{t('recovery.choosePath')}</legend>
        {strategies.map((s) => {
          const p = pathOf(s.strategy)
          if (s.available === false) {
            const off = t('recovery.unavailable', { decision: s.pending_decision || '—' })
            return (
              <label key={s.strategy} className="nplpaths__opt nplpaths__opt--off" title={off}>
                <input type="radio" name={group} disabled className="sr-only" />
                <StatusIcon kind="off" />
                <span className="nplpaths__name">{served(s, 'label')}</span>
                <span className="nplpaths__exp">{off}</span>
              </label>
            )
          }
          const steps = (p.next_steps || []).length > 1 ? p.next_steps.map((x) => served(x, 'label')).join(' → ') : ''
          return (
            <label key={s.strategy} className={`nplpaths__opt${pick === s.strategy ? ' nplpaths__opt--on' : ''}`}>
              <input type="radio" name={group} value={s.strategy} checked={pick === s.strategy}
                     onChange={() => { setPick(s.strategy); setAsking(false) }} />
              <span className="nplpaths__name">
                {served(s, 'label')}
                {steps ? <span className="nplpaths__steps">{steps}</span> : null}
              </span>
              <span className="nplpaths__exp">{t('recovery.expectedShort')}</span>
              <span className="nplpaths__amt num">{money(p.expected_recovery)}</span>
            </label>
          )
        })}
      </fieldset>
      {rated ? (
        <p className="nplcase__note">
          {t('recovery.rate', { rate: rated.rate_pct })}{rated.rate_is_assumption ? ` · ${t('recovery.assumption')}` : ''}
        </p>
      ) : null}
      {asking && !why ? (
        <div className="nplask" role="group" aria-label={t('recovery.confirmPath')}>
          <StatusIcon kind="do" />
          <div className="nplask__text">
            <p className="nplask__q">{t('recovery.askOpen', { path: label(pick), name: m.row.display_name || '—' })}</p>
            <p className="nplask__sub">{t('recovery.signedAs')}</p>
            <label className="label nplask__why">
              {t('npl.openReason')}
              <input className="field" value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
          </div>
          <button type="button" className="btn btn--primary" disabled={busy} onClick={confirm} autoFocus>{t('common.confirm')}</button>
          <button type="button" className="btn" onClick={() => { back.current = true; setAsking(false) }}>{t('common.cancel')}</button>
        </div>
      ) : (
        <>
          <div className="nplcase__acts">
            <button type="button" className="btn btn--primary" disabled={!!why} ref={triggerRef}
                    title={why === 'mgr' ? t('recovery.managerOnly') : why === 'pick' ? t('recovery.pickFirst') : undefined}
                    onClick={() => setAsking(true)}>{t('recovery.confirmPath')}</button>
            <button type="button" className="btn" onClick={onCase}>{t('recovery.openCase')}<Icon name="arrow-right" /></button>
            <button type="button" className="btn btn--quiet" onClick={onLog}><Icon name="pen" />{t('recovery.logContact')}</button>
          </div>
          {why ? <p className="nplcase__reason">{why === 'mgr' ? t('recovery.confirmManagerOnly') : t('recovery.pickFirst')}</p> : null}
        </>
      )}
      {problem ? <Problem problem={problem} /> : null}
    </>
  )
}

/** In progress / closed: the steps, the figures, the record, the acts and their in-place forms. */
function Progress({ m, steps, label, reload, onCase, onLog, onMove }) {
  const { t } = usePrefs()
  const mgr = atLeast('MANAGER')
  const [form, setForm] = useState(null)
  const { rec, lot, state } = m
  const path = label(rec.strategy)
  const toggle = (f) => setForm((cur) => (cur === f ? null : f))
  return (
    <>
      <p className="eyebrow">{state === 'closed' ? t('recovery.closedPath', { path }) : t('recovery.stepsOf', { path })}</p>
      <ol className="nplsteps" style={{ '--steps': steps.length }}>
        {steps.map((s, i) => (
          <li key={i} className={`nplsteps__step nplsteps__step--${s.kind}`}>
            <span className="nplsteps__track"><StatusIcon kind={s.kind} /><span className="nplsteps__line" /></span>
            <span className="nplsteps__label">{s.label}</span>
            {s.sub ? <span className="nplsteps__sub">{s.sub}</span> : null}
          </li>
        ))}
      </ol>
      <dl className="nplfigs">
        <div><dt>{t('recovery.expected')}</dt><dd className="num">{money(rec.expected_recovery)}</dd></div>
        <div><dt>{t('recovery.recovered')}</dt><dd className="num">{money(rec.recovered_total)}</dd></div>
        <div><dt>{t('recovery.colPath')}</dt><dd>{path}</dd></div>
        {lot ? <div><dt>{t('recovery.lotNo')}</dt><dd>{lot.lot_no}</dd></div> : null}
      </dl>
      {m.history.map((h) => (
        <p key={h.uid} className="nplcase__hist">
          <StatusIcon kind="off" size={14} />
          {t('recovery.supersededLine', { path: label(h.strategy), on: date(h.superseded_on), from: h.uid, to: h.superseded_by || '—' })}
        </p>
      ))}
      <RecoveryLines rec={rec} compact />
      {state === 'active' ? (
        <>
          <div className="nplcase__acts">
            <button type="button" className="btn btn--primary" aria-expanded={form === 'money'} onClick={() => toggle('money')}>
              <Icon name="plus" />{t('recovery.recordRecovery')}
            </button>
            <button type="button" className="btn" disabled={!mgr} title={mgr ? undefined : t('recovery.managerOnly')}
                    onClick={onMove}>{t('recovery.changePathMore')}</button>
            <button type="button" className="btn" aria-expanded={form === 'close'} onClick={() => toggle('close')}>
              {t('recovery.resolveMore')}
            </button>
            <button type="button" className="btn btn--quiet" onClick={onCase}>{t('recovery.openCase')}<Icon name="arrow-right" /></button>
            <button type="button" className="btn btn--quiet" onClick={onLog}><Icon name="pen" />{t('recovery.logContact')}</button>
          </div>
          {mgr ? null : <p className="nplcase__reason">{t('recovery.moveManagerOnly')}</p>}
          {form === 'money' ? <MoneyForm rec={rec} reload={reload} onClose={() => setForm(null)} /> : null}
          {form === 'close' ? <CloseForm rec={rec} reload={reload} onClose={() => setForm(null)} /> : null}
        </>
      ) : (
        <div className="nplcase__acts">
          <button type="button" className="btn btn--quiet" onClick={onCase}>{t('recovery.openCase')}<Icon name="arrow-right" /></button>
          <button type="button" className="btn btn--quiet" onClick={onLog}><Icon name="pen" />{t('recovery.logContact')}</button>
        </div>
      )}
    </>
  )
}

/** View "บอร์ดแนวทาง" (F08): one lane per path + undecided; D27's lane stays, dimmed. */
function PathBoard({ models, strategies, onGoList, acts }) {
  const { t, served } = usePrefs()
  const mgr = atLeast('MANAGER')
  const [menu, setMenu] = useState(null)
  const laneOf = (m) => (m.state === 'undecided' ? 'UNDECIDED' : m.strategy)
  const defs = [
    { id: 'UNDECIDED', label: t('recovery.undecided'), icon: nplCaseStatus({}).kind },
    ...strategies.map((s) => ({
      id: s.strategy, label: served(s, 'label'), off: s.available === false,
      icon: s.available === false ? nplCaseStatus({ available: false }).kind : recoveryStatus('IN_PROGRESS').kind,
      why: t('recovery.unavailable', { decision: s.pending_decision || '—' }),
    })),
  ]
  const known = new Set(defs.map((l) => l.id))
  const lanes = defs.map((l) => ({
    ...l,
    aria: l.off ? `${l.label} · ${l.why}` : l.label,
    note: l.off ? <p className="lane__note"><StatusIcon kind="off" size={14} />{l.why}</p> : null,
    cards: models.filter((m) => laneOf(m) === l.id).map((m) => (
      <PathCard key={m.row.uid} m={m} mgr={mgr} open={menu === m.row.uid}
                onMenu={() => setMenu(menu === m.row.uid ? null : m.row.uid)}
                onGoList={() => onGoList(m.row.uid)} {...acts(m)} />
    )),
  }))
  const unknown = models.filter((m) => !known.has(laneOf(m))).map((m) => m.row.display_name || m.row.uid)
  return <Lanes lanes={lanes} unknown={unknown} className="lanes--paths" />
}

function PathCard({ m, mgr, open, onMenu, onGoList, onLog, onMove }) {
  const { t, served } = usePrefs()
  const look = lookOf(m, stepsOf(m, t, served))
  const name = m.row.display_name || '—'
  const closed = m.state === 'closed'
  const moveWhy = !mgr ? t('recovery.managerOnly') : closed ? t('recovery.caseClosed') : null
  // A menu item unmounts with the menu, so focus goes to ⋯ first — where the drawer returns it.
  const moreRef = useRef(null)
  const pick = (fn) => () => { moreRef.current?.focus(); onMenu(); fn() }
  return (
    <article className="lcard">
      <div className="lcard__top">
        <StatusIcon kind={look.st.kind} title={t(look.pill.key)} />
        <button type="button" className="lcard__name" onClick={onGoList}>{name}</button>
        <button type="button" className="btn btn--quiet btn--icon" aria-label={t('recovery.cardMenu', { name })}
                aria-expanded={open} onClick={onMenu} ref={moreRef}><Icon name="more" size={18} /></button>
      </div>
      <p className="lcard__line">{t('recovery.colOverdue')} <strong className="num">{money(m.row.aggregate_overdue)}</strong></p>
      <p className="lcard__line">{t('recovery.npv')} <span className="num lcard__ink">{money(m.row.remaining_npv)}</span></p>
      <p className="lcard__chips">
        <NeutralChip title={m.row.npl_type_label || undefined}>{m.row.npl_type_label || t('recovery.noType')}</NeutralChip>
      </p>
      {open ? (
        <div className="lcard__menu" role="group" aria-label={t('recovery.cardMenu', { name })}>
          <button type="button" className="lcard__item" onClick={onGoList}><Icon name="list" />{t('recovery.openRow')}</button>
          <button type="button" className="lcard__item" onClick={pick(onLog)}><Icon name="pen" />{t('recovery.logContact')}</button>
          <button type="button" className="lcard__item" disabled={!!moveWhy} title={moveWhy || undefined}
                  onClick={pick(onMove)}><Icon name="split" />{t('recovery.changePath')}</button>
          {moveWhy ? <span className="lcard__why">{moveWhy}</span> : null}
        </div>
      ) : null}
    </article>
  )
}

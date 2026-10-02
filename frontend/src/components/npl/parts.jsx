import { useEffect, useId, useState } from 'react'
import { api } from '../../lib/api.js'
import { usePrefs } from '../../lib/prefs.jsx'
import { useIdentity } from '../../lib/identity.jsx'
import { money, date } from '../../lib/format.js'
import { recoveryOutcome } from '../../lib/status.js'
import { useToast } from '../Toast.jsx'
import { Drawer } from '../Drawer.jsx'
import { Problem } from '../Problem.jsx'
import { InfoPopover } from '../InfoPopover.jsx'
import { StatusIcon } from '../StatusIcon.jsx'

/**
 * One act and its own refusal, shown where the person acted (brief §3.4: refusals are
 * always visible). `run(fn, okText)` toasts and reloads the screen on success and
 * resolves true; on a refusal it keeps the served Problem and resolves false.
 */
export function useAct(reload) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState(null)
  async function run(fn, okText) {
    setBusy(true)
    setProblem(null)
    try {
      await fn()
      if (okText) toast(okText)
      reload()
      return true
    } catch (e) {
      setProblem(e?.problem || { code: 'request_failed' })
      return false
    } finally {
      setBusy(false)
    }
  }
  return { busy, problem, setProblem, run }
}

/** A list cell's column name for screen readers (the visible head row is drawn once, aria-hidden). */
export const SrLabel = ({ children }) => <span className="sr-only">{children} </span>

/** A dictionary word when this screen has one, else the served code itself (never blank). */
export function word(t, key, code) {
  const w = t(key)
  return w === key ? (code ?? '—') : w
}

/** A recovery line's `source`: UNSPECIFIED / REFURB_RESALE in Thai, typed text as typed. */
export function sourceWord(t, source) {
  return source ? word(t, `recovery.srcLine.${source}`, source) : t('recovery.srcLine.UNSPECIFIED')
}

/**
 * A kanban of lanes (the path board and the recovery stage board). Heads line up across
 * lanes (subgrid); every lane is drawn, empty ones say so; a card outside the lanes is
 * reported, never dropped. `data-testid="board"` is the board the tests address.
 */
export function Lanes({ lanes, unknown = [], className = '' }) {
  const { t } = usePrefs()
  return (
    <>
      {unknown.length ? (
        <div className="problem" role="status">
          <p className="problem__head">
            <StatusIcon kind="problem" />
            <span className="problem__title">{t('recovery.reconcile', { n: unknown.length })}</span>
          </p>
          <p className="problem__msg">{unknown.slice(0, 6).join(' · ')}</p>
        </div>
      ) : null}
      <div className={`lanes ${className}`.trim()} data-testid="board">
        {lanes.map((l) => (
          <section key={l.id} className={`lane${l.off ? ' lane--off' : ''}`} aria-label={l.aria || l.label}>
            <h2 className="lane__head">
              {l.icon ? <StatusIcon kind={l.icon} /> : null}
              <span className="lane__name">{l.label}</span>
              <span className="lane__count num">{l.cards.length}</span>
            </h2>
            <div className="lane__body">
              {l.note}
              {l.cards.length ? l.cards : <p className="lane__empty">{t('recovery.emptyLane')}</p>}
            </div>
          </section>
        ))}
      </div>
    </>
  )
}

/**
 * The move drawer of both NPL boards (spec §2.3, §4): the reason first (required), then
 * one button per destination — clicking one IS the confirm. The current destination is
 * disabled "… ✓"; an unavailable one carries its reason. The rule notes sit in an "i".
 */
export function NplMoveDrawer({ open, onClose, title, subtitle, notes, options, currentId, currentTitle, problem, busy, onPick }) {
  const { t } = usePrefs()
  const id = useId()
  const [reason, setReason] = useState('')
  const [missing, setMissing] = useState(false)
  useEffect(() => {
    if (open) { setReason(''); setMissing(false) }
  }, [open])

  function pick(to) {
    if (!reason.trim()) { setMissing(true); return }
    onPick(to, reason.trim())
  }

  return (
    <Drawer open={open} onClose={onClose} title={title} subtitle={subtitle}
            footer={<button type="button" className="btn" onClick={onClose}>{t('common.cancel')}</button>}>
      {problem ? <Problem problem={problem} /> : null}
      <div className="nplmove__reason">
        <div className="nplmove__label">
          <label className="label" htmlFor={id}>
            <span>{t('recovery.moveReason')}<span className="req" aria-hidden="true">*</span></span>
          </label>
          {notes?.length ? (
            <InfoPopover align="right">{notes.map((n) => <span key={n} className="nplmove__note">{n}</span>)}</InfoPopover>
          ) : null}
        </div>
        <textarea id={id} className="field" rows={3} value={reason} aria-required="true" aria-invalid={missing}
                  onChange={(e) => { setReason(e.target.value); setMissing(false) }} />
        {missing ? <p className="field__error" role="alert">{t('recovery.reasonRequired')}</p> : null}
      </div>
      <div className="nplmove__dest" role="group" aria-label={t('recovery.moveTo')}>
        <span className="label">{t('recovery.moveTo')}</span>
        {(options || []).map((o) => {
          const current = o.id === currentId
          return (
            <button key={o.id} type="button" className="btn nplmove__opt" disabled={current || busy || o.disabled}
                    title={(current ? currentTitle : o.title) || undefined}
                    aria-current={current ? 'true' : undefined} onClick={() => pick(o.id)}>
              {o.off ? <StatusIcon kind="off" /> : null}
              <span className="nplmove__optLabel">{current ? `${o.label} ✓` : o.label}</span>
              {current || o.note ? <span className="nplmove__optNote" aria-hidden="true">{current ? t('recovery.now') : o.note}</span> : null}
            </button>
          )
        })}
      </div>
    </Drawer>
  )
}

/** In place (E pattern): record money recovered on an open recovery (spec §5). */
export function MoneyForm({ rec, reload, onClose }) {
  const { t } = usePrefs()
  const identity = useIdentity()
  const { busy, problem, run } = useAct(reload)
  const [amount, setAmount] = useState('')
  const [source, setSource] = useState('')
  async function save() {
    const ok = await run(() => api.recordRecovery(rec.uid, {
      amount, source: source.trim() || 'UNSPECIFIED', by: identity.officer || undefined,
    }), t('recovery.recorded'))
    if (ok) onClose()
  }
  return (
    <section className="nplform" aria-label={t('recovery.recordRecovery')}>
      <h3 className="nplform__head">{t('recovery.recordRecovery')}<span className="nplform__sub">{rec.uid}</span></h3>
      {problem ? <Problem problem={problem} /> : null}
      <div className="nplform__grid nplform__grid--money">
        <label className="label">
          <span>{t('recovery.amount')}<span className="req" aria-hidden="true">*</span></span>
          <input className="field num nplform__amount" inputMode="decimal" value={amount} aria-required="true"
                 onChange={(e) => setAmount(e.target.value)} />
        </label>
        <label className="label">
          <span>{t('recovery.source')}</span>
          <input className="field" value={source} placeholder={t('recovery.srcLine.UNSPECIFIED')}
                 onChange={(e) => setSource(e.target.value)} />
        </label>
      </div>
      <div className="nplform__acts">
        <button type="button" className="btn btn--primary" disabled={busy || !amount.trim()}
                title={amount.trim() ? undefined : t('recovery.amountFirst')} onClick={save}>{t('common.save')}</button>
        <button type="button" className="btn" onClick={onClose}>{t('common.cancel')}</button>
      </div>
    </section>
  )
}

const OUTCOMES = ['FULL', 'PARTIAL', 'NO_CONCLUSION', 'CLOSED_WRITE_OFF']

/** In place: close a recovery with its outcome; a write-off is the Owner's alone (spec §5). */
export function CloseForm({ rec, reload, onClose }) {
  const { t } = usePrefs()
  const identity = useIdentity()
  const { busy, problem, run } = useAct(reload)
  const [outcome, setOutcome] = useState('')
  const owner = identity.role === 'OWNER'
  const group = useId()
  async function save() {
    const ok = await run(() => api.resolveRecovery(rec.uid, {
      outcome, role: identity.role, by: identity.officer || undefined,
    }), t('recovery.resolved'))
    if (ok) onClose()
  }
  return (
    <section className="nplform" aria-label={t('recovery.resolve')}>
      <h3 className="nplform__head">{t('recovery.resolve')}<span className="nplform__sub">{rec.uid}</span></h3>
      {problem ? <Problem problem={problem} /> : null}
      <fieldset className="nplform__set">
        <legend className="label">
          <span>{t('recovery.outcome')}<span className="req" aria-hidden="true">*</span></span>
        </legend>
        <div className="nplform__grid">
          {OUTCOMES.map((o) => {
            const off = o === 'CLOSED_WRITE_OFF' && !owner
            return (
              <label key={o} className={`nplform__radio${o === 'CLOSED_WRITE_OFF' ? ' nplform__radio--danger' : ''}`}
                     title={off ? t('recovery.writeOffOwner') : undefined}>
                <input type="radio" name={group} value={o} checked={outcome === o} disabled={off}
                       onChange={() => setOutcome(o)} />
                {t(recoveryOutcome(o).key)}
              </label>
            )
          })}
        </div>
        {!owner ? <p className="nplform__reason">{`${t('status.outcome.CLOSED_WRITE_OFF')}: ${t('recovery.writeOffOwner')}`}</p> : null}
      </fieldset>
      <div className="nplform__acts">
        <button type="button" className="btn btn--primary" disabled={busy || !outcome}
                title={outcome ? undefined : t('recovery.outcomeFirst')} onClick={save}>{t('common.confirm')}</button>
        <button type="button" className="btn" onClick={onClose}>{t('common.cancel')}</button>
      </div>
    </section>
  )
}

/**
 * The money recovered on one record. Full (the การเรียกคืน tab): จำนวนเงิน · วันที่ · ที่มา
 * with a head and an empty line. Compact (an NPL row): วันที่ · ที่มา · amount, only when any.
 */
export function RecoveryLines({ rec, compact = false }) {
  const { t } = usePrefs()
  const lines = rec?.recoveries || []
  if (compact && !lines.length) return null
  return (
    <table className={`nplLines${compact ? ' nplLines--compact' : ''}`}>
      {compact ? null : (
        <thead>
          <tr><th className="num">{t('recovery.amount')}</th><th>{t('recovery.on')}</th><th>{t('recovery.source')}</th></tr>
        </thead>
      )}
      <tbody>
        {lines.map((r, i) => {
          const amount = <td className="num nplLines__amt">{money(r.amount)}</td>
          const on = <td className="num nplLines__muted">{date(r.on)}</td>
          const src = <td>{sourceWord(t, r.source)}</td>
          return <tr key={i}>{compact ? <>{on}{src}{amount}</> : <>{amount}{on}{src}</>}</tr>
        })}
        {lines.length ? null : <tr><td colSpan={3} className="nplLines__empty">{t('recovery.noRecoveries')}</td></tr>}
      </tbody>
    </table>
  )
}


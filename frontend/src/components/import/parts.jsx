// Parts the แหล่งข้อมูล panels share (design D): the figure cell, the progress box, the
// drop zone, the PEAK review rows and the side sheet that links one of them, and the
// apply confirmation both PEAK reports ask.
import { useEffect, useState } from 'react'
import { api } from '../../lib/api.js'
import { usePrefs } from '../../lib/prefs.jsx'
import { atLeast, useIdentity } from '../../lib/identity.jsx'
import { date, money, int, when } from '../../lib/format.js'
import { runStatus } from '../../lib/status.js'
import { StatusIcon, StatusPill } from '../StatusIcon.jsx'
import { Icon } from '../Icon.jsx'
import { Drawer } from '../Drawer.jsx'
import { ConfirmDialog } from '../ConfirmDialog.jsx'
import { Problem } from '../Problem.jsx'

/** A word for a served code under `prefix`; an unknown code shows as served. */
export function codeWord(t, prefix, code) {
  const key = `${prefix}${code}`
  const word = t(key)
  return word === key ? String(code) : word
}

/** The matcher's rule in words: "COMPOSITE:VOLT_ID" reads "หลายกฎ · ตรง Volt ID". */
export function ruleWord(t, rule) {
  if (!rule) return ''
  return String(rule).split(':').map((code) => codeWord(t, 'peak.rule.', code)).join(' · ')
}

/** A client-made refusal: a Thai headline plus the served reason as its one line. */
export function runProblem(head, problem, reason) {
  const p = problem || {}
  const th = reason || p.detail_th || p.message_th || p.detail
  const en = p.detail || th
  return {
    code: p.code || 'pipeline_failed',
    message_th: head,
    message_en: head,
    retryable: p.retryable,
    errors: th ? [{ message_th: th, message: en }] : [],
  }
}

/** One figure: label (with its status icon when it has one) over a number. */
export function Fig({ label, value, kind }) {
  return (
    <div className="imp-figs__cell">
      <span className="imp-figs__label">{kind ? <StatusIcon kind={kind} size={14} /> : null}{label}</span>
      <span className="imp-figs__value num">{value}</span>
    </div>
  )
}

/** A running read: the pie by share done, the words, a bar. */
export function Progress({ text, done, total, indeterminate = false, onCancel, cancelLabel }) {
  const pct = total ? Math.max(0, Math.min(100, Math.round((Number(done) / Number(total)) * 100))) : 0
  return (
    <div className="imp-progress" role="status" aria-label={text}>
      <span className="imp-progress__line num">
        <StatusIcon kind={runStatus('running', done, total).kind} />{text}
        {onCancel ? (
          <button type="button" className="imp-progress__cancel" aria-label={cancelLabel || 'Cancel'}
                  title={cancelLabel || 'Cancel'} onClick={onCancel}>
            <Icon name="close" size={16} />
          </button>
        ) : null}
      </span>
      <span className={`imp-progress__bar${indeterminate ? ' imp-progress__bar--indeterminate' : ''}`}>
        <span style={indeterminate ? undefined : { width: `${pct}%` }} />
      </span>
    </div>
  )
}

/** Shared phase/byte progress used by every upload door. */
export function OperationProgress({ task, onCancel }) {
  const { t } = usePrefs()
  if (!task) return null
  const phase = task.phase || 'uploading'
  const bytesDone = task.uploadedBytes ?? task.uploaded_bytes
  const bytesTotal = task.totalBytes ?? task.total_bytes
  const done = phase === 'uploading' ? bytesDone : task.processed
  const total = phase === 'uploading' ? bytesTotal : task.phase_total
  const key = `upload.phase.${phase}`
  const translated = t(key, { done: int(done), total: int(total) })
  return <Progress text={translated === key ? phase : translated} done={done} total={total}
                   indeterminate={!total} onCancel={onCancel} cancelLabel={t('common.cancel')} />
}

/** The drop zone: a click opens the page's own file input; a dropped file is taken as is. */
export function Dropzone({ text, hint, tall = false, disabled = false, onPick, onFile }) {
  return (
    <button type="button" className={`imp-drop${tall ? ' imp-drop--tall' : ''}`} disabled={disabled}
            title={tall ? undefined : hint} onClick={onPick}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault()
              const file = e.dataTransfer?.files?.[0]
              if (file && !disabled) onFile(file)
            }}>
      <Icon name="upload" size={tall ? 20 : 18} />
      {tall ? (
        <>
          <span className="imp-drop__text">{text}</span>
          <span className="imp-drop__hint">{hint}</span>
        </>
      ) : text}
    </button>
  )
}

/** The file input behind a drop zone and its upload button (visually hidden). */
export function FileInput({ inputRef, label, disabled, onFile }) {
  return (
    <input ref={inputRef} type="file" accept=".csv,.xlsx" className="sr-only" tabIndex={-1}
           aria-label={label} disabled={disabled}
           onChange={(e) => {
             const file = e.target.files?.[0]
             e.target.value = ''
             if (file) onFile(file)
           }} />
  )
}

const cycle = (r) => (r.cycle_n ? `${r.cycle_n}/${r.cycle_of || '—'}` : '—')
const candidateRecord = (candidate) => {
  if (candidate && typeof candidate === 'object') return candidate
  return candidate ? { customer_no: String(candidate), rule: null, code: null } : null
}
const candidateRecords = (row) => (row.candidates || []).map(candidateRecord).filter(Boolean)

/**
 * The review list (รอยืนยัน · ไม่พบลูกค้า · receipts): one line per invoice, no buttons
 * in rows — a row opens the side sheet. Rows a person already linked are hidden.
 */
export function ReviewRows({ page, empty, current, busy, onOpen, onMore }) {
  const { t } = usePrefs()
  if (!page) return <p className="empty" role="status">{t('common.loading')}</p>
  const rows = page.rows.filter((r) => !r.linked_no)
  return (
    <div className="imp-rows">
      <div className="imp-rows__grid imp-rows__head">
        <span>{t('peak.colDoc')}</span><span>{t('peak.colName')}</span><span>{t('peak.colDue')}</span>
        <span>{t('peak.colCycle')}</span><span className="imp-rows__num">{t('peak.colAwaiting')}</span>
        <span>{t('peak.colProposal')}</span><span />
      </div>
      {rows.length ? rows.map((r) => {
        const c = candidateRecords(r)[0]
        const code = r.contact_code || r.reference || ''
        const prop = c ? `→ ${c.customer_no} · ${ruleWord(t, c.rule)}` : t('peak.noProposal')
        return (
          <button key={r.doc_no} type="button" title={t('peak.linkCase')} onClick={() => onOpen(r)}
                  className={`imp-rows__grid imp-rows__row${current === r.doc_no ? ' imp-rows__row--on' : ''}`}>
            <span className="num">{r.doc_no}</span>
            <span className="imp-rows__name" title={[r.customer_name, code].filter(Boolean).join(' · ')}>
              {r.customer_name || '—'}<span className="imp-rows__code">{code}</span>
            </span>
            <span className="num">{date(r.due_on)}</span>
            <span className="num">{cycle(r)}</span>
            <span className="num imp-rows__num">{money(r.amount_awaiting)}</span>
            <span className="imp-rows__prop" title={prop}>
              {c ? <><b className="num">→ {c.customer_no}</b> · {ruleWord(t, c.rule)}</> : prop}
            </span>
            <Icon name="right" className="imp-rows__chev" />
          </button>
        )
      }) : <p className="empty">{empty}</p>}
      <div className="imp-rows__foot">
        <span className="num">{t('peak.showing', { n: int(rows.length), total: int(page.total) })}</span>
        {page.rows.length < page.total ? (
          <button type="button" className="btn btn--quiet btn--sm" disabled={busy} onClick={onMore}>{t('peak.loadMore')}</button>
        ) : null}
      </div>
    </div>
  )
}

/**
 * The side sheet for one review row: its facts, the system's proposals (each links at
 * once) and a search to link any other customer, with an optional reason.
 */
export function RowSheet({ row, busy, problem, onClose, onLink }) {
  const { t } = usePrefs()
  const [q, setQ] = useState('')
  const [found, setFound] = useState(null)
  const [picked, setPicked] = useState(null)
  const [reason, setReason] = useState('')

  useEffect(() => {
    if (q.trim().length < 2) { setFound(null); return undefined }
    let alive = true
    const id = setTimeout(() => {
      api.workbook({ q: q.trim(), identities: 1, limit: 5 })
        .then((d) => { if (alive) setFound((d?.rows || []).slice(0, 5)) })
        .catch(() => { if (alive) setFound([]) })
    }, 180)
    return () => { alive = false; clearTimeout(id) }
  }, [q])

  const cands = candidateRecords(row)
  return (
    <Drawer open onClose={onClose} width={480} title={row.doc_no} subtitle={row.customer_name || undefined}
            footer={(
              <>
                <button type="button" className="btn" onClick={onClose}>{t('common.cancel')}</button>
                <button type="button" className="btn btn--primary" disabled={busy || !picked}
                        title={picked ? undefined : t('peak.pickFirst')}
                        onClick={() => onLink(row, picked.customer_no, reason.trim())}>
                  {t('peak.link')}
                </button>
              </>
            )}>
      <p className="imp-sheet__status">
        <StatusPill kind="do">{t(cands.length ? 'status.import.CANDIDATE' : 'status.import.UNMATCHED')}</StatusPill>
        {t('peak.linkCase')}
      </p>
      <dl className="kv">
        <dt>{t('peak.colDue')}</dt><dd className="num">{date(row.due_on)}</dd>
        <dt>{t('peak.colCycle')}</dt><dd className="num">{cycle(row)}</dd>
        <dt>{t('peak.colAwaiting')}</dt><dd className="num">{money(row.amount_awaiting)}</dd>
        <dt>{t('peak.contactCode')}</dt><dd className="num">{row.contact_code || row.reference || '—'}</dd>
      </dl>
      {cands.length ? (
        <section className="imp-sheet__sec">
          <h3>{t('peak.proposals')}</h3>
          {cands.map((c) => (
            <button key={`${c.customer_no}-${c.rule}`} type="button" className="btn imp-sheet__prop" disabled={busy}
                    onClick={() => onLink(row, c.customer_no, '')}>
              {t('peak.confirmCandidate', { who: c.customer_no })} · {ruleWord(t, c.rule)}
            </button>
          ))}
        </section>
      ) : null}
      <section className="imp-sheet__sec">
        <h3>{t('peak.linkOther')}</h3>
        <label className="label">
          {t('peak.searchCustomer')}
          <input className="field" value={q} disabled={busy} placeholder={t('peak.pickPlaceholder')}
                 onChange={(e) => { setQ(e.target.value); setPicked(null) }} />
        </label>
        {found && found.length ? (
          <ul className="imp-sheet__results" aria-label={t('peak.results')}>
            {found.map((r) => {
              const c = r.customer || {}
              const on = picked?.customer_no === c.customer_no
              return (
                <li key={c.uid || c.customer_no}>
                  <button type="button" aria-pressed={on} disabled={busy} onClick={() => setPicked(c)}
                          className={`imp-sheet__result${on ? ' imp-sheet__result--on' : ''}`}>
                    <span>{c.display_name} · {c.customer_no}</span>
                    {on ? <Icon name="check" /> : null}
                  </button>
                </li>
              )
            })}
          </ul>
        ) : found ? <p className="imp-sheet__none">{t('peak.noResults')}</p> : null}
        {picked ? (
          <label className="label">
            {t('peak.decisionReason')}
            <input className="field" value={reason} disabled={busy} onChange={(e) => setReason(e.target.value)} />
          </label>
        ) : null}
      </section>
      <Problem problem={problem} />
    </Drawer>
  )
}

/** The "what changed since the review" list the fence's refusal offers: one line
 *  per committed act (who · what · when), served by the run's own changes read. */
export function ChangesDrawer({ open, runId, onClose }) {
  const { t } = usePrefs()
  const [page, setPage] = useState(null)
  const [problem, setProblem] = useState(null)
  useEffect(() => {
    if (!open || !runId) return undefined
    let alive = true
    setProblem(null)
    api.peakRunChanges(runId, { limit: 50 })
      .then((body) => { if (alive) setPage(body) })
      .catch((e) => { if (alive) setProblem(e?.problem || { code: 'request_failed' }) })
    return () => { alive = false }
  }, [open, runId])
  return (
    <Drawer open={open} onClose={onClose} width={440}
            title={t('peak.changesTitle')} subtitle={page?.since ? when(page.since) : undefined}>
      {problem ? <Problem problem={problem} /> : !page ? (
        <p className="empty" role="status">{t('common.loading')}</p>
      ) : !page.rows?.length ? (
        <p className="empty">{t('peak.changesEmpty')}</p>
      ) : (
        <>
          <p className="scr-meta">{t('peak.changesCount', { n: int(page.total) })}</p>
          <ul className="imp-changes">
            {page.rows.map((row, i) => (
              <li key={row.at + row.act + i}>
                <span className="num">{when(row.at)}</span>
                <span className="imp-changes__act">{row.act || '—'}</span>
                <span className="imp-changes__who">{row.actor || '—'}{row.subject_uid ? ` · ${row.subject_uid}` : ''}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Drawer>
  )
}

/**
 * The confirmation both PEAK reports ask before they move payment status: what the act
 * does, the report's own figures, and "use an older report" (Manager and above).
 *
 * A confirm the review fence refused (`state_conflict` / `preview_stale`) offers its
 * own honest answers in place: re-check the run against the version that stands now,
 * see what changed since the review — and, Manager and above, a forced confirm that
 * crosses the fence on record, with a reason the audit row will keep.
 */
export function ApplyDialog({ open, title, facts, busy, problem, allowOlder, onAllowOlder,
                              stale = false, onRecheck, onShowChanges, onForce, onClose, onConfirm }) {
  const { t } = usePrefs()
  useIdentity() // re-gate live when the role changes
  const mgr = atLeast('MANAGER')
  const [force, setForce] = useState(false)
  const [reason, setReason] = useState('')
  useEffect(() => { if (!open) { setForce(false); setReason('') } }, [open])
  const fence = stale && ['state_conflict', 'preview_stale'].includes(problem?.code)
  const forcing = fence && force
  return (
    <ConfirmDialog open={open} onClose={onClose}
                   onConfirm={() => (forcing ? onForce?.(reason.trim()) : onConfirm())}
                   busy={busy} title={title}
                   confirmLabel={t(forcing ? 'peak.forceConfirm' : 'peak.applyConfirm')}>
      <p>{t('peak.applyNote')}</p>
      {facts.filter(Boolean).map((f) => <p key={f} className="imp-apply__fact num">{f}</p>)}
      <label className="imp-apply__check" title={mgr ? undefined : t('data.managerOnly')}>
        <input type="checkbox" checked={mgr && allowOlder} disabled={!mgr || busy}
               onChange={(e) => onAllowOlder(e.target.checked)} />
        {t('peak.allowOlder')}
      </label>
      {mgr ? null : <span className="imp-apply__reason">{t('data.managerOnly')}</span>}
      {fence ? (
        <div className="imp-apply__fence" role="alert">
          <p>{t('peak.staleNote')}</p>
          <div className="imp-apply__fenceActs">
            <button type="button" className="btn btn--sm" disabled={busy} onClick={onRecheck}>{t('peak.recheck')}</button>
            <button type="button" className="btn btn--sm" disabled={busy} onClick={onShowChanges}>{t('peak.showChanges')}</button>
          </div>
          {mgr ? (
            <label className="imp-apply__check">
              <input type="checkbox" checked={force} disabled={busy} onChange={(e) => setForce(e.target.checked)} />
              {t('peak.forceState')}
            </label>
          ) : null}
          {forcing ? (
            <label className="label">
              {t('peak.forceReason')}
              <input className="field" value={reason} disabled={busy} autoFocus
                     placeholder={t('peak.forceReasonHint')} onChange={(e) => setReason(e.target.value)} />
            </label>
          ) : null}
          {forcing && !reason.trim() ? <p className="imp-apply__reason">{t('peak.forceReasonRequired')}</p> : null}
        </div>
      ) : null}
      <Problem problem={problem} />
    </ConfirmDialog>
  )
}

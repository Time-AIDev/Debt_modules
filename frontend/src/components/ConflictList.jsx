import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { date, int } from '../lib/format.js'
import { importStatus } from '../lib/status.js'
import { StatusIcon, StatusPill } from './StatusIcon.jsx'
import { Icon } from './Icon.jsx'
import { Drawer } from './Drawer.jsx'
import { Problem } from './Problem.jsx'
import { SegmentedControl } from './SegmentedControl.jsx'
import { useToast } from './Toast.jsx'

const PAGE = 50

/**
 * Q7 / TASK-214: where PEAK and the crm.lead record disagree. Design D: one line per
 * customer; the line opens a side sheet with the table — ฟิลด์ · Odoo · PEAK · ค่าที่ใช้ —
 * and one "ใช้ PEAK ทั้งหมด". Nothing is written to Odoo; PEAK is the default, a reason is
 * optional and revealed only when wanted, and every choice is audited and can be retired.
 */
export function ConflictList({ runId, busy, onChanged }) {
  const { t } = usePrefs()
  const toast = useToast()
  const [page, setPage] = useState(null)
  const [problem, setProblem] = useState(null)
  const [draft, setDraft] = useState({})
  const [reasonOpen, setReasonOpen] = useState({})
  const [saving, setSaving] = useState(false)
  const [openNo, setOpenNo] = useState(null)

  const load = useCallback((offset = 0) => {
    if (!runId) return
    setProblem(null)
    api.peakConflicts(runId, { limit: PAGE, offset }).then((body) => {
      setPage((prev) => ({
        ...body,
        rows: [...(offset > 0 ? (prev?.rows || []) : []), ...(body.rows || [])],
      }))
    }).catch((e) => setProblem(e?.problem || { code: 'request_failed' }))
  }, [runId])

  useEffect(() => { load(0) }, [load])

  const key = (no, field) => `${no}:${field}`

  async function save(row) {
    const decisions = row.conflicts
      .map((c) => {
        const d = draft[key(row.customer_no, c.field)]
        if (!d) return null
        return { field: c.field, source: d.source, reason: d.reason || undefined }
      })
      .filter(Boolean)
    if (!decisions.length) return
    setSaving(true)
    setProblem(null)
    try {
      await api.peakConflictsDecide(runId, { customer_no: row.customer_no, decisions })
      toast(t('peak.decisionsSaved'))
      setDraft((prev) => {
        const next = { ...prev }
        decisions.forEach((d) => delete next[key(row.customer_no, d.field)])
        return next
      })
      onChanged?.()
      load(0)
    } catch (e) {
      setProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setSaving(false)
    }
  }

  function takePeakAll(row) {
    setDraft((prev) => {
      const next = { ...prev }
      row.conflicts.forEach((c) => { next[key(row.customer_no, c.field)] = { source: 'PEAK', reason: prev[key(row.customer_no, c.field)]?.reason || '' } })
      return next
    })
  }

  async function retire(decision) {
    setSaving(true)
    setProblem(null)
    try {
      await api.peakDecisionRetire(decision.uid)
      toast(t('peak.decisionRetired'))
      onChanged?.()
      load(0)
    } catch (e) {
      setProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setSaving(false)
    }
  }

  // Closing the sheet drops that customer's unsaved picks and reasons.
  function close() {
    const drop = (o) => Object.fromEntries(Object.entries(o).filter(([k]) => !k.startsWith(`${openNo}:`)))
    setDraft(drop)
    setReasonOpen(drop)
    setProblem(null)
    setOpenNo(null)
  }

  if (problem && !page) return <Problem problem={problem} />
  if (!page) return <p className="empty" role="status">{t('common.loading')}</p>
  if (!page.rows.length) return <p className="empty">{t('peak.noConflicts')}</p>

  const disabled = busy || saving
  const open = page.rows.find((r) => r.customer_no === openNo) || null
  const pillOf = (row) => {
    const undecided = row.conflicts.filter((c) => !c.decision).length
    return row.decided || !undecided
      ? <StatusPill kind="done">{t('peak.conflictDecided')}</StatusPill>
      : <StatusPill kind={importStatus('CONFLICT').kind}>{t('peak.conflictFields', { n: undecided })}</StatusPill>
  }

  return (
    <div className="imp-rows">
      <div className="imp-conf__grid imp-rows__head">
        <span>{t('peak.colCustomerNo')}</span><span>{t('peak.colCustomer')}</span><span>{t('peak.field.volt_id')}</span>
        <span>{t('peak.invoices')}</span><span>{t('peak.colDecision')}</span><span />
      </div>
      {page.rows.map((row) => (
        <button key={row.customer_no} type="button" onClick={() => { setProblem(null); setOpenNo(row.customer_no) }}
                className={`imp-conf__grid imp-rows__row${openNo === row.customer_no ? ' imp-rows__row--on' : ''}`}>
          <span className="num">{row.customer_no}</span>
          <span className="imp-rows__name">{row.display_name || row.customer_no}</span>
          <span className="num">{row.volt_id || '—'}</span>
          <span>{t('peak.conflictInvoices', { n: int(row.invoice_count) })}</span>
          <span>{pillOf(row)}</span>
          <Icon name="right" className="imp-rows__chev" />
        </button>
      ))}
      <div className="imp-rows__foot">
        <span className="num">{t('peak.showing', { n: int(page.rows.length), total: int(page.total) })}</span>
        {page.rows.length < page.total ? (
          <button type="button" className="btn btn--quiet btn--sm" disabled={disabled} onClick={() => load(page.rows.length)}>
            {t('peak.loadMore')}
          </button>
        ) : null}
      </div>

      {open ? (
        <Drawer
          open
          onClose={close}
          width={480}
          title={`${open.display_name || open.customer_no} · ${open.volt_id || '—'}`}
          subtitle={<span title={t('peak.localOnly')}>{open.customer_no} · {t('peak.conflictInvoices', { n: int(open.invoice_count) })}</span>}
          footer={(
            <>
              <button type="button" className="btn" onClick={close}>{t('common.cancel')}</button>
              {(() => {
                const dirty = open.conflicts.some((c) => draft[key(open.customer_no, c.field)])
                return (
                  <button type="button" className="btn btn--primary" disabled={disabled || !dirty}
                          title={dirty ? undefined : t('peak.saveFirst')} onClick={() => save(open)}>
                    {t('peak.saveDecisions')}
                  </button>
                )
              })()}
            </>
          )}
        >
          <p className="imp-sheet__status">
            {pillOf(open)}
            <span className="spacer" />
            <button type="button" className="btn btn--quiet btn--sm" disabled={disabled} onClick={() => takePeakAll(open)}>
              {t('peak.usePeakAll')}
            </button>
          </p>
          <table className="imp-conf__table">
            <thead>
              <tr>
                <th scope="col">{t('peak.conflictField')}</th>
                <th scope="col">{t('peak.conflictOdoo')}</th>
                <th scope="col">{t('peak.conflictPeak')}</th>
                <th scope="col">{t('peak.conflictChoice')}</th>
              </tr>
            </thead>
            {open.conflicts.map((c) => {
              const k = key(open.customer_no, c.field)
              const decision = c.decision
              const pick = draft[k]?.source ?? decision?.source ?? 'PEAK'
              const draftReason = draft[k]?.reason
              const showReason = reasonOpen[k] === true || Boolean(draftReason)
              const label = t(`peak.field.${c.field}`)
              return (
                <tbody key={c.field}>
                  <tr>
                    <th scope="row">{label}</th>
                    <td>{c.odoo_value ?? '—'}</td>
                    <td>{c.peak_value ?? '—'}</td>
                    <td>
                      <SegmentedControl
                        label={`${t('peak.conflictChoice')} ${label}`}
                        className="imp-conf__seg"
                        value={pick}
                        onChange={(source) => setDraft((prev) => ({ ...prev, [k]: { source, reason: prev[k]?.reason || '' } }))}
                        options={[
                          { id: 'PEAK', label: t('peak.usePeak'), disabled },
                          { id: 'ODOO', label: t('peak.keepOdoo'), disabled },
                        ]}
                      />
                    </td>
                  </tr>
                  <tr className="imp-conf__more">
                    <td colSpan={4}>
                      {decision ? (
                        <p className="imp-conf__decided">
                          <StatusIcon kind="done" size={14} />
                          <span>
                            {t('peak.decidedBy', { by: decision.by, on: date(decision.at) })}
                            {decision.reason ? ` · ${decision.reason}` : ''}
                          </span>
                          <button type="button" className="btn btn--quiet btn--sm" disabled={disabled} onClick={() => retire(decision)}>
                            {t('peak.retireDecision')}
                          </button>
                        </p>
                      ) : null}
                      {showReason ? (
                        <label className="label">
                          {t('peak.decisionReason')}
                          <input className="field" value={draftReason || ''} disabled={disabled} autoFocus
                                 onChange={(e) => setDraft((prev) => ({
                                   ...prev,
                                   [k]: { source: prev[k]?.source || decision?.source || 'PEAK', reason: e.target.value },
                                 }))} />
                        </label>
                      ) : (
                        <button type="button" className="btn btn--quiet btn--sm imp-conf__reasonBtn" disabled={disabled}
                                onClick={() => setReasonOpen((prev) => ({ ...prev, [k]: true }))}>
                          + {t('peak.decisionReason')}
                        </button>
                      )}
                    </td>
                  </tr>
                </tbody>
              )
            })}
          </table>
          <Problem problem={problem} />
        </Drawer>
      ) : null}
    </div>
  )
}

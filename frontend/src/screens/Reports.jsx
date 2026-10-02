import { useCallback, useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useIdentity, atLeast } from '../lib/identity.jsx'
import { useCrumb } from '../lib/crumb.jsx'
import { money, pct, int, date as fmtDate, monthLabel } from '../lib/format.js'
import { downloadBlob, downloadText } from '../lib/download.js'
import { DataTable } from '../components/DataTable.jsx'
import { StatusPill, NeutralChip } from '../components/StatusIcon.jsx'
import { ptpStatus, paymentStatus, statusOf } from '../lib/status.js'
import { Drawer } from '../components/Drawer.jsx'
import { Problem, LoadError } from '../components/Problem.jsx'
import { useToast } from '../components/Toast.jsx'
import { useReloadOnEpoch } from '../lib/dataEpoch.jsx'
import { internalOrigin, recordState } from '../lib/origin.js'

// A served period label "2026-10-17..2026-10-23" as dates: 17/10/2026 – 23/10/2026.
const periodText = (label) => (label ? String(label).split('..').map(fmtDate).join(' – ') : '—')

/** รายงาน: the live weekly payload, the published editions, and the publish act. */
export function Reports() {
  const { t, lang } = usePrefs()
  const identity = useIdentity()
  const toast = useToast()
  const location = useLocation()
  useCrumb('group.system', 'nav.reports')

  const [weekly, setWeekly] = useState(null)
  const [editions, setEditions] = useState([])
  const [problem, setProblem] = useState(null)
  const [busy, setBusy] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [writeProblem, setWriteProblem] = useState(null)

  const load = useCallback(() => {
    setProblem(null)
    Promise.all([api.weeklyReport(), api.weeklyEditions()])
      .then(([w, e]) => { setWeekly(w); setEditions(e?.editions || []) })
      .catch((e) => setProblem(e?.problem || { code: 'request_failed' }))
  }, [])
  useEffect(() => { load() }, [load])
  useReloadOnEpoch(load)

  async function publish() {
    setBusy(true)
    setWriteProblem(null)
    try {
      await api.weeklyPublish({ by: identity.officer || 'manager', role: identity.role })
      toast(t('reports.published'))
      load()
    } catch (e) {
      setWriteProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  async function exportEdition() {
    setBusy(true)
    setWriteProblem(null)
    try {
      const { blob, filename } = await api.weeklyExport({ reason: reason || undefined, by: identity.officer || undefined })
      downloadBlob(filename, blob)
      setExportOpen(false)
      toast(t('reports.exported'))
    } catch (e) {
      setWriteProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  const mgmt = weekly?.management_summary || {}
  const cash = mgmt.cash_in || {}
  const portfolio = weekly?.portfolio || {}
  const promises = weekly?.promises || {}
  const movement = weekly?.npl_movement || {}
  const pfUnit = (lang === 'en' ? portfolio.unit_en : portfolio.unit_th) || portfolio.unit

  return (
    <div className="stack">
      <div className="lensbar">
        <span className="lensbar__title">{t('nav.reports')}</span>
        <span className="lensbar__meta">{periodText(weekly?.period?.label)}</span>
        <span className="spacer" />
        <button type="button" className="btn btn--sm" onClick={() => { setWriteProblem(null); setExportOpen(true) }}>
          {t('reports.export')}
        </button>
        <button type="button" className="btn btn--sm btn--primary" disabled={busy || !atLeast('MANAGER')}
                title={atLeast('MANAGER') ? undefined : t('reports.managerOnly')} onClick={publish}>
          {t('reports.publish')}
        </button>
      </div>
      {problem ? <LoadError problem={problem} onRetry={load} /> : null}
      {!weekly && !problem ? <p className="empty">{t('common.loading')}</p> : null}

      {/* F16 / TASK-025: the PTP report leads the stack. */}
      <PtpReportSection />

      <MonthlySection />

      {weekly ? (
        <>
          <section className="card">
            <header className="card__head">
              <h2>{t('reports.summary')}</h2>
              <span className="scr-meta">{lang === 'en' ? mgmt.measure_label_en : mgmt.measure_label_th}</span>
              <span className="spacer" />
              <NeutralChip>{weekly.period?.week ? `WK-${weekly.period.week}/${weekly.period.week_year}` : '—'}</NeutralChip>
            </header>
            <div className="card__body">
              <div className="money4">
                {[['total', t('reports.total')], ['instalment', t('reports.instalment')], ['cash_or_project', t('reports.cashProject')]].map(([key, label]) => (
                  <div key={key}>
                    <p className="eyebrow">{label}</p>
                    <p className="scr-value">{money(cash[key])}</p>
                    <p className="scr-meta">{mgmt.targets?.[key] ? `${t('reports.target')} ${money(mgmt.targets[key])} · ${pct(mgmt.achievement?.[key])}` : t('dash.noTarget')}</p>
                  </div>
                ))}
                <div>
                  <p className="eyebrow">{t('reports.kept')}</p>
                  <p className="scr-value">{pct(promises.kept_rate_pct)}</p>
                  <p className="scr-meta">{t('reports.keptLine', { kept: promises.kept ?? 0, broken: promises.broken ?? 0, open: promises.open ?? 0 })}</p>
                </div>
              </div>
            </div>
            <p className="card__note">{lang === 'en' ? mgmt.note_en : mgmt.note_th}</p>
          </section>

          <div className="grid2">
            <section className="card">
              <header className="card__head"><h2>{t('reports.portfolio')}</h2></header>
              <div className="card__body">
                {/* the served head-count by payment status, in the status words and icons */}
                <dl className="kv">
                  {[['current', 'CURRENT'], ['late', 'LATE'], ['npl', 'NPL']].map(([k, code]) => (
                    <div key={k} style={{ display: 'contents' }}>
                      <dt><StatusPill kind={paymentStatus(code).kind}>{t(paymentStatus(code).key)}</StatusPill></dt>
                      <dd className="num">{portfolio[k] ?? '—'}</dd>
                    </div>
                  ))}
                  <dt>{t('reports.pf.inCollection')}</dt><dd className="num">{portfolio.in_collection ?? '—'}</dd>
                  <dt>{t('reports.pf.ratioLate')}</dt><dd className="num">{pct(portfolio.ratio_late_pct)}</dd>
                </dl>
              </div>
              {pfUnit ? <p className="card__note">{pfUnit}</p> : null}
            </section>
            <section className="card">
              <header className="card__head"><h2>{t('reports.movement')}</h2></header>
              <div className="card__body">
                <dl className="kv">
                  <dt>{t('reports.entered')}</dt><dd className="num">{movement.entered?.customers ?? 0}</dd>
                  <dt>{t('reports.left')}</dt><dd className="num">{movement.left?.customers ?? 0}</dd>
                  <dt>{t('reports.nextFocus')}</dt><dd>{weekly.next_week_focus?.th || weekly.next_week_focus || '—'}</dd>
                </dl>
              </div>
              <p className="card__note">{movement.definition_th && lang === 'th' ? movement.definition_th : movement.definition || ''}</p>
            </section>
          </div>

          <section className="card">
            <header className="card__head"><h2>{t('reports.editions')}</h2></header>
            <DataTable
              caption={t('reports.editions')}
              minWidth={780}
              getKey={(r) => r.edition_uid || r.uid}
              rows={editions}
              empty={t('reports.noEditions')}
              columns={[
                { key: 'uid', label: t('reports.edition'), render: (r) => <span style={{ fontWeight: 600 }}>{r.edition_uid || r.uid}</span> },
                { key: 'period', label: t('reports.period'), render: (r) => periodText(r.period_label || r.period || [r.period_start, r.period_end].filter(Boolean).join('..')) },
                { key: 'cash', label: t('reports.cashIn'), num: true, render: (r) => money(r.cash_total) },
                { key: 'contacts', label: t('reports.contacts'), num: true, render: (r) => r.counted_contacts ?? r.contacts ?? '—' },
                { key: 'kept', label: t('reports.keptCol'), num: true, render: (r) => `${r.ptp_kept ?? 0} / ${r.ptp_total ?? 0}` },
                { key: 'state', label: t('record.invState'), render: (r) => {
                  const s = statusOf('edition', r.status || r.state || 'PUBLISHED')
                  return <StatusPill kind={s.kind}>{t(s.key)}</StatusPill>
                } },
              ]}
            />
            <p className="card__note">{t('reports.editionsNote')}</p>
          </section>
        </>
      ) : null}

      {writeProblem && !exportOpen ? <Problem problem={writeProblem} /> : null}

      <Drawer
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        title={t('reports.export')}
        footer={(
          <>
            <button type="button" className="btn" onClick={() => setExportOpen(false)}>{t('common.cancel')}</button>
            <button type="button" className="btn btn--primary" disabled={busy} onClick={exportEdition}>{t('reports.exportRun')}</button>
          </>
        )}
      >
        <label>
          <span className="eyebrow">{t('reports.exportReason')}<span className="req" aria-hidden="true">*</span></span>
          <textarea className="field" rows={3} value={reason} aria-required="true" onChange={(e) => setReason(e.target.value)} />
        </label>
        {writeProblem ? <Problem problem={writeProblem} /> : null}
      </Drawer>
    </div>
  )
}

const MONTH_STATUSES = ['CURRENT', 'LATE', 'NPL', 'CLOSED', 'TERMINATED', 'NOT_INSTALLED']
const signed = (n) => (n > 0 ? `+${n}` : String(n))

/**
 * Monthly history (Arina, 2026-09-25): per month, customers by payment status, NPL
 * in/out against the month before and the change on it — every figure the server's
 * (records.customer_month). One month leaves as .xlsx: Manager, with a reason.
 */
function MonthlySection() {
  const { t, lang } = usePrefs()
  const toast = useToast()
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState(null)
  const [open, setOpen] = useState(false)
  const [month, setMonth] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [writeProblem, setWriteProblem] = useState(null)

  const load = useCallback(() => {
    setProblem(null)
    api.monthlyReport(12).then(setData).catch((e) => setProblem(e?.problem || { code: 'request_failed' }))
  }, [])
  useEffect(() => { load() }, [load])
  useReloadOnEpoch(load)

  const months = data?.months || []
  async function run() {
    setBusy(true)
    setWriteProblem(null)
    try {
      const { blob, filename } = await api.monthlyExport({ month: month || months[0]?.month, reason })
      downloadBlob(filename, blob)
      setOpen(false)
      toast(t('reports.exported'))
    } catch (e) {
      setWriteProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  const mgr = atLeast('MANAGER')
  return (
    <section className="card">
      <div className="card__head">
        <h2>{t('reports.monthlyTitle')}</h2>
        <span className="spacer" />
        <button type="button" className="btn btn--sm" disabled={!mgr || !months.length}
                title={mgr ? undefined : t('reports.managerOnly')}
                onClick={() => { setWriteProblem(null); setMonth(months[0]?.month || ''); setOpen(true) }}>
          {t('reports.monthlyExport')}
        </button>
      </div>
      <div className="card__body">
        {problem ? <LoadError problem={problem} onRetry={load} /> : null}
        {!data && !problem ? <p className="empty">{t('common.loading')}</p> : null}
        {data && !months.length ? <p className="empty">{t('reports.monthlyNone')}</p> : null}
        {months.length ? (
          <DataTable
            caption={t('reports.monthlyTitle')}
            minWidth={980}
            getKey={(r) => r.month}
            rows={months}
            columns={[
              { key: 'month', label: t('reports.monthlyMonth'), render: (r) => monthLabel(r.month, lang) },
              { key: 'customers', label: t('reports.monthlyCustomers'), num: true,
                render: (r) => <>{int(r.customers)}{r.mom ? <span className="muted"> ({signed(r.mom.customers)})</span> : null}</> },
              ...MONTH_STATUSES.map((code) => ({
                key: code, num: true,
                label: <StatusPill kind={paymentStatus(code).kind}>{t(paymentStatus(code).key)}</StatusPill>,
                render: (r) => int(r.by_status?.[code]?.count || 0),
              })),
              { key: 'npl', label: t('reports.monthlyNpl'), num: true,
                render: (r) => (r.npl_in == null ? '—' : `+${r.npl_in} / −${r.npl_out}`) },
              { key: 'overdue', label: t('reports.monthlyOverdue'), num: true, render: (r) => money(r.overdue) },
              { key: 'outstanding', label: t('reports.monthlyOutstanding'), num: true,
                render: (r) => <>{money(r.outstanding)}{r.mom ? <span className="muted"> ({Number(r.mom.outstanding) > 0 ? '+' : ''}{money(r.mom.outstanding)})</span> : null}</> },
            ]}
          />
        ) : null}
      </div>
      <p className="card__note">{t('reports.monthlyNote')}</p>
      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title={t('reports.monthlyExport')}
        footer={(
          <>
            <button type="button" className="btn" onClick={() => setOpen(false)}>{t('common.cancel')}</button>
            <button type="button" className="btn btn--primary" disabled={busy || !reason.trim()} onClick={run}>{t('reports.exportRun')}</button>
          </>
        )}
      >
        <label>
          <span className="eyebrow">{t('reports.monthlyMonth')}</span>
          <select className="field" value={month} onChange={(e) => setMonth(e.target.value)}>
            {months.map((m) => <option key={m.month} value={m.month}>{monthLabel(m.month, lang)}</option>)}
          </select>
        </label>
        <label>
          <span className="eyebrow">{t('reports.exportReason')}<span className="req" aria-hidden="true">*</span></span>
          <textarea className="field" rows={3} value={reason} aria-required="true" onChange={(e) => setReason(e.target.value)} />
        </label>
        {writeProblem ? <Problem problem={writeProblem} /> : null}
      </Drawer>
    </section>
  )
}

/**
 * F16 / TASK-025: every promise in a date range, served with its totals and
 * exportable as CSV. The filters default from the payload's own period; every
 * figure on the card — the rows, the totals, the count — is the server's.
 */
function PtpReportSection() {
  const { t, lang } = usePrefs()
  const identity = useIdentity()
  const toast = useToast()
  const [filters, setFilters] = useState(null)
  const [data, setData] = useState(null)
  const [officers, setOfficers] = useState([])
  const [problem, setProblem] = useState(null)
  const [exportProblem, setExportProblem] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback((next) => {
    setProblem(null)
    const params = next ? {
      from: next.from || undefined, to: next.to || undefined,
      officer: next.officer || undefined, status: next.status || undefined,
    } : undefined
    return api.ptpReport(params)
      .then((body) => {
        setData(body)
        setFilters((prev) => prev || {
          from: body?.meta?.from || '', to: body?.meta?.to || '', officer: '', status: '',
        })
        return body
      })
      .catch((e) => setProblem(e?.problem || { code: 'request_failed' }))
  }, [])

  useEffect(() => { load(null) }, [load])
  useEffect(() => {
    api.officers().then((d) => setOfficers(d?.officers || [])).catch(() => {})
  }, [])

  function apply(patch) {
    const next = { ...(filters || {}), ...patch }
    setFilters(next)
    load(next)
  }

  async function exportCsv() {
    setBusy(true)
    setExportProblem(null)
    try {
      const out = await api.ptpReportExport(filters || {})
      downloadText(out.filename || 'ptp-report.csv', out.text)
      toast(t('reports.exported'))
    } catch (e) {
      setExportProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  const totals = data?.totals || {}
  const byStatus = Object.entries(totals.by_status || {})
  const sourceWord = (src) => (t(`reports.ptpSource.${src}`) === `reports.ptpSource.${src}` ? src : t(`reports.ptpSource.${src}`))
  return (
    <section className="card">
      <header className="card__head">
        <h2>{t('reports.ptpTitle')}</h2>
        <span className="spacer" />
        <button type="button" className="btn btn--sm" disabled={busy} onClick={exportCsv}>
          {t('reports.ptpExport')}
        </button>
      </header>
      <div className="card__body">
        <div className="ptpfilters">
          <label>
            <span className="eyebrow">{t('reports.ptpFrom')}</span>
            <input className="field" type="date" value={filters?.from || ''}
                   onChange={(e) => apply({ from: e.target.value })} />
          </label>
          <label>
            <span className="eyebrow">{t('reports.ptpTo')}</span>
            <input className="field" type="date" value={filters?.to || ''}
                   onChange={(e) => apply({ to: e.target.value })} />
          </label>
          <label>
            <span className="eyebrow">{t('today.officer')}</span>
            <select className="field" value={filters?.officer || ''}
                    onChange={(e) => apply({ officer: e.target.value })}>
              <option value="">{t('today.officerAll')}</option>
              {officers.map((o) => (
                <option key={o.uid} value={o.uid}>{(lang === 'en' ? o.display_name_en : o.display_name_th) || o.uid}</option>
              ))}
            </select>
          </label>
          <label>
            <span className="eyebrow">{t('record.invState')}</span>
            <select className="field" value={filters?.status || ''}
                    onChange={(e) => apply({ status: e.target.value })}>
              <option value="">{t('reports.ptpAllStatuses')}</option>
              {(data?.meta?.statuses || []).map((s) => <option key={s} value={s}>{t(ptpStatus(s).key)}</option>)}
            </select>
          </label>
        </div>
        <DataTable
          caption={t('reports.ptpTitle')}
          minWidth={860}
          getKey={(r) => r.uid}
          rows={data?.rows || []}
          empty={t('reports.ptpEmpty')}
          columns={[
            { key: 'customer', label: t('record.debtor'), render: (r) => <Link className="scr-link" to={`/customers/${r.customer_uid}`} state={recordState(internalOrigin(location, 'nav.reports'))}>{r.display_name || r.customer_uid}</Link> },
            { key: 'volt', label: t('reports.ptpVolt'), render: (r) => r.volt_id || '—' },
            { key: 'officer', label: t('record.officer'), render: (r) => r.officer_uid || '—' },
            { key: 'date', label: t('reports.ptpDueOn'), render: (r) => fmtDate(r.promise_date) },
            { key: 'amount', label: t('record.invAmount'), num: true, render: (r) => money(r.promised_amount) },
            { key: 'status', label: t('record.invState'), render: (r) => <StatusPill kind={ptpStatus(r.status).kind} title={r.status}>{t(ptpStatus(r.status).key)}</StatusPill> },
            { key: 'source', label: t('reports.ptpSource'), render: (r) => (r.source ? <NeutralChip title={r.source}>{sourceWord(r.source)}</NeutralChip> : '—') },
            { key: 'renegotiated', label: t('reports.ptpRenegotiated'), render: (r) => (r.renegotiation_count ? t('reports.ptpRenegotiatedN', { n: r.renegotiation_count }) : '—') },
            { key: 'lineage', label: t('reports.ptpLineage'), render: (r) => (r.lineage_from_uid ? t('reports.ptpLineageFrom', { uid: r.lineage_from_uid }) : '—') },
          ]}
        />
        <p className="card__note">
          {t('reports.ptpTotal', { n: totals.count ?? 0 })} · {money(totals.promised_amount)}
          {byStatus.length ? ` · ${byStatus.map(([s, v]) => `${t(ptpStatus(s).key)} ${v.count} (${money(v.promised_amount)})`).join(' · ')}` : ''}
        </p>
        <details className="page-note">
          <summary>{t('reports.methodNote')}</summary>
          <p>{t('reports.ptpNote')}</p>
        </details>
        {problem ? <Problem problem={problem} /> : null}
        {exportProblem ? <Problem problem={exportProblem} /> : null}
      </div>
    </section>
  )
}

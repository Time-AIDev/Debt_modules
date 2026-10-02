import { useCallback, useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useIdentity, atLeast } from '../lib/identity.jsx'
import { useCrumb } from '../lib/crumb.jsx'
import { money, pct, date as fmtDate } from '../lib/format.js'
import { KpiCard, Bars, Section } from '../components/Cards.jsx'
import { DataTable } from '../components/DataTable.jsx'
import { StatusPill } from '../components/StatusIcon.jsx'
import { paymentStatus, statusOf } from '../lib/status.js'
import { Drawer } from '../components/Drawer.jsx'
import { Problem, LoadError } from '../components/Problem.jsx'
import { useToast } from '../components/Toast.jsx'
import { useReloadOnEpoch } from '../lib/dataEpoch.jsx'
import { internalOrigin, recordState } from '../lib/origin.js'

/** ภาพรวม: the team's served figures. No customer list — every card links to its lens. */
export function Dashboard() {
  const { t, lang } = usePrefs()
  useIdentity() // subscribe: a role switch re-renders this screen, so the gate below follows it
  const toast = useToast()
  const location = useLocation()
  useCrumb('group.mine', 'nav.dash')
  const [team, setTeam] = useState(null)
  const [weekly, setWeekly] = useState(null)
  const [worker, setWorkbook] = useState(null)
  const [problem, setProblem] = useState(null)
  const [targetOpen, setTargetOpen] = useState(false)
  const [targetDraft, setTargetDraft] = useState('')
  const [targetBusy, setTargetBusy] = useState(false)
  const [targetProblem, setTargetProblem] = useState(null)

  const load = useCallback(() => {
    setProblem(null)
    Promise.all([api.reportsTeam(), api.weeklyReport(), api.workbook({ sort: 'aggregate_overdue', dir: 'desc', limit: 5 })])
      .then(([tm, wk, wb]) => { setTeam(tm); setWeekly(wk); setWorkbook(wb) })
      .catch((e) => setProblem(e?.problem || { code: 'request_failed' }))
  }, [])
  useEffect(() => { load() }, [load])
  useReloadOnEpoch(load)
  const closeTarget = useCallback(() => setTargetOpen(false), [])

  if (problem) return <LoadError problem={problem} onRetry={load} />
  if (!team) return <p className="empty">{t('common.loading')}</p>

  const tm = team.team || {}
  const queues = team.queues || {}
  const weeks = team.receipts_by_month || []
  const roll = team.npl_roll || {}
  const bands = team.aging_bands || []
  const mgmt = weekly?.management_summary || {}
  const cash = mgmt.cash_in || {}
  const targets = mgmt.targets || {}
  const achievement = mgmt.achievement || {}
  const promises = weekly?.promises || {}
  const exposure = (worker?.rows || []).slice(0, 5)
  const bandMax = Math.max(...bands.map((b) => b.customers || 0), 1)
  // Manager and above set the month's cash-in target (the route refuses anyone
  // below); the button is the screen's half of that same bar, never the rule.
  const canSetTarget = atLeast('MANAGER')

  function openTarget() {
    setTargetProblem(null)
    setTargetDraft(tm.target_month ? String(tm.target_month) : '')
    setTargetOpen(true)
  }

  async function saveTarget(value) {
    setTargetBusy(true)
    setTargetProblem(null)
    try {
      await api.putCollectionTargets(team.period.month, { 'cash_received:portfolio': value })
      toast(t('dash.targetSaved'))
      setTargetOpen(false)
      load()
    } catch (e) {
      setTargetProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setTargetBusy(false)
    }
  }

  const fields = [
    { key: 'arrears', label: t('dash.arrears'), value: money(tm.arrears_total), note: t('dash.arrearsNote') },
    { key: 'debtors', label: t('dash.debtors'), value: `${tm.debtors ?? '—'}`, note: t('dash.debtorsNote', { total: tm.cases_total ?? '—' }) },
    { key: 'queue', label: t('dash.queue'), value: `${tm.queue_today ?? '—'}`, note: t('dash.queueNote', { done: tm.queue_done ?? 0 }) },
    { key: 'kept', label: t('dash.kept'), value: pct(tm.ptp_kept_rate), note: t('dash.keptNote', { kept: tm.ptps_kept ?? 0, decided: tm.ptps_decided ?? 0 }) },
    { key: 'npl', label: t('dash.npl'), value: `${tm.npl_count ?? '—'}`, note: t('dash.nplNote') },
  ]

  const kpis = [
    {
      key: 'attainment', label: t('dash.attainment'), value: pct(tm.attainment),
      sub: t('dash.attainmentSub', { got: money(tm.receipts_month), target: money(tm.target_month) }),
      note: tm.attainment_note_th || '',
      barPct: tm.target_month ? Number(String(tm.attainment || 0).replace('%', '')) : null,
      barColor: 'var(--volt-green)',
      // Below manager the control stays visible, disabled with its reason (GUD-002).
      action: team.period?.month ? (
        <>
          <button type="button" className="btn btn--sm" disabled={!canSetTarget} onClick={openTarget}
                  title={canSetTarget ? undefined : t('dash.managerOnly')}>
            {t('dash.setTarget')}
          </button>
          {canSetTarget ? null : <span className="scr-meta">{t('dash.managerOnly')}</span>}
        </>
      ) : null,
    },
    { key: 'ptp', label: t('dash.ptpKept'), value: pct(tm.ptp_kept_rate_week), sub: t('dash.ptpSub', { kept: tm.ptps_kept_week ?? 0, decided: tm.ptps_decided_week ?? 0 }), note: t('dash.ptpNote', { delta: tm.ptp_kept_rate_delta_pts ?? '—' }), barPct: tm.ptp_kept_target_pct ? Number(String(tm.ptp_kept_rate_week || 0).replace('%', '')) : null, barColor: 'var(--volt-green)' },
    { key: 'contact', label: t('dash.contact'), value: pct(tm.contact_success_rate), sub: t('dash.contactSub', { reached: tm.reached_contacts ?? 0, all: tm.contacts ?? 0 }), note: tm.contact_scope_note_th || '', barPct: tm.contact_target_pct ? Number(String(tm.contact_success_rate || 0).replace('%', '')) : null, barColor: 'var(--volt-green)' },
    { key: 'dso', label: t('dash.dso'), value: tm.dso_days !== null && tm.dso_days !== undefined ? `${tm.dso_days} ${t('dash.days')}` : '—', sub: t('dash.dsoSub', { prior: tm.dso_prior_month_days ?? '—' }), note: tm.dso_note_th || '', barPct: tm.dso_target_days ? Math.min(100, Math.round((tm.dso_days / (tm.dso_target_days * 1.5)) * 100)) : null, barColor: 'var(--volt-ink-2)' },
  ]

  return (
    <div className="stack">
      <section className="card">
        <div className="scr-head">
          <div className="scr-head__id">
            <span className="eyebrow">{t('dash.eyebrow')}</span>
            <h1>{t('dash.title')}</h1>
            <p className="scr-meta">{t('dash.sub', { date: fmtDate(team.period?.business_date), officers: team.period?.officers ?? '—' })}</p>
          </div>
          <span className="scr-meta">{lang === 'en' ? team.period?.month_label_en : team.period?.month_label_th}</span>
        </div>
        <div className="scr-facts">
          {fields.map((f) => (
            <div className="scr-fact" key={f.key}>
              <span className="eyebrow">{f.label}</span>
              <span className="scr-value">{f.value}</span>
              <span className="scr-meta">{f.note}</span>
            </div>
          ))}
        </div>
      </section>

      <div className="money4">
        {kpis.map(({ key, ...card }) => <KpiCard key={key} {...card} />)}
      </div>

      <div className="grid2">
        <Section title={t('dash.trend')} note={t('dash.trendNote')}>
          <Bars
            label={t('dash.trend')}
            unit={weeks.some((w) => w.target) ? t('dash.trendUnit') : undefined}
            bars={weeks.map((w) => ({
              key: w.month,
              label: lang === 'en' ? w.label_en : w.label_th,
              value: w.attainment ? pct(w.attainment) : money(w.total),
              barPct: w.attainment_bar_pct ? Number(w.attainment_bar_pct) : 2,
              color: w.attainment_bar_pct ? (w.current ? 'var(--volt-ink)' : 'var(--volt-ink-2)') : 'var(--volt-warm)',
            }))}
          />
        </Section>
        <Section title={t('dash.roll')} note={t('dash.rollNote')}>
          <ul className="rows">
            {[['in', roll.rolled_in, 'NPL'], ['out', roll.rolled_out, 'CURRENT'], ['still', roll.still_npl, 'NPL']].map(([key, part, pay]) => (
              <li key={key} className="rows__row">
                <StatusPill kind={paymentStatus(pay).kind}>{t(`dash.roll.${key}`)}</StatusPill>
                <span className="rows__main">{part?.customers ?? 0} {t('dash.customers')}</span>
                <span className="num">{money(part?.amount)}</span>
              </li>
            ))}
          </ul>
        </Section>
      </div>

      <div className="grid2">
        <Section title={t('dash.aging')} note={t('dash.agingNote', { set: team.band_set_code || '—' })}>
          <Bars
            label={t('dash.aging')}
            bars={bands.map((b) => ({
              key: b.code,
              label: lang === 'en' ? b.label_en : b.label_th,
              value: `${b.customers}`,
              barPct: Math.round(((b.customers || 0) / bandMax) * 100),
              color: b.code === 'NPL_CONFIRMED' ? 'var(--volt-ink)' : b.code === 'CURRENT' ? 'var(--volt-green)' : 'var(--volt-ink-2)',
            }))}
          />
        </Section>
        <Section title={t('dash.target')} note={t('dash.targetNote')}>
          <ul className="rows">
            {['total', 'instalment', 'cash_or_project'].map((key) => (
              <li key={key} className="rows__row">
                <span className="rows__main">{t(`dash.cash.${key}`)}</span>
                <span className="num">{money(cash[key])}</span>
                <span className="num">{targets[key] ? `${money(targets[key])} · ${pct(achievement[key])}` : t('dash.noTarget')}</span>
              </li>
            ))}
          </ul>
          <p className="scr-meta" style={{ marginTop: 8 }}>{t('dash.promisesLine', { kept: promises.kept ?? 0, broken: promises.broken ?? 0, open: promises.open ?? 0 })}</p>
        </Section>
      </div>

      <Section title={t('dash.team')} note={t('dash.teamNote')}>
        <DataTable
          caption={t('dash.team')}
          minWidth={820}
          getKey={(r) => r.officer_uid || 'total'}
          rows={[...(team.officers || []), ...(team.officers_total ? [team.officers_total] : [])]}
          columns={[
            { key: 'name', label: t('dash.officer'), render: (r) => (
              <span className="stack" style={{ gap: 1 }}>
                <span style={{ fontWeight: 600 }}>{lang === 'en' ? r.display_name_en : r.display_name}</span>
                {r.officer_uid ? <span className="scr-meta">{t('dash.queueLine', { done: r.queue_done ?? 0, total: r.queue_today ?? 0 })}</span> : null}
              </span>
            ) },
            { key: 'cases', label: t('dash.cases'), num: true, render: (r) => r.cases ?? '—' },
            { key: 'arrears', label: t('dash.arrearsCol'), num: true, render: (r) => money(r.arrears) },
            { key: 'receipts', label: t('dash.receipts'), num: true, render: (r) => money(r.receipts_month) },
            { key: 'contact', label: t('dash.contactRate'), num: true, render: (r) => pct(r.contact_rate) },
            { key: 'ptp', label: t('dash.ptpRate'), num: true, render: (r) => pct(r.ptp_kept_rate) },
            { key: 'npl', label: t('dash.nplCol'), num: true, render: (r) => r.npl_count ?? '—' },
          ]}
        />
      </Section>

      <div className="grid2">
        <Section title={t('dash.exposure')}>
          <ul className="rows">
            {exposure.map((row) => (
              <li key={row.customer.uid} className="rows__row">
                <Link to={`/customers/${row.customer.uid}`}
                      state={recordState(internalOrigin(location, 'nav.dash'))}
                      className="rows__main scr-link">{row.customer.display_name}</Link>
                <span className="num">{row.oldest_dpd === null ? t('today.dpdNone') : `DPD ${row.oldest_dpd}`}</span>
                <span className="num">{money(row.aggregate_overdue)}</span>
              </li>
            ))}
          </ul>
        </Section>
        <Section title={t('dash.next')}>
          <ul className="rows">
            {[
              ['/reviews', t('nav.reviews'), queues.reviews_open],
              ['/?workstream=pre_install', t('nav.pipeline'), queues.pipeline],
              ['/payments', t('nav.payments'), queues.peak_not_approved],
              ['/recovery', t('nav.recovery'), queues.npl_cases],
            ].map(([to, label, count]) => (
              <li key={to} className="rows__row">
                <StatusPill kind={statusOf('queue', count ? 'WAITING' : 'CLEAR').kind} title={t(statusOf('queue', count ? 'WAITING' : 'CLEAR').key)}>
                  <span className="num">{count ?? 0}</span>
                </StatusPill>
                <Link to={to} className="rows__main scr-link">{label}</Link>
              </li>
            ))}
          </ul>
        </Section>
      </div>

      <Drawer
        open={targetOpen}
        onClose={closeTarget}
        title={t('dash.targetTitle')}
        subtitle={`${lang === 'en' ? team.period?.month_label_en : team.period?.month_label_th} · ${t('dash.managerOnly')}`}
        footer={(
          <>
            <button type="button" className="btn" disabled={targetBusy} onClick={() => saveTarget('')}>
              {t('dash.targetClear')}
            </button>
            <span className="spacer" />
            <button type="button" className="btn" onClick={closeTarget}>{t('common.cancel')}</button>
            <button type="button" className="btn btn--primary" disabled={targetBusy}
                    onClick={() => saveTarget(targetDraft.trim())}>
              {t('common.save')}
            </button>
          </>
        )}
      >
        <label>
          <span className="eyebrow">{t('dash.targetAmount')}</span>
          <input className="field" type="text" inputMode="numeric" pattern="[0-9]*"
                 aria-label={t('dash.targetAmount')} value={targetDraft}
                 onChange={(e) => setTargetDraft(e.target.value)} />
        </label>
        <p className="drawer__hint">{t('dash.targetHint')}</p>
        {tm.target_month_source === 'CONFIG_DEFAULT' ? (
          <p className="drawer__hint">{t('dash.targetConfigDefault')}</p>
        ) : null}
        {targetProblem ? <Problem problem={targetProblem} /> : null}
      </Drawer>
    </div>
  )
}

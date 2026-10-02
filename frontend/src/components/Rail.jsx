import { NavLink } from 'react-router-dom'
import logo from '../assets/volt-logo-lockup.png'
import { usePrefs } from '../lib/prefs.jsx'
import { NAV_GROUPS } from '../lib/nav.js'
import { money } from '../lib/format.js'

function Icon({ path }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="rail__icon">
      <path d={path} />
    </svg>
  )
}

/**
 * The dark rail: wordmark, KPI strip, grouped nav, caseload footer. Counts come from
 * /v1/shell/summary — this component never invents one. Amber marks where the user is.
 */
export function Rail({ summary }) {
  const { t, lang, railOpen, railWidth, setRailOpen } = usePrefs()
  const badges = summary?.badges || {}
  const kpi = summary?.kpi || {}
  const workload = summary?.workload || {}
  const kpiPct = kpi.achieved ? Number(String(kpi.achieved).replace('%', '')) : null
  const workloadPct = workload.bar_pct !== undefined && workload.bar_pct !== null ? Number(workload.bar_pct) : null
  const hasTarget = kpi.target !== null && kpi.target !== undefined
  const kpiValue = money(kpi.value)
  const kpiTarget = money(kpi.target)
  const hasCap = workload.cap !== null && workload.cap !== undefined
  const capNote = lang === 'en' ? workload.cap_note_en : workload.cap_note_th

  return (
    <aside className={`rail${railOpen ? '' : ' rail--closed'}`} style={{ width: railOpen ? (railWidth === 'narrow' ? 204 : 248) : 60 }}>
      <div className="rail__head">
        {railOpen ? (
          <span className="rail__brand">
            <img src={logo} alt="VOLT" className="rail__logo" />
            <span className="rail__descriptor">{t('rail.descriptor')}</span>
          </span>
        ) : (
          <img src={logo} alt="VOLT" className="rail__logo rail__logo--mark" />
        )}
        <button
          type="button"
          className="rail__toggle"
          onClick={() => setRailOpen(!railOpen)}
          title={t(railOpen ? 'rail.toggleOpen' : 'rail.toggleClosed')}
          aria-expanded={railOpen}
        >
          <svg viewBox="0 0 10 10" aria-hidden="true" className={railOpen ? '' : 'rail__caret--flip'}>
            <path d="M6.5 1.5 3 5l3.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>

      {railOpen && (
        <div className="rail__kpi">
          <span className="rail__eyebrow">{t('rail.kpi')}</span>
          <span className="rail__kpiValue num">{hasTarget ? (kpi.achieved || kpiValue) : kpiValue}</span>
          {hasTarget ? (
            <>
              <span className="rail__bar"><span style={{ width: `${kpiPct ?? 0}%` }} /></span>
              <span className="rail__kpiNote">{t('rail.kpiLine', { value: kpiValue, target: kpiTarget })}</span>
            </>
          ) : (
            <span className="rail__kpiNote">{kpi.week_label || kpi.period || '—'}</span>
          )}
        </div>
      )}

      <nav className="rail__nav" aria-label={t('app.brand')}>
        {NAV_GROUPS.map((group, gi) => (
          <div className="rail__group" key={group.label || `g${gi}`}>
            {group.label && railOpen ? <p className="rail__eyebrow rail__groupLabel">{t(group.label)}</p> : null}
            {group.items.map((item) => {
              const count = item.badge ? badges[item.badge] : null
              return (
                <NavLink
                  key={item.id}
                  to={item.to}
                  end={item.to === '/'}
                  className={({ isActive }) => `rail__link${isActive ? ' rail__link--on' : ''}`}
                  title={t(`nav.${item.id}`)}
                >
                  <Icon path={item.icon} />
                  {railOpen ? <span className="rail__label">{t(`nav.${item.id}`)}</span> : null}
                  {count !== null && count !== undefined ? (
                    <span className={`rail__count${railOpen ? '' : ' rail__count--dot'}`}>{count}</span>
                  ) : null}
                </NavLink>
              )
            })}
          </div>
        ))}
      </nav>

      {railOpen && (
        <div className="rail__foot">
          <span className="rail__eyebrow">{t('rail.caseload')}</span>
          <span className="rail__footLine">
            {hasCap
              ? t('rail.caseloadLine', { caseload: workload.caseload ?? '—', cap: workload.cap })
              : (capNote || t('rail.caseloadLine', { caseload: workload.caseload ?? '—', cap: '—' }))}
          </span>
          {workload.contact_denominator ? (
            <span className="rail__kpiNote">{t('rail.caseloadMeasured', { n: workload.contact_denominator })}</span>
          ) : null}
          {hasCap ? (
            <span className="rail__bar"><span style={{ width: `${workloadPct ?? 0}%`, background: 'var(--viz-sev-3)' }} /></span>
          ) : null}
        </div>
      )}
    </aside>
  )
}

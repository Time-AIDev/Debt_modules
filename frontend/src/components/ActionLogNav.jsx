import { NavLink } from 'react-router-dom'
import { usePrefs } from '../lib/prefs.jsx'

export function ActionLogNav() {
  const { t } = usePrefs()
  return <nav className="history-tabs" aria-label={t('history.navigation')}>
    {[
      ['/audit', 'nav.audit'],
      ['/audit/accounting-reviews', 'history.accounting'],
      ['/audit/terminated', 'nav.terminated'],
    ].map(([to, key]) => <NavLink key={to} to={to} end={to === '/audit'}
      className={({ isActive }) => `btn btn--sm${isActive ? ' btn--primary' : ''}`}>{t(key)}</NavLink>)}
  </nav>
}

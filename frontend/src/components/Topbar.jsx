import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useIdentity, setRole, ROLES, roleLabel } from '../lib/identity.jsx'
import { Popover } from './Popover.jsx'
import { SegmentedControl } from './SegmentedControl.jsx'

/** Search trigger, breadcrumbs, env chip, View popover, identity menu. */
export function Topbar({ crumb, searchLabel, onSearch }) {
  const {
    t, lang, theme, density, railWidth,
    setLang, setTheme, setDensity, setRailWidth, setRailOpen, railOpen,
  } = usePrefs()
  const identity = useIdentity()
  const [viewOpen, setViewOpen] = useState(false)
  const [idOpen, setIdOpen] = useState(false)
  const parent = crumb?.parent
  const internalParent = typeof parent?.to === 'string' && parent.to.startsWith('/') && !parent.to.startsWith('//')

  return (
    <header className="topbar">
      <button type="button" className="searchbox" onClick={onSearch}>
        <svg viewBox="0 0 24 24" aria-hidden="true" className="searchbox__icon">
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.5-3.5" />
        </svg>
        <span className="searchbox__label">{searchLabel || t('shell.search')}</span>
        <span className="searchbox__key">⌘K</span>
      </button>

      <nav className="crumbs" aria-label={t('shell.breadcrumb')}>
        {internalParent ? <Link to={parent.to} state={parent.state}>{parent.label || crumb.group}</Link> : <span>{crumb.group}</span>}
        <span className="crumbs__sep" aria-hidden="true">›</span>
        <span className="crumbs__page">{crumb.page}</span>
      </nav>

      <span className="spacer" />

      <span className="envchip">
        <span className="envchip__dot" aria-hidden="true" />
        {t('shell.env')}
      </span>

      <div className="topbar__menu">
        <button type="button" className="btn btn--sm" aria-expanded={viewOpen} onClick={() => setViewOpen(!viewOpen)}>
          {t('shell.view')}
        </button>
        <Popover open={viewOpen} onClose={() => setViewOpen(false)} label={t('shell.view')}>
          <div className="popover__field">
            <span className="eyebrow">{t('shell.density')}</span>
            <SegmentedControl
              label={t('shell.density')}
              value={density}
              onChange={setDensity}
              options={[{ id: 'comfortable', label: t('shell.roomy') }, { id: 'compact', label: t('shell.compact') }]}
            />
          </div>
          <div className="popover__field">
            <span className="eyebrow">{t('shell.theme')}</span>
            <SegmentedControl
              label={t('shell.theme')}
              value={theme}
              onChange={setTheme}
              options={[{ id: 'dark', label: t('shell.dark') }, { id: 'light', label: t('shell.light') }]}
            />
          </div>
          <div className="popover__field">
            <span className="eyebrow">{t('shell.railWidth')}</span>
            <SegmentedControl
              label={t('shell.railWidth')}
              value={railWidth}
              onChange={(v) => { setRailWidth(v); setRailOpen(true) }}
              options={[{ id: 'normal', label: t('shell.railNormal') }, { id: 'narrow', label: t('shell.railNarrow') }]}
            />
          </div>
          <div className="popover__field">
            <span className="eyebrow">{t('shell.language')}</span>
            <SegmentedControl
              label={t('shell.language')}
              value={lang}
              onChange={setLang}
              options={[{ id: 'th', label: 'ไทย' }, { id: 'en', label: 'English' }]}
            />
          </div>
        </Popover>
      </div>

      <div className="topbar__menu">
        <button type="button" className="identity" aria-expanded={idOpen} onClick={() => setIdOpen(!idOpen)}>
          <span className="identity__avatar" aria-hidden="true">{identity.name.slice(0, 1) || '—'}</span>
          <span className="identity__text">
            <span className="identity__role">{roleLabel(identity.role, lang)}</span>
            <span className="identity__name">{identity.name}</span>
          </span>
        </button>
        <Popover open={idOpen} onClose={() => setIdOpen(false)} label={t('shell.signRole')} width={230}>
          <span className="eyebrow">{t('shell.signRole')}</span>
          <div className="identity__roles">
            {ROLES.map((r) => (
              <button
                key={r}
                type="button"
                className={`choice__btn${r === identity.role ? ' choice__btn--on' : ''}`}
                aria-checked={r === identity.role}
                role="radio"
                disabled={identity.locked && r !== identity.role}
                onClick={() => { setRole(r); setIdOpen(false) }}
              >
                {roleLabel(r, lang)}
              </button>
            ))}
          </div>
          <p className="popover__note">{t('shell.signNote')}</p>
          {identity.session ? (
            <button
              type="button"
              className="btn btn--sm"
              onClick={async () => {
                try { await api.authLogout() } catch { /* the gate re-reads on next call */ }
                window.dispatchEvent(new Event('volt:auth-required'))
                setIdOpen(false)
              }}
            >
              {t('shell.signOut')}
            </button>
          ) : null}
        </Popover>
      </div>
      <span className="sr-only" data-testid="rail-open-state">{railOpen ? 'open' : 'closed'}</span>
    </header>
  )
}

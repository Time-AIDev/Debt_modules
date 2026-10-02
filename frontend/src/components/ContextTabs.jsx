import { usePrefs } from '../lib/prefs.jsx'

/**
 * The tab strip under the topbar: the active lens plus up to four recent records.
 * A tab's dot carries the served risk severity, never a decorative colour.
 * F13 / TASK-017: each recent tab has its own close control — closing removes the
 * tab and never navigates (the page stays where it is).
 */
export function ContextTabs({ current, recents }) {
  const { t } = usePrefs()
  return (
    <div className="ctxtabs" role="tablist" aria-label="tabs">
      <span className="ctxtab ctxtab--on" role="tab" aria-selected="true">
        <span className="ctxtab__dot ctxtab__dot--brand" aria-hidden="true" />
        <span className="ctxtab__label">{current.label}</span>
        {current.meta ? <span className="ctxtab__meta">{current.meta}</span> : null}
      </span>
      {recents.map((r) => (
        <div key={r.key} role="tab" aria-selected={!!r.current}
             className={`ctxtab${r.current ? ' ctxtab--rec' : ''}`}>
          <button type="button" className="ctxtab__open" onClick={r.onOpen}>
            <span className="ctxtab__dot" style={{ background: r.color }} aria-hidden="true" />
            <span className="ctxtab__label">{r.label}</span>
            {r.meta ? <span className="ctxtab__meta">{r.meta}</span> : null}
          </button>
          <button type="button" className="ctxtab__close" aria-label={t('shell.closeTab', { label: r.label })}
                  onClick={(e) => { e.stopPropagation(); r.onClose?.() }}>
            ×
          </button>
        </div>
      ))}
    </div>
  )
}

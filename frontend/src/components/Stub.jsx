import { useCrumb } from '../lib/crumb.jsx'
import { usePrefs } from '../lib/prefs.jsx'

/** Placeholder lens body used until the phase that builds it lands. */
export function Stub({ titleKey, groupKey = 'group.system', phase }) {
  const { t } = usePrefs()
  useCrumb(groupKey, titleKey)
  return (
    <section className="card">
      <header className="card__head"><h1 className="stub__title">{t(titleKey)}</h1></header>
      <div className="card__body">
        <p>{phase ? `Phase ${phase}` : ''}</p>
      </div>
    </section>
  )
}

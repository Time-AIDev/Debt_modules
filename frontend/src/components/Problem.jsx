import { usePrefs } from '../lib/prefs.jsx'
import { StatusIcon, NeutralChip } from './StatusIcon.jsx'

/**
 * RFC 9457 refusal, always visible (brief §3.4): the served sentence in the active
 * language is the headline — never the server's English `title` on a Thai screen — the
 * precondition list when the refusal carries `extensions`, per-row errors, and the code
 * kept in the title attribute and data-code (never the headline).
 */
export function Problem({ problem, onRetry }) {
  const { lang, t } = usePrefs()
  if (!problem) return null
  const headline = (lang === 'en'
    ? problem.message_en || problem.detail || problem.title
    : problem.message_th) || t('problem.title')
  // A refusal with no Thai sentence (a client-made one) still says what it served.
  const body = lang !== 'en' && !problem.message_th ? problem.detail : null
  const preconditions = problem.extensions?.preconditions || []
  const errors = Array.isArray(problem.errors) ? problem.errors : []
  return (
    <div className="problem" role="alert" data-code={problem.code} title={problem.code}>
      <p className="problem__head">
        <StatusIcon kind="problem" />
        <span className="problem__title">{headline}</span>
        {problem.retryable ? <NeutralChip>{t('problem.retryable')}</NeutralChip> : null}
      </p>
      {body ? <p className="problem__msg">{body}</p> : null}
      {preconditions.length > 0 && (
        <ul className="problem__list">
          <li className="problem__listHead">{t('problem.preconditions')}</li>
          {preconditions.map((p, i) => (
            <li key={p.code || i}>
              <StatusIcon kind={p.met ? 'done' : 'idle'} size={14} />
              <span>{lang === 'en' ? p.label_en || p.label_th || p.code : p.label_th || p.label_en || p.code}</span>
            </li>
          ))}
        </ul>
      )}
      {errors.length > 0 && (
        <ul className="problem__list">
          {errors.map((e, i) => (
            <li key={`${e.pointer || i}`}>
              {(lang === 'en' ? e.message : e.message_th || e.message) || e.code}
            </li>
          ))}
        </ul>
      )}
      {onRetry ? (
        <button type="button" className="btn btn--sm" onClick={onRetry}>{t('common.retry')}</button>
      ) : null}
    </div>
  )
}

/** A screen-level load failure: same envelope, retry affordance. */
export function LoadError({ problem, onRetry }) {
  return <div className="load-error"><Problem problem={problem} onRetry={onRetry} /></div>
}

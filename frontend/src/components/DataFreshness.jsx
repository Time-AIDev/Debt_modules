import { useState } from 'react'
import { Link } from 'react-router-dom'
import { date, when } from '../lib/format.js'
import { refreshImports, useDataState } from '../lib/dataEpoch.jsx'
import { usePrefs } from '../lib/prefs.jsx'
import { StatusIcon } from './StatusIcon.jsx'

/**
 * One freshness line for the screens that show imported facts.
 *
 * Shows which source the served book came from and when it was imported (the
 * serving block of the shared data-state read), the applied PEAK report date when
 * there is one, and — only when this session is genuinely behind — the stale
 * banner with its own update action. Before this, the same facts were spread over
 * the rail, the workbook header, a Today hint, the Data sources chain card and a
 * separate banner, each fetching its own state.
 */
export function DataFreshness({ className }) {
  const { t } = usePrefs()
  const state = useDataState()
  const [busy, setBusy] = useState(false)

  if (!state) return null
  const serving = state.serving || {}
  const stale = Boolean(state.stale)
  const peakAsOf = state.peak_as_of
  const line = t('data.freshness', { source: serving.serving_name || '—', on: when(serving.imported_at) || '—' })
  const peak = peakAsOf ? t('today.peakAsOf', { on: date(peakAsOf) }) : null

  async function run() {
    setBusy(true)
    try {
      await refreshImports()
    } catch { /* the shared state redraws with whatever the server says now */ }
    setBusy(false)
  }

  return (
    <div className={`freshness${stale ? ' freshness--stale' : ''}${className ? ` ${className}` : ''}`} role="status">
      {/* The whole sentence rides in the title: a narrow bar may cut the line, never the fact. */}
      <span className="freshness__line" title={peak ? `${line} · ${peak}` : line}>
        {line}
        {peak ? (
          <>
            {' · '}
            <Link to="/data-sources#peak-report">{peak}</Link>
          </>
        ) : null}
      </span>
      {stale ? (
        <>
          <span className="freshness__stale" title={t('data.staleBanner')}><StatusIcon kind="do" />{t('data.staleBanner')}</span>
          <span className="spacer" />
          <button type="button" className="btn btn--sm" disabled={busy} onClick={run}>
            {t('data.staleRefresh')}
          </button>
        </>
      ) : null}
    </div>
  )
}

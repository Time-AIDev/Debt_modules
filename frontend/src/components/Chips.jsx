import { severityColor } from '../lib/format.js'
import { usePrefs } from '../lib/prefs.jsx'
import { paymentStatus, tierStatus, peakDocStatus } from '../lib/status.js'
import { StatusPill, NeutralChip } from './StatusIcon.jsx'

/** The legacy toned chip, kept for its callers; its tones sit on the Volt palette. */
export function Chip({ tone = 'neutral', children, title }) {
  const cls = tone === 'neutral' ? 'chip' : `chip chip--${tone}`
  return <span className={cls} title={title}>{children}</span>
}

/** Payment status → the shared status pill (brief §3.2); a served label wins over the word. */
export function StatusChip({ code, label }) {
  const { t } = usePrefs()
  const s = paymentStatus(code)
  return <StatusPill kind={s.kind} title={code}>{label || t(s.key)}</StatusPill>
}

/** The aging band: a neutral fact, not a status. */
export function BandChip({ bucket, bandSet, label }) {
  return <NeutralChip title={bandSet || undefined}>{label || bucket || '—'}</NeutralChip>
}

export function SeverityRail({ score }) {
  return <span className="sev-rail" style={{ background: severityColor(score) }} aria-hidden="true" />
}

/** A Today tier → its status pill; the served tier label wins over the word. */
export function TierChip({ code, label }) {
  const { t } = usePrefs()
  const s = tierStatus(code)
  return <StatusPill kind={s.kind} title={code}>{label || t(s.key)}</StatusPill>
}

/** A PEAK document's state → its status pill. */
export function PeakChip({ state, label }) {
  const { t } = usePrefs()
  const s = peakDocStatus(state)
  return <StatusPill kind={s.kind} title={state}>{label || t(s.key)}</StatusPill>
}

export function EntityChip({ entity }) {
  if (!entity) return null
  return <NeutralChip title={entity}>{entity}</NeutralChip>
}

export function SourceChip({ source }) {
  const mark = source && typeof source === 'object' ? source.identity || source.history : source
  if (!mark || mark === 'SYNTHETIC') return null
  return <NeutralChip title={`data_source: ${mark}`}>{mark}</NeutralChip>
}

/** Today's legal contact already used by someone: the lock pill. */
export function LockChip({ lockedBy }) {
  const { t } = usePrefs()
  return <StatusPill kind="lock">{t('status.today.LOCKED', { who: lockedBy || '—' })}</StatusPill>
}

import { movingKind } from '../lib/status.js'

export { movingKind }

// Brief §3.2: eight shapes, ONE meaning everywhere; the geometry is the design
// sprite's `st-*` symbols. Each glyph paints its token colour through currentColor
// (set per kind below, so dark mode follows the tokens); the symbol inside a
// yellow/green disc stays #111E2A (always on a light fill) and the "!" stays white.
const ON_FILL = '#111E2A'
const COLOR = {
  do: 'var(--volt-yellow)',
  problem: 'var(--volt-red)',
  done: 'var(--volt-green)',
  moneyin: 'var(--volt-green)',
  'moving-1': 'var(--volt-ink)',
  'moving-2': 'var(--volt-ink)',
  'moving-3': 'var(--volt-ink)',
  'moving-4': 'var(--volt-ink)',
  idle: 'var(--volt-ink-2)',
  off: 'var(--volt-ink-2)',
  lock: 'var(--volt-ink-2)',
}

const ring = <circle cx="8" cy="8" r="6.9" fill="none" stroke="currentColor" strokeWidth="1.4" />
const round = { strokeLinecap: 'round', strokeLinejoin: 'round' }

const GLYPHS = {
  do: (
    <>
      <circle cx="8" cy="8" r="8" fill="currentColor" />
      <path d="M8 4.3v3.9l2.6 1.5" fill="none" stroke={ON_FILL} strokeWidth="1.6" {...round} />
    </>
  ),
  problem: (
    <>
      <path d="M8 1.3 15.3 14.3H.7Z" fill="currentColor" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
      <path d="M8 5.7v3.9" stroke="#FFFFFF" strokeWidth="1.7" strokeLinecap="round" />
      <circle cx="8" cy="11.9" r="1" fill="#FFFFFF" />
    </>
  ),
  'moving-1': <>{ring}<path d="M8 8V3.4A4.6 4.6 0 0 1 12.6 8Z" fill="currentColor" /></>,
  'moving-2': <>{ring}<path d="M8 3.4A4.6 4.6 0 0 1 8 12.6Z" fill="currentColor" /></>,
  'moving-3': <>{ring}<path d="M8 8V3.4A4.6 4.6 0 1 1 3.4 8Z" fill="currentColor" /></>,
  'moving-4': <>{ring}<circle cx="8" cy="8" r="4.6" fill="currentColor" /></>,
  idle: ring,
  done: (
    <>
      <circle cx="8" cy="8" r="8" fill="currentColor" />
      <path d="M4.7 8.3l2.2 2.2 4.4-4.6" fill="none" stroke={ON_FILL} strokeWidth="1.7" {...round} />
    </>
  ),
  off: <>{ring}<path d="M3.2 12.8 12.8 3.2" stroke="currentColor" strokeWidth="1.4" /></>,
  moneyin: (
    <>
      <circle cx="8" cy="8" r="8" fill="currentColor" />
      <path d="M8 3.9v5.4M5.7 7.2 8 9.5l2.3-2.3M5 11.9h6" fill="none" stroke={ON_FILL} strokeWidth="1.5" {...round} />
    </>
  ),
  lock: (
    <>
      <rect x="3.2" y="7" width="9.6" height="7" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path d="M5.6 7V5.1a2.4 2.4 0 0 1 4.8 0V7" fill="none" stroke="currentColor" strokeWidth="1.4" />
    </>
  ),
}

/**
 * One status glyph. Decorative (aria-hidden) unless `title` names it — then it is an
 * image with that name. Never alone on screen: a word or a number sits next to it.
 * An unknown kind draws `idle`.
 */
export function StatusIcon({ kind, size = 16, title, className }) {
  const k = GLYPHS[kind] ? kind : 'idle'
  const a11y = title ? { role: 'img' } : { 'aria-hidden': 'true' }
  return (
    <svg viewBox="0 0 16 16" width={size} height={size} focusable="false" {...a11y}
         className={`st st--${k}${className ? ` ${className}` : ''}`} style={{ color: COLOR[k] }}>
      {title ? <title>{title}</title> : null}
      {GLYPHS[k]}
    </svg>
  )
}

const FAMILY = { do: 'do', problem: 'problem', done: 'done', moneyin: 'done' }

/** Status pill = icon 14 + word; the ground follows the icon family (do · problem · done · warm). */
export function StatusPill({ kind, children, title, size = 14 }) {
  return (
    <span className={`pill pill--${FAMILY[kind] || 'warm'}`} title={title}>
      <StatusIcon kind={kind} size={size} />
      {children}
    </span>
  )
}

/** A fact with no status meaning: DC status, aging band, entity, source, NPL type, "นับตามกฎหมาย". */
export function NeutralChip({ children, title }) {
  return <span className="chip" title={title}>{children}</span>
}

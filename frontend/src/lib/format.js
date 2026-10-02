// Presentation-only formatters. Money arrives as a served decimal string; this file
// never computes money, it only lays it out. (`toFixed` on a served value would be
// arithmetic in the view; the API Layer convention forbids that.)

const MONEY = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})
const INT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })

/** 'YYYY-MM' as a month name: "ก.ย. 2569" / "Sep 2026". */
export function monthLabel(month, lang = 'th') {
  if (!month) return '—'
  const [y, m] = String(month).split('-').map(Number)
  return new Intl.DateTimeFormat(lang === 'en' ? 'en-GB' : 'th-TH', { month: 'short', year: 'numeric' })
    .format(new Date(y, m - 1, 1))
}

export function money(value) {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  return Number.isFinite(n) ? MONEY.format(n) : '—'
}

export function int(value) {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  return Number.isFinite(n) ? INT.format(n) : '—'
}

/** A served "62.4%" string stays a string; this only supplies the % when absent. */
export function pct(value) {
  if (value === null || value === undefined || value === '') return '—'
  const s = String(value)
  return s.endsWith('%') ? s : `${s}%`
}

/** ISO date → the console's dd/mm/yyyy, Gregorian. */
export function date(iso) {
  if (!iso) return '—'
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso))
  return m ? `${m[3]}/${m[2]}/${m[1]}` : String(iso)
}

/** ISO date → dd/mm (list rows). */
export function dateShort(iso) {
  if (!iso) return '—'
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso))
  return m ? `${m[3]}/${m[2]}` : String(iso)
}

/** ISO timestamp → dd/mm hh:mm (audit rows, contact times). */
export function when(iso) {
  if (!iso) return '—'
  const s = String(iso)
  const d = /^(\d{4})-(\d{2})-(\d{2})/.exec(s)
  const t = /[T ](\d{2}):(\d{2})/.exec(s)
  if (!d) return s
  return `${d[3]}/${d[2]}${t ? ` ${t[1]}:${t[2]}` : ''}`
}

/** DPD at or past the overdue line (30 days). The one threshold the list marks. */
export function dpdTone(dpd) {
  const n = Number(dpd)
  return Number.isFinite(n) && n >= 30 ? 'over' : 'idle'
}

/** Seven-tier severity from a served 0–100 risk score. Presentation rank only. */
export function severity(score) {
  const n = Number(score)
  if (!Number.isFinite(n)) return 2
  if (n >= 85) return 5
  if (n >= 65) return 4
  if (n >= 40) return 3
  if (n >= 20) return 2
  return 1
}

export function severityColor(n) {
  return `var(--viz-sev-${severity(n)})`
}

function toLocalIso(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** Monday of the week containing an ISO date (calendar grid). Local-time safe. */
export function mondayOf(iso) {
  const [y, m, d] = String(iso).split('-').map(Number)
  const date = new Date(y, m - 1, d)
  const offset = (date.getDay() + 6) % 7
  date.setDate(date.getDate() - offset)
  return toLocalIso(date)
}

export function addDays(iso, n) {
  const [y, m, d] = String(iso).split('-').map(Number)
  const date = new Date(y, m - 1, d + n)
  return toLocalIso(date)
}

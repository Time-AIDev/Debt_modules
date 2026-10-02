import { usePrefs } from '../lib/prefs.jsx'
import { StatusIcon } from './StatusIcon.jsx'
import { Icon } from './Icon.jsx'

/**
 * The list-panel card (final design, spec-main §3.1): a head (the meta line with the
 * sort toggle, then the filter), `pinned` blocks that stay put above the rows, the
 * collapsible groups (the only part that scrolls) and a footer line. The panel draws
 * served content only; group counts and labels come from the caller. `hideTitle`
 * keeps the title as the panel's name only, for a screen whose lens bar says it.
 */
export function ListPanel({ title, count, sub, filter, sort, note, pinned, hideTitle = false, children }) {
  return (
    <aside className="panel" aria-label={title}>
      <header className="panel__head">
        {hideTitle ? null : (
          <div className="panel__headline">
            <h1>{title}</h1>
            {count !== undefined && count !== null ? <span className="num panel__count">{count}</span> : null}
          </div>
        )}
        {sub || sort ? (
          <div className="panel__meta">
            <p className="panel__sub">{sub}</p>
            {sort}
          </div>
        ) : null}
        {filter}
      </header>
      {pinned}
      <div className="panel__body">{children}</div>
      {note ? <footer className="panel__note">{note}</footer> : null}
    </aside>
  )
}

/** A collapsible group: sticky head with a caret, the group's status icon, its label and count. */
export function Group({ label, count, open, onToggle, icon, children }) {
  return (
    <div className="group" role="group" aria-label={label}>
      <button type="button" className="group__head" onClick={onToggle} aria-expanded={open}>
        <Icon name={open ? 'down' : 'right'} size={14} className="group__caret" />
        {icon ? <StatusIcon kind={icon} /> : null}
        <span className="group__label">{label}</span>
        <span className="group__count num">{count}</span>
      </button>
      {open ? children : null}
    </div>
  )
}

const isScore = (s) => s !== null && s !== undefined && s !== '' && Number.isFinite(Number(s))

/**
 * One row, three lines (spec-main §3.1 "Row"): status icon · name · arrears; the id
 * line · DPD; the chips · "เสี่ยง n" (the served risk score that used to be the colour
 * rail — the DPD heat bar is gone, the row prints the DPD). The row is ONE button;
 * `select` ({ checked, onToggle, label }) adds its checkbox as a sibling, never inside.
 */
export function ListRow({ name, sub, arrears, dpd, dpdLabel, score, icon, iconTitle, chips, onSelect, current, select }) {
  const { t } = usePrefs()
  const dpdText = dpdLabel || (dpd === undefined ? null : dpd === null ? '—' : `DPD ${dpd}`)
  const indent = icon ? ' row__line--indent' : ''
  return (
    <div className={`row${current ? ' row--current' : ''}`}>
      {select ? (
        <input type="checkbox" className="row__check" aria-label={select.label}
               checked={select.checked} onChange={select.onToggle} />
      ) : null}
      <button type="button" className="row__btn" onClick={onSelect} aria-current={current ? 'true' : undefined}>
        <span className="row__line">
          {icon ? <StatusIcon kind={icon} title={iconTitle} /> : null}
          <span className="row__name">{name}</span>
          {arrears !== undefined ? <span className="row__arrears num">{arrears}</span> : null}
        </span>
        {sub || dpdText ? (
          <span className={`row__line row__line--sub${indent}`}>
            <span className="row__sub">{sub}</span>
            {dpdText ? (
              <span className={`row__dpd num${dpd === null || dpd === undefined ? ' row__dpd--none' : ''}`}>{dpdText}</span>
            ) : null}
          </span>
        ) : null}
        {chips || isScore(score) ? (
          <span className={`row__line row__line--chips${indent}`}>
            <span className="row__chips">{chips}</span>
            {isScore(score) ? <span className="row__risk num">{t('today.risk', { n: score })}</span> : null}
          </span>
        ) : null}
      </button>
    </div>
  )
}

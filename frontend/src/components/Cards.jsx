/** KPI card: label, served figure, bar (only when a served bar percentage exists), note. */
export function KpiCard({ label, value, sub, note, barPct, barColor = 'var(--viz-sev-3)', action }) {
  return (
    <section className="card kpi">
      <span className="eyebrow">{label}</span>
      <span className="kpi__value num">{value}</span>
      {barPct !== undefined && barPct !== null ? (
        <span className="bar bar--thick" aria-hidden="true">
          <span className="bar__fill" style={{ width: `${barPct}%`, background: barColor }} />
        </span>
      ) : null}
      {sub ? <span className="kpi__sub num">{sub}</span> : null}
      {note ? <span className="kpi__note">{note}</span> : null}
      {action ? <span className="kpi__action">{action}</span> : null}
    </section>
  )
}

/** Vertical bars from served values. Height is driven by barPct (served), never recomputed. */
export function Bars({ label, unit, bars, highlightLast = false }) {
  const max = bars.reduce((m, b) => Math.max(m, b.barPct || 0), 0) || 1
  return (
    <div className="bars" role="img" aria-label={label}>
      {bars.map((b) => (
        <div className="bars__col" key={b.key || b.label}>
          <span className="bars__value num">{b.value}</span>
          <span
            className="bars__bar"
            style={{ height: `${Math.round(((b.barPct || 0) / max) * 120) + 8}px`, background: b.color || 'var(--viz-sev-3)' }}
          />
          <span className="bars__label">{b.label}</span>
        </div>
      ))}
      {unit ? <span className="bars__unit">{unit}</span> : null}
      {highlightLast ? null : null}
    </div>
  )
}

export function EmptyState({ children }) {
  return <p className="empty">{children}</p>
}

export function Section({ title, action, children, note, headless = false }) {
  return (
    <section className="card">
      {!headless && (
        <header className="card__head">
          <h2>{title}</h2>
          {action}
        </header>
      )}
      <div className="card__body">{children}</div>
      {note ? <p className="card__note">{note}</p> : null}
    </section>
  )
}

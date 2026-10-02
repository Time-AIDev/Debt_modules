/** The design's segment: one selected option, radiogroup semantics. */
export function SegmentedControl({ label, options, value, onChange, className = '' }) {
  return (
    <div className={`seg ${className}`.trim()} role="radiogroup" aria-label={label}>
      {options.map((o) => {
        const on = o.id === value
        return (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={on}
            className={`seg__btn${on ? ' seg__btn--on' : ''}`}
            disabled={!!o.disabled}
            title={o.title || undefined}
            onClick={() => onChange(o.id)}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

/** A menu of choices in a popover card (identity roles, setting options). */
export function ChoiceList({ label, options, value, onPick, disabled = false }) {
  return (
    <div className="choice" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          role="radio"
          aria-checked={o.id === value}
          className={`choice__btn${o.id === value ? ' choice__btn--on' : ''}`}
          disabled={disabled || o.disabled}
          onClick={() => onPick(o.id)}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

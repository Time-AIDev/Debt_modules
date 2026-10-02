import { useState } from 'react'
import { usePrefs } from '../lib/prefs.jsx'
import { Popover } from './Popover.jsx'

/**
 * A notice kept for the moment of acting (brief §3.4): a quiet 28px "i" button that
 * opens a small card (max 320, 12/18 ink-2). Esc and an outside click close it.
 * `align="right"` opens the card leftwards from the button's right edge.
 */
export function InfoPopover({ children, label, align = 'left' }) {
  const { t } = usePrefs()
  const [open, setOpen] = useState(false)
  const name = label || t('common.moreInfo')
  // The popover closes on an outside mousedown; the trigger's own press toggles instead.
  return (
    <span className="info">
      <button type="button" className="btn btn--quiet btn--icon" aria-label={name} aria-expanded={open}
              onMouseDown={(e) => { if (open) e.stopPropagation() }}
              onClick={() => setOpen((v) => !v)}>
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false">
          <path d="M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-5M12 8h.01" fill="none" stroke="currentColor"
                strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      <Popover open={open} onClose={() => setOpen(false)} label={name} width="max-content" as="span"
               className={`popover--info${align === 'right' ? ' popover--right' : ''}`}>
        {children}
      </Popover>
    </span>
  )
}

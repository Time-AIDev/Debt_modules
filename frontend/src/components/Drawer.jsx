import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { usePrefs } from '../lib/prefs.jsx'

// A disabled field cannot take focus (focus() fails silently), so it never counts as first.
const FIRST = 'input:not([disabled]), textarea:not([disabled]), select:not([disabled]), button:not([disabled])'
const TABBABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * The focus contract every dialog here shares (Drawer, ConfirmDialog, CaseSheet):
 * on open, focus the first field or the box itself; Esc closes; Tab stays inside the
 * box; on close, focus goes back to the trigger. A dialog opened INSIDE this one (a
 * drawer in the case sheet) owns the keys while it is open, and an open popover inside
 * owns Esc.
 */
export function useDialogFocus(open, boxRef, onClose) {
  // onClose is almost always an inline arrow (a new identity every render). Kept in
  // a ref and left out of the effect's deps on purpose: with it in, every keystroke
  // in a controlled field re-ran this effect and stole focus back to the panel/close
  // button after one character (found writing the pre-install card, 2026-09-20).
  const closeRef = useRef(onClose)
  closeRef.current = onClose

  useEffect(() => {
    if (!open) return undefined
    const back = document.activeElement
    const box = boxRef.current
    ;(box?.querySelector(FIRST) || box)?.focus()
    const onKey = (e) => {
      if (!box || box.querySelector('[aria-modal="true"]')) return
      if (e.key === 'Escape') {
        if (box.querySelector('.popover')) return
        e.stopPropagation()
        closeRef.current()
      } else if (e.key === 'Tab') {
        const items = [...box.querySelectorAll(TABBABLE)]
        if (!items.length) { e.preventDefault(); return }
        const first = items[0]
        const last = items[items.length - 1]
        const at = document.activeElement
        if (!box.contains(at) || (e.shiftKey && at === first) || (!e.shiftKey && at === last)) {
          e.preventDefault()
          ;(e.shiftKey ? last : first).focus()
        }
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      if (back && typeof back.focus === 'function') back.focus()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])
}

/**
 * Where an overlay sits (brief §3.4): over the content column only — the shell's
 * <main id="main"> — so the rail, top bar and context tabs stay in view. Inside the
 * case pop-up (layout containment) an overlay is already scoped to the sheet, so it
 * takes no offset there. Returns an inline style for the fixed overlay root.
 */
export function useContentBox(open, rootRef) {
  const [box, setBox] = useState(undefined)
  useLayoutEffect(() => {
    if (!open) return undefined
    const place = () => {
      if (rootRef?.current?.parentElement?.closest('.casesheet__dialog')) { setBox(undefined); return }
      const r = document.getElementById('main')?.getBoundingClientRect()
      setBox(r ? { top: Math.max(r.top, 0), left: Math.max(r.left, 0) } : undefined)
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, { passive: true })
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])
  return box
}

/**
 * The one slide-over dialog. Mounted only while open (no hidden DOM), focuses the
 * first field or the panel on open, closes on Esc or overlay click, and returns
 * focus to the trigger. Footer is a render prop so each drawer keeps its own verbs.
 */
export function Drawer({ open, onClose, title, subtitle, children, footer, headAction, width = 440 }) {
  const { t } = usePrefs()
  const panelRef = useRef(null)
  const rootRef = useRef(null)
  useDialogFocus(open, panelRef, onClose)
  const box = useContentBox(open, rootRef)

  if (!open) return null

  return (
    <div className="drawer" role="dialog" aria-modal="true" aria-label={title} ref={rootRef} style={box}>
      <div className="drawer__scrim" onClick={onClose} />
      <aside className="drawer__panel" ref={panelRef} tabIndex={-1} style={{ width }}>
        <header className="drawer__head">
          <div className="drawer__title">
            <p>{title}</p>
            {subtitle ? <p className="drawer__sub">{subtitle}</p> : null}
          </div>
          {headAction}
          <button type="button" className="btn btn--sm" onClick={onClose}>{t('common.close')}</button>
        </header>
        <div className="drawer__body">{children}</div>
        {footer ? <footer className="drawer__foot">{footer}</footer> : null}
      </aside>
    </div>
  )
}

import { useRef } from 'react'
import { usePrefs } from '../lib/prefs.jsx'
import { useContentBox, useDialogFocus } from './Drawer.jsx'

/**
 * The design's confirm (brief §3.4): a centred 440 card over a scrim — the title, what
 * the act will do (children, 14 ink-2), then "ยกเลิก" and ONE confirm (primary, or
 * `danger` for a destructive act). Esc and the scrim cancel; focus is kept inside.
 * Put a refusal (Problem) in the children so it shows where the person acted.
 */
export function ConfirmDialog({ open, onClose, onConfirm, title, children, confirmLabel, danger = false, busy = false }) {
  const { t } = usePrefs()
  const cardRef = useRef(null)
  const rootRef = useRef(null)
  useDialogFocus(open, cardRef, onClose)
  const box = useContentBox(open, rootRef)

  if (!open) return null
  return (
    <div className="dialog" role="dialog" aria-modal="true" aria-label={title} ref={rootRef} style={box}>
      <div className="dialog__scrim" onClick={onClose} />
      <div className="dialog__card" ref={cardRef} tabIndex={-1}>
        <p className="dialog__title">{title}</p>
        {children ? <div className="dialog__body">{children}</div> : null}
        <div className="dialog__foot">
          <button type="button" className="btn" onClick={onClose}>{t('common.cancel')}</button>
          <button type="button" className={danger ? 'btn btn--danger' : 'btn btn--primary'} disabled={busy} onClick={onConfirm}>
            {confirmLabel || t('common.confirm')}
          </button>
        </div>
      </div>
    </div>
  )
}

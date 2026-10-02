import { useEffect, useState } from 'react'
import { usePrefs } from '../lib/prefs.jsx'
import { Drawer } from './Drawer.jsx'
import { Problem } from './Problem.jsx'
import { StatusIcon } from './StatusIcon.jsx'

/**
 * The one move drawer (spec-main §5.1): a reason (required) and one button per served
 * destination — with its status icon when the caller gives `kind` — the current one
 * disabled "… ✓" + aria-current so the list never changes shape. Used by the Today
 * board, the case and the recovery board; the caller owns the API call. The rule
 * note is a notice: only a caller that passes `noteKey` still prints one.
 */
export function MoveDrawer({ open, onClose, title, subtitle, currentId, options, busy, problem, onConfirm, noteKey }) {
  const { t } = usePrefs()
  const [reason, setReason] = useState('')
  const [missing, setMissing] = useState(false)

  useEffect(() => {
    if (open) { setReason(''); setMissing(false) }
  }, [open])

  function confirm(toId) {
    if (!reason.trim()) { setMissing(true); return }
    onConfirm(toId, reason.trim())
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={title || t('board.moveTitle')}
      subtitle={subtitle}
      footer={<button type="button" className="btn" onClick={onClose}>{t('common.cancel')}</button>}
    >
      <label className="label">
        <span>{t('board.moveReason')}<span className="req" aria-hidden="true">*</span></span>
        <textarea className="field" rows={3} value={reason} aria-required="true" aria-invalid={missing || undefined}
                  onChange={(e) => { setReason(e.target.value); setMissing(false) }} />
        {missing ? <span className="field__error" role="alert">{t('board.reasonRequired')}</span> : null}
      </label>
      <div className="board__dest" role="group" aria-label={t('board.moveToLabel')}>
        <span className="eyebrow" aria-hidden="true">{t('board.moveToLabel')}</span>
        {(options || []).map((o) => {
          const current = o.id === currentId
          return (
            <button key={o.id} type="button" className="btn" disabled={current || busy || o.disabled}
                    title={o.title || undefined}
                    aria-current={current ? 'true' : undefined}
                    onClick={() => confirm(o.id)}>
              {o.kind ? <StatusIcon kind={o.kind} /> : null}
              {current ? `${o.label} ✓` : o.label}
            </button>
          )
        })}
      </div>
      {problem ? <Problem problem={problem} /> : null}
      {noteKey ? <p className="drawer__hint">{t(noteKey)}</p> : null}
    </Drawer>
  )
}

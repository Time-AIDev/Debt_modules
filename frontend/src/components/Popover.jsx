import { useEffect, useRef } from 'react'

/** A topbar disclosure: Escape and outside-click close it; the trigger keeps focus. */
export function Popover({ open, onClose, label, children, width = 240, className, as: Tag = 'div' }) {
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    const onClick = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose() }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <Tag className={`popover${className ? ` ${className}` : ''}`} style={{ width }} ref={ref} role="group" aria-label={label}>
      {children}
    </Tag>
  )
}

// UI icons of the final design (the sprite's `ic-*` symbols): 24-grid strokes in
// currentColor. Decorative unless `title` names them. Status meanings use StatusIcon.
const PATHS = {
  'phone': "M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2",
  'chat': "M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z",
  'copy': "M9 9h10v10H9zM5 15V5h10",
  'eye': "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  'down': "M6 9l6 6 6-6",
  'right': "M9 6l6 6-6 6",
  'left': "M15 6l-6 6 6 6",
  'up': "M6 15l6-6 6 6",
  'close': "M6 6l12 12M18 6 6 18",
  'more': "M5 12h.01M12 12h.01M19 12h.01",
  'upload': "M12 16V4M7 9l5-5 5 5M4 20h16",
  'download': "M12 4v12M7 11l5 5 5-5M4 20h16",
  'refresh': "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  'info': "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-5M12 8h.01",
  'search': "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-3.5-3.5",
  'sort': "M7 4v16M4 17l3 3 3-3M17 20V4M14 7l3-3 3 3",
  'check': "M5 12.5l4.5 4.5L19 7.5",
  'user': "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
  'users': "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 21a7 7 0 0 1 14 0M16 3.5a4 4 0 0 1 0 7.5M22 21a7 7 0 0 0-4.5-6.5",
  'calendar': "M8 2v4M16 2v4M3 10h18M5 6h14v15H5z",
  'file': "M6 3h8l5 5v13H6zM14 3v5h5",
  'link': "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
  'unlink': "M15 9l-6 6M9.5 5.5l1-1a4 4 0 0 1 5.7 5.7l-1 1M14.5 18.5l-1 1a4 4 0 0 1-5.7-5.7l1-1",
  'board': "M4 4h5v16H4zM10.5 4h5v10h-5zM17 4h3v7h-3z",
  'list': "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  'split': "M16 3h5v5M21 3l-7 7M8 21H3v-5M3 21l7-7",
  'receipt': "M6 3h12v18l-3-2-3 2-3-2-3 2zM9 8h6M9 12h6",
  'pen': "M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4",
  'stop': "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM5 5l14 14",
  'doc': "M7 3h10v18H7zM10 8h4M10 12h4M10 16h2",
  'flag': "M5 21V4h11l-2 4 2 4H5",
  'plus': "M12 5v14M5 12h14",
  'minus': "M5 12h14",
  'arrow-right': "M5 12h14M13 6l6 6-6 6",
}

export const ICON_NAMES = Object.keys(PATHS)

/** One UI icon by name (`phone`, `chat`, `copy`, `close`, `down`, …); size 16–18 by default 16. */
export function Icon({ name, size = 16, title, className }) {
  const d = PATHS[name]
  if (!d) return null
  const a11y = title ? { role: 'img' } : { 'aria-hidden': 'true' }
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} focusable="false" {...a11y}
         className={`icon${className ? ` ${className}` : ''}`} fill="none" stroke="currentColor"
         strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      {title ? <title>{title}</title> : null}
      {(Array.isArray(d) ? d : [d]).map((p) => <path key={p} d={p} />)}
    </svg>
  )
}

export function internalOrigin(location, label, state) {
  const pathname = location?.pathname || '/'
  if (!pathname.startsWith('/') || pathname.startsWith('//')) return null
  return {
    to: `${pathname}${location?.search || ''}`,
    state: state ?? location?.state,
    label,
    scrollY: typeof window === 'undefined' ? 0 : window.scrollY,
  }
}

export function recordState(origin) {
  return origin ? { origin } : undefined
}

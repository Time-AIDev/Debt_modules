// The rail model. Order and grouping follow the final design; titles are dictionary
// keys so both languages stay in one place. `badge` names a key in
// /v1/shell/summary.badges — a badge the payload does not carry draws no count.
export const NAV_GROUPS = [
  {
    label: null,
    items: [
      { id: 'dash', to: '/dashboard', icon: 'M3 13h8V3H3v10zm10 8h8V11h-8v10zM3 21h8v-6H3v6zM13 9h8V3h-8v6z' },
    ],
  },
  {
    label: 'group.mine',
    items: [
      { id: 'today', to: '/', icon: 'M8 2v4M16 2v4M3 10h18M5 6h14v15H5z', badge: 'today' },
      { id: 'calendar', to: '/calendar', icon: 'M8 2v4M16 2v4M3 10h18M5 6h14v15H5zM9 14h2M15 14h2M9 18h2' },
      { id: 'terminated', to: '/terminated', icon: 'M5 4h14v16H5zM9 9h6M9 13h6' },
      { id: 'book', to: '/book', icon: 'M4 4h16v16H4zM8 4v16', badge: 'book' },
    ],
  },
  {
    label: 'group.review',
    items: [
      { id: 'reviews', to: '/reviews', icon: 'M9 11l3 3 5-5M5 4h14v16H5z', badge: 'reviews' },
      { id: 'payments', to: '/payments', icon: 'M3 8h18v10H3zM3 12h18', badge: 'payments' },
      { id: 'recovery', to: '/recovery', icon: 'M12 3l9 16H3z', badge: 'recovery' },
    ],
  },
  {
    label: 'group.system',
    items: [
      { id: 'reports', to: '/reports', icon: 'M5 20V10M12 20V4M19 20v-7' },
      { id: 'settings', to: '/settings', icon: 'M12 15a3 3 0 100-6 3 3 0 000 6zM4 12h2m12 0h2M12 4v2m0 12v2', badge: 'settings' },
      { id: 'data', to: '/data-sources', icon: 'M4 7c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 7v10c0 1.7 3.6 3 8 3s8-1.3 8-3V7' },
      { id: 'audit', to: '/audit', icon: 'M9 4h6l4 4v12H5V4zM9 13h6M9 17h4' },
    ],
  },
]

export const NAV_ITEMS = NAV_GROUPS.flatMap((g) => g.items)

export function navItemByPath(pathname) {
  if (pathname.startsWith('/terminated')) return NAV_ITEMS.find((i) => i.id === 'terminated') || null
  if (pathname.startsWith('/customers')) return NAV_ITEMS.find((i) => i.id === 'today') || null
  return NAV_ITEMS.find((i) => i.to === pathname) || null
}

export function groupKeyFor(item) {
  for (const g of NAV_GROUPS) {
    if (g.items.some((i) => i.id === item.id)) return g.label
  }
  return null
}

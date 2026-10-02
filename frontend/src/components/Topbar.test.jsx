import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { renderScreen } from '../test-utils.jsx'
import { Topbar } from './Topbar.jsx'

vi.mock('../lib/api.js', () => ({ api: { authLogout: vi.fn() } }))

describe('Topbar breadcrumb', () => {
  it('links to the source page with its route state', () => {
    renderScreen(
      <Topbar
        crumb={{
          group: 'งานของฉัน',
          page: 'ปัทมวรรณ สุขเจริญ',
          parent: { to: '/calendar?owner=me', state: { unit: 'week', anchor: '2026-10-05' } },
        }}
        onSearch={() => {}}
      />,
    )

    expect(screen.getByRole('link', { name: 'งานของฉัน' })).toHaveAttribute('href', '/calendar?owner=me')
    expect(screen.getByText('ปัทมวรรณ สุขเจริญ')).not.toHaveAttribute('href')
  })
})

import { describe, expect, it, vi } from 'vitest'
import { act, screen } from '@testing-library/react'
import { renderScreen } from '../test-utils.jsx'
import { Topbar } from './Topbar.jsx'
import { setPublicRuntime } from '../lib/publicRuntime.js'

vi.mock('../lib/api.js', () => ({ api: { authLogout: vi.fn() } }))

describe('Topbar breadcrumb', () => {
  it('labels real production data without claiming it is sample data', () => {
    setPublicRuntime({ environment: 'production', data_mode: 'shared' })
    renderScreen(<Topbar crumb={{ group: 'งานของฉัน', page: 'วันนี้' }} onSearch={() => {}} />)
    expect(screen.getByText('Production')).toBeInTheDocument()
    expect(screen.queryByText(/ข้อมูลตัวอย่าง/)).not.toBeInTheDocument()
    act(() => setPublicRuntime(null))
  })
  it('labels fixtures as sample data only when the API declares fixtures', () => {
    setPublicRuntime({ environment: 'development', data_mode: 'fixtures' })
    renderScreen(<Topbar crumb={{ group: 'งานของฉัน', page: 'วันนี้' }} onSearch={() => {}} />)
    expect(screen.getByText('Development · ข้อมูลตัวอย่าง')).toBeInTheDocument()
    act(() => setPublicRuntime(null))
  })
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

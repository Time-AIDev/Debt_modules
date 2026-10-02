import { describe, it, expect, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { ContextTabs } from './ContextTabs.jsx'

describe('the context tabs (F13)', () => {
  it('closes a recent tab without navigating', async () => {
    const user = userEvent.setup()
    const onOpen = vi.fn()
    const onClose = vi.fn()
    renderScreen(
      <ContextTabs
        current={{ label: 'วันนี้', meta: 'งานของฉัน' }}
        recents={[{
          key: 'case-c-1', label: 'ปัทมวรรณ สุขเจริญ', meta: 'วันนี้',
          color: 'var(--viz-sev-3)', current: false, onOpen, onClose,
        }]}
      />,
    )
    expect(screen.getByRole('tab', { name: /ปัทมวรรณ/ })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'ปิดแท็บ ปัทมวรรณ สุขเจริญ' }))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onOpen).not.toHaveBeenCalled()
  })

  it('opens a recent tab from its label', async () => {
    const user = userEvent.setup()
    const onOpen = vi.fn()
    renderScreen(
      <ContextTabs
        current={{ label: 'วันนี้' }}
        recents={[{ key: 'case-c-1', label: 'ปัทมวรรณ', color: 'var(--viz-sev-3)', onOpen, onClose: vi.fn() }]}
      />,
    )
    await user.click(screen.getByRole('button', { name: 'ปัทมวรรณ' }))
    expect(onOpen).toHaveBeenCalledTimes(1)
  })
})

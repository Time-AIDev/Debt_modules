import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useState } from 'react'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { CaseSheet } from './CaseSheet.jsx'
import { CASE } from '../test-fixtures.js'

vi.mock('../lib/api.js', () => ({
  api: new Proxy({}, {
    get: (target, prop) => {
      if (!(prop in target)) target[prop] = vi.fn(async () => ({}))
      return target[prop]
    },
  }),
  CHANGED_EVENT: 'volt:changed',
  AUTH_REQUIRED_EVENT: 'volt:auth-required',
}))
const { api } = await import('../lib/api.js')

function Host() {
  const [open, setOpen] = useState(true)
  return <CaseSheet uid="c-1" open={open} onClose={() => setOpen(false)} />
}

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
  api.caseDetail.mockResolvedValue(CASE)
})

describe('the case pop-up sheet', () => {
  it('opens on a customer, shows the case and closes on Esc', async () => {
    const user = userEvent.setup()
    renderScreen(<Host />)

    const sheet = screen.getByRole('dialog', { name: 'เคสลูกค้า' })
    expect(sheet).toHaveAttribute('aria-modal', 'true')
    expect(await screen.findByRole('heading', { name: /ปัทมวรรณ สุขเจริญ/ })).toBeInTheDocument()
    expect(api.caseDetail).toHaveBeenCalledWith('c-1')

    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'เคสลูกค้า' })).toBeNull())
  })

  it('lets an open drawer inside the sheet take Esc first', async () => {
    const user = userEvent.setup()
    renderScreen(<Host />)
    await user.click(await screen.findByRole('button', { name: 'บันทึกผลการติดต่อ' }))
    expect(await screen.findByRole('dialog', { name: 'บันทึกผลการติดต่อ' })).toBeInTheDocument()

    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'บันทึกผลการติดต่อ' })).toBeNull())
    expect(screen.getByRole('dialog', { name: 'เคสลูกค้า' })).toBeInTheDocument()
  })

  it('opens straight onto its contact drawer when asked, and says when that drawer closes', async () => {
    const user = userEvent.setup()
    const onLogClose = vi.fn()
    renderScreen(<CaseSheet uid="c-1" open openLog onLogClose={onLogClose} onClose={() => {}} />)

    expect(await screen.findByRole('dialog', { name: 'บันทึกผลการติดต่อ' })).toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: 'เคสลูกค้า' })).toBeInTheDocument()

    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'บันทึกผลการติดต่อ' })).toBeNull())
    expect(onLogClose).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('dialog', { name: 'เคสลูกค้า' })).toBeInTheDocument()
  })
})

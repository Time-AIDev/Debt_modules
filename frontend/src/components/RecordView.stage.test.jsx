import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { setRole } from '../lib/identity.jsx'
import { Record } from '../screens/Record.jsx'
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

function stageCase(over = {}) {
  return {
    ...CASE,
    work_item: {
      ...CASE.work_item,
      ladder: { ...CASE.work_item.ladder, stage: 'NOTICE_30', case_uid: 'case-c-1', kind: 'LEASE' },
    },
    ...over,
  }
}

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
  api.caseDetail.mockResolvedValue(stageCase())
  api.setCaseStage.mockResolvedValue({ case: {} })
  api.setCashCaseStage.mockResolvedValue({ case: {} })
})

describe('the ladder stage control (F05, Q1)', () => {
  it('is visible and disabled with its reason below manager', async () => {
    setRole('OFFICER')
    renderScreen(<Record />, { route: '/customers/c-1' })
    const button = await screen.findByRole('button', { name: 'ปรับขั้น' })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('title', 'เฉพาะผู้จัดการขึ้นไป')
  })

  it('opens the move drawer for a manager, with the current stage disabled', async () => {
    setRole('MANAGER')
    const user = userEvent.setup()
    renderScreen(<Record />, { route: '/customers/c-1' })
    const button = await screen.findByRole('button', { name: 'ปรับขั้น' })
    expect(button).not.toBeDisabled()
    await user.click(button)
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('button', { name: 'ขั้น 30 วัน · โทรแจ้งเตือน ✓' })).toBeDisabled()
    expect(within(dialog).getByRole('button', { name: 'ขั้น 90 วัน · หนังสือทวงถาม' })).not.toBeDisabled()
  })

  it('posts the move with its reason and reloads', async () => {
    setRole('MANAGER')
    const user = userEvent.setup()
    renderScreen(<Record />, { route: '/customers/c-1' })
    await user.click(await screen.findByRole('button', { name: 'ปรับขั้น' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'ขั้น 90 วัน · หนังสือทวงถาม' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('ต้องระบุเหตุผล')
    await user.type(within(dialog).getByRole('textbox'), 'ลูกค้าค้างนานกว่าที่บันทึกไว้')
    await user.click(within(dialog).getByRole('button', { name: 'ขั้น 90 วัน · หนังสือทวงถาม' }))
    await waitFor(() => expect(api.setCaseStage).toHaveBeenCalledTimes(1))
    expect(api.setCaseStage.mock.calls[0]).toEqual(['case-c-1', {
      to_stage: 'DEFAULT_CONFIRMED_90',
      reason: 'ลูกค้าค้างนานกว่าที่บันทึกไว้',
      by: undefined,
      role: 'MANAGER',
    }])
  })

  it('shows no control where the ladder has no journey case', async () => {
    setRole('MANAGER')
    api.caseDetail.mockResolvedValue({
      ...CASE,
      work_item: { ...CASE.work_item, ladder: { ...CASE.work_item.ladder, case_uid: null } },
    })
    renderScreen(<Record />, { route: '/customers/c-1' })
    await screen.findByText('ขั้น 30 วัน · โทรแจ้งเตือน')
    expect(screen.queryByRole('button', { name: 'ปรับขั้น' })).not.toBeInTheDocument()
  })
})

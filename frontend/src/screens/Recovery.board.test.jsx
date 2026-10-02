import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { setRole } from '../lib/identity.jsx'
import { Recovery } from './Recovery.jsx'

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

const NPL = {
  npl_cases: [
    {
      uid: 'npl-1', case_uid: 'case-1', customer_uid: 'c-1', display_name: 'ลูกค้า ทดสอบหนึ่ง',
      volt_id: 'V-1', entity: 'SPV', npl_type_label: 'NPL 90', aggregate_overdue: '8697.00',
      remaining_npv: '150000.00', oldest_dpd: 74, risk_score: 88, strategy: 'LEGAL',
      recovery_uid: 'rec-1', payment_status: 'NPL', status_label_th: 'กำลังดำเนินการ',
      status_label_en: 'In progress', source: 'SHEET', recovery_paths: { paths: [] },
    },
    {
      uid: 'npl-2', case_uid: 'case-2', customer_uid: 'c-2', display_name: 'ลูกค้า ทดสอบสอง',
      aggregate_overdue: '32400.00', remaining_npv: '200000.00', oldest_dpd: 61, risk_score: 81,
      strategy: null, recovery_uid: null, payment_status: 'NPL', status_label_th: 'ยังไม่เลือกแนวทาง',
      source: 'SHEET', recovery_paths: { paths: [] },
    },
  ],
  meta: {
    badge: 2, total: 2,
    strategies: [
      { strategy: 'LEGAL', label_th: 'ดำเนินคดี', label_en: 'Legal', available: true, pending_decision: null, rate_pct: '38' },
      { strategy: 'REPOSSESSION', label_th: 'ยึดคืนอุปกรณ์', label_en: 'Repossession', available: true, pending_decision: null, rate_pct: '38' },
      { strategy: 'COOP_DECOMMISSION', label_th: 'รื้อถอนโดยความยินยอม', label_en: 'Cooperative decommission', available: true, pending_decision: null, rate_pct: '38' },
      { strategy: 'EXTERNAL_COLLECTION', label_th: 'ส่งสำนักงานเร่งรัดหนี้ภายนอก', label_en: 'External collection', available: false, pending_decision: 'D27', rate_pct: null },
    ],
  },
}

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
  setRole('MANAGER')
  api.nplCases.mockResolvedValue(NPL)
  api.recoveryCases.mockResolvedValue({ recovery_cases: [] })
  api.lots.mockResolvedValue({ lots: [] })
  api.recoveryBoard.mockResolvedValue({ columns: [] })
  api.serviceBilling.mockResolvedValue({ accounts: [] })
  api.changeRecoveryStrategy.mockResolvedValue({ recovery: {} })
  api.openRecovery.mockResolvedValue({ recovery: {} })
})

describe('the NPL strategy board (F08, Q2)', () => {
  // The path kanban is the second view of the เคส NPL tab (final design E).
  async function openBoard(user) {
    renderScreen(<Recovery />)
    await user.click(await screen.findByRole('radio', { name: /บอร์ดแนวทาง/ }))
    return screen.findByTestId('board')
  }
  async function openMenu(user, name) {
    await user.click(screen.getByRole('button', { name: `ตัวเลือกของ ${name}` }))
  }

  it('draws five columns, the unavailable one named with its decision', async () => {
    const user = userEvent.setup()
    const board = await openBoard(user)
    expect(board.querySelectorAll('.lane')).toHaveLength(5)
    expect(screen.getByRole('region', { name: /ยังไม่เลือกแนวทาง/ })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /ส่งสำนักงานเร่งรัดหนี้ภายนอก · ยังใช้ไม่ได้ · รอคำตัดสิน D27/ })).toBeInTheDocument()
  })

  it('places each card in its served strategy column', async () => {
    const user = userEvent.setup()
    await openBoard(user)
    expect(within(screen.getByRole('region', { name: /^ดำเนินคดี/ })).getByText('ลูกค้า ทดสอบหนึ่ง')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: /ยังไม่เลือกแนวทาง/ })).getByText('ลูกค้า ทดสอบสอง')).toBeInTheDocument()
  })

  it('moves a card with a reason through change-strategy when a recovery is open', async () => {
    const user = userEvent.setup()
    await openBoard(user)
    await openMenu(user, 'ลูกค้า ทดสอบหนึ่ง')
    await user.click(screen.getByRole('button', { name: 'ย้ายแนวทาง' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('button', { name: 'ดำเนินคดี ✓' })).toBeDisabled()
    const ext = within(dialog).getByRole('button', { name: 'ส่งสำนักงานเร่งรัดหนี้ภายนอก' })
    expect(ext).toBeDisabled()
    expect(ext).toHaveAttribute('title', expect.stringContaining('D27'))
    await user.type(within(dialog).getByRole('textbox'), 'ลูกค้ายอมให้ยึดคืน')
    await user.click(within(dialog).getByRole('button', { name: 'ยึดคืนอุปกรณ์' }))
    await waitFor(() => expect(api.changeRecoveryStrategy).toHaveBeenCalledTimes(1))
    expect(api.changeRecoveryStrategy.mock.calls[0][0]).toBe('rec-1')
    expect(api.changeRecoveryStrategy.mock.calls[0][1]).toMatchObject({
      strategy: 'REPOSSESSION', reason: 'ลูกค้ายอมให้ยึดคืน', role: 'MANAGER',
    })
  })

  it('opens the strategy through open-recovery when the card has none, and disables the move below manager', async () => {
    const user = userEvent.setup()
    await openBoard(user)
    await openMenu(user, 'ลูกค้า ทดสอบสอง')
    await user.click(screen.getByRole('button', { name: 'ย้ายแนวทาง' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByRole('textbox'), 'เริ่มดำเนินคดี')
    await user.click(within(dialog).getByRole('button', { name: 'ดำเนินคดี' }))
    await waitFor(() => expect(api.openRecovery).toHaveBeenCalledTimes(1))
    expect(api.openRecovery.mock.calls[0][0]).toBe('npl-2')
    expect(api.openRecovery.mock.calls[0][1]).toMatchObject({ strategy: 'LEGAL', reason: 'เริ่มดำเนินคดี' })
  })

  it('disables the move button with its reason below manager', async () => {
    setRole('SUPERVISOR')
    const user = userEvent.setup()
    await openBoard(user)
    // Every card: the one with an open path and the undecided one (that move opens a path).
    for (const name of ['ลูกค้า ทดสอบหนึ่ง', 'ลูกค้า ทดสอบสอง']) {
      await openMenu(user, name)
      const move = within(screen.getByRole('group', { name: `ตัวเลือกของ ${name}` })).getByRole('button', { name: 'ย้ายแนวทาง' })
      expect(move).toBeDisabled()
      expect(move).toHaveAttribute('title', 'เฉพาะผู้จัดการขึ้นไป')
    }
  })

  it('asks for a reason before any move', async () => {
    const user = userEvent.setup()
    await openBoard(user)
    await openMenu(user, 'ลูกค้า ทดสอบสอง')
    await user.click(screen.getByRole('button', { name: 'ย้ายแนวทาง' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'ดำเนินคดี' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent('ต้องระบุเหตุผลที่ย้าย')
    expect(api.openRecovery).not.toHaveBeenCalled()
  })
})

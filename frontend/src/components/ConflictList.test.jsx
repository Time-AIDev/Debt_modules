import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { ConflictList } from './ConflictList.jsx'

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

const OPEN = {
  rows: [{
    customer_no: '28005096535', display_name: 'ปัทมวรรณ สุขเจริญ', volt_id: 'VL0010158_head',
    invoice_count: 2, decided: false,
    conflicts: [
      { field: 'customer_name', odoo_value: 'สมชาย ธรรมดี', peak_value: 'Worarut Sangtong', decision: null },
      { field: 'system_size_kwp', odoo_value: '5.00', peak_value: '6.25', decision: null },
    ],
  }],
  total: 1, limit: 50, offset: 0, undecided_fields: 2,
}

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
  api.peakConflicts.mockResolvedValue(OPEN)
  api.peakConflictsDecide.mockResolvedValue({ customer_no: '28005096535', decisions: 1 })
  api.peakDecisionRetire.mockResolvedValue({ decision: {} })
})

describe('the conflict list (D02, target/07)', () => {
  it('lists one line per customer and opens the table with the four columns, each field defaulting to PEAK', async () => {
    const user = userEvent.setup()
    renderScreen(<ConflictList runId={7} onChanged={() => {}} />)
    expect(await screen.findByText('ปัทมวรรณ สุขเจริญ')).toBeInTheDocument()
    expect(screen.getByText('ขัดแย้ง 2 ฟิลด์')).toBeInTheDocument()
    // design D: the line opens the side sheet that holds the table
    await user.click(screen.getByRole('button', { name: /ปัทมวรรณ สุขเจริญ/ }))
    for (const head of ['ฟิลด์', 'Odoo (crm.lead)', 'PEAK', 'ค่าที่ใช้']) {
      expect(screen.getByRole('columnheader', { name: head })).toBeInTheDocument()
    }
    const nameRow = screen.getByText('ชื่อลูกค้า').closest('tr')
    expect(within(nameRow).getByText('สมชาย ธรรมดี')).toBeInTheDocument()
    expect(within(nameRow).getByText('Worarut Sangtong')).toBeInTheDocument()
    expect(within(nameRow).getByRole('radio', { name: /ใช้ PEAK/ })).toBeChecked()
  })

  it('keeps Odoo for one field with a revealed reason and saves the chosen sources', async () => {
    const user = userEvent.setup()
    renderScreen(<ConflictList runId={7} onChanged={() => {}} />)
    await screen.findByText('ปัทมวรรณ สุขเจริญ')
    await user.click(screen.getByRole('button', { name: /ปัทมวรรณ สุขเจริญ/ }))
    expect(screen.getByRole('button', { name: 'บันทึกการตัดสิน' })).toBeDisabled()
    const nameRow = screen.getByText('ชื่อลูกค้า').closest('tr')
    await user.click(within(nameRow).getByRole('radio', { name: /เก็บ Odoo/ }))
    // the reason field is progressive disclosure: it appears when asked for
    await user.click(screen.getAllByRole('button', { name: /เหตุผล \(ถ้ามี\)/ })[0])
    // (the reason sits on the line under its field, so it is found by its label; the
    // reveal hands it focus)
    expect(screen.getByLabelText('เหตุผล (ถ้ามี)')).toHaveFocus()
    await user.type(screen.getByLabelText('เหตุผล (ถ้ามี)'), 'Odoo name matches the contract')
    await user.click(screen.getByRole('button', { name: 'บันทึกการตัดสิน' }))
    await waitFor(() => expect(api.peakConflictsDecide).toHaveBeenCalledTimes(1))
    expect(api.peakConflictsDecide.mock.calls[0][0]).toBe(7)
    expect(api.peakConflictsDecide.mock.calls[0][1]).toMatchObject({
      customer_no: '28005096535',
      decisions: [{ field: 'customer_name', source: 'ODOO', reason: 'Odoo name matches the contract' }],
    })
  })

  it('shows a decided field with its provenance and retires it', async () => {
    api.peakConflicts.mockResolvedValue({
      ...OPEN,
      rows: [{
        ...OPEN.rows[0], decided: true,
        conflicts: [{
          field: 'customer_name', odoo_value: 'สมชาย ธรรมดี', peak_value: 'Worarut Sangtong',
          decision: { source: 'PEAK', by: 'settasak', at: '2026-09-23T10:00:00', reason: 'PEAK wins', uid: 3 },
        }],
      }],
      undecided_fields: 0,
    })
    const user = userEvent.setup()
    renderScreen(<ConflictList runId={7} onChanged={() => {}} />)
    await screen.findByText('ปัทมวรรณ สุขเจริญ')
    expect(screen.getByText('ตัดสินแล้ว')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /ปัทมวรรณ สุขเจริญ/ }))
    // brief §3.3: dates read dd/mm/yyyy
    expect(screen.getByText(/ตัดสินแล้ว โดย settasak เมื่อ 23\/09\/2026 · PEAK wins/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'ยกเลิกการตัดสิน' }))
    await waitFor(() => expect(api.peakDecisionRetire).toHaveBeenCalledWith(3))
  })
})

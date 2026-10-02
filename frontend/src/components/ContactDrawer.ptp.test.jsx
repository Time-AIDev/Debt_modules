import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useState } from 'react'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { ContactDrawer, contactSummary } from './ContactDrawer.jsx'

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

const RESULTS = {
  name: 'CONTACT_RESULT',
  values: [
    { code: 'REACHED_ANSWERED', label_th: 'ติดต่อได้ - รับสาย', label_en: 'Reached', active: true },
    { code: 'REACHED_PTP', label_th: 'ติดต่อได้ (โทรศัพท์) - นัดชำระ', label_en: 'Reached by phone — PTP', active: true },
    { code: 'PROMISED', label_th: 'ติดต่อได้ (LINE) - นัดชำระ', label_en: 'Reached on LINE — PTP', active: true },
    { code: 'LINE_READ', label_th: 'ส่ง LINE แล้ว อ่านแล้ว', label_en: 'LINE read', active: true },
    { code: 'UNREACHABLE_NO_ANSWER', label_th: 'ติดต่อไม่ได้ - ไม่รับสาย', label_en: 'No answer', active: true },
  ],
}
const NEXT = {
  name: 'NEXT_ACTION',
  values: [{ code: 'FOLLOW_PTP', label_th: 'ตรวจสอบยอดตามนัด', label_en: 'Check', active: true }],
}

const CUSTOMER = { uid: 'c-1', display_name: 'ปัทมวรรณ สุขเจริญ' }

function drawer(over = {}) {
  return (
    <ContactDrawer
      open
      onClose={() => {}}
      customer={CUSTOMER}
      businessDate="2026-10-23"
      onSaved={() => {}}
      {...over}
    />
  )
}

beforeEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
  api.dictionary.mockImplementation(async (name) => (name === 'CONTACT_RESULT' ? RESULTS : NEXT))
  api.logContact.mockResolvedValue({ counted: true })
  api.logCaseContact.mockResolvedValue({ contact: { uid: 'ct-1' } })
  api.renegotiatePtp.mockResolvedValue({ ptp: { uid: 'p-2' } })
})

describe('the contact drawer promise fields (F01, F01c)', () => {
  it('shows the amount and date only for a promise result', async () => {
    const user = userEvent.setup()
    renderScreen(drawer())
    expect(await screen.findByLabelText(/^ผลการติดต่อ/)).toBeInTheDocument()
    expect(screen.queryByLabelText(/จำนวนเงินนัดชำระ/)).not.toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText(/^ผลการติดต่อ/), 'REACHED_PTP')
    expect(screen.getByLabelText(/จำนวนเงินนัดชำระ/)).toHaveAttribute('aria-required', 'true')
    expect(screen.getByLabelText(/วันที่นัดชำระ/)).toHaveAttribute('aria-required', 'true')
    await user.selectOptions(screen.getByLabelText(/^ผลการติดต่อ/), 'REACHED_ANSWERED')
    expect(screen.queryByLabelText(/จำนวนเงินนัดชำระ/)).not.toBeInTheDocument()
  })

  it('refuses to save a promise without an amount and sends the ptp when filled', async () => {
    const user = userEvent.setup()
    renderScreen(drawer())
    // PHONE channel shows the phone PTP; LINE PTP is hidden until channel switches.
    await user.selectOptions(await screen.findByLabelText(/^ผลการติดต่อ/), 'REACHED_PTP')
    const save = screen.getByRole('button', { name: 'บันทึก' })
    expect(save).toBeDisabled()
    await user.type(screen.getByLabelText(/จำนวนเงินนัดชำระ/), '1000')
    expect(save).not.toBeDisabled()
    await user.click(save)
    await waitFor(() => expect(api.logCaseContact).toHaveBeenCalled())
    expect(api.logCaseContact.mock.calls[0][1]).toMatchObject({
      result: 'REACHED_PTP',
      ptp: { amount: '1000', date: '2026-10-24' },
    })
  })

  it('shows the LINE PTP only on the LINE channel', async () => {
    const user = userEvent.setup()
    renderScreen(drawer())
    const resultSelect = await screen.findByLabelText(/^ผลการติดต่อ/)
    // PHONE hides the LINE promise.
    expect([...resultSelect.options].map((o) => o.value)).not.toContain('PROMISED')
    await user.selectOptions(screen.getByLabelText(/^ช่องทาง/), 'LINE')
    const lineResults = await screen.findByLabelText(/^ผลการติดต่อ/)
    expect([...lineResults.options].map((o) => o.value)).toContain('PROMISED')
    expect([...lineResults.options].map((o) => o.value)).not.toContain('REACHED_PTP')
    await user.selectOptions(lineResults, 'PROMISED')
    expect(screen.getByLabelText(/จำนวนเงินนัดชำระ/)).toBeInTheDocument()
  })

  it('offers no VISIT channel', async () => {
    renderScreen(drawer())
    const channelSelect = await screen.findByLabelText(/^ช่องทาง/)
    expect([...channelSelect.options].map((o) => o.value)).toEqual(['PHONE', 'LINE'])
  })

  it('offers the renegotiation when the customer already holds an open promise', async () => {
    api.logCaseContact.mockRejectedValue({
      problem: {
        code: 'ptp_already_open', message_th: 'ลูกค้ารายนี้มีนัดชำระที่ยังเปิดอยู่แล้ว',
        errors: [], extensions: { ptp_uid: 'p-9' },
      },
    })
    const user = userEvent.setup()
    renderScreen(drawer())
    await user.selectOptions(screen.getByLabelText(/^ช่องทาง/), 'LINE')
    await user.selectOptions(await screen.findByLabelText(/^ผลการติดต่อ/), 'PROMISED')
    await user.type(screen.getByLabelText(/จำนวนเงินนัดชำระ/), '1500')
    await user.click(screen.getByRole('button', { name: 'บันทึก' }))
    expect(await screen.findByText('ลูกค้ารายนี้มีนัดชำระที่ยังเปิดอยู่แล้ว')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'เจรจาใหม่' }))
    await waitFor(() => expect(api.renegotiatePtp).toHaveBeenCalled())
    expect(api.renegotiatePtp.mock.calls[0][0]).toBe('p-9')
    expect(api.renegotiatePtp.mock.calls[0][1]).toMatchObject({ amount: '1500', date: '2026-10-24' })
  })

  it('moves an open promise through เลื่อนนัด mode instead of duplicating it', async () => {
    const user = userEvent.setup()
    renderScreen(drawer({
      promise: {
        uid: 'p-1', status: 'OPEN', promised_amount: '500.00',
        promise_date: '2026-10-30', renegotiation_count: 1,
      },
    }))
    await user.selectOptions(screen.getByLabelText(/^ช่องทาง/), 'LINE')
    await user.selectOptions(await screen.findByLabelText(/^ผลการติดต่อ/), 'PROMISED')
    expect(screen.getByText('เลื่อนนัดชำระ (ผิดนัด / เลื่อนนัด)')).toBeInTheDocument()
    expect(screen.getByText(/เลื่อนมาแล้ว 1 ครั้ง/)).toBeInTheDocument()
    await user.type(screen.getByLabelText(/เหตุผลที่เลื่อน/), 'ลูกค้าขอเลื่อนออกไป')
    await user.click(screen.getByRole('button', { name: 'บันทึก' }))
    await waitFor(() => expect(api.renegotiatePtp).toHaveBeenCalled())
    expect(api.logCaseContact).not.toHaveBeenCalled()
    expect(api.renegotiatePtp.mock.calls[0][0]).toBe('p-1')
    expect(api.renegotiatePtp.mock.calls[0][1]).toMatchObject({ reason: 'ลูกค้าขอเลื่อนออกไป' })
  })

  it('renders the three-cell summary from the served strings', async () => {
    renderScreen(drawer({
      summary: { arrears: '8,697.00', paid: 23, total: 96, remaining: 73 },
    }))
    expect(await screen.findByText('ยอดค้าง')).toBeInTheDocument()
    expect(screen.getByText('8,697.00')).toBeInTheDocument()
    expect(screen.getByText(/23 \/ 96/)).toBeInTheDocument()
    expect(screen.getByText('73')).toBeInTheDocument()
  })

  it('formats the served outstanding in the strip (it printed raw)', () => {
    const summary = contactSummary({ payment_summary: { totals: { overdue_amount: '48600.00', cycle_count: 96, paid_count: 23, remaining_count: 73 } } })
    expect(summary).toEqual({ arrears: '48,600.00', paid: 23, total: 96, remaining: 73 })
  })

  it('uses the served instalment breakdown instead of counting a deposit', () => {
    const summary = contactSummary({ payment_summary: { totals: {
      overdue_amount: '0.00', cycle_count: 2, paid_count: 1, remaining_count: 1,
      breakdown: { instalment: { count: 1, counts: { PAID: 0 }, remaining_count: 1 } },
    } } })

    expect(summary).toEqual({ arrears: '0.00', paid: 0, total: 1, remaining: 1 })
  })

  it('keeps Save\'s rule and missing field as its tooltip', async () => {
    const user = userEvent.setup()
    renderScreen(drawer())
    const save = await screen.findByRole('button', { name: 'บันทึก' })
    await waitFor(() => expect(save).toHaveAttribute('title', 'นับเป็นการติดต่อวันนี้ · คืนสิทธิ์ได้ภายใน 90 วินาที'))
    await user.selectOptions(screen.getByLabelText(/^ผลการติดต่อ/), 'REACHED_PTP')
    expect(save).toHaveAttribute('title', 'ผลการติดต่อเป็นนัดชำระ ต้องระบุจำนวนเงินและวันที่นัดก่อนบันทึก')
  })
})

describe('the locked daily slot\'s ways through (contact_locked)', () => {
  const LOCKED = {
    problem: {
      code: 'contact_locked', message_th: 'ลูกค้ารายนี้ถูกติดต่อแล้ววันนี้',
      extensions: { alternatives: [
        { code: 'INBOUND_NOT_COUNTED', label_th: 'บันทึกเป็นลูกค้าติดต่อเข้า (ไม่นับครั้ง) พร้อมกล่อง PTP' },
        { code: 'SECOND_CONTACT_NOT_COUNTED', label_th: 'บันทึกการติดต่อครั้งที่สอง (ไม่นับ)' },
      ] },
    },
  }

  it('records the inbound way as INBOUND and the second contact declared not counted', async () => {
    const user = userEvent.setup()
    api.logContact.mockRejectedValueOnce(LOCKED)
    renderScreen(drawer())
    await user.click(await screen.findByRole('button', { name: 'บันทึก' }))
    expect(await screen.findByText('ลูกค้ารายนี้ถูกติดต่อแล้ววันนี้')).toBeInTheDocument()
    api.logContact.mockResolvedValueOnce({ counted: false })
    await user.click(screen.getByRole('button', { name: 'บันทึกเป็นลูกค้าติดต่อเข้า (ไม่นับครั้ง) พร้อมกล่อง PTP' }))
    await waitFor(() => expect(api.logCaseContact).toHaveBeenCalledTimes(1))
    expect(api.logContact.mock.calls[1][0]).toMatchObject({ direction: 'INBOUND' })
    expect(api.logCaseContact.mock.calls[0][1]).toMatchObject({ direction: 'INBOUND', counted: false })

    api.logContact.mockRejectedValueOnce(LOCKED)
    renderScreen(drawer())
    await user.click((await screen.findAllByRole('button', { name: 'บันทึก' })).at(-1))
    await user.click(await screen.findByRole('button', { name: 'บันทึกการติดต่อครั้งที่สอง (ไม่นับ)' }))
    await waitFor(() => expect(api.logCaseContact).toHaveBeenCalledTimes(2))
    expect(api.logContact.mock.calls.at(-1)[0]).toMatchObject({ direction: 'OUTBOUND', not_counted: true })
  })

  it('hands the slot\'s not-counted answer to the case row, like counted (fix-all Leg R)', async () => {
    const user = userEvent.setup()
    renderScreen(drawer())
    await user.click(await screen.findByRole('button', { name: 'บันทึก' }))
    await waitFor(() => expect(api.logCaseContact).toHaveBeenCalledTimes(1))
    expect(api.logCaseContact.mock.calls[0][1]).toMatchObject({ counted: true, not_counted: false })

    api.logContact.mockRejectedValueOnce(LOCKED)
    renderScreen(drawer())
    await user.click((await screen.findAllByRole('button', { name: 'บันทึก' })).at(-1))
    api.logContact.mockResolvedValueOnce({ counted: false, not_counted_declared: true })
    await user.click(await screen.findByRole('button', { name: 'บันทึกการติดต่อครั้งที่สอง (ไม่นับ)' }))
    await waitFor(() => expect(api.logCaseContact).toHaveBeenCalledTimes(2))
    expect(api.logCaseContact.mock.calls[1][1]).toMatchObject({ counted: false, not_counted: true })
  })

  it('re-sends a refused move of a promise as not counted', async () => {
    const user = userEvent.setup()
    api.renegotiatePtp.mockRejectedValueOnce(LOCKED)
    renderScreen(drawer({
      promise: { uid: 'p-1', status: 'BROKEN', promised_amount: '500.00', promise_date: '2026-10-20', renegotiation_count: 0 },
    }))
    await user.selectOptions(await screen.findByLabelText(/^ผลการติดต่อ/), 'REACHED_PTP')
    expect(screen.getByText('เลื่อนมาแล้ว 0 ครั้ง · ผิดนัด · ฿500.00 · 20/10/2026')).toHaveAttribute('title', 'ครั้งที่ 3 ต้องให้ผู้จัดการตรวจ')
    await user.type(screen.getByLabelText(/เหตุผลที่เลื่อน/), 'ลูกค้าขอเลื่อน')
    await user.click(screen.getByRole('button', { name: 'บันทึก' }))
    await user.click(await screen.findByRole('button', { name: 'บันทึกการติดต่อครั้งที่สอง (ไม่นับ)' }))
    await waitFor(() => expect(api.renegotiatePtp).toHaveBeenCalledTimes(2))
    expect(api.renegotiatePtp.mock.calls[1][1]).toMatchObject({ not_counted: true, reason: 'ลูกค้าขอเลื่อน' })
  })
})

describe('a reload of the same customer keeps the form', () => {
  // The case reloads after a refused save; here the reload brings a new promise.
  function Host() {
    const [open, setOpen] = useState(true)
    const [promise, setPromise] = useState(undefined)
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>เปิดอีกครั้ง</button>
        <ContactDrawer open={open} onClose={() => setOpen(false)} customer={CUSTOMER} businessDate="2026-10-23"
                       promise={promise}
                       onSaved={() => setPromise({ uid: 'p-9', status: 'OPEN', promised_amount: '700.00', promise_date: '2026-10-30' })} />
      </>
    )
  }

  it('keeps the refusal and the typed fields, and starts fresh only on re-open', async () => {
    const user = userEvent.setup()
    api.logCaseContact.mockRejectedValue({ problem: { code: 'ptp_already_open', message_th: 'มีนัดชำระที่เปิดอยู่แล้ว', extensions: { ptp_uid: 'p-9' } } })
    renderScreen(<Host />)
    await user.selectOptions(await screen.findByLabelText(/^ผลการติดต่อ/), 'REACHED_PTP')
    await user.type(screen.getByLabelText(/จำนวนเงินนัดชำระ/), '1500')
    await user.type(screen.getByLabelText('บันทึกเพิ่มเติม'), 'ลูกค้ารับปาก')
    await user.click(screen.getByRole('button', { name: 'บันทึก' }))
    expect(await screen.findByText('มีนัดชำระที่เปิดอยู่แล้ว')).toBeInTheDocument()
    // the reloaded case carries p-9: the answer and what was typed stay
    await waitFor(() => expect(screen.getByText('เลื่อนนัดชำระ (ผิดนัด / เลื่อนนัด)')).toBeInTheDocument())
    expect(screen.getByText('เลื่อนมาแล้ว 0 ครั้ง · นัดเปิดอยู่ · ฿700.00 · 30/10/2026')).toBeInTheDocument()   // the fresh promise
    expect(screen.getByText('มีนัดชำระที่เปิดอยู่แล้ว')).toBeInTheDocument()
    expect(screen.getByLabelText('บันทึกเพิ่มเติม')).toHaveValue('ลูกค้ารับปาก')
    expect(screen.getByLabelText(/จำนวนเงินนัดชำระ/)).toHaveValue('1500')
    // closing and opening again is a fresh form
    await user.click(screen.getByRole('button', { name: 'ยกเลิก' }))
    await user.click(screen.getByRole('button', { name: 'เปิดอีกครั้ง' }))
    expect(await screen.findByLabelText('บันทึกเพิ่มเติม')).toHaveValue('')
    expect(screen.queryByText('มีนัดชำระที่เปิดอยู่แล้ว')).toBeNull()
  })
})

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { PhoneLine } from './PhoneLine.jsx'
import { renderScreen } from '../test-utils.jsx'

vi.mock('../lib/api.js', () => ({
  api: { revealCustomerPhone: vi.fn() },
}))
const { api } = await import('../lib/api.js')

const BASE = {
  uid: 'c-1', customer_no: 'C-1', display_name: 'ธีรวัฒน์ ศรีอุดม',
  phone_masked: '08x-xxx-6632', phone_on_file: true, phone_revealable: true,
}

const REVEALED = {
  uid: 'c-1', phone_e164: '+66812346632', phone_display: '081-234-6632',
  kind: 'MOBILE', source: 'IMPORT',
}

function stubClipboard(writeText) {
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
}

beforeEach(() => {
  vi.clearAllMocks()
  Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
})

describe('PhoneLine', () => {
  it('rests on the mask and never renders the full number before the reveal', () => {
    renderScreen(<PhoneLine customer={BASE} />)
    expect(screen.getByText('08x-xxx-6632')).toBeInTheDocument()
    expect(screen.queryByText('081-234-6632')).toBeNull()
    expect(screen.getByRole('button', { name: 'เปิดเบอร์' })).toHaveAttribute('aria-pressed', 'false')
    expect(api.revealCustomerPhone).not.toHaveBeenCalled()
  })

  it('reveals through the audited route and hides again without a second call', async () => {
    const user = userEvent.setup()
    api.revealCustomerPhone.mockResolvedValue({ customer: REVEALED })
    renderScreen(<PhoneLine customer={BASE} />)

    await user.click(screen.getByRole('button', { name: 'เปิดเบอร์' }))
    await waitFor(() => expect(api.revealCustomerPhone).toHaveBeenCalledWith('c-1'))
    expect(await screen.findByText('081-234-6632')).toBeInTheDocument()
    expect(screen.queryByText('08x-xxx-6632')).toBeNull()
    const hide = screen.getByRole('button', { name: 'ซ่อนเบอร์' })
    expect(hide).toHaveAttribute('aria-pressed', 'true')

    await user.click(hide)
    expect(screen.getByText('08x-xxx-6632')).toBeInTheDocument()
    expect(api.revealCustomerPhone).toHaveBeenCalledTimes(1)
  })

  it('copies the revealed number and says so', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn().mockResolvedValue(undefined)
    stubClipboard(writeText)
    api.revealCustomerPhone.mockResolvedValue({ customer: REVEALED })
    renderScreen(<PhoneLine customer={BASE} />)

    await user.click(screen.getByRole('button', { name: 'คัดลอก' }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('081-234-6632'))
    expect(api.revealCustomerPhone).toHaveBeenCalledTimes(1)   // one act, one audit row
    expect(await screen.findByRole('status')).toHaveTextContent('คัดลอกเบอร์แล้ว')
  })

  it('offers a real tel: link once the number is open, and dials through the reveal first', async () => {
    const user = userEvent.setup()
    api.revealCustomerPhone.mockResolvedValue({ customer: REVEALED })
    const original = window.location
    Object.defineProperty(window, 'location', { value: { href: '' }, configurable: true })
    try {
      renderScreen(<PhoneLine customer={BASE} />)

      await user.click(screen.getByRole('button', { name: 'โทร' }))
      await waitFor(() => expect(api.revealCustomerPhone).toHaveBeenCalledTimes(1))
      await waitFor(() => expect(window.location.href).toBe('tel:+66812346632'))
      const link = await screen.findByRole('link', { name: 'โทรไปที่เบอร์ 081-234-6632' })
      expect(link).toHaveAttribute('href', 'tel:+66812346632')
      expect(document.querySelector('.record__phoneValue')).toHaveTextContent('081-234-6632')
    } finally {
      Object.defineProperty(window, 'location', { value: original, configurable: true })
    }
  })

  it('says a mask-only import has no full number instead of offering dead buttons', () => {
    renderScreen(<PhoneLine customer={{ ...BASE, phone_revealable: false }} />)
    expect(screen.getByText('08x-xxx-6632')).toBeInTheDocument()
    expect(screen.getByText('ไฟล์นำเข้ามีแต่เบอร์ที่ถูกปิด — ยังไม่มีเบอร์เต็มในระบบ')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'เปิดเบอร์' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'โทร' })).toBeNull()
  })

  it('says so when the customer has no number at all', () => {
    renderScreen(<PhoneLine customer={{ uid: 'c-9', phone_masked: null, phone_on_file: false, phone_revealable: false }} />)
    expect(screen.getByText('ไม่มีเบอร์ในระบบ')).toBeInTheDocument()
    // no number at all: the hint alone, never a placeholder standing in for a number
    expect(document.querySelector('.record__phoneValue')).toBeNull()
    expect(screen.queryByRole('button', { name: 'เปิดเบอร์' })).toBeNull()
  })

  it('keeps the mask in place and shows the server sentence when the reveal is refused', async () => {
    const user = userEvent.setup()
    api.revealCustomerPhone.mockRejectedValue({ problem: {
      code: 'phone_not_on_file', title: 'No full number is on file',
      message_th: 'ยังไม่มีเบอร์เต็มในระบบสำหรับลูกค้ารายนี้',
    } })
    renderScreen(<PhoneLine customer={BASE} />)

    await user.click(screen.getByRole('button', { name: 'เปิดเบอร์' }))
    expect(await screen.findByText('ยังไม่มีเบอร์เต็มในระบบสำหรับลูกค้ารายนี้')).toBeInTheDocument()
    expect(within(document.querySelector('.record__phone')).getByText('08x-xxx-6632')).toBeInTheDocument()
    expect(screen.queryByText('081-234-6632')).toBeNull()
  })
})

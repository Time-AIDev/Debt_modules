import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { SocialComposer } from './SocialComposer.jsx'

vi.mock('../lib/api.js', () => ({
  api: {
    messageTemplates: vi.fn(),
    createMessageTemplate: vi.fn(),
  },
}))
const { api } = await import('../lib/api.js')
let clipboardWrite

beforeEach(() => {
  vi.clearAllMocks()
  api.messageTemplates.mockResolvedValue({
    items: [{ uid: 'mt-1', channel: 'LINE', name: 'เตือนนัด', body: 'ขอแจ้งเตือนยอดนัดชำระ' }],
  })
  api.createMessageTemplate.mockResolvedValue({ template: { uid: 'mt-2' } })
  clipboardWrite = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: clipboardWrite },
  })
  vi.spyOn(window, 'open').mockImplementation(() => null)
})

describe('SocialComposer', () => {
  it('selects a personal template, copies first, then reveals the LINE link', async () => {
    const user = userEvent.setup()
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: clipboardWrite } })
    renderScreen(<SocialComposer open channel="LINE" recipientId="line-user" onClose={() => {}} />)
    const dialog = await screen.findByRole('dialog', { name: 'ส่งข้อความทาง LINE' })
    await waitFor(() => expect(api.messageTemplates).toHaveBeenCalledWith({ channel: 'LINE' }))
    await user.selectOptions(within(dialog).getByLabelText('เทมเพลตส่วนตัว'), 'mt-1')
    expect(within(dialog).getByLabelText('ข้อความ')).toHaveValue('ขอแจ้งเตือนยอดนัดชำระ')
    expect(within(dialog).queryByRole('button', { name: 'เปิด LINE' })).not.toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: 'คัดลอกข้อความ' }))
    expect(clipboardWrite).toHaveBeenCalledWith('ขอแจ้งเตือนยอดนัดชำระ')
    await user.click(within(dialog).getByRole('button', { name: 'เปิด LINE' }))
    expect(window.open).toHaveBeenCalledWith('https://line.me/R/ti/p/~line-user', '_blank', 'noopener,noreferrer')
  })

  it('opens Facebook Messenger through m.me only after copying', async () => {
    api.messageTemplates.mockResolvedValue({ items: [] })
    const user = userEvent.setup()
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: clipboardWrite } })
    renderScreen(<SocialComposer open channel="FACEBOOK" recipientId="meta-user" onClose={() => {}} />)
    const dialog = await screen.findByRole('dialog', { name: 'ส่งข้อความทาง Facebook' })
    await user.type(within(dialog).getByLabelText('ข้อความ'), 'สวัสดีค่ะ')
    await user.click(within(dialog).getByRole('button', { name: 'คัดลอกข้อความ' }))
    await user.click(within(dialog).getByRole('button', { name: 'เปิด Facebook' }))
    expect(window.open).toHaveBeenCalledWith('https://m.me/meta-user', '_blank', 'noopener,noreferrer')
  })
})

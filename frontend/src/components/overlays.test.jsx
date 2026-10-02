import { describe, it, expect, vi } from 'vitest'
import { useState } from 'react'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { ConfirmDialog } from './ConfirmDialog.jsx'
import { Drawer } from './Drawer.jsx'
import { InfoPopover } from './InfoPopover.jsx'
import { StatusIcon, StatusPill } from './StatusIcon.jsx'

function ConfirmHost({ onConfirm }) {
  const [open, setOpen] = useState(true)
  return (
    <ConfirmDialog open={open} onClose={() => setOpen(false)} onConfirm={onConfirm} title="ใช้รายงานนี้กับระบบ"
                   confirmLabel="ยืนยันใช้รายงาน">
      ระบบจะใช้รายงานนี้แทนรายงานเดิม
    </ConfirmDialog>
  )
}

describe('the confirm dialog', () => {
  it('starts on cancel, confirms with its own verb and closes on Esc', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    renderScreen(<ConfirmHost onConfirm={onConfirm} />)
    expect(screen.getByRole('dialog', { name: 'ใช้รายงานนี้กับระบบ' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ยกเลิก' })).toHaveFocus()

    await user.click(screen.getByRole('button', { name: 'ยืนยันใช้รายงาน' }))
    expect(onConfirm).toHaveBeenCalledTimes(1)

    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })
})

describe('the info popover', () => {
  it('opens a kept notice from a named "i" and closes on Esc', async () => {
    const user = userEvent.setup()
    renderScreen(<InfoPopover>ขั้นชี้แนะมาจากปฏิทินบันไดเท่านั้น</InfoPopover>)
    const trigger = screen.getByRole('button', { name: 'ข้อมูลเพิ่มเติม' })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')

    await user.click(trigger)
    expect(screen.getByText('ขั้นชี้แนะมาจากปฏิทินบันไดเท่านั้น')).toBeInTheDocument()
    expect(trigger).toHaveAttribute('aria-expanded', 'true')

    await user.keyboard('{Escape}')
    expect(screen.queryByText('ขั้นชี้แนะมาจากปฏิทินบันไดเท่านั้น')).toBeNull()
  })
})

describe('the status icon', () => {
  it('is decorative beside its word, named when it stands alone, and idle when unknown', () => {
    const { container } = renderScreen(
      <>
        <StatusPill kind="problem">ผิดนัด</StatusPill>
        <StatusIcon kind="moving-3" title="กำลังดำเนินการ" />
        <StatusIcon kind="nope" />
      </>,
    )
    expect(screen.getByText('ผิดนัด').closest('.pill')).toHaveClass('pill--problem')
    expect(screen.getByRole('img', { name: 'กำลังดำเนินการ' })).toHaveClass('st--moving-3')
    expect(container.querySelectorAll('svg[aria-hidden="true"]')).toHaveLength(2)
    expect(container.querySelector('.st--idle')).not.toBeNull()
  })
})

describe('overlay placement and first focus', () => {
  it('skips a disabled field when choosing where focus starts', () => {
    // The apply confirm below Manager: its "ใช้รายงานเก่ากว่า" box is disabled, and a
    // disabled field cannot take focus — focus must land on the first live control.
    renderScreen(
      <ConfirmDialog open onClose={() => {}} onConfirm={() => {}} title="ใช้รายงานนี้กับระบบ">
        <label>ใช้รายงานเก่ากว่า<input type="checkbox" disabled /></label>
      </ConfirmDialog>,
    )
    expect(screen.getByRole('button', { name: 'ยกเลิก' })).toHaveFocus()
  })

  it('sits over the content column only, leaving the rail and top bar in view', () => {
    const main = document.createElement('main')
    main.id = 'main'
    main.getBoundingClientRect = () => ({ top: 92, left: 248, right: 1440, bottom: 900, width: 1192, height: 808 })
    document.body.appendChild(main)
    try {
      renderScreen(<Drawer open onClose={() => {}} title="ย้ายลูกค้า"><p>x</p></Drawer>)
      const root = screen.getByRole('dialog', { name: 'ย้ายลูกค้า' })
      expect(root.style.top).toBe('92px')
      expect(root.style.left).toBe('248px')
    } finally {
      main.remove()
    }
  })
})

import { describe, it, expect, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { Board } from './Board.jsx'

const COLUMNS = [
  { id: 'col_01H8X', label: 'โทรวันนี้' },
  { id: 'col_01H8Y', label: 'รอชำระ' },
  { id: 'col_01H8Z', label: 'รับปากชำระ' },
  { id: 'col_01H90', label: 'ยกระดับ' },
]

// The status icon each lane head carries (brief §3.2), read off its class.
function laneIcons(container) {
  return [...container.querySelectorAll('.board__col')].map((c) => {
    const st = c.querySelector('.board__head .st')
    return st ? [...st.classList].find((k) => k.startsWith('st--')) : null
  })
}

const CARD = {
  uid: 'c-1', name: 'ปัทมวรรณ สุขเจริญ', icon: 'do', entity: 'SPV', source: { identity: 'SHEET' }, score: 78,
  arrears: '48600.00', balance: '612400.00', dpd: 24, bandLabel: 'ค้างไม่ถึง 30 วัน', nextAction: 'ตรวจสอบยอดตามนัด',
  locked: true, lockedBy: 'สมชาย', pendingReview: 'rv-1', columnId: 'col_01H8Z',
}

describe('Board', () => {
  it('heads each served status column with its own status icon', () => {
    const { container } = renderScreen(<Board columns={COLUMNS} items={[]} reconcile={0} />)
    expect(laneIcons(container)).toEqual(['st--do', 'st--idle', 'st--moving-2', 'st--problem'])
  })

  it('keeps a plain head for a column the status mapping does not know (a new column, a recovery stage)', () => {
    const { container } = renderScreen(<Board
      columns={[...COLUMNS, { id: 'col_custom', label: 'คอลัมน์ใหม่' }, { id: 'CONTACT', label: 'ติดต่อ' }]}
      items={[]}
      reconcile={0}
    />)
    expect(laneIcons(container).slice(-2)).toEqual([null, null])
    expect(screen.getByRole('region', { name: 'ติดต่อ' })).toBeInTheDocument()
  })

  it('draws the card parts and hands the name, the log and the move to the caller', async () => {
    const onOpen = vi.fn()
    const onLog = vi.fn()
    const onMove = vi.fn()
    const user = userEvent.setup()
    renderScreen(<Board columns={COLUMNS} items={[CARD]} reconcile={1} onOpen={onOpen} onLog={onLog} onMove={onMove} />)
    const card = screen.getByRole('article', { name: 'ปัทมวรรณ สุขเจริญ' })
    for (const text of ['48,600.00', 'DPD 24', 'ค้างไม่ถึง 30 วัน', 'ตรวจสอบยอดตามนัด', 'เสี่ยง 78', 'ติดต่อแล้ว · สมชาย', 'รอผู้จัดการ']) {
      expect(within(card).getByText(text)).toBeInTheDocument()
    }
    await user.click(within(card).getByRole('button', { name: 'ปัทมวรรณ สุขเจริญ' }))
    expect(onOpen).toHaveBeenCalledWith('c-1')
    await user.click(within(card).getByRole('button', { name: 'บันทึกผลการติดต่อ' }))
    expect(onLog).toHaveBeenCalledWith(expect.objectContaining({ uid: 'c-1' }))
    await user.click(within(card).getByRole('button', { name: 'ย้าย…' }))
    expect(onMove).toHaveBeenCalledWith(expect.objectContaining({ uid: 'c-1' }))
  })

  it('reports a card outside the served columns in a refusal box instead of dropping it', () => {
    renderScreen(<Board columns={COLUMNS} items={[{ ...CARD, columnId: 'col_gone' }]} reconcile={1} />)
    const box = screen.getByRole('alert')
    expect(box).toHaveTextContent('1 รายอยู่นอกคอลัมน์ที่ให้บริการ')
    expect(box).toHaveTextContent('ปัทมวรรณ สุขเจริญ')
  })
})

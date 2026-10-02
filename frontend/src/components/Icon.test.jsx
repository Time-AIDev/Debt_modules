import { render } from '@testing-library/react'
import { Icon, ICON_NAMES } from './Icon.jsx'

describe('Icon (the design sprite ic-* set)', () => {
  it('draws a known icon as a decorative svg and nothing for an unknown name', () => {
    const { container, rerender } = render(<Icon name="phone" />)
    const svg = container.querySelector('svg.icon')
    expect(svg).toHaveAttribute('aria-hidden', 'true')
    expect(svg.querySelectorAll('path').length).toBeGreaterThan(0)
    rerender(<Icon name="nope" />)
    expect(container.querySelector('svg')).toBeNull()
  })

  it('carries all 34 UI icons of the design and names itself when titled', () => {
    expect(ICON_NAMES).toHaveLength(34)
    const { getByRole } = render(<Icon name="close" title="ปิด" />)
    expect(getByRole('img', { name: 'ปิด' })).toBeInTheDocument()
  })
})

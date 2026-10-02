import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PrefsProvider, usePrefs, PREFS_KEYS } from './prefs.jsx'

function Probe() {
  const p = usePrefs()
  return (
    <div>
      <span data-testid="lang">{p.lang}</span>
      <span data-testid="theme">{p.theme}</span>
      <span data-testid="density">{p.density}</span>
      <span data-testid="rail">{p.railOpen ? 'open' : 'closed'}</span>
      <span data-testid="rail-width">{p.railWidth}</span>
      <span data-testid="today">{p.todayView}</span>
      <button type="button" onClick={() => p.setLang('en')}>en</button>
      <button type="button" onClick={() => p.setTheme('dark')}>dark</button>
      <button type="button" onClick={() => p.setDensity('comfortable')}>roomy</button>
      <button type="button" onClick={() => p.setRailOpen(false)}>collapse</button>
      <button type="button" onClick={() => p.setTodayView('board')}>board</button>
    </div>
  )
}

beforeEach(() => window.localStorage.clear())

describe('prefs', () => {
  it('defaults to Thai, dark, roomy, open wide rail, split Today', () => {
    render(<PrefsProvider><Probe /></PrefsProvider>)
    expect(screen.getByTestId('lang')).toHaveTextContent('th')
    expect(screen.getByTestId('theme')).toHaveTextContent('dark')
    expect(screen.getByTestId('density')).toHaveTextContent('comfortable')
    expect(screen.getByTestId('rail')).toHaveTextContent('open')
    expect(screen.getByTestId('rail-width')).toHaveTextContent('normal')
    expect(screen.getByTestId('today')).toHaveTextContent('split')
  })

  it('resets the old display choices exactly once', () => {
    window.localStorage.setItem(PREFS_KEYS.lang, 'en')
    window.localStorage.setItem(PREFS_KEYS.theme, 'light')
    window.localStorage.setItem(PREFS_KEYS.density, 'compact')
    window.localStorage.setItem(PREFS_KEYS.railOpen, 'closed')
    window.localStorage.setItem(PREFS_KEYS.railWidth, 'narrow')

    const first = render(<PrefsProvider><Probe /></PrefsProvider>)
    expect(screen.getByTestId('lang')).toHaveTextContent('th')
    expect(screen.getByTestId('theme')).toHaveTextContent('dark')
    expect(screen.getByTestId('density')).toHaveTextContent('comfortable')
    expect(screen.getByTestId('rail')).toHaveTextContent('open')
    expect(screen.getByTestId('rail-width')).toHaveTextContent('normal')
    expect(window.localStorage.getItem(PREFS_KEYS.version)).toBe('2')
    first.unmount()

    window.localStorage.setItem(PREFS_KEYS.theme, 'light')
    render(<PrefsProvider><Probe /></PrefsProvider>)
    expect(screen.getByTestId('theme')).toHaveTextContent('light')
  })

  it('persists each choice under the volt.* keys', async () => {
    const user = userEvent.setup()
    render(<PrefsProvider><Probe /></PrefsProvider>)
    await user.click(screen.getByRole('button', { name: 'en' }))
    await user.click(screen.getByRole('button', { name: 'dark' }))
    await user.click(screen.getByRole('button', { name: 'roomy' }))
    await user.click(screen.getByRole('button', { name: 'collapse' }))
    await user.click(screen.getByRole('button', { name: 'board' }))
    expect(window.localStorage.getItem(PREFS_KEYS.lang)).toBe('en')
    expect(window.localStorage.getItem(PREFS_KEYS.theme)).toBe('dark')
    expect(window.localStorage.getItem(PREFS_KEYS.density)).toBe('comfortable')
    expect(window.localStorage.getItem(PREFS_KEYS.railOpen)).toBe('closed')
    expect(window.localStorage.getItem(PREFS_KEYS.todayView)).toBe('board')
  })

  it('applies theme and density to the document root', async () => {
    const user = userEvent.setup()
    render(<PrefsProvider><Probe /></PrefsProvider>)
    await user.click(screen.getByRole('button', { name: 'dark' }))
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    await user.click(screen.getByRole('button', { name: 'roomy' }))
    expect(document.documentElement.getAttribute('data-density')).toBe('comfortable')
  })

  it('falls back to split for an unknown stored today view', () => {
    window.localStorage.setItem(PREFS_KEYS.todayView, 'kanban')
    render(<PrefsProvider><Probe /></PrefsProvider>)
    expect(screen.getByTestId('today')).toHaveTextContent('split')
  })

  it('falls back to split for the retired list view, so an upgrade loses nothing', () => {
    window.localStorage.setItem(PREFS_KEYS.todayView, 'list')
    render(<PrefsProvider><Probe /></PrefsProvider>)
    expect(screen.getByTestId('today')).toHaveTextContent('split')
  })
})

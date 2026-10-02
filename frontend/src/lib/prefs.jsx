// Display preferences only: language, theme, density, rail width/open, Today view.
// Storage keys keep the `volt.*` names the previous build used. Version 2 resets
// the feedback defaults once; choices made after that migration persist normally.
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { translate, served } from './i18n/index.js'

export const PREFS_KEYS = {
  version: 'volt.prefs.version',
  lang: 'volt.lang',
  theme: 'volt.theme',
  density: 'volt.density',
  railOpen: 'volt.shell.rail',
  railWidth: 'volt.shell.railWidth',
  todayView: 'volt.today-view',
}

const PREFS_VERSION = '2'

function migratePreferences() {
  try {
    if (window.localStorage.getItem(PREFS_KEYS.version) === PREFS_VERSION) return
    window.localStorage.setItem(PREFS_KEYS.lang, 'th')
    window.localStorage.setItem(PREFS_KEYS.theme, 'dark')
    window.localStorage.setItem(PREFS_KEYS.density, 'comfortable')
    window.localStorage.setItem(PREFS_KEYS.railOpen, 'open')
    window.localStorage.setItem(PREFS_KEYS.railWidth, 'normal')
    window.localStorage.setItem(PREFS_KEYS.version, PREFS_VERSION)
  } catch { /* private mode */ }
}

export const TODAY_VIEWS = ['split', 'board']

function read(key, allowed, fallback) {
  try {
    const v = window.localStorage.getItem(key)
    return allowed.includes(v) ? v : fallback
  } catch {
    return fallback
  }
}

function persist(key, value) {
  try { window.localStorage.setItem(key, value) } catch { /* private mode */ }
}

const PrefsContext = createContext(null)

export function PrefsProvider({ children }) {
  migratePreferences()
  const [lang, setLangState] = useState(() => read(PREFS_KEYS.lang, ['th', 'en'], 'th'))
  const [theme, setThemeState] = useState(() => read(PREFS_KEYS.theme, ['light', 'dark'], 'dark'))
  const [density, setDensityState] = useState(() => read(PREFS_KEYS.density, ['compact', 'comfortable'], 'comfortable'))
  const [railOpen, setRailOpenState] = useState(() => read(PREFS_KEYS.railOpen, ['open', 'closed'], 'open') === 'open')
  const [railWidth, setRailWidthState] = useState(() => read(PREFS_KEYS.railWidth, ['normal', 'narrow'], 'normal'))
  const [todayView, setTodayViewState] = useState(() => read(PREFS_KEYS.todayView, TODAY_VIEWS, 'split'))

  useEffect(() => {
    const root = document.documentElement
    root.setAttribute('data-theme', theme)
    root.setAttribute('data-density', density === 'comfortable' ? 'comfortable' : 'compact')
    root.lang = lang
  }, [theme, density, lang])

  const setLang = useCallback((v) => {
    if (!['th', 'en'].includes(v)) return
    persist(PREFS_KEYS.lang, v)
    setLangState(v)
  }, [])
  const setTheme = useCallback((v) => {
    if (!['light', 'dark'].includes(v)) return
    persist(PREFS_KEYS.theme, v)
    setThemeState(v)
  }, [])
  const setDensity = useCallback((v) => {
    if (!['compact', 'comfortable'].includes(v)) return
    persist(PREFS_KEYS.density, v)
    setDensityState(v)
  }, [])
  const setRailOpen = useCallback((v) => {
    persist(PREFS_KEYS.railOpen, v ? 'open' : 'closed')
    setRailOpenState(!!v)
  }, [])
  const setRailWidth = useCallback((v) => {
    if (!['normal', 'narrow'].includes(v)) return
    persist(PREFS_KEYS.railWidth, v)
    setRailWidthState(v)
  }, [])
  const setTodayView = useCallback((v) => {
    if (!TODAY_VIEWS.includes(v)) return
    persist(PREFS_KEYS.todayView, v)
    setTodayViewState(v)
  }, [])

  const t = useCallback((key, vars) => translate(lang, key, vars), [lang])
  const servedText = useCallback((obj, base) => served(obj, base, lang), [lang])

  const value = useMemo(() => ({
    lang, theme, density, railOpen, railWidth, todayView,
    t, served: servedText,
    setLang, setTheme, setDensity, setRailOpen, setRailWidth, setTodayView,
  }), [lang, theme, density, railOpen, railWidth, todayView, t, servedText,
    setLang, setTheme, setDensity, setRailOpen, setRailWidth, setTodayView])

  return <PrefsContext.Provider value={value}>{children}</PrefsContext.Provider>
}

export function usePrefs() {
  const ctx = useContext(PrefsContext)
  if (!ctx) throw new Error('usePrefs outside PrefsProvider')
  return ctx
}

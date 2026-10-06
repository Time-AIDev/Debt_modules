import { render } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { PrefsProvider } from './lib/prefs.jsx'
import { ToastProvider } from './components/Toast.jsx'
import { CrumbProvider } from './lib/crumb.jsx'
import { forgetDataState } from './lib/dataEpoch.jsx'

function wrap(ui, { route = '/' } = {}, withCrumb = true) {
  // The data-state cache is module-level (one shared read per page); a test render
  // must start from a fetch, or the previous test's payload leaks in.
  forgetDataState()
  const inner = withCrumb ? <CrumbProvider>{ui}</CrumbProvider> : ui
  // A deep-link screen must receive the same path parameters as the real App.
  // Rendering Record directly inside MemoryRouter gave useParams() an empty UID
  // while loose API mocks returned an unrelated fixture and concealed that gap.
  const routed = withCrumb && route.split('?')[0].startsWith('/customers/')
    ? <Routes><Route path="/customers/:uid" element={inner} /></Routes> : inner
  return render(
    <PrefsProvider>
      <ToastProvider>
        <MemoryRouter initialEntries={[route]}>{routed}</MemoryRouter>
      </ToastProvider>
    </PrefsProvider>,
  )
}

/** A screen or component that calls useCrumb needs the provider. */
export function renderScreen(ui, options) {
  return wrap(ui, options, true)
}

/** The App mounts its own CrumbProvider. */
export function renderApp(ui, options) {
  return wrap(ui, options, false)
}

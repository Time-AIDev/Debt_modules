import { useEffect, useState } from 'react'
import { Route, Routes, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { api, CHANGED_EVENT } from './lib/api.js'
import { DATA_EPOCH_EVENT } from './lib/events.js'
import { useDataStatePoll } from './lib/dataEpoch.jsx'
import { usePrefs } from './lib/prefs.jsx'
import { setRoster } from './lib/identity.jsx'
import { navItemByPath, groupKeyFor } from './lib/nav.js'
import { CrumbProvider, useCrumbContext } from './lib/crumb.jsx'
import { RecentsProvider, useRecents } from './lib/recents.jsx'
import { Rail } from './components/Rail.jsx'
import { Topbar } from './components/Topbar.jsx'
import { ContextTabs } from './components/ContextTabs.jsx'
import { Palette } from './components/Palette.jsx'
import { Today } from './screens/Today.jsx'
import { Record } from './screens/Record.jsx'
import { Dashboard } from './screens/Dashboard.jsx'
import { Book } from './screens/Book.jsx'
import { Reviews } from './screens/Reviews.jsx'
import { Payments } from './screens/Payments.jsx'
import { Recovery } from './screens/Recovery.jsx'
import { Reports } from './screens/Reports.jsx'
import { Settings } from './screens/Settings.jsx'
import { Calendar } from './screens/Calendar.jsx'
import { DataSources } from './screens/DataSources.jsx'
import { Terminated, ArchivedCase } from './screens/Terminated.jsx'
import { Audit } from './screens/Audit.jsx'
import { AccountingHistory } from './screens/AccountingHistory.jsx'

function LegacyTerminated() {
  const location = useLocation()
  return <Navigate to={`${location.pathname.replace(/^\/terminated/, '/audit/terminated')}${location.search}`}
    state={location.state} replace />
}

function Shell() {
  const { t, todayView } = usePrefs()
  const location = useLocation()
  const navigate = useNavigate()
  const { crumb } = useCrumbContext()
  const { items: recents, forget } = useRecents()
  const [summary, setSummary] = useState(null)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [tick, setTick] = useState(0)
  // Fix-all F4: an open screen hears of an import within 30 s, not at the next click.
  useDataStatePoll()

  // Not on navigation (2026-09-27): the counts move only after a write (CHANGED_EVENT)
  // or an import (DATA_EPOCH_EVENT), both bump `tick`. Refetching per pathname sent a
  // full-book build per click — each customer page is a new pathname — and the
  // abandoned ones still ran on staging's single CPU.
  useEffect(() => {
    let alive = true
    api.shellSummary().then((d) => { if (alive) setSummary(d) }).catch(() => { if (alive) setSummary(null) })
    return () => { alive = false }
  }, [tick])

  useEffect(() => {
    let alive = true
    api.officers().then((d) => { if (alive) setRoster(d?.officers || []) }).catch(() => {})
    return () => { alive = false }
  }, [])

  useEffect(() => {
    const onChanged = () => setTick((n) => n + 1)
    // A moved import epoch moves the rail's facts too (another browser applied a
    // report / pulled leads): the rail must not wait for the next navigation.
    window.addEventListener(CHANGED_EVENT, onChanged)
    window.addEventListener(DATA_EPOCH_EVENT, onChanged)
    return () => {
      window.removeEventListener(CHANGED_EVENT, onChanged)
      window.removeEventListener(DATA_EPOCH_EVENT, onChanged)
    }
  }, [])

  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen((v) => !v)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const item = navItemByPath(location.pathname)
  const groupKey = item ? groupKeyFor(item) : 'group.mine'
  const currentTab = {
    label: crumb.pageLabel || t(crumb.page),
    meta: crumb.pageLabel ? t(crumb.page) : t(groupKey || 'group.mine'),
  }

  useEffect(() => {
    const y = location.state?.restoreScroll
    if (typeof y !== 'number') return undefined
    const id = requestAnimationFrame(() => window.scrollTo({ top: y }))
    return () => cancelAnimationFrame(id)
  }, [location.key, location.state])

  return (
    <div className="shell">
      <a className="skip-link" href="#main">ข้ามไปเนื้อหา</a>
      <Rail summary={summary} />
      <div className="shell__col">
        <Topbar
          crumb={{ group: t(crumb.group || groupKey || 'group.mine'), page: currentTab.label, parent: crumb.parent }}
          onSearch={() => setPaletteOpen(true)}
        />
        <ContextTabs
          current={currentTab}
          recents={recents.map((r) => ({
            key: r.key,
            label: r.label,
            meta: r.meta,
            color: r.color,
            current: r.to === location.pathname,
            onOpen: () => navigate(r.to),
            onClose: () => forget(r.key),
          }))}
        />
        <main className="main" id="main" data-view={todayView}>
          <Routes>
            <Route path="/" element={<Today />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/book" element={<Book />} />
            <Route path="/customers/:uid" element={<Record />} />
            <Route path="/reviews" element={<Reviews />} />
            <Route path="/pipeline" element={<Navigate to="/?workstream=pre_install" replace />} />
            <Route path="/payments" element={<Payments />} />
            <Route path="/recovery" element={<Recovery />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/calendar" element={<Calendar />} />
            <Route path="/data-sources" element={<DataSources />} />
            <Route path="/terminated" element={<LegacyTerminated />} />
            <Route path="/terminated/:uid" element={<LegacyTerminated />} />
            <Route path="/audit" element={<Audit />} />
            <Route path="/audit/accounting-reviews" element={<AccountingHistory />} />
            <Route path="/audit/terminated" element={<Terminated />} />
            <Route path="/audit/terminated/:uid" element={<ArchivedCase />} />
            <Route path="/workbook" element={<Navigate to="/book" replace />} />
            <Route path="/customers" element={<Navigate to="/book" replace />} />
            <Route path="/reminders" element={<Navigate to="/calendar" replace />} />
            <Route path="/today" element={<Navigate to="/" replace />} />
            <Route path="/manager-review" element={<Navigate to="/reviews" replace />} />
            <Route path="/npl" element={<Navigate to="/recovery" replace />} />
            <Route path="/data" element={<Navigate to="/data-sources" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
      <Palette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  )
}

export default function App() {
  return (
    <CrumbProvider>
      <RecentsProvider>
        <Shell />
      </RecentsProvider>
    </CrumbProvider>
  )
}

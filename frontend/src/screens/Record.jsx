import { useMemo, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { usePrefs } from '../lib/prefs.jsx'
import { useCrumb } from '../lib/crumb.jsx'
import { useCaseDetail } from '../lib/useCaseDetail.js'
import { RecordView, businessDateOf } from '../components/RecordView.jsx'
import { ContactDrawer, contactSummary, openPromise } from '../components/ContactDrawer.jsx'

/** The standalone customer record route (board cards, deep links, book rows). */
export function Record() {
  const { uid } = useParams()
  const { t } = usePrefs()
  const { data, problem, load } = useCaseDetail(uid)
  const [contactOpen, setContactOpen] = useState(false)
  // Opened from the calendar → the back button returns there, to the same view.
  const via = useLocation().state
  const navigation = useMemo(() => {
    const legacyCalendar = via?.from === 'calendar'
    const origin = via?.origin || (legacyCalendar ? {
      to: '/calendar', state: { unit: via.unit, anchor: via.anchor }, label: 'nav.calendar', scrollY: 0,
    } : { to: '/', state: undefined, label: 'nav.today', scrollY: 0 })
    const safe = typeof origin?.to === 'string' && origin.to.startsWith('/') && !origin.to.startsWith('//')
      ? origin : { to: '/', state: undefined, label: 'nav.today', scrollY: 0 }
    const label = safe.label || 'nav.today'
    const state = { ...(safe.state || {}), restoreScroll: safe.scrollY || 0 }
    return { origin: safe, label, state, parent: { to: safe.to, state, label: t(label) } }
  }, [via, t])
  useCrumb('group.mine', navigation.label, data?.customer?.display_name, navigation.parent)

  return (
    <div className="stack">
      <div className="lensbar">
        <Link
          to={navigation.origin.to}
          state={navigation.state}
          className="btn btn--sm"
        >← {t(navigation.label)}</Link>
        <span className="lensbar__title">{data?.customer?.display_name || t('common.loading')}</span>
        <span className="spacer" />
      </div>
      <RecordView
        data={data}
        problem={problem}
        onRetry={load}
        onChanged={load}
        onLogContact={() => setContactOpen(true)}
      />
      <ContactDrawer
        open={contactOpen}
        onClose={() => setContactOpen(false)}
        customer={data?.customer}
        businessDate={businessDateOf(data)}
        summary={contactSummary(data)}
        promise={openPromise(data)}
        onSaved={load}
      />
    </div>
  )
}

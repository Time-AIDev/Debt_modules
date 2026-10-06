import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useCrumb } from '../lib/crumb.jsx'
import { internalOrigin, recordState } from '../lib/origin.js'
import { date } from '../lib/format.js'
import { ActionLogNav } from '../components/ActionLogNav.jsx'
import { DataTable } from '../components/DataTable.jsx'
import { LoadError } from '../components/Problem.jsx'
import { thaiTime, useHistoryRead, useHistoryScroll } from './Terminated.jsx'
import './history.css'

export function AccountingHistory() {
  const { t } = usePrefs()
  useCrumb('group.system', 'history.accounting')
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const query = params.toString()
  const { data, loading, problem, retry } = useHistoryRead(query,
    () => api.accountingHistory({ ...Object.fromEntries(params), page_size: 50 }))
  useHistoryScroll(data, location)
  const page = Number(params.get('page') || 1)
  const origin = location.state?.origin
  const back = origin?.to?.startsWith('/') && !origin.to.startsWith('//') ? origin : null
  function update(name, value) {
    const next = new URLSearchParams(params)
    value ? next.set(name, value) : next.delete(name)
    if (name !== 'page') next.delete('page')
    setParams(next, { replace: true })
  }
  return <div className="stack">
    {back ? <Link className="scr-meta" to={back.to}
      state={{ ...back.state, restoreScroll: back.scrollY }}>{t('history.backCase')}</Link> : null}
    <div className="lensbar"><h1 className="lensbar__title">{t('history.accounting')}</h1>
      <span className="lensbar__meta num">{data?.meta?.total ?? '—'} {t('history.entries')}</span></div>
    <ActionLogNav />
    <p className="scr-meta">{t('history.accountingNote')}</p>
    <section className="card">
      <form className="history-filters" onSubmit={(e) => e.preventDefault()}>
        {['customer_uid', 'contract_uid', 'deferral_uid'].map((key) => <label key={key}>{t(`history.${key}`)}
          <input className="field" value={params.get(key) || ''} onChange={(e) => update(key, e.target.value)} />
        </label>)}
        <button className="btn btn--sm" type="button" onClick={() => setParams({})}>{t('history.clear')}</button>
      </form>
      {loading ? <p role="status" className="history-state">{t('common.loading')}</p>
        : problem ? <LoadError problem={problem} onRetry={retry} /> : data ? <>
          <DataTable caption={t('history.accounting')} minWidth={1000} rows={data.entries || []}
            getKey={(r) => r.uid} empty={t('history.accountingEmpty')} columns={[
              { key: 'customer', label: t('history.customer'), render: (r) => <><strong>{r.customer_name || r.customer_uid}</strong>
                <div className="scr-meta">{r.volt_id || r.customer_uid}</div></> },
              { key: 'contract_uid', label: t('deferral.contract'), render: (r) => <>{r.contract_uid}
                <div className="scr-meta">{r.deferral_uid}</div></> },
              { key: 'at', label: t('history.time'), render: (r) => thaiTime(r.at) },
              { key: 'by', label: t('history.actor'), render: (r) => r.by || r.actor || '—' },
              { key: 'status', label: t('deferral.accountingStatus'), render: (r) => t(`deferral.accounting.${r.status}`) },
              { key: 'note', label: t('deferral.reviewNote'), render: (r) => <div className="history-reason">{r.note || '—'}</div> },
              { key: 'documents', label: t('history.documents'), render: (r) => (r.document_refs || []).join(' · ') || '—' },
              { key: 'moves', label: t('deferral.cycles'), render: (r) => (r.moves || []).map((m) => <div key={m.n}>
                {t('deferral.cycle', { n: m.n })}: {date(m.old_due_date)} → {date(m.new_due_date)}</div>) },
              { key: 'open', label: t('history.customerCase'), render: (r) => <Link className="btn btn--sm"
                to={`/customers/${encodeURIComponent(r.customer_uid)}`}
                state={recordState(internalOrigin(location, 'history.accounting'))}>{t('history.customerCase')}</Link> },
            ]} />
          <div className="history-pagination">
            <button className="btn btn--sm" disabled={page <= 1} onClick={() => update('page', String(page - 1))}>{t('history.previous')}</button>
            <span>{t('history.page', { page, total: Math.max(1, Math.ceil(data.meta.total / (data.meta.page_size || 50))) })}</span>
            <button className="btn btn--sm" disabled={page * (data.meta.page_size || 50) >= data.meta.total}
              onClick={() => update('page', String(page + 1))}>{t('history.next')}</button>
          </div>
        </> : null}
    </section>
  </div>
}

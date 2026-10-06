import { useReloadOnEpoch } from '../lib/dataEpoch.jsx'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useCrumb } from '../lib/crumb.jsx'
import { downloadText } from '../lib/download.js'
import { ListPanel, Group, ListRow } from '../components/ListPanel.jsx'
import { PaymentPosition } from '../components/PaymentPosition.jsx'
import { RecordView } from '../components/RecordView.jsx'
import { ContactDrawer, contactSummary, openPromise } from '../components/ContactDrawer.jsx'
import { Drawer } from '../components/Drawer.jsx'
import { Problem, LoadError } from '../components/Problem.jsx'
import { useToast } from '../components/Toast.jsx'

const BAND_RANK = {
  CURRENT: 0, NONE: 0,
  UNDER_30: 1, EARLY_OVERDUE: 1,
  UNDER_60: 2, MID_OVERDUE: 2,
  UNDER_90: 3,
  OVER_90: 4, RISK_REVIEW: 4,
  COLLECTION_1_30: 1, COLLECTION_31_60: 2,
  COLLECTION_61_89: 3, COLLECTION_90_PLUS: 4,
  NPL_CONFIRMED: 5, NPL_RESOLVED: 5,
  CLOSED: 6,
}

const SORTS = [
  ['aggregate_overdue', 'book.sortArrears'],
  ['aggregate_outstanding', 'book.sortBalance'],
  ['oldest_dpd', 'book.sortDpd'],
  ['display_name', 'book.sortName'],
  ['next_action_on', 'book.sortNext'],
]

const PAGE_SIZE = 50

export function Book() {
  const { t, lang } = usePrefs()
  const toast = useToast()
  const navigate = useNavigate()
  useCrumb('group.mine', 'nav.book')

  const [params, setParams] = useSearchParams()
  const q = params.get('q') || ''
  const sort = params.get('sort') || 'aggregate_overdue'
  const dir = params.get('dir') || 'desc'
  const entity = params.get('entity') || ''
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState(null)
  const [closed, setClosed] = useState({})
  const [record, setRecord] = useState(null)
  const [recordProblem, setRecordProblem] = useState(null)
  const [contactFor, setContactFor] = useState(null)
  const [exportOpen, setExportOpen] = useState(false)
  const [exportReason, setExportReason] = useState('')
  const [exportProblem, setExportProblem] = useState(null)
  const [busy, setBusy] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const requestSeq = useRef(0)

  const query = useCallback(() => {
    // identities=1: this lens is the customer directory, so it also lists the
    // contract-less crm.lead rows the serving source holds (2026-09-19 ruling).
    // The queue, the KPIs and every money export stay contract-only.
    const p = { sort, dir, identities: 1 }
    if (q.trim()) p.q = q.trim()
    if (entity) p.entity = entity
    return p
  }, [q, sort, dir, entity])

  function updateFilter(key, value) {
    const next = new URLSearchParams(params)
    value ? next.set(key, value) : next.delete(key)
    next.delete('sel')
    next.delete('cursor')
    requestSeq.current += 1
    setRecord(null)
    setData(null)
    setLoadingMore(false)
    setParams(next, { replace: true })
  }

  const listQuery = useCallback(() => ({ ...query(), limit: PAGE_SIZE }), [query])

  const performFirstPage = useCallback((seq, request) => api.workbook(request)
    .then((next) => {
      if (requestSeq.current !== seq) return
      setData(next)
      setLoadingMore(false)
    })
    .catch((e) => {
      if (requestSeq.current !== seq) return
      setProblem(e?.problem || { code: 'request_failed' })
      setLoadingMore(false)
    }), [])

  const load = useCallback(() => {
    const seq = ++requestSeq.current
    setProblem(null)
    setData(null)
    setLoadingMore(false)
    return performFirstPage(seq, listQuery())
  }, [listQuery, performFirstPage])

  useEffect(() => {
    const seq = ++requestSeq.current
    setProblem(null)
    setData(null)
    setLoadingMore(false)
    const request = listQuery()
    const id = setTimeout(() => performFirstPage(seq, request), q ? 220 : 0)
    return () => clearTimeout(id)
  }, [listQuery, performFirstPage, q])
  useReloadOnEpoch(load)

  const loadMore = useCallback(() => {
    const cursor = data?.page?.next_cursor
    if (!cursor || loadingMore) return
    const seq = ++requestSeq.current
    setProblem(null)
    setLoadingMore(true)
    api.workbook({ ...listQuery(), cursor })
      .then((next) => {
        if (requestSeq.current !== seq) return
        setData((current) => ({
          ...next,
          rows: [...(current?.rows || []), ...(next?.rows || [])],
        }))
        setLoadingMore(false)
      })
      .catch((e) => {
        if (requestSeq.current !== seq) return
        if (e?.problem?.code === 'workbook_cursor_stale') {
          load()
          return
        }
        setProblem(e?.problem || { code: 'request_failed' })
        setLoadingMore(false)
      })
  }, [data?.page?.next_cursor, listQuery, load, loadingMore])

  const rows = data?.rows || []
  const selUid = params.get('sel')
  const sel = rows.find((r) => r.customer.uid === selUid) || rows[0]

  useEffect(() => {
    if (!sel) { setRecord(null); return undefined }
    let alive = true
    setRecord(null)
    setRecordProblem(null)
    api.caseDetail(sel.customer.uid)
      .then((d) => { if (alive) setRecord(d) })
      .catch((e) => { if (alive) setRecordProblem(e?.problem || { code: 'request_failed' }) })
    return () => { alive = false }
  }, [sel?.customer.uid])

  const grouped = useMemo(() => {
    const by = new Map()
    for (const r of rows) {
      const key = r.aging_bucket || 'NONE'
      if (!by.has(key)) by.set(key, { key, label: (lang === 'en' ? r.aging_bucket_label_en : r.aging_bucket_label_th) || key, rows: [] })
      by.get(key).rows.push(r)
    }
    return [...by.values()].sort((a, b) => (BAND_RANK[a.key] ?? 9) - (BAND_RANK[b.key] ?? 9))
  }, [rows, lang])

  function select(uid) {
    const next = new URLSearchParams(params)
    next.set('sel', uid)
    setParams(next, { replace: true })
  }

  async function plainExport() {
    try {
      const { text, filename } = await api.workbookExport(query())
      downloadText(filename, text)
      toast(t('book.exported'))
    } catch (e) {
      setExportProblem(e?.problem || { code: 'export_failed' })
      setExportOpen(true)
    }
  }

  async function governedExport() {
    setBusy(true)
    setExportProblem(null)
    try {
      const { text, filename } = await api.workbookExportGoverned({ reason: exportReason, ...query() })
      downloadText(filename, text)
      setExportOpen(false)
      toast(t('book.exported'))
    } catch (e) {
      setExportProblem(e?.problem || { code: 'export_failed' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      <div className="lensbar">
        <span className="lensbar__title">{t('nav.book')}</span>
        <span className="lensbar__meta num">{data?.meta?.total ?? '—'} {t('today.items')}</span>
        <span className="lensbar__meta">{data?.meta?.source_name || ''}</span>
        <span className="spacer" />
        <input className="field lensbar__search" placeholder={t('book.search')} aria-label={t('book.search')}
               value={q} onChange={(e) => updateFilter('q', e.target.value)} />
        <select className="field" aria-label={t('today.entity')} value={entity} onChange={(e) => updateFilter('entity', e.target.value)}>
          <option value="">{t('today.entityAll')}</option><option value="EPC">EPC</option><option value="SPV">SPV</option>
        </select>
        <select className="field" aria-label={t('book.sort')} value={sort} onChange={(e) => updateFilter('sort', e.target.value)} style={{ width: 170 }}>
          {SORTS.map(([id, key]) => <option key={id} value={id}>{t(key)}</option>)}
        </select>
        <button type="button" className="btn btn--sm" onClick={() => updateFilter('dir', dir === 'desc' ? 'asc' : 'desc')}>
          {dir === 'desc' ? t('book.desc') : t('book.asc')}
        </button>
        <button type="button" className="btn btn--sm" onClick={plainExport}>{t('book.exportCsv')}</button>
        <button type="button" className="btn btn--sm" onClick={() => { setExportProblem(null); setExportOpen(true) }}>{t('book.exportGoverned')}</button>
      </div>

      <div className="work work--split">
        <ListPanel
          title={t('nav.book')}
          count={data?.meta?.total}
          sub={t('book.sub', { source: data?.meta?.source_name || '—' })}
          note={[
            lang === 'en' ? data?.meta?.source_note_en : data?.meta?.source_note_th,
            lang === 'en' ? data?.meta?.identities_note_en : data?.meta?.identities_note_th,
          ].filter(Boolean).join(' · ') || t('book.note')}
        >
          {problem ? <div style={{ padding: 12 }}><LoadError problem={problem} onRetry={load} /></div> : null}
          {!problem && !data ? <p className="empty">{t('common.loading')}</p> : null}
          {grouped.map((g) => (
            <Group key={g.key} label={g.label} count={g.rows.length}
                   open={!closed[g.key]}
                   onToggle={() => setClosed((c) => ({ ...c, [g.key]: !c[g.key] }))}>
              {g.rows.map((r) => {
                const uid = r.customer.uid
                const hasIssue = Number(r.open_service_issues || 0) > 0
                return (
                  <ListRow
                    key={uid}
                    icon={hasIssue ? 'problem' : 'done'}
                    iconTitle={t(hasIssue ? 'today.issueOpen' : 'today.issueNone')}
                    name={r.customer.display_name}
                    sub={r.customer.volt_id || r.case?.volt_id || r.customer.customer_no}
                    current={sel?.customer.uid === uid}
                    onSelect={() => select(uid)}
                    chips={<PaymentPosition pp={r.payment_position} compact />}
                  />
                )
              })}
            </Group>
          ))}
          {data?.page?.has_more ? (
            <div style={{ padding: 12, textAlign: 'center' }}>
              <button type="button" className="btn btn--sm" disabled={loadingMore} onClick={loadMore}>
                {t(loadingMore ? 'book.loadingMore' : 'book.loadMore')}
              </button>
            </div>
          ) : null}
        </ListPanel>

        <RecordView
          data={record}
          problem={recordProblem}
          businessDate={data?.meta?.business_date}
          onRetry={() => sel && api.caseDetail(sel.customer.uid).then(setRecord).catch(() => {})}
          onChanged={() => { load(); if (sel) api.caseDetail(sel.customer.uid).then(setRecord).catch(() => {}) }}
          onLogContact={() => setContactFor(sel?.customer)}
        />
      </div>

      <ContactDrawer
        open={!!contactFor}
        onClose={() => setContactFor(null)}
        customer={contactFor}
        businessDate={data?.meta?.business_date}
        summary={contactSummary(record?.customer?.uid === contactFor?.uid ? record : null)}
        promise={openPromise(record?.customer?.uid === contactFor?.uid ? record : null)}
        onSaved={() => { load(); if (sel) api.caseDetail(sel.customer.uid).then(setRecord).catch(() => {}) }}
      />

      <Drawer
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        title={t('book.exportGoverned')}
        footer={(
          <>
            <button type="button" className="btn" onClick={() => setExportOpen(false)}>{t('common.cancel')}</button>
            <button type="button" className="btn btn--primary" disabled={busy || exportReason.trim().length < 8}
                    onClick={governedExport}>{t('book.exportRun')}</button>
          </>
        )}
      >
        <label>
          <span className="eyebrow">{t('book.exportReason')}<span className="req" aria-hidden="true">*</span></span>
          <textarea className="field" rows={3} value={exportReason} aria-required="true" onChange={(e) => setExportReason(e.target.value)} />
        </label>
        <p className="drawer__hint">{t('book.exportNote')}</p>
        {exportProblem ? <Problem problem={exportProblem} /> : null}
      </Drawer>
    </div>
  )
}

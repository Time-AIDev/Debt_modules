import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useIdentity, atLeast } from '../lib/identity.jsx'
import { useCrumb } from '../lib/crumb.jsx'
import { money, when } from '../lib/format.js'
import { ListPanel, Group, ListRow } from '../components/ListPanel.jsx'
import { PeakChip } from '../components/Chips.jsx'
import { StatusPill, NeutralChip } from '../components/StatusIcon.jsx'
import { peakDocStatus, statusOf } from '../lib/status.js'
import { Problem, LoadError } from '../components/Problem.jsx'
import { useToast } from '../components/Toast.jsx'
import { useReloadOnEpoch } from '../lib/dataEpoch.jsx'

const BAD = ['UNSENT', 'REJECTED']
const DRAFT = ['PENDING', 'DRAFT_CREATED']

/** เงินเข้าและ PEAK: draft-only documents, their gates, and the allocation lines. */
export function Payments() {
  const { t, lang } = usePrefs()
  const identity = useIdentity()
  const toast = useToast()
  useCrumb('group.review', 'nav.payments')

  const [params, setParams] = useSearchParams()
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState(null)
  const [closed, setClosed] = useState({})
  const [busy, setBusy] = useState(false)
  const [writeProblem, setWriteProblem] = useState(null)

  const load = useCallback(() => {
    setProblem(null)
    api.peakDocuments()
      .then(setData)
      .catch((e) => setProblem(e?.problem || { code: 'request_failed' }))
  }, [])
  useEffect(() => { load() }, [load])
  useReloadOnEpoch(load)

  const docs = data?.documents || []
  const meta = data?.meta || {}
  const selUid = params.get('sel')
  const sel = docs.find((d) => d.uid === selUid) || docs[0]

  const grouped = useMemo(() => ([
    { key: 'bad', label: t('payments.bad'), rows: docs.filter((d) => BAD.includes(d.state)), kind: peakDocStatus('REJECTED').kind },
    { key: 'draft', label: t('payments.draft'), rows: docs.filter((d) => DRAFT.includes(d.state)), kind: peakDocStatus('DRAFT_CREATED').kind },
    { key: 'approved', label: t('payments.approved'), rows: docs.filter((d) => d.state === 'APPROVED_IN_PEAK'), kind: peakDocStatus('APPROVED_IN_PEAK').kind },
  ].filter((g) => g.rows.length)), [docs, t])

  function select(uid) {
    const next = new URLSearchParams(params)
    next.set('sel', uid)
    setParams(next, { replace: true })
  }

  async function act(fn, okKey) {
    setBusy(true)
    setWriteProblem(null)
    try {
      await fn()
      toast(t(okKey))
      load()
    } catch (e) {
      setWriteProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  async function toggleStub() {
    setBusy(true)
    setWriteProblem(null)
    try {
      const next = await api.peakStub(!meta.stub)
      toast(next?.stub ? t('payments.stubOn') : t('payments.stubOff'))
      load()
    } catch (e) {
      setWriteProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  const counts = meta.counts || {}
  const allocation = meta.allocation || { lines: [] }
  // A served code in words (write mode, document intent); an unknown one shows the code itself.
  const words = (prefix, code) => (t(`${prefix}${code}`) === `${prefix}${code}` ? code : t(`${prefix}${code}`))
  const isOwner = identity.role === 'OWNER'

  return (
    <div className="work work--split">
      <ListPanel title={t('nav.payments')} count={docs.length} sub={t('payments.sub')} note={t('payments.note')}>
        <div className="panel__tools" style={{ padding: '8px 14px', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button type="button" className="btn btn--sm" disabled={busy}
                  onClick={() => act(() => api.peakRefreshAll(), 'payments.refreshed')}>
            {t('payments.refreshAll')}
          </button>
          <button type="button" className="btn btn--sm" disabled={busy || !isOwner} onClick={toggleStub}
                  title={isOwner ? undefined : t('payments.ownerOnly')}>
            {t(meta.stub ? 'payments.stubOff' : 'payments.stubOn')}
          </button>
          {isOwner ? null : <span className="scr-meta" style={{ flexBasis: '100%' }}>{t('payments.ownerOnly')}</span>}
        </div>
        {problem ? <div style={{ padding: 12 }}><LoadError problem={problem} onRetry={load} /></div> : null}
        {!problem && !data ? <p className="empty">{t('common.loading')}</p> : null}
        {data && docs.length === 0 ? <p className="empty">{t('payments.empty')}</p> : null}
        {grouped.map((g) => (
          <Group key={g.key} count={g.rows.length} open={!closed[g.key]}
                 icon={g.kind} label={g.label}
                 onToggle={() => setClosed((c) => ({ ...c, [g.key]: !c[g.key] }))}>
            {g.rows.map((d) => (
              <ListRow
                key={d.uid}
                name={d.customer_name || d.uid}
                sub={`${d.uid} · ${d.entity || ''} · ${d.intent ? words('payments.intent.', d.intent) : ''}`}
                score={d.risk_score}
                heatPct={0}
                current={sel?.uid === d.uid}
                onSelect={() => select(d.uid)}
                chips={<PeakChip state={d.state} />}
              />
            ))}
          </Group>
        ))}
      </ListPanel>

      <div className="stack">
        <section className="card">
          <header className="card__head">
            <h2>{t('nav.payments')}</h2>
            <span className="scr-meta">{counts.DRAFT_CREATED || 0} {t('payments.draftCount')} · {counts.REJECTED || 0} {t('payments.rejectedCount')}</span>
            <span className="spacer" />
            {meta.write_mode ? <NeutralChip title={meta.write_mode}>{words('payments.mode.', meta.write_mode)}</NeutralChip> : null}
          </header>
          <div className="card__body">
            <p className="scr-meta">{lang === 'en' ? meta.transport_note_en : meta.transport_note_th}</p>
          </div>
        </section>

        {sel ? (
          <>
            <section className="card">
              <div className="scr-head">
                <div className="scr-head__id">
                  <div className="scr-head__chips">
                    <span className="eyebrow">{t('payments.kind')}</span>
                    <PeakChip state={sel.state} />
                    {sel.waiting_days ? <NeutralChip>{t('payments.waiting', { n: sel.waiting_days })}</NeutralChip> : null}
                  </div>
                  <h1>{sel.customer_name || sel.uid}</h1>
                  <p className="scr-meta">{[sel.uid, sel.entity, sel.company_id, sel.peak_number].filter(Boolean).join(' · ')}</p>
                </div>
                <div className="scr-head__act">
                  <span className="scr-meta">{lang === 'en' ? sel.state_need_en : sel.state_need_th}</span>
                  <div className="scr-head__buttons">
                    <button type="button" className="btn btn--sm" disabled={busy}
                            onClick={() => act(() => api.peakResend(sel.uid, {}), 'payments.resent')}>
                      {t('payments.resend')}
                    </button>
                    <button type="button" className="btn btn--sm" disabled={busy}
                            onClick={() => act(() => api.peakRefresh(sel.uid, {}), 'payments.refreshed')}>
                      {t('payments.refresh')}
                    </button>
                    {sel.state === 'REJECTED' ? (
                      <button type="button" className="btn btn--sm btn--primary" disabled={busy || !atLeast('MANAGER')}
                              title={atLeast('MANAGER') ? undefined : t('payments.managerOnly')}
                              onClick={() => act(() => api.peakResubmit(sel.uid, {}), 'payments.resubmitted')}>
                        {t('payments.resubmit')}
                      </button>
                    ) : null}
                  </div>
                  {sel.state === 'REJECTED' && !atLeast('MANAGER') ? <span className="scr-meta">{t('payments.managerOnly')}</span> : null}
                </div>
              </div>
              {sel.rejection_reason ? <p className="card__note">{t('payments.rejectedBecause')} · {sel.rejection_reason}</p> : null}
              {sel.state_read_at ? <p className="card__note">{t('payments.lastRead')} · {when(sel.state_read_at)}</p> : null}
            </section>
            {writeProblem ? <Problem problem={writeProblem} /> : null}
            {sel.allocation?.lines?.length ? (
              <section className="card">
                <header className="card__head"><h2>{t('payments.allocation')}</h2></header>
                <div className="card__body">
                  <ul className="rows">
                    {sel.allocation.lines.map((line) => (
                      <li key={line.state} className="rows__row">
                        <StatusPill kind={statusOf('allocation', line.state).kind}>{lang === 'en' ? line.label_en : line.label_th}</StatusPill>
                        <span className="spacer" />
                        <span className="num">{line.amount ? money(line.amount) : '—'}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <p className="card__note">{t('payments.allocNote')}</p>
              </section>
            ) : null}
          </>
        ) : null}

        <section className="card">
          <header className="card__head"><h2>{t('payments.allocation')}</h2></header>
          <div className="card__body">
            <ul className="rows">
              {(allocation.lines || []).map((line) => (
                <li key={line.state} className="rows__row">
                  <StatusPill kind={statusOf('allocation', line.state).kind}>{lang === 'en' ? line.label_en : line.label_th}</StatusPill>
                  <span className="spacer" />
                  <span className="num">{line.count ?? 0}</span>
                  <span className="num">{line.amount ? money(line.amount) : '—'}</span>
                </li>
              ))}
            </ul>
          </div>
          <p className="card__note">{t('payments.allocNote')} · {t('payments.noApprove')}</p>
        </section>
      </div>
    </div>
  )
}

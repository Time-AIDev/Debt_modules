import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useSearchParams, useNavigate } from 'react-router-dom'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useIdentity, atLeast } from '../lib/identity.jsx'
import { useCrumb } from '../lib/crumb.jsx'
import { money, when } from '../lib/format.js'
import { ListPanel, Group, ListRow } from '../components/ListPanel.jsx'
import { Drawer } from '../components/Drawer.jsx'
import { Problem, LoadError } from '../components/Problem.jsx'
import { StatusPill, NeutralChip } from '../components/StatusIcon.jsx'
import { reviewStatus, statusOf } from '../lib/status.js'
import { useToast } from '../components/Toast.jsx'
import { internalOrigin, recordState } from '../lib/origin.js'

/**
 * รอตรวจ: the manager's queue. The decisions offered are the row's own served
 * `decisions` (falling back to meta.decisions) — never a client list. An
 * NPL_TYPE_SET decision additionally needs the served NPL type.
 */
export function Reviews() {
  const { t, lang } = usePrefs()
  const identity = useIdentity()
  const toast = useToast()
  const navigate = useNavigate()
  const location = useLocation()
  useCrumb('group.review', 'nav.reviews')

  const [params, setParams] = useSearchParams()
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState(null)
  const [closed, setClosed] = useState({})
  const [decideOpen, setDecideOpen] = useState(false)
  const [decision, setDecision] = useState('')
  const [comment, setComment] = useState('')
  const [nplType, setNplType] = useState('')
  const [busy, setBusy] = useState(false)
  const [answerProblem, setAnswerProblem] = useState(null)

  const load = useCallback(() => {
    setProblem(null)
    api.reviews()
      .then(setData)
      .catch((e) => setProblem(e?.problem || { code: 'request_failed' }))
  }, [])
  useEffect(() => { load() }, [load])

  const rows = data?.reviews || []
  const meta = data?.meta || {}
  const selUid = params.get('sel')
  const sel = rows.find((r) => r.uid === selUid) || rows[0]

  const grouped = useMemo(() => {
    const old = rows.filter((r) => r.sla_breached)
    const fresh = rows.filter((r) => !r.sla_breached)
    return [
      { key: 'old', label: t('reviews.old', { hours: meta.sla_hours ?? '—' }), rows: old, kind: statusOf('reviewSla', 'BREACHED').kind },
      { key: 'new', label: t('reviews.new'), rows: fresh, kind: reviewStatus('OPEN').kind },
    ].filter((g) => g.rows.length > 0)
  }, [rows, meta, t])

  function select(uid) {
    const next = new URLSearchParams(params)
    next.set('sel', uid)
    setParams(next, { replace: true })
  }

  function openDecide() {
    const first = (sel?.decisions || meta.decisions || [])[0]
    setDecision(first?.code || '')
    setComment('')
    setNplType((meta.npl_types || [])[0]?.code || '')
    setAnswerProblem(null)
    setDecideOpen(true)
  }

  async function submit() {
    setBusy(true)
    setAnswerProblem(null)
    try {
      await api.answerReview(sel.uid, {
        decision,
        comment,
        ...(decision === 'NPL_TYPE_SET' ? { npl_type: nplType } : {}),
      })
      toast(t('reviews.answered'))
      setDecideOpen(false)
      load()
    } catch (e) {
      setAnswerProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  const slaOf = (breached) => statusOf('reviewSla', breached ? 'BREACHED' : 'WITHIN')
  const canDecide = atLeast('SUPERVISOR')
  const options = sel?.decisions || meta.decisions || []
  // An answered review names its decision in words (the served option's label), never the raw code.
  const decidedOption = options.find((o) => o.code === sel?.decision)
  const decided = decidedOption ? (lang === 'en' ? decidedOption.label_en : decidedOption.label_th) : sel?.decision
  const nplOptions = meta.npl_types || []

  return (
    <>
      <div className="work work--split">
        <ListPanel title={t('nav.reviews')} count={meta.open ?? rows.length} sub={t('reviews.sub')} note={t('reviews.note')}>
          {problem ? <div style={{ padding: 12 }}><LoadError problem={problem} onRetry={load} /></div> : null}
          {!problem && !data ? <p className="empty">{t('common.loading')}</p> : null}
          {grouped.map((g) => (
            <Group key={g.key} count={g.rows.length} open={!closed[g.key]}
                   icon={g.kind} label={g.label}
                   onToggle={() => setClosed((c) => ({ ...c, [g.key]: !c[g.key] }))}>
              {g.rows.map((r) => (
                <ListRow
                  key={r.uid}
                  name={r.display_name}
                  sub={`${r.uid} · ${lang === 'en' ? r.reason_label_en : r.reason_label}`}
                  arrears={money(r.aggregate_overdue)}
                  dpd={r.oldest_dpd}
                  dpdLabel={r.oldest_dpd === null ? t('today.dpdNone') : `DPD ${r.oldest_dpd}`}
                  score={r.risk_score}
                  heatPct={Math.min(100, Math.round(((r.oldest_dpd || 0) / 120) * 100))}
                  current={sel?.uid === r.uid}
                  onSelect={() => select(r.uid)}
                  chips={r.sla_breached ? <StatusPill kind={slaOf(true).kind}>{t(slaOf(true).key)}</StatusPill> : null}
                />
              ))}
            </Group>
          ))}
        </ListPanel>

        <div className="stack">
          {sel ? (
            <>
              <section className="card">
                <div className="scr-head">
                  <div className="scr-head__id">
                    <div className="scr-head__chips">
                      <span className="eyebrow">{t('reviews.kind')}</span>
                      <NeutralChip>{lang === 'en' ? sel.reason_label_en : sel.reason_label}</NeutralChip>
                      <StatusPill kind={slaOf(sel.sla_breached).kind}>{t(slaOf(sel.sla_breached).key)}</StatusPill>
                    </div>
                    <h1>{sel.question_th ? (lang === 'en' ? sel.question_en : sel.question_th) : sel.question}</h1>
                    <p className="scr-meta">{sel.display_name} · {sel.uid} · {when(sel.raised_at_time || sel.raised_at)}</p>
                  </div>
                  <div className="scr-head__act">
                    <span className="scr-meta">{lang === 'en' ? sel.need_en : sel.need_th}</span>
                    {sel.status === 'OPEN' ? (
                      <>
                        <button type="button" className="btn btn--primary" disabled={!canDecide} onClick={openDecide}
                                title={canDecide ? undefined : t('reviews.managerOnly')}>
                          {t('reviews.answer')}
                        </button>
                        {canDecide ? null : <span className="scr-meta">{t('reviews.managerOnly')}</span>}
                      </>
                    ) : (
                      <StatusPill kind={reviewStatus(sel.status).kind} title={sel.decision || undefined}>
                        {t(reviewStatus(sel.status).key)}{decided ? ` · ${decided}` : ''}
                      </StatusPill>
                    )}
                  </div>
                </div>
                {sel.status !== 'OPEN' ? (
                  <p className="card__note">{t('reviews.onRecord')} · {sel.comment || '—'} · {sel.answered_by || '—'}</p>
                ) : null}
              </section>

              <div className="grid2b">
                <section className="card">
                  <header className="card__head"><h2>{t('reviews.evidence')}</h2></header>
                  <div className="card__body">
                    <p className="scr-meta">{lang === 'en' ? sel.evidence?.note_en : sel.evidence?.note_th}</p>
                    <dl className="kv" style={{ marginTop: 10 }}>
                      <dt>{t('record.ptp')}</dt>
                      <dd>{t('reviews.ptpLine', { kept: sel.evidence?.kept_ptp_count ?? 0, broken: sel.evidence?.broken_ptp_count ?? 0 })}</dd>
                      <dt>{t('record.recent')}</dt>
                      <dd>{(sel.evidence?.last_contacts || []).length ? `${(sel.evidence.last_contacts || []).length}` : t('record.noContact')}</dd>
                    </dl>
                  </div>
                  <p className="card__note">{t('reviews.evidenceNote')}</p>
                </section>
                <section className="card">
                  <header className="card__head"><h2>{t('reviews.related')}</h2></header>
                  <div className="card__body">
                    <p className="scr-value">{sel.display_name}</p>
                    <p className="scr-meta">{sel.customer_uid}</p>
                    <dl className="kv" style={{ marginTop: 10 }}>
                      <dt>{t('record.arrears')}</dt><dd className="num">{money(sel.aggregate_overdue)}</dd>
                      <dt>{t('record.age')}</dt><dd>{sel.oldest_dpd === null ? t('today.dpdNone') : `DPD ${sel.oldest_dpd}`}</dd>
                      <dt>{t('record.riskScore')}</dt><dd className="num">{sel.risk_score ?? '—'}</dd>
                    </dl>
                    <button type="button" className="btn" style={{ marginTop: 12 }}
                            onClick={() => navigate(`/customers/${sel.customer_uid}`, {
                              state: recordState(internalOrigin(location, 'nav.reviews')),
                            })}>
                      {t('reviews.openCase')}
                    </button>
                  </div>
                </section>
              </div>
            </>
          ) : <p className="empty">{t('reviews.empty')}</p>}
        </div>
      </div>

      <Drawer
        open={decideOpen}
        onClose={() => setDecideOpen(false)}
        title={t('reviews.answerTitle')}
        subtitle={sel?.display_name}
        footer={(
          <>
            <button type="button" className="btn" onClick={() => setDecideOpen(false)}>{t('common.cancel')}</button>
            <button type="button" className="btn btn--primary"
                    disabled={busy || !decision || (decision === 'NPL_TYPE_SET' && !nplType)} onClick={submit}>
              {t('reviews.confirmAnswer')}
            </button>
          </>
        )}
      >
        <label>
          <span className="eyebrow">{t('reviews.decision')}<span className="req" aria-hidden="true">*</span></span>
          <select className="field" value={decision} aria-required="true" onChange={(e) => setDecision(e.target.value)}>
            {options.map((o) => (
              <option key={o.code} value={o.code}>{lang === 'en' ? o.label_en : o.label_th}</option>
            ))}
          </select>
        </label>
        {decision === 'NPL_TYPE_SET' ? (
          <label>
            <span className="eyebrow">{t('reviews.nplType')}<span className="req" aria-hidden="true">*</span></span>
            <select className="field" value={nplType} aria-required="true" onChange={(e) => setNplType(e.target.value)}>
              {nplOptions.map((o) => (
                <option key={o.code} value={o.code}>{lang === 'en' ? o.label_en : o.label_th}</option>
              ))}
            </select>
          </label>
        ) : null}
        <label>
          <span className="eyebrow">{t('reviews.comment')}</span>
          <textarea className="field" rows={4} value={comment} onChange={(e) => setComment(e.target.value)} />
        </label>
        {answerProblem ? <Problem problem={answerProblem} /> : null}
        <p className="drawer__hint">{t('reviews.returns')}</p>
      </Drawer>
    </>
  )
}

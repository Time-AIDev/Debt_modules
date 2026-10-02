import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useCrumb } from '../lib/crumb.jsx'
import { money, date as fmtDate } from '../lib/format.js'
import { ListPanel, Group, ListRow } from '../components/ListPanel.jsx'
import { LoadError } from '../components/Problem.jsx'
import { StatusPill } from '../components/StatusIcon.jsx'
import { preinstallStatus, preinstallProgress, preinstallReleased } from '../lib/status.js'
import { PreInstallCard } from '../components/PreInstallCard.jsx'
import { useReloadOnEpoch } from '../lib/dataEpoch.jsx'
import { DataFreshness } from '../components/DataFreshness.jsx'

const passed = (item) => (item.conditions || []).every((c) => c.passed)
const passedCount = (item) => (item.conditions || []).filter((c) => c.passed).length

/** ใบแจ้งหนี้ก่อนติดตั้ง: the book of cards; the card itself is shared with the case. */
export function Pipeline() {
  const { t } = usePrefs()
  // "ผ่าน n จาก m" as the pre-install progress pill (the pie by share passed, all passed → done).
  const progress = (item) => {
    const vars = { done: passedCount(item), total: (item.conditions || []).length }
    const s = preinstallProgress(vars.done, vars.total)
    return <StatusPill kind={s.kind}>{t(s.key, vars)}</StatusPill>
  }
  useCrumb('group.review', 'nav.pipeline')

  const [params, setParams] = useSearchParams()
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState(null)
  const [closed, setClosed] = useState({})

  const load = useCallback(() => {
    setProblem(null)
    api.pipeline()
      .then(setData)
      .catch((e) => setProblem(e?.problem || { code: 'request_failed' }))
  }, [])
  useEffect(() => { load() }, [load])
  useReloadOnEpoch(load)

  const items = data?.items || []
  const meta = data?.meta || {}
  const selUid = params.get('sel')
  const sel = items.find((i) => i.uid === selUid) || items[0]

  const grouped = useMemo(() => {
    const ready = items.filter((i) => passed(i) && !i.released_at)
    const blocked = items.filter((i) => !passed(i) || i.released_at)
    return [
      { key: 'blocked', label: t('pipeline.blocked'), rows: blocked, kind: preinstallStatus('OPEN').kind },
      { key: 'ready', label: t('pipeline.ready'), rows: ready, kind: preinstallStatus('PASSED').kind },
    ].filter((g) => g.rows.length)
  }, [items, t])

  function select(uid) {
    const next = new URLSearchParams(params)
    next.set('sel', uid)
    setParams(next, { replace: true })
  }

  return (
    <>
      <DataFreshness />
    <div className="work work--split">
      <ListPanel title={t('nav.pipeline')} count={meta.total ?? items.length} sub={t('pipeline.sub')} note={t('pipeline.note')}>
        {problem ? <div style={{ padding: 12 }}><LoadError problem={problem} onRetry={load} /></div> : null}
        {!problem && !data ? <p className="empty">{t('common.loading')}</p> : null}
        {grouped.map((g) => (
          <Group key={g.key} count={g.rows.length} open={!closed[g.key]}
                 icon={g.kind} label={g.label}
                 onToggle={() => setClosed((c) => ({ ...c, [g.key]: !c[g.key] }))}>
            {g.rows.map((i) => (
              <ListRow
                key={i.uid}
                name={i.display_name}
                sub={[i.uid, i.entity, i.customer_no].filter(Boolean).join(' · ')}
                arrears={money(i.amount_due)}
                dpd={i.case_dpd}
                dpdLabel={i.case_dpd === null || i.case_dpd === undefined ? t('today.dpdNone') : `DPD ${i.case_dpd}`}
                score={i.risk_score}
                heatPct={Math.min(100, Math.round(((i.case_dpd || 0) / 120) * 100))}
                current={sel?.uid === i.uid}
                onSelect={() => select(i.uid)}
                chips={progress(i)}
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
                    <span className="eyebrow">{t('pipeline.kind')}</span>
                    {progress(sel)}
                    {sel.released_at ? (
                      <StatusPill kind={preinstallReleased().kind}>{t(preinstallReleased().key, { date: fmtDate(sel.released_at) })}</StatusPill>
                    ) : null}
                  </div>
                  <h1>{sel.display_name}</h1>
                  <p className="scr-meta">{[sel.uid, sel.customer_no, sel.entity].filter(Boolean).join(' · ')}</p>
                </div>
                <div className="scr-head__act">
                  <span className="scr-meta">
                    {t('pipeline.installOn')} · {fmtDate(sel.actual_install_on || sel.confirmed_install_on) || '—'}
                  </span>
                  <span className="scr-value">{money(sel.amount_due)}</span>
                </div>
              </div>
            </section>

            <PreInstallCard item={sel} meta={meta} onChanged={load} />
          </>
        ) : <p className="empty">{t('pipeline.empty')}</p>}
      </div>
    </div>
    </>
  )
}

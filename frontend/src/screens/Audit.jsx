import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useCrumb } from '../lib/crumb.jsx'
import { when } from '../lib/format.js'
import { DataTable } from '../components/DataTable.jsx'
import { StatusPill, NeutralChip } from '../components/StatusIcon.jsx'
import { auditStatus } from '../lib/status.js'
import { LoadError } from '../components/Problem.jsx'

function signingText(source, lang) {
  if (!source) return '—'
  if (typeof source === 'string') return source
  return (lang === 'en' ? source.value_en || source.note_en : source.value_th || source.note_th) || '—'
}

/** บันทึกการใช้งาน: every act, signed, with its own hash chain. */
export function Audit() {
  const { t, lang } = usePrefs()
  useCrumb('group.system', 'nav.audit')

  const [data, setData] = useState(null)
  const [problem, setProblem] = useState(null)
  const [actor, setActor] = useState('')
  const [act, setAct] = useState('')
  const [entries, setEntries] = useState([])
  const [verify, setVerify] = useState(null)

  const load = useCallback((params, append) => {
    setProblem(null)
    api.audit(params)
      .then((d) => {
        setData(d)
        setEntries((prev) => (append ? [...prev, ...d.entries] : d.entries))
      })
      .catch((e) => setProblem(e?.problem || { code: 'request_failed' }))
  }, [])

  useEffect(() => { load({}) }, [load])

  function applyFilters(nextActor, nextAct) {
    setActor(nextActor); setAct(nextAct)
    const params = {}
    if (nextActor) params.actor = nextActor
    if (nextAct) params.act = nextAct
    load(params)
  }

  return (
    <div className="stack">
      <div className="lensbar">
        <span className="lensbar__title">{t('nav.audit')}</span>
        <span className="lensbar__meta num">{data?.meta?.count ?? entries.length}</span>
        <span className="spacer" />
        <button type="button" className="btn btn--sm" onClick={() => api.auditVerify().then(setVerify).catch(() => setVerify({ ok: false }))}>
          {t('audit.verify')}
        </button>
      </div>
      {problem ? <LoadError problem={problem} onRetry={() => load({})} /> : null}
      {verify ? (
        <span>
          <StatusPill kind={auditStatus(verify.ok || verify.valid ? 'OK' : 'REFUSED').kind}>
            {verify.ok || verify.valid ? t('audit.chainOk') : t('audit.chainBad')}
          </StatusPill>
        </span>
      ) : null}

      <section className="card">
        <div className="panel__tools" style={{ padding: '10px 16px', display: 'flex', gap: 8, flexWrap: 'wrap', borderBottom: '1px solid var(--line-default)' }}>
          <select className="field" aria-label={t('audit.actor')} value={actor} style={{ width: 200 }}
                  onChange={(e) => applyFilters(e.target.value, act)}>
            <option value="">{t('audit.actorAll')}</option>
            {(data?.meta?.actors || []).map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
          <select className="field" aria-label={t('audit.act')} value={act} style={{ width: 240 }}
                  onChange={(e) => applyFilters(actor, e.target.value)}>
            <option value="">{t('audit.actAll')}</option>
            {(data?.meta?.acts || []).map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
          <span className="spacer" />
          <span className="scr-meta">
            {t('audit.signing')} {signingText(data?.meta?.signing_source, lang)}
          </span>
        </div>
        <DataTable
          caption={t('nav.audit')}
          minWidth={900}
          getKey={(r) => r.seq}
          rows={entries}
          empty={t('audit.empty')}
          columns={[
            { key: 'at', label: t('audit.time'), render: (r) => <span className="num">{when(r.at)}</span> },
            { key: 'actor', label: t('audit.actor'), render: (r) => (
              <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                <span style={{ fontWeight: 500 }}>{r.actor_claimed || '—'}</span>
                {r.actor_source ? <NeutralChip>{r.actor_source}</NeutralChip> : null}
              </span>
            ) },
            { key: 'act', label: t('audit.act'), render: (r) => r.act || `${r.verb} ${r.route_template}` },
            { key: 'target', label: t('audit.target'), render: (r) => <span className="scr-meta">{r.subject_uid || r.subject_type || '—'}</span> },
            { key: 'result', label: t('audit.result'), render: (r) => {
              const s = auditStatus(r.outcome)
              return (
                <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                  <StatusPill kind={s.kind} title={r.outcome}>{t(s.key)}</StatusPill>
                  {r.error_code ? <span className="scr-meta">{r.error_code}</span> : null}
                </span>
              )
            } },
          ]}
        />
        <div style={{ padding: '11px 16px', display: 'flex', gap: 10, alignItems: 'center' }}>
          {data?.meta?.next_before_seq ? (
            <button type="button" className="btn btn--sm"
                    onClick={() => load({ ...(actor ? { actor } : {}), ...(act ? { act } : {}), before_seq: data.meta.next_before_seq }, true)}>
              {t('audit.loadOlder')}
            </button>
          ) : null}
          <span className="scr-meta">{t('audit.note')}</span>
        </div>
      </section>
    </div>
  )
}

import { Fragment, useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { money, int, pct } from '../lib/format.js'
import { Problem } from './Problem.jsx'

/**
 * F09 / ruling Q4 (feedback-r2 TASK-009): the assigned officer's own scoreboard on
 * the case overview. Every row is one served figure from GET /v1/reports/officers/{uid}
 * — the same computation `/v1/reports/team` serves — and the note below the rows is
 * the server's own sentence, never one the client writes.
 */
export function OfficerScoreboard({ officerUid }) {
  const { t, lang } = usePrefs()
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState(null)

  useEffect(() => {
    if (!officerUid) {
      setData(null)
      setProblem(null)
      return undefined
    }
    let alive = true
    setData(null)
    setProblem(null)
    api.reportsOfficer(officerUid)
      .then((body) => { if (alive) setData(body) })
      .catch((e) => { if (alive) setProblem(e?.problem || { code: 'request_failed' }) })
    return () => { alive = false }
  }, [officerUid])

  const heading = t('record.officerProgress', { name: data?.officer?.display_name || officerUid || '—' })

  if (!officerUid) {
    return (
      <section className="card">
        <header className="card__head"><h2>{t('record.officerProgress', { name: '—' })}</h2></header>
        <div className="card__body"><p className="case__empty">{t('record.noOfficer')}</p></div>
      </section>
    )
  }
  if (problem) {
    return (
      <section className="card">
        <header className="card__head"><h2>{heading}</h2></header>
        <div className="card__body"><Problem problem={problem} /></div>
      </section>
    )
  }
  if (!data) {
    return (
      <section className="card">
        <header className="card__head"><h2>{heading}</h2></header>
        <div className="card__body"><p className="case__empty">{t('common.loading')}</p></div>
      </section>
    )
  }

  const o = data.officer || {}
  const rows = [
    [t('record.officerQueue'), `${o.queue_done ?? 0} / ${o.queue_today ?? 0}`],
    [t('record.officerCases'), int(o.cases)],
    [t('record.officerArrears'), money(o.arrears)],
    [t('record.officerContactRate'), pct(o.contact_rate)],
    [t('record.officerPtpRate'), pct(o.ptp_kept_rate)],
    [t('record.officerReceipts'), money(o.receipts_month)],
  ]
  return (
    <section className="card">
      <header className="card__head"><h2>{heading}</h2></header>
      <div className="card__body">
        <dl className="case__kv">
          {rows.map(([label, value]) => (
            <Fragment key={label}>
              <dt>{label}</dt>
              <dd className="num">{value}</dd>
            </Fragment>
          ))}
        </dl>
        {/* The served sentence states what the rates are counted from — data, kept. */}
        <p className="case__rowNote case__scoreNote">{lang === 'en' ? data.note_en : data.note_th}</p>
      </div>
    </section>
  )
}

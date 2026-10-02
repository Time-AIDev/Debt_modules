import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useIdentity, atLeast } from '../lib/identity.jsx'
import { useCrumb } from '../lib/crumb.jsx'
import { Icon } from '../components/Icon.jsx'
import { LoadError } from '../components/Problem.jsx'
import { CaseSheet } from '../components/CaseSheet.jsx'
import { NplCases, caseModels } from '../components/npl/NplCases.jsx'
import { Recoveries, RecoveryBoard, Lots, Service } from '../components/npl/RecoveryTabs.jsx'
import { NplMoveDrawer, useAct, word } from '../components/npl/parts.jsx'

const TABS = [
  ['npl', 'recovery.nplTab'],
  ['recovery', 'recovery.recoveryTab'],
  ['board', 'recovery.boardTab'],
  ['lots', 'recovery.lotsTab'],
  ['service', 'recovery.serviceTab'],
]

/**
 * NPL และการเรียกคืน — design E (final design, spec-npl.md): a lens bar with the rules
 * folded into "เกณฑ์และที่มา", five real tabs, one-line glyph lists that open in place,
 * the path kanban as a second view, the customer case as a pop-up sheet.
 */
export function Recovery() {
  const { t, served } = usePrefs()
  const identity = useIdentity()
  useCrumb('group.review', 'nav.recovery')

  const [tab, setTab] = useState('npl')
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState(null)
  const [criteria, setCriteria] = useState(false)
  const [caseUid, setCaseUid] = useState(null)
  const [caseLog, setCaseLog] = useState(false)
  const [move, setMove] = useState(null)

  const load = useCallback(() => {
    setProblem(null)
    Promise.all([
      api.nplCases(), api.recoveryCases(), api.lots(), api.recoveryBoard(), api.serviceBilling(),
    ]).then(([npl, recs, lots, board, service]) => setData({
      npl, recs: recs?.recovery_cases || [], lots: lots?.lots || [], board, service,
    })).catch((e) => setProblem(e?.problem || { code: 'request_failed' }))
  }, [])
  useEffect(() => { load() }, [load])
  const moveAct = useAct(load)

  const rows = data?.npl?.npl_cases || []
  const strategies = data?.npl?.meta?.strategies || []
  const recs = data?.recs || []
  const models = caseModels(rows, recs)
  const count = (state) => models.filter((m) => m.state === state).length
  const pathLabel = (code) => served(strategies.find((s) => s.strategy === code), 'label') || code || '—'
  const stageLabel = (stage) => word(t, `board.col.recovery.${stage}`, stage)
  const nameOf = (sourceRef) => rows.find((r) => r.uid === sourceRef)?.display_name || '—'
  const counts = {
    npl: rows.length,
    recovery: recs.length,
    board: (data?.board?.columns || []).reduce((n, c) => n + (c.cards || []).length, 0),
    lots: (data?.lots || []).length,
    service: (data?.service?.accounts || []).length,
  }
  const summary = [
    t('recovery.nCases', { n: data?.npl?.meta?.badge ?? rows.length }),
    `${t('recovery.undecided')} ${count('undecided')}`,
    `${t('recovery.inflight')} ${count('active')}`,
    count('closed') ? `${t('recovery.closedGroup')} ${count('closed')}` : null,
  ].filter(Boolean).join(' · ')

  const openCase = (uid) => { if (uid) { setCaseUid(uid); setCaseLog(false) } }
  // "บันทึกผลการติดต่อ" opens the case pop-up with its contact drawer on top (spec-npl §8).
  const openLog = (uid) => { if (uid) { setCaseUid(uid); setCaseLog(true) } }
  const startMove = (next) => { moveAct.setProblem(null); setMove(next) }
  const by = identity.officer || undefined
  const mgr = atLeast('MANAGER')

  // One drawer for both boards: the path (F08, MANAGER+) or the recovery stage.
  let drawer = null
  if (move?.kind === 'path') {
    const m = move.model
    drawer = {
      title: t('recovery.changePath'),
      subtitle: m.row.display_name,
      notes: [t('recovery.pathMoveNote')],
      currentId: m.state === 'active' ? m.strategy : null,
      currentTitle: t('recovery.currentPath'),
      options: strategies.map((s) => {
        const off = s.available === false
        const decision = s.pending_decision || '—'
        return {
          id: s.strategy, label: served(s, 'label'), off, disabled: off || !mgr,
          title: off ? t('recovery.unavailable', { decision }) : mgr ? undefined : t('recovery.managerOnly'),
          note: off ? t('recovery.waitDecision', { decision }) : undefined,
        }
      }),
      problem: moveAct.problem || (mgr ? null : { code: 'forbidden', message_th: t('recovery.pathManagerOnly'), message_en: t('recovery.pathManagerOnly') }),
      onPick: async (to, reason) => {
        const ok = m.state === 'active'
          ? await moveAct.run(() => api.changeRecoveryStrategy(m.rec.uid, { strategy: to, reason, by, role: identity.role }),
            t('recovery.pathChanged'))
          : await moveAct.run(() => api.openRecovery(m.row.uid, { strategy: to, reason, by, role: identity.role }),
            t('recovery.pathOpened', { path: pathLabel(to) }))
        if (ok) setMove(null)
      },
    }
  } else if (move?.kind === 'stage') {
    drawer = {
      title: t('recovery.moveStage'),
      subtitle: move.card.display_name,
      notes: [t('recovery.boardNote'), t('recovery.moveNote')],
      currentId: move.stage,
      currentTitle: t('recovery.currentStage'),
      options: (data?.board?.columns || []).map((c) => ({ id: c.stage, label: stageLabel(c.stage) })),
      problem: moveAct.problem,
      onPick: async (to, reason) => {
        const ok = await moveAct.run(() => api.recoveryBoardMove({ customer_uid: move.card.customer_uid, to_stage: to, reason, by }),
          t('recovery.moved'))
        if (ok) setMove(null)
      },
    }
  }

  const criteriaLines = [
    t('recovery.sub'),
    t('recovery.note', { decision: rows.find((r) => r.pending_decision)?.pending_decision || '—' }),
    t('recovery.pathHint', { rate: strategies.find((s) => s.rate_pct)?.rate_pct ?? '—' }),
    t('recovery.pathNote'),
    served(data?.npl?.meta, 'note'),
  ].filter(Boolean)

  return (
    <div className="npl">
      <div className="npl__lens">
        <h1 className="npl__title">{t('nav.recovery')}</h1>
        {data ? <span className="npl__summary num">{summary}</span> : null}
        <span className="spacer" />
        <button type="button" className="btn btn--quiet npl__crit" aria-expanded={criteria} onClick={() => setCriteria((v) => !v)}>
          <Icon name="info" />{t('recovery.criteria')}<Icon name="down" className="npl__critCaret" />
        </button>
      </div>
      {criteria ? (
        <ul className="npl__criteria" aria-label={t('recovery.criteria')}>
          {criteriaLines.map((line) => <li key={line}>{line}</li>)}
        </ul>
      ) : null}
      {problem ? <LoadError problem={problem} onRetry={load} /> : null}

      <div className="tabs npl__tabs" role="tablist" aria-label={t('recovery.tabs')}>
        {TABS.map(([id, key]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id}
                  className={`tabs__tab${tab === id ? ' tabs__tab--on' : ''}`} onClick={() => setTab(id)}>
            {t(key)}{data ? <span className="tabs__count num">{counts[id]}</span> : null}
          </button>
        ))}
      </div>

      <div className="npl__body" role="tabpanel" aria-label={t(TABS.find(([id]) => id === tab)[1])}>
        {!data && !problem ? <p className="empty">{t('common.loading')}</p> : null}
        {data && tab === 'npl' ? (
          <NplCases models={models} strategies={strategies} label={pathLabel} reload={load} onCase={openCase} onLog={openLog}
                    onMove={(model) => startMove({ kind: 'path', model })} />
        ) : null}
        {data && tab === 'recovery' ? <Recoveries recs={recs} nameOf={nameOf} label={pathLabel} reload={load} /> : null}
        {data && tab === 'board' ? (
          <RecoveryBoard board={data.board} stageLabel={stageLabel} onCase={openCase} onLog={openLog}
                         onMove={(card, stage) => startMove({ kind: 'stage', card, stage })} />
        ) : null}
        {data && tab === 'lots' ? (
          <Lots lots={data.lots} nameOfRecovery={(uid) => nameOf(recs.find((r) => r.uid === uid)?.source_ref)} reload={load} />
        ) : null}
        {data && tab === 'service' ? <Service service={data.service} reload={load} /> : null}
      </div>

      <NplMoveDrawer open={!!drawer} onClose={() => setMove(null)} busy={moveAct.busy} {...drawer} />
      <CaseSheet uid={caseUid} open={!!caseUid} openLog={caseLog} onLogClose={() => setCaseLog(false)}
                 onClose={() => setCaseUid(null)} onChanged={load} />
    </div>
  )
}

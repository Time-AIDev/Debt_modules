import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useIdentity, atLeast } from '../lib/identity.jsx'
import { useCrumb } from '../lib/crumb.jsx'
import { money, date } from '../lib/format.js'
import { useDictionary, labelFor } from '../lib/dictionaries.js'
import { FAMILIES, tierStatus } from '../lib/status.js'
import { ListPanel, Group, ListRow } from '../components/ListPanel.jsx'
import { PaymentPosition } from '../components/PaymentPosition.jsx'
import { RecordView } from '../components/RecordView.jsx'
import { ContactDrawer, contactSummary, openPromise } from '../components/ContactDrawer.jsx'
import { MoveDrawer } from '../components/MoveDrawer.jsx'
import { Board } from '../components/Board.jsx'
import { CaseSheet } from '../components/CaseSheet.jsx'
import { SegmentedControl } from '../components/SegmentedControl.jsx'
import { AssignBar } from '../components/AssignBar.jsx'
import { AssignSplitDrawer } from '../components/AssignSplitDrawer.jsx'
import { DailySummary } from '../components/DailySummary.jsx'
import { InfoPopover } from '../components/InfoPopover.jsx'
import { StatusPill } from '../components/StatusIcon.jsx'
import { Icon } from '../components/Icon.jsx'
import { LoadError, Problem } from '../components/Problem.jsx'
import { Drawer } from '../components/Drawer.jsx'
import { useToast } from '../components/Toast.jsx'
import { useReloadOnEpoch } from '../lib/dataEpoch.jsx'
import { DataFreshness } from '../components/DataFreshness.jsx'
import { downloadText } from '../lib/download.js'

/** A row's status icon: worked today → done, else its tier's (brief §3.2). */
const rowKind = (it) => tierStatus(it.worked_today ? 'WORKED' : it.tier).kind
const passed = (item) => (item.conditions || []).every((condition) => condition.passed)
const passedCount = (item) => (item.conditions || []).filter((condition) => condition.passed).length

export function Today() {
  const { t, lang, todayView, setTodayView } = usePrefs()
  const identity = useIdentity()
  const toast = useToast()
  useCrumb('group.mine', 'nav.today')

  const [params, setParams] = useSearchParams()
  const [officer, setOfficer] = useState('')
  const [payload, setPayload] = useState(null)
  const [problem, setProblem] = useState(null)
  const [columns, setColumns] = useState(null)
  const [officers, setOfficers] = useState([])
  const [record, setRecord] = useState(null)
  const [recordProblem, setRecordProblem] = useState(null)
  const [closed, setClosed] = useState({})
  const [sortRisk, setSortRisk] = useState(false)
  const [contactFor, setContactFor] = useState(null)
  const [moveFor, setMoveFor] = useState(null)
  const [moveProblem, setMoveProblem] = useState(null)
  const [moving, setMoving] = useState(false)
  // feedback-r2 TASK-013/014: the supervisor's multi-select and its assign bar.
  const [selected, setSelected] = useState(() => new Set())
  const [assigning, setAssigning] = useState(false)
  const [assignProblem, setAssignProblem] = useState(null)
  // TASK-028: the manager's portfolio split drawer, and TASK-030: the worked group.
  const [splitOpen, setSplitOpen] = useState(false)
  const [workedOpen, setWorkedOpen] = useState(false)
  // Final design: the board opens a customer in the case pop-up ({ uid, log }).
  const [sheet, setSheet] = useState(null)
  const [exportOpen, setExportOpen] = useState(false)
  const [exportReason, setExportReason] = useState('')
  const [exportProblem, setExportProblem] = useState(null)
  const [exporting, setExporting] = useState(false)

  const nextActions = useDictionary('NEXT_ACTION')
  const selUid = params.get('sel')
  const workstream = params.get('workstream') === 'pre_install' ? 'pre_install' : 'collection'
  const preInstall = workstream === 'pre_install'
  const board = todayView === 'board' && !preInstall
  const itemUid = useCallback((item) => (preInstall ? item?.customer_uid : item?.customer?.uid), [preInstall])

  const loadVersion = useRef(0)
  const load = useCallback(() => {
    const version = ++loadVersion.current
    setProblem(null)
    setPayload(null)
    setRecord(null)
    setSelected(new Set())
    // feedback-r2 TASK-015: the "ยังไม่มอบหมาย" option filters through the server's
    // own unassigned desk, never by dropping rows on the client.
    const query = officer === '__unassigned__' ? { unassigned: 1 } : officer ? { officer } : undefined
    const request = preInstall ? api.pipeline() : api.today(query)
    request
      .then((d) => { if (version === loadVersion.current) setPayload(d) })
      .catch((e) => {
        if (version === loadVersion.current) setProblem(e?.problem || { code: 'request_failed' })
      })
  }, [officer, preInstall])

  useEffect(() => {
    load()
    return () => { loadVersion.current += 1 }
  }, [load])
  useReloadOnEpoch(load)
  useEffect(() => {
    api.boardColumns().then((d) => setColumns(d?.columns || [])).catch(() => setColumns([]))
    api.officers().then((d) => setOfficers(d?.officers || [])).catch(() => setOfficers([]))
  }, [])

  const items = payload?.items || []
  const meta = payload?.meta || {}

  const tierLabel = useCallback((tier) => {
    const key = lang === 'en' ? 'tier_labels_en' : 'tier_labels_th'
    return (meta[key] || {})[tier] || tier
  }, [meta, lang])

  const grouped = useMemo(() => (meta.tiers || []).map((tier) => {
    const pool = items.filter((it) => it.tier === tier && it.case?.payment_status !== 'PENDING')
    const rows = sortRisk ? [...pool].sort((a, b) => Number(b.aggregate_overdue) - Number(a.aggregate_overdue)) : pool
    return { tier, label: tierLabel(tier), rows }
  }), [items, meta, sortRisk, tierLabel])
  const pendingRows = items.filter((it) => it.case?.payment_status === 'PENDING')
  // R-A: rows worked today leave their tier group and collect in one collapsed group
  // at the bottom; the tier order inside both groups is untouched.
  const allGroups = [
    ...(pendingRows.length ? [{ tier: 'PAYMENT_PENDING', label: t('today.paymentPending'), rows: pendingRows }] : []),
    ...grouped,
  ]
  const unworkedGroups = allGroups
    .map((g) => ({ ...g, rows: g.rows.filter((r) => !r.worked_today) }))
    .filter((g) => g.rows.length > 0)
  const workedRows = allGroups.flatMap((g) => g.rows.filter((r) => r.worked_today))
  const preInstallGroups = useMemo(() => [
    { tier: 'PREINSTALL_BLOCKED', label: t('pipeline.blocked'), rows: items.filter((item) => !passed(item)) },
    { tier: 'PREINSTALL_READY', label: t('pipeline.ready'), rows: items.filter((item) => passed(item)) },
  ].filter((group) => group.rows.length), [items, t])

  // The first row on load is the first one on screen still to work (the sort toggle
  // included); once shown it is pinned in the URL, so a saved contact keeps it
  // selected (it only moves into the worked group).
  const sel = items.find((it) => itemUid(it) === selUid)
    || (preInstall ? preInstallGroups[0]?.rows[0] : unworkedGroups[0]?.rows[0])
    || workedRows[0]
    || items[0]
  useEffect(() => {
    const uid = itemUid(sel)
    if (uid && uid !== selUid) select(uid)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel, selUid, itemUid])

  useEffect(() => {
    if (!sel) { setRecord(null); return undefined }
    let alive = true
    setRecord(null)
    setRecordProblem(null)
    api.caseDetail(itemUid(sel))
      .then((d) => { if (alive) setRecord(d) })
      .catch((e) => { if (alive) setRecordProblem(e?.problem || { code: 'request_failed' }) })
    return () => { alive = false }
  }, [sel, itemUid])

  const officerName = useCallback((uid) => {
    const o = officers.find((x) => x.uid === uid)
    return (lang === 'en' ? o?.display_name_en : o?.display_name_th) || uid
  }, [officers, lang])

  const boardColumns = useMemo(() => (columns || []).map((c) => {
    const key = `board.col.${c.column_id}`
    const translated = t(key)
    return { id: c.column_id, label: translated === key ? c.name : translated, kind: FAMILIES.board[1][c.column_id] }
  }), [columns, t])

  const boardItems = useMemo(() => (preInstall ? [] : items.map((it) => {
    const next = it.case?.next_action ? labelFor(nextActions, it.case.next_action, lang) : ''
    return {
      uid: it.customer.uid,
      name: it.customer.display_name,
      icon: rowKind(it),
      entity: it.entity,
      source: it.data_source,
      score: it.risk_score,
      arrears: it.aggregate_overdue,
      balance: it.aggregate_outstanding,
      dpd: it.oldest_dpd,
      bandLabel: lang === 'en' ? it.aging_bucket_label_en : it.aging_bucket_label_th,
      nextAction: next,
      nextTitle: next ? t('today.nextTitle', { label: next, on: date(it.case?.next_action_on) }) : '',
      locked: it.contact_lock?.state === 'LOCKED',
      lockedBy: it.contact_lock?.locked_by,
      pendingReview: it.board_pending_review_uid,
      autoMoved: it.auto_moved,
      autoCause: it.auto_moved_cause,
      override: it.board_override,
      columnId: it.board_column_id,
    }
  })), [items, lang, nextActions, preInstall, t])

  function select(uid) {
    const next = new URLSearchParams(params)
    next.set('sel', uid)
    setParams(next, { replace: true })
  }

  function changeWorkstream(value) {
    const next = new URLSearchParams(params)
    next.set('workstream', value)
    next.delete('sel')
    setSelected(new Set())
    setRecord(null)
    setPayload(null)
    setParams(next, { replace: true })
  }

  function afterWrite() {
    load()
  }

  async function exportSelected() {
    if (!selected.size || exportReason.trim().length < 8) return
    setExporting(true)
    setExportProblem(null)
    try {
      const result = await api.todayExport({
        workstream,
        customer_uids: [...selected],
        reason: exportReason.trim(),
      })
      downloadText(result.filename, result.text)
      toast(t('today.exported', { n: selected.size }))
      setExportOpen(false)
      setExportReason('')
    } catch (error) {
      setExportProblem(error?.problem || { code: 'export_failed' })
    } finally {
      setExporting(false)
    }
  }

  async function submitMove(toId, reason) {
    setMoving(true)
    setMoveProblem(null)
    try {
      const result = await api.boardMove({
        customer_uid: moveFor.uid,
        to_column_id: toId,
        reason,
        by: identity.officer || undefined,
      })
      const dest = boardColumns.find((c) => c.id === toId)
      if (result.applied) toast(t('board.movedForward', { column: dest?.label || toId }))
      else toast(t('board.sentForReview'))
      setMoveFor(null)
      afterWrite()
    } catch (e) {
      setMoveProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setMoving(false)
    }
  }

  // F10 / Q5 (TASK-014): one request for the whole selection — never a client loop
  // over the single-assign route, so a failure leaves nothing half-assigned.
  async function assignSelected(officerUid, reason) {
    if (!selected.size || !officerUid) return
    setAssigning(true)
    setAssignProblem(null)
    try {
      const result = await api.assignCustomers({
        customer_uids: [...selected],
        officer_uid: officerUid,
        reason,
        by: identity.officer || undefined,
      })
      toast(t('today.assigned', { n: result?.count ?? selected.size }))
      setSelected(new Set())
      load()
    } catch (e) {
      setAssignProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setAssigning(false)
    }
  }

  function toggleTick(uid) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(uid)) next.delete(uid)
      else next.add(uid)
      return next
    })
  }

  // F10 / TASK-015: each officer's own list size rides the option, and the unassigned
  // group is its own choice (served by /v1/today?unassigned=1).
  const officerOptions = [
    { id: '', label: t('today.officerAll') },
    ...officers.map((o) => {
      const count = meta.officer_totals?.[o.uid]
      return { id: o.uid, label: count === undefined || count === null ? officerName(o.uid) : `${officerName(o.uid)} · ${count}` }
    }),
    { id: '__unassigned__', label: t('today.officerUnassigned', { n: meta.unassigned_total ?? '—' }) },
  ]
  const businessDate = preInstall ? payload?.meta?.business_date : payload?.run?.business_date
  const canSelect = atLeast('OFFICER')
  const canAssign = atLeast('SUPERVISOR')
  const canSplit = atLeast('MANAGER')

  // F17 / TASK-030: the summary follows the list on screen — the filtered officer's
  // own entry, else "*" (the whole list served, the unassigned desk included).
  const summaries = meta.daily_summary || {}
  const dailySummary = (officer && officer !== '__unassigned__' ? summaries[officer] : null) || summaries['*'] || null
  // The served Odoo-identities sentence; its "where" part (after the last " — ") links
  // to the book — the whole sentence when it has no such part.
  const identitiesNote = lang === 'en' ? meta.identities_note_en : meta.identities_note_th
  const noteDash = identitiesNote ? identitiesNote.lastIndexOf(' — ') : -1
  const noteCut = noteDash < 0 ? 0 : noteDash + 3

  function renderRow(it) {
    const uid = it.customer.uid
    const name = it.customer.display_name
    const hasIssue = Number(it.open_service_issues || 0) > 0
    return (
      <ListRow
        key={uid}
        icon={hasIssue ? 'problem' : 'done'}
        iconTitle={t(hasIssue ? 'today.issueOpen' : 'today.issueNone')}
        name={name}
        sub={it.customer.volt_id || it.customer.customer_no}
        current={itemUid(sel) === uid}
        onSelect={() => select(uid)}
        select={canSelect ? { checked: selected.has(uid), onToggle: () => toggleTick(uid), label: t('today.selectRow', { name }) } : undefined}
        chips={(
          <PaymentPosition pp={it.payment_position} compact />
        )}
      />
    )
  }

  function renderPreInstallRow(item) {
    const uid = item.customer_uid
    const name = item.display_name
    const gateState = item.gate_down_payment?.state
    const downPayment = gateState === 'PASSED'
      ? { kind: 'done', key: 'today.dpReceived' }
      : item.amount_due !== null && item.amount_due !== undefined && item.amount_due !== ''
        ? { kind: 'do', key: 'today.dpWaiting' }
        : { kind: 'idle', key: 'today.dpUnknown' }
    return (
      <ListRow
        key={uid}
        icon={passed(item) ? 'done' : 'do'}
        name={name}
        sub={[item.volt_id || item.customer_no, item.entity, item.sales_lead].filter(Boolean).join(' · ')}
        arrears={money(item.amount_due)}
        dpd={item.case_dpd}
        dpdLabel={item.case_dpd === null || item.case_dpd === undefined ? t('today.dpdNone') : `DPD ${item.case_dpd}`}
        score={item.risk_score}
        current={itemUid(sel) === uid}
        onSelect={() => select(uid)}
        select={canSelect ? { checked: selected.has(uid), onToggle: () => toggleTick(uid), label: t('today.selectRow', { name }) } : undefined}
        chips={(
          <>
            <StatusPill kind={downPayment.kind}>{t(downPayment.key)}</StatusPill>
            <StatusPill kind={passed(item) ? 'done' : 'do'}>
              {t('pipeline.progress', { done: passedCount(item), total: (item.conditions || []).length })}
            </StatusPill>
          </>
        )}
      />
    )
  }

  return (
    <div className={`today today--${board ? 'board' : 'list'}`}>
      <div className="today__lens">
        <h1 className="today__title">{t('nav.today')}</h1>
        <span className="today__count num">{meta.total ?? '—'} {t('today.items')}</span>
        <span className="today__divider" aria-hidden="true" />
        <DataFreshness className="today__fresh" />
        <SegmentedControl
          label={t('today.workstream')}
          value={workstream}
          onChange={changeWorkstream}
          options={[
            { id: 'collection', label: t('today.collection') },
            { id: 'pre_install', label: t('today.preInstall') },
          ]}
        />
        {/* F10b/F10c / R-C (TASK-028): the portfolio split, a manager's act — disabled
            with its reason below manager. */}
        {!preInstall ? <button type="button" className="btn btn--sm" disabled={!canSplit}
                title={canSplit ? undefined : t('today.splitManagerOnly')} onClick={() => setSplitOpen(true)}>
          <Icon name="split" />{t('today.split')}
        </button> : null}
        {!preInstall ? <SegmentedControl
          label={t('shell.view')}
          value={todayView}
          onChange={setTodayView}
          options={[
            { id: 'split', label: <><Icon name="list" />{t('view.split')}</> },
            { id: 'board', label: <><Icon name="board" />{t('view.board')}</> },
          ]}
        /> : null}
        {board ? <InfoPopover align="right">{t('board.moveNote')}</InfoPopover> : null}
      </div>

      {board ? (
        <>
          {problem ? <LoadError problem={problem} onRetry={load} /> : null}
          {!problem && !columns ? <p className="empty">{t('common.loading')}</p> : null}
          {columns ? (
            <Board
              columns={boardColumns}
              items={boardItems}
              reconcile={meta.total}
              onOpen={(uid) => setSheet({ uid, log: false })}
              onLog={(card) => setSheet({ uid: card.uid, log: true })}
              onMove={(card) => { setMoveProblem(null); setMoveFor(card) }}
            />
          ) : null}
        </>
      ) : (
        <div className="work work--split today__work">
          <ListPanel
            title={t('nav.today')}
            hideTitle
            sub={preInstall ? t('pipeline.sub') : t('today.sub', { date: businessDate ? date(businessDate) : '—' })}
            sort={!preInstall ? (
              <button type="button" className="btn btn--quiet btn--sm" onClick={() => setSortRisk(!sortRisk)} title={t('today.sortTitle')}>
                <Icon name="sort" />{sortRisk ? t('today.sortRisk') : t('today.sortOrder')}
              </button>
            ) : undefined}
            filter={!preInstall ? (
              <select className="field today__filter" aria-label={t('today.officer')} value={officer}
                      onChange={(e) => setOfficer(e.target.value)}>
                {officerOptions.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
              </select>
            ) : undefined}
            pinned={(
              <>
                {selected.size > 0 ? (
                  <div className="today__selection" role="region" aria-label={t('today.selectionRegion')}>
                    {!canAssign || preInstall ? <strong>{t('today.selectedN', { n: selected.size })}</strong> : <span className="spacer" />}
                    <button type="button" className="btn btn--primary btn--sm" onClick={() => { setExportProblem(null); setExportOpen(true) }}>
                      <Icon name="download" />{t('today.exportSelected')}
                    </button>
                    <button type="button" className="btn btn--quiet btn--sm" onClick={() => setSelected(new Set())}>
                      {t('today.clearSelection')}
                    </button>
                  </div>
                ) : null}
                {/* F10 / Q5 (TASK-014): the selection's own bar, only while rows are ticked. */}
                {!preInstall && canAssign && selected.size > 0 ? (
                  <AssignBar
                    count={selected.size}
                    customerUids={[...selected]}
                    officers={officers}
                    totals={meta.officer_totals || {}}
                    busy={assigning}
                    problem={assignProblem}
                    onAssign={assignSelected}
                    onClear={() => setSelected(new Set())}
                    onDone={() => { setSelected(new Set()); load() }}
                  />
                ) : null}
                {/* F17 / TASK-030: the served numbers of the day. */}
                {!preInstall ? <DailySummary summary={dailySummary} /> : null}
              </>
            )}
            note={!preInstall && identitiesNote ? (
              <span>
                {identitiesNote.slice(0, noteCut)}
                <Link className="today__noteLink" to="/book">{identitiesNote.slice(noteCut)}</Link>
              </span>
            ) : null}
          >
            {problem ? <div className="today__pad"><LoadError problem={problem} onRetry={load} /></div> : null}
            {!problem && !payload ? <p className="empty">{t('common.loading')}</p> : null}
            {payload && !items.length ? (
              <div className="today__empty">
                <p className="empty">{t('today.empty')}</p>
                {officer ? (
                  <button type="button" className="btn btn--quiet btn--sm" onClick={() => setOfficer('')}>{t('today.clearFilter')}</button>
                ) : null}
              </div>
            ) : null}
            {(preInstall ? preInstallGroups : unworkedGroups).map((g) => (
              <Group
                key={g.tier}
                label={g.label}
                count={g.rows.length}
                icon={preInstall ? (g.tier === 'PREINSTALL_READY' ? 'done' : 'do') : tierStatus(g.tier).kind}
                open={!closed[g.tier]}
                onToggle={() => setClosed((c) => ({ ...c, [g.tier]: !c[g.tier] }))}
              >
                {g.rows.map(preInstall ? renderPreInstallRow : renderRow)}
              </Group>
            ))}
            {!preInstall && workedRows.length ? (
              <Group
                label={t('today.workedGroup')}
                count={meta.worked_today_count ?? workedRows.length}
                icon={tierStatus('WORKED').kind}
                open={workedOpen}
                onToggle={() => setWorkedOpen((v) => !v)}
              >
                {workedRows.map(renderRow)}
              </Group>
            ) : null}
          </ListPanel>

          <div className="today__case">
            {sel ? (
              <RecordView
                mode="page"
                item={sel}
                data={record}
                problem={recordProblem}
                businessDate={businessDate}
                onRetry={() => api.caseDetail(itemUid(sel)).then(setRecord).catch(() => {})}
                onChanged={afterWrite}
                onLogContact={() => setContactFor(preInstall ? (record?.customer || { uid: itemUid(sel), display_name: sel.display_name }) : sel.customer)}
              />
            ) : payload ? <p className="today__none">{t('today.noCase')}</p> : null}
          </div>
        </div>
      )}

      <ContactDrawer
        open={!!contactFor}
        onClose={() => setContactFor(null)}
        customer={contactFor}
        businessDate={businessDate}
        summary={contactSummary(record?.customer?.uid === contactFor?.uid ? record : null)}
        promise={openPromise(record?.customer?.uid === contactFor?.uid ? record : null)}
        onSaved={afterWrite}
      />
      <MoveDrawer
        open={!!moveFor}
        onClose={() => setMoveFor(null)}
        subtitle={moveFor?.name}
        currentId={moveFor?.columnId}
        options={boardColumns}
        busy={moving}
        problem={moveProblem}
        onConfirm={submitMove}
      />
      <AssignSplitDrawer
        open={splitOpen}
        onClose={() => setSplitOpen(false)}
        officers={officers}
        totals={meta.officer_totals || {}}
        onDone={load}
      />
      <Drawer
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        title={t('today.exportTitle')}
        footer={(
          <>
            <button type="button" className="btn" onClick={() => setExportOpen(false)}>{t('common.cancel')}</button>
            <button type="button" className="btn btn--primary" disabled={exporting || exportReason.trim().length < 8 || exportReason.trim().length > 500} onClick={exportSelected}>
              {exporting ? t('common.saving') : t('today.exportRun')}
            </button>
          </>
        )}
      >
        <label className="stack stack--tight">
          <span className="eyebrow">{t('today.exportReason')}<span className="req" aria-hidden="true">*</span></span>
          <textarea className="field" rows={4} required aria-required="true" minLength={8} maxLength={500}
                    value={exportReason} onChange={(event) => setExportReason(event.target.value)} />
        </label>
        {exportProblem ? <Problem problem={exportProblem} /> : null}
      </Drawer>
      <CaseSheet
        uid={sheet?.uid}
        open={!!sheet}
        item={sheet ? items.find((it) => it.customer?.uid === sheet.uid) : undefined}
        openLog={!!sheet?.log}
        onLogClose={() => setSheet((s) => (s ? { ...s, log: false } : s))}
        onClose={() => setSheet(null)}
        onChanged={afterWrite}
      />
    </div>
  )
}

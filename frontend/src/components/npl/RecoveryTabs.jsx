import { Fragment, useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api.js'
import { usePrefs } from '../../lib/prefs.jsx'
import { useIdentity } from '../../lib/identity.jsx'
import { money, int, date } from '../../lib/format.js'
import { recoveryStatus, recoveryOutcome, lotStatus, serviceStatus, invoiceStatus, paymentStatus } from '../../lib/status.js'
import { StatusIcon, StatusPill, NeutralChip } from '../StatusIcon.jsx'
import { Icon } from '../Icon.jsx'
import { Problem } from '../Problem.jsx'
import { InfoPopover } from '../InfoPopover.jsx'
import { Lanes, MoneyForm, CloseForm, RecoveryLines, SrLabel, useAct, word } from './parts.jsx'

const caret = <Icon name="down" className="glist__caret" />

/** Tab "การเรียกคืน" (spec §3): one line per record, the first open; money and close in place. */
export function Recoveries({ recs, nameOf, label, reload }) {
  const { t } = usePrefs()
  const [openUid, setOpenUid] = useState(undefined)
  const openId = openUid === undefined ? recs[0]?.uid : openUid
  return (
    <div className="glist glist--recs">
      <div className="glist__head" aria-hidden="true">
        <span /><span>{t('recovery.colRecovery')}</span><span>{t('recovery.colCustomer')}</span><span>{t('recovery.colPath')}</span>
        <span className="r">{t('recovery.expected')}</span><span className="r">{t('recovery.recovered')}</span>
        <span className="glist__pad">{t('recovery.colStatus')}</span><span />
      </div>
      {recs.length ? null : <p className="empty">{t('recovery.noRecovery')}</p>}
      {recs.map((rec) => {
        const s = recoveryStatus(rec.status)
        const open = openId === rec.uid
        return (
          <Fragment key={rec.uid}>
            <button type="button" className="glist__row" aria-expanded={open} onClick={() => setOpenUid(open ? null : rec.uid)}>
              <StatusIcon kind={s.kind} />
              <span className="glist__ref">{rec.uid}</span>
              <span className="glist__name glist__clip" title={nameOf(rec.source_ref)}>
                <SrLabel>{t('recovery.colCustomer')}</SrLabel>{nameOf(rec.source_ref)}
              </span>
              <span className="glist__clip glist__small"><SrLabel>{t('recovery.colPath')}</SrLabel>{label(rec.strategy)}</span>
              <span className="num r"><SrLabel>{t('recovery.expected')}</SrLabel>{money(rec.expected_recovery)}</span>
              <span className="num r strong"><SrLabel>{t('recovery.recovered')}</SrLabel>{money(rec.recovered_total)}</span>
              <span className="glist__pad glist__clip"><StatusPill kind={s.kind}>{t(s.key)}</StatusPill></span>
              {caret}
            </button>
            {open ? <RecoveryOpen rec={rec} reload={reload} /> : null}
          </Fragment>
        )
      })}
    </div>
  )
}

function RecoveryOpen({ rec, reload }) {
  const { t, served } = usePrefs()
  const [form, setForm] = useState(null)
  const locked = rec.status === 'RESOLVED' ? t('recovery.lockedResolved')
    : rec.status === 'SUPERSEDED' ? t('recovery.lockedSuperseded', { uid: rec.superseded_by || '—' }) : null
  const toggle = (f) => setForm((cur) => (cur === f ? null : f))
  return (
    <div className="glist__open">
      <dl className="kv nplcase__kv">
        <dt>{t('recovery.remaining')}</dt><dd className="num">{money(rec.remaining_npv)}</dd>
        <dt>{t('recovery.recovered')}</dt><dd className="num">{money(rec.recovered_total)}</dd>
        <dt>{t('recovery.rateLabel')}</dt>
        <dd className="nplrec__rate">
          {rec.rate_pct ? `${rec.rate_pct}%` : '—'}{rec.rate_is_assumption ? ` · ${t('recovery.assumption')}` : ''}
          <InfoPopover>{served(rec, 'rate_basis')}</InfoPopover>
        </dd>
        <dt>{t('recovery.contract')}</dt><dd>{rec.contract_uid || '—'}</dd>
        <dt>{t('recovery.entity')}</dt><dd>{rec.entity || '—'}</dd>
        {rec.status === 'RESOLVED' ? (
          <><dt>{t('recovery.outcome')}</dt><dd>{`${t(recoveryOutcome(rec.outcome).key)} · ${date(rec.resolved_on)}`}</dd></>
        ) : null}
        {rec.status === 'SUPERSEDED' ? (
          <><dt>{t('status.rec.SUPERSEDED')}</dt><dd>{t('recovery.supersededBy', { uid: rec.superseded_by || '—', date: date(rec.superseded_on) })}</dd></>
        ) : null}
      </dl>
      <div className="nplcase__main">
        <p className="eyebrow">{t('recovery.recoveries')}</p>
        <RecoveryLines rec={rec} />
        <div className="nplcase__acts">
          <button type="button" className="btn btn--primary" disabled={!!locked} title={locked || undefined}
                  aria-expanded={form === 'money'} onClick={() => toggle('money')}><Icon name="plus" />{t('recovery.recordRecovery')}</button>
          <button type="button" className="btn" disabled={!!locked} title={locked || undefined}
                  aria-expanded={form === 'close'} onClick={() => toggle('close')}>{t('recovery.resolve')}</button>
        </div>
        {locked ? <p className="nplcase__reason">{locked}</p> : null}
        {!locked && form === 'money' ? <MoneyForm rec={rec} reload={reload} onClose={() => setForm(null)} /> : null}
        {!locked && form === 'close' ? <CloseForm rec={rec} reload={reload} onClose={() => setForm(null)} /> : null}
      </div>
    </div>
  )
}

/** Tab "กระดานเรียกคืน" (spec §4): the served stages in served order; neutral heads. */
export function RecoveryBoard({ board, stageLabel, onCase, onLog, onMove }) {
  const { t, served } = usePrefs()
  const lanes = (board?.columns || []).map((c) => ({
    id: c.stage,
    label: stageLabel(c.stage),
    cards: (c.cards || []).map((card) => {
      const name = card.display_name || '—'
      const pay = card.payment_status ? paymentStatus(card.payment_status) : null
      return (
        <article key={card.customer_uid} className="lcard">
          <div className="lcard__top">
            <button type="button" className="lcard__name" onClick={() => onCase(card.customer_uid)}>{name}</button>
          </div>
          <p className="lcard__line">{t('recovery.colOverdue')} <strong className="num lcard__big">{money(card.arrears)}</strong></p>
          <p className="lcard__line num">{t('case.cardBalance', { amount: money(card.aggregate_outstanding) })}</p>
          <p className="lcard__chips">
            {pay ? <StatusPill kind={pay.kind}>{t(pay.key)}</StatusPill> : null}
            {card.oldest_dpd == null ? null : <span className="num">DPD {card.oldest_dpd}</span>}
            {card.aging_bucket ? (
              <NeutralChip title={card.aging_bucket}>
                {served(card, 'aging_bucket_label') || word(t, `recovery.aging.${card.aging_bucket}`, card.aging_bucket)}
              </NeutralChip>
            ) : null}
          </p>
          <div className="lcard__acts">
            <button type="button" className="btn btn--sm" onClick={() => onLog(card.customer_uid, name)}>{t('recovery.logContact')}</button>
            <button type="button" className="btn btn--sm btn--quiet" aria-label={t('recovery.moveStageOf', { name })}
                    onClick={() => onMove(card, c.stage)}>{t('recovery.moveMore')}</button>
          </div>
        </article>
      )
    }),
  }))
  return <Lanes lanes={lanes} className="lanes--stages" />
}

const variance = (v) => (v == null ? '—' : v === 0 ? '0' : v > 0 ? `+${v}` : `−${Math.abs(v)}`)
// A lot carries zero grades until it is graded; before that the column says "—".
const graded = (lot) => !!lot.grades && ['GRADED', 'PRICED', 'SOLD'].includes(lot.status)

/** Tab "ล็อตทรัพย์สิน" (spec §6): the served details and the ONE next act of each stage. */
export function Lots({ lots, nameOfRecovery, reload }) {
  const { t } = usePrefs()
  const [openUid, setOpenUid] = useState(null)
  return (
    <div className="glist glist--lots">
      <div className="glist__head">
        <span className="glist__contents" aria-hidden="true">
          <span /><span>{t('recovery.lotNo')}</span><span>{t('recovery.colCustomer')}</span><span>{t('recovery.colStatus')}</span>
          <span className="r">{t('recovery.expectedCount')}</span><span className="r">{t('recovery.actualCount')}</span>
          <span className="r">{t('recovery.variance')}</span><span className="glist__pad">{t('recovery.grades')}</span>
          <span className="r">{t('recovery.resale')}</span>
        </span>
        <InfoPopover align="right">{t('recovery.lotsNote')}</InfoPopover>
      </div>
      {lots.length ? null : <p className="empty">{t('recovery.noLots')}</p>}
      {lots.map((lot) => {
        const s = lotStatus(lot.status)
        const open = openUid === lot.uid
        return (
          <Fragment key={lot.uid}>
            <button type="button" className="glist__row" aria-expanded={open} onClick={() => setOpenUid(open ? null : lot.uid)}>
              <StatusIcon kind={s.kind} />
              <span className="glist__key">{lot.lot_no}</span>
              <span className="glist__clip" title={nameOfRecovery(lot.recovery_uid)}>
                <SrLabel>{t('recovery.colCustomer')}</SrLabel>{nameOfRecovery(lot.recovery_uid)}
              </span>
              <span className="glist__clip glist__small" title={t(s.key)}>{t(s.key)}</span>
              <span className="num r"><SrLabel>{t('recovery.expectedCount')}</SrLabel>{lot.expected_count ?? '—'}</span>
              <span className="num r"><SrLabel>{t('recovery.actualCount')}</SrLabel>{lot.actual_count ?? '—'}</span>
              <span className="num r"><SrLabel>{t('recovery.variance')}</SrLabel>{variance(lot.count_variance)}</span>
              <span className="num glist__pad glist__small">
                <SrLabel>{t('recovery.grades')}</SrLabel>
                {graded(lot) ? `A ${lot.grades.A || 0} · B ${lot.grades.B || 0} · C ${lot.grades.C || 0}` : '—'}
              </span>
              <span className="num r strong"><SrLabel>{t('recovery.resale')}</SrLabel>{money(lot.resale_price)}</span>
              {caret}
            </button>
            {open ? (
              <div className="glist__open">
                <dl className="kv nplcase__kv">
                  <dt>{t('recovery.fee')}</dt><dd className="num">{money(lot.uninstall_fee)}</dd>
                  <dt>{t('recovery.location')}</dt><dd>{lot.location || '—'}</dd>
                  <dt>{t('recovery.watt')}</dt><dd className="num">{lot.watt == null ? '—' : `${int(lot.watt)} W`}</dd>
                  <dt>{t('recovery.product')}</dt><dd>{lot.product_code || '—'}</dd>
                  <dt>{t('recovery.varianceWhy')}</dt><dd>{lot.variance_note || '—'}</dd>
                  <dt>{t('recovery.stock')}</dt><dd>{lot.stock_blocked ? t('recovery.stockLocked') : t('recovery.stockFree')}</dd>
                  {lot.priced_by ? <><dt>{t('recovery.pricedBy')}</dt><dd>{lot.priced_by}</dd></> : null}
                  {lot.sold_amount ? <><dt>{t('recovery.soldAmount')}</dt><dd className="num">{money(lot.sold_amount)}</dd></> : null}
                </dl>
                <LotAct key={lot.status} lot={lot} reload={reload} />
              </div>
            ) : null}
          </Fragment>
        )
      })}
    </div>
  )
}

function LotAct({ lot, reload }) {
  const { t } = usePrefs()
  const identity = useIdentity()
  const { busy, problem, run } = useAct(reload)
  const [f, setF] = useState({ count: '', why: '', a: '', b: '', c: '', price: '' })
  const [asking, setAsking] = useState(false)
  const sellRef = useRef(null)
  const back = useRef(false)
  useEffect(() => { if (!asking && back.current) { back.current = false; sellRef.current?.focus() } }, [asking])
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }))
  const act = (kind, body, okKey) => run(() => api.lotAct(lot.uid, kind, { ...body, by: identity.officer || undefined }), t(okKey))
  const pricer = identity.role === 'OPS' || identity.role === 'OWNER'
  const head = (titleKey, sub) => <h3 className="nplform__head">{t(titleKey)}<span className="nplform__sub">{sub}</span></h3>
  const req = <span className="req" aria-hidden="true">*</span>
  let body = null

  if (lot.status === 'PLANNED' || lot.status === 'UNINSTALLED') {
    const whyReq = f.count.trim() !== '' && Number(f.count) !== lot.expected_count
    body = (
      <>
        {head('recovery.countTitle', `${lot.lot_no} · ${t('recovery.expectedPieces', { n: lot.expected_count })}`)}
        <div className="nplform__grid nplform__grid--count">
          <label className="label"><span>{t('recovery.actualCount')}{req}</span>
            <input className="field num" inputMode="numeric" value={f.count} aria-required="true" onChange={set('count')} /></label>
          <label className="label" title={t('recovery.varianceHint')}><span>{t('recovery.varianceNote')}{whyReq ? req : null}</span>
            <textarea className="field" rows={2} value={f.why} aria-required={whyReq || undefined} onChange={set('why')} /></label>
        </div>
        <div className="nplform__acts">
          <button type="button" className="btn btn--primary" disabled={busy}
                  onClick={() => act('count', { actual_count: f.count.trim() === '' ? null : Number(f.count), variance_note: f.why.trim() || undefined }, 'recovery.countDone')}>
            {t('recovery.saveCount')}
          </button>
        </div>
      </>
    )
  } else if (lot.status === 'COUNTED') {
    body = (
      <>
        {head('recovery.gradeTitle', `${lot.lot_no} · ${t('recovery.countedPieces', { n: lot.actual_count ?? '—' })}`)}
        <div className="nplform__grid nplform__grid--grades">
          {['a', 'b', 'c'].map((k) => (
            <label key={k} className="label"><span>{k.toUpperCase()}{req}</span>
              <input className="field num" inputMode="numeric" value={f[k]} aria-required="true" onChange={set(k)} /></label>
          ))}
        </div>
        <div className="nplform__acts">
          <button type="button" className="btn btn--primary" disabled={busy}
                  onClick={() => act('grade', { grades: { A: Number(f.a || 0), B: Number(f.b || 0), C: Number(f.c || 0) } }, 'recovery.gradeDone')}>
            {t('recovery.gradeAct')}
          </button>
        </div>
      </>
    )
  } else if (lot.status === 'GRADED') {
    const why = pricer ? undefined : t('recovery.opsOnly')
    body = (
      <>
        {head('recovery.priceTitle', lot.lot_no)}
        <label className="label nplform__price"><span>{t('recovery.priceLabel')}{req}</span>
          <input className="field num" inputMode="decimal" value={f.price} aria-required="true" disabled={!pricer} title={why}
                 onChange={set('price')} /></label>
        <div className="nplform__acts">
          <button type="button" className="btn btn--primary" disabled={busy || !pricer} title={why}
                  onClick={() => act('price', { resale_price: f.price }, 'recovery.priceDone')}>{t('recovery.priceAct')}</button>
        </div>
        {why ? <p className="nplform__reason">{why}</p> : null}
      </>
    )
  } else if (lot.status === 'PRICED') {
    const price = money(lot.resale_price)
    const cancel = () => { back.current = true; setAsking(false) }
    body = (
      <>
        {head('recovery.sellAct', `${lot.lot_no} · ${t('recovery.resale')} ${price}`)}
        {asking ? (
          <div className="nplask" role="group" aria-label={t('recovery.sellAct')}>
            <StatusIcon kind="do" />
            <div className="nplask__text">
              <p className="nplask__q">{t('recovery.askSell', { lot: lot.lot_no, price })}</p>
              <p className="nplask__sub">{t('recovery.sellNote')}</p>
            </div>
            <button type="button" className="btn btn--primary" disabled={busy} autoFocus
                    onClick={() => act('sell', {}, 'recovery.sold')}>{t('common.confirm')}</button>
            <button type="button" className="btn" onClick={cancel}>{t('common.cancel')}</button>
          </div>
        ) : (
          <div className="nplform__acts">
            <button type="button" className="btn btn--primary" ref={sellRef} onClick={() => setAsking(true)}>{t('recovery.sellAct')}</button>
          </div>
        )}
      </>
    )
  } else if (lot.status === 'SOLD') {
    body = <p className="nplform__done"><StatusIcon kind="done" />{t('recovery.soldLine', { price: money(lot.sold_amount ?? lot.resale_price) })}</p>
  }

  return (
    <div className="nplform nplform--flat">
      {problem ? <Problem problem={problem} /> : null}
      {body}
    </div>
  )
}

/** The note column of a service account: unpaid bills · a decline asked · why it was cancelled. */
function serviceNote(t, a) {
  const overdue = (a.service_invoices || []).filter((i) => i.state === 'OVERDUE')
  return [
    overdue.length ? t('recovery.unpaidBills', { n: overdue.length, date: date(overdue[0].due_date) }) : null,
    a.decline_requested ? t('recovery.declineAsked') : null,
    a.status === 'CANCELLED' && a.cancelled_reason ? word(t, `recovery.cancel.${a.cancelled_reason}`, a.cancelled_reason) : null,
  ].filter(Boolean).join(' · ') || '—'
}

/** Tab "ค่าบริการเดือน 37+" (spec §7): the window + SVC-37 line, accounts, bill / decline in place. */
export function Service({ service, reload }) {
  const { t } = usePrefs()
  const meta = service?.meta || {}
  const rows = service?.accounts || []
  const [openK, setOpenK] = useState(null)
  return (
    <>
      <p className="npl__context">{t('recovery.serviceLine', {
        from: meta.billing_window?.from_day ?? '—', to: meta.billing_window?.to_day ?? '—',
        decision: meta.decline_pending_decision || '—', owner: meta.decline_owner || '—',
      })}</p>
      <div className="glist glist--svc">
        <div className="glist__head" aria-hidden="true">
          <span /><span>{t('recovery.contract')}</span><span>{t('recovery.colCustomer')}</span><span className="r">{t('recovery.month')}</span>
          <span className="glist__pad">{t('recovery.colStatus')}</span><span className="r">{t('recovery.monthly')}</span>
          <span className="glist__pad">{t('recovery.colNote')}</span><span />
        </div>
        {rows.length ? null : <p className="empty">{t('recovery.noService')}</p>}
        {rows.map((a) => {
          const s = serviceStatus(a)
          const said = t(s.key, { decision: a.decline_pending_decision || '—' })
          const open = openK === a.contract_uid
          const note = serviceNote(t, a)
          return (
            <Fragment key={a.contract_uid}>
              <button type="button" className="glist__row" aria-expanded={open} onClick={() => setOpenK(open ? null : a.contract_uid)}>
                <StatusIcon kind={s.kind} />
                <span className="glist__key">{a.contract_uid}</span>
                <span className="glist__clip" title={a.customer?.display_name || undefined}>
                  <SrLabel>{t('recovery.colCustomer')}</SrLabel>{a.customer?.display_name || '—'}
                </span>
                <span className="num r"><SrLabel>{t('recovery.month')}</SrLabel>{a.month_index ?? '—'}</span>
                <span className="glist__pad glist__clip glist__small" title={said}>{said}</span>
                <span className="num r"><SrLabel>{t('recovery.monthly')}</SrLabel>{money(a.monthly_amount)}</span>
                <span className="glist__pad glist__clip glist__small glist__dim" title={note}>
                  <SrLabel>{t('recovery.colNote')}</SrLabel>{note}
                </span>
                {caret}
              </button>
              {open ? <ServiceOpen a={a} reload={reload} /> : null}
            </Fragment>
          )
        })}
      </div>
    </>
  )
}

function ServiceOpen({ a, reload }) {
  const { t } = usePrefs()
  const identity = useIdentity()
  const { busy, problem, run } = useAct(reload)
  const cancelled = a.status === 'CANCELLED'
  const declined = !!a.decline_requested
  const waiting = t('recovery.declineWaiting', { decision: a.decline_pending_decision || '—' })
  const invoices = a.service_invoices || []
  return (
    <div className="glist__open glist__open--svc">
      <div>
        <p className="eyebrow">{t('recovery.serviceInvoices')}</p>
        {invoices.length ? (
          <table className="nplLines nplLines--inv">
            <tbody>
              {invoices.map((i) => {
                const s = invoiceStatus(i.state)
                return (
                  <tr key={i.uid}>
                    <td className="num">{i.uid}</td>
                    <td><StatusPill kind={s.kind}>{t(s.key)}</StatusPill></td>
                    <td className="nplLines__muted">{t('recovery.due', { date: date(i.due_date) })}</td>
                    <td className="num nplLines__amt">{money(i.amount)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        ) : <p className="nplcase__note">{t('recovery.noServiceInvoices')}</p>}
      </div>
      <div className="nplcase__main">
        {problem ? <Problem problem={problem} /> : null}
        <div className="nplcase__acts">
          <button type="button" className="btn btn--primary" disabled={busy || cancelled} title={cancelled ? t('recovery.billCancelled') : undefined}
                  onClick={() => run(() => api.billService(a.contract_uid), t('recovery.billed'))}>
            <Icon name="receipt" />{t('recovery.bill')}
          </button>
          <button type="button" className="btn" disabled={busy || declined} title={declined ? waiting : undefined}
                  onClick={() => run(() => api.declineService(a.contract_uid, { by: identity.officer || undefined }), t('recovery.declined'))}>
            {declined ? t('recovery.declineDone') : t('recovery.decline')}
          </button>
        </div>
        {cancelled ? <p className="nplcase__reason">{`${t('recovery.bill')}: ${t('recovery.billCancelled')}`}</p> : null}
        {declined ? <p className="nplcase__reason">{waiting}</p> : null}
      </div>
    </div>
  )
}

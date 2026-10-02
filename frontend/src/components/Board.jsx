import { money } from '../lib/format.js'
import { FAMILIES } from '../lib/status.js'
import { usePrefs } from '../lib/prefs.jsx'
import { EntityChip, SourceChip } from './Chips.jsx'
import { StatusIcon, StatusPill, NeutralChip } from './StatusIcon.jsx'
import { Problem } from './Problem.jsx'

const COLUMN_KIND = FAMILIES.board[1]

/**
 * The Kanban board (spec-main §4): the served columns as lanes in the served order —
 * every lane drawn, empty ones included — each headed by its status icon (`col.kind`,
 * else the status mapping's; a column it does not know keeps a plain head: a recovery
 * stage is not an urgency). A card outside the served columns is reported in a
 * Problem box, never dropped.
 */
export function Board({ columns, items, emptyText, onOpen, onLog, onMove, reconcile, moveLabel, moveDisabledTitle, openLabel, balanceLabel }) {
  const { t } = usePrefs()
  const known = new Set((columns || []).map((c) => c.id))
  const unknown = (items || []).filter((i) => !known.has(i.columnId))
  const outside = t('board.reconcile', { n: unknown.length })
  return (
    <>
      {unknown.length > 0 && (
        <Problem problem={{
          code: 'board_reconcile',
          message_th: outside,
          message_en: outside,
          errors: unknown.slice(0, 6).map((i) => ({ pointer: i.uid, message_th: i.name, message: i.name })),
        }} />
      )}
      <div className="board" data-testid="board" data-reconciles={String((items || []).length - unknown.length === reconcile)}>
        {(columns || []).map((col) => {
          const cards = (items || []).filter((i) => i.columnId === col.id)
          const kind = col.kind || COLUMN_KIND[col.id]
          return (
            <section key={col.id} className="board__col" aria-label={col.label}>
              <h2 className="board__head">
                {kind ? <StatusIcon kind={kind} /> : null}
                <span className="board__name">{col.label}</span>
                <span className="board__count num">{cards.length}</span>
              </h2>
              <div className="board__body" role="group" aria-label={col.label} tabIndex={cards.length ? 0 : undefined}>
                {cards.length === 0 ? (
                  <p className="board__empty" data-testid={`board-empty-${col.id}`}>{emptyText || t('board.emptyColumn')}</p>
                ) : cards.map((card) => (
                  <BoardCard key={card.uid} card={card} onOpen={onOpen} onLog={onLog} onMove={onMove}
                             moveLabel={moveLabel} moveDisabledTitle={moveDisabledTitle}
                             openLabel={openLabel} balanceLabel={balanceLabel} />
                ))}
              </div>
            </section>
          )
        })}
      </div>
    </>
  )
}

const isScore = (s) => s !== null && s !== undefined && s !== '' && Number.isFinite(Number(s))

/** One card (spec-main §4): status icon + name → the case + risk; chips; money; DPD · band · next action; actions. */
function BoardCard({ card, onOpen, onLog, onMove, moveLabel, moveDisabledTitle, openLabel, balanceLabel }) {
  const { t } = usePrefs()
  const noDpd = card.dpd === null || card.dpd === undefined
  return (
    <article className="board__card" aria-label={card.name}>
      <div className="board__top">
        {card.icon ? <StatusIcon kind={card.icon} /> : null}
        <button type="button" className="board__nameLink" title={card.name} onClick={() => onOpen(card.uid)}>{card.name}</button>
        {isScore(card.score) ? <span className="board__risk num">{t('today.risk', { n: card.score })}</span> : null}
      </div>
      <div className="board__sub">
        <EntityChip entity={card.entity} />
        <SourceChip source={card.source} />
        {card.locked ? <StatusPill kind="lock">{t('status.today.LOCKED', { who: card.lockedBy || '—' })}</StatusPill> : null}
        {card.pendingReview ? <StatusPill kind="do">{t('status.board.AWAITING_MANAGER')}</StatusPill> : null}
        {card.autoMoved ? <span className="board__mark">{t('board.autoMoved', { cause: t(`board.cause.${card.autoCause}`) })}</span> : null}
        {card.override && !card.pendingReview ? <span className="board__mark">{t('board.overrideActive')}</span> : null}
      </div>
      <div className="board__money">
        <span className="board__arrears num">{money(card.arrears)}</span>
        <span className="board__balance num">{balanceLabel || t('record.balance')} {money(card.balance)}</span>
      </div>
      <div className="board__meta">
        <span className={`board__dpd num${noDpd ? ' board__dpd--none' : ''}`}>{noDpd ? t('today.dpdNone') : `DPD ${card.dpd}`}</span>
        {card.bandLabel ? <NeutralChip>{card.bandLabel}</NeutralChip> : null}
        {card.nextAction ? <span title={card.nextTitle || undefined}>{card.nextAction}</span> : null}
      </div>
      <div className="board__act">
        {openLabel ? (
          <button type="button" className="btn btn--sm" onClick={() => onOpen(card.uid)}>{openLabel}</button>
        ) : null}
        <button type="button" className="btn btn--sm" onClick={() => onLog(card)}>{t('record.logContact')}</button>
        <button type="button" className="btn btn--sm btn--quiet" disabled={!!moveDisabledTitle}
                title={moveDisabledTitle || undefined} onClick={() => onMove(card)}>
          {moveLabel || t('board.requestMove')}
        </button>
      </div>
    </article>
  )
}

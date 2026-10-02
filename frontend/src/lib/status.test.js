import { describe, it, expect } from 'vitest'
import th from './i18n/th.js'
import { translate } from './i18n/index.js'
import {
  FAMILIES, movingKind, statusOf, paymentStatus, tierStatus, todayException, boardColumnStatus, ptpStatus, issueStatus,
  reviewStatus, invoiceStatus, peakDocStatus, preinstallStatus, preinstallProgress, nplCaseStatus, recoveryStatus,
  lotStatus, serviceStatus, importStatus, runStatus, rungStatus, connectionStatus, reconStatus, cellStatus,
  ladderRung, calendarKind, auditStatus, statusColor, channelKey, eventKey, settingStatus,
} from './status.js'

const word = (s, vars) => translate('th', s.key, vars)

describe('the one status mapping (brief §3.2)', () => {
  it('maps payment status — the same icon in the header and the manual-status card', () => {
    expect(paymentStatus('CURRENT')).toEqual({ kind: 'done', key: 'pay.CURRENT' })
    expect(paymentStatus('LATE').kind).toBe('do')
    expect(paymentStatus('NPL').kind).toBe('problem')
    expect(paymentStatus('TERMINATED').kind).toBe('off')
    expect(word(paymentStatus('NOT_INSTALLED'))).toBe('ยังไม่ติดตั้ง')
  })

  it('maps Today tiers, exceptions and board columns', () => {
    expect(tierStatus('PTP_DUE_TODAY').kind).toBe('do')
    expect(tierStatus('BROKEN_PTP').kind).toBe('problem')
    expect(tierStatus('ANSWER_WAITING').kind).toBe('moving-2')
    expect(tierStatus('WORKED').kind).toBe('done')
    expect(word(tierStatus('NEW_ARREARS'))).toBe('ค้างชำระใหม่ ยังไม่เคยติดต่อ')
    expect(todayException('LOCKED').kind).toBe('lock')
    expect(word(todayException('MONEY_IN'), { ref: 'RV-1' })).toBe('เงินเข้าก่อนนัด · RV-1')
    expect(boardColumnStatus('col_01H90')).toEqual({ kind: 'problem', key: 'status.board.col_01H90' })
    expect(word(boardColumnStatus('col_01H8Z'))).toBe('รับปากชำระ')
  })

  it('turns raw PTP, ticket and review codes into Thai words', () => {
    expect(word(ptpStatus('OPEN'))).toBe('นัดเปิดอยู่')
    expect(ptpStatus('BROKEN').kind).toBe('problem')
    expect(ptpStatus('RENEGOTIATED').kind).toBe('moving-2')
    expect(ptpStatus('CANCELLED').kind).toBe('off')
    expect(word(issueStatus('IN_PROGRESS'))).toBe('กำลังแก้')
    expect(issueStatus('NONE').kind).toBe('done')
    expect(word(reviewStatus('OPEN'))).toBe('รอผู้จัดการตอบ')
    expect(reviewStatus('ANSWERED')).toEqual({ kind: 'done', key: 'status.review.ANSWERED' })
    expect(reviewStatus('DECIDED').kind).toBe('done')
  })

  it('maps invoices, PEAK documents and pre-install', () => {
    expect(invoiceStatus('PARTIALLY_PAID')).toEqual({ kind: 'moving-2', key: 'inv.state.PARTIALLY_PAID' })
    expect(invoiceStatus('OVERDUE').kind).toBe('problem')
    expect(invoiceStatus('AR_REVIEW').kind).toBe('moving-1')
    expect(peakDocStatus('REJECTED').kind).toBe('problem')
    expect(peakDocStatus('UNSENT').kind).toBe('off')
    expect(word(preinstallStatus('PASSED'))).toBe('มีหลักฐานแล้ว')
    expect(preinstallProgress(2, 3)).toEqual({ kind: 'moving-3', key: 'status.pre.progress' })
    expect(preinstallProgress(3, 3).kind).toBe('done')
  })

  it('maps NPL cases, recovery records, lots and service 37+', () => {
    expect(nplCaseStatus({})).toEqual({ kind: 'do', key: 'status.npl.UNDECIDED' })
    expect(nplCaseStatus({ status: 'IN_PROGRESS', done: 3 }).kind).toBe('moving-3')
    expect(nplCaseStatus({ status: 'IN_PROGRESS', done: 0 }).kind).toBe('moving-1')
    expect(word(nplCaseStatus({ status: 'RESOLVED', outcome: 'CLOSED_WRITE_OFF' }))).toBe('ตัดจำหน่าย')
    expect(nplCaseStatus({ status: 'SUPERSEDED' }).kind).toBe('off')
    expect(word(nplCaseStatus({ available: false }), { decision: 'D27' })).toBe('ยังใช้ไม่ได้ · รอ D27')
    expect(recoveryStatus('IN_PROGRESS').kind).toBe('moving-2')
    expect(lotStatus('GRADED')).toEqual({ kind: 'moving-3', key: 'status.lot.GRADED' })
    expect(lotStatus('SOLD').kind).toBe('done')
    expect(serviceStatus({ status: 'BILLING', service_invoices: [{ state: 'OVERDUE' }] }).kind).toBe('problem')
    expect(serviceStatus({ status: 'BILLING', decline_requested: true }).kind).toBe('moving-2')
    expect(serviceStatus({ status: 'BILLING' }).kind).toBe('do')
    expect(serviceStatus({ status: 'PREPAID' }).kind).toBe('done')
  })

  it('maps the import states from served codes and flags', () => {
    expect(importStatus('EXACT').kind).toBe('done')
    expect(importStatus('UNMATCHED').kind).toBe('do')
    expect(importStatus('REJECTED').kind).toBe('problem')
    expect(runStatus('running', 1, 2).kind).toBe('moving-2')
    expect(runStatus('failed').kind).toBe('problem')
    expect(rungStatus({ serving: true }).kind).toBe('done')
    expect(rungStatus({ code: 'STALE_SYSTEM', state_en: 'Last resort' }).kind).toBe('off')
    expect(word(rungStatus({ code: 'SHEET', state_en: 'Reserve' }))).toBe('สำรอง')
    expect(connectionStatus({ configured: true, reachable: false }).kind).toBe('problem')
    expect(connectionStatus({}).kind).toBe('off')
    expect(reconStatus({ judged: false }).kind).toBe('idle')
    expect(reconStatus({ matches: false }).kind).toBe('problem')
    expect(reconStatus({ matches: null }).kind).toBe('off')
  })

  it('colours instalment cells and ranks ladder rungs', () => {
    expect(cellStatus('PAID').kind).toBe('paid')
    expect(cellStatus('OVERDUE').kind).toBe('late')
    expect(cellStatus('LATE').kind).toBe('late')
    expect(cellStatus('LINK_SENT').kind).toBe('link')
    expect(cellStatus('UPCOMING', true).kind).toBe('part')
    expect(cellStatus(null).kind).toBe('notdue')
    expect(cellStatus('RESTRUCTURE')).toEqual({ kind: 'notdue', key: 'RESTRUCTURE' })
    expect([0, 1, 2].map((i) => ladderRung(i, 1).kind)).toEqual(['passed', 'current', 'later'])
  })

  it('covers the other screens: calendar kinds and audit results', () => {
    expect(calendarKind('PTP_DUE')).toEqual({ kind: 'do', key: 'cal.kind.PTP_DUE' })
    expect(calendarKind('PTP_PAYMENT').kind).toBe('moneyin')
    expect(auditStatus('REFUSED').kind).toBe('problem')
    expect(statusOf('allocation', 'ALLOCATED').kind).toBe('done')
    expect(statusOf('allocation', 'AWAITING_RULING').kind).toBe('off')
    expect(word(statusOf('edition', 'SUPERSEDED'))).toBe('ถูกแทนที่')
    expect(settingStatus({ lock: 'locked', editable: false })).toEqual({ kind: 'off', key: 'settings.lock.LOCKED' })
    expect(settingStatus({ editable: true }).kind).toBe('done')
    expect(word(settingStatus({ editable: false, editable_by: 'OWNER' }))).toBe('แก้ได้เฉพาะเจ้าของระบบ')
    expect(statusOf('reviewSla', 'BREACHED').kind).toBe('problem')
    expect(statusOf('queue', 'CLEAR').kind).toBe('done')
    expect(word(statusOf('due', 'OVERDUE'))).toBe('เลยกำหนด')
  })

  it('never blanks: an unknown code shows itself, a missing one a dash', () => {
    expect(ptpStatus('SOMETHING_NEW')).toEqual({ kind: 'idle', key: 'SOMETHING_NEW' })
    expect(word(ptpStatus('SOMETHING_NEW'))).toBe('SOMETHING_NEW')
    expect(word(paymentStatus(null))).toBe('—')
    expect(statusOf('nope', 'X')).toEqual({ kind: 'idle', key: 'X' })
  })

  it('has a Thai word for every state it maps', () => {
    for (const [fam, [, kinds]] of Object.entries(FAMILIES)) {
      for (const code of Object.keys(kinds)) expect(th[statusOf(fam, code).key], `${fam}.${code}`).toBeTruthy()
    }
    for (const k of ['paid', 'late', 'notdue', 'link', 'closed', 'part']) expect(th[`status.cell.${k}`]).toBeTruthy()
    for (const k of ['passed', 'current', 'later']) expect(th[`status.ladder.${k}`]).toBeTruthy()
    for (const k of ['status.pre.progress', 'status.pre.released', 'status.npl.UNDECIDED', 'status.npl.UNAVAILABLE', 'status.import.running']) expect(th[k], k).toBeTruthy()
  })

  it('draws the pie by quarter and colours a dot by its kind', () => {
    expect(movingKind(0, 4)).toBe('idle')
    expect(movingKind(1, 4)).toBe('moving-1')
    expect(movingKind(1, 3)).toBe('moving-1')
    expect(movingKind(9, 10)).toBe('moving-4')
    expect(movingKind(4, 4)).toBe('done')
    expect(movingKind(1, 0)).toBe('idle')
    expect(statusColor('problem')).toBe('var(--volt-red)')
    expect(statusColor('moving-2')).toBe('var(--volt-ink)')
    expect(statusColor('lock')).toBe('var(--volt-ink-2)')
  })

  it('names channels and case events in words, never a blank', () => {
    expect(translate('th', channelKey('PHONE'))).toBe('โทรศัพท์')
    expect(translate('th', eventKey('PTP_BROKEN'))).toBe('ผิดนัด')
    expect(translate('th', eventKey('SOMETHING'))).toBe('SOMETHING')
    expect(translate('th', channelKey(undefined))).toBe('—')
  })
})

import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useToast } from './Toast.jsx'
import { Icon } from './Icon.jsx'

/**
 * The customer's phone number on a case (2026-09-20).
 *
 * The server hides the number: every list and the case detail serve a mask plus
 * `phone_revealable`, and `POST .../phone:reveal` is the one audited door that
 * answers `phone_e164`/`phone_display` (PHONE_REVEALED — source and kind, never the
 * digits). This component is the screen half of that contract:
 *
 *   - the mask is the resting state; `เปิดเบอร์` reveals, `ซ่อนเบอร์` hides again;
 *   - a reveal stays open until the officer leaves the case (approved 2026-09-20) —
 *     the reset is a new customer, which is a remount (the caller keys by uid), not
 *     a timer that would blank a number mid-call;
 *   - copy and dial reveal first: the number on the clipboard or in the dialer is
 *     the same act the audit already records, so it is one reveal, not a second
 *     door;
 *   - a customer whose import carries only a mask (the pre-2026-09-20 rows) says so
 *     instead of offering buttons that cannot work.
 *
 * The number is never rendered before the reveal, and a failed reveal keeps the
 * mask in place (the server's own sentence explains why).
 */
export function PhoneLine({ customer }) {
  const { t, lang } = usePrefs()
  const say = useToast()
  const [revealed, setRevealed] = useState(null)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState(null)
  const valueRef = useRef(null)

  const uid = customer?.uid
  useEffect(() => {
    setRevealed(null)
    setProblem(null)
    setBusy(false)
  }, [uid])

  if (!customer) return null
  const revealable = Boolean(customer.phone_revealable)
  const masked = customer.phone_masked && customer.phone_masked !== 'xxx-xxx-xxxx' ? customer.phone_masked : null
  const shown = revealed ? (revealed.phone_display || revealed.phone_e164) : (masked || '—')
  const refusal = problem
    ? (lang === 'en' ? problem.message_en || problem.detail || problem.title || problem.code
                     : problem.message_th || problem.detail || problem.title || problem.code)
    : null

  async function open() {
    if (busy) return null
    setBusy(true)
    setProblem(null)
    try {
      const r = await api.revealCustomerPhone(customer.uid)
      setRevealed(r.customer)
      return r.customer
    } catch (e) {
      setProblem(e?.problem || { code: 'request_failed' })
      return null
    } finally {
      setBusy(false)
    }
  }

  // The design's toggle says the reveal was recorded (the server audits it).
  async function toggle() {
    if (revealed) { setRevealed(null); return }
    if (await open()) say(t('record.phoneRevealed'))
  }

  async function copy() {
    const value = revealed || await open()
    if (!value) return
    const text = value.phone_display || value.phone_e164
    try {
      if (typeof navigator !== 'undefined' && typeof navigator.clipboard?.writeText === 'function') {
        await navigator.clipboard.writeText(text)
        say(t('record.phoneCopied'))
        return
      }
    } catch {
      // fall through to the selection hint
    }
    const node = valueRef.current
    if (node && typeof window !== 'undefined' && window.getSelection) {
      const range = window.document.createRange()
      range.selectNodeContents(node)
      const selection = window.getSelection()
      selection.removeAllRanges()
      selection.addRange(range)
    }
    say(t('record.phoneCopyManual'))
  }

  async function dial() {
    const value = revealed || await open()
    if (!value) return
    if (typeof window !== 'undefined') window.location.href = `tel:${value.phone_e164}`
  }

  return (
    <div className="record__phone">
      {masked || revealed || revealable ? (
        <span ref={valueRef} className="record__phoneValue num" data-revealed={revealed ? 'true' : 'false'}>{shown}</span>
      ) : null}
      {revealable ? (
        <>
          <button type="button" className="btn btn--quiet record__phoneBtn" aria-pressed={Boolean(revealed)}
                  aria-disabled={busy || undefined} onClick={toggle}>
            <Icon name="eye" />{revealed ? t('record.phoneHide') : t('record.phoneShow')}
          </button>
          <button type="button" className="btn btn--quiet record__phoneBtn"
                  aria-disabled={busy || undefined} onClick={copy}>
            <Icon name="copy" />{t('record.phoneCopy')}
          </button>
          {revealed ? (
            <a className="btn btn--quiet record__phoneBtn" href={`tel:${revealed.phone_e164}`}
               aria-label={t('record.phoneCallAria', { number: shown })}><Icon name="phone" />{t('record.call')}</a>
          ) : (
            <button type="button" className="btn btn--quiet record__phoneBtn" title={t('record.phoneCallLocked')}
                    aria-disabled={busy || undefined} onClick={dial}>
              <Icon name="phone" />{t('record.call')}
            </button>
          )}
        </>
      ) : (
        <span className="record__phoneHint">{masked ? t('record.phoneUnavailable') : t('record.phoneNone')}</span>
      )}
      {refusal ? <span className="record__phoneError" role="status">{refusal}</span> : null}
    </div>
  )
}

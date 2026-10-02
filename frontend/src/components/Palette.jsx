import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { NAV_GROUPS } from '../lib/nav.js'
import { invoiceStatus } from '../lib/status.js'
import { StatusIcon } from './StatusIcon.jsx'
import { internalOrigin, recordState } from '../lib/origin.js'

const MATCH_FIELD = {
  volt_id: 'volt_id',
  customer_no: 'customer_no',
  name_roman: 'name_roman',
  phone_masked: 'phone_masked',
  email_masked: 'email_masked',
}

function customerMeta(customer) {
  const field = MATCH_FIELD[customer.matched_on]
  return (field && customer[field]) || customer.officer || ''
}

/**
 * ⌘K palette: local screens and commands plus the lightweight customer index.
 * Customer results stay server-ranked; only local entries are filtered in-browser.
 */
export function Palette({ open, onClose }) {
  const { t, setTheme, theme, setDensity, density, setRailOpen, railOpen } = usePrefs()
  const navigate = useNavigate()
  const location = useLocation()
  const [query, setQuery] = useState('')
  const [customers, setCustomers] = useState([])
  const [index, setIndex] = useState(0)
  const [preview, setPreview] = useState(null)
  const inputRef = useRef(null)
  const previewUidRef = useRef(null)
  const previewRequestRef = useRef(null)
  const previewCacheRef = useRef(new Map())

  function closePreview() {
    previewUidRef.current = null
    previewRequestRef.current?.abort()
    previewRequestRef.current = null
    setPreview(null)
  }

  useEffect(() => {
    if (!open) return undefined
    setQuery('')
    setCustomers([])
    setIndex(0)
    previewCacheRef.current.clear()
    closePreview()
    const id = setTimeout(() => inputRef.current?.focus(), 0)
    return () => clearTimeout(id)
  }, [open])

  useEffect(() => {
    const q = query.trim()
    setCustomers([])
    closePreview()
    if (!open || q.length < 1) return undefined

    let current = true
    const controller = new AbortController()
    const id = setTimeout(() => {
      api.customerSearch({ q, limit: 6 }, { signal: controller.signal }).then((data) => {
        if (current && !controller.signal.aborted) setCustomers(data?.items || [])
      }).catch((error) => {
        if (current && !controller.signal.aborted && error?.name !== 'AbortError') setCustomers([])
      })
    }, 75)
    return () => {
      current = false
      clearTimeout(id)
      controller.abort()
    }
  }, [open, query])

  const entries = useMemo(() => {
    const q = query.trim().toLocaleLowerCase()
    const localMatch = (entry) => !q
      || entry.label.toLocaleLowerCase().includes(q)
      || entry.meta.toLocaleLowerCase().includes(q)
    const screens = NAV_GROUPS.flatMap((group) => group.items.map((item) => ({
      key: `screen-${item.id}`,
      kindCode: 'screen',
      kind: t('palette.kind.screen'),
      label: t(`nav.${item.id}`),
      meta: group.label ? t(group.label) : '',
      go: () => navigate(item.to),
    }))).filter(localMatch)
    const commands = [
      { key: 'command-theme', kindCode: 'command', kind: t('palette.kind.command'), label: t('cmd.theme'), meta: '', go: () => setTheme(theme === 'dark' ? 'light' : 'dark') },
      { key: 'command-density', kindCode: 'command', kind: t('palette.kind.command'), label: t('cmd.density'), meta: '36 / 44 px', go: () => setDensity(density === 'compact' ? 'comfortable' : 'compact') },
      { key: 'command-rail', kindCode: 'command', kind: t('palette.kind.command'), label: t('cmd.rail'), meta: '', go: () => setRailOpen(!railOpen) },
    ].filter(localMatch)
    const people = customers.map((customer) => ({
      key: `customer-${customer.customer_uid}`,
      kindCode: 'customer',
      kind: t('palette.kind.customer'),
      label: customer.display_name || customer.customer_uid,
      meta: customerMeta(customer),
      customer,
      go: () => navigate(`/customers/${customer.customer_uid}`, {
        state: recordState(internalOrigin(location, 'nav.today')),
      }),
    }))
    return [...people, ...screens, ...commands].slice(0, 8)
  }, [query, customers, navigate, location, t, setTheme, theme, setDensity, density, setRailOpen, railOpen])

  useEffect(() => { setIndex(0) }, [query])
  useEffect(() => () => previewRequestRef.current?.abort(), [])

  function showPreview(customer) {
    const uid = customer.customer_uid
    if (previewUidRef.current === uid) return
    previewUidRef.current = uid
    previewRequestRef.current?.abort()
    const cached = previewCacheRef.current.get(uid)
    if (cached) {
      previewRequestRef.current = null
      setPreview({ uid, state: 'ready', ...cached })
      return
    }
    const controller = new AbortController()
    previewRequestRef.current = controller
    setPreview({ uid, state: 'loading', items: [], meta: {} })
    api.customerInvoiceStatuses(uid, { limit: 5 }, { signal: controller.signal }).then((data) => {
      if (controller.signal.aborted || previewUidRef.current !== uid) return
      const result = { items: data?.items || [], meta: data?.meta || {} }
      previewCacheRef.current.set(uid, result)
      previewRequestRef.current = null
      setPreview({ uid, state: 'ready', ...result })
    }).catch((error) => {
      if (controller.signal.aborted || previewUidRef.current !== uid || error?.name === 'AbortError') return
      previewRequestRef.current = null
      setPreview({ uid, state: 'error', items: [], meta: {} })
    })
  }

  if (!open) return null

  function commit(entry) {
    if (!entry) return
    entry.go()
    onClose()
  }

  function previewPanel(customer) {
    if (preview?.uid !== customer.customer_uid) return null
    const panelId = `invoice-preview-${customer.customer_uid}`
    if (preview.state === 'loading') return <p id={panelId} role="status" className="palette__invoiceState">{t('palette.invoiceLoading')}</p>
    if (preview.state === 'error') return <p id={panelId} role="status" className="palette__invoiceState palette__invoiceState--error">{t('palette.invoiceError')}</p>
    if (!preview.items.length) return <p id={panelId} role="status" className="palette__invoiceState">{t('palette.invoiceEmpty')}</p>
    return (
      <div id={panelId} className="palette__invoicePopover" role="region" aria-label={t('palette.invoicePreview', { name: customer.display_name })}>
        <ul className="palette__invoiceList">
          {preview.items.map((invoice) => (
            <li key={invoice.uid}>
              <strong>{invoice.reference}</strong>
              <span className={`palette__invoiceStatus st--${invoiceStatus(invoice.state).kind}`}>
                <StatusIcon kind={invoiceStatus(invoice.state).kind} />
                {t(invoiceStatus(invoice.state).key)}
              </span>
            </li>
          ))}
        </ul>
        {preview.meta.has_more ? (
          <p className="palette__invoiceMore">{t('palette.invoiceMore', { count: preview.meta.remaining })}</p>
        ) : null}
      </div>
    )
  }

  return (
    <div
      className="palette"
      role="dialog"
      aria-modal="true"
      aria-label={t('palette.placeholder')}
      onKeyDown={(event) => {
        if (event.key !== 'Escape') return
        event.stopPropagation()
        if (preview) closePreview()
        else onClose()
      }}
    >
      <div className="palette__scrim" onClick={onClose} />
      <div className="palette__card">
        <div className="palette__head">
          <svg viewBox="0 0 24 24" aria-hidden="true" className="searchbox__icon">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            ref={inputRef}
            value={query}
            placeholder={t('palette.placeholder')}
            aria-label={t('palette.placeholder')}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown') { event.preventDefault(); setIndex((i) => Math.min(i + 1, entries.length - 1)) }
              if (event.key === 'ArrowUp') { event.preventDefault(); setIndex((i) => Math.max(i - 1, 0)) }
              if (event.key === 'Enter') { event.preventDefault(); commit(entries[index]) }
            }}
          />
          <span className="palette__key">ESC</span>
        </div>
        <div className="palette__list">
          {entries.length === 0 ? (
            <p className="empty">{t('palette.noResults')}</p>
          ) : entries.map((entry, i) => entry.kindCode === 'customer' ? (
            <div
              key={entry.key}
              className="palette__result"
              onMouseLeave={closePreview}
              onBlur={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget)) closePreview()
              }}
            >
              <button
                type="button"
                className={`palette__row${i === index ? ' palette__row--on' : ''}`}
                onMouseEnter={() => setIndex(i)}
                onClick={() => commit(entry)}
              >
                <span className="chip chip--current">{entry.kind}</span>
                <span className="palette__label">{entry.label}</span>
                <span className="palette__meta">{entry.meta}</span>
              </button>
              <button
                type="button"
                className="palette__invoiceButton"
                aria-label={t('palette.invoicePreview', { name: entry.label })}
                aria-expanded={preview?.uid === entry.customer.customer_uid}
                aria-controls={`invoice-preview-${entry.customer.customer_uid}`}
                onMouseEnter={() => showPreview(entry.customer)}
                onFocus={() => showPreview(entry.customer)}
                onClick={() => showPreview(entry.customer)}
              >
                &gt;
              </button>
              {previewPanel(entry.customer)}
            </div>
          ) : (
            <button
              key={entry.key}
              type="button"
              className={`palette__row${i === index ? ' palette__row--on' : ''}`}
              onMouseEnter={() => setIndex(i)}
              onClick={() => commit(entry)}
            >
              <span className={`chip${entry.kindCode === 'command' ? ' chip--brand' : ''}`}>{entry.kind}</span>
              <span className="palette__label">{entry.label}</span>
              <span className="palette__meta">{entry.meta}</span>
            </button>
          ))}
        </div>
        <div className="palette__foot">{t('palette.foot')}</div>
      </div>
    </div>
  )
}

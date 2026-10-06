import { useState } from 'react'
import { usePrefs } from '../lib/prefs.jsx'
import { Icon } from './Icon.jsx'

export function CustomerIdentity({ customer }) {
  const { t } = usePrefs()
  const [result, setResult] = useState(null)
  const crm = customer.odoo_crm
  const name = crm?.name || customer.volt_id
  async function copy() {
    try {
      await navigator.clipboard.writeText(name)
      setResult('record.identityCopied')
    } catch {
      setResult('record.identityCopyFailed')
    }
  }
  return <>
    {name ? <>
      {crm?.url ? <a className="case__odooLink case__identityText num" href={crm.url} target="_blank" rel="noopener noreferrer">{name}</a>
        : <span className="case__identityText num">{name}</span>}
      <button type="button" className="btn btn--sm" onClick={copy} aria-label={t(crm?.name ? 'record.identityCopyOdoo' : 'record.identityCopy')}><Icon name="copy" /></button>
    </> : null}
    {customer.customer_no ? <span className="num">{name ? '· ' : ''}<span>{customer.customer_no}</span></span> : null}
    {result ? <span role="status">{t(result)}</span> : null}
  </>
}

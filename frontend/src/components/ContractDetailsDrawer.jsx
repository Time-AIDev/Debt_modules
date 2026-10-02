import { Fragment } from 'react'
import { usePrefs } from '../lib/prefs.jsx'
import { money, date as fmtDate } from '../lib/format.js'
import { Drawer } from './Drawer.jsx'

/**
 * F15 phase 2 / feedback-r2 TASK-022: the contract's facts in one drawer, every row
 * the case detail's own served value. A field the case does not carry reads "—";
 * equipment comes from the PEAK invoice lines when they are served, and says so when
 * they are not.
 */
export function ContractDetailsDrawer({ open, onClose, data }) {
  const { t } = usePrefs()
  if (!data) return null
  // The contract type is a code; the design says it with its Thai word beside it.
  const typeWord = (code) => { const k = `record.contractType.${code}`; const w = t(k); return w === k ? value(code) : w }
  const first = (data.contracts || [])[0] || {}
  const order = data.order || {}
  const totals = data.payment_summary?.totals || {}
  const value = (v) => (v === null || v === undefined || v === '' ? '—' : v)
  const equipment = [...new Set((data.invoices || [])
    .flatMap((inv) => [inv.product_name, ...((inv.lines || []).map((l) => l.product_name))])
    .filter(Boolean))]
  const rows = [
    [t('record.contractNo'), value(first.uid)],
    [t('record.contractProduct'), typeWord(first.product)],
    [t('record.contractEntity'), value(first.entity)],
    [t('record.contractPrincipal'), money(first.principal)],
    [t('record.contractAmount'), money(totals.contract_amount)],
    [t('record.contractTerm'), value(first.term_months)],
    [t('record.pmtMonth'), money(first.pmt)],
    [t('record.contractFirstDue'), fmtDate(first.first_due)],
    ...(first.contract_end ? [[t('deferral.newEnd'), fmtDate(first.contract_end)]] : []),
    [t('record.contractPaidThrough'), fmtDate(first.paid_through)],
    [t('record.contractFeeState'), value(first.fee_state)],
    [t('record.contractEquipment'), equipment.length ? equipment.join(' · ') : t('record.equipmentUnknown')],
  ]
  // The six Odoo-order rows render only when the case serves its order.
  const orderRows = data.order ? [
    [t('record.contractSigned'), fmtDate(order.contract_signed_date)],
    [t('record.contractEpcStart'), fmtDate(order.epc_start_date)],
    [t('record.contractEpcEnd'), fmtDate(order.epc_end_date)],
    [t('record.contractOrderType'), value(order.order_type)],
    [t('record.contractEpc'), value(order.epc)],
    [t('record.contractSalesLead'), value(order.sales_lead)],
  ] : []
  return (
    <Drawer open={open} onClose={onClose} title={t('record.contractDetails')}
            subtitle={data.customer?.display_name} width={520}>
      {[rows, orderRows].filter((r) => r.length).map((list, i) => (
        <dl key={i} className={i ? 'kv contract__order' : 'kv'}>
          {list.map(([label, shown]) => (
            <Fragment key={label}>
              <dt>{label}</dt>
              <dd className="num">{shown}</dd>
            </Fragment>
          ))}
        </dl>
      ))}
    </Drawer>
  )
}

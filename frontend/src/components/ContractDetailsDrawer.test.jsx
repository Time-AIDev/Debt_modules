import { describe, it, expect } from 'vitest'
import { screen } from '@testing-library/react'
import { renderScreen } from '../test-utils.jsx'
import { ContractDetailsDrawer } from './ContractDetailsDrawer.jsx'

const DATA = {
  customer: { display_name: 'ปัทมวรรณ สุขเจริญ' },
  contracts: [{
    uid: 'ct-1', product: 'LEASE', entity: 'SPV', principal: '150000.00', term_months: 96,
    pmt: '2899.00', first_due: '2023-11-10', paid_through: '2025-10-10', fee_state: null,
  }],
  payment_summary: { totals: { contract_amount: '278304.00' } },
  invoices: [
    { product_name: 'Panel 550W' },
    { product_name: 'Panel 550W' },
    { product_name: 'Inverter 5kW' },
  ],
}

describe('the contract details drawer (F15 phase 2)', () => {
  it('prints the served contract rows', () => {
    renderScreen(<ContractDetailsDrawer open onClose={() => {}} data={DATA} />)
    expect(screen.getByText('รายละเอียดสัญญา')).toBeInTheDocument()
    // the contract type is said with its Thai word (raw code → word, design D)
    for (const value of ['ct-1', 'LEASE · สัญญาเช่า', 'SPV', '150,000.00', '278,304.00', '96', '2,899.00', '10/11/2023', '10/10/2025']) {
      expect(screen.getByText(value)).toBeInTheDocument()
    }
    // a null field reads "—", never a fabricated value
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
    // equipment comes from the PEAK lines, deduplicated
    expect(screen.getByText('Panel 550W · Inverter 5kW')).toBeInTheDocument()
  })

  it('says when no equipment is on record', () => {
    renderScreen(<ContractDetailsDrawer open onClose={() => {}} data={{ ...DATA, invoices: [] }} />)
    expect(screen.getByText('ไม่มีข้อมูลอุปกรณ์')).toBeInTheDocument()
  })
})

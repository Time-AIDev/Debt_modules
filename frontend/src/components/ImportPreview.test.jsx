import { beforeEach, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { ImportPreview } from './ImportPreview.jsx'
vi.mock('../lib/api.js', () => ({ api: { applyImportPreview: vi.fn(), dictionary: vi.fn() } }))
const { api } = await import('../lib/api.js')
const entry = { key: 'r1', customer_uid: 'c1', customer_no: 'C1', contract_uid: 'k1', eligible: true,
  source_ref: { sheet: 'Done - Cash', row: 3 }, source_status: 'Late', mapped_status: 'LATE', quality: {} }
const preview = { uid: 'p1', profile: 'debt_status', version: 'v1', entries: [entry] }
beforeEach(() => {
  vi.clearAllMocks()
  api.dictionary.mockResolvedValue({ values: [{ code: 'DEFAULT', label_th: 'ผิดนัด', active: true }] })
  api.applyImportPreview.mockResolvedValue({ state: 'APPLIED' })
})

it('requires row review and a confirmation before applying exact version/keys', async () => {
  const user = userEvent.setup()
  renderScreen(<ImportPreview preview={preview} canApply />)
  const apply = screen.getByRole('button', { name: 'ตรวจสรุปและบันทึกรายการที่เลือก' })
  expect(apply).toBeDisabled()
  await user.click(screen.getByRole('checkbox', { name: 'ตรวจรายการ C1 แล้ว' }))
  await user.click(apply)
  expect(api.applyImportPreview).not.toHaveBeenCalled()
  await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'ยืนยันบันทึกรายการที่ตรวจแล้ว' }))
  await waitFor(() => expect(api.applyImportPreview).toHaveBeenCalledWith('p1', expect.objectContaining({
    preview_version: 'v1', selected_keys: ['r1'], termination_confirmations: [],
  })))
})

it('keeps unknown formulas and unconfirmed status visible and unselectable', () => {
  renderScreen(<ImportPreview preview={{ ...preview, entries: [{ ...entry, eligible: false, source_status: '', mapped_status: null,
    quality: { missing_cached_fields: ['M1'], unknown_money_fields: ['M2'] }, monthly_cells: [
      { month: '2026-01', amount_field: 'M1', amount: '100', unknown: true, status_field: 'Status M1', status: '' },
    ] }] }} canApply />)
  expect(screen.getByRole('checkbox', { name: 'ตรวจรายการ C1 แล้ว' })).toBeDisabled()
  expect(screen.getByText(/M1 · M2/)).toBeInTheDocument()
  expect(screen.queryByText('100')).toBeNull()
  expect(screen.getByText(/ยังยืนยันไม่ได้ → ยังยืนยันไม่ได้/)).toBeInTheDocument()
})

it('imports repossession evidence without implicitly terminating the contract', async () => {
  const user = userEvent.setup()
  renderScreen(<ImportPreview preview={{ ...preview, entries: [{ ...entry,
    termination_candidate: { completed_evidence: true, contract_uids: ['k1'] } }] }} canApply />)
  await user.click(screen.getByRole('checkbox', { name: 'ตรวจรายการ C1 แล้ว' }))
  expect(screen.getByRole('checkbox', { name: 'ยุติสัญญาที่ระบุจากหลักฐานนี้ด้วย' })).not.toBeChecked()
  expect(screen.queryByRole('combobox')).toBeNull()
  await user.click(screen.getByRole('button', { name: 'ตรวจสรุปและบันทึกรายการที่เลือก' }))
  await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'ยืนยันบันทึกรายการที่ตรวจแล้ว' }))
  await waitFor(() => expect(api.applyImportPreview.mock.calls[0][1].termination_confirmations).toEqual([]))
})

it('never supplies a default termination cause and requires reason and exact scope', async () => {
  const user = userEvent.setup()
  renderScreen(<ImportPreview preview={{ ...preview, entries: [{ ...entry,
    termination_candidate: { completed_evidence: true, contract_uids: ['k1'] } }] }} canApply />)
  await user.click(screen.getByRole('checkbox', { name: 'ตรวจรายการ C1 แล้ว' }))
  await user.click(screen.getByRole('checkbox', { name: 'ยุติสัญญาที่ระบุจากหลักฐานนี้ด้วย' }))
  expect(screen.getByRole('combobox')).toHaveValue('')
  const apply = screen.getByRole('button', { name: 'ตรวจสรุปและบันทึกรายการที่เลือก' })
  expect(apply).toBeDisabled()
  await user.selectOptions(screen.getByRole('combobox'), 'DEFAULT')
  await user.type(screen.getByRole('textbox'), 'ตรวจหลักฐานเรียกคืนครบแล้ว')
  expect(apply).toBeDisabled()
  await user.click(screen.getByRole('checkbox', { name: 'ตรวจและยืนยันสัญญาที่จะยุติ: k1' }))
  await user.click(apply)
  await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'ยืนยันบันทึกรายการที่ตรวจแล้ว' }))
  await waitFor(() => expect(api.applyImportPreview.mock.calls[0][1].termination_confirmations).toEqual([
    { key: 'r1', cause: 'DEFAULT', reason: 'ตรวจหลักฐานเรียกคืนครบแล้ว', contract_uids: ['k1'] },
  ]))
})

it('does not offer apply or editable selections to an unauthorized role', () => {
  renderScreen(<ImportPreview preview={preview} canApply={false} />)
  expect(screen.getByRole('checkbox', { name: 'ตรวจรายการ C1 แล้ว' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'ตรวจสรุปและบันทึกรายการที่เลือก' })).toBeDisabled()
})

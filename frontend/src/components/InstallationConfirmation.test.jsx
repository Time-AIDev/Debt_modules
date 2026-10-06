import { beforeEach, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderScreen } from '../test-utils.jsx'
import { InstallationConfirmation } from './InstallationConfirmation.jsx'
vi.mock('../lib/api.js', () => ({ api: { confirmInstallation: vi.fn() } }))
const { api } = await import('../lib/api.js')
const data = { contracts: [{ uid: 'k1' }], case: { npl_assessment: { exclusions: [
  { contract_uid: 'k1', reason: 'INSTALLATION_UNCONFIRMED' },
] } } }
beforeEach(() => vi.clearAllMocks())
it('requires actual completion evidence rather than guessing from source dates', async () => {
  const user = userEvent.setup()
  api.confirmInstallation.mockResolvedValue({ confirmation: { completed_on: '2026-10-01', document_ref: 'INSTALL-1' } })
  renderScreen(<InstallationConfirmation data={data} />)
  await user.click(screen.getByText('บันทึกหลักฐานติดตั้งเสร็จ'))
  expect(screen.getByLabelText('วันที่ติดตั้งเสร็จจริง')).toHaveValue('')
  await user.type(screen.getByLabelText('วันที่ติดตั้งเสร็จจริง'), '2026-10-01')
  await user.type(screen.getByLabelText('เลขอ้างอิงเอกสารติดตั้ง'), 'INSTALL-1')
  await user.type(screen.getByLabelText('รายละเอียดที่ตรวจสอบแล้ว'), 'ตรวจเอกสารลงนามรับมอบแล้ว')
  await user.click(screen.getByRole('button', { name: 'ยืนยันติดตั้งเสร็จจากหลักฐาน' }))
  await waitFor(() => expect(api.confirmInstallation).toHaveBeenCalledWith('k1', expect.objectContaining({
    completed_on: '2026-10-01', document_ref: 'INSTALL-1', reason: 'ตรวจเอกสารลงนามรับมอบแล้ว',
  })))
})
it('does not ask for completion confirmation on an unrelated exclusion', () => {
  renderScreen(<InstallationConfirmation data={{ ...data, case: { npl_assessment: { exclusions: [
    { contract_uid: 'k1', reason: 'CANCELLED' },
  ] } } }} />)
  expect(screen.queryByText('บันทึกหลักฐานติดตั้งเสร็จ')).toBeNull()
})

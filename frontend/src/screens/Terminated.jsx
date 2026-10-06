import { useEffect, useState } from 'react'
import { Link, useLocation, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useCrumb } from '../lib/crumb.jsx'
import { CycleGrid } from '../components/CycleGrid.jsx'
import { DataTable } from '../components/DataTable.jsx'
import { LoadError } from '../components/Problem.jsx'
import { date } from '../lib/format.js'
import { ActionLogNav } from '../components/ActionLogNav.jsx'
import './history.css'

export const causeLabel = (value) => ({ DEFAULT: 'ผิดนัด / เรียกคืน', CUSTOMER_REQUEST: 'ลูกค้าขอยุติ' }[value] || value || 'ไม่พบหลักฐาน')
export const sourceLabel = (value) => ({ SHEET: 'ข้อมูลนำเข้า', PERSON: 'ดำเนินการในระบบ', MIXED: 'หลายแหล่งข้อมูล', UNKNOWN: 'ไม่พบหลักฐาน' }[value] || value || '—')
export const thaiTime = (value) => {
  if (!value) return 'ไม่พบหลักฐาน'
  const raw = String(value).replace(' ', 'T')
  const aware = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)
  const normalized = aware ? raw : `${raw.length === 10 ? `${raw}T00:00:00` : raw}+07:00`
  const instant = new Date(normalized)
  return Number.isNaN(instant.getTime()) ? 'ไม่พบหลักฐาน'
    : new Intl.DateTimeFormat('th-TH', { timeZone: 'Asia/Bangkok', dateStyle: 'medium', timeStyle: 'short' }).format(instant)
}

// A request owns its result. Navigation cannot display the previous customer's file.
export function useHistoryRead(key, read) {
  const [state, setState] = useState({})
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let active = true
    setState({ key, loading: true })
    read().then((data) => { if (active) setState({ key, data }) })
      .catch((error) => { if (active) setState({ key, problem: error?.problem || { code: 'request_failed', message_th: 'โหลดข้อมูลไม่สำเร็จ' } }) })
    return () => { active = false }
  }, [key, retry]) // read is deliberately represented by the complete request key.
  return { ...(state.key === key ? state : { loading: true }), retry: () => setRetry((n) => n + 1) }
}

export function useHistoryScroll(data, location) {
  useEffect(() => {
    const y = location.state?.restoreScroll
    if (!data || typeof y !== 'number') return undefined
    const frame = requestAnimationFrame(() => window.scrollTo({ top: y }))
    return () => cancelAnimationFrame(frame)
  }, [data, location.key, location.state])
}

export function Terminated() {
  useCrumb('group.system', 'nav.terminated')
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  const query = params.toString()
  const { data, problem, loading, retry } = useHistoryRead(query, () => api.terminated({ ...Object.fromEntries(params), history: true }))
  useHistoryScroll(data, location)
  const [actors, setActors] = useState([])
  const origin = location.state?.origin
  const back = origin?.to?.startsWith('/') && !origin.to.startsWith('//') ? origin : null
  useEffect(() => { if (data?.meta?.actors) setActors(data.meta.actors) }, [data])
  const update = (name, value) => {
    const next = new URLSearchParams(params)
    value ? next.set(name, value) : next.delete(name)
    if (name !== 'page') next.delete('page')
    setParams(next, { replace: true })
  }
  const page = Number(params.get('page') || 1)
  return <div className="stack">
    {back ? <Link className="scr-meta" to={back.to} state={{ ...back.state, restoreScroll: back.scrollY }}>← กลับหน้าเคส</Link> : null}
    <div className="lensbar"><h1 className="lensbar__title">สัญญาที่ยุติ</h1><span className="lensbar__meta">{data ? `${data.meta.total} รายการประวัติ` : ''}</span></div>
    <ActionLogNav />
    <p className="scr-meta">ค้นหาเหตุผลและเปิดข้อมูลเคสที่เก็บไว้ย้อนหลัง • ไม่รวมการชำระครบตามปกติ</p>
    <section className="card">
      <form className="history-filters" onSubmit={(e) => e.preventDefault()}>
        <label>รหัสลูกค้า<input className="field" value={params.get('customer_uid') || ''} onChange={(e) => update('customer_uid', e.target.value)} /></label>
        <label>ค้นหาลูกค้า / VOLT ID / เลขลูกค้า<input className="field" type="search" aria-label="ค้นหาลูกค้า / เลขลูกค้า" value={params.get('q') || ''} onChange={(e) => update('q', e.target.value)} /></label>
        <label>ตั้งแต่วันที่ยุติ<input className="field" type="date" value={params.get('since') || ''} onChange={(e) => update('since', e.target.value)} /></label>
        <label>ถึงวันที่ยุติ<input className="field" type="date" value={params.get('until') || ''} onChange={(e) => update('until', e.target.value)} /></label>
        <label>สาเหตุ<select className="field" value={params.get('cause') || ''} onChange={(e) => update('cause', e.target.value)}><option value="">ทั้งหมด</option>{['DEFAULT', 'CUSTOMER_REQUEST'].map((c) => <option key={c} value={c}>{causeLabel(c)}</option>)}</select></label>
        <label>ผู้ดำเนินการ<select className="field" value={params.get('actor') || ''} onChange={(e) => update('actor', e.target.value)}><option value="">ทั้งหมด</option>{actors.map((c) => <option key={c}>{c}</option>)}</select></label>
        <label>แหล่งข้อมูล<select className="field" value={params.get('source') || ''} onChange={(e) => update('source', e.target.value)}><option value="">ทั้งหมด</option>{['PERSON', 'SHEET', 'MIXED', 'UNKNOWN'].map((c) => <option key={c} value={c}>{sourceLabel(c)}</option>)}</select></label>
        <button className="btn btn--sm" type="button" onClick={() => setParams({})}>ล้างตัวกรอง</button>
      </form>
      {loading ? <p className="history-state" role="status">กำลังโหลดสัญญาที่ยุติ…</p> : problem ? <LoadError problem={problem} onRetry={retry} /> : data ? <>
        <DataTable caption="สัญญาที่ยุติ" minWidth={1120} rows={data.entries} getKey={(r) => r.archive_uid} empty="ไม่พบสัญญาที่ยุติที่ตรงกับตัวกรอง" columns={[
          { key: 'name', label: 'ลูกค้า', render: (r) => <><strong>{r.customer_name}</strong><div className="scr-meta">{r.volt_id || r.customer_no || r.customer_uid}</div></> },
          { key: 'terminated_on', label: 'วันที่ยุติ', render: (r) => r.terminated_on ? date(r.terminated_on) : 'ไม่พบหลักฐาน' },
          { key: 'actor', label: 'ผู้ดำเนินการ', render: (r) => r.actor || 'ไม่พบหลักฐาน' },
          { key: 'causes', label: 'สาเหตุ', render: (r) => (r.causes || []).map(causeLabel).join(', ') || 'ไม่พบหลักฐาน' },
          { key: 'reason', label: 'เหตุผล', render: (r) => <div className="history-reason">{r.reason || 'ไม่พบเหตุผลที่บันทึกไว้'}</div> },
          { key: 'source', label: 'แหล่งข้อมูล', render: (r) => sourceLabel(r.source) },
          { key: 'open', label: 'เคสย้อนหลัง', render: (r) => <Link className="btn btn--sm" to={`/audit/terminated/${r.archive_uid}`} state={{ origin: { to: location.pathname + location.search, scrollY: window.scrollY, state: location.state } }} aria-label={`ดูเคสย้อนหลัง ${r.customer_name}`}>ดูเคสย้อนหลัง</Link> },
        ]} />
        <div className="history-pagination"><button className="btn btn--sm" disabled={page <= 1} onClick={() => update('page', String(page - 1))}>ก่อนหน้า</button><span>หน้า {page} / {Math.max(1, Math.ceil(data.meta.total / 50))}</span><button className="btn btn--sm" disabled={page * 50 >= data.meta.total} onClick={() => update('page', String(page + 1))}>ถัดไป</button></div>
      </> : null}
    </section>
  </div>
}

const labels = { state: 'สถานะ', occurred_at: 'เวลาติดต่อ', officer_uid: 'ผู้ติดต่อ', responsible_team: 'ทีมรับผิดชอบ', ticket_status: 'สถานะตั๋ว', deadline: 'กำหนดเสร็จ', closed_by: 'ผู้ปิดตั๋ว', resolution_note: 'ผลการแก้ไข', created_by: 'ผู้บันทึก', created_on: 'วันที่บันทึก', fee_clock_note_th: 'การพักค่าปรับ', penalty: 'ค่าปรับ', amount_paid: 'ชำระแล้ว', amount_outstanding: 'ยอดคงเหลือ', invoice_uid: 'ใบแจ้งหนี้', matched: 'การจับคู่', invoice_state: 'สถานะใบแจ้งหนี้', invoice_kind: 'ประเภทใบแจ้งหนี้', receipt_no: 'เลขใบเสร็จ', note_en: 'หมายเหตุ (อังกฤษ)', termination: 'การยุติ', strategy: 'วิธีเรียกคืน', resolved_by: 'ผู้ปิดงาน', resolved_on: 'วันที่ปิดงาน', result_code: 'ผลติดต่อ', summary: 'รายละเอียด', ticket_ref: 'เลขตั๋ว', opened_by: 'ผู้เปิดตั๋ว', promise_uid: 'สัญญาชำระ', collection_amount: 'ยอดติดตาม', ref: 'เลขอ้างอิง', reference: 'เลขอ้างอิง', amount_total: 'ยอดรวม', amount_due: 'ยอดค้าง', due_on: 'วันครบกำหนด', month: 'เดือน', cell: 'ข้อมูลนำเข้า', payment_status: 'สถานะชำระ', fee_state: 'สถานะค่าธรรมเนียม', period_no: 'งวด', due_amount: 'ยอดงวด', paid_amount: 'ชำระแล้ว', uid: 'เลขอ้างอิง', contract_uid: 'สัญญา', customer_uid: 'ลูกค้า', product: 'ผลิตภัณฑ์', entity: 'บริษัท', status: 'สถานะ', principal: 'เงินต้น', term_months: 'จำนวนงวด', first_due: 'วันเริ่มชำระ', paid_through: 'ชำระถึงงวด', pmt: 'ค่างวด', contract_end: 'วันสิ้นสุด', comment_th: 'หมายเหตุ', instalments_overdue: 'ยอดค้าง', penalty_accrued_unbilled: 'ค่าปรับ', oldest_dpd: 'วันค้าง', invoice_no: 'เลขใบแจ้งหนี้', doc_no: 'เลขเอกสาร', peak_number: 'เลขเอกสาร PEAK', amount: 'จำนวนเงิน', balance: 'ยอดคงเหลือ', outstanding: 'ยอดค้าง', due_date: 'วันครบกำหนด', issued_on: 'วันที่ออก', paid_on: 'วันที่รับเงิน', receipt_date: 'วันที่รับเงิน', note: 'หมายเหตุ', reason: 'เหตุผล', reason_th: 'เหตุผล', by: 'ผู้ดำเนินการ', on: 'วันที่', at: 'เวลา', kind: 'กิจกรรม', result: 'ผลลัพธ์', outcome: 'ผลลัพธ์', channel: 'ช่องทาง', ticket: 'ตั๋วปัญหา', title: 'หัวข้อ', description: 'รายละเอียด', opened_on: 'วันที่เปิด', closed_on: 'วันที่ปิด', created_at: 'วันที่สร้าง', type: 'ประเภท', category: 'ประเภท', note_th: 'หมายเหตุ', promised_amount: 'ยอดสัญญาชำระ', promise_date: 'วันนัดชำระ', peak_state: 'สถานะ PEAK', allocated_amount: 'จัดสรรแล้ว', received_on: 'วันที่รับเงิน', instrument: 'วิธีดำเนินการ', origin: 'แหล่งข้อมูล', cause: 'สาเหตุ' }
function Fields({ value }) {
  const { t } = usePrefs()
  const word = (key, code) => t(key) === key ? String(code) : t(key)
  const show = (key, v) => key === 'cause' ? causeLabel(v) : key === 'origin' ? sourceLabel(v) : key === 'kind' ? word(`case.event.${v}`, v) : key === 'product' ? word(`record.contractType.${v}`, v) : key === 'status' || key === 'state' ? word(`pay.${v}`, v) : key === 'instrument' ? ({ TERMINATE_ACT: 'ยุติสัญญาจากหน้าเคส', WRITE_OFF: 'ตัดจำหน่าย', RECOVERY_FULL: 'เรียกคืนครบ', RECOVERY_PARTIAL: 'เรียกคืนบางส่วน', SHEET_CATEGORY: 'ประเภทจากข้อมูลนำเข้า' }[v] || String(v)) : String(v)
  return <dl className="history-fields">{Object.entries(value || {}).filter(([k, v]) => labels[k] && v != null && typeof v !== 'object').map(([k, v]) => <div key={k}><dt>{labels[k]}</dt><dd>{show(k, v)}</dd></div>)}</dl>
}
function ReadRows({ title, rows }) {
  return <section className="card"><header className="card__head"><h2>{title}</h2><span className="scr-meta">{rows.length} รายการ</span></header>{rows.length ? rows.map((r, i) => <article className="history-record" key={r.uid || i}><Fields value={r} /></article>) : <p className="history-state">ไม่มีข้อมูลที่บันทึกไว้</p>}</section>
}

export function ArchivedCase() {
  useCrumb('group.system', 'nav.terminated')
  const { uid } = useParams()
  const location = useLocation()
  const { data, problem, loading, retry } = useHistoryRead(uid, () => api.terminatedCase(uid))
  const [tab, setTab] = useState('contracts')
  useEffect(() => setTab('contracts'), [uid])
  const origin = location.state?.origin
  const back = origin?.to?.startsWith('/') && !origin.to.startsWith('//') ? origin.to : '/audit/terminated'
  return <div className="stack archive-case">
    <Link className="scr-meta" to={back} state={{ ...origin?.state, restoreScroll: origin?.scrollY }}>← {back === '/audit' || back.startsWith('/audit?') ? 'กลับบันทึกการใช้งาน' : 'กลับสัญญาที่ยุติ'}</Link>
    <ActionLogNav />
    {loading ? <p role="status">กำลังโหลดเคสย้อนหลัง…</p> : problem ? <LoadError problem={problem} onRetry={retry} /> : data ? <>
      <section className="card"><header className="card__head"><h1>{data.customer_name}</h1><span className="pill pill--done">อ่านอย่างเดียว</span></header>
        <div className="history-record"><p className="scr-meta">{data.volt_id || data.customer_no} · เก็บข้อมูล {thaiTime(data.captured_at)}</p>
          <p>{data.capture_kind === 'BACKFILL' ? 'ข้อมูลเก่า: snapshot เก็บ ณ วัน backfill ไม่ใช่ข้อมูล ณ วันยุติ' : data.capture_kind === 'IMPORT' ? 'ข้อมูลที่เก็บจากการนำเข้า ณ เวลาที่แสดงข้างต้น' : 'ข้อมูลที่บันทึกไว้เมื่อยุติสำเร็จ'}</p>
          <Fields value={{ on: data.terminated_on || 'ไม่พบหลักฐาน', by: data.actor || 'ไม่พบหลักฐาน', origin: data.source }} />
          <h2>เหตุผลการยุติ</h2><p className="history-reason">{data.reason || 'ไม่พบเหตุผลที่บันทึกไว้'}</p>
          {(data.terminations || []).map((r) => <Fields key={r.contract_uid} value={r} />)}
        </div>
      </section>
      <nav className="history-tabs" aria-label="ข้อมูลเคสย้อนหลัง">{[['contracts', 'สัญญา'], ['invoices', 'ใบแจ้งหนี้'], ['receipts', 'เงินเข้า'], ['history', 'ประวัติ'], ['issues', 'ตั๋วปัญหา'], ['recovery_cases', 'งานเรียกคืน']].map(([key, label]) => <button className={`btn btn--sm ${key === tab ? 'btn--primary' : ''}`} type="button" aria-pressed={key === tab} key={key} onClick={() => setTab(key)}>{label}</button>)}</nav>
      {tab === 'contracts' && data.snapshot?.payment_summary ? <section className="card"><header className="card__head"><h2>งวดชำระ ณ วันที่เก็บข้อมูล</h2></header><CycleGrid summary={data.snapshot.payment_summary} invoices={data.snapshot.invoices || []} /></section> : null}
      {tab === 'history' ? <><ReadRows title="กิจกรรมในเคส" rows={(data.snapshot?.events || []).map((event) => { const term = event.kind === 'CONTRACT_TERMINATED' ? data.terminations?.find((r) => r.contract_uid === event.contract_uid || (!event.contract_uid && data.terminations.length === 1)) : null; return term ? { ...event, ...term, reason: term.reason || term.reason_th || term.reason_en || 'ไม่พบหลักฐาน', on: term.on || 'ไม่พบหลักฐาน' } : event })} /><ReadRows title="ผลติดต่อ" rows={data.snapshot?.contact_log || []} /><ReadRows title="สัญญาชำระ" rows={data.snapshot?.ptps || []} /></> : <ReadRows title={{ contracts: 'สัญญาที่บันทึกไว้', invoices: 'ใบแจ้งหนี้ที่บันทึกไว้', receipts: 'เงินเข้าที่บันทึกไว้', issues: 'ตั๋วปัญหาที่บันทึกไว้', recovery_cases: 'งานเรียกคืนที่บันทึกไว้' }[tab]} rows={data.snapshot?.[tab] || []} />}
    </> : null}
  </div>
}

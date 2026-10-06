import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useCrumb } from '../lib/crumb.jsx'
import { DataTable } from '../components/DataTable.jsx'
import { StatusPill } from '../components/StatusIcon.jsx'
import { auditStatus } from '../lib/status.js'
import { LoadError } from '../components/Problem.jsx'
import { thaiTime, useHistoryRead, useHistoryScroll } from './Terminated.jsx'
import { ActionLogNav } from '../components/ActionLogNav.jsx'

// Calendar dates on this screen mean Bangkok days, with an exclusive upper bound.
export function auditDateRange(since, until) {
  const params = {}
  if (since) params.since = `${since}T00:00:00+07:00`
  if (until) {
    const end = new Date(`${until}T00:00:00+07:00`).getTime()
    params.until = Number.isFinite(end) ? new Date(end + 86400000).toISOString() : until
  }
  return params
}

function AuditDetail({ entry, onClose, origin }) {
  const dialog = useRef(null)
  useEffect(() => { dialog.current?.showModal(); return () => dialog.current?.close() }, [])
  const d = entry.display || {}
  return <dialog ref={dialog} className="history-dialog" onCancel={onClose} onClose={onClose} aria-labelledby="audit-detail-title">
    <div className="card__head"><h2 id="audit-detail-title">รายละเอียดกิจกรรม</h2><button className="btn btn--sm" autoFocus onClick={onClose}>ปิด</button></div>
    <div className="history-record"><dl className="history-fields">
      {[['เวลา (ไทย)', thaiTime(entry.at)], ['ผู้ดำเนินการ', entry.actor_claimed || '—'], ['กิจกรรม', d.activity_th || entry.act || `${entry.verb} ${entry.route_template}`], ['ลูกค้า', d.customer_name || 'ไม่พบข้อมูลลูกค้า'], ['เป้าหมาย', entry.subject_uid || entry.subject_type || '—'], ['ผลลัพธ์', entry.outcome === 'OK' ? 'สำเร็จ' : 'ไม่สำเร็จ'], ['เหตุผลที่บันทึกไว้', d.reason || 'ไม่พบเหตุผลที่มีหลักฐาน'], ['เลขอ้างอิง', entry.request_id], ['ข้อผิดพลาด', entry.error_code || '—']].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
    </dl>
    {d.case_url ? <Link className="btn btn--sm" to={d.case_url.replace(/^\/terminated\//, '/audit/terminated/')} state={{ origin }}>เปิดเคส{d.case_url.includes('/terminated/') ? 'ย้อนหลัง' : ''}</Link> : <p className="scr-meta">เปิดเคสไม่ได้ — เก็บเลขอ้างอิงไว้สำหรับตรวจสอบ</p>}
    <details><summary>รายละเอียดและ hash สำหรับตรวจสอบ</summary><pre className="history-json">{JSON.stringify({ detail: entry.detail, hash: entry.hash, prev_hash: entry.prev_hash }, null, 2)}</pre></details>
    </div>
  </dialog>
}

export function Audit() {
  const { t } = usePrefs()
  useCrumb('group.system', 'nav.audit')
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  const query = params.toString()
  const filters = { ...Object.fromEntries(params), ...auditDateRange(params.get('since'), params.get('until')) }
  const { data, problem, loading, retry } = useHistoryRead(query, () => api.audit(filters))
  useHistoryScroll(data, location)
  const [verify, setVerify] = useState(null)
  const [selected, setSelected] = useState(null)
  const [options, setOptions] = useState({ actors: [], acts: [], act_labels: {} })
  useEffect(() => { if (data?.meta) setOptions(data.meta) }, [data])
  useEffect(() => setSelected(null), [query])
  const update = (name, value) => {
    const next = new URLSearchParams(params)
    value ? next.set(name, value) : next.delete(name)
    if (name !== 'before_seq') next.delete('before_seq')
    setParams(next, { replace: true })
  }
  return <div className="stack">
    <div className="lensbar"><h1 className="lensbar__title">{t('nav.audit')}</h1><span className="spacer" /><button type="button" className="btn btn--sm" onClick={() => api.auditVerify().then(setVerify).catch(() => setVerify({ ok: false }))}>{t('audit.verify')}</button></div>
    <ActionLogNav />
    {verify ? <span><StatusPill kind={verify.ok || verify.valid ? 'done' : 'problem'}>{verify.ok || verify.valid ? t('audit.chainOk') : t('audit.chainBad')}</StatusPill></span> : null}
    <section className="card">
      <form className="history-filters" onSubmit={(e) => e.preventDefault()}>
        <label>ค้นหาลูกค้า / เลขอ้างอิง<input type="search" className="field" value={params.get('q') || ''} onChange={(e) => update('q', e.target.value)} /></label>
        <label>ตั้งแต่วันที่ (ไทย)<input type="date" className="field" value={params.get('since') || ''} onChange={(e) => update('since', e.target.value)} /></label>
        <label>ถึงวันที่ (ไทย)<input type="date" className="field" value={params.get('until') || ''} onChange={(e) => update('until', e.target.value)} /></label>
        <label>{t('audit.actor')}<select className="field" value={params.get('actor') || ''} onChange={(e) => update('actor', e.target.value)}><option value="">{t('audit.actorAll')}</option>{options.actors.map((a) => <option key={a}>{a}</option>)}</select></label>
        <label>{t('audit.act')}<select className="field" value={params.get('act') || ''} onChange={(e) => update('act', e.target.value)}><option value="">{t('audit.actAll')}</option>{options.acts.map((a) => <option key={a} value={a}>{options.act_labels?.[a] || a}</option>)}</select></label>
        <label>ผลลัพธ์<select className="field" value={params.get('outcome') || ''} onChange={(e) => update('outcome', e.target.value)}><option value="">ทั้งหมด</option><option value="OK">สำเร็จ</option><option value="REFUSED">ไม่สำเร็จ</option></select></label>
        <button className="btn btn--sm" type="button" onClick={() => setParams({})}>ล้างตัวกรอง</button>
      </form>
      {loading ? <p role="status" className="history-state">กำลังโหลดบันทึกการใช้งาน…</p> : problem ? <LoadError problem={problem} onRetry={retry} /> : data ? <>
        <DataTable caption={t('nav.audit')} minWidth={900} rows={data.entries} getKey={(r) => r.seq} empty={t('audit.empty')} columns={[
          { key: 'at', label: 'เวลา (ไทย)', render: (r) => thaiTime(r.at) },
          { key: 'actor', label: t('audit.actor'), render: (r) => r.actor_claimed || '—' },
          { key: 'act', label: t('audit.act'), render: (r) => <button className="btn btn--sm" onClick={() => setSelected(r)}>{r.display?.activity_th || r.act || `${r.verb} ${r.route_template}`}</button> },
          { key: 'target', label: 'ลูกค้า / เป้าหมาย', render: (r) => <>{r.display?.customer_name || r.subject_uid || r.subject_type || '—'}<div className="scr-meta">{r.display?.customer_no || r.request_id}</div></> },
          { key: 'result', label: t('audit.result'), render: (r) => <><StatusPill kind={auditStatus(r.outcome).kind}>{t(auditStatus(r.outcome).key)}</StatusPill>{r.error_code ? <span className="scr-meta"> {r.error_code}</span> : null}</> },
        ]} />
        <div className="history-pagination">{params.get('before_seq') ? <button className="btn btn--sm" onClick={() => update('before_seq', '')}>กลับรายการล่าสุด</button> : null}{data.meta.next_before_seq ? <button className="btn btn--sm" onClick={() => update('before_seq', String(data.meta.next_before_seq))}>{t('audit.loadOlder')}</button> : null}<span className="scr-meta">{t('audit.note')}</span></div>
      </> : null}
    </section>
    {selected ? <AuditDetail entry={selected} onClose={() => setSelected(null)} origin={{ to: location.pathname + location.search, scrollY: window.scrollY, label: 'nav.audit' }} /> : null}
  </div>
}

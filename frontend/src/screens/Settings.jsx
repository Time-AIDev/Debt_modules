import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { useIdentity, atLeast, roleLabel } from '../lib/identity.jsx'
import { useCrumb } from '../lib/crumb.jsx'
import { StatusPill, NeutralChip } from '../components/StatusIcon.jsx'
import { settingStatus, statusOf } from '../lib/status.js'
import { Drawer } from '../components/Drawer.jsx'
import { Problem, LoadError } from '../components/Problem.jsx'
import { useToast } from '../components/Toast.jsx'

/**
 * ตั้งค่า: the register in the design's three columns (setting · officer view ·
 * manager view). The label is the debt team's plain name; the served key stays
 * one hover away and on the wire untouched — the PUT body is the key verbatim.
 * Locks and roles come from the server, so the manager column's state is served,
 * never guessed: it is editable only when the response says editable for this role.
 */
export function Settings() {
  const { t, lang } = usePrefs()
  const identity = useIdentity()
  const toast = useToast()
  useCrumb('group.system', 'nav.settings')

  const [config, setConfig] = useState(null)
  const [bandSets, setBandSets] = useState(null)
  const [dictionaries, setDictionaries] = useState(null)
  const [users, setUsers] = useState(null)
  const [usersProblem, setUsersProblem] = useState(null)
  const [authOff, setAuthOff] = useState(false)
  const [problem, setProblem] = useState(null)
  const [draft, setDraft] = useState({})
  const [busy, setBusy] = useState(false)
  const [writeProblem, setWriteProblem] = useState(null)
  const [inviteOpen, setInviteOpen] = useState(false)
  const [invite, setInvite] = useState({ email: '', role: 'OFFICER', officer: '' })

  const load = useCallback(() => {
    setProblem(null)
    Promise.all([api.config(), api.bandSets(), api.dictionaries()])
      .then(([c, b, d]) => { setConfig(c); setBandSets(b); setDictionaries(d) })
      .catch((e) => setProblem(e?.problem || { code: 'request_failed' }))
    api.authConfig().then((cfg) => {
      setAuthOff(cfg?.mode !== 'on')
      if (cfg?.mode === 'on') {
        api.authUsers().then(setUsers).catch((e) => setUsersProblem(e?.problem || { code: 'request_failed' }))
      }
    }).catch(() => setUsersProblem({ code: 'request_failed' }))
  }, [])
  useEffect(() => { load() }, [load])

  async function save(key) {
    setBusy(true)
    setWriteProblem(null)
    try {
      await api.putConfig({ [key]: draft[key] })
      toast(t('settings.saved'))
      setDraft((d) => { const next = { ...d }; delete next[key]; return next })
      load()
    } catch (e) {
      setWriteProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  async function activateBandSet(code) {
    setBusy(true)
    setWriteProblem(null)
    try {
      await api.reactivateBandSet(code)
      toast(t('settings.bandActivated'))
      load()
    } catch (e) {
      setWriteProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  async function inviteUser() {
    setBusy(true)
    setWriteProblem(null)
    try {
      await api.authInviteUser(invite)
      toast(t('settings.invited'))
      setInviteOpen(false)
      setInvite({ email: '', role: 'OFFICER', officer: '' })
      api.authUsers().then(setUsers).catch(() => {})
    } catch (e) {
      setWriteProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  async function disableUser(uid) {
    setBusy(true)
    setWriteProblem(null)
    try {
      await api.authDisableUser(uid)
      toast(t('settings.disabled'))
      api.authUsers().then(setUsers).catch(() => {})
    } catch (e) {
      setWriteProblem(e?.problem || { code: 'request_failed' })
    } finally {
      setBusy(false)
    }
  }

  if (problem) return <LoadError problem={problem} onRetry={load} />
  if (!config) return <p className="empty">{t('common.loading')}</p>

  const rows = Object.entries(config.config || {})
  const grantable = users?.grantable_roles || []
  const canManage = atLeast('MANAGER')
  const officerCol = canManage ? t('settings.colOfficerRead') : t('settings.colOfficerYou')
  const managerCol = canManage ? t('settings.colManagerYou') : t('settings.colManagerOther')

  // The invite body needs the registry officer the account acts as (POST /v1/auth/users
  // refuses without it — /v1/officers is the only source of a valid uid), and the rank
  // rule is the served grantable_roles: an officer above the actor's rank is never offered.
  const inviteOfficers = (identity.roster || [])
    .filter((o) => !grantable.length || grantable.includes(o.role))
    .map((o) => ({ uid: o.uid, role: o.role, label: (lang === 'en' ? o.display_name_en : o.display_name_th) || o.uid }))

  function openInvite() {
    setWriteProblem(null)
    setInvite({ email: '', role: 'OFFICER', officer: inviteOfficers[0]?.uid || '' })
    setInviteOpen(true)
  }

  function changeOfficer(uid) {
    const hit = inviteOfficers.find((o) => o.uid === uid)
    const nextRole = hit && grantable.includes(hit.role) ? hit.role : invite.role
    setInvite((i) => ({ ...i, officer: uid, role: nextRole }))
  }

  return (
    <div className="stack">
      <section className="card">
        <header className="setHead">
          <h1>{t('settings.register')}</h1>
          <p>{t('settings.registerNote')}</p>
        </header>
        <div className="setgrid">
          <div className="setgrid__head" aria-hidden="true">
            <span>{t('settings.colItem')}</span>
            <span>{officerCol}</span>
            <span>{managerCol}</span>
          </div>
          {rows.map(([key, row]) => {
            const locked = row.lock === 'locked' || row.locked
            const editableNow = row.editable === true
            const value = draft[key] !== undefined ? draft[key] : row.value
            const translated = t(`settings.key.${key}`)
            const label = translated === `settings.key.${key}` ? key : translated
            const lock = settingStatus(row)
            const note = locked ? t('settings.needRuling')
              : editableNow ? t('settings.youCanEdit')
              : row.editable_by === 'OWNER' ? t('settings.ownerOnly')
              : t('settings.managerOnly')
            const dirty = draft[key] !== undefined && draft[key] !== row.value
            return (
              <div key={key} className="setrow">
                <div className="setrow__main">
                  <span className="setrow__label">
                    <span className="setrow__labelText" data-key={key} tabIndex={0}>
                      {label}
                      <span className="sr-only">{t('settings.rawKey', { key })}</span>
                    </span>
                    <StatusPill kind={lock.kind}>{t(lock.key)}</StatusPill>
                  </span>
                  <span className="setrow__note">{lang === 'en' ? row.note_en : row.note_th}</span>
                  <span className="setrow__meta">{t('settings.owner')} {row.owner || '—'}{row.changed_by ? ` · ${row.changed_by}` : ''}</span>
                </div>
                <div className={`setcell${canManage ? '' : ' setcell--on'}`}>
                  <p className="setcell__value num">{row.value ?? '—'}</p>
                  <p className="setcell__note">{t('settings.readOnly')}</p>
                </div>
                <div className={`setcell${canManage ? ' setcell--on' : ''}`}>
                  <div className="setcell__edit">
                    <input
                      className={`field${editableNow ? '' : ' field--locked'}`}
                      value={value ?? ''}
                      disabled={!editableNow}
                      aria-label={label}
                      onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
                    />
                    {editableNow && dirty ? (
                      <button type="button" className="btn btn--sm" disabled={busy} onClick={() => save(key)}>
                        {t('common.save')}
                      </button>
                    ) : null}
                  </div>
                  <p className="setcell__note">{note}</p>
                </div>
              </div>
            )
          })}
        </div>
        {writeProblem ? <div className="card__note"><Problem problem={writeProblem} /></div> : null}
      </section>

      <section className="card">
        <header className="card__head">
          <h2>{t('settings.users')}</h2>
          <span className="spacer" />
          <button type="button" className="btn btn--sm" disabled={!atLeast('MANAGER')}
                  title={atLeast('MANAGER') ? undefined : t('settings.managerOnly')} onClick={openInvite}>
            {t('settings.invite')}
          </button>
        </header>
        <div className="card__body">
          {authOff ? <p className="empty" style={{ padding: 0 }}>{t('settings.authOff')}</p> : null}
          {usersProblem ? <Problem problem={usersProblem} /> : null}
          {users ? (
            <ul className="rows">
              {(users.users || []).map((u) => (
                <li key={u.uid} className="rows__row">
                  <span className="rows__main">
                    <span className="user__name">{u.display_name || u.email || u.uid}</span>
                    <span className="scr-meta">{u.email || ''} {u.caseload !== null && u.caseload !== undefined ? `· ${t('settings.caseload')} ${u.caseload}` : ''}</span>
                  </span>
                  <NeutralChip title={u.role}>{roleLabel(u.role, lang)}</NeutralChip>
                  <button type="button" className="btn btn--sm btn--danger" disabled={busy || u.disabled}
                          onClick={() => disableUser(u.uid)}>
                    {t('settings.disable')}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        <p className="card__note">{users?.note_th && lang === 'th' ? users.note_th : users?.note_en || t('settings.usersNote')}</p>
      </section>

      <div className="grid2">
        <section className="card">
          <header className="card__head"><h2>{t('settings.bandSets')}</h2></header>
          <div className="card__body">
            <ul className="rows">
              {(bandSets?.band_sets || []).map((b) => (
                <li key={b.code} className="rows__row">
                  <span className="rows__main">{b.code}</span>
                  {b.active ? <StatusPill kind={statusOf('bandSet', 'ACTIVE').kind}>{t(statusOf('bandSet', 'ACTIVE').key)}</StatusPill> : (
                    <button type="button" className="btn btn--sm" disabled={busy} onClick={() => activateBandSet(b.code)}>
                      {t('settings.activate')}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </div>
          <p className="card__note">{lang === 'en' ? bandSets?.edit_refusal_en : bandSets?.edit_refusal_th}</p>
        </section>

        <section className="card">
          <header className="card__head"><h2>{t('settings.dictionaries')}</h2></header>
          <div className="card__body">
            <ul className="rows">
              {Object.entries(dictionaries?.dictionaries || {}).slice(0, 9).map(([name, values]) => (
                <li key={name} className="rows__row">
                  <span className="rows__main">{name}</span>
                  <span className="num">{values.filter((v) => v.active !== false).length}</span>
                </li>
              ))}
            </ul>
          </div>
          <p className="card__note">{t('settings.dictionariesNote')}</p>
        </section>
      </div>

      <Drawer
        open={inviteOpen}
        onClose={() => setInviteOpen(false)}
        title={t('settings.invite')}
        footer={(
          <>
            <button type="button" className="btn" onClick={() => setInviteOpen(false)}>{t('common.cancel')}</button>
            <button type="button" className="btn btn--primary" disabled={busy || !invite.email || !invite.officer} onClick={inviteUser}>
              {t('settings.inviteRun')}
            </button>
          </>
        )}
      >
        <label><span className="eyebrow">{t('settings.email')}<span className="req" aria-hidden="true">*</span></span>
          <input className="field" type="email" value={invite.email} aria-required="true" onChange={(e) => setInvite({ ...invite, email: e.target.value })} /></label>
        <label><span className="eyebrow">{t('settings.officer')}<span className="req" aria-hidden="true">*</span></span>
          <select className="field" value={invite.officer} aria-required="true" onChange={(e) => changeOfficer(e.target.value)}>
            <option value="">—</option>
            {inviteOfficers.map((o) => <option key={o.uid} value={o.uid}>{o.label}</option>)}
          </select>
          <span className="scr-meta">{t('settings.officerNote')}</span></label>
        <label><span className="eyebrow">{t('settings.role')}</span>
          <select className="field" value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })}>
            {(grantable.length ? grantable : ['OFFICER']).map((r) => <option key={r} value={r}>{roleLabel(r, lang)}</option>)}
          </select></label>
        {writeProblem ? <Problem problem={writeProblem} /> : null}
        <p className="drawer__hint">{t('settings.inviteNote')}</p>
      </Drawer>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { usePrefs } from '../lib/prefs.jsx'
import { Drawer } from './Drawer.jsx'
import { Problem } from './Problem.jsx'

const CHANNEL_LABEL = { LINE: 'LINE', FACEBOOK: 'Facebook' }

export function socialUrl(channel, recipientId) {
  const id = encodeURIComponent(recipientId || '')
  return channel === 'FACEBOOK' ? `https://m.me/${id}` : `https://line.me/R/ti/p/~${id}`
}

export function SocialComposer({ open, onClose, channel, recipientId }) {
  const { t } = usePrefs()
  const label = CHANNEL_LABEL[channel] || channel
  const [templates, setTemplates] = useState([])
  const [selected, setSelected] = useState('')
  const [message, setMessage] = useState('')
  const [templateName, setTemplateName] = useState('')
  const [copied, setCopied] = useState(false)
  const [problem, setProblem] = useState(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open || !channel) return undefined
    let alive = true
    setTemplates([])
    setSelected('')
    setMessage('')
    setTemplateName('')
    setCopied(false)
    setProblem(null)
    api.messageTemplates({ channel })
      .then((data) => { if (alive) setTemplates(data?.items || []) })
      .catch((error) => { if (alive) setProblem(error?.problem || { code: 'request_failed' }) })
    return () => { alive = false }
  }, [open, channel])

  async function copy() {
    if (!message.trim()) return
    try {
      await navigator.clipboard.writeText(message)
      setCopied(true)
      setProblem(null)
    } catch {
      setProblem({ code: 'copy_failed', message_th: t('social.copyFailed') })
    }
  }

  async function saveTemplate() {
    if (!templateName.trim() || !message.trim() || saving) return
    setSaving(true)
    setProblem(null)
    try {
      await api.createMessageTemplate({ channel, name: templateName.trim(), body: message.trim() })
      const data = await api.messageTemplates({ channel })
      setTemplates(data?.items || [])
      setTemplateName('')
    } catch (error) {
      setProblem(error?.problem || { code: 'request_failed' })
    } finally {
      setSaving(false)
    }
  }

  const title = t('social.title', { channel: label })
  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={title}
      headAction={<button type="button" className="btn btn--sm" disabled={!message.trim()} onClick={copy}>{t('social.copy')}</button>}
      footer={copied ? (
        <button type="button" className="btn btn--primary" onClick={() => window.open(socialUrl(channel, recipientId), '_blank', 'noopener,noreferrer')}>
          {t('social.open', { channel: label })}
        </button>
      ) : null}
    >
      {problem ? <Problem problem={problem} /> : null}
      <label className="field-label" htmlFor="social-template">{t('social.template')}</label>
      <select
        id="social-template"
        className="field"
        value={selected}
        onChange={(event) => {
          const uid = event.target.value
          setSelected(uid)
          const template = templates.find((item) => item.uid === uid)
          setMessage(template?.body || '')
          setCopied(false)
        }}
      >
        <option value="">{t('social.newMessage')}</option>
        {templates.map((template) => <option key={template.uid} value={template.uid}>{template.name}</option>)}
      </select>
      <label className="field-label" htmlFor="social-message">{t('social.message')}</label>
      <textarea id="social-message" className="field" rows="8" value={message}
                onChange={(event) => { setMessage(event.target.value); setCopied(false) }} />
      <div className="drawer__grid2">
        <input className="field" aria-label={t('social.templateName')} value={templateName}
               placeholder={t('social.templateName')} onChange={(event) => setTemplateName(event.target.value)} />
        <button type="button" className="btn" disabled={!templateName.trim() || !message.trim() || saving}
                onClick={saveTemplate}>{t('social.saveTemplate')}</button>
      </div>
    </Drawer>
  )
}

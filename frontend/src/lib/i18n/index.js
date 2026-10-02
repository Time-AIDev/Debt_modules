import th from './th.js'
import en from './en.js'

export const DICTS = { th, en }
export const LANGS = ['th', 'en']

/** TH is the source table; EN must carry every key (enforced by i18n.test). */
export function translate(lang, key, vars) {
  const table = lang === 'en' ? en : th
  let s = table[key]
  if (s === undefined) s = th[key]
  if (s === undefined) return key
  if (vars) {
    for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(String(v))
  }
  return s
}

/**
 * Served API sentences carry `_th`/`_en` twins. EN screens must never fall back to
 * the Thai twin (the `english-*` rule the old suite pinned), so the fallback order
 * differs per language.
 */
export function served(obj, base, lang) {
  if (!obj) return ''
  if (lang === 'en') return obj[`${base}_en`] ?? obj[base] ?? ''
  return obj[`${base}_th`] ?? obj[base] ?? obj[`${base}_en`] ?? ''
}

/** Localize a dictionary array served as `{code,label_th,label_en}` or `[code,label]`. */
export function optionLabel(options, code, lang) {
  if (!Array.isArray(options)) return code || ''
  const hit = options.find((o) => (Array.isArray(o) ? o[0] : o.code) === code)
  if (!hit) return code || ''
  if (Array.isArray(hit)) return hit[1] || code
  return (lang === 'en' ? hit.label_en : hit.label_th) || hit.label || code
}

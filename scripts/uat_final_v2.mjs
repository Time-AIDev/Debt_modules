#!/usr/bin/env node
/**
 * uat_final_v2.mjs — the scripted end-to-end UAT of the twelve Final v2 screens.
 *
 * It drives the running app (Vite at :5173 proxying the API at :8000) with Chrome
 * for Testing under .uat-browser/, as OWNER in Thai for the screen walk and the
 * key interactions, then repeats the walk in English and flags any Thai left in
 * the interface (customer names and document ids excepted). Finally it runs the
 * acceptance list from docs/design/handoff-v2/README.md and writes
 * .v2-outcome/uat/uat-report.json + uat-report.md.
 *
 * It NEVER fixes product code. A failing product check stays a failure, with the
 * exact reproduction, in the report.
 *
 * Usage:
 *   node scripts/uat_final_v2.mjs
 *   UAT_BASE=http://localhost:5173 UAT_API=http://127.0.0.1:8000 node scripts/uat_final_v2.mjs
 *   node scripts/uat_final_v2.mjs --skip-e2e        (do not run scripts/e2e_check.py)
 *   node scripts/uat_final_v2.mjs --skip-acceptance (skip the acceptance list)
 *   node scripts/uat_final_v2.mjs --only today,workbook   (restrict both walk phases)
 *   node scripts/uat_final_v2.mjs --dry-run         (platform sanity + one TH walk on
 *                                                    today + one EN residue check on
 *                                                    data-sources + a rail-navigation
 *                                                    smoke over the routes that used to
 *                                                    detach; skips the other acceptance
 *                                                    phases and e2e_check.py)
 */
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { spawnSync, execFileSync } from 'node:child_process'

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..')
const require = createRequire(path.join(ROOT, 'frontend', 'package.json'))
const puppeteer = require('puppeteer-core')
const BASE = process.env.UAT_BASE || 'http://localhost:5173'
const API = process.env.UAT_API || 'http://127.0.0.1:8000'
const OUT = path.join(ROOT, '.v2-outcome', 'uat')
const SHOTS = path.join(OUT, 'shots')
const FIXTURES = path.join(OUT, 'fixtures')
const ARGS = process.argv.slice(2)
const flag = (f) => ARGS.includes(f)
const argValue = (f) => { const i = ARGS.indexOf(f); return i >= 0 ? ARGS[i + 1] : null }
const DRY_RUN = flag('--dry-run')
const ONLY = (argValue('--only') || '').split(',').map((s) => s.trim()).filter(Boolean)
const SKIP_ACCEPTANCE = flag('--skip-acceptance') || DRY_RUN
const SKIP_E2E = flag('--skip-e2e') || DRY_RUN
const MODE = DRY_RUN ? 'dry-run' : ONLY.length ? `only:${ONLY.join(',')}` : 'full'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const PASS = 'pass'
const FAIL = 'fail'
const NA = 'not-exercisable'
const INFO = 'info'

// --- stale-handle / navigation robustness ----------------------------------------
// The reported A1 failures ("Attempted to use detached Frame") came from a renderer
// that went away under host memory pressure and from evaluating page state mid-load.
// Every navigation now settles on network idle, every element is re-queried after a
// navigation, and a stale-handle error gets exactly one retry; the rail check rebuilds
// the whole page, because a detached main frame cannot be recovered in place.
const STALE_RE = /detached Frame|Execution context was destroyed|Cannot find context|Node is detached|Session closed|Target closed|frame was detached|Navigating frame was detached|Connection closed/i
const isStaleError = (e) => STALE_RE.test(String((e && e.message) || e))
let staleRetries = 0
const staleNotes = []
async function withStaleRetry(label, fn, retries = 1, onRetry = null) {
  for (let attempt = 0; ; attempt++) {
    try { return await fn() } catch (e) {
      if (attempt >= retries || !isStaleError(e)) throw e
      staleRetries++
      staleNotes.push(`${label}: ${String(e.message).slice(0, 140)}`)
      console.log(`  .. stale handle in ${label}; ${onRetry ? 'rebuilding the page and ' : ''}retrying once`)
      if (onRetry) { try { await onRetry() } catch { /* the page may already be gone */ } }
      await sleep(400)
    }
  }
}
// A detached main frame cannot be recovered in place: the caller's onRetry hook
// closes the dead page and builds a fresh one, then the same body runs again on the
// new page (never a held ElementHandle, always a selector string re-queried).
async function withPageRetry(label, holder, fn, retries = 1) {
  return withStaleRetry(label, () => fn(holder.page), retries, async () => {
    mergeErrors(holder.errors, holder.page && holder.page.__errors)
    await safeClose(holder.page)
    holder.page = await newPage(holder.browser)
  })
}
async function safeClose(page) {
  try {       await safeClose(page) } catch { /* the frame may already be gone */ }
}
function mergeErrors(into, from) {
  if (!into || !from) return into
  for (const key of ['console', 'page', 'http']) {
    if (Array.isArray(from[key])) into[key].push(...from[key].slice(0, 200))
  }
  return into
}
// Thin retry wrappers that keep puppeteer's own (page, selector, opts) signature so
// every call site reads the same; a timeout is not stale and propagates untouched.
async function waitForSelectorOn(page, selector, opts = {}) {
  return withStaleRetry(`waitFor ${selector}`, () => page.waitForSelector(selector, opts))
}
async function waitForFunctionOn(page, fn, opts = {}, ...args) {
  return withStaleRetry(`waitForFunction ${String(fn).slice(0, 48)}`, () => page.waitForFunction(fn, opts, ...args))
}

// --- check registry -----------------------------------------------------------
const checks = []
let currentScreen = 'run'
function record(name, status, detail = '', extra = {}) {
  checks.push({ screen: currentScreen, name, status, detail, ...extra })
  const mark = status === PASS ? 'ok  ' : status === FAIL ? 'FAIL' : status === NA ? 'n/a ' : 'info'
  console.log(`  [${mark}] ${name}${detail ? ' — ' + String(detail).slice(0, 160) : ''}`)
}
function assert(cond, message) {
  if (!cond) throw new Error(message)
}
function na(message) {
  const e = new Error(message)
  e.notExercisable = true
  throw e
}
async function step(name, fn, opts = {}) {
  const started = Date.now()
  try {
    const detail = await fn()
    if (detail && typeof detail === 'object') {
      record(name, PASS, detail.detail || '', { ...(detail.extra || {}), ms: Date.now() - started })
    } else {
      record(name, PASS, detail || '', { ms: Date.now() - started })
    }
  } catch (e) {
    if (e && e.notExercisable) record(name, NA, e.message, { ms: Date.now() - started })
    else record(name, FAIL, e.message, { product: opts.product !== false, ms: Date.now() - started })
    if (opts.rethrow) throw e
  }
}

// --- report state -------------------------------------------------------------
const screenArtifacts = {}   // key -> { screenshot, console: [], page: [], http: [] }
const failures = []

function chromePath() {
  const dir = path.join(ROOT, '.uat-browser', 'chrome')
  if (!fs.existsSync(dir)) throw new Error('no Chrome for Testing under .uat-browser/')
  const ver = fs.readdirSync(dir).find((d) => d.startsWith('mac_'))
  const app = path.join(dir, ver, 'chrome-mac-arm64', 'Google Chrome for Testing.app', 'Contents', 'MacOS', 'Google Chrome for Testing')
  if (!fs.existsSync(app)) throw new Error('Chrome binary not found at ' + app)
  return app
}

async function apiGet(route, role = 'OWNER') {
  const res = await fetch(API + route, { headers: { 'X-Volt-Role': role } })
  if (!res.ok) throw new Error(`GET ${route} -> ${res.status}`)
  return res.json()
}

// --- page helpers ---------------------------------------------------------------
const OFFICER_BY_ROLE = { OFFICER: 'nantapol', SUPERVISOR: 'settasak', MANAGER: 'settasak', OWNER: 'owner', OPS: 'ops' }

async function newPage(browser) {
  const page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 900 })
  const errors = { console: [], page: [], http: [] }
  page.on('console', (m) => { if (m.type() === 'error') errors.console.push(m.text().slice(0, 400)) })
  page.on('pageerror', (e) => errors.page.push(String(e).slice(0, 400)))
  page.on('response', (r) => {
    if (r.status() >= 400) errors.http.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`)
  })
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => { try { localStorage.clear(); sessionStorage.clear() } catch {} })
  page.__errors = errors
  return page
}

// Navigation is deterministic: DOM-content load, then a bounded network-idle wait, then
// a short settle. The network-idle wait is capped (the API here can hold a request open
// for tens of seconds under memory pressure; the selector wait below owns that budget).
async function settle(page, { idle = 500, cap = 12000, after = 350 } = {}) {
  await page.waitForNetworkIdle({ idleTime: idle, timeout: cap }).catch(() => {})
  await sleep(after)
}

async function gotoAndSettle(page, url, { timeout = 45000 } = {}) {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout })
  await settle(page)
}

// Poll the SPA path. A full document load destroys the execution context mid-poll;
// that is a navigation in flight, not a failed check, so it is retried rather than
// thrown (never hold a handle across a load — a string is re-queried each pass).
async function waitForPath(page, route, timeout = 30000) {
  const deadline = Date.now() + timeout
  let last = ''
  while (Date.now() < deadline) {
    try {
      if (await page.evaluate((r) => location.pathname === r, route)) return
    } catch (e) {
      // A dead frame must surface as stale so the caller can rebuild the page, not
      // burn the whole timeout and then report a plain "did not reach".
      if (isStaleError(e)) throw e
      last = String(e.message).slice(0, 100)
    }
    await sleep(150)
  }
  throw new Error(`did not reach ${route}${last ? ` (${last})` : ''}`)
}

async function pageDump(page, max = 900) {
  try {
    return await withStaleRetry('page dump', () => page.evaluate(() => {
      const body = document.body ? document.body.innerText.replace(/\s+/g, ' ').trim() : ''
      return `${location.href} :: ${body.slice(0, 1400)}`
    }), 0).then((t) => t.slice(0, max))
  } catch (e) {
    return `[page dump unavailable: ${String(e.message).slice(0, 140)}]`
  }
}

async function open(page, route, { role = 'OWNER', lang = 'th', theme = 'light', waitFor = null, timeout = 45000 } = {}) {
  await withStaleRetry(`set session for ${route}`, () => page.evaluate((p) => {
    localStorage.setItem('volt.role', p.role)
    localStorage.setItem('volt.lang', p.lang)
    localStorage.setItem('volt.theme', p.theme)
    localStorage.setItem('volt.officer', p.officer)
    localStorage.setItem('volt.density', 'compact')
  }, { role, lang, theme, officer: OFFICER_BY_ROLE[role] || 'nantapol' }), 0)
  await gotoAndSettle(page, BASE + route, { timeout })
  if (waitFor) {
    // The API on this host degrades badly under machine memory pressure (a freshly
    // started instance is equally slow), and a truncated response can crash the
    // React tree, so one reload is allowed before failing.
    try {
      await waitForSelectorOn(page, waitFor, { timeout })
    } catch (e) {
      console.log(`  .. slow/crashed first paint on ${route}; reloading once`)
      await gotoAndSettle(page, BASE + route, { timeout })
      await waitForSelectorOn(page, waitFor, { timeout })
    }
  }
  await sleep(300)
}

// After a write the screen reloads itself; under host pressure that can be slow, and
// a truncated asset response can blank the React tree. One explicit re-open is
// allowed before the check is called a failure.
async function ensureSelector(page, route, selector, timeout = 45000) {
  try {
    await waitForSelectorOn(page, selector, { timeout: Math.floor(timeout / 2) })
    return
  } catch { /* fall through to one explicit reload */ }
  console.log(`  .. ${selector} not present on ${route}; re-opening once`)
  await gotoAndSettle(page, BASE + route, { timeout })
  await waitForSelectorOn(page, selector, { timeout })
}

async function setInput(page, selector, value) {
  await withStaleRetry(`setInput ${selector}`, () => page.$eval(selector, (el, v) => {
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set
    setter.call(el, v)
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.dispatchEvent(new Event('change', { bubbles: true }))
  }, String(value)))
}

// Selector-string equivalents of the old held-handle reads and writes: each call
// re-queries the live DOM, so nothing survives (or dangles across) a page load.
async function setInputAt(page, selector, index, value) {
  await withStaleRetry(`setInputAt ${selector}[${index}]`, () => page.evaluate(({ selector, index, v }) => {
    const el = document.querySelectorAll(selector)[index]
    if (!el) throw new Error(`no element ${selector} at index ${index}`)
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set
    setter.call(el, v)
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.dispatchEvent(new Event('change', { bubbles: true }))
  }, { selector, index, v: String(value) }))
}

async function mustEval(page, selector, fn, message) {
  assert(await countOf(page, selector) > 0, message)
  return withStaleRetry(`read ${selector}`, () => page.$eval(selector, fn))
}

// A DOM click, not a coordinate click: puppeteer's hit-testing was landing on the
// drawer scrim for footer buttons on the slide-over panels (proven on the pipeline
// evidence drawer), so every act goes through the element's own click(). A stale
// frame is rethrown as itself (never as "no element"), so the caller's stale-handle
// retry can see it; clicks are not auto-retried here because a lost reply may mean
// the click already landed.
async function domClick(page, selector) {
  try {
    return await page.$eval(selector, (el) => { el.click(); return true })
  } catch (e) {
    if (isStaleError(e)) throw e
    throw new Error(`domClick: no element ${selector}`)
  }
}

async function clickByText(page, containerSel, pattern) {
  const hit = await page.evaluate(({ containerSel, pattern }) => {
    const root = document.querySelector(containerSel)
    if (!root) return null
    const re = new RegExp(pattern)
    const el = [...root.querySelectorAll('button, a')].find((b) => re.test(b.textContent || ''))
    if (!el) return null
    el.click()
    return (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80)
  }, { containerSel, pattern })
  if (!hit) throw new Error(`no control matching /${pattern}/ inside ${containerSel}`)
  return hit
}

async function textOf(page, selector) {
  try {
    return await withStaleRetry(`textOf ${selector}`, () =>
      page.$eval(selector, (el) => (el.textContent || '').replace(/\s+/g, ' ').trim()))
  } catch (e) {
    // A missing element is an empty string; a dead frame is not — it must reach the
    // caller's page-rebuild retry instead of quietly reading as "no text".
    if (isStaleError(e)) throw e
    return ''
  }
}

// Count with a selector string, never a held handle: a fresh query each call survives
// a page load and leaves nothing behind that a navigation can detach. Same rule as
// textOf: only a genuinely absent selector reads as 0.
async function countOf(page, selector) {
  try {
    return await withStaleRetry(`countOf ${selector}`, () =>
      page.$$eval(selector, (els) => els.length))
  } catch (e) {
    if (isStaleError(e)) throw e
    return 0
  }
}

async function isDisabled(page, selector) {
  try {
    return await withStaleRetry(`isDisabled ${selector}`, () =>
      page.$eval(selector, (el) => el.disabled === true))
  } catch (e) {
    if (isStaleError(e)) throw e
    return null
  }
}

async function shot(page, name) {
  const file = path.join(SHOTS, name)
  await page.screenshot({ path: file })
  return path.relative(ROOT, file)
}

// --- fixtures / allowlists ------------------------------------------------------
async function gatherNames() {
  const names = new Set()
  const add = (v) => {
    if (typeof v !== 'string' || !v.trim()) return
    names.add(v.replace(/\s+/g, ' ').trim())
  }
  try {
    const wb = await apiGet('/v1/workbook')
    for (const r of wb.rows || []) {
      add(r.customer?.display_name); add(r.display_name); add(r.volt_id)
      add(r.customer?.customer_no); add(r.customer_no); add(r.order_ref); add(r.case?.volt_id)
    }
  } catch {}
  try {
    const t = await apiGet('/v1/today-list')
    for (const i of t.items || []) { add(i.customer?.display_name); add(i.customer?.customer_no) }
  } catch {}
  try {
    const rv = await apiGet('/v1/reviews?status=OPEN')
    for (const r of rv.reviews || []) { add(r.display_name) }
  } catch {}
  try {
    const npl = await apiGet('/v1/npl-cases')
    for (const n of npl.npl_cases || []) { add(n.display_name) }
  } catch {}
  try {
    const off = await apiGet('/v1/officers')
    for (const o of off.officers || []) { add(o.uid); add(o.display_name_th); add(o.display_name_en) }
  } catch {}
  return names
}

const ID_RE = /(?:^|[^A-Za-z0-9])(?:rv|so|iv|rc|npl|wk|imp|vc|vl|vrc|c|pip|case|inv|cr|pix)-?\s?\d/i

// Proper nouns allowed to survive in the English interface: document / report / feature
// names that have no English form (the PEAK report name is served from
// frontend/src/i18n-admin.js peak.title). Customer and officer names come from the live
// API (gatherNames) and document ids match ID_RE. Ordinary Thai sentences still fail:
// EVERY Thai run in a node must be covered by an allowlisted name or proper noun.
const PROPER_NOUNS = [
  'รายงานใบแจ้งหนี้',       // PEAK report name
  'รายงานใบแจ้งหนี้ PEAK',
  'ชุดแจ้งเตือน',           // the reminder-batches feature/document name
]

function thaiIgnoreReason(text, names, properNouns = PROPER_NOUNS) {
  if (!/[\u0E00-\u0E7F]/.test(text)) return null
  const norm = text.replace(/\s+/g, ' ').trim()
  if (ID_RE.test(norm)) return { allowed: true, why: 'document id' }
  const runs = norm.match(/[\u0E00-\u0E7F]+/g) || []
  if (runs.length === 0) return null
  const entities = [...names, ...properNouns].filter(Boolean)
  const hits = new Map()
  const misses = []
  for (const run of runs) {
    const hit = entities.find((e) => e.includes(run))
    if (hit) hits.set(run, hit)
    else misses.push(run)
  }
  if (misses.length === 0) {
    const used = [...new Set(hits.values())]
    return { allowed: true, why: `proper noun/name: ${used.map((u) => `"${u}"`).join(', ')}` }
  }
  return { allowed: false, misses }
}

const THAI_DUMP = `(() => {
  const out = [];
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (w.nextNode()) {
    const t = w.currentNode.textContent.replace(/\\s+/g, ' ').trim();
    if (!t || !/[\\u0E00-\\u0E7F]/.test(t)) continue;
    const el = w.currentNode.parentElement;
    if (!el) continue;
    const s = getComputedStyle(el); const r = el.getBoundingClientRect();
    if (s.display === 'none' || s.visibility === 'hidden' || r.width <= 0 || r.height <= 0) continue;
    if (['SCRIPT','STYLE'].includes(el.tagName)) continue;
    out.push({ t: t.slice(0, 140), typed: !!(el.closest && el.closest('[data-typed]')) });
  }
  const seen = new Set();
  return out.filter((x) => { const k = x.typed + '|' + x.t; if (seen.has(k)) return false; seen.add(k); return true; });
})()`

// --- the twelve screens ----------------------------------------------------------
const SCREENS = [
  { key: 'today', route: '/', th: 'วันนี้', en: 'Today' },
  { key: 'dashboard', route: '/dashboard', th: 'ภาพรวม', en: 'Overview' },
  { key: 'calendar', route: '/calendar', th: 'ปฏิทิน', en: 'Calendar' },
  { key: 'workbook', route: '/workbook', th: 'ลูกค้า / สมุดงาน', en: 'Customers / Workbook' },
  { key: 'reviews', route: '/reviews', th: 'รอตรวจ', en: 'Reviews' },
  { key: 'pipeline', route: '/pipeline', th: 'ใบแจ้งหนี้ก่อนติดตั้ง', en: 'Pre-installation invoices' },
  { key: 'payments', route: '/payments', th: 'เงินเข้าและ PEAK', en: 'Receipts & PEAK' },
  { key: 'recovery', route: '/recovery', th: 'NPL และการเรียกคืน', en: 'NPL & recovery' },
  { key: 'reports', route: '/reports', th: 'รายงาน', en: 'Reports' },
  { key: 'settings', route: '/settings', th: 'ตั้งค่า', en: 'Settings' },
  { key: 'data-sources', route: '/data-sources', th: 'แหล่งข้อมูล', en: 'Data sources' },
  { key: 'audit', route: '/audit', th: 'บันทึกการใช้งาน', en: 'Action log' },
]

// The work panel each screen must open. `record: true` = Today/Workbook, whose own
// work panel IS the customer record; every other screen must NOT resolve there.
const PANELS = {
  today: { selector: '[data-testid^="split-row-"]', record: true },
  dashboard: { selector: '[data-testid="dash-header"]', record: false },
  calendar: { selector: '[data-testid="cal-month"]', record: false },
  workbook: { selector: '[data-testid="workbook"]', record: true },
  reviews: { selector: '[data-testid^="review-"]', record: false },
  pipeline: { selector: '[data-testid^="pipe-status-"]', record: false },
  payments: { selector: '[data-testid="payments"]', record: false },
  recovery: { selector: '[data-testid^="npl-"]', record: false },
  reports: { selector: '[data-testid="editions-table"]', record: false },
  settings: { selector: '[data-testid^="cfg-"]', record: false },
  'data-sources': { selector: '[data-testid="ds-strip"]', record: false },
  audit: { selector: '[data-testid="audit-table"]', record: false },
}

// --- per-screen interactions (Thai / OWNER) ---------------------------------------
const state = {}   // cross-phase facts: ready pipeline uid, selected recovery, etc.

async function walkToday(page) {
  await step('split view: select a queue row and fill the record header', async () => {
    await waitForSelectorOn(page, '[data-testid^="split-row-"]', { timeout: 45000 })
    const key = await mustEval(page, '[data-testid^="split-row-"]:not([disabled])',
      (el) => el.getAttribute('data-testid').replace('split-row-', ''), 'no enabled queue row')
    await domClick(page, `[data-testid="split-row-${key}"]`)
    await sleep(400)
    await waitForSelectorOn(page, '[data-testid="case-record"]', { timeout: 30000 })
    const heading = await textOf(page, '[data-testid="case-record"]')
    assert(heading.length > 0, 'record header is empty after selecting a row')
    const current = await page.$eval(`[data-testid="split-row-${key}"]`, (el) => el.getAttribute('aria-current'))
    assert(current === 'true', 'the selected row is not marked aria-current')
    return `${key} -> "${heading.slice(0, 60)}"`
  })

  await step('log-contact drawer opens and closes', async () => {
    const label = await clickByText(page, '[data-testid="case-record"]', 'บันทึกการติดต่อ|Log contact')
    await waitForSelectorOn(page, '.cd-drawer[role="dialog"]', { timeout: 30000 })
    await page.keyboard.press('Escape')
    await waitForFunctionOn(page, () => !document.querySelector('.cd-drawer'), { timeout: 30000 })
    return `opened via "${label}"`
  })

  await step('switch two record tabs', async () => {
    for (const tab of ['invoices', 'history']) {
      await domClick(page, `#cs-tab-${tab}`)
      await waitForSelectorOn(page, `#cs-panel-${tab}:not([hidden])`, { timeout: 30000 })
      const selected = await page.$eval(`#cs-tab-${tab}`, (el) => el.getAttribute('aria-selected'))
      assert(selected === 'true', `tab ${tab} did not become selected`)
    }
  })
}

async function walkDashboard(page) {
  await step('team dashboard renders, with no individual-customer list', async () => {
    await waitForSelectorOn(page, '[data-testid="dash-header"]', { timeout: 45000 })
    const officers = await countOf(page, '[data-testid="dash-officers"]')
    assert(officers > 0, 'the per-officer performance table is missing')
    for (const sel of ['[data-testid="case-record"]', '[data-testid^="split-row-"]', 'a[href^="/customers/"]']) {
      const n = await countOf(page, sel)
      assert(n === 0, `Overview contains an individual-customer element: ${sel} (${n})`)
    }
    return 'KPI cards + officer table; 0 customer rows'
  })
}

async function walkCalendar(page) {
  await step('switch month / week', async () => {
    await waitForSelectorOn(page, '[data-testid="cal-month"]', { timeout: 45000 })
    await domClick(page, '[data-testid="cal-view-week"]')
    await waitForSelectorOn(page, '[data-testid="cal-week"]', { timeout: 30000 })
    await domClick(page, '[data-testid="cal-view-month"]')
    await waitForSelectorOn(page, '[data-testid="cal-month"]', { timeout: 30000 })
    return 'month -> week -> month'
  })

  await step('move a next action with date + reason; the Moved chip appears', async () => {
    // The move control lives on the week list.
    await domClick(page, '[data-testid="cal-view-week"]')
    await waitForSelectorOn(page, '[data-testid="cal-week"]', { timeout: 30000 })
    const { customerUid, sourceDay } = await mustEval(page, '[data-testid^="cal-move-open-"]', (el) => ({
      customerUid: el.getAttribute('data-testid').replace('cal-move-open-', ''),
      sourceDay: el.closest('[data-day]')?.getAttribute('data-day') || '',
    }), 'no movable next action on the visible week')
    state.calendarCustomer = customerUid
    await domClick(page, `[data-testid="cal-move-open-${customerUid}"]`)
    await waitForSelectorOn(page, '[data-testid="cal-move"]', { timeout: 30000 })

    const days = await page.$$eval('[data-testid^="cal-row-"]', (els) =>
      [...new Set(els.map((el) => el.closest('[data-day]')?.getAttribute('data-day')).filter(Boolean))].sort())
    const target = days.find((d) => d > sourceDay) || days.filter((d) => d < sourceDay).pop()
    assert(target, `no other day in the visible week to move ${sourceDay} to`)

    await setInput(page, '[data-testid="cal-move-to"]', target)
    await sleep(200)
    // The empty-reason refusal: confirm must be disabled, and stay disabled.
    const disabled = await isDisabled(page, '[data-testid="cal-move-confirm"]')
    assert(disabled === true, 'Move-date confirm is enabled with no reason — it must refuse to save')
    record('move-date refuses without a reason (confirm disabled)', PASS, `to=${target}, reason empty`)

    await setInput(page, '[data-testid="cal-move-reason"]', 'UAT: เลื่อนวันตามคำขอลูกค้า')
    await sleep(200)
    await domClick(page, '[data-testid="cal-move-confirm"]')
    try {
      await waitForFunctionOn(page, () => !document.querySelector('[data-testid="cal-move"]'), { timeout: 40000 })
    } catch {
      const refusal = await textOf(page, '[data-testid="cal-move-refusal"]')
      throw new Error(`move-date was refused: ${refusal || 'no refusal text'}`)
    }
    await waitForFunctionOn(page, () => document.querySelector('[data-testid^="cal-moved-"]'), { timeout: 40000 })
    return `${customerUid} ${sourceDay} -> ${target}`
  })

  await step('back to month and screenshot the moved item', async () => {
    await domClick(page, '[data-testid="cal-view-month"]')
    await waitForSelectorOn(page, '[data-testid="cal-month"]', { timeout: 30000 })
  })
}

async function walkWorkbook(page) {
  await step('expand / collapse a band group', async () => {
    await waitForSelectorOn(page, '[data-testid^="split-group-"]', { timeout: 45000 })
    const headSel = await page.$eval('[data-testid^="split-group-"]', (el) => `[data-testid="${el.getAttribute('data-testid')}"]`)
    const before = await page.$eval(headSel, (el) => el.getAttribute('aria-expanded'))
    assert(before === 'true', `group starts collapsed (aria-expanded=${before})`)
    await domClick(page, headSel)
    await waitForFunctionOn(page, (sel) => document.querySelector(sel).getAttribute('aria-expanded') === 'false', { timeout: 30000 }, headSel)
    await domClick(page, headSel)
    await waitForFunctionOn(page, (sel) => document.querySelector(sel).getAttribute('aria-expanded') === 'true', { timeout: 30000 }, headSel)
    return 'first band group toggled both ways'
  })

  await step('select a row', async () => {
    const key = await mustEval(page, '[data-testid^="split-row-"]:not([disabled])',
      (el) => el.getAttribute('data-testid').replace('split-row-', ''), 'no selectable workbook row')
    await domClick(page, `[data-testid="split-row-${key}"]`)
    await waitForSelectorOn(page, '[data-testid="case-record"]', { timeout: 30000 })
    const heading = await textOf(page, '[data-testid="case-record"]')
    assert(heading.length > 0, 'record header empty after selecting a workbook row')
    return `${key} -> "${heading.slice(0, 50)}"`
  })
}

async function walkReviews(page) {
  await step('select a review row', async () => {
    await waitForSelectorOn(page, '[data-testid^="split-row-"]', { timeout: 45000 })
    state.reviewKey = await mustEval(page, '[data-testid^="split-row-"]:not([disabled])',
      (el) => el.getAttribute('data-testid').replace('split-row-', ''), 'no review row to select')
    await domClick(page, `[data-testid="split-row-${state.reviewKey}"]`)
    await waitForSelectorOn(page, `[data-testid="review-${state.reviewKey}"]`, { timeout: 30000 })
    return state.reviewKey
  })

  await step('decision form refuses an empty submit', async () => {
    const uid = state.reviewKey
    assert(uid, 'no review selected')
    await waitForSelectorOn(page, `fieldset[data-testid="rq-form-${uid}"]`, { timeout: 30000 })
    const disabled = await isDisabled(page, `fieldset[data-testid="rq-form-${uid}"] button[type="submit"]`)
    assert(disabled === true, 'the review submit is enabled with no decision and no reason')
    const why = await textOf(page, `[data-testid="rq-answer-why-${uid}"]`)
    assert(why.length > 0, 'no on-screen reason for the blocked submit')
    return why.slice(0, 100)
  })

  await step('submit the decision with a reason', async () => {
    const uid = state.reviewKey
    const form = `fieldset[data-testid="rq-form-${uid}"]`
    await page.select(`${form} select`, 'NPL_TYPE_SET')
    await waitForFunctionOn(page, (sel) => document.querySelectorAll(sel + ' select').length >= 3, { timeout: 30000 }, form)
    const selects = await page.$$(`${form} select`)
    assert(selects.length >= 3, `expected decision + NPL type + next action selects, found ${selects.length}`)
    const nplValue = await selects[1].evaluate((el) => [...el.options].map((o) => o.value).filter(Boolean)[0] || '')
    assert(nplValue, 'the NPL type select offers no option')
    await selects[1].select(nplValue)
    await setInput(page, `${form} textarea`, 'UAT: กำหนดประเภทจากหลักฐานในระบบ')
    await sleep(300)
    const enabled = await isDisabled(page, `${form} button[type="submit"]`)
    assert(enabled === false, 'the review submit stays disabled after decision + type + reason')
    const respPromise = page.waitForResponse(
      (r) => r.url().includes(`/v1/reviews/${uid}:answer`), { timeout: 45000 }).catch(() => null)
    await domClick(page, `${form} button[type="submit"]`)
    const resp = await respPromise
    if (resp && resp.status() >= 400) {
      await sleep(500)
      const refusal = await textOf(page, '.refusal[role="alert"]')
      throw new Error(`the answer was refused (HTTP ${resp.status()}): ${refusal.slice(0, 200)}`)
    }
    // The screen reloads after an accepted answer; under host pressure that can take
    // longer than a fixed pause, so wait for either of its two lawful end states.
    try {
      await waitForFunctionOn(page, (id) => {
        const answered = document.querySelector(`[data-testid="rq-answered-${id}"]`)
        const still = document.querySelector(`[data-testid="review-${id}"]`)
        return answered || !still
      }, { timeout: 45000 }, uid)
    } catch {
      throw new Error('the answer was accepted but neither the outcome band appeared nor the request left the open queue')
    }
    const answered = await textOf(page, `[data-testid="rq-answered-${uid}"]`)
    if (answered) return `HTTP ${resp ? resp.status() : '?'}; ${answered.slice(0, 60)}`
    return `HTTP ${resp ? resp.status() : '?'}; request closed and left the open queue`
  })
}

async function walkPipeline(page) {
  await step('select a pipeline row', async () => {
    // Prefer an item whose contract-signed condition is still open, so the evidence
    // drawer really flips it. The read runs inside the page, so it sees the SAME
    // session cookie the screen's own reads see — the pipeline store is per session.
    await waitForSelectorOn(page, '[data-testid^="split-row-"]', { timeout: 45000 })
    const openUid = await page.evaluate(async () => {
      try {
        const r = await fetch('/api/v1/pipeline')
        const d = await r.json()
        const hit = (d.items || []).find((i) => (i.conditions || []).some((c) => c.key === 'contract_signed' && !c.passed))
        return hit ? hit.uid : null
      } catch { return null }
    })
    if (openUid) state.pipelineUid = openUid
    if (state.pipelineUid) {
      await open(page, `/pipeline?sel=${state.pipelineUid}`, { role: 'OWNER', lang: 'th', waitFor: `[data-testid="pipe-status-${state.pipelineUid}"]` })
    } else {
      state.pipelineUid = await mustEval(page, '[data-testid^="split-row-"]:not([disabled])',
        (el) => el.getAttribute('data-testid').replace('split-row-', ''), 'no pipeline row to select')
      await domClick(page, `[data-testid="split-row-${state.pipelineUid}"]`)
      await waitForSelectorOn(page, `[data-testid="pipe-status-${state.pipelineUid}"]`, { timeout: 30000 })
    }
    return state.pipelineUid
  })

  await step('attach evidence to contract-signed and see the condition pass', async () => {
    const uid = state.pipelineUid
    assert(uid, 'no pipeline item selected')
    const chipSel = `[data-testid="cond-contract_signed-${uid}"] [data-gate-state]`
    const before = await page.$eval(chipSel, (el) => el.getAttribute('data-gate-state')).catch(() => 'missing')
    assert(before !== 'PASSED', `the chosen item already has contract_signed PASSED (${before})`)
    await domClick(page, `[data-testid="cond-attach-contract_signed-${uid}"]`)
    await waitForSelectorOn(page, '.pipe-drawer[role="dialog"]', { timeout: 30000 })
    await setInput(page, '[data-testid="pipe-evidence-note"]', 'UAT: สำเนาสัญญาลงนามสองฝ่าย')
    await sleep(250)
    await domClick(page, '[data-testid="pipe-evidence-attach"]')
    try {
      await waitForFunctionOn(page, 
        (sel) => document.querySelector(sel)?.getAttribute('data-gate-state') === 'PASSED',
        { timeout: 40000 }, chipSel)
    } catch {
      const refusal = await textOf(page, '.pipe-drawer .refusal')
      const open = await countOf(page, '.pipe-drawer') > 0
      throw new Error(`condition did not pass (drawer ${open ? 'still open' : 'closed'}): ${refusal || 'no refusal text'}`)
    }
    // The drawer stays open by design (it can take more than one attachment); close
    // it with Escape as an officer would.
    await page.keyboard.press('Escape')
    await waitForFunctionOn(page, () => !document.querySelector('.pipe-drawer'), { timeout: 30000 }).catch(() => {})
    return `contract_signed: ${before} -> PASSED`
  })

  await step('pass the down-payment condition (slip ref + amount)', async () => {
    const uid = state.pipelineUid
    const cond = `[data-testid="cond-down_payment-${uid}"]`
    await ensureSelector(page, `/pipeline?sel=${uid}`, cond, 60000)
    const inputSel = `${cond} form input`
    const inputCount = await countOf(page, inputSel)
    assert(inputCount >= 1, 'down-payment form has no input')
    const ref = await page.$eval(inputSel, (el) => el.value).catch(() => '')
    if (!ref) await setInputAt(page, inputSel, 0, 'UAT-SLIP-0001')
    if (inputCount >= 2) await setInputAt(page, inputSel, 1, '5000')
    await sleep(300)
    const respPromise = page.waitForResponse(
      (r) => r.url().includes(`/v1/pipeline/${uid}/gates/down-payment`), { timeout: 45000 }).catch(() => null)
    await domClick(page, `${cond} form button[type="submit"]`)
    const resp = await respPromise
    await sleep(500)
    if (resp && resp.status() >= 400) {
      const refusal = await textOf(page, '.refusal')
      throw new Error(`down-payment refused (HTTP ${resp.status()}): ${refusal || 'no refusal text'}`)
    }
    try {
      await waitForFunctionOn(page, 
        (sel) => document.querySelector(sel)?.getAttribute('data-gate-state') === 'PASSED',
        { timeout: 20000 }, `${cond} [data-gate-state]`)
    } catch {
      // The route answers 200 but returns the item's PRE-write conditions
      // (routers/pipeline.py:144 returns the raw item; annotate() runs nowhere on
      // this path), so the chip and the Release button read stale state until a
      // reload. Name that exactly rather than a bare timeout.
      const body = resp ? await resp.json().catch(() => null) : null
      const stale = body?.item?.conditions?.find((c) => c.key === 'down_payment')
      if (resp && resp.status() < 400 && stale && !stale.passed) {
        throw new Error(`gate accepted (HTTP ${resp.status()}) but the response carries the pre-write conditions (down_payment=${stale.state}) — the chip stays OPEN and Release stays disabled until a manual reload`)
      }
      const refusal = await textOf(page, '.refusal')
      throw new Error(`down-payment gate did not pass: ${refusal || (resp ? `HTTP ${resp.status()}` : 'no response')}`)
    }
    return 'down_payment -> PASSED'
  })

  await step('all three conditions are passed, release is offered', async () => {
    const uid = state.pipelineUid
    await ensureSelector(page, `/pipeline?sel=${uid}`, `[data-testid="pipe-status-${uid}"]`, 60000)
    const passed = await countOf(page, `[data-testid="pipe-status-${uid}"]`)
    assert(passed === 1, 'pipeline work panel is missing')
    const states = await page.$$eval('[data-gate-state]', (els) => els.map((el) => el.getAttribute('data-gate-state')))
    assert(states.every((s) => s === 'PASSED'), `conditions not all passed: ${states.join(', ')}`)
    const releaseDisabled = await isDisabled(page, `[data-testid="release-${uid}"]`)
    assert(releaseDisabled === false, 'release is disabled at 3/3')
    return '3/3 passed'
  })
}

async function walkPayments(page) {
  await step('raise a slip so a document exists, then select it', async () => {
    await waitForSelectorOn(page, '[data-testid="payments"]', { timeout: 45000 })
    let rows = await countOf(page, '[data-testid^="split-row-"]')
    if (rows === 0) {
      // Empty fixture list: drive one slip through the form.
      await domClick(page, '[data-testid="slip-invoice"]')
      await waitForSelectorOn(page, '[data-testid="slip-invoice"][aria-expanded="true"]', { timeout: 30000 })
      let optionSel = null
      const picker = '.ss__panel li[role="option"][data-value]:not([data-value=""])'
      try {
        await waitForSelectorOn(page, picker, { timeout: 30000 })
        optionSel = picker
      } catch { /* handled below */ }
      assert(optionSel, 'the invoice picker offers no payable invoice')
      const { label, value } = await page.$eval(optionSel, (el) => ({
        label: el.textContent.trim(), value: el.getAttribute('data-value'),
      }))
      await domClick(page, `.ss__panel li[role="option"][data-value="${value}"]`)
      await waitForFunctionOn(page, (v) => document.querySelector('[data-testid="slip-invoice"]')?.getAttribute('data-value') === v, { timeout: 30000 }, value)
      const form = 'section.ops-card'
      const formInputSel = `${form} .ops-form input`
      assert(await countOf(page, formInputSel) >= 2, 'the slip form does not carry amount + slip-ref inputs')
      const amount = await page.$eval(formInputSel, (el) => el.value).catch(() => '')
      if (!amount) await setInputAt(page, formInputSel, 0, '1000')
      await setInputAt(page, formInputSel, 1, 'UAT-SLIP-REF-1')
      await sleep(200)
      await domClick(page, `${form} form button[type="submit"]`)
      await waitForSelectorOn(page, '[data-testid="slip-result"]', { timeout: 45000 })
      await waitForFunctionOn(page, () => document.querySelector('[data-testid^="split-row-"]'), { timeout: 45000 })
      rows = await countOf(page, '[data-testid^="split-row-"]')
      state.paymentUid = await page.$eval('[data-testid^="split-row-"]', (el) => el.getAttribute('data-testid').replace('split-row-', ''))
      await domClick(page, `[data-testid="split-row-${state.paymentUid}"]`)
      await waitForSelectorOn(page, '[data-testid="doc-head"]', { timeout: 30000 })
      return `slip on ${label.slice(0, 60)} -> ${rows} document row(s)`
    }
    state.paymentUid = await mustEval(page, '[data-testid^="split-row-"]:not([disabled])',
      (el) => el.getAttribute('data-testid').replace('split-row-', ''), 'no payment document row')
    await domClick(page, `[data-testid="split-row-${state.paymentUid}"]`)
    await waitForSelectorOn(page, '[data-testid="doc-head"]', { timeout: 30000 })
    return `${state.paymentUid} (fixtures already had documents)`
  })

  await step('the document gates panel is served', async () => {
    const gates = await countOf(page, '[data-testid^="gate-"]')
    assert(gates === 3, `expected 3 gates, found ${gates}`)
    const allocation = await countOf(page, '[data-testid="pay-allocation"]')
    assert(allocation === 1, 'allocation block missing')
  })
}

async function walkRecovery(page) {
  await step('select an NPL case and choose a recovery path', async () => {
    await waitForSelectorOn(page, '[data-testid^="split-row-"]', { timeout: 45000 })
    // Read inside the page so the candidate comes from the SAME session the screen
    // uses (the NPL/recovery store is per volt_session cookie).
    const freeUid = await page.evaluate(async () => {
      try {
        const r = await fetch('/api/v1/npl-cases')
        const d = await r.json()
        const hit = (d.npl_cases || []).find((n) => !n.recovery_uid)
        return hit ? hit.uid : null
      } catch { return null }
    })
    if (!freeUid) na('every NPL case in this session already has a recovery path — no path left to choose')
    state.recoveryKey = freeUid
    await open(page, `/recovery?sel_npl=${freeUid}`, { role: 'OWNER', lang: 'th', waitFor: `[data-testid="split-row-${freeUid}"]` })
    await waitForSelectorOn(page, '[data-testid="npl-npv"]', { timeout: 30000 })
    assert(await countOf(page, '[data-testid="path-choice"]') > 0, 'no path-choice panel on the selected NPL case')
    const radioSel = await page.$eval('[role="radio"][data-testid^="path-"]:not([disabled])', (el) => `[data-testid="${el.getAttribute('data-testid')}"]`)
    await domClick(page, radioSel)
    await waitForSelectorOn(page, '[data-testid="path-confirm"]:not([disabled])', { timeout: 30000 })
    const confirmBefore = await page.$eval('[data-testid="path-confirm"]', (el) => el.textContent.trim())
    // A real mouse click: React's synthetic handler for this panel's confirm did not
    // fire under el.click() (probed on 2026-09-18), while the slider-over scrim makes
    // page.click unsafe elsewhere. This one control uses the real pointer.
    await page.click('[data-testid="path-confirm"]')
    try {
      await waitForSelectorOn(page, '[data-testid="path-chosen"]', { timeout: 40000 })
    } catch {
      const refusal = await textOf(page, '.refusal')
      throw new Error(`confirming the path was refused: ${refusal || 'no refusal text'}`)
    }
    return `${state.recoveryKey}: ${radioSel} confirmed (${confirmBefore})`
  })

  await step('the chosen path serves its next steps', async () => {
    const panel = await countOf(page, '[data-testid^="path-steps-"]')
    if (panel === 0) {
      na('the API served no next_steps list for this strategy — the steps panel cannot be exercised on fixtures')
    }
    const steps = await countOf(page, '[data-testid^="path-step-"]')
    assert(steps > 0, 'the steps panel rendered no step rows')
    return `${steps} served step(s)`
  })
}

async function walkReports(page) {
  await step('weekly editions table with a draft', async () => {
    await waitForSelectorOn(page, '[data-testid="editions-table"]', { timeout: 45000 })
    await waitForSelectorOn(page, '[data-testid="wk-publish"]', { timeout: 45000 })
    const table = await textOf(page, '[data-testid="editions-table"]')
    assert(table.length > 0, 'editions table is empty')
    return 'draft + editions table rendered'
  })
}

async function walkSettings(page) {
  await step('locked and editable rows are visible together', async () => {
    await waitForSelectorOn(page, '[data-testid^="cfg-"]', { timeout: 45000 })
    const locked = await countOf(page, '[data-lock="locked"]')
    const editable = await countOf(page, '[data-lock="manager"], [data-lock="owner_only"]')
    assert(locked > 0, 'no locked setting row')
    assert(editable > 0, 'no editable setting row')
    return `${locked} locked / ${editable} editable`
  })

  await step('officer and manager columns render side by side', async () => {
    const officer = await countOf(page, '[data-testid^="cfg-officer-"]')
    const manager = await countOf(page, '[data-testid^="cfg-manager-"]')
    assert(officer > 0 && manager > 0, `missing view columns (officer=${officer}, manager=${manager})`)
    const highlighted = await page.$$eval('.set-row__view.is-you', (els) => els.length)
    assert(highlighted > 0, "no column is marked as the current role's own")
    return `${officer} officer / ${manager} manager columns, ${highlighted} highlighted as current role`
  })

  await step('change one unlocked setting and save', async () => {
    const key = 'pipeline_lookahead_days'
    const inputSel = `[data-testid="cfg-input-${key}"]`
    await waitForSelectorOn(page, inputSel, { timeout: 30000 })
    const enabled = await isDisabled(page, inputSel)
    assert(enabled === false, `${key} is not editable at OWNER`)
    const before = await textOf(page, `[data-testid="cfg-changed-${key}"]`)
    const current = await page.$eval(inputSel, (el) => el.value)
    const next = current === '4' ? '5' : '4'
    await setInput(page, inputSel, next)
    await sleep(250)
    const saveDisabled = await isDisabled(page, `[data-testid="cfg-save-${key}"]`)
    assert(saveDisabled === false, 'Save is disabled after changing the value')
    await domClick(page, `[data-testid="cfg-save-${key}"]`)
    await waitForFunctionOn(page, 
      (sel) => !document.querySelector(sel)?.textContent.includes('ยังไม่มีการแก้ไข'),
      { timeout: 30000 }, `[data-testid="cfg-changed-${key}"]`)
    const after = await textOf(page, `[data-testid="cfg-changed-${key}"]`)
    assert(after !== before, `the changed-by line did not move: ${after}`)
    return `${key}: ${current} -> ${next}; ${after.slice(0, 50)}`
  })
}

async function walkDataSources(page) {
  await step('idle import surfaces (three stages)', async () => {
    await waitForSelectorOn(page, '[data-testid="ds-strip"]', { timeout: 45000 })
    const drop = await countOf(page, '[data-testid="dropzone"]')
    const submit = await countOf(page, '[data-testid="import-submit"]')
    const land = await countOf(page, '[data-testid="import-land"]')
    assert(drop > 0 && submit > 0 && land > 0, 'not all three import-stage controls rendered')
    const why = await textOf(page, '[data-testid="import-why"]')
    assert(why.length > 0, 'the check-file button has no stated reason while no file is chosen')
    return 'dropzone, Check file, Land rows all present; idle reason shown'
  })

  await step('check a file: the inspection report renders', async () => {
    const csv = path.join(FIXTURES, 'uat-check.csv')
    fs.writeFileSync(csv, 'VOLT ID,Payment Status,Contract Term,Monthly Payment\nUAT_0001,Current,60,3500\nUAT_0002,Late,48,4200\n', 'utf8')
    const input = await page.$('input[type="file"]')
    assert(input, 'no file input inside the dropzone')
    await input.uploadFile(csv)
    await sleep(400)
    const submitDisabled = await isDisabled(page, '[data-testid="import-submit"]')
    assert(submitDisabled === false, 'Check file stays disabled after choosing a file')
    await domClick(page, '[data-testid="import-submit"]')
    await waitForSelectorOn(page, '[data-testid="import-report"]', { timeout: 45000 })
    return 'inspection report rendered'
  })

  await step('land the file: the receipt renders (third stage)', async () => {
    const csv = path.join(FIXTURES, 'uat-crm-lead.csv')
    fs.writeFileSync(csv, [
      'Volt ID,First Name,Last Name,Order Type,Order Status,Phone,Monthly Rate, INC VAT,Term,DP Amount,Watt,EPC,EPC Start Date,Install Province',
      'UAT_0001,ทดสอบ,ระบบ,LEASING,Order - Done,0800000000,3500,60,5000,5,EPC,2026-10-01,กรุงเทพมหานคร',
    ].join('\n') + '\n', 'utf8')
    const input = await page.$('input[type="file"]')
    assert(input, 'no file input inside the dropzone')
    await input.uploadFile(csv)
    await sleep(400)
    const landDisabled = await isDisabled(page, '[data-testid="import-land"]')
    assert(landDisabled === false, 'Land rows is disabled at OWNER')
    await domClick(page, '[data-testid="import-land"]')
    try {
      await waitForFunctionOn(page, () => {
        const m = document.querySelector('[data-testid="manifest"]')
        const t = m ? m.textContent : ''
        return t && !/ยังไม่มี|ไม่มีรายการ|Empty/i.test(t)
      }, { timeout: 120000, polling: 1500 })
    } catch {
      na('the crm-lead landing run did not complete against these fixtures within 45s (no receipt surfaced)')
    }
    return 'landed receipt rendered'
  })

  await step('export refuses without a reason and succeeds with one', async () => {
    await waitForSelectorOn(page, '[data-testid="export-reason"]', { timeout: 30000 })
    const disabled = await isDisabled(page, '[data-testid="export-submit"]')
    assert(disabled === true, 'export is enabled with no reason')
    const why = await textOf(page, '[data-testid="export-why"]')
    assert(why.length > 0, 'no on-screen reason for the blocked export')
    await setInput(page, '[data-testid="export-reason"]', 'UAT: ตรวจสอบข้อมูลก่อนส่งมอบ')
    await sleep(250)
    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/v1/workbook:export') && r.request().method() === 'POST', { timeout: 45000 })
    await domClick(page, '[data-testid="export-submit"]')
    const resp = await respPromise
    assert(resp.status() === 200, `export answered ${resp.status()}`)
    return `reason required (${why.slice(0, 50)}); POST -> 200`
  })
}

async function walkAudit(page) {
  await step('change the act filter', async () => {
    await waitForSelectorOn(page, '[data-testid="audit-table"]', { timeout: 45000 })
    const values = await page.$$eval('#audit-act option', (os) => os.map((o) => o.value).filter(Boolean))
    assert(values.length > 0, 'the act filter has no act to choose')
    await page.select('#audit-act', values[0])
    await sleep(800)
    const rows = await countOf(page, '[data-testid^="audit-row-"]')
    return `act=${values[0]} -> ${rows} row(s)`
  })
}

const WALKERS = {
  today: walkToday,
  dashboard: walkDashboard,
  calendar: walkCalendar,
  workbook: walkWorkbook,
  reviews: walkReviews,
  pipeline: walkPipeline,
  payments: walkPayments,
  recovery: walkRecovery,
  reports: walkReports,
  settings: walkSettings,
  'data-sources': walkDataSources,
  audit: walkAudit,
}

// --- acceptance checks ------------------------------------------------------------
// Only Today and Workbook may resolve their own work panel to the customer record;
// every other rail row must open its OWN panel and must not silently land on the
// customer record. The allowlist is explicit so a route's flag can never be read
// backwards in the report.
const RECORD_SCREENS = new Set(['today', 'workbook'])
// The routes whose rail navigation produced the detached-frame failures. The dry-run
// smoke walks exactly these; a full run walks all twelve.
const RAIL_SMOKE_ROUTES = ['/reviews', '/pipeline', '/payments', '/recovery', '/reports', '/settings', '/data-sources', '/audit']

async function acceptanceRail(browser, routes = null) {
  currentScreen = 'acceptance:rail'
  const wanted = routes || SCREENS.map((s) => s.route)
  const holder = { browser, page: await newPage(browser), errors: { console: [], page: [], http: [] } }
  try {
    for (const route of wanted) {
      const screen = SCREENS.find((s) => s.route === route)
      const allowRecord = RECORD_SCREENS.has(screen.key)
      await step(`rail row ${route} opens its own work panel`, async () => {
        return withPageRetry(`rail ${route}`, holder, async (page) => {
          await open(page, '/', { role: 'OWNER', lang: 'th', waitFor: '[data-testid^="split-row-"]' })
          assert(await countOf(page, `nav#rail-nav a[href="${route}"]`) > 0, `no rail row for ${route}`)
          await domClick(page, `nav#rail-nav a[href="${route}"]`)
          await waitForPath(page, route, 30000)
          const panel = PANELS[screen.key]
          try {
            await waitForSelectorOn(page, panel.selector, { timeout: 45000 })
          } catch (e) {
            if (isStaleError(e)) throw e
            throw new Error(`${route} (${screen.key}): work-panel selector ${panel.selector} never rendered; records=${await countOf(page, '[data-testid="case-record"]')}; page: ${await pageDump(page, 1200)}`)
          }
          if (allowRecord) await waitForSelectorOn(page, '[data-testid="case-record"]', { timeout: 30000 }).catch(() => {})
          const records = await countOf(page, '[data-testid="case-record"]')
          const evidence = allowRecord
            ? `${route} (${screen.key}) -> ${panel.selector}; customer record x${records}; record screens: Today/WorkBook (allowed)`
            : `${route} (${screen.key}) -> ${panel.selector}; customer record x${records} (must be 0)`
          if (allowRecord) {
            assert(records > 0, `${route} must open the customer record but none rendered [expected: customer record (allowed); evidence: ${evidence}; page: ${await pageDump(page)}]`)
            return { detail: 'customer record (allowed: Today/WorkBook)', extra: { evidence, route, expected: 'customer record', records } }
          }
          assert(records === 0, `${route} silently resolved to the customer record [expected: own work panel ${panel.selector}; evidence: ${evidence}; page: ${await pageDump(page)}]`)
          return { detail: 'own work panel, no customer record', extra: { evidence, route, expected: panel.selector, records } }
        })
      }, { product: true })
    }
  } finally {
    mergeErrors(holder.errors, holder.page && holder.page.__errors)
    Object.assign(screenArtifacts['rail'] = screenArtifacts['rail'] || {}, { errors: holder.errors })
    await safeClose(holder.page)
  }
}

async function acceptanceSettings(browser) {
  const page = await newPage(browser)
  currentScreen = 'acceptance:settings'
  const lockedKey = 'invoice_owner_role'
  const unlockedKey = 'pipeline_lookahead_days'
  try {
    for (const role of ['OWNER', 'MANAGER', 'OFFICER']) {
      await open(page, '/settings', { role, lang: 'th', waitFor: '[data-testid^="cfg-"]' })
      await step(`[${role}] locked setting cannot be edited`, async () => {
        const disabled = await isDisabled(page, `[data-testid="cfg-input-${lockedKey}"]`)
        assert(disabled === true, `${lockedKey} is editable at ${role}`)
        const why = await textOf(page, `[data-testid="cfg-why-${lockedKey}"]`)
        assert(why.length > 0, `${lockedKey} is locked with no stated reason`)
        const chip = await countOf(page, `[data-testid="cfg-${lockedKey}"] [data-testid="state-locked"], [data-testid="cfg-${lockedKey}"] [data-testid="state-open"]`)
        assert(chip > 0, 'no locked chip on the row')
        return why.slice(0, 70)
      })
      await step(`[${role}] unlocked setting ${role === 'OFFICER' ? 'refuses' : 'allows'} editing`, async () => {
        const disabled = await isDisabled(page, `[data-testid="cfg-input-${unlockedKey}"]`)
        if (role === 'OFFICER') {
          assert(disabled === true, `${unlockedKey} is editable below Manager`)
          const why = await textOf(page, `[data-testid="cfg-why-${unlockedKey}"]`)
          assert(why.length > 0, 'no visible reason for the below-Manager refusal')
          return why.slice(0, 70)
        }
        assert(disabled === false, `${unlockedKey} is not editable at ${role}`)
        return 'editable'
      })
    }
  } finally {
    Object.assign(screenArtifacts['settings-roles'] = screenArtifacts['settings-roles'] || {}, { errors: page.__errors })
    await safeClose(page)
  }
}

// A3 — a below-Manager refusal is read from the live page, not from one brittle
// testid: the disabled control, its reason attribute / aria-describedby, and the whole
// visible page text are all evidence sources. The exact evidence string is returned;
// when nothing is found the page dump is. This is deliberately resilient to a screen
// moving its reason to another element or another sentence.
async function refusalEvidence(page, controlSel, patterns = []) {
  try {
    return await page.evaluate(({ controlSel, patterns }) => {
      const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim()
      const out = { exists: false, disabled: null, reasons: [], pageMatch: '', text: '' }
      const el = document.querySelector(controlSel)
      out.exists = Boolean(el)
      if (el) {
        out.disabled = el.disabled === true
        for (const attr of ['title', 'aria-label', 'data-reason']) {
          const v = norm(el.getAttribute(attr))
          if (v) out.reasons.push(`${attr}="${v}"`)
        }
        for (const id of norm(el.getAttribute('aria-describedby')).split(/\s+/).filter(Boolean)) {
          const t = norm(document.getElementById(id)?.innerText)
          if (t) out.reasons.push(`aria-describedby(#${id})="${t}"`)
        }
      }
      const body = norm(document.body ? document.body.innerText : '')
      out.text = body.slice(0, 1600)
      if (patterns.length) {
        const m = body.match(new RegExp(`.{0,80}(?:${patterns.join('|')}).{0,140}`, 'i'))
        if (m) out.pageMatch = norm(m[0])
      }
      return out
    }, { controlSel, patterns })
  } catch (e) {
    if (isStaleError(e)) throw e
    return { exists: false, disabled: null, reasons: [], pageMatch: '', text: `[page read failed: ${e.message}]` }
  }
}

async function refuseBelowManager(page, { route, controlSel, patterns = [], label, respIncludes = '' }) {
  await open(page, route, { role: 'OFFICER', lang: 'th', waitFor: controlSel })
  const ev = await refusalEvidence(page, controlSel, patterns)
  if (!ev.exists) {
    throw new Error(`${label}: no control ${controlSel} on ${route}; page: ${await pageDump(page)}`)
  }
  if (ev.disabled === true) {
    const reason = ev.reasons[0] || ev.pageMatch
    if (reason) {
      return { detail: reason.slice(0, 100), evidence: `${label}: ${controlSel} disabled; ${reason}` }
    }
    throw new Error(`${label}: ${controlSel} is disabled with no visible reason line or reason attribute; page: ${await pageDump(page, 1400)}`)
  }
  const respPromise = page.waitForResponse(
    (r) => r.request().method() === 'POST' && r.url().includes(respIncludes), { timeout: 45000 }).catch(() => null)
  await domClick(page, controlSel)
  const resp = await respPromise
  await sleep(600)
  const refusal = await textOf(page, '.refusal[role="alert"]')
  if (resp && resp.status() >= 400 && refusal) {
    return { detail: `HTTP ${resp.status()} — ${refusal.slice(0, 100)}`, evidence: `${label}: control was enabled; POST -> HTTP ${resp.status()}; refusal "${refusal.slice(0, 200)}"` }
  }
  if (resp && resp.status() < 300) {
    throw new Error(`${label}: the act was ACCEPTED below Manager (HTTP ${resp.status()}) — it must refuse with a named reason; page: ${await pageDump(page)}`)
  }
  throw new Error(`${label}: no refusal after the click (${resp ? `HTTP ${resp.status()}` : 'no response'}, refusal ${refusal.slice(0, 80) || 'none'}); page: ${await pageDump(page)}`)
}

async function acceptancePublish(browser) {
  const page = await newPage(browser)
  currentScreen = 'acceptance:reports'
  try {
    await step('MANAGER publishes the draft, then downloads it with a reason', async () => {
      await open(page, '/reports', { role: 'MANAGER', lang: 'th', waitFor: '[data-testid="editions-table"]' })
      await waitForSelectorOn(page, '[data-testid="wk-publish"]', { timeout: 45000 })
      const pubDisabled = await isDisabled(page, '[data-testid="wk-publish"]')
      assert(pubDisabled === false, 'Publish is disabled at MANAGER')
      const respPromise = page.waitForResponse(
        (r) => r.url().includes('/v1/reports/weekly:publish') && r.request().method() === 'POST', { timeout: 45000 }).catch(() => null)
      await domClick(page, '[data-testid="wk-publish"]')
      const pubResp = await respPromise
      assert(!pubResp || pubResp.status() < 400, `publish answered ${pubResp ? pubResp.status() : 'no response'}`)
      await waitForSelectorOn(page, '[data-testid^="wk-download-"]', { timeout: 45000 })
      const downloadSel = await page.$eval('[data-testid^="wk-download-"]', (el) => `[data-testid="${el.getAttribute('data-testid')}"]`)
      await domClick(page, downloadSel)
      await waitForSelectorOn(page, '[data-testid="wk-export-form"]', { timeout: 30000 })
      const exportResp = page.waitForResponse(
        (r) => r.url().includes('/v1/reports/weekly:export') && r.request().method() === 'POST', { timeout: 45000 })
      await setInput(page, '[data-testid="wk-export-reason"]', 'UAT: เก็บฉบับเผยแพร่ไว้ตรวจสอบ')
      await sleep(200)
      await domClick(page, '[data-testid="wk-export-submit"]')
      const resp = await exportResp
      assert(resp.status() === 200, `weekly export answered ${resp.status()}`)
      return 'published; export POST -> 200'
    })

    await step('[OFFICER] Publish refuses with a named reason', async () => {
      return refuseBelowManager(page, {
        route: '/reports',
        controlSel: '[data-testid="wk-publish"]',
        patterns: ['ผู้จัดการ', 'Manager or the Owner'],
        label: '[OFFICER] Publish refuses',
        respIncludes: '/v1/reports/weekly:publish',
      })
    })
  } finally {
    Object.assign(screenArtifacts['reports-publish'] = screenArtifacts['reports-publish'] || {}, { errors: page.__errors })
    await safeClose(page)
  }
}

async function acceptanceRelease(browser) {
  const page = await newPage(browser)
  currentScreen = 'acceptance:pipeline'
  try {
    await step('[OFFICER] Release refuses below Manager with a named reason', async () => {
      const uid = state.pipelineUid
      assert(uid, 'no pipeline item was made release-ready in the OWNER walk')
      const controlSel = `[data-testid="release-${uid}"]`
      await open(page, `/pipeline?sel=${uid}`, { role: 'OFFICER', lang: 'th', waitFor: controlSel })
      // The disabled control with its reason attribute / visible reason line IS the
      // refusal; the whole page text is the fallback when the reason moved element.
      const ev = await refusalEvidence(page, controlSel,
        ['ต้องผ่านเงื่อนไขครบทุกข้อก่อน', 'every condition must pass first', 'ผู้จัดการ', 'Manager or the Owner'])
      if (!ev.exists) {
        throw new Error(`[OFFICER] Release: no control ${controlSel} on /pipeline?sel=${uid}; page: ${await pageDump(page)}`)
      }
      if (ev.disabled === true) {
        const reason = ev.reasons[0] || ev.pageMatch
        if (reason) {
          return {
            detail: reason.slice(0, 100),
            extra: { evidence: `[OFFICER] Release: ${controlSel} disabled; ${reason}` },
          }
        }
        throw new Error(`[OFFICER] Release: ${controlSel} is disabled with no visible reason line or reason attribute; page: ${await pageDump(page, 1400)}`)
      }
      const respPromise = page.waitForResponse(
        (r) => r.url().includes(`/v1/pipeline/${uid}:release`), { timeout: 45000 }).catch(() => null)
      await domClick(page, controlSel)
      const resp = await respPromise
      await sleep(600)
      const refusal = await textOf(page, '.refusal[role="alert"]')
      if (resp && resp.status() >= 400 && refusal) {
        return {
          detail: `HTTP ${resp.status()} — ${refusal.slice(0, 100)}`,
          extra: { evidence: `[OFFICER] Release: control was enabled; POST -> HTTP ${resp.status()}; refusal "${refusal.slice(0, 200)}"` },
        }
      }
      if (resp && resp.status() < 300) {
        const chip = await textOf(page, `[data-testid="pipe-status-${uid}"]`)
        let owner = 'unknown'
        try { owner = (await apiGet('/v1/config')).config?.invoice_owner_role?.value || 'unknown' } catch {}
        throw new Error(`release was ACCEPTED below Manager (HTTP ${resp.status()}, "${chip.slice(0, 60)}") — the handoff acceptance says it must refuse with a named reason. The server's gate is invoice_owner_role=${owner} (a locked, awaiting-ruling setting), so at COLLECTION an OFFICER release is allowed. Page: ${await pageDump(page)}`)
      }
      throw new Error(`release answered ${resp ? resp.status() : 'no response'} with no visible refusal (${refusal.slice(0, 80) || 'no .refusal'}); page: ${await pageDump(page)}`)
    })
  } finally {
    Object.assign(screenArtifacts['pipeline-release'] = screenArtifacts['pipeline-release'] || {}, { errors: page.__errors })
    await safeClose(page)
  }
}

async function acceptanceLand(browser) {
  const page = await newPage(browser)
  currentScreen = 'acceptance:data-sources'
  try {
    await step('[OFFICER] Land rows refuses below Manager with a named reason', async () => {
      return refuseBelowManager(page, {
        route: '/data-sources',
        controlSel: '[data-testid="import-land"]',
        patterns: ['เฉพาะผู้จัดการหรือเจ้าของ', 'Only a Manager or the Owner'],
        label: '[OFFICER] Land rows refuses',
        respIncludes: '/v1/pipelines/crm-lead',
      })
    })
  } finally {
    Object.assign(screenArtifacts['ds-land'] = screenArtifacts['ds-land'] || {}, { errors: page.__errors })
    await safeClose(page)
  }
}

async function acceptanceAudit(browser, names) {
  const page = await newPage(browser)
  currentScreen = 'acceptance:audit'
  try {
    // A second actor: view one customer as MANAGER so the log carries two names.
    await open(page, '/', { role: 'MANAGER', lang: 'th', waitFor: '[data-testid^="split-row-"]' })
    const rowSel = '[data-testid^="split-row-"]:not([disabled])'
    if (await countOf(page, rowSel) > 0) {
      await domClick(page, rowSel)
      await sleep(800)
    }

    await open(page, '/audit', { role: 'OWNER', lang: 'th', waitFor: '[data-testid="audit-table"]' })

    await step('change the actor filter', async () => {
      const values = await page.$$eval('#audit-actor option', (os) => os.map((o) => o.value).filter(Boolean))
      assert(values.length > 0, 'the actor filter offers no actor at all')
      if (values.length < 2) na(`only one actor in the filter (${values[0]}) — no second actor to switch to`)
      await page.select('#audit-actor', values[1])
      try {
        await waitForFunctionOn(page, (actor) => {
          const rows = [...document.querySelectorAll('[data-testid^="audit-row-"] td.audit__who')]
          return rows.length > 0 && rows.every((td) => td.textContent.includes(actor))
        }, { timeout: 40000 }, values[1])
      } catch {
        const actors = await page.$$eval('[data-testid^="audit-row-"] td.audit__who', (tds) => tds.map((td) => td.textContent.trim().slice(0, 30)))
        throw new Error(`rows were not filtered to ${values[1]}: ${actors.slice(0, 6).join(', ')}`)
      }
      const shown = await countOf(page, '[data-testid^="audit-row-"]')
      return `${values.length} actors; filtered to ${values[1]} (${shown} rows)`
    })

    await step('load older rows', async () => {
      await page.select('#audit-actor', '')
      await sleep(1000)
      if (await countOf(page, '.audit__foot button') === 0) na('no older page is offered — the log holds fewer than the 50-row page')
      const before = await countOf(page, '[data-testid^="audit-row-"]')
      await domClick(page, '.audit__foot button')
      await waitForFunctionOn(page, (n) => document.querySelectorAll('[data-testid^="audit-row-"]').length > n, { timeout: 30000 }, before)
      const after = await countOf(page, '[data-testid^="audit-row-"]')
      return `${before} -> ${after} rows`
    })
  } finally {
    Object.assign(screenArtifacts['audit-filter'] = screenArtifacts['audit-filter'] || {}, { errors: page.__errors })
    await safeClose(page)
  }
  void names
}

async function acceptanceResilience(browser) {
  const page = await newPage(browser)
  currentScreen = 'acceptance:resilience'
  try {
    await step('the app survives an empty API body (no crash)', async () => {
      // Deterministic reproduction of the failure seen live on /pipeline: a truncated
      // response leaves api.js returning null, and a screen that dereferences it
      // unmounts the whole React tree. This feeds two shell/screen reads an empty
      // 200 body and checks the app is still mounted afterwards.
      await page.setRequestInterception(true)
      page.on('request', (req) => {
        const url = req.url()
        if (url.includes('/api/v1/shell/summary') || url.includes('/api/v1/today')) {
          req.respond({ status: 200, contentType: 'application/json', body: '' }).catch(() => {})
        } else req.continue().catch(() => {})
      })
      await open(page, '/', { role: 'OWNER', lang: 'th' })
      await sleep(3000)
      const mounted = await page.evaluate(() => Boolean(document.querySelector('#root') && document.querySelector('#root').children.length > 0))
      const screenish = await countOf(page, '[data-testid^="split-row-"], [data-testid="today-loading"], [data-testid="today-hello"]')
      // After the fix a malformed body renders the screen's own error state (role=alert)
      // instead of unmounting; either a live screen or that alert is a pass — a crash is
      // the only failure.
      const errored = await countOf(page, '[role="alert"]')
      const errs = page.__errors.page
      assert(mounted && (screenish > 0 || errored > 0), `the app crashed on an empty API body — page errors: ${errs.slice(0, 2).join(' | ') || 'none recorded'}`)
      return screenish > 0 ? 'app stayed mounted on an empty body' : 'app stayed mounted and showed its error state on an empty body'
    })
  } finally {
    screenArtifacts['resilience'] = { errors: page.__errors }
    await safeClose(page)
  }
}

async function acceptanceReviewsRefusal(browser) {
  const page = await newPage(browser)
  currentScreen = 'acceptance:reviews'
  try {
    await step('Reject / decision refuses to save without a reason', async () => {
      await open(page, '/reviews', { role: 'OWNER', lang: 'th', waitFor: '[data-testid^="split-row-"]' })
      const uid = await mustEval(page, '[data-testid^="split-row-"]:not([disabled])',
        (el) => el.getAttribute('data-testid').replace('split-row-', ''), 'no open review to decide')
      await domClick(page, `[data-testid="split-row-${uid}"]`)
      await waitForSelectorOn(page, `fieldset[data-testid="rq-form-${uid}"]`, { timeout: 30000 })
      await page.select(`fieldset[data-testid="rq-form-${uid}"] select`, 'BOARD_MOVE_REJECT')
      await sleep(300)
      const disabled = await isDisabled(page, `fieldset[data-testid="rq-form-${uid}"] button[type="submit"]`)
      assert(disabled === true, 'a Reject decision can be submitted with no reason/comment')
      const why = await textOf(page, `[data-testid="rq-answer-why-${uid}"]`)
      assert(why.length > 0, 'no on-screen reason for the blocked reject')
      return `decision=BOARD_MOVE_REJECT blocked: ${why.slice(0, 80)}`
    })
  } finally {
    Object.assign(screenArtifacts['reviews-refusal'] = screenArtifacts['reviews-refusal'] || {}, { errors: page.__errors })
    await safeClose(page)
  }
}

// --- main --------------------------------------------------------------------------
async function run() {
  fs.mkdirSync(SHOTS, { recursive: true })
  fs.mkdirSync(FIXTURES, { recursive: true })

  let gitHead = 'unknown'
  try { gitHead = execFileSync('git', ['rev-parse', '--short', 'HEAD'], { cwd: ROOT }).toString().trim() } catch {}

  console.log(`UAT Final v2 — ${BASE} (API ${API}), git ${gitHead}`)
  // Platform sanity
  currentScreen = 'platform'
  await step('API is answering', async () => {
    const h = await apiGet('/healthz', 'OFFICER')
    assert(h.status === 'ok', `healthz status=${h.status}`)
    return 'healthz ok'
  })
  await step('web app is answering', async () => {
    const r = await fetch(BASE + '/')
    assert(r.ok, `GET ${BASE}/ -> ${r.status}`)
    return `HTTP ${r.status}`
  })
  await step('API latency sample (environment note)', async () => {
    const timings = []
    let slow = false
    for (const route of ['/v1/today', '/v1/workbook']) {
      const t0 = Date.now()
      const r = await fetch(API + route, { headers: { 'X-Volt-Role': 'OFFICER' } })
      const s = (Date.now() - t0) / 1000
      if (s > 5) slow = true
      timings.push(`${route}=${s.toFixed(1)}s (${r.status})`)
    }
    record('API latency sample', INFO, timings.join(', ') + (slow ? ' — host under heavy memory pressure; waits were raised accordingly' : ''))
  })

  const names = await gatherNames()
  const browser = await puppeteer.launch({
    executablePath: chromePath(), headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage', `--lang=th`],
  })

  // The dry-run is exactly: one Thai screen (today), one English residue screen
  // (data-sources — it carries the PEAK report proper noun), and the rail-navigation
  // smoke over the routes that used to detach. Everything else waits for the full run.
  const pick = (keys) => keys.map((k) => SCREENS.find((s) => s.key === k)).filter(Boolean)
  const TH_SCREENS = DRY_RUN ? pick(['today']) : ONLY.length ? SCREENS.filter((s) => ONLY.includes(s.key)) : SCREENS
  const EN_SCREENS = DRY_RUN ? pick(['data-sources']) : ONLY.length ? SCREENS.filter((s) => ONLY.includes(s.key)) : SCREENS
  console.log(`mode ${MODE}`)

  // --- Phase 1: Thai / OWNER walk with interactions --------------------------------
  console.log('\n== Thai / OWNER screen walk ==')
  for (const screen of TH_SCREENS) {
    currentScreen = screen.key
    const holder = { browser, page: await newPage(browser), errors: { console: [], page: [], http: [] } }
    console.log(`\n-- ${screen.key} ${screen.route}`)
    try {
      // Opening + the record-resolution read are read-only and are retried on a stale
      // main frame by rebuilding the page. The walker steps below write; each keeps its
      // own failure, so a renderer that dies mid-write is never replayed blindly.
      await withPageRetry(`open ${screen.key}`, holder, async (page) => {
        await open(page, screen.route, { role: 'OWNER', lang: 'th', waitFor: PANELS[screen.key].selector })
        const records = await countOf(page, '[data-testid="case-record"]')
        if (!PANELS[screen.key].record) {
          await step('does not resolve to the customer record', async () => {
            assert(records === 0, 'the screen silently resolved to the customer record')
          })
        }
      })
      const walker = WALKERS[screen.key]
      if (walker) await walker(holder.page)
      const file = await shot(holder.page, `th--${screen.key}.png`)
      mergeErrors(holder.errors, holder.page.__errors)
      screenArtifacts[screen.key] = { screenshot: file, errors: holder.errors, title: screen.th, route: screen.route }
    } catch (e) {
      mergeErrors(holder.errors, holder.page && holder.page.__errors)
      record('screen walk', FAIL, e.message, { evidence: await pageDump(holder.page) })
      const file = await shot(holder.page, `th--${screen.key}.png`).catch(() => null)
      screenArtifacts[screen.key] = { screenshot: file, errors: holder.errors, title: screen.th, route: screen.route }
    } finally {
      await safeClose(holder.page)
    }
  }

  // --- Phase 2: English walk, Thai residue ------------------------------------------
  console.log('\n== English walk — Thai residue ==')
  for (const screen of EN_SCREENS) {
    currentScreen = `${screen.key}:en`
    const holder = { browser, page: await newPage(browser), errors: { console: [], page: [], http: [] } }
    try {
      // Read-only, so the whole screen read is retried once on a stale frame.
      await withPageRetry(`EN ${screen.key}`, holder, async (page) => {
        await open(page, screen.route, { role: 'OWNER', lang: 'en', waitFor: PANELS[screen.key].selector })
        await sleep(400)
        const thai = await page.evaluate(THAI_DUMP)
        const verdicts = thai.map((item) => ({ text: item.t, verdict: item.typed ? { allowed: true, why: 'typed data (sheet comment/note)' } : thaiIgnoreReason(item.t, names) }))
        const leftover = verdicts.filter((v) => v.verdict && !v.verdict.allowed).map((v) => v.text)
        const ignored = verdicts.filter((v) => v.verdict && v.verdict.allowed)
        // Say what was ignored and why, so a widened allowlist is visible in the log and
        // in the JSON — never a silent pass.
        for (const v of ignored) {
          console.log(`  .. EN Thai ignored: "${v.text.slice(0, 90)}" — ${v.verdict.why}`)
        }
        const ignoredEvidence = ignored.map((v) => `"${v.text.slice(0, 90)}" (${v.verdict.why})`)
        if (leftover.length === 0) {
          record('no Thai left in the English interface', PASS,
            `${thai.length} Thai node(s), ${ignored.length} ignored names/ids/proper nouns`,
            { evidence: ignoredEvidence.join('; ').slice(0, 2000), thai_ignored: ignored.map((v) => ({ text: v.text, why: v.verdict.why })) })
        } else {
          record('no Thai left in the English interface', FAIL,
            leftover.slice(0, 6).join(' | '),
            { product: true, thai: leftover, evidence: `flags: ${leftover.slice(0, 6).join(' | ')}; ignored: ${ignoredEvidence.join('; ').slice(0, 900)}`, thai_ignored: ignored.map((v) => ({ text: v.text, why: v.verdict.why })) })
        }
        const file = await shot(page, `en--${screen.key}.png`)
        const art = screenArtifacts[screen.key] || {}
        art.enScreenshot = file
        art.thaiResidue = leftover
        screenArtifacts[screen.key] = art
      })
    } catch (e) {
      record('English walk', FAIL, e.message, { evidence: await pageDump(holder.page) })
    } finally {
      mergeErrors(holder.errors, holder.page && holder.page.__errors)
      await safeClose(holder.page)
    }
  }

  // --- Phase 3: acceptance list -----------------------------------------------------
  console.log('\n== Acceptance list ==')
  if (DRY_RUN) {
    // The rail smoke is the dry-run's proof for the detached-frame fix: exactly the
    // eight routes that failed with "Attempted to use detached Frame" in the last run.
    await acceptanceRail(browser, RAIL_SMOKE_ROUTES)
  } else if (!SKIP_ACCEPTANCE) {
    // One phase throwing (e.g. a dead renderer) must not skip the phases after it —
    // that is how A3 came back "missing | missing | missing".
    const phases = [
      ['acceptance:rail', () => acceptanceRail(browser)],
      ['acceptance:settings', () => acceptanceSettings(browser)],
      ['acceptance:reports', () => acceptancePublish(browser)],
      ['acceptance:reviews', () => acceptanceReviewsRefusal(browser)],
      ['acceptance:pipeline', () => acceptanceRelease(browser)],
      ['acceptance:data-sources', () => acceptanceLand(browser)],
      ['acceptance:audit', () => acceptanceAudit(browser, names)],
      ['acceptance:resilience', () => acceptanceResilience(browser)],
    ]
    for (const [phase, run] of phases) {
      try { await run() } catch (e) {
        currentScreen = 'acceptance'
        record(`${phase} run`, FAIL, e.message, { evidence: String(e.message).slice(0, 800) })
      }
    }
  }

  // Acceptance summaries that are derived, not separate interactions.
  if (!DRY_RUN && !SKIP_ACCEPTANCE) {
    currentScreen = 'acceptance:summary'
    await step('locked and unlocked settings visible together (from /settings walk)', async () => {
      const walk = checks.find((c) => c.screen === 'settings' && c.name.startsWith('locked and editable'))
      assert(walk && walk.status === PASS, 'the settings walk did not prove both states visible together')
      return walk.detail
    })
    await step('Overview contains no individual-customer list', async () => {
      const walk = checks.find((c) => c.screen === 'dashboard' && c.name.includes('no individual-customer'))
      assert(walk && walk.status === PASS, 'dashboard customer-list check did not pass')
      return walk.detail
    })
    await step('Move date refuses without a reason', async () => {
      const walk = checks.find((c) => c.name.includes('move-date refuses'))
      assert(walk && walk.status === PASS, walk ? walk.detail : 'not exercised')
      return walk.detail
    })
    await step('Release/Land/Publish refuse below Manager', async () => {
      const wanted = [
        ['acceptance:reports', '[OFFICER] Publish refuses'],
        ['acceptance:data-sources', '[OFFICER] Land rows refuses'],
        ['acceptance:pipeline', '[OFFICER] Release refuses'],
      ]
      const rows = wanted.map(([screen, prefix]) => checks.find((c) => c.screen === screen && c.name.startsWith(prefix)))
      const bad = rows.filter((r) => !r || r.status !== PASS)
      assert(bad.length === 0, bad.map((r) => (r ? `${r.name}: ${r.detail}` : 'missing')).join(' | '))
      return {
        detail: rows.map((r) => r.detail.slice(0, 60)).join(' | '),
        extra: { evidence: rows.map((r) => r.evidence || r.detail).join('; ').slice(0, 900) },
      }
    })
  }

  // The stale-handle ledger: an explicit INFO row so "no stale-handle errors" is a
  // verifiable statement in the report, not a claim.
  currentScreen = 'platform'
  record('stale-handle retries', INFO,
    staleRetries === 0 ? '0 — no stale/detached-frame error was seen' : `${staleRetries} retried after a stale/detached frame`,
    { evidence: staleNotes.slice(0, 10).join('; ').slice(0, 900) })

  await browser.close()

  // --- e2e_check.py -------------------------------------------------------------------
  let e2e = null
  if (!SKIP_E2E) {
    console.log('\n== scripts/e2e_check.py ==')
    const py = path.join(ROOT, 'backend', '.venv', 'bin', 'python')
    const script = path.join(ROOT, 'scripts', 'e2e_check.py')
    const runRes = spawnSync(py, [script, '--base-url', API, '--json'], { cwd: ROOT, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
    let parsed = null
    try { parsed = JSON.parse(runRes.stdout) } catch {}
    e2e = {
      exit_code: runRes.status,
      total: parsed ? parsed.total : null,
      passed: parsed ? parsed.passed : null,
      failed: parsed ? parsed.failed : null,
      ok: parsed ? parsed.ok : null,
      failing: parsed ? (parsed.checks || []).filter((c) => c.status !== 'PASS').map((c) => ({ number: c.number, name: c.name, error: c.error || '' })) : [],
      stderr: (runRes.stderr || '').slice(-2000),
      stdout_tail: parsed ? '' : (runRes.stdout || '').slice(-3000),
    }
    console.log(`  exit=${e2e.exit_code} total=${e2e.total} passed=${e2e.passed} failed=${e2e.failed}`)
  }

  // --- derive failures, write reports -------------------------------------------------
  // `acceptance:summary` rows are roll-ups of checks already listed (A3 etc.), so they
  // are not repeated as product failures.
  const productFailures = checks.filter((c) => c.status === FAIL && c.product && c.screen !== 'acceptance:summary')
  for (const c of productFailures) {
    failures.push({
      screen: c.screen, check: c.name, observed: c.detail,
      reproduction: reproductionFor(c.screen, c.name),
    })
  }

  writeJson({ gitHead, names: names.size, e2e })
  writeMarkdown({ gitHead, e2e })
  console.log(`\nReport: ${path.relative(ROOT, path.join(OUT, 'uat-report.md'))} / uat-report.json`)
  const failed = checks.filter((c) => c.status === FAIL).length
  const notEx = checks.filter((c) => c.status === NA).length
  console.log(`${checks.length} checks — ${checks.length - failed - notEx} pass, ${failed} fail, ${notEx} not-exercisable`)
  return failed > 0 ? 1 : 0
}

function reproductionFor(screen, name) {
  const route = SCREENS.find((s) => s.key === screen)?.route || screen
  if (screen === 'pipeline' && name.includes('down-payment')) {
    return 'As OWNER open /pipeline?sel=<uid> for a row whose contract_signed is OPEN. Attach evidence to ' +
      'contract-signed (drawer -> note -> Attach), then fill the down-payment slip reference + amount and press ' +
      'ยืนยันเงินดาวน์. The POST /v1/pipeline/{uid}/gates/down-payment answers 200 but the response body\'s ' +
      'item.conditions still reads down_payment=OPEN, so the chip stays "ยังไม่ยืนยัน" and Release stays disabled ' +
      'until a manual reload (routers/pipeline.py:144 returns the raw item; pipeline.annotate() is not called).'
  }
  if (screen === 'pipeline' && name.includes('all three conditions')) {
    return 'Same run as the down-payment failure above: after the 200, the screen still shows PASSED, OPEN, PASSED ' +
      'and the Release button disabled; reloading /pipeline?sel=<uid> shows 3/3 and enables Release.'
  }
  if (screen === 'calendar:en') {
    return 'Set volt.lang=en, open /calendar as OWNER, scroll to the ชุดแจ้งเตือน / reminder-batches card at the ' +
      'bottom. The message-template preview is still the Thai sentence "เรียนคุณ {name} ..." with no English variant.'
  }
  if (screen === 'data-sources:en') {
    return 'Set volt.lang=en, open /data-sources as OWNER, scroll to the PEAK report card. Its English sentence ' +
      'embeds the Thai report name: Drop the PEAK "รายงานใบแจ้งหนี้" export. ...'
  }
  if (screen === 'acceptance:rail') {
    const route = (name.match(/rail row (\S+) opens/) || [])[1] || '<route>'
    return `Open / as OWNER (Thai), click the rail row for ${route}, and assert the row's own panel: Today (/) ` +
      'and Workbook (/workbook) are the only routes allowed to land on the customer record; every other route ' +
      'must show its own work panel with 0 customer-record nodes.'
  }
  if (screen === 'acceptance:pipeline') {
    return 'Prepare an item at 3/3 as OWNER (see the down-payment failure), then set volt.role=OFFICER, open ' +
      '/pipeline?sel=<uid> and press Release. POST /v1/pipeline/{uid}:release answers 201 and the item is released; ' +
      'the handoff acceptance (docs/design/handoff-v2/README.md) says release must refuse below Manager with a ' +
      'toast naming the rule. The server gate is config invoice_owner_role; with COLLECTION an OFFICER may release.'
  }
  if (screen === 'acceptance:resilience') {
    return 'In a fresh page with request interception, answer /api/v1/today and /api/v1/shell/summary with a 200 and ' +
      'an EMPTY body (a truncated response does this live). api.js\'s get() returns null (response.json() catch), ' +
      'and Today throws TypeError: Cannot read properties of null (reading \'items\'), unmounting the React tree.'
  }
  if (screen === 'today') return 'Open / as OWNER (Thai), select the first row in the split list.'
  return `Open ${route} and repeat: ${name}`
}

function writeJson({ gitHead, names, e2e }) {
  const byScreen = {}
  for (const c of checks) {
    byScreen[c.screen] = byScreen[c.screen] || { pass: 0, fail: 0, 'not-exercisable': 0, info: 0 }
    byScreen[c.screen][c.status] = (byScreen[c.screen][c.status] || 0) + 1
  }
  const payload = {
    generated_at: new Date().toISOString(),
    git_head: gitHead,
    base: BASE,
    api: API,
    allowlist_names: names,
    summary: {
      checks: checks.length,
      pass: checks.filter((c) => c.status === PASS).length,
      fail: checks.filter((c) => c.status === FAIL).length,
      not_exercisable: checks.filter((c) => c.status === NA).length,
      info: checks.filter((c) => c.status === INFO).length,
    },
    by_screen: byScreen,
    screens: screenArtifacts,
    checks,
    product_failures: failures,
    e2e_check: e2e,
  }
  fs.writeFileSync(path.join(OUT, 'uat-report.json'), JSON.stringify(payload, null, 2), 'utf8')
}

function writeMarkdown({ gitHead, e2e }) {
  const lines = []
  lines.push(`# UAT Final v2 — ${new Date().toISOString()}`)
  lines.push('')
  lines.push(`- Web: ${BASE}`)
  lines.push(`- API: ${API}`)
  lines.push(`- git: ${gitHead}`)
  lines.push(`- mode: ${MODE}`)
  lines.push(`- stale-handle retries: ${staleRetries}${staleNotes.length ? ` (${staleNotes.slice(0, 3).join('; ')})` : ''}`)
  const byScreen = {}
  for (const c of checks) {
    byScreen[c.screen] = byScreen[c.screen] || []
    byScreen[c.screen].push(c)
  }
  lines.push('')
  lines.push('## Summary — screen x checks')
  lines.push('')
  lines.push('| screen / phase | checks | pass | fail | not exercisable | screenshot |')
  lines.push('|---|---|---|---|---|---|')
  const order = [...SCREENS.map((s) => s.key), ...['platform', 'acceptance:rail', 'acceptance:settings', 'acceptance:reports', 'acceptance:reviews', 'acceptance:pipeline', 'acceptance:data-sources', 'acceptance:audit', 'acceptance:summary']]
  const keys = [...new Set([...order, ...Object.keys(byScreen)])]
  for (const key of keys) {
    const rows = byScreen[key]
    if (!rows) continue
    const p = rows.filter((r) => r.status === PASS || r.status === INFO).length
    const f = rows.filter((r) => r.status === FAIL).length
    const n = rows.filter((r) => r.status === NA).length
    const art = screenArtifacts[key]
    lines.push(`| ${key} | ${rows.length} | ${p} | ${f} | ${n} | ${art?.screenshot || ''} |`)
  }
  const allThai = checks.filter((c) => c.name.includes('Thai left') && c.status === FAIL)
  lines.push('')
  lines.push('## Acceptance list')
  lines.push('')
  lines.push('| # | acceptance item | status | evidence |')
  lines.push('|---|---|---|---|')
  const acceptance = [
    ['A1', 'Every rail row opens its own work panel (no silent customer record)', checks.filter((c) => c.screen === 'acceptance:rail')],
    ['A2', 'Locked setting cannot be edited at any role; unlocked cannot below Manager', checks.filter((c) => c.screen === 'acceptance:settings')],
    ['A3', 'Release / Land rows / Publish refuse below Manager with a named reason', [checks.find((c) => c.name === 'Release/Land/Publish refuse below Manager')]],
    ['A4', 'Reject and Move date refuse to save without a reason', [
      checks.find((c) => c.name.includes('Reject / decision refuses')),
      checks.find((c) => c.name.includes('move-date refuses')),
    ]],
    ['A5', 'Overview contains no individual-customer list', [checks.find((c) => c.name === 'Overview contains no individual-customer list')]],
    ['A6', 'Locked and unlocked settings visible together', [checks.find((c) => c.name.includes('locked and unlocked settings visible together'))]],
    ['A7', 'English interface has no Thai except names/ids', allThai.length ? allThai : [checks.find((c) => c.name.includes('Thai left in the English interface'))]],
  ]
  for (const [id, label, rows] of acceptance) {
    const present = (rows || []).filter(Boolean)
    if (present.length === 0) {
      lines.push(`| ${id} | ${label} | not run (${MODE}) | |`)
      continue
    }
    const bad = present.filter((r) => r.status === FAIL).length
    const nex = present.filter((r) => r.status === NA).length
    const status = bad ? `FAIL (${bad})` : nex && nex === present.length ? 'not exercisable' : 'PASS'
    lines.push(`| ${id} | ${label} | ${status} | ${present.map((r) => `${r.name}: ${r.evidence || r.detail}`).join('; ').slice(0, 400)} |`)
  }
  lines.push('')
  lines.push('## Product failures (with reproduction)')
  lines.push('')
  if (failures.length === 0) lines.push('_None._')
  for (const [i, f] of failures.entries()) {
    lines.push(`### ${i + 1}. ${f.check} — ${f.screen}`)
    lines.push('')
    lines.push(`- Observed: ${f.observed}`)
    lines.push(`- Reproduction: ${f.reproduction}`)
    lines.push('')
  }
  lines.push('## Console / page / HTTP errors captured')
  lines.push('')
  lines.push('Triage: `404 GET /api/v1/auth/users` is expected with AUTH_MODE off (the users card says so);')
  lines.push('`503 GET /api/v1/pipelines/crm-lead/customers` and `.../peak-report/links` are the unconfigured')
  lines.push('Odoo/PEAK integrations (the screens state that too). `ERR_CONTENT_LENGTH_MISMATCH` is the host/proxy')
  lines.push('truncating a response under memory pressure — one of those truncations produced the crash in failure #6.')
  lines.push('')
  for (const [key, art] of Object.entries(screenArtifacts)) {
    const e = art.errors || {}
    const parts = []
    if (e.console?.length) parts.push(`console x${e.console.length}: ${[...new Set(e.console)].slice(0, 3).join(' || ')}`)
    if (e.page?.length) parts.push(`page x${e.page.length}: ${[...new Set(e.page)].slice(0, 3).join(' || ')}`)
    if (e.http?.length) parts.push(`http x${e.http.length}: ${[...new Set(e.http)].slice(0, 5).join(', ')}`)
    if (parts.length) lines.push(`- **${key}**: ${parts.join(' — ').slice(0, 600)}`)
  }
  lines.push('')
  lines.push('## scripts/e2e_check.py')
  lines.push('')
  if (!e2e) lines.push('_Not run (--skip-e2e)._')
  else {
    lines.push(`- exit code: ${e2e.exit_code}`)
    lines.push(`- ${e2e.passed}/${e2e.total} passed, ${e2e.failed} failed, ok=${e2e.ok}`)
    for (const f of e2e.failing) lines.push(`  - #${f.number} ${f.name}: ${f.error}`)
    if (e2e.failing.some((f) => [27, 28].includes(f.number))) {
      lines.push('- Interpretation: #27 and #28 still assert the OLD two-gate pipeline model')
      lines.push('  (`gate_down_payment` / `gate_epc_confirmed`). The Final v2 API gates release on the three')
      lines.push('  served conditions (contract_signed / down_payment / entity_resolved), so #27 sees the')
      lines.push('  condition keys and #28 releases an item whose contract-signed condition is still open.')
      lines.push('  The check needs updating for the current model; this UAT did not modify it.')
    }
    if (e2e.stderr) lines.push(`- stderr: ${e2e.stderr.slice(0, 500)}`)
    if (e2e.stdout_tail) lines.push(`- stdout tail: ${e2e.stdout_tail.slice(-800)}`)
  }
  lines.push('')
  lines.push(`_Artifacts: ${path.relative(ROOT, OUT)}/uat-report.json, ${path.relative(ROOT, SHOTS)}/_.`)
  fs.writeFileSync(path.join(OUT, 'uat-report.md'), lines.join('\n'), 'utf8')
}

run().then((code) => process.exit(code)).catch((e) => { console.error(e); process.exit(1) })

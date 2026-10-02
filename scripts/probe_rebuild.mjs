// Browser smoke pass for the rebuilt console: every lens, both languages, light and
// dark, with console errors collected and screenshots written to
// docs/design/rebuild-2026-09/evidence/. Run with the dev server on 5173 and the API
// on 8000 (vite proxies /api to it).
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'

const ROOT = '/Users/parattakorn/volt-debt-prototype'
const require = createRequire(path.join(ROOT, 'frontend', 'package.json'))
const puppeteer = require('puppeteer-core')

const BASE = 'http://localhost:5173'
const API = 'http://127.0.0.1:8000'
const OUT = path.join(ROOT, 'docs', 'design', 'rebuild-2026-09', 'evidence')
fs.mkdirSync(OUT, { recursive: true })

const dir = path.join(ROOT, '.uat-browser', 'chrome')
const ver = fs.readdirSync(dir).find((d) => d.startsWith('mac_'))
const exe = path.join(dir, ver, 'chrome-mac-arm64', 'Google Chrome for Testing.app', 'Contents', 'MacOS', 'Google Chrome for Testing')

// Auth on? Sign in once with a test account so the API calls and the browser carry
// the session. Passwords live outside the repo (~/.volt-test-accounts.json, mode 600).
const authConfig = await (await fetch(`${API}/v1/auth/config`)).json().catch(() => ({ mode: 'off' }))
let creds = null
let apiCookie = ''
if (authConfig.mode === 'on') {
  const book = JSON.parse(fs.readFileSync(path.join(os.homedir(), '.volt-test-accounts.json'), 'utf8'))
  creds = { username: 'manager.test', password: book['manager.test'] }
  const res = await fetch(`${API}/v1/auth/password`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(creds),
  })
  if (!res.ok) {
    console.error(`auth is on and the probe could not sign in as ${creds.username} (${res.status})`)
    process.exit(1)
  }
  apiCookie = (res.headers.get('set-cookie') || '').split(';')[0]
  console.log(`auth on — signed in as ${creds.username}`)
}

const today = await (await fetch(`${API}/v1/today`, {
  headers: { 'X-Volt-Role': 'MANAGER', ...(apiCookie ? { Cookie: apiCookie } : {}) },
})).json()
const uid = today.items?.[0]?.customer?.uid

const ROUTES = [
  ['today', '/'],
  ['book', '/book'],
  ['customer', `/customers/${uid}`],
  ['reviews', '/reviews'],
  ['pipeline', '/pipeline'],
  ['payments', '/payments'],
  ['recovery', '/recovery'],
  ['dashboard', '/dashboard'],
  ['calendar', '/calendar'],
  ['reports', '/reports'],
  ['settings', '/settings'],
  ['data', '/data-sources'],
  ['audit', '/audit'],
]

const browser = await puppeteer.launch({ executablePath: exe, headless: true, args: ['--no-sandbox'] })
const page = await browser.newPage()
await page.setViewport({ width: 1440, height: 900 })

const problems = []
page.on('pageerror', (e) => problems.push(`PAGEERROR ${String(e).slice(0, 240)}`))
page.on('console', (m) => { if (m.type() === 'error') problems.push(`CONSOLE ${m.text().slice(0, 240)}`) })

async function setPrefs(lang, theme) {
  await page.evaluate((lang, theme) => {
    localStorage.setItem('volt.role', 'MANAGER')
    localStorage.setItem('volt.officer', '')
    localStorage.setItem('volt.lang', lang)
    localStorage.setItem('volt.theme', theme)
    localStorage.setItem('volt.density', 'compact')
    localStorage.setItem('volt.shell.rail', 'open')
  }, lang, theme)
}

/** The login card, once, when the API runs with AUTH_MODE=on. */
async function signIn() {
  if (!creds) return
  await page.waitForSelector('#login-user', { timeout: 8000 })
  await page.type('#login-user', creds.username)
  await page.type('#login-pass', creds.password)
  await page.click('form button[type=submit]')
  await page.waitForSelector('main.main', { timeout: 8000 })
}

// Sign in once, before the matrix, so the pre-login 401s never land in a view's log.
if (creds) {
  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  // The login card is evidence too: Google's rendered button mounts into the host
  // when the client id is served (it stays empty when the origin is not allowed).
  await page.waitForSelector('.login__googleHost', { timeout: 8000 }).catch(() => {})
  await page.waitForFunction(
    () => (document.querySelector('.login__googleHost')?.innerHTML.length || 0) > 100,
    { timeout: 8000 },
  ).catch(() => {})
  await page.screenshot({ path: path.join(OUT, 'th-light-1440-login.png') })
  await signIn()
  problems.length = 0
}

const results = []
for (const [name, route] of ROUTES) {
  for (const [lang, theme] of [['th', 'light'], ['en', 'dark']]) {
    problems.length = 0
    await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' })
    await setPrefs(lang, theme)
    await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' })
    try {
      await page.waitForSelector('main.main', { timeout: 8000 })
      // Wait until the rail has a served summary (its placeholder is an em dash),
      // then give the lens's own fetch a beat to paint.
      await page.waitForFunction(
        () => {
          const k = document.querySelector('.rail__kpi')
          return k && !k.innerText.includes('—')
        },
        { timeout: 9000 },
      ).catch(() => {})
      // A slow lens must not be photographed mid-load: give the main pane a beat to
      // replace its loading line with served content.
      await page.waitForFunction(
        () => (document.querySelector('main.main')?.innerText || '').length > 60,
        { timeout: 8000 },
      ).catch(() => {})
      await new Promise((r) => setTimeout(r, 1200))
      await page.screenshot({ path: path.join(OUT, `${lang}-${theme}-1440-${name}.png`), fullPage: true })
      const text = await page.evaluate(() => document.querySelector('main.main')?.innerText || '')
      results.push({ name, lang, theme, ok: true, chars: text.length, problems: [...problems] })
    } catch (e) {
      results.push({ name, lang, theme, ok: false, error: String(e).slice(0, 160), problems: [...problems] })
    }
  }
}

// A narrow pass: the record pane in the two-pane split is the layout that used to
// overlap its money figures, and Settings is the screen this round redesigned.
await page.setViewport({ width: 1280, height: 860 })
for (const [name, route] of [['today', '/'], ['customer', `/customers/${uid}`], ['settings', '/settings']]) {
  problems.length = 0
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' })
  await setPrefs('th', 'light')
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' })
  try {
    await page.waitForSelector('main.main', { timeout: 8000 })
    await page.waitForFunction(
      () => {
        const k = document.querySelector('.rail__kpi')
        return k && !k.innerText.includes('—')
      },
      { timeout: 9000 },
    ).catch(() => {})
    await new Promise((r) => setTimeout(r, 1500))
    // Viewport-only: a full-page capture expands the viewport and the sticky queue
    // panel can drop out of the frame, which would misreport the narrow layout.
    await page.screenshot({ path: path.join(OUT, `th-light-1280-${name}.png`) })
    const text = await page.evaluate(() => document.querySelector('main.main')?.innerText || '')
    results.push({ name: `${name}@1280`, lang: 'th', theme: 'light', ok: true, chars: text.length, problems: [...problems] })
  } catch (e) {
    results.push({ name: `${name}@1280`, lang: 'th', theme: 'light', ok: false, error: String(e).slice(0, 160), problems: [...problems] })
  }
}

await browser.close()
let failed = 0
for (const r of results) {
  const bad = r.problems.length || !r.ok
  if (bad) failed++
  console.log(`${r.ok ? 'OK  ' : 'FAIL'} ${r.lang}/${r.theme} ${r.name} ${r.chars ? `(${r.chars} chars)` : ''} ${r.error || ''}`)
  for (const p of r.problems.slice(0, 3)) console.log('     ', p)
}
console.log(failed ? `\n${failed} view(s) with problems` : '\nall views clean')
process.exit(failed ? 1 : 0)

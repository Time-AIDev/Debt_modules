#!/usr/bin/env node
/**
 * uat_browser.mjs — a text-mode window onto the running prototype for the blind
 * UAT rounds (UAT_Blind_Round_Protocol.md lives in the Drive decision records). It drives Chrome for Testing
 * (installed under .uat-browser/) with puppeteer-core and prints what a person
 * would see: headings, text, and every interactive element with an index.
 *
 * Usage
 *   node scripts/uat_browser.mjs <path-or-url> [--role OFFICER|SUPERVISOR|MANAGER|OWNER]
 *        UAT_USER=manager UAT_PASS=... signs in first (a deployed estate has AUTH on)
 *        [--lang th|en] [--profile name] [--shot file.png] [--actions actions.json] [--wait ms] [--max 400]
 *   --profile keeps cookies (the API session) between runs, so a persona's work persists.
 *
 * actions.json is a list executed in order after load, each printed with the
 * resulting screen:
 *   {"click": 12}                  click element #12 from the last listing
 *   {"click": "บันทึกการติดต่อ"}          click the first element whose text contains this
 *   {"type": 7, "value": "3199"}   type into element #7 (input/textarea)
 *   {"select": 9, "value": "CALLBACK"}   choose an option value in select #9
 *   {"check": 4}                   toggle a checkbox
 *   {"goto": "/workbook"}          navigate
 *   {"wait": 800}                  pause
 *   {"shot": "after-step-3.png"}   screenshot
 *
 * Every run is a fresh browser; the app's own state lives in the API session
 * cookie, which is kept for the run.
 */
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..')
// puppeteer-core is a devDependency of the frontend package, so resolve it from there.
const require = createRequire(path.join(ROOT, 'frontend', 'package.json'))
const puppeteer = require('puppeteer-core')
const BASE = process.env.UAT_BASE || 'http://localhost:5173'

function chromePath() {
  const dir = path.join(ROOT, '.uat-browser', 'chrome')
  if (!fs.existsSync(dir)) throw new Error('no Chrome for Testing under .uat-browser/ — run: npx @puppeteer/browsers install chrome@stable --path .uat-browser')
  const ver = fs.readdirSync(dir).find((d) => d.startsWith('mac_'))
  const app = path.join(dir, ver, 'chrome-mac-arm64', 'Google Chrome for Testing.app', 'Contents', 'MacOS', 'Google Chrome for Testing')
  if (!fs.existsSync(app)) throw new Error('Chrome binary not found at ' + app)
  return app
}

function arg(name, dflt) {
  const i = process.argv.indexOf(name)
  return i > 0 ? process.argv[i + 1] : dflt
}

const target = process.argv[2] && !process.argv[2].startsWith('--') ? process.argv[2] : '/'
const role = arg('--role', 'OFFICER')
const lang = arg('--lang', 'th')
const shot = arg('--shot', null)
const actionsFile = arg('--actions', null)
const waitMs = Number(arg('--wait', 900))
const maxLines = Number(arg('--max', 400))
const profile = arg('--profile', null)

const DUMP = `(() => {
  const out = []; const els = [];
  const seen = new Set();
  const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const label = (el) => {
    const aria = el.getAttribute && (el.getAttribute('aria-label') || el.getAttribute('title'));
    if (aria) return aria;
    if (el.labels && el.labels.length) return Array.from(el.labels).map(l => l.textContent.trim()).join(' ');
    if (el.placeholder) return el.placeholder;
    return (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
  };
  const walk = (node, depth) => {
    if (node.nodeType !== 1) return;
    const el = node;
    if (!visible(el)) return;
    const tag = el.tagName.toLowerCase();
    if (['script','style','svg','path'].includes(tag)) return;
    const interactive = el.matches('a[href],button,input,select,textarea,[role=button],[role=tab],[role=radio],[role=switch],[tabindex="0"]');
    if (interactive) {
      const idx = els.push(el);
      const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';
      let extra = '';
      if (tag === 'input') extra = ' type=' + (el.type || 'text') + (el.value ? ' value="' + String(el.value).slice(0, 40) + '"' : '') + (el.checked ? ' checked' : '');
      if (tag === 'select') extra = ' value=' + el.value + ' options=[' + Array.from(el.options).slice(0, 25).map(o => o.value + (o.textContent.trim() && o.textContent.trim() !== o.value ? ':' + o.textContent.trim().slice(0, 30) : '')).join(' | ') + ']';
      if (tag === 'a') extra = ' href=' + el.getAttribute('href');
      if (tag === 'textarea') extra = el.value ? ' value="' + el.value.slice(0, 40) + '"' : '';
      out.push('  '.repeat(Math.min(depth, 6)) + '[' + idx + '] <' + tag + (el.getAttribute('role') ? ' role=' + el.getAttribute('role') : '') + (disabled ? ' DISABLED' : '') + extra + '> ' + label(el));
      if (tag !== 'a' && tag !== 'button') return;
      return;
    }
    if (/^h[1-6]$/.test(tag)) { out.push('  '.repeat(Math.min(depth, 6)) + '#'.repeat(Number(tag[1])) + ' ' + (el.textContent || '').trim().replace(/\\s+/g, ' ')); return; }
    const own = Array.from(el.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent.trim()).filter(Boolean).join(' ');
    if (own && !seen.has(own + depth)) { out.push('  '.repeat(Math.min(depth, 6)) + own.replace(/\\s+/g, ' ').slice(0, 200)); seen.add(own + depth); }
    for (const c of el.children) walk(c, depth + 1);
  };
  walk(document.body, 0);
  window.__uatEls = els;
  return { url: location.pathname + location.search, title: document.title, lines: out };
})()`

async function dump(page, note) {
  await new Promise((r) => setTimeout(r, waitMs))
  const d = await page.evaluate(DUMP)
  const lines = d.lines.slice(0, maxLines)
  console.log('\n===== ' + (note || 'screen') + ' · ' + d.url + ' · role=' + role + ' lang=' + lang + ' =====')
  console.log(lines.join('\n'))
  if (d.lines.length > maxLines) console.log('… ' + (d.lines.length - maxLines) + ' more lines (raise --max)')
  return d
}

async function findByText(page, text) {
  return page.evaluate((t) => {
    const els = window.__uatEls || []
    const i = els.findIndex((el) => (el.textContent || el.getAttribute('aria-label') || '').includes(t))
    return i >= 0 ? i + 1 : -1
  }, text)
}

async function main() {
  const launch = { executablePath: chromePath(), headless: true, args: ['--no-sandbox', '--lang=' + lang] }
  if (profile) launch.userDataDir = path.join(ROOT, '.uat-browser', 'profiles', profile)
  const browser = await puppeteer.launch(launch)
  const page = await browser.newPage()
  await page.setViewport({ width: 1366, height: 900 })
  page.on('pageerror', (e) => console.log('!! page error: ' + e.message))
  page.on('console', (m) => { if (m.type() === 'error') console.log('!! console error: ' + m.text().slice(0, 200)) })
  const url = target.startsWith('http') ? target : BASE + target
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' })
  await page.evaluate((r, l) => { try { localStorage.setItem('volt.role', r); localStorage.setItem('volt.lang', l); localStorage.setItem('volt.theme', 'light') } catch {} }, role, lang)
  // 2026-09-21: a deployed estate runs AUTH_MODE=on, so every page redirects to the
  // login until the session cookie exists. UAT_USER/UAT_PASS sign in once here (the
  // same POST the login form makes) and hand the cookie to the browser; a local run
  // without them behaves exactly as before.
  const uatUser = process.env.UAT_USER
  const uatPass = process.env.UAT_PASS
  if (uatUser && uatPass) {
    const res = await fetch(BASE + '/v1/auth/password', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ username: uatUser, password: uatPass }),
    })
    const setCookies = res.headers.getSetCookie ? res.headers.getSetCookie() : [res.headers.get('set-cookie') || '']
    // EVERY cookie the login sets: volt_auth is the signed session and volt_session
    // is the sandbox id. Keeping only volt_session showed the login screen again with
    // a 401 on the next request (2026-09-21) — the same mistake e2e_check made.
    const pairs = setCookies.map((c) => (c || '').split(';')[0]).filter((c) => c.includes('='))
    if (res.status !== 200 || pairs.length === 0) {
      throw new Error('login failed for ' + uatUser + ': HTTP ' + res.status)
    }
    for (const pair of pairs) {
      const i = pair.indexOf('=')
      await browser.setCookie({
        name: pair.slice(0, i).trim(), value: pair.slice(i + 1).trim(),
        domain: new URL(BASE).hostname, path: '/', httpOnly: true, sameSite: 'Lax',
      })
    }
    console.log('signed in as ' + uatUser + ' (' + pairs.map((c) => c.split('=')[0]).join(', ') + ')')
  }
  await page.goto(url, { waitUntil: 'networkidle0' })
  await dump(page, 'loaded')
  if (shot) { await page.screenshot({ path: shot, fullPage: true }); console.log('screenshot -> ' + shot) }
  if (actionsFile) {
    const actions = JSON.parse(fs.readFileSync(actionsFile, 'utf8'))
    for (const [n, a] of actions.entries()) {
      try {
        if (a.goto) { await page.goto(BASE + a.goto, { waitUntil: 'networkidle0' }) }
        else if (a.wait) { await new Promise((r) => setTimeout(r, a.wait)) }
        else if (a.shot) { await page.screenshot({ path: a.shot, fullPage: true }); console.log('screenshot -> ' + a.shot); continue }
        else {
          let idx = a.click ?? a.type ?? a.select ?? a.check
          if (typeof idx === 'string') { idx = await findByText(page, idx); if (idx < 0) { console.log('!! no element containing "' + (a.click ?? a.type ?? a.select ?? a.check) + '"'); continue } }
          const handle = await page.evaluateHandle((i) => (window.__uatEls || [])[i - 1], idx)
          const el = handle.asElement()
          if (!el) { console.log('!! no element #' + idx); continue }
          if (a.click !== undefined || a.check !== undefined) { await el.click() }
          else if (a.type !== undefined) {
            const kind = await el.evaluate((n) => n.type)
            if (kind === 'date') {
              // A date input takes a value, not keystrokes (typing digits mangles the year).
              await el.evaluate((n, v) => { const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; setter.call(n, v); n.dispatchEvent(new Event('input', { bubbles: true })); n.dispatchEvent(new Event('change', { bubbles: true })) }, String(a.value ?? ''))
            } else { await el.click({ clickCount: 3 }); await el.type(String(a.value ?? '')) }
          }
          else if (a.select !== undefined) { await el.select(String(a.value)) }
        }
      } catch (e) { console.log('!! action ' + (n + 1) + ' failed: ' + e.message.split('\n')[0]) }
      await dump(page, 'after action ' + (n + 1) + ' ' + JSON.stringify(a))
    }
  }
  await browser.close()
}

main().catch((e) => { console.error(e.message); process.exit(1) })

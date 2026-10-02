#!/usr/bin/env node
/**
 * design_capture.mjs — screenshot the Final v2 prototype and the rebuilt app at
 * the same size so the two can be compared screen by screen.
 *
 *   node scripts/design_capture.mjs proto --out /tmp/cap/proto [--lang th|en] [--serve-url URL]
 *   node scripts/design_capture.mjs app   --out /tmp/cap/app   [--lang th|en] [--role OWNER] [--base URL]
 *
 * The prototype has no routes: its rail anchors are clicked by their label. The
 * app's routes carry the screen. Both are captured at 1440x900, viewport only,
 * which is the frame the handoff screenshots use.
 */
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { execFileSync } from 'node:child_process'

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..')
const require = createRequire(path.join(ROOT, 'frontend', 'package.json'))
const puppeteer = require('puppeteer-core')
const MCP_URL = 'https://api.anthropic.com/v1/design/mcp'
const PROJECT = '800e8d00-edf4-4954-954b-773f7f97ceb0'

const arg = (name, dflt) => {
  const i = process.argv.indexOf(name)
  return i > 0 ? process.argv[i + 1] : dflt
}

const SCREENS = [
  ['dash', 'ภาพรวม', 'Overview', '/dashboard'],
  ['today', 'วันนี้', 'Today', '/'],
  ['calendar', 'ปฏิทิน', 'Calendar', '/calendar'],
  ['book', 'ลูกค้า / สมุดงาน', 'Customers / Work book', '/workbook'],
  ['reviews', 'รอตรวจ', 'Reviews', '/reviews'],
  ['pipeline', 'ใบแจ้งหนี้ก่อนติดตั้ง', 'Pre-installation invoices', '/pipeline'],
  ['payments', 'เงินเข้าและ PEAK', 'Receipts & PEAK', '/payments'],
  ['recovery', 'NPL และการเรียกคืน', 'NPL & recovery', '/recovery'],
  ['reports', 'รายงาน', 'Reports', '/reports'],
  ['settings', 'ตั้งค่า', 'Settings', '/settings'],
  ['data', 'แหล่งข้อมูล', 'Data sources', '/data-sources'],
  ['audit', 'บันทึกการใช้งาน', 'Action log', '/audit'],
]

function chromePath() {
  const dir = path.join(ROOT, '.uat-browser', 'chrome')
  const ver = fs.readdirSync(dir).find((d) => d.startsWith('mac_'))
  return path.join(dir, ver, 'chrome-mac-arm64', 'Google Chrome for Testing.app', 'Contents', 'MacOS', 'Google Chrome for Testing')
}

async function token() {
  if (process.env.DESIGN_MCP_TOKEN) return process.env.DESIGN_MCP_TOKEN
  const raw = execFileSync('security', ['find-generic-password', '-s', 'Claude Code-credentials', '-w'], { encoding: 'utf8' })
  return JSON.parse(raw).designOauth.accessToken
}

async function serveUrl() {
  const res = await fetch(MCP_URL, {
    method: 'POST',
    headers: { Authorization: 'Bearer ' + (await token()), 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'render_preview', arguments: { project_id: PROJECT, path: 'Volt Debt - Final v2.dc.html' } } }),
  })
  const body = await res.text()
  return JSON.parse(JSON.parse(body).result.content[0].text).serve_url
}

async function main() {
  const target = process.argv[2]
  const out = arg('--out', `/tmp/design-capture/${target}`)
  const lang = arg('--lang', 'th')
  const role = arg('--role', 'OWNER')
  const base = arg('--base', 'http://localhost:5173')
  const width = Number(arg('--width', 1440))
  const height = Number(arg('--height', 900))
  fs.mkdirSync(out, { recursive: true })

  const browser = await puppeteer.launch({ executablePath: chromePath(), headless: 'new', args: ['--no-sandbox', '--lang=' + lang, '--force-device-scale-factor=1'] })
  const page = await browser.newPage()
  await page.setViewport({ width, height, deviceScaleFactor: 1 })
  page.on('pageerror', (e) => console.log('!! ' + e.message))

  if (target === 'proto') {
    const url = arg('--serve-url', await serveUrl())
    const clickText = (label) => page.evaluate((label) => {
      const b = [...document.querySelectorAll('button')].find((el) => (el.textContent || '').trim() === label)
      if (b) b.click()
      return !!b
    }, label)
    for (const [i, [id, th, en]] of SCREENS.entries()) {
      const label = lang === 'th' ? th : en
      await page.goto(url, { waitUntil: 'networkidle0' })
      await page.evaluate(() => new Promise((r) => setTimeout(r, 600)))
      if (lang === 'en') {
        await clickText('นวน')
        await page.evaluate(() => new Promise((r) => setTimeout(r, 300)))
        await clickText('English')
        await page.evaluate(() => new Promise((r) => setTimeout(r, 400)))
        // close the View popover again (its label is English now)
        await clickText('นวน')
        await clickText('View')
      }
      const ok = await page.evaluate((i) => {
        const a = [...document.querySelectorAll('nav a')][i]
        if (!a) return false
        a.click()
        return true
      }, i)
      if (!ok) { console.log(`!! rail row ${i} not found`); continue }
      await page.evaluate(() => new Promise((r) => setTimeout(r, 700)))
      await page.screenshot({ path: path.join(out, `${id}-${lang}.png`) })
      console.log(`${id}-${lang}.png  ${label}`)
    }
  } else {
    await page.goto(base + '/', { waitUntil: 'domcontentloaded' })
    await page.evaluate((r, l) => {
      try { localStorage.setItem('volt.role', r); localStorage.setItem('volt.lang', l); localStorage.setItem('volt.theme', 'light') } catch {}
    }, role, lang)
    for (const [id, , , route] of SCREENS) {
      await page.goto(base + route, { waitUntil: 'networkidle0' })
      await page.evaluate(() => new Promise((r) => setTimeout(r, 700)))
      await page.screenshot({ path: path.join(out, `${id}-${lang}.png`) })
      console.log(`${id}-${lang}.png  ${route}`)
    }
  }
  await browser.close()
}

main().catch((e) => { console.error(e.message); process.exit(1) })

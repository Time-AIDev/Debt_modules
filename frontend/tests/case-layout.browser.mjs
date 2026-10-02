import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { after, before, test } from 'node:test'
import puppeteer from 'puppeteer-core'

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const css = ['tokens', 'base', 'shell', 'today', 'case']
  .map((name) => fs.readFileSync(path.join(frontend, 'src', 'styles', `${name}.css`), 'utf8'))
  .join('\n')
const chrome = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
let browser

before(async () => { browser = await puppeteer.launch({ executablePath: chrome, headless: true }) })
after(async () => { await browser?.close() })

async function layout(kind, width = 1277) {
  const page = await browser.newPage()
  await page.setViewport({ width, height: 705 })
  const work = kind === 'today'
    ? '<div class="today"><div class="today__lens"></div><div class="work work--split today__work"><aside class="panel"><div class="panel__body"></div></aside><div class="today__case"><article class="case case--page"><header class="case__head"></header><div class="case__tabs"></div><div class="case__body"><section class="case__overview"><div class="case__main"></div><div class="case__side"></div></section></div></article></div></div></div>'
    : '<div class="stack"><div class="lensbar"></div><div class="work work--split"><aside class="panel"><div class="panel__body"></div></aside><article class="case case--page"><header class="case__head"></header><div class="case__tabs"></div><div class="case__body"><section class="case__overview"><div class="case__main"></div><div class="case__side"></div></section></div></article></div></div>'
  await page.setContent(`<style>${css}\n.chrome { height: 94px; flex: none; } .today__lens, .lensbar { height: 40px; } .case__head { height: 220px; } .case__tabs { height: 44px; } .case__main { height: 1100px; }</style><div class="shell"><aside style="flex: 0 0 246px"></aside><div class="shell__col"><div class="chrome"></div><main class="main">${work}</main></div></div>`)
  const result = await page.evaluate(() => {
    const caseEl = document.querySelector('.case')
    const body = document.querySelector('.case__body')
    const pane = document.querySelector('.panel')
    return {
      pageHeight: document.documentElement.scrollHeight,
      caseHeight: caseEl.getBoundingClientRect().height,
      caseLeft: caseEl.getBoundingClientRect().left,
      caseWidth: caseEl.getBoundingClientRect().width,
      bodyOverflow: getComputedStyle(body).overflowY,
      panelOverflow: getComputedStyle(pane.querySelector('.panel__body')).overflowY,
      overviewDirection: getComputedStyle(document.querySelector('.case__overview')).flexDirection,
    }
  })
  await page.close()
  return result
}

test('Today keeps the customer case in the page scroll while its list remains scrollable', async () => {
  const today = await layout('today')
  assert.ok(today.caseHeight > 1200, `case height was ${today.caseHeight}`)
  assert.ok(today.pageHeight > 1200, `page height was ${today.pageHeight}`)
  assert.equal(today.bodyOverflow, 'visible')
  assert.equal(today.panelOverflow, 'auto')
})

test('Today and Workbook give the case the same column and use its own width for card layout', async () => {
  const today = await layout('today', 1250)
  const book = await layout('book', 1250)
  assert.equal(today.caseLeft, book.caseLeft)
  assert.equal(today.caseWidth, book.caseWidth)
  assert.equal(today.overviewDirection, 'column')
  assert.equal(book.overviewDirection, 'column')
})

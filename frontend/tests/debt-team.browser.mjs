/** Read-only browser inventory for an isolated staging deployment.
 * UAT_BASE=http://127.0.0.1:5173 UAT_SESSION_FILE=/private/session.json
 * UAT_REVISION=<full SHA> CHROME_PATH=/usr/bin/chromium node frontend/tests/debt-team.browser.mjs
 * Session JSON may contain cookies and/or tab_token. It is never printed or saved.
 * This screen walk does not claim that mutation workflows or Google login passed.
 */
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { safeClose } from '../../scripts/browser_support.mjs'

const require = createRequire(new URL('../package.json', import.meta.url))
const puppeteer = require('puppeteer-core')
const base = process.env.UAT_BASE || 'http://127.0.0.1:5173'
const target = new URL(base)
if (!['127.0.0.1', 'localhost', '[::1]'].includes(target.hostname)) {
  throw new Error('This synthetic-session browser inventory requires an isolated loopback staging target')
}
const revision = process.env.UAT_REVISION
if (!/^[a-f0-9]{40}$/.test(revision || '')) throw new Error('UAT_REVISION must pin the full candidate commit')
const output = path.resolve(process.env.UAT_OUTPUT || '.test-artifacts/debt-team-browser')
fs.mkdirSync(output, { recursive: true, mode: 0o700 }); fs.chmodSync(output, 0o700)
const routes = ['/', '/?workstream=pre_install&entity=EPC', '/?entity=SPV', '/book?entity=EPC',
  '/book?entity=SPV', '/dashboard', '/calendar', '/reviews', '/payments', '/recovery', '/reports',
  '/settings', '/data-sources', '/audit', '/audit/accounting-reviews', '/audit/terminated',
  '/terminated?customer_uid=synthetic-history']
const report = { format: 'volt-debt-browser-inventory-v1', revision, target: base,
  started_at_utc: new Date().toISOString(), mode: 'isolated-staging-read-only',
  google_login_verified: false, mutation_workflows_verified: false, screens: [],
  required_manual_tasks: ['paired monthly evidence', 'ambiguous/missing identity review', 'contract supplement',
    'receipt/invoice auto matching and cancellations', 'installation confirmation and NPL exclusions',
    'deferral preview/confirm/reverse', 'accounting findings and immutable history',
    'repossession evidence import and explicit termination', 'history return with filter/scroll',
    'Officer/Manager/OPS role refusals', 'unknown network outcome recovery'], }
const browser = await puppeteer.launch({ executablePath: process.env.CHROME_PATH || '/usr/bin/chromium',
  headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] })
let page
try {
  page = await browser.newPage()
  const sessionPath = process.env.UAT_SESSION_FILE
  if (!sessionPath) throw new Error('An authenticated isolated-staging session is required')
  const stat = fs.statSync(sessionPath)
  if (!stat.isFile() || (stat.mode & 0o077) || stat.size > 65536) throw new Error('The staging session file must be private and bounded')
  const session = JSON.parse(fs.readFileSync(sessionPath, 'utf8'))
  if (session.cookies?.length) await browser.setCookie(...session.cookies)
  if (session.tab_token) await page.evaluateOnNewDocument((token) => {
    window.sessionStorage.setItem('volt.auth.tab', token)
  }, session.tab_token)
  await page.setViewport({ width: 1366, height: 900 })
  for (const [index, route] of routes.entries()) {
    const errors = { page: 0, console: 0, failed_requests: [], api_failures: [] }
    const onError = () => { errors.page += 1 }
    const onConsole = (message) => { if (message.type() === 'error') errors.console += 1 }
    const onFailure = (request) => { errors.failed_requests.push({ path: new URL(request.url()).pathname,
      error: request.failure()?.errorText || 'request_failed' }) }
    const onResponse = (response) => {
      const url = new URL(response.url())
      if (url.origin === target.origin && url.pathname.startsWith('/api/') && response.status() >= 400) {
        errors.api_failures.push({ path: url.pathname, status: response.status() })
      }
    }
    page.on('pageerror', onError); page.on('console', onConsole)
    page.on('requestfailed', onFailure); page.on('response', onResponse)
    let result
    try {
      const response = await page.goto(new URL(route, base).href, { waitUntil: 'networkidle0', timeout: 30000 })
      await page.waitForSelector('#main', { timeout: 15000 })
      const state = await page.evaluate(() => ({
        blank: !document.querySelector('#main')?.textContent.trim(),
        loginVisible: !!document.querySelector('[name="credential"]') || !!document.querySelector('.login'),
        company: document.querySelector('select[aria-label="EPC/SPV"]')?.value ?? null,
        auditActive: !!document.querySelector('.rail__link--on[href="/audit"]'),
      }))
      const expectedCompany = new URL(route, base).searchParams.get('entity')
      const screenshot = `${String(index).padStart(2, '0')}.png`
      await page.screenshot({ path: path.join(output, screenshot), fullPage: true })
      result = { route, status: response.status(), screenshot, ...state, ...errors,
        passed: response.status() === 200 && !state.blank && !state.loginVisible
          && !errors.page && !errors.console && !errors.failed_requests.length && !errors.api_failures.length
          && (!expectedCompany || state.company === expectedCompany)
          && (!route.startsWith('/audit') && !route.startsWith('/terminated') || state.auditActive) }
    } catch (error) { result = { route, passed: false, error: error.name || 'browser_failed', ...errors } }
    report.screens.push(result)
    page.off('pageerror', onError); page.off('console', onConsole)
    page.off('requestfailed', onFailure); page.off('response', onResponse)
  }
} catch (error) { report.setup_failed = error.message }
finally { await safeClose(page); await browser.close() }
report.completed_at_utc = new Date().toISOString()
report.passed = !report.setup_failed && report.screens.length === routes.length && report.screens.every((row) => row.passed)
fs.writeFileSync(path.join(output, 'inventory.json'), JSON.stringify(report, null, 2)+'\n', { mode: 0o600 })
console.log(JSON.stringify({ passed: report.passed, screens: report.screens.length, output,
  mutation_workflows_verified: false, google_login_verified: false }))
process.exitCode = report.passed ? 0 : 1

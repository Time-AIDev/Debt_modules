#!/usr/bin/env node
/**
 * design_mcp_fetch.mjs — import a Claude Design project through the claude_design
 * MCP (https://api.anthropic.com/v1/design/mcp) into a local folder.
 *
 * Auth comes from the claude.ai design grant that Claude Code stored when the
 * user ran /design-login: the OAuth record `designOauth` in the macOS keychain
 * item "Claude Code-credentials" (override with DESIGN_MCP_TOKEN). The token is
 * read per run and never written anywhere.
 *
 * Usage
 *   node scripts/design_mcp_fetch.mjs --project <uuid> --out docs/design/handoff-v2
 *        [--files "a.html,b.js"] [--no-screenshots]
 *
 * read_file pages by line and escapes only & < >, so text is rebuilt by decoding
 * those three entities exactly once and dropping the one separator newline the
 * server adds at the end of each window. Binary files (png) are fetched through
 * render_preview's short-lived serve URL.
 */
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { execFileSync } from 'node:child_process'

const MCP_URL = 'https://api.anthropic.com/v1/design/mcp'
const WINDOW = 400

function arg(name, dflt) {
  const i = process.argv.indexOf(name)
  return i > 0 ? process.argv[i + 1] : dflt
}

function token() {
  if (process.env.DESIGN_MCP_TOKEN) return process.env.DESIGN_MCP_TOKEN
  const raw = execFileSync('security', ['find-generic-password', '-s', 'Claude Code-credentials', '-w'], { encoding: 'utf8' })
  const creds = JSON.parse(raw)
  const t = creds?.designOauth?.accessToken
  if (!t) throw new Error('no designOauth accessToken — run /design-login in Claude Code first')
  return t
}

let TOKEN = token()
let RPC_ID = 0

async function rpc(method, params) {
  const res = await fetch(MCP_URL, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${TOKEN}`,
      'Content-Type': 'application/json',
      Accept: 'application/json, text/event-stream',
    },
    body: JSON.stringify({ jsonrpc: '2.0', id: ++RPC_ID, method, params }),
    signal: AbortSignal.timeout(120000),
  })
  if (!res.ok) throw new Error(`${method}: HTTP ${res.status} ${await res.text()}`)
  const raw = await res.text()
  const body = raw.startsWith('data:') ? raw.split('\n').find((l) => l.startsWith('data:')).slice(5) : raw
  const parsed = JSON.parse(body)
  if (parsed.error) throw new Error(`${method}: ${JSON.stringify(parsed.error)}`)
  return parsed.result
}

async function callTool(name, args) {
  const r = await rpc('tools/call', { name, arguments: args })
  const block = r.content?.[0]
  if (!block) throw new Error(`${name}: empty result`)
  if (block.type === 'image') return { image: block }
  return { text: block.text }
}

function decodeEscapes(s) {
  return s.replace(/&(lt|gt|amp);/g, (m) => ({ '&lt;': '<', '&gt;': '>', '&amp;': '&' }[m]))
}

function unwrap(text) {
  const open = text.indexOf('>')
  const body = text.slice(open + 1, text.indexOf('</untrusted-project-content>'))
  return decodeEscapes(body.startsWith('\n') ? body.slice(1) : body)
}

async function readText(project, file) {
  const parts = []
  let offset = 1
  for (;;) {
    const { text } = await callTool('read_file', { project_id: project, path: file, offset, limit: WINDOW })
    if (text.startsWith('read_file:')) throw new Error(`${file}: ${text.slice(0, 160)}`)
    const m = text.match(/etag="([^"]+)"[^>]*lines="(\d+)-(\d+)" total_lines="(\d+)"/)
    if (!m) throw new Error(`${file}: unparsable wrapper: ${text.slice(0, 200)}`)
    const last = Number(m[3])
    const total = Number(m[4])
    const chunk = unwrap(text)
    if (/truncated_line/.test(text.slice(0, text.indexOf('</untrusted-project-content>')))) {
      throw new Error(`${file}: a single line exceeds the 256 KiB window`)
    }
    parts.push(chunk)
    if (last >= total) break
    offset = last + 1
  }
  // every window carries the file's real lines plus one separator newline the
  // server appends, the last window included; drop one trailing newline per
  // window and the join is byte-exact against the project listing's size.
  return parts.map((p) => (p.endsWith('\n') ? p.slice(0, -1) : p)).join('')
}

async function readBinary(project, file, dest) {
  const { text } = await callTool('render_preview', { project_id: project, path: file })
  const { serve_url } = JSON.parse(text)
  const res = await fetch(serve_url)
  if (!res.ok) throw new Error(`${file}: serve HTTP ${res.status}`)
  const buf = Buffer.from(await res.arrayBuffer())
  fs.mkdirSync(path.dirname(dest), { recursive: true })
  fs.writeFileSync(dest, buf)
  return { bytes: buf.length, sha: crypto.createHash('sha256').update(buf).digest('hex') }
}

function write(dest, data) {
  fs.mkdirSync(path.dirname(dest), { recursive: true })
  fs.writeFileSync(dest, data)
  const h = crypto.createHash('sha256').update(data)
  return { bytes: Buffer.byteLength(data), sha: h.digest('hex') }
}

const project = arg('--project')
const outDir = arg('--out')
if (!project || !outDir) {
  console.error('usage: design_mcp_fetch.mjs --project <uuid> --out <dir>')
  process.exit(2)
}

const listing = JSON.parse((await callTool('list_files', { project_id: project, depth: -1 })).text)
const sizeOf = new Map(listing.map((e) => [e.path, e]))
const report = []

const textFiles = [
  ['Volt Debt - Final v2.dc.html', 'Volt Debt - Final v2.dc.html'],
  ['support.js', 'support.js'],
  ['design_handoff_volt_debt_console/README.md', 'README.md'],
  ['design_handoff_volt_debt_console/KICKOFF_PROMPT.md', 'KICKOFF_PROMPT.md'],
]
for (const [remote, local] of textFiles) {
  const body = await readText(project, remote)
  const dest = path.join(outDir, local)
  const written = write(dest, body)
  const listed = sizeOf.get(remote)?.size
  report.push({ remote, local, ...written, listed, match: listed == null ? 'n/a' : listed === written.bytes ? 'yes' : 'NO' })
  console.log(`${written.bytes} B  ${local}${listed && listed !== written.bytes ? `  (listing says ${listed})` : ''}`)
}

const binaries = [
  ['assets/volt-logo.png', 'assets/volt-logo.png'],
  ['design_handoff_volt_debt_console/screenshots/01-screen.png', 'screenshots/01-screen.png'],
  ['design_handoff_volt_debt_console/screenshots/02-screen.png', 'screenshots/02-screen.png'],
  ['design_handoff_volt_debt_console/screenshots/03-screen.png', 'screenshots/03-screen.png'],
  ['design_handoff_volt_debt_console/screenshots/04-screen.png', 'screenshots/04-screen.png'],
  ['design_handoff_volt_debt_console/screenshots/05-screen.png', 'screenshots/05-screen.png'],
  ['design_handoff_volt_debt_console/screenshots/06-screen.png', 'screenshots/06-screen.png'],
  ['design_handoff_volt_debt_console/screenshots/07-screen.png', 'screenshots/07-screen.png'],
  ['design_handoff_volt_debt_console/screenshots/08-screen.png', 'screenshots/08-screen.png'],
  ['design_handoff_volt_debt_console/screenshots/09-screen.png', 'screenshots/09-screen.png'],
  ['design_handoff_volt_debt_console/screenshots/10-screen.png', 'screenshots/10-screen.png'],
  ['design_handoff_volt_debt_console/screenshots/11-screen.png', 'screenshots/11-screen.png'],
  ['design_handoff_volt_debt_console/screenshots/12-screen.png', 'screenshots/12-screen.png'],
  ['design_handoff_volt_debt_console/screenshots/13-screen.png', 'screenshots/13-screen.png'],
  ['design_handoff_volt_debt_console/screenshots/14-screen.png', 'screenshots/14-screen.png'],
  ['design_handoff_volt_debt_console/screenshots/15-screen.png', 'screenshots/15-screen.png'],
]
if (!process.argv.includes('--no-screenshots')) {
  for (const [remote, local] of binaries) {
    const r = await readBinary(project, remote, path.join(outDir, local))
    report.push({ remote, local, ...r, listed: sizeOf.get(remote)?.size })
    console.log(`${r.bytes} B  ${local}`)
  }
}

const stamp = new Date().toISOString()
const lines = [
  '# Fetch record',
  '',
  `Imported from Claude Design project \`${project}\` on ${stamp}.`,
  '',
  'Re-run with:',
  '',
  '```sh',
  `node scripts/design_mcp_fetch.mjs --project ${project} --out ${outDir}`,
  '```',
  '',
  'Auth: the `designOauth` grant Claude Code stored when `/design-login` was last run',
  '(macOS keychain item `Claude Code-credentials`); override with `DESIGN_MCP_TOKEN`.',
  'Text files are paged through `read_file` (256 KiB cap per call) and rebuilt',
  'byte-exact; binaries come through `render_preview` serve URLs.',
  '',
  '| file | bytes | sha256 | listing |',
  '|---|---|---|---|',
  ...report.map((r) => `| \`${r.local}\` | ${r.bytes} | \`${r.sha.slice(0, 16)}…\` | ${r.listed ?? '—'} |`),
  '',
  'Local edits to these files are not pushed back: the MCP write methods are never called by this script.',
  '',
]
write(path.join(outDir, 'FETCH.md'), lines.join('\n'))
console.log(`\nwrote ${report.length} files to ${outDir}`)

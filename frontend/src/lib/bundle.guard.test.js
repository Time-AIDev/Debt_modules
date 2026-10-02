// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'

/**
 * The browser bundle must load.
 *
 * 2026-09-20: `lib/api.js` re-exported AUTH_REQUIRED_EVENT from lib/events.js and
 * still declared it — a duplicate export. Vitest's transform tolerates that, so 100
 * green tests and the API-only black-box checks all missed it while every browser
 * showed a blank page (`Identifier 'AUTH_REQUIRED_EVENT' has already been declared`).
 * Bundling the real entry with esbuild is the same class of error Vite's production
 * build refuses, in a test that runs with the rest of the suite.
 */
const ENTRY = fileURLToPath(new URL('../../src/main.jsx', import.meta.url))

describe('the browser bundle', () => {
  it('bundles the entry with no module-level error', async () => {
    let errors = []
    try {
      const result = await build({
        entryPoints: [ENTRY],
        bundle: true,
        write: false,
        logLevel: 'silent',
        format: 'esm',
        jsx: 'automatic',
        loader: {
          '.css': 'empty',
          '.png': 'dataurl', '.jpg': 'dataurl', '.jpeg': 'dataurl',
          '.svg': 'dataurl', '.webp': 'dataurl', '.woff2': 'dataurl',
        },
      })
      errors = result.errors || []
    } catch (e) {
      errors = e.errors || [{ text: String(e) }]
    }
    expect(errors.map((e) => e.text)).toEqual([])
  }, 30000)
})

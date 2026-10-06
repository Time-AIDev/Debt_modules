import assert from 'node:assert/strict'
import { test } from 'node:test'
import { safeClose } from '../../scripts/browser_support.mjs'

test('safeClose calls the page close method once and tolerates an already closed page', async () => {
  let calls = 0
  await safeClose({ close: async () => { calls += 1 } })
  assert.equal(calls, 1)
  await safeClose({ close: async () => { throw new Error('already closed') } })
  await safeClose(null)
})

/** Closing a failed browser page must terminate; one close attempt is enough. */
export async function safeClose(page) {
  try { await page?.close() } catch { /* the browser may already have closed it */ }
}

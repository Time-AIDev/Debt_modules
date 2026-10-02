/** Hand a served file (CSV text or Blob) to the browser. Presentation only. */
export function downloadText(filename, text) {
  const csv = String(text || '').replace(/^\ufeff+/, '')
  const blob = new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8' })
  downloadBlob(filename, blob)
}

export function downloadBlob(filename, blob) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename || 'export'
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

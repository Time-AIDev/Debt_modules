export const ACTIVE_RUN_STATES = new Set([
  'queued', 'uploading', 'parsing', 'scanning', 'applying', 'cancel_requested',
  // Compatibility with operation runs created by an older staging revision.
  'running',
])

export const isRunActive = (run) => !!run && ACTIVE_RUN_STATES.has(run.state)

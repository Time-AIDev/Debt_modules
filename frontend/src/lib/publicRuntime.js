import { useSyncExternalStore } from 'react'

let runtime = { environment: 'unknown', data_mode: 'unknown' }
const listeners = new Set()
export function setPublicRuntime(value) {
  runtime = {
    environment: ['production', 'staging', 'development', 'local'].includes(value?.environment) ? value.environment : 'unknown',
    data_mode: ['shared', 'fixtures'].includes(value?.data_mode) ? value.data_mode : 'unknown',
  }
  listeners.forEach((listener) => listener())
}
export function usePublicRuntime() {
  return useSyncExternalStore((listener) => { listeners.add(listener); return () => listeners.delete(listener) }, () => runtime)
}

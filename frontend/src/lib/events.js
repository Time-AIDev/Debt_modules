// The window events the app talks to itself with. Kept out of lib/api.js so a test
// that mocks the transport wholesale cannot break a component that only listens.
export const CHANGED_EVENT = 'volt:changed'
export const AUTH_REQUIRED_EVENT = 'volt:auth-required'
export const DATA_EPOCH_EVENT = 'volt:data-epoch'
export const IMPORT_REFRESHED_EVENT = 'volt:import-refreshed'

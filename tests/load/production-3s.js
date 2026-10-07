// User-approved latency policy, 2026-10-07. Historical traffic/payload is unchanged.
import historical, { options as baselineOptions, handleSummary as baselineSummary } from './production.js';

export default historical;
export const handleSummary = baselineSummary;
export const options = { ...baselineOptions, thresholds: {
  ...baselineOptions.thresholds,
  business_read_ms: ['p(95)<3000'],
  business_write_ms: ['p(95)<3000'],
} };

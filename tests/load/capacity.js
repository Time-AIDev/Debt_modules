// Additional paged UI scenario. The complete historical workload still runs.
import http from 'k6/http';
import { check } from 'k6';
import { Trend, Rate } from 'k6/metrics';
import { SharedArray } from 'k6/data';
import historical, { options as originalOptions } from './production-3s.js';

const actors = new SharedArray('capacity actors', () => JSON.parse(open(__ENV.TOKENS_FILE)));
const dataset = JSON.parse(open(__ENV.DATASET_FILE));
const pageTime = new Trend('capacity_page_ms', true);
const pageErrors = new Rate('capacity_page_errors');
export const options = { ...originalOptions, thresholds: {
  ...originalOptions.thresholds, capacity_page_ms: ['p(95)<3000'], capacity_page_errors: ['rate<0.01'],
} };

export default function () {
  historical();
  const actor = actors[(__VU - 1) % actors.length];
  const response = http.get(`${__ENV.BASE_URL}/api/v1/today?limit=50&entity=SPV`, {
    headers: { Authorization: `Bearer ${actor.token}` }, timeout: '20s', tags: { name: 'today_paged' },
  });
  pageTime.add(response.timings.duration);
  let valid = response.status === 200 && (response.headers['Content-Type'] || '').includes('application/json');
  if (valid) {
    const body = response.json();
    valid = Array.isArray(body.items) && body.items.length === Math.min(50, dataset.customers)
      && body.meta.total === dataset.customers && body.page?.returned === body.items.length
      && Object.values(body.meta.counts_by_tier || {}).reduce((sum, count) => sum + count, 0) === dataset.customers;
  }
  check(valid, { 'paged Today preserves exact full-desk totals': value => value === true });
  pageErrors.add(!valid);
}

export function handleSummary(data) {
  return { [__ENV.SUMMARY_FILE || 'summary.json']: JSON.stringify(data, null, 2),
    stdout: `Completed ${__ENV.RUN_ID || 'capacity'}; machine-readable results saved.\n` };
}

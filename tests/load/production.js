import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';
import { SharedArray } from 'k6/data';

const users = new SharedArray('synthetic users', () => JSON.parse(open(__ENV.TOKENS_FILE)));
const dataset = JSON.parse(open(__ENV.DATASET_FILE));
const base = __ENV.BASE_URL || 'http://127.0.0.1:18081';
const errors = new Rate('business_errors');
const reads = new Trend('business_read_ms', true);
const writes = new Trend('business_write_ms', true);
const conflicts = new Counter('state_conflicts');
const replayFailures = new Rate('idempotency_replay_errors');

export const options = {
  scenarios: { interactive: { executor: 'constant-vus', vus: Number(__ENV.VUS || 10),
    duration: __ENV.DURATION || '120s', gracefulStop: '30s' } },
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  thresholds: {
    business_errors: ['rate<0.01'], business_read_ms: ['p(95)<2000'],
    business_write_ms: ['p(95)<2000'], idempotency_replay_errors: ['rate==0'],
    checks: ['rate>0.99'],
  },
};

function request(path, headers, name) {
  const response = http.get(base + path, { headers, tags: { name }, timeout: '20s' });
  reads.add(response.timings.duration, { name });
  const valid = check(response, { 'business read returns JSON 200': r => r.status === 200 && (r.headers['Content-Type'] || '').includes('application/json') });
  let semantic = valid;
  if (valid) {
    const body = response.json();
    if (name === 'workbook') semantic = Array.isArray(body.rows) && body.rows.length === Math.min(50, dataset.customers) && body.meta.total === dataset.customers;
    else if (name === 'today') semantic = Array.isArray(body.items) && body.items.length === dataset.customers;
    else if (name.startsWith('case')) semantic = body.customer?.uid === path.split('/').pop();
    else if (name === 'monthly') semantic = Array.isArray(body.months);
    check(semantic, { 'business response matches synthetic dataset': value => value === true });
  }
  errors.add(!semantic, { name });
  return response;
}

export default function () {
  const actor = users[(__VU - 1) % users.length];
  const headers = { Authorization: `Bearer ${actor.token}` };
  const choice = (__ITER + __VU) % 10;
  if (choice < 4) request('/api/v1/workbook?limit=50', headers, 'workbook');
  else if (choice < 7) request('/api/v1/today', headers, 'today');
  else if (choice < 9) request(`/api/v1/cases/by-customer/${dataset.customer_uids[(__ITER + __VU) % dataset.customer_uids.length]}`, headers, 'case');
  else request('/api/v1/reports/monthly', headers, 'monthly');

  if (__ITER % 5 === 0) {
    const customer = dataset.customer_uids[(__ITER + __VU) % dataset.customer_uids.length];
    const path = `/api/v1/cases/by-customer/${customer}/notes`;
    const state = request(`/api/v1/cases/by-customer/${customer}`, headers, 'case_before_write');
    const key = `${__ENV.RUN_ID || 'load'}-${__VU}-${__ITER}`;
    const writeHeaders = { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': key };
    if (state.headers['X-Volt-State-Version']) writeHeaders['If-Match'] = state.headers['X-Volt-State-Version'];
    const payload = JSON.stringify({ text: `Synthetic k6 note ${key}` });
    let response = http.post(base + path, payload, { headers: writeHeaders, tags: { name: 'case_note_write' }, timeout: '20s' });
    if (response.status === 409) {
      conflicts.add(1);
      const latest = request(`/api/v1/cases/by-customer/${customer}`, headers, 'case_refresh');
      writeHeaders['If-Match'] = latest.headers['X-Volt-State-Version'];
      response = http.post(base + path, payload, { headers: writeHeaders, tags: { name: 'case_note_write_retry' }, timeout: '20s' });
    }
    writes.add(response.timings.duration);
    const valid = check(response, { 'case note commits or explicitly conflicts': r => r.status === 201 || r.status === 409 });
    errors.add(!valid);
    if (response.status === 201) {
      const replay = http.post(base + path, payload, { headers: writeHeaders, tags: { name: 'case_note_replay' }, timeout: '20s' });
      const identical = check(replay, { 'idempotency retry returns identical response': r => r.status === 201 && r.body === response.body });
      replayFailures.add(!identical);
    }
  }
  sleep(Number(__ENV.THINK_SECONDS || 1));
}

export function handleSummary(data) {
  return { [__ENV.SUMMARY_FILE || 'summary.json']: JSON.stringify(data, null, 2),
    stdout: `Completed ${__ENV.RUN_ID || 'load'}; machine-readable results saved.\n` };
}

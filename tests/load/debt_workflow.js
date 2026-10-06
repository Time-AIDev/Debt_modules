// Supplemental real Debt mutation flow; historical production.js is unchanged.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';
import { SharedArray } from 'k6/data';
const actors = new SharedArray('debt workflow actors', () => JSON.parse(open(__ENV.TOKENS_FILE)));
const dataset = JSON.parse(open(__ENV.DATASET_FILE));
const base = __ENV.BASE_URL;
const reads = new Trend('business_read_ms', true);
const writes = new Trend('business_write_ms', true);
const actionTime = new Trend('complete_action_ms', true);
const failures = new Rate('business_errors');
const replays = new Rate('idempotency_replay_errors');
const conflicts = new Counter('expected_state_conflicts');
const committed = new Counter('debt_mutations_committed');
export const options = {
  scenarios: { debt_workflow: { executor: 'constant-vus', vus: Number(__ENV.VUS || 10),
    duration: __ENV.DURATION || '120s', gracefulStop: '30s' } },
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  thresholds: { business_read_ms: ['p(95)<2000'], business_write_ms: ['p(95)<2000'],
    complete_action_ms: ['p(95)<2000'], business_errors: ['rate<0.01'],
    checks: ['rate>0.99'], idempotency_replay_errors: ['rate==0'], debt_mutations_committed: ['count>0'] },
};

function headers(actor) { return { Authorization: `Bearer ${actor.token}` }; }
function readCase(actor, uid) {
  const r = http.get(`${base}/api/v1/cases/by-customer/${uid}`, { headers: headers(actor), timeout: '20s', tags: { name: 'debt_case' } });
  reads.add(r.timings.duration);
  const valid = check(r, { 'real-flow case read succeeds': response => response.status === 200 });
  failures.add(!valid);
  return valid ? { response: r, body: r.json() } : null;
}

function act(actor, uid, suffix, payload, name, expectedStatus) {
  const started = Date.now();
  let state = readCase(actor, uid);
  if (!state) { actionTime.add(Date.now() - started); return null; }
  const path = suffix.startsWith('/api/') ? suffix : `/api/v1/cases/by-customer/${uid}/${suffix}`;
  const key = `${__ENV.RUN_ID}-debt-${__VU}-${__ITER}-${name}`;
  const hs = { ...headers(actor), 'Content-Type': 'application/json', 'Idempotency-Key': key,
    'If-Match': state.response.headers['X-Volt-Case-Version'] || state.response.headers['X-Volt-State-Version'] };
  const wire = JSON.stringify(payload);
  let r = http.post(base + path, wire, { headers: hs, timeout: '20s', tags: { name } });
  if (r.status === 409) {
    conflicts.add(1);
    state = readCase(actor, uid);
    if (state) {
      hs['If-Match'] = state.response.headers['X-Volt-Case-Version'] || state.response.headers['X-Volt-State-Version'];
      r = http.post(base + path, wire, { headers: hs, timeout: '20s', tags: { name: name + '_retry' } });
    }
  }
  writes.add(r.timings.duration, { name });
  const success = check(r, { 'Debt mutation actually commits': response => response.status === expectedStatus });
  failures.add(!success);
  if (!success) { actionTime.add(Date.now() - started); return null; }
  committed.add(1, { name });
  const replay = http.post(base + path, wire, { headers: hs, timeout: '20s', tags: { name: name + '_replay' } });
  const identical = check(replay, { 'Debt mutation replay is identical': response => response.status === expectedStatus && response.body === r.body });
  replays.add(!identical);
  actionTime.add(Date.now() - started, { name });
  return r.json();
}

export function setup() {
  const r = http.get(`${base}/api/v1/today?limit=1`, { headers: headers(actors[0]), timeout: '30s' });
  if (r.status !== 200) throw new Error('Synthetic workflow preflight failed');
  const day = r.json().run.business_date;
  const next = new Date(day + 'T00:00:00Z'); next.setUTCDate(next.getUTCDate() + 1);
  return { businessDate: day, nextDate: next.toISOString().slice(0, 10) };
}

export default function (calendar) {
  const actor = actors[(__VU - 1) % actors.length];
  // Distinct actor/customer partitions keep intentional stale-edit tests separate
  // from throughput. Every repeated action still uses the real server rules.
  const perActor = Math.max(1, Math.floor(dataset.customer_uids.length / actors.length));
  const index = ((__ITER % perActor) * actors.length + (__VU - 1)) % dataset.customer_uids.length;
  const uid = dataset.customer_uids[index];
  const initial = readCase(actor, uid);
  if (!initial) return;
  act(actor, uid, 'next-action', { next_action: 'CALLBACK', next_action_on: calendar.nextDate }, 'next_action', 200);
  act(actor, uid, 'dc-status', { code: initial.body.case.dc_status === 'CONTACT_BACK' ? 'NO_ACTION' : 'CONTACT_BACK',
    reason: 'Synthetic real Debt follow-up' }, 'dc_status', 200);
  act(actor, uid, 'contacts', { result: 'UNREACHABLE_NO_ANSWER', counted: false, not_counted: true,
    next_action: 'CALLBACK', next_action_on: calendar.nextDate, note: 'Synthetic uncounted follow-up' }, 'contact', 201);
  // One explicit PTP lifecycle per customer; preserve escalation/lineage rules.
  if (__ITER < perActor && !initial.body.case.open_ptp_uid) {
    const opened = act(actor, uid, 'contacts', { result: 'REACHED_PTP', counted: false, not_counted: true,
      ptp: { amount: '100.00', date: calendar.nextDate }, note: 'Synthetic payment promise' }, 'ptp_create', 201);
    if (opened?.ptp?.uid) {
      const closed = act(actor, uid, `/api/v1/case-ptps/${opened.ptp.uid}:close`, { outcome: 'BROKEN',
        on: calendar.businessDate, reason: 'Synthetic customer explicitly refused the promise' }, 'ptp_close', 200);
      const proper = check(closed, { 'PTP lifecycle persisted for correct case': value => value?.ptp?.status === 'BROKEN' && value?.ptp?.customer_uid === uid });
      failures.add(!proper);
    }
  }
  const latest = readCase(actor, uid);
  const unchangedMoney = check(latest, { 'Debt contact/PTP edits manufacture no confirmed cash': value => value
    && value.body.work_item?.aggregate_outstanding === initial.body.work_item?.aggregate_outstanding });
  failures.add(!unchangedMoney);
  sleep(Number(__ENV.THINK_SECONDS || 1));
}

export function handleSummary(data) {
  return { [__ENV.SUMMARY_FILE || 'summary.json']: JSON.stringify(data, null, 2),
    stdout: `Completed ${__ENV.RUN_ID}; real Debt workflow results saved.\n` };
}

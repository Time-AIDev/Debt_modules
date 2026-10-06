#!/usr/bin/env python3
"""Run dataflow units or the full regression on an isolated disposable database.

python scripts/test_dataflow.py --unit
python scripts/test_dataflow.py --all --coverage
Artifacts include JUnit, flow results and optional line/branch coverage. Providers
are mocked; production configuration and databases are never used.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def run(cmd, *, cwd=ROOT, env=None, log=None):
    if log:
        with log.open('w') as output:
            return subprocess.run(cmd, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT).returncode
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout.strip()


def junit(path):
    if not path.exists(): return {'missing': True, 'cases': []}
    root = ET.parse(path).getroot()
    cases = [{'name': c.get('name'), 'class': c.get('classname'),
              'status': 'failed' if c.find('failure') is not None or c.find('error') is not None
              else 'skipped' if c.find('skipped') is not None else 'passed'} for c in root.iter('testcase')]
    return {'tests': len(cases), **{s: sum(c['status'] == s for c in cases)
                                   for s in ('passed', 'failed', 'skipped')}, 'cases': cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument('--unit', action='store_true', help='No PostgreSQL; SQL suites are deselected')
    scope.add_argument('--all', action='store_true', help='Include SQL integration/atomicity suites')
    parser.add_argument('--coverage', action='store_true')
    parser.add_argument('--backend-only', action='store_true')
    parser.add_argument('--frontend-only', action='store_true')
    parser.add_argument('--backend-tests', nargs='+', default=['tests'])
    parser.add_argument('--postgres-image', default='postgres:16')
    parser.add_argument('--output', type=Path, default=ROOT/'.test-artifacts/dataflow')
    args = parser.parse_args()
    if args.backend_only and args.frontend_only: parser.error('Choose one backend/frontend filter')
    for selected in args.backend_tests:
        path = (ROOT/'backend'/selected.split('::', 1)[0]).resolve()
        if not path.is_relative_to(ROOT/'backend/tests') or not path.exists():
            parser.error('Backend selection must be under backend/tests')
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output, 0o700)
    plan = json.loads((ROOT/'tests/dataflow/coverage-map.json').read_text())
    for flow in plan['flows']:
        for path in flow['backend'] + flow['frontend']:
            if not (ROOT/path).is_file(): raise SystemExit('Missing flow test: '+path)
    token = uuid.uuid4().hex[:12]
    database_container = 'volt-dataflow-test-db-'+token
    web_image = 'volt-dataflow-test-web:'+token
    env = dict(os.environ, DATABASE_URL='', ENV='dev', AUTH_MODE='off',
               VOLT_SHARED_STATE_ENABLED='false', VOLT_TEST_PG_URL='')
    for key in list(env):
        if key.startswith(('ODOO_', 'PEAK_')): env[key] = ''
    results = {'started_at_utc': datetime.now(timezone.utc).isoformat(),
               'scope': 'all' if args.all else 'unit-and-memory-api-contracts',
               'backend_selection': args.backend_tests,
               'components': [s for s in ('backend','frontend') if not (s == 'backend' and args.frontend_only or s == 'frontend' and args.backend_only)],
               'production_used': False, 'provider_network': 'blocked/mocked', 'commands': {}}
    started_db = False
    try:
        if not args.frontend_only:
            if args.all:
                if not shutil.which('docker'): raise SystemExit('--all requires Docker for isolated PostgreSQL')
                credential = output/'postgres.env'
                password = secrets.token_hex(24)
                credential.write_text('POSTGRES_USER=volt_test\nPOSTGRES_DB=volt_test_dataflow\nPOSTGRES_PASSWORD='+password+'\n')
                credential.chmod(0o600)
                run(['docker','run','-d','--name',database_container,'--label','volt.test.dataflow='+token,
                     '--env-file',str(credential),'--memory','256m','--tmpfs','/var/lib/postgresql/data:size=512m',
                     '-p','127.0.0.1::5432',args.postgres_image])
                started_db = True
                for _ in range(60):
                    ready = subprocess.run(['docker','exec',database_container,'pg_isready','-U','volt_test','-d','volt_test_dataflow'],capture_output=True)
                    if ready.returncode == 0: break
                    time.sleep(1)
                else: raise SystemExit('Isolated PostgreSQL did not become ready')
                info = json.loads(run(['docker','inspect',database_container]))[0]
                binding = info['NetworkSettings']['Ports']['5432/tcp'][0]
                assert binding['HostIp'] == '127.0.0.1'
                env['VOLT_TEST_PG_URL'] = 'postgresql+psycopg://volt_test:'+password+'@127.0.0.1:'+binding['HostPort']+'/volt_test_dataflow'
                results['test_database'] = {'host':'127.0.0.1','database':'volt_test_dataflow','disposable':True}
            cmd = [sys.executable]
            if args.coverage:
                cmd += ['-m','coverage','run','--branch','--source=app','--data-file='+str(output/'.coverage'),'-m','pytest']
            else: cmd += ['-m','pytest']
            cmd += args.backend_tests + ['--junitxml='+str(output/'backend.xml')]
            if not args.all: cmd += ['--dataflow-unit-only']
            results['commands']['backend_exit'] = run(cmd,cwd=ROOT/'backend',env=env,log=output/'backend.log')
            results['backend'] = junit(output/'backend.xml')
            if args.coverage:
                run([sys.executable,'-m','coverage','json','--data-file='+str(output/'.coverage'),'-o',str(output/'backend-coverage.json')],cwd=ROOT/'backend')
                run([sys.executable,'-m','coverage','html','--data-file='+str(output/'.coverage'),'-d',str(output/'coverage-html')],cwd=ROOT/'backend')
                results['coverage'] = json.loads((output/'backend-coverage.json').read_text())['totals']
        if not args.backend_only:
            if shutil.which('npm'):
                cmd = ['npm','test','--','--reporter=default','--reporter=junit','--outputFile='+str(output/'frontend.xml')]
                results['commands']['frontend_exit'] = run(cmd,cwd=ROOT/'frontend',env=env,log=output/'frontend.log')
            elif shutil.which('docker'):
                build = run(['docker','build','--target','build','-t',web_image,'-f','frontend/Dockerfile','frontend'],log=output/'frontend-build.log')
                if build: results['commands']['frontend_exit'] = build
                else:
                    results['commands']['frontend_exit'] = run(['docker','run','--rm','--network','none','--memory','768m',
                        '-v',str(output)+':/test-artifacts',web_image,'npm','test','--','--reporter=default','--reporter=junit',
                        '--outputFile=/test-artifacts/frontend.xml'],log=output/'frontend.log')
            else: raise SystemExit('Frontend tests require npm or Docker')
            results['frontend'] = junit(output/'frontend.xml')
    finally:
        if started_db:
            subprocess.run(['docker','rm','-f','-v',database_container],capture_output=True)
        if shutil.which('docker'):
            subprocess.run(['docker','image','rm',web_image],capture_output=True)
        (output/'postgres.env').unlink(missing_ok=True)
        results['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        results['flows'] = []
        for flow in plan['flows']:
            selected = []
            for domain in ('backend','frontend'):
                for case in results.get(domain,{}).get('cases',[]):
                    if domain == 'backend':
                        match = False
                        for p in flow[domain]:
                            prefix = p.removeprefix('backend/').removesuffix('.py').replace('/','.')
                            file_matches = case['class'] == prefix or case['class'].startswith(prefix+'.')
                            allowed = flow.get('backend_cases', {}).get(p)
                            if file_matches and (allowed is None or case['name'].split('[', 1)[0] in allowed):
                                match = True
                    else:
                        match = any(Path(p).stem in (case['class'] or '') for p in flow[domain])
                    if match: selected.append(case)
            results['flows'].append({'id':flow['id'],'name':flow['name'],'observed_tests':len(selected),
                                    **{s:sum(c['status']==s for c in selected) for s in ('passed','failed','skipped')}})
        (output/'summary.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps({k:v for k,v in results.items() if k not in ('backend','frontend','flows')},indent=2))
    print('JUnit, logs, coverage and flow results: '+str(output))
    return 1 if not results['commands'] or any(results['commands'].values()) else 0


if __name__ == '__main__': raise SystemExit(main())

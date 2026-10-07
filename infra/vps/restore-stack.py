"""Run a restored application on owned internal Docker resources, with workers paused."""
import io
import json
import os
from pathlib import Path
import secrets
import time
import uuid

from recovery_support import Commands, RecoveryError, docker_env, parse_env, sha

COUNT_SQL = """SELECT 'schema_version',version::bigint FROM app.schema_version WHERE singleton=true
UNION ALL SELECT 'app.business_record',count(*) FROM app.business_record
UNION ALL SELECT 'audit.entry',count(*) FROM audit.entry
UNION ALL SELECT 'app.auth_session',count(*) FROM app.auth_session
UNION ALL SELECT 'app.task_outbox',count(*) FROM app.task_outbox
UNION ALL SELECT 'application_tables',count(*) FROM information_schema.tables
WHERE table_schema IN ('app','audit','landing','records') AND table_type='BASE TABLE';"""
BUSINESS_TABLES = ('app.business_record', 'audit.entry', 'app.task_outbox', 'landing.customer',
                   'landing."order"', 'landing.peak_invoice', 'landing.peak_receipt',
                   'records.payment_claim', 'records.attachment')


class RestoredStack:
    def __init__(self, directory, images, log, commands=None):
        self.directory = Path(directory)
        self.images = images
        self.commands = commands or Commands(log)
        self.token = uuid.uuid4().hex[:12]
        self.prefix = 'volt-cold-restore-'+self.token
        self.network = self.prefix+'-net'
        self.volume = self.prefix+'-db'
        self.created = []
        self.network_created = self.volume_created = False
        self.admin = 'volt_restore_'+self.token

    def create(self, name, arguments):
        full = self.prefix+'-'+name
        self.commands.run(['docker', 'run', '--detach', '--name', full,
                           '--label', 'volt.cold-restore='+self.token,
                           '--network', self.network, '--network-alias', name,
                           *arguments], timeout=180)
        self.created.append(full)
        return full

    def sql(self, query):
        return self.commands.run(['docker', 'exec', '--interactive', self.prefix+'-db', 'psql',
                                  '--username', self.admin, '--dbname', 'debt', '--no-psqlrc',
                                  '--tuples-only', '--no-align', '--field-separator', '\t',
                                  '--set=ON_ERROR_STOP=1'], stdin=io.BytesIO(query.encode()), capture=True)

    def business_fingerprints(self):
        result = {}
        for table in BUSINESS_TABLES:
            value = self.sql("SET statement_timeout='30000'; SELECT count(*),md5(coalesce(string_agg(md5(row_to_json(t)::text),'' ORDER BY md5(row_to_json(t)::text)),'')) FROM "+table+' t;')
            line = value.splitlines()[-1].split('\t')
            result[table] = {'count': int(line[0]), 'fingerprint': line[1]}
        return result

    def retry(self, arguments, timeout=180):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            try:
                return self.commands.run(arguments, capture=True, timeout=10)
            except Exception:
                time.sleep(2)
        raise RecoveryError('Restored application dependency did not become ready')

    def restore_database(self, backup):
        self.commands.run(['docker', 'network', 'create', '--internal', '--label',
                           'volt.cold-restore='+self.token, self.network], timeout=30)
        self.network_created = True
        existing = self.commands.run(['docker', 'volume', 'ls', '--filter', 'name=^'+self.volume+'$',
                                      '--format', '{{.Name}}'], capture=True, timeout=30)
        if existing:
            raise RecoveryError('Recovery resource name already exists')
        self.commands.run(['docker', 'volume', 'create', '--label', 'volt.cold-restore='+self.token, self.volume], timeout=30)
        self.volume_created = True
        docker_env(self.directory/'db.env', {'POSTGRES_USER': self.admin, 'POSTGRES_DB': 'postgres',
                                            'POSTGRES_PASSWORD': secrets.token_hex(32)})
        db = self.create('db', ['--memory', '512m', '--env-file', str(self.directory/'db.env'),
                                '--mount', 'type=volume,src='+self.volume+',dst=/var/lib/postgresql/data', self.images['db']])
        self.retry(['docker', 'exec', db, 'pg_isready', '--host', '127.0.0.1', '--username', self.admin, '--dbname', 'postgres'])
        with (backup/'globals.sql').open('rb') as file:
            self.commands.run(['docker', 'exec', '--interactive', db, 'psql', '--username', self.admin,
                               '--dbname', 'postgres', '--no-psqlrc', '--set=ON_ERROR_STOP=1'], stdin=file)
        self.commands.run(['docker', 'exec', db, 'createdb', '--username', self.admin, '--owner', 'debt_migrate', 'debt'])
        with (backup/'database.dump').open('rb') as file:
            self.commands.run(['docker', 'exec', '--interactive', db, 'pg_restore', '--username', self.admin,
                               '--dbname', 'debt', '--exit-on-error'], stdin=file, timeout=1800)
        counts = {key: int(value) for key, value in (line.split('\t') for line in self.sql(COUNT_SQL).splitlines())}
        expected = {key: int(value) for key, value in (line.split('\t') for line in (backup/'database-counts.tsv').read_text().splitlines())}
        if not expected or any(counts.get(key) != value for key, value in expected.items()):
            raise RecoveryError('Restored database counts differ from backup metadata')
        if int(self.sql('SHOW server_version_num;')) // 10000 != 16:
            raise RecoveryError('Restored database is not PostgreSQL 16')
        return counts

    def worker_probe_arguments(self, api_args, native):
        if native:
            return ([*api_args[:-1], '--memory', '1800m', api_args[-1],
                     'python', '-m', 'app.local_worker', '--probe-only'],
                    {'kind': 'native', 'sha256': None})
        helper = self.directory/'worker-probe.py'
        helper.write_bytes((Path(__file__).resolve().parent/'recovery_worker_probe.py').read_bytes())
        # The containing recovery directory is private. The captured API UID10001
        # needs read access to this code-only single-file mount.
        helper.chmod(0o644)
        return ([*api_args[:-1], '--memory', '1800m',
                 '--volume', str(helper)+':/app/recovery-worker-probe.py:ro',
                 api_args[-1], 'python', '/app/recovery-worker-probe.py'],
                {'kind': 'compatibility_heartbeat', 'sha256': sha(helper)})

    def application(self, config, objects, signatures, revision):
        # Older captured releases lack --probe-only and would silently run jobs
        # if given that flag. Use a reviewed heartbeat-only entry for those images.
        probe = self.commands.run(['docker', 'run', '--rm', '--network', 'none', self.images['api'],
                                  'python', '-c', "from pathlib import Path; print('--probe-only' in Path('/app/app/local_worker.py').read_text())"], capture=True)
        if probe not in ('True', 'False'):
            raise RecoveryError('Recovery image probe capability could not be verified')
        compatibility_probe = probe == 'False'
        runtime = parse_env(config/'api.env')
        runtime_password = secrets.token_hex(32)
        self.sql("ALTER ROLE debt_api WITH LOGIN PASSWORD '"+runtime_password+"';")
        # Retain the original configuration separately, and use isolated credentials at runtime.
        for key in list(runtime):
            if key.startswith(('ODOO_', 'PEAK_')) or key in ('GOOGLE_APPLICATION_CREDENTIALS', 'SCANNER_URL'):
                runtime[key] = ''
        runtime.update(ENV='stg', DEPLOYMENT_ENV='stg', AUTH_MODE='on', AUTH_ALLOW_TEST_ACCOUNTS='false',
                       AUTH_SESSION_SECRET=secrets.token_hex(48), PROD_GO_LIVE_ENABLED='false',
                       PEAK_OUTBOUND_ENABLED='false', CRM_WON_ONLY='true', VOLT_SHARED_STATE_ENABLED='true',
                       VOLT_RECOVERY_READ_ONLY='true',
                       TASK_QUEUE_BACKEND='postgres', DATABASE_URL='postgresql+psycopg://debt_api:'+runtime_password+'@db/debt',
                       OBJECT_STORAGE_BACKEND='filesystem', OBJECT_STORAGE_ROOT='/private-objects',
                       CLAMAV_HOST='scanner', CLAMAV_PORT='3310', REQUIRE_DEPENDENCY_READINESS='true')
        runtime.pop('VOLT_BUSINESS_DATE', None)
        docker_env(self.directory/'api.env', runtime)
        objects.mkdir(mode=0o700, exist_ok=True)
        for entry in [objects, *objects.rglob('*')]:
            os.chown(entry, 10001, 10001)
        scanner_config = self.directory/'clamd.conf'
        scanner_config.write_text('DatabaseDirectory /var/lib/clamav\nTCPSocket 3310\nTCPAddr 0.0.0.0\nForeground yes\nUser clamav\nLogFile /tmp/clamd.log\nLocalSocket /tmp/clamd.sock\n')
        scanner_config.chmod(0o600)
        self.create('scanner', ['--memory', '3g', '--volume', str(signatures)+':/var/lib/clamav',
                                '--volume', str(scanner_config)+':/etc/clamav/recovery.conf:ro',
                                '--entrypoint', 'sh', self.images['scanner'], '-c',
                                'chown -R clamav:clamav /var/lib/clamav; exec clamd --foreground=true --config-file=/etc/clamav/recovery.conf'])
        api_args = ['--memory', '1g', '--env-file', str(self.directory/'api.env'),
                    '--volume', str(objects)+':/private-objects', '--security-opt', 'no-new-privileges:true', self.images['api']]
        worker_args, worker_probe = self.worker_probe_arguments(api_args, not compatibility_probe)
        worker = self.create('worker', worker_args)
        api = self.create('api', api_args)
        self.retry(['docker', 'exec', worker, 'python', '-m', 'app.local_worker', '--healthcheck'], timeout=300)
        check = "import json,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8080/readyz',timeout=3); assert r.status==200 and json.load(r)['status']=='ready'; print('ready')"
        self.retry(['docker', 'exec', api, 'python', '-c', check], timeout=420)
        web = self.create('web', ['--memory', '128m', '--env', 'ENV=stg', '--env', 'API_BASE_URL=/api', self.images['web']])
        self.retry(['docker', 'exec', web, 'wget', '-q', '-T', '3', '-O', '/dev/null', 'http://127.0.0.1:8080/healthz'])
        edge_config = self.directory/'Caddyfile'
        edge_config.write_text('http://:8080 {\n handle /api/* {\n uri strip_prefix /api\n reverse_proxy api:8080\n }\n handle {\n reverse_proxy web:8080\n }\n}\n')
        edge_config.chmod(0o600)
        self.create('edge', ['--memory', '128m', '--volume', str(edge_config)+':/etc/caddy/Caddyfile:ro', self.images['edge']])
        edge_check = "import json,urllib.request; r=urllib.request.urlopen('http://edge:8080/api/readyz',timeout=3); assert r.status==200 and json.load(r)['status']=='ready'; print('ready')"
        self.retry(['docker', 'exec', api, 'python', '-c', edge_check])
        auth_check = "import json,urllib.request; r=json.load(urllib.request.urlopen('http://edge:8080/api/v1/auth/config',timeout=3)); assert r['mode']=='on' and r['password_enabled'] is False and r.get('google_client_id'); print('auth-on')"
        self.retry(['docker', 'exec', api, 'python', '-c', auth_check])
        # Inspected labels/images, running state and OOM status are observable proof.
        inspected = json.loads(self.commands.run(['docker', 'inspect', *self.created], capture=True, timeout=30))
        if any(not item['State']['Running'] or item['State'].get('OOMKilled') for item in inspected):
            raise RecoveryError('A restored service stopped or was OOM killed')
        if any(item.get('Config', {}).get('Labels', {}).get('volt.cold-restore') != self.token for item in inspected):
            raise RecoveryError('Restored services do not belong to this recovery')
        if any(item.get('HostConfig', {}).get('PortBindings') for item in inspected):
            raise RecoveryError('Recovery services must not publish ports')
        for item in inspected:
            name = item['Name'].rsplit('-', 1)[-1]
            if item['Image'] != self.images['api' if name == 'worker' else name]:
                raise RecoveryError('Restored service image differs from its release')
        network = json.loads(self.commands.run(['docker', 'network', 'inspect', self.network], capture=True, timeout=30))[0]
        if network.get('Internal') is not True:
            raise RecoveryError('Recovery network is not isolated')
        return {'api': 'ready', 'worker': 'probe-only-healthy', 'scanner': 'ping-via-readiness',
                'web': 'ready', 'edge': 'isolated-proxy-ready', 'network': 'internal', 'published_ports': [],
                'worker_probe': worker_probe['kind'], 'worker_probe_sha256': worker_probe['sha256']}

    def cleanup(self):
        errors = []
        for container in reversed(self.created):
            try:
                label = self.commands.run(['docker', 'inspect', '--format', '{{index .Config.Labels "volt.cold-restore"}}', container], capture=True, timeout=30)
                if label != self.token:
                    raise RecoveryError('Refusing to remove an unowned recovery container')
                self.commands.run(['docker', 'rm', '--force', '--volumes', container], timeout=90)
            except Exception:
                errors.append('container')
        for kind, name, created in [('volume', self.volume, self.volume_created), ('network', self.network, self.network_created)]:
            if not created:
                continue
            try:
                label = self.commands.run(['docker', kind, 'inspect', '--format', '{{index .Labels "volt.cold-restore"}}', name], capture=True, timeout=30)
                if label != self.token:
                    raise RecoveryError('Refusing to remove an unowned recovery resource')
                self.commands.run(['docker', kind, 'rm', name], timeout=60)
            except Exception:
                errors.append(kind)
        if errors:
            raise RecoveryError('Owned recovery resource cleanup was incomplete')

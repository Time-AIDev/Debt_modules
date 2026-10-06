"""Canonical-image labels and legacy password handoff, with external calls mocked."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('review_runtime', ROOT / 'scripts/run_runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
REVISION = 'a' * 40
IMAGE = 'sha256:' + 'b' * 64
FINGERPRINT = 'c' * 16


class ImageLabels(unittest.TestCase):
    def exercise(self, cached_label, dirty=False):
        builds, inspections = [], []
        expected = REVISION + '-dirty-' + FINGERPRINT if dirty else REVISION
        def command(args, capture=False):
            if args[:2] == ['git', 'rev-parse']:
                return REVISION + '\n'
            if args[:2] == ['git', 'status']:
                return ' M backend/app/main.py\n' if dirty else ''
            builds.append(args)
            return ''
        def inspect(args, **kwargs):
            inspections.append(args)
            # Each build's following inspect reports the label actually requested.
            just_built = bool(builds and args[3] in builds[-1])
            label = expected if just_built else cached_label
            return SimpleNamespace(returncode=0, stdout=IMAGE + ' ' + label + '\n')
        with patch.object(runtime, 'run', command), patch.object(runtime, 'source_fingerprint', return_value=FINGERPRINT), patch.object(runtime.subprocess, 'run', inspect):
            images = runtime.images(SimpleNamespace(api_image=None, web_image=None), True)
        self.assertEqual(images, (IMAGE, IMAGE))
        return builds, inspections, expected

    def test_unknown_or_stale_cached_labels_are_rebuilt_with_commit_binding(self):
        for stale in ('unknown', 'd' * 40, '<no value>'):
            with self.subTest(stale=stale):
                builds, inspections, expected = self.exercise(stale)
                self.assertEqual(len(builds), 2)
                self.assertTrue(all('VOLT_GIT_REVISION=' + expected in args for args in builds))
                self.assertTrue(all(REVISION[:12] in args[3] for args in inspections))

    def test_matching_committed_images_are_reused(self):
        builds, inspections, _ = self.exercise(REVISION)
        self.assertEqual(builds, [])
        self.assertEqual(len(inspections), 2)

    def test_dirty_dev_source_remains_runnable_without_promotable_commit_label(self):
        builds, inspections, expected = self.exercise(REVISION, dirty=True)
        self.assertEqual(len(builds), 2)
        self.assertIn('-dirty-', expected)
        self.assertNotEqual(expected, REVISION)
        self.assertTrue(all(args[3].endswith('-dirty') for args in inspections))
        self.assertTrue(all('VOLT_GIT_REVISION=' + expected in args for args in builds))


class PasswordHandoff(unittest.TestCase):
    def test_supplied_and_generated_credentials_are_only_in_private_handoff(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / 'scripts').mkdir()
            shutil.copy(ROOT / 'scripts/staging_accounts.sh', base / 'scripts/staging_accounts.sh')
            binary = base / 'backend/.venv/bin/python'
            binary.parent.mkdir(parents=True)
            binary.write_text('''#!%s
import hashlib,json,os,secrets,sys
if sys.argv[1] == '-':
    exec(sys.stdin.read(), {'__name__':'__main__'})
elif 'officers.registry' in sys.argv[2]:
    accounts={}
    for role in ('OFFICER','SUPERVISOR','MANAGER','OWNER'):
        accounts[role.lower()]={'role':role,'officer':role.lower(),'hash':hashlib.sha256(os.environ.get('AUTH_TEST_PW_'+role,'').encode()).hexdigest()}
    print(json.dumps(accounts))
else:
    exec(sys.argv[2])
''' % sys.executable)
            binary.chmod(0o700)
            commands = base / 'bin'
            commands.mkdir()
            gcloud = commands / 'gcloud'
            gcloud.write_text('''#!%s
import os,sys
if sys.argv[1:3]==['auth','list']:
    print('mock-active-account')
else:
    open(os.environ['MOCK_HASH_FILE'],'w').write(sys.stdin.read())
''' % sys.executable)
            gcloud.chmod(0o700)
            home = base / 'home'
            home.mkdir()
            env = dict(os.environ, PROJECT='isolated-mock-project', HOME=str(home),
                       PATH=str(commands) + os.pathsep + os.environ.get('PATH',''),
                       AUTH_TEST_PASSWORD_OFFICER='provided-secret-that-must-not-be-logged',
                       MOCK_HASH_FILE=str(base / 'sent-hashes.json'))
            for key in ('AUTH_TEST_PASSWORD','AUTH_TEST_PASSWORD_SUPERVISOR','AUTH_TEST_PASSWORD_MANAGER','AUTH_TEST_PASSWORD_OWNER','VOLT_TEST_HANDOFF_DIR'):
                env.pop(key, None)
            result = subprocess.run(['bash',str(base / 'scripts/staging_accounts.sh'),'--apply'],env=env,text=True,capture_output=True,check=True)
            files = list((home / '.volt-test-account-handoff').glob('*.json'))
            self.assertEqual(len(files),1)
            data = json.loads(files[0].read_text())
            self.assertEqual(stat.S_IMODE(files[0].stat().st_mode),0o600)
            self.assertEqual(stat.S_IMODE(files[0].parent.stat().st_mode),0o700)
            self.assertEqual(data['accounts'][0]['password'],env['AUTH_TEST_PASSWORD_OFFICER'])
            combined = result.stdout + result.stderr
            hashes = (base / 'sent-hashes.json').read_text()
            self.assertIn(str(files[0]),combined)
            for account in data['accounts']:
                self.assertNotIn(account['password'],combined)
                self.assertNotIn(account['password'],hashes)
            self.assertEqual(len(json.loads(hashes)),4)
            unsafe = base / 'existing-shared-directory'
            unsafe.mkdir(mode=0o755)
            unsafe.chmod(0o755)
            (base / 'sent-hashes.json').unlink()
            failed = subprocess.run(['bash',str(base / 'scripts/staging_accounts.sh'),'--apply'],
                                    env=dict(env, VOLT_TEST_HANDOFF_DIR=str(unsafe)), text=True, capture_output=True)
            self.assertNotEqual(failed.returncode,0)
            self.assertEqual(stat.S_IMODE(unsafe.stat().st_mode),0o755)
            self.assertFalse((base / 'sent-hashes.json').exists())
            self.assertNotIn(env['AUTH_TEST_PASSWORD_OFFICER'],failed.stdout+failed.stderr)


if __name__ == '__main__':
    unittest.main()
